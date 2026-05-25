#!/usr/bin/env python3
"""在关键词分类后，基于语义理解手动修正剩余上下文依赖的评论分类。"""

import json
import re
import sys
from pathlib import Path
from collections import defaultdict

from dict_manager import DictManager
from sentiment_classifier import classify_sentiment, clean_text, _write_excel

# 手动修正列表：清洗后的评论文本 → (正确分类, 原因)
# 评论来自上下文语义分析，关键词无法捕获
MANUAL_FIXES: dict[str, tuple[str, str, float]] = {
    # ── 抱怨预报不准/前后不一 ──
    "经典下完了出红暴": ("负面", "讽刺预警总是在雨后发布，经典的'马后炮'", -1.0),
    "这是市桥今年目前最大的一场雨了，昨天说有大雨的又不大，今天就大成这样": ("负面", "抱怨昨天预报有大雨不准，今天突然大成这样", -1.0),
    "停雨了才来发。": ("负面", "批评预警滞后，雨停了才发", -1.0),
    "停雨了才收到预警短信": ("负面", "批评预警短信滞后", -1.0),
    "上一条仲话升级可能性少": ("负面", "吐槽上一分钟还说升级可能性小，前后矛盾", -1.0),
    "刚升红预半小时就停雨了": ("负面", "抱怨刚升级红色预警就停雨，预警失去意义", -1.0),
    "今天的中雨比昨天的暴雨还大": ("负面", "吐槽预报不准，中雨比暴雨还大", -1.0),
    # ── 抱怨预警滞后/不停课 ──
    "刚送到学校才来发红色。": ("负面", "抱怨送完孩子到学校才发红色预警", -1.0),
    "刚送到学校": ("负面", "抱怨送完孩子才发预警（简略版）", -1.0),
    "等大家都到学校就通知": ("负面", "讽刺校方/官方故意拖延，等学生到校后才通知", -1.0),
    "可是我的学校为什么不放假": ("负面", "抱怨学校不放假", -1.0),
    "2点上学你现在才发出来他们都在路上游泳了": ("负面", "抱怨预警太晚，孩子已经在积水路上", -1.5),
    "天河区停课铃没显示停课啊？": ("负面", "抱怨停课铃不显示停课信息", -1.0),
    "晚点，等大家都到学校就停": ("负面", "讽刺：晚点发预警，等大家都到校再停课", -1.0),
    "越秀也没有": ("负面", "抱怨越秀区也没收到停课通知", -1.0),
    # ── 担忧/影响生活 ──
    "痛击市区": ("负面", "担忧暴雨对市区的冲击", -0.8),
    "真的夸张 这种大雨持续下一小时了": ("负面", "担忧大雨持续时间长，语气担忧", -0.8),
    "这雨下得，我们学校老师集体变清洁工了": ("负面", "抱怨雨水灌入学校，老师被迫清理", -1.0),
    # ── 其他抱怨/负面预判 ──
    "等会只有从化 增城下，不得跟昨天一样被你们这群人骂": ("负面", "负面预判：预测又要被骂，不满情绪", -0.8),
    "？怎么看软件上是取消了啊": ("负面", "困惑不满：预警软件显示取消，信息不一致", -0.8),
    "市区就是没有！怎么，闷热到爆炸还不让人骂了？自己那边有雨下还要堵我们没雨下的嘴吗？都安得什么心啊！": ("负面", "强烈愤怒：抱怨预报不准，闷热难忍还不让说", -2.0),
    # ── 伪正面修正（正面词被讽刺使用） ──
    "你们啊，好好总结分析这次长时间暴雨灾害的成因，尽快向公众公布，以后做好真正的预警": ("负面", "批评/问责：'你们啊'是教训口吻，要求做好真正的预警暗示之前没做到", -1.5),
    "666 小学下午快上课 就来红色": ("负面", "讽刺：'666'不是夸赞，是反讽快上课了才来红色预警", -1.0),
    "刚红暴完就停雨了笑死": ("负面", "讽刺：'笑死'不是好笑，是嘲笑红色预警刚发雨就停了", -1.0),
}


