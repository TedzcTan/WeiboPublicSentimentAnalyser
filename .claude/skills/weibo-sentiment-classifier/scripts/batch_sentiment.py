# -*- coding: utf-8 -*-
"""
Batch Sentiment Classifier for Weather Comments
===============================================
Uses keyword-based classification optimized for weather-related comments.
Handles large volumes (15K+ comments) efficiently.
"""

import argparse
import json
import re
from pathlib import Path
from collections import Counter


# Positive keywords for weather context
POSITIVE_PATTERNS = [
    r'准确|准时|及时|靠谱|给力|赞|厉害|牛|棒|不错|挺好|很好|非常好',
    r'谢谢|感谢|辛苦|点赞|加油|支持|比心|爱心',
    r'方便|实用|好用|管用|有效',
    r'期待|希望.*继续|越来越好|继续努力',
    r'贴心|细心|专业|认真|负责',
    r'收到|知道|明白|了解|清楚.*了',
    r'终于|太好了|真好|太棒|完美',
    r'喜欢|满意|不错|可以|还行',
    r'提醒.*及时|注意.*安全|大家.*注意',
    r'凉快|舒服|舒适|凉爽|晴天|好天气',
    r'下雨|降温|凉了|没那么热|终于.*雨',
    r'广州天气.*准|天气.*准|预报.*准',
]

# Negative keywords for weather context
NEGATIVE_PATTERNS = [
    r'不准|不.*准|错误|忽悠|骗人|坑|离谱|垃圾|差劲|失望',
    r'热死|热.*死|闷热|太热|好热|暴热|烤|蒸|烫',
    r'冷死|冻死|太冷|好冷',
    r'没.*准过|从来.*不准|一直.*不准|又.*不准',
    r'下雨.*烦|讨厌.*雨|又下雨|还下雨|还在下雨',
    r'怎么.*又|怎么.*还|说好.*不|说好的.*呢',
    r'湿|潮湿|回南天|发霉|长毛',
    r'骗|假|虚|错|坑|烂|废|差|糟',
    r'烦|讨厌|难受|痛苦|崩溃|无语|无奈',
    r'什么时候.*结束|什么时候.*停|什么时候.*凉',
    r'不够.*准|不太.*准|不怎么.*准',
    r'台风|暴雨|冰雹|雷.*大|预警',
    r'停课|停工|取消|延误',
    r'闷|桑拿|蒸笼|烤箱|火炉',
    r'唉|哎|晕|靠|卧槽|特么|尼玛',
]

# Compound patterns: <negative context> + <keyword>
NEGATIVE_CONTEXT = r'(不|没|别|无|未|非)'


def classify_comment(content: str) -> tuple:
    """Classify a comment as positive/negative/neutral with score.

    Returns (sentiment_label, score) where:
    - positive: score > 0
    - negative: score < 0
    - neutral: score = 0
    """
    if not content or not content.strip():
        return ("中性", 0.0)

    text = content.strip()
    pos_score = 0.0
    neg_score = 0.0

    for pattern in POSITIVE_PATTERNS:
        matches = re.findall(pattern, text)
        if matches:
            pos_score += len(matches) * 0.5

    for pattern in NEGATIVE_PATTERNS:
        matches = re.findall(pattern, text)
        if matches:
            neg_score += len(matches) * 0.5

    # Cap scores
    pos_score = min(pos_score, 1.0)
    neg_score = min(neg_score, 1.0)

    net_score = pos_score - neg_score

    if net_score >= 0.3:
        return ("正面", net_score)
    elif net_score <= -0.3:
        return ("负面", net_score)
    else:
        return ("中性", 0.0)


def deduplicate_comments(data: list) -> list[dict]:
    """Deduplicate comments by comment_id."""
    seen = set()
    result = []
    for post in data:
        for c in post.get("comments", []):
            cid = c.get("comment_id", "")
            if cid and cid not in seen:
                seen.add(cid)
                result.append(c)
    return result


def write_excel(output_path: Path, data: list, classifications: dict) -> str:
    """Write EXCEL with summary and detail sheets."""
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

    # Sheet 1: Summary
    ws1 = wb.active
    ws1.title = "汇总"
    s_headers = list(summary_rows[0].keys()) if summary_rows else []
    ws1.append(s_headers)
    for row in summary_rows:
        ws1.append([row.get(h, "") for h in s_headers])

    # Sheet 2: Detail
    ws2 = wb.create_sheet("评论明细")
    d_headers = list(detail_rows[0].keys()) if detail_rows else []
    ws2.append(d_headers)
    for row in detail_rows:
        ws2.append([row.get(h, "") for h in d_headers])

    # Styling
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
    parser = argparse.ArgumentParser(description="Batch Sentiment Classifier for Weather Comments")
    parser.add_argument("-i", "--input", required=True, help="Input JSON file path")
    parser.add_argument("-o", "--output", default=None, help="Output EXCEL path")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    if args.output is None:
        stem = input_path.stem
        output_path = input_path.with_name(f"{stem}_情感分析.xlsx")
    else:
        output_path = Path(args.output)

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    comments = deduplicate_comments(data)

    # Classify all comments
    classifications = {}
    for c in comments:
        cid = c.get("comment_id", "")
        content = c.get("content", "")
        sentiment, score = classify_comment(content)
        classifications[cid] = (sentiment, score)

    # Generate EXCEL
    out = write_excel(output_path, data, classifications)

    # Statistics
    counter = Counter(v[0] for v in classifications.values())
    total = len(classifications)

    print(f"处理完成: {len(data)} 篇帖子, {total} 条去重评论")
    print(f"  正面: {counter.get('正面', 0)} ({round(counter.get('正面', 0) / total * 100, 1)}%)")
    print(f"  负面: {counter.get('负面', 0)} ({round(counter.get('负面', 0) / total * 100, 1)}%)")
    print(f"  中性: {counter.get('中性', 0)} ({round(counter.get('中性', 0) / total * 100, 1)}%)")
    print(f"输出文件: {output_path}")


if __name__ == "__main__":
    main()
