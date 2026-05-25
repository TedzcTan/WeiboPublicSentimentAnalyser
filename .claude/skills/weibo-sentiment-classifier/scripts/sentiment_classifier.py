#!/usr/bin/env python3
"""微博评论情感分类器 — 基于本地词典库的置信度加权分类，输出 EXCEL 报告。"""

import argparse
import json
import re
from pathlib import Path

from dict_manager import DictManager

# 全局单例，由 analyze_file 初始化
_dict: DictManager = None


def clean_text(text: str) -> str:
    """清洗评论内容：去除 emoji、URL、@提及、多余空白。"""
    text = text or ""
    text = re.sub(r"https?://\S+", "", text)
    # 中文微博 @提及 通常以冒号或空格结束，避免吃掉后续内容
    text = re.sub(r"@[^\s@：:]+[：:]?\s*", "", text)
    text = re.sub(r"[^一-鿿　-〿＀-￯a-zA-Z0-9,.!?;:\"\'()（）、。！？；：""''【】《》…～\s\-+]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def classify_sentiment(text: str) -> tuple[str, float]:
    """对单条评论进行情感分类，返回 (分类, 情感分)。

    使用词典管理器的置信度权重进行加权评分。
    """
    global _dict
    text = clean_text(text)
    if not text:
        return ("中性", 0.0)

    # 纯问候语 → 中性
    if _dict.is_greeting(text):
        _dict.record_hit(text, "greeting")
        return ("中性", 0.0)

    # 字符级扫描，最长匹配 4 字词
    n = len(text)
    sentiment_hits = []  # (position, is_positive, word)

    positive_words = _dict.get_positive_words()
    negative_words = _dict.get_negative_words()

    i = 0
    while i < n:
        matched = False
        for wlen in range(min(4, n - i), 0, -1):
            cand = text[i : i + wlen]
            if cand in positive_words:
                sentiment_hits.append((i, True, cand))
                i += wlen
                matched = True
                break
            elif cand in negative_words:
                sentiment_hits.append((i, False, cand))
                i += wlen
                matched = True
                break
        if not matched:
            i += 1

    if not sentiment_hits:
        _dict.record_unmatched(text)
        return ("中性", 0.0)

    # 问句检测
    has_question = any(m in text for m in _dict.question_markers)

    # 如果所有问句标记都在负面词内部（如"什么东西"中的"什么"），
    # 则是斥责表达而非真正问句，不触发问句降权
    if has_question:
        neg_words_text = "".join(w for _, is_pos, w in sentiment_hits if not is_pos)
        question_only_in_neg = True
        for qm in _dict.question_markers:
            if qm in text and qm not in neg_words_text:
                question_only_in_neg = False
                break
        if question_only_in_neg:
            has_question = False

    # 置信度加权评分
    score = 0.0
    for pos, is_pos, word in sentiment_hits:
        polarity = "positive" if is_pos else "negative"
        _dict.record_hit(word, polarity)

        prefix = text[max(0, pos - 2) : pos]
        has_negator = any(neg in prefix for neg in _dict.negators)

        # 基础分 × 置信度权重
        confidence = _dict.get_confidence(word, polarity)
        word_score = 1.0 * confidence

        # 程度副词放大
        if any(deg in prefix for deg in _dict.degree_words):
            word_score *= 1.5

        if has_negator:
            if is_pos:
                score -= word_score
            # 否定 + 负面 → 缓和，不计分
        elif has_question and is_pos and word in _dict.question_context_positive:
            # 问句中的条件性正面词不计正面分
            _dict.record_hit(word, "question_context")
        else:
            score += word_score if is_pos else -word_score

    # 疑问句微弱情感 → 中性（阈值 1.0，反问句通常有更强的情感分）
    # 连续多个问号 → 反问/质疑，不降权
    if has_question and abs(score) <= 1.0:
        if not re.search(r"[？?]{2,}", text):
            score = 0.0

    # 分类判定
    if score > 0:
        result = "正面"
    elif score < 0:
        result = "负面"
    else:
        result = "中性"

    # 边界记录
    if 0 < abs(score) <= 1.5:
        _dict.record_borderline(text, score, result)

    return (result, round(score, 1))


def analyze_file(input_path: str, output_path: str = None, no_update: bool = False) -> str:
    """主分析流程：读取 JSON → 分类 → 写 EXCEL → 反思更新词典。"""
    global _dict
    _dict = DictManager()

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

    summary_rows = []
    detail_rows = []

    for post in data:
        author = post.get("author_nickname", "")
        created = post.get("created_at", "")
        content = post.get("note_text", "")
        like_count = post.get("comments_count_on_post", 0)
        total = post.get("total_after_filter", len(post.get("comments", [])))

        comments = post.get("comments", [])
        pos_count = 0
        neg_count = 0
        neu_count = 0

        for c in comments:
            sentiment, score = classify_sentiment(c.get("content", ""))
            if sentiment == "正面":
                pos_count += 1
            elif sentiment == "负面":
                neg_count += 1
            else:
                neu_count += 1

            detail_rows.append({
                "微博作者": author,
                "微博内容": content,
                "评论者": c.get("nickname", ""),
                "评论内容": c.get("content", ""),
                "情感分数": score,
                "情感分类": sentiment,
                "点赞数": c.get("like_count", 0),
            })

        denom = total if total > 0 else 1
        pos_pct = round(pos_count / denom * 100, 1)
        neg_pct = round(neg_count / denom * 100, 1)
        neu_pct = round(neu_count / denom * 100, 1)

        summary_rows.append({
            "微博作者名称": author,
            "发布时间": created,
            "微博内容": content,
            "点赞数": like_count,
            "评论数": total,
            "正面数量": pos_count,
            "正面占比": f"{pos_pct}%",
            "负面数量": neg_count,
            "负面占比": f"{neg_pct}%",
            "中性数量": neu_count,
            "中性占比": f"{neu_pct}%",
        })

    # 写 EXCEL
    _write_excel(output_path, summary_rows, detail_rows)

    total_comments = len(detail_rows)
    print(f"处理完成: {len(data)} 篇帖子, {total_comments} 条评论")
    print(f"输出文件: {output_path}")

    # 反思与词典更新
    if not no_update:
        _dict.data["meta"]["total_comments_analyzed"] += total_comments
        _dict.commit_session()
        report = _dict.reflect()
        print()
        print(report)
    else:
        print("(跳过词典更新)")

    return str(output_path)


def _write_excel(path: Path, summary_rows: list, detail_rows: list) -> None:
    """写入 EXCEL 文件（汇总 + 明细两个 Sheet）。"""
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill

    wb = Workbook()

    # ── Sheet 1: 汇总 ──
    ws1 = wb.active
    ws1.title = "汇总"
    s_headers = list(summary_rows[0].keys()) if summary_rows else []
    ws1.append(s_headers)
    for row in summary_rows:
        ws1.append([row.get(h, "") for h in s_headers])

    # ── Sheet 2: 评论明细 ──
    ws2 = wb.create_sheet("评论明细")
    d_headers = list(detail_rows[0].keys()) if detail_rows else []
    ws2.append(d_headers)
    for row in detail_rows:
        ws2.append([row.get(h, "") for h in d_headers])

    # ── 样式 ──
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


def cmd_stats():
    """显示词典统计信息。"""
    dm = DictManager()
    stats = dm.get_stats()
    print("=== 词典库统计 ===")
    print(f"版本: v{stats['version']}  |  累计运行: {stats['total_runs']} 次")
    print(f"正面词: {stats['positive_count']}  负面词: {stats['negative_count']}  问候语: {stats['greeting_count']}")
    print(f"待审核候选词: {stats['candidate_count']}")
    if stats["top_positive"]:
        print("\n触发次数 Top5 正面词:")
        for word, info in stats["top_positive"]:
            print(f"  {word}  (×{info['count']})")
    if stats["top_negative"]:
        print("\n触发次数 Top5 负面词:")
        for word, info in stats["top_negative"]:
            print(f"  {word}  (×{info['count']})")


def main():
    parser = argparse.ArgumentParser(description="微博评论情感分类器（词典库驱动）")
    parser.add_argument("-i", "--input", default=None, help="微博评论爬虫输出的 JSON 文件路径")
    parser.add_argument("-o", "--output", default=None, help="EXCEL 输出路径（默认在输入文件同目录生成）")
    parser.add_argument("--no-update", action="store_true", help="跳过词典库的自动反思更新")
    parser.add_argument("--dict-stats", action="store_true", help="仅显示词典库统计信息")
    args = parser.parse_args()

    if args.dict_stats:
        cmd_stats()
        return

    if not args.input:
        parser.error("必须指定 --input 或 --dict-stats")

    analyze_file(args.input, args.output, no_update=args.no_update)


if __name__ == "__main__":
    main()
