#!/usr/bin/env python3
"""微博评论情感分类器 — 基于 AI 模型逐条判断，输出 EXCEL 报告。"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

# 每批发送给 AI 的评论数
BATCH_SIZE = 40

SYSTEM_PROMPT = """你是一个中文微博评论情感分析助手。对每条评论判断情感倾向。

分类标准：
- "正面"：表达喜欢、感谢、期待、满意、赞扬、开心、支持、感动等积极情绪
- "负面"：表达讨厌、抱怨、担忧、愤怒、不满、讽刺、失望、质疑等消极情绪
- "中性"：纯信息询问、客观事实陈述、中性问候、无明显情感倾向

情感强度 score 范围：-1.0（极负面）到 1.0（极正面），0 表示完全中性。

注意：
- 讽刺、反语应判为负面（如"这天气预报真准"实际表达不准时）
- 纯"晚安""早上好""你好"等问候语 → 中性
- 仅问句无情绪词 → 中性
- 表情符号缺失不影响判断，根据文字语义判断

严格只返回 JSON 数组，格式：
[{"index": 序号, "sentiment": "正面"|"负面"|"中性", "score": 数值}]"""


def clean_text(text: str) -> str:
    """清洗评论内容：去除 URL、@提及、多余空白。"""
    text = text or ""
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"@[^\s@：:]+[：:]?\s*", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def classify_batch(client, batch_items: list[tuple[int, str]], model: str) -> list[dict]:
    """批量分类评论，返回 [{index, sentiment, score}]。"""
    lines = "\n".join(f"[{idx}] {text}" for idx, text in batch_items)

    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"请对以下评论逐一进行情感分类：\n\n{lines}"}],
    )

    text = response.content[0].text.strip()
    # 去除可能的 markdown 代码块包裹
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    return json.loads(text)


def analyze_file(
    input_path: str,
    output_path: str = None,
    api_key: str = None,
    model: str = "claude-sonnet-4-6",
) -> str:
    """主分析流程：读取 JSON → AI 逐条分类 → 写 EXCEL。"""
    from anthropic import Anthropic

    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("请设置 ANTHROPIC_API_KEY 环境变量或通过 --api-key 参数提供")

    client = Anthropic(api_key=api_key)

    input_path = Path(input_path)
    if not input_path.exists():
        raise FileNotFoundError(f"输入文件不存在: {input_path}")

    if output_path is None:
        stem = input_path.stem
        output_path = input_path.with_name(f"{stem}_情感分析.xlsx")
    else:
        output_path = Path(output_path)

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 收集所有评论
    all_comments = []  # [(post_idx, comment_idx, content)]
    for pi, post in enumerate(data):
        for ci, c in enumerate(post.get("comments", [])):
            all_comments.append((pi, ci, c.get("content", "")))

    total = len(all_comments)
    results: dict[tuple[int, int], tuple[str, float]] = {}

    # 分批处理
    for batch_start in range(0, total, BATCH_SIZE):
        batch_end = min(batch_start + BATCH_SIZE, total)
        batch = all_comments[batch_start:batch_end]
        batch_items = [(i, clean_text(content)) for i, (_, _, content) in enumerate(batch)]

        # 过滤空评论（清洗后为空则直接标记中性）
        non_empty = [(i, t) for i, t in batch_items if t]

        print(f"\r分类进度: {batch_end}/{total}", end="", flush=True)

        if non_empty:
            for attempt in range(3):
                try:
                    batch_results = classify_batch(client, non_empty, model)
                    for r in batch_results:
                        idx_in_batch = r["index"]
                        real_idx = batch_start + idx_in_batch
                        pi, ci, _ = all_comments[real_idx]
                        results[(pi, ci)] = (r["sentiment"], r["score"])
                    break
                except Exception as e:
                    if attempt < 2:
                        wait = (attempt + 1) * 2
                        print(f"\n批次 {batch_start}-{batch_end} 失败: {e}, {wait}s 后重试...")
                        time.sleep(wait)
                    else:
                        raise

        # 空评论标记为中性
        empty_indices = set(range(len(batch))) - {i for i, _ in non_empty}
        for i in empty_indices:
            real_idx = batch_start + i
            pi, ci, _ = all_comments[real_idx]
            results[(pi, ci)] = ("中性", 0.0)

        # 速率限制
        if batch_end < total:
            time.sleep(0.3)

    print()  # 换行

    # 构建 EXCEL 数据
    detail_rows = []
    summary_rows = []

    for pi, post in enumerate(data):
        author = post.get("author_nickname", "")
        created = post.get("created_at", "")
        content = post.get("note_text", "")
        like_count = post.get("comments_count_on_post", 0)
        comments = post.get("comments", [])
        total_comment = post.get("total_after_filter", len(comments))

        pos = neg = neu = 0

        for ci, c in enumerate(comments):
            sentiment, score = results.get((pi, ci), ("中性", 0.0))
            if sentiment == "正面":
                pos += 1
            elif sentiment == "负面":
                neg += 1
            else:
                neu += 1

            detail_rows.append({
                "微博作者": author,
                "微博内容": content,
                "评论者": c.get("nickname", ""),
                "评论内容": c.get("content", ""),
                "情感分数": score,
                "情感分类": sentiment,
                "点赞数": c.get("like_count", 0),
            })

        denom = total_comment if total_comment > 0 else 1
        pos_pct = round(pos / denom * 100, 1)
        neg_pct = round(neg / denom * 100, 1)
        neu_pct = round(neu / denom * 100, 1)

        summary_rows.append({
            "微博作者名称": author,
            "发布时间": created,
            "微博内容": content,
            "点赞数": like_count,
            "评论数": total_comment,
            "正面数量": pos,
            "正面占比": f"{pos_pct}%",
            "负面数量": neg,
            "负面占比": f"{neg_pct}%",
            "中性数量": neu,
            "中性占比": f"{neu_pct}%",
        })

    _write_excel(output_path, summary_rows, detail_rows)

    # 统计摘要
    total_pos = sum(1 for r in detail_rows if r["情感分类"] == "正面")
    total_neg = sum(1 for r in detail_rows if r["情感分类"] == "负面")
    total_neu = sum(1 for r in detail_rows if r["情感分类"] == "中性")

    print(f"处理完成: {len(data)} 篇帖子, {total} 条评论")
    print(f"  正面: {total_pos} ({round(total_pos / total * 100, 1)}%)")
    print(f"  负面: {total_neg} ({round(total_neg / total * 100, 1)}%)")
    print(f"  中性: {total_neu} ({round(total_neu / total * 100, 1)}%)")
    print(f"输出文件: {output_path}")

    return str(output_path)


def _write_excel(path: Path, summary_rows: list, detail_rows: list) -> None:
    """写入 EXCEL 文件（汇总 + 明细两个 Sheet）。"""
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill

    wb = Workbook()

    # Sheet 1: 汇总
    ws1 = wb.active
    ws1.title = "汇总"
    s_headers = list(summary_rows[0].keys()) if summary_rows else []
    ws1.append(s_headers)
    for row in summary_rows:
        ws1.append([row.get(h, "") for h in s_headers])

    # Sheet 2: 评论明细
    ws2 = wb.create_sheet("评论明细")
    d_headers = list(detail_rows[0].keys()) if detail_rows else []
    ws2.append(d_headers)
    for row in detail_rows:
        ws2.append([row.get(h, "") for h in d_headers])

    # 样式
    header_font = Font(bold=True, size=11)
    header_fill = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")
    wrap_align = Alignment(wrap_text=True, vertical="center")

    for ws, headers in [(ws1, s_headers), (ws2, d_headers)]:
        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=1, column=col_idx)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center")

        for row in ws.iter_rows(min_row=2, max_row=ws.max_row, max_col=len(headers)):
            for cell in row:
                cell.alignment = wrap_align

        for col_idx in range(1, len(headers) + 1):
            max_width = len(str(headers[col_idx - 1])) * 2
            for row_idx in range(2, ws.max_row + 1):
                val = str(ws.cell(row=row_idx, column=col_idx).value or "")
                width = sum(2 if ord(c) > 127 else 1 for c in val)
                max_width = min(max(max_width, width), 60)
            ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = max_width + 2

    wb.save(path)


def main():
    parser = argparse.ArgumentParser(description="微博评论情感分类器（AI 驱动）")
    parser.add_argument("-i", "--input", required=True, help="微博评论爬虫输出的 JSON 文件路径")
    parser.add_argument("-o", "--output", default=None, help="EXCEL 输出路径（默认在输入文件同目录生成）")
    parser.add_argument("--api-key", default=None, help="Anthropic API Key（默认从 ANTHROPIC_API_KEY 环境变量读取）")
    parser.add_argument("--model", default="claude-sonnet-4-6", help="使用的模型（默认 claude-sonnet-4-6）")
    parser.add_argument("--batch-size", type=int, default=40, help="每批处理的评论数（默认 40）")
    args = parser.parse_args()

    global BATCH_SIZE
    BATCH_SIZE = args.batch_size

    analyze_file(args.input, args.output, args.api_key, args.model)


if __name__ == "__main__":
    main()