def apply_fixes(detail_rows: list[dict]) -> list[dict]:
    """对评论明细列表应用手动修正，返回修正后的列表。"""
    fixes_applied = 0
    for row in detail_rows:
        cleaned = clean_text(row["评论内容"])
        for pattern, (sentiment, reason, score) in MANUAL_FIXES.items():
            if cleaned == clean_text(pattern):
                old = row["情感分类"]
                row["情感分类"] = sentiment
                row["情感分数"] = score
                print(f"  ✓ [{old}→{sentiment}] {reason}")
                print(f"    「{row['评论内容'][:60]}」")
                fixes_applied += 1
                break
    print(f"\n共修正 {fixes_applied} 条评论")
    return detail_rows


def rebuild_summary(data: list[dict], detail_rows: list[dict]) -> list[dict]:
    """根据修正后的明细重建汇总行。"""
    summary_rows = []
    comment_idx = 0
    for post in data:
        author = post.get("author_nickname", "")
        created = post.get("created_at", "")
        content = post.get("note_text", "")
        like_count = post.get("comments_count_on_post", 0)
        total = post.get("total_after_filter", len(post.get("comments", [])))

        pos = neg = neu = 0
        for _ in post.get("comments", []):
            s = detail_rows[comment_idx]["情感分类"]
            if s == "正面":
                pos += 1
            elif s == "负面":
                neg += 1
            else:
                neu += 1
            comment_idx += 1

        denom = total if total > 0 else 1
        summary_rows.append({
            "微博作者名称": author,
            "发布时间": created,
            "微博内容": content,
            "点赞数": like_count,
            "评论数": total,
            "正面数量": pos,
            "正面占比": f"{round(pos / denom * 100, 1)}%",
            "负面数量": neg,
            "负面占比": f"{round(neg / denom * 100, 1)}%",
            "中性数量": neu,
            "中性占比": f"{round(neu / denom * 100, 1)}%",
        })
    return summary_rows


def main():
    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else input_path.with_name(f"{input_path.stem}_情感分析.xlsx")

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Step 1: 关键词分类
    import sentiment_classifier
    sentiment_classifier._dict = DictManager()

    detail_rows = []
    for post in data:
        for c in post.get("comments", []):
            sentiment, score = classify_sentiment(c.get("content", ""))
            detail_rows.append({
                "微博作者": post.get("author_nickname", ""),
                "微博内容": post.get("note_text", ""),
                "评论者": c.get("nickname", ""),
                "评论内容": c.get("content", ""),
                "情感分数": score,
                "情感分类": sentiment,
                "点赞数": c.get("like_count", 0),
            })

    before_pos = sum(1 for r in detail_rows if r["情感分类"] == "正面")
    before_neg = sum(1 for r in detail_rows if r["情感分类"] == "负面")
    before_neu = sum(1 for r in detail_rows if r["情感分类"] == "中性")
    print(f"关键词分类完成: 正面{before_pos}, 负面{before_neg}, 中性{before_neu}")

    # Step 2: 应用语义手动修正
    print("\n=== 应用语义手动修正 ===")
    detail_rows = apply_fixes(detail_rows)

    after_pos = sum(1 for r in detail_rows if r["情感分类"] == "正面")
    after_neg = sum(1 for r in detail_rows if r["情感分类"] == "负面")
    after_neu = sum(1 for r in detail_rows if r["情感分类"] == "中性")
    print(f"\n修正后: 正面{after_pos}, 负面{after_neg}, 中性{after_neu}")
    print(f"本次修正: 负面 +{after_neg - before_neg}")

    # Step 3: 重建汇总并写 EXCEL
    summary_rows = rebuild_summary(data, detail_rows)
    _write_excel(output_path, summary_rows, detail_rows)
    print(f"\n输出文件: {output_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python apply_manual_fixes.py <JSON路径> [输出路径]")
        sys.exit(1)
    main()
