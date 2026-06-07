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
CLASSIFICATIONS: dict[str, tuple[str, float]] = {
    "5298836893602254": ("中性", 0.0),
    "5298849294060743": ("中性", 0.0),
    "5298837602177785": ("中性", 0.0),
    "5298842281182580": ("中性", 0.0),
    "5298837285504666": ("中性", 0.0),
    "5298878347740883": ("负面", -0.6),
    "5298841863852898": ("负面", -0.4),
    "5298838441300637": ("负面", -0.5),
    "5298839932110913": ("负面", -0.3),
    "5298842939426568": ("负面", -0.4),
    "5298840689443155": ("负面", -0.8),
    "5298845917382679": ("中性", 0.0),
    "5298865632708423": ("负面", -0.6),
    "5298841307056302": ("中性", 0.0),
    "5298847114861385": ("中性", 0.0),
    "5298853603708913": ("中性", 0.0),
    "5298852840083201": ("中性", 0.0),
    "5298837472417190": ("中性", 0.0),
    "5298839122609129": ("中性", 0.0),
    "5298840766776506": ("中性", 0.0),
    "5298849526842713": ("负面", -0.5),
    "5298843964936177": ("中性", 0.0),
    "5298837971275368": ("负面", -0.3),
    "5298838430289444": ("中性", 0.0),
    "5298838933866990": ("中性", 0.0),
    "5298837203978530": ("负面", -0.4),
    "5298847354196113": ("中性", 0.0),
    "5298845896409507": ("中性", 0.0),
    "5298844066646366": ("中性", 0.0),
    "5298846989292733": ("负面", -0.3),
    "5298854383845690": ("中性", 0.0),
    "5298845957227442": ("负面", -0.3),
    "5298839741271255": ("中性", 0.0),
    "5298840299376354": ("中性", 0.0),
    "5298845516825368": ("负面", -0.8),
    "5298847576232486": ("中性", 0.0),
    "5298857181448668": ("中性", 0.0),
    "5298847405573902": ("负面", -0.5),
    "5298848525717287": ("中性", 0.0),
    "5298846133655196": ("负面", -0.5),
    "5298844212397921": ("负面", -0.3),
    "5298842316570744": ("负面", -0.3),
    "5298842681742989": ("负面", -0.4),
    "5298842851347318": ("负面", -0.6),
    "5298842121535873": ("中性", 0.0),
    "5298841646531961": ("负面", -0.6),
    "5298843638827175": ("负面", -0.4),
    "5298838256491536": ("中性", 0.0),
    "5298866232756804": ("中性", 0.0),
    "5298837080245991": ("负面", -0.6),
    "5298837035947339": ("中性", 0.0),
    "5298836798180969": ("中性", 0.0),
    "5298841620583999": ("中性", 0.0),
    "5298836532629762": ("中性", 0.0),
    "5298850197931187": ("中性", 0.0),
    "5298845350105439": ("中性", 0.0),
    "5298837614760818": ("中性", 0.0),
    "5298837501774931": ("负面", -0.4),
    "5298836853751931": ("中性", 0.0),
    "5298837000292854": ("中性", 0.0),
    "5298847647798311": ("中性", 0.0),
    "5298846248733892": ("负面", -0.5),
    "5298921859711772": ("中性", 0.0),
    "5298889441673220": ("中性", 0.0),
    "5298882739440397": ("中性", 0.0),
    "5298874274816516": ("中性", 0.0),
    "5298867419485081": ("正面", 0.3),
    "5298856528969809": ("负面", -0.5),
    "5298855455230140": ("中性", 0.0),
    "5298854326178051": ("中性", 0.0),
    "5298854033360563": ("中性", 0.0),
    "5298851701067364": ("中性", 0.0),
    "5298850619458062": ("中性", 0.0),
    "5298849874973548": ("中性", 0.0),
    "5298847845976875": ("负面", -0.6),
    "5298845244463194": ("中性", 0.0),
    "5298845055713889": ("负面", -0.4),
    "5298844288942938": ("中性", 0.0),
    "5298844176746181": ("负面", -0.4),
    "5298843734246191": ("中性", 0.0),
    "5298843675529542": ("中性", 0.0),
    "5298843155695287": ("负面", -0.3),
    "5298842526548601": ("中性", 0.0),
    "5298842083789869": ("中性", 0.0),
    "5298841775768428": ("负面", -0.4),
    "5298841670911971": ("负面", -0.6),
    "5298841586762868": ("中性", 0.0),
    "5298841407722347": ("中性", 0.0),
    "5298841133781033": ("中性", 0.0),
    "5298841068766423": ("负面", -0.3),
    "5298840921706676": ("中性", 0.0),
    "5298840873731746": ("中性", 0.0),
    "5298840701764152": ("中性", 0.0),
    "5298840408168388": ("中性", 0.0),
    "5298840041426704": ("中性", 0.0),
    "5298839938404292": ("中性", 0.0),
    "5298842427457728": ("负面", -0.4),
    "5298842333610825": ("中性", 0.0),
    "5298839768796525": ("中性", 0.0),
    "5298839758303724": ("中性", 0.0),
    "5298839376631161": ("负面", -0.3),
    "5298841874074332": ("负面", -0.4),
    "5298839204403795": ("中性", 0.0),
    "5298838768452300": ("中性", 0.0),
    "5298838543008089": ("负面", -0.3),
    "5298838483240679": ("中性", 0.0),
    "5298838422161882": ("中性", 0.0),
    "5298838411681354": ("中性", 0.0),
    "5298837203980444": ("中性", 0.0),
    "5298836916667103": ("中性", 0.0),
    "5298837122187783": ("中性", 0.0),
    "5298836889405371": ("中性", 0.0),
    "5298836862141861": ("中性", 0.0),
    "5298836662914151": ("负面", -0.7),
    "5298836614678148": ("负面", -0.3),
    "5298836609437742": ("中性", 0.0),
    "5298836595806836": ("负面", -0.3),
    "5298836576141988": ("中性", 0.0),
    "5298870910457136": ("中性", 0.0),
    "5298975416522762": ("中性", 0.0),
    "5298879684674656": ("负面", -0.3),
    "5298856536312609": ("中性", 0.0),
    "5298849134674813": ("负面", -0.8),
    "5298847513577096": ("负面", -0.5),
    "5298844099154046": ("负面", -0.6),
    "5298848810926341": ("负面", -0.7),
    "5298849170065987": ("中性", 0.0),
    "5298846978017595": ("中性", 0.0),
    "5298840379071086": ("中性", 0.0),
    "5298839731051476": ("中性", 0.0),
    "5298838766095936": ("中性", 0.0),
    "5298836618088263": ("中性", 0.0),
    "5298849969080216": ("负面", -0.5),
    "5298851151347990": ("中性", 0.0),
    "5298847184062966": ("负面", -0.3),
    "5298844592245740": ("负面", -0.5),
    "5298852072523219": ("负面", -0.7),
}


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
