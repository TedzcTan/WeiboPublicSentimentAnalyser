#!/usr/bin/env python3
"""微博评论情感分类器 — Claude AI 直接分析评论内容，无需外部 API。

工作流程：
1. 读取爬虫 JSON → 去重评论 → 输出待分类列表
2. Claude 逐条分析每条评论的情感（正面/负面/中性）
3. 将分类结果填入脚本的 CLASSIFICATIONS 字典
4. 再次运行脚本 → 生成 EXCEL 报告
"""

import argparse
import json
from pathlib import Path

# ============================================================
# 分类结果：comment_id → (情感分类, 情感分数)
# Claude AI 在对话中逐条分析后填入此处，然后重新运行脚本生成 EXCEL
# ============================================================
CLASSIFICATIONS: dict[str, tuple[str, float]] = {}


def deduplicate_comments(data: list) -> list[dict]:
    """按 comment_id 去重，保留首次出现的评论。"""
    seen = set()
    result = []
    for post in data:
        for c in post.get("comments", []):
            cid = c.get("comment_id", "")
            if cid and cid not in seen:
                seen.add(cid)
                result.append(c)
    return result


def print_comments_for_review(comments: list[dict]) -> None:
    """打印所有去重评论，供 Claude 逐条分析。"""
    print(f"\n共 {len(comments)} 条去重评论，请逐条判断情感倾向：\n")
    for i, c in enumerate(comments):
        content = c.get("content", "").strip()
        cid = c.get("comment_id", "")
        nickname = c.get("nickname", "")
        print(f"[{i}] {nickname}: {content}")
        print(f"    comment_id: {cid}")
        print()


def build_classification_dict(comments: list[dict]) -> dict[str, tuple[str, float]]:
    """从 CLASSIFICATIONS 字典构建完整映射，缺失的默认标记为中性。"""
    result = {}
    for c in comments:
        cid = c.get("comment_id", "")
        if cid in CLASSIFICATIONS:
            result[cid] = CLASSIFICATIONS[cid]
        else:
            result[cid] = ("中性", 0.0)
    return result


def write_excel(output_path: Path, data: list, classifications: dict[str, tuple[str, float]]) -> str:
    """写入 EXCEL 文件（汇总 + 明细两个 Sheet）。"""
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill

    wb = Workbook()

    detail_rows = []
    summary_rows = []

    for post in data:
        author = post.get("author_nickname", "")
        created = post.get("created_at", "")
        content = post.get("note_text", "")
        like_count = post.get("comments_count_on_post", 0)
        comments = post.get("comments", [])

        seen_in_post = set()
        unique_comments = []
        for c in comments:
            cid = c.get("comment_id", "")
            if cid not in seen_in_post:
                seen_in_post.add(cid)
                unique_comments.append(c)

        total_comment = len(unique_comments)
        pos = neg = neu = 0

        for c in unique_comments:
            cid = c.get("comment_id", "")
            sentiment, score = classifications.get(cid, ("中性", 0.0))
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
        summary_rows.append({
            "微博作者名称": author,
            "发布时间": created,
            "微博内容": content,
            "点赞数": like_count,
            "评论数": total_comment,
            "正面数量": pos,
            "正面占比": f"{round(pos / denom * 100, 1)}%",
            "负面数量": neg,
            "负面占比": f"{round(neg / denom * 100, 1)}%",
            "中性数量": neu,
            "中性占比": f"{round(neu / denom * 100, 1)}%",
        })

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

    wb.save(output_path)
    return str(output_path)


def main():
    parser = argparse.ArgumentParser(
        description="微博评论情感分类器（Claude AI 直判，无需 API）"
    )
    parser.add_argument("-i", "--input", required=True, help="微博评论爬虫输出的 JSON 文件路径")
    parser.add_argument("-o", "--output", default=None, help="EXCEL 输出路径（默认在输入文件同目录生成）")
    parser.add_argument("--review", action="store_true",
                        help="仅打印去重评论列表，供 Claude 逐条分析（不生成 EXCEL）")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        raise FileNotFoundError(f"输入文件不存在: {input_path}")

    if args.output is None:
        stem = input_path.stem
        output_path = input_path.with_name(f"{stem}_情感分析.xlsx")
    else:
        output_path = Path(args.output)

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    comments = deduplicate_comments(data)

    if args.review:
        print_comments_for_review(comments)
        return

    if not CLASSIFICATIONS:
        print("=" * 60)
        print("CLASSIFICATIONS 字典为空。请按以下步骤操作：")
        print("=" * 60)
        print()
        print("1. 先运行 --review 模式查看所有评论：")
        print(f"   uv run python ../.claude/skills/weibo-sentiment-classifier/scripts/sentiment_classifier.py --input \"{args.input}\" --review")
        print()
        print("2. Claude 逐条分析评论，将结果填入脚本顶部的 CLASSIFICATIONS 字典")
        print("3. 重新运行脚本生成 EXCEL")
        print()
        print(f"共 {len(comments)} 条去重评论待分类。")
        return

    classifications = build_classification_dict(comments)
    out = write_excel(output_path, data, classifications)

    # 统计
    total_pos = sum(1 for v in classifications.values() if v[0] == "正面")
    total_neg = sum(1 for v in classifications.values() if v[0] == "负面")
    total_neu = sum(1 for v in classifications.values() if v[0] == "中性")
    total = len(classifications)

    print(f"处理完成: {len(data)} 篇帖子, {total} 条去重评论")
    print(f"  正面: {total_pos} ({round(total_pos / total * 100, 1)}%)")
    print(f"  负面: {total_neg} ({round(total_neg / total * 100, 1)}%)")
    print(f"  中性: {total_neu} ({round(total_neu / total * 100, 1)}%)")
    print(f"输出文件: {output_path}")


if __name__ == "__main__":
    main()
