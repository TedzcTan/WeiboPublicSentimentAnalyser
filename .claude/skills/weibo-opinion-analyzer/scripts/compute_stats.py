#!/usr/bin/env python3
"""
微博舆情分析 — 统计计算脚本。

从爬取 JSON 和情感分类 EXCEL 中计算：
  - 全局统计（帖子数、评论/点赞/转发数、有效评论数）
  - 帖子热度指数及 TOP3
  - 情感分布汇总
  - 代表评论提取（供话题聚类使用）

用法：
  uv run python ../.claude/skills/weibo-opinion-analyzer/scripts/compute_stats.py \
      --input ../WeiboExtractData/深圳天气/2026-05-20/深圳天气_20260520.json \
      --input ../WeiboExtractData/深圳天气/2026-05-21/深圳天气_20260521.json \
      --sentiment ../WeiboExtractData/深圳天气/2026-05-20/深圳天气_20260520_情感分析.xlsx \
      --sentiment ../WeiboExtractData/深圳天气/2026-05-21/深圳天气_20260521_情感分析.xlsx
"""

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

try:
    from openpyxl import load_workbook
except ImportError:
    print("ERROR: openpyxl required. Run: uv pip install openpyxl", file=sys.stderr)
    sys.exit(1)


def load_json(path: str) -> List[Dict]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def compute_global_stats(json_files: List[str]) -> Dict[str, Any]:
    """Compute global statistics from JSON files."""
    all_posts = []
    for f in json_files:
        all_posts.extend(load_json(f))

    total_posts = len(all_posts)
    total_comments = sum(p.get("comments_count_on_post", 0) or 0 for p in all_posts)
    total_attitudes = sum(p.get("attitudes_count", 0) or 0 for p in all_posts)
    total_reposts = sum(p.get("reposts_count", 0) or 0 for p in all_posts)
    total_effective = sum(p.get("total_after_filter", 0) or 0 for p in all_posts)

    return {
        "total_posts": total_posts,
        "total_comments": total_comments,
        "total_attitudes": total_attitudes,
        "total_reposts": total_reposts,
        "total_effective": total_effective,
    }


def compute_top_posts(json_files: List[str], sentinel_files: List[str], top_n: int = 3) -> List[Dict]:
    """Compute heat index and return TOP-N posts with sentiment info."""

    # Load sentiment data keyed by note_text prefix
    sentiment_map: Dict[str, Dict] = {}
    for xlsx_path in sentinel_files:
        wb = load_workbook(xlsx_path)
        ws = wb["汇总"]
        rows = list(ws.iter_rows(values_only=True))
        for row in rows[1:]:
            note_text = (row[2] or "")[:100]
            sentiment_map[note_text] = {
                "attitudes": int(row[3] or 0),
                "comments_total": int(row[4] or 0),
                "positive": int(row[5] or 0),
                "positive_pct": str(row[6] or ""),
                "negative": int(row[7] or 0),
                "negative_pct": str(row[8] or ""),
                "neutral": int(row[9] or 0),
                "neutral_pct": str(row[10] or ""),
            }

    # Build post list with heat index
    posts = []
    for jf in json_files:
        for post in load_json(jf):
            comments = post.get("comments_count_on_post", 0) or 0
            attitudes = post.get("attitudes_count", 0) or 0
            reposts = post.get("reposts_count", 0) or 0
            heat = comments * 0.4 + attitudes * 0.3 + reposts * 0.3

            note_text = (post.get("note_text", "") or "")[:100]

            # Match sentiment
            sent = sentiment_map.get(note_text, {})
            # Fuzzy match if exact fails
            if not sent:
                for key, val in sentiment_map.items():
                    if key[:50] == note_text[:50]:
                        sent = val
                        break

            posts.append({
                "note_id": post.get("note_id", ""),
                "note_text": note_text,
                "created_at": post.get("created_at", ""),
                "comments_count": comments,
                "attitudes_count": attitudes,
                "reposts_count": reposts,
                "heat_index": round(heat, 1),
                "sentiment": sent,
                "top_comments": get_top_comments(post, 3),
            })

    posts.sort(key=lambda x: x["heat_index"], reverse=True)
    return posts[:top_n]


