#!/usr/bin/env python3
"""
微博话题聚类 — 评论提取脚本。

从爬取 JSON 文件中提取代表性评论，输出结构化的评论文本，
供 Claude AI 进行语义聚类分析。

用法：
  uv run python ../.claude/skills/weibo-topic-clusterer/scripts/extract_comments.py \
      --input ../WeiboExtractData/深圳天气/2026-05-20/深圳天气_20260520.json \
      --input ../WeiboExtractData/深圳天气/2026-05-21/深圳天气_20260521.json \
      --sentiment ../WeiboExtractData/深圳天气/2026-05-20/深圳天气_20260520_情感分析.xlsx \
      --max-comments 200
"""

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from openpyxl import load_workbook
except ImportError:
    print("ERROR: openpyxl required. Run: uv pip install openpyxl", file=sys.stderr)
    sys.exit(1)


def load_json(path: str) -> List[Dict]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_sentiment_map(sentiment_files: List[str]) -> Dict[str, str]:
    """
    Build a mapping from comment content (first 80 chars) to sentiment label.
    Uses the detail sheet from sentiment Excel.
    """
    sentiment_map: Dict[str, str] = {}
    for xlsx_path in sentiment_files:
        wb = load_workbook(xlsx_path)
        if "评论明细" not in wb.sheetnames:
            continue
        ws = wb["评论明细"]
        rows = list(ws.iter_rows(values_only=True))
        for row in rows[1:]:
            comment_text = (row[3] or "")[:80]
            sentiment = row[5] or ""  # 情感分类 column
            sentiment_map[comment_text] = sentiment
    return sentiment_map


def extract_comments(
    json_files: List[str],
    sentiment_files: Optional[List[str]] = None,
    max_total: int = 200,
    top_ratio: float = 0.4,
    seed: int = 42,
) -> List[Dict]:
    """
    Extract comments from JSON files, prioritizing high-like comments
    and ensuring balanced representation across posts.
    """
    # Load all posts with their comments
    all_posts = []
    for jf in json_files:
        for post in load_json(jf):
            comments = [c for c in post.get("comments", []) if c.get("depth", 0) == 0]
            if comments:
                all_posts.append({
                    "note_id": post.get("note_id", ""),
                    "note_text": (post.get("note_text", "") or "")[:100].replace("\n", " "),
                    "created_at": post.get("created_at", ""),
                    "comments": comments,
                })

    if not all_posts:
        return []

    # Load sentiment labels if available
    sentiment_map = {}
    if sentiment_files:
        sentiment_map = load_sentiment_map(sentiment_files)

    # Flatten and score all comments
    all_comments: List[Dict] = []
    for post in all_posts:
        for c in post["comments"]:
            content = c.get("content", "").strip()
            if not content:
                continue
            like_count = c.get("like_count", 0) or 0
            all_comments.append({
                "content": content,
                "likes": like_count,
                "note_id": post["note_id"],
                "note_context": post["note_text"],
                "nickname": c.get("nickname", ""),
                "created_at": c.get("created_at", ""),
                "sentiment": sentiment_map.get(content[:80], ""),
                # Score: likes + length bonus (substantial content)
                "score": like_count + min(len(content) / 10, 5),
            })

    # Deduplicate by content prefix
    seen = set()
    unique_comments = []
    for c in sorted(all_comments, key=lambda x: x["score"], reverse=True):
        key = c["content"][:40]
        if key not in seen:
            seen.add(key)
            unique_comments.append(c)

    # Top-N by score + random sample for diversity
    top_count = int(max_total * top_ratio)
    random_count = max_total - top_count

    top_pool = unique_comments[:top_count]

    random.seed(seed)
    rest = unique_comments[top_count:]
    random.shuffle(rest)
    random_pool = rest[:random_count]

    result = top_pool + random_pool
    # Strip internal scoring field
    for c in result:
        c.pop("score", None)

    return result


def main():
    # Fix Windows GBK encoding for emoji output
    if sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="微博话题聚类评论提取")
    parser.add_argument("--input", "-i", action="append", dest="json_files", required=True,
                        help="爬取结果 JSON 文件（可多次指定）")
    parser.add_argument("--sentiment", "-s", action="append", dest="sentiment_files",
                        help="情感分类 EXCEL 文件（可多次指定，可选）")
    parser.add_argument("--max-comments", "-n", type=int, default=200,
                        help="最大提取评论数（默认 200）")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    parser.add_argument("--format", choices=["json", "text"], default="json",
                        help="输出格式：json 或 text（纯文本，每行一条评论）")
    args = parser.parse_args()

    json_files = [str(Path(f)) for f in args.json_files]
    sentiment_files = [str(Path(f)) for f in args.sentiment_files] if args.sentiment_files else None

    comments = extract_comments(
        json_files=json_files,
        sentiment_files=sentiment_files,
        max_total=args.max_comments,
        seed=args.seed,
    )

    if not comments:
        print("WARN: No comments extracted", file=sys.stderr)
        sys.exit(0)

    if args.format == "text":
        for i, c in enumerate(comments):
            print(f"[{i + 1}] likes={c['likes']} sentiment={c.get('sentiment', '?')}")
            print(f"    上下文: {c['note_context'][:60]}")
            print(f"    评论: {c['content']}")
            print()
    else:
        print(json.dumps(comments, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