def get_top_comments(post: Dict, n: int = 3) -> List[Dict]:
    """Extract top-N comments by like count from a post."""
    comments = post.get("comments", [])
    comments = [c for c in comments if c.get("depth", 0) == 0]  # Only top-level
    comments.sort(key=lambda x: x.get("like_count", 0), reverse=True)
    result = []
    for c in comments[:n]:
        result.append({
            "content": c.get("content", ""),
            "likes": c.get("like_count", 0),
            "nickname": c.get("nickname", ""),
        })
    return result


def compute_sentiment_distribution(sentiment_files: List[str]) -> Dict[str, Any]:
    """Aggregate sentiment counts from Excel files."""
    total_pos = 0
    total_neg = 0
    total_neu = 0

    for xlsx_path in sentiment_files:
        wb = load_workbook(xlsx_path)
        ws = wb["汇总"]
        rows = list(ws.iter_rows(values_only=True))
        for row in rows[1:]:
            total_pos += int(row[5] or 0)
            total_neg += int(row[7] or 0)
            total_neu += int(row[9] or 0)

    total = total_pos + total_neg + total_neu
    return {
        "positive": total_pos,
        "positive_pct": round(total_pos / total * 100, 1) if total > 0 else 0,
        "negative": total_neg,
        "negative_pct": round(total_neg / total * 100, 1) if total > 0 else 0,
        "neutral": total_neu,
        "neutral_pct": round(total_neu / total * 100, 1) if total > 0 else 0,
        "total": total,
    }


def extract_representative_comments(
    json_files: List[str],
    sample_top: int = 80,
    sample_random: int = 120,
    seed: int = 42,
) -> Tuple[List[Dict], List[Dict], List[Dict]]:
    """
    Extract representative comments for topic clustering.
    Returns (top_liked, sample_positive, sample_negative) tuples.
    """
    all_comments = []
    for jf in json_files:
        for post in load_json(jf):
            note_text = (post.get("note_text", "") or "")[:80].replace("\n", " ")
            for c in post.get("comments", []):
                all_comments.append({
                    "content": c.get("content", ""),
                    "likes": c.get("like_count", 0),
                    "note_context": note_text,
                    "depth": c.get("depth", 0),
                    "created_at": c.get("created_at", ""),
                    "nickname": c.get("nickname", ""),
                })

    # Filter to depth-0 for cleaner signal
    root_comments = [c for c in all_comments if c["depth"] == 0]

    # Sort by likes
    root_comments.sort(key=lambda x: x["likes"], reverse=True)
    top_pool = root_comments[:sample_top]

    # Random sample from the rest
    random.seed(seed)
    rest = root_comments[sample_top:]
    random.shuffle(rest)
    random_pool = rest[:sample_random]

    return top_pool, random_pool


def main():
    # Fix Windows GBK encoding for emoji output
    if sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="微博舆情分析统计计算")
    parser.add_argument("--input", "-i", action="append", dest="json_files", required=True,
                        help="爬取结果 JSON 文件（可多次指定）")
    parser.add_argument("--sentiment", "-s", action="append", dest="sentiment_files", required=True,
                        help="情感分类 EXCEL 文件（可多次指定）")
    parser.add_argument("--top-n", type=int, default=3, help="热度 TOP-N 帖子数（默认 3）")
    parser.add_argument("--sample-top", type=int, default=80,
                        help="话题聚类：按点赞数取 TOP 评论数")
    parser.add_argument("--sample-random", type=int, default=120,
                        help="话题聚类：随机采样评论数")
    args = parser.parse_args()

    # Resolve paths relative to CWD
    json_files = [str(Path(f)) for f in args.json_files]
    sentiment_files = [str(Path(f)) for f in args.sentiment_files]

    # 1. Global stats
    global_stats = compute_global_stats(json_files)

    # 2. TOP-N posts
    top_posts = compute_top_posts(json_files, sentiment_files, args.top_n)

    # 3. Sentiment distribution
    sentiment_dist = compute_sentiment_distribution(sentiment_files)

    # 4. Representative comments
    top_comments, random_comments = extract_representative_comments(
        json_files, args.sample_top, args.sample_random
    )
    sample = top_comments + random_comments

    # Output as JSON for consumption by the rest of the pipeline
    output = {
        "global_stats": global_stats,
        "top_posts": top_posts,
        "sentiment_distribution": sentiment_dist,
        "representative_comments": sample,
        "comment_count": len(sample),
    }

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
