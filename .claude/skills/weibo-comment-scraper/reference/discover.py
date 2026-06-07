# -*- coding: utf-8 -*-
"""
发现指定用户在时间范围内的全部帖子 note_id。

用法:
  cd MediaCrawler
  uv run python ../.claude/skills/weibo-comment-scraper/reference/discover.py \
      --user-id 2294193132 \
      --start "2026-06-06 08:00" \
      --end "2026-06-07 08:00"

输出: 每行一个 note_id，stderr 输出总数。
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone, timedelta


def main():
    parser = argparse.ArgumentParser(description="发现时间范围内的微博帖子")
    parser.add_argument("--user-id", required=True, help="微博用户ID")
    parser.add_argument("--start", required=True, help="起始时间 (YYYY-MM-DD HH:MM)")
    parser.add_argument("--end", required=True, help="结束时间 (YYYY-MM-DD HH:MM)")
    parser.add_argument("--cookie-file", default=None,
                        help="Cookie 文件路径（默认从 scripts/.weibo_cookies 读取）")
    parser.add_argument("--max-pages", type=int, default=50,
                        help="最大翻页数（默认 50）")
    args = parser.parse_args()

    # Cookie 路径
    if args.cookie_file:
        cookie_path = args.cookie_file
    else:
        import os
        skill_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cookie_path = os.path.join(skill_dir, "scripts", ".weibo_cookies")

    try:
        with open(cookie_path, "r") as f:
            cookie = f.read().strip()
    except FileNotFoundError:
        print(f"ERROR: Cookie 文件不存在: {cookie_path}", file=sys.stderr)
        sys.exit(1)

    if not cookie:
        print("ERROR: Cookie 文件为空", file=sys.stderr)
        sys.exit(1)

    TZ = timezone(timedelta(hours=8))  # 微博使用 UTC+8
    start = datetime.fromisoformat(args.start).replace(tzinfo=TZ)
    end = datetime.fromisoformat(args.end).replace(tzinfo=TZ)

    note_ids = []
    since_id = ""
    page = 0
    stop = False

    while not stop and page < args.max_pages:
        url = f"https://m.weibo.cn/api/container/getIndex?containerid=107603{args.user_id}"
        if since_id:
            url += f"&since_id={since_id}"

        r = subprocess.run(
            ["curl", "-s", url,
             "-H", f"Cookie: {cookie}",
             "-H", ("User-Agent: Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1")],
            capture_output=True, text=True,
        )

        try:
            data = json.loads(r.stdout).get("data", {})
        except json.JSONDecodeError:
            print(f"ERROR: API 返回非 JSON（第 {page+1} 页），可能触发验证码或 Cookie 过期", file=sys.stderr)
            print(f"响应前 500 字符: {r.stdout[:500]}", file=sys.stderr)
            sys.exit(1)

        cards = data.get("cards", [])
        info = data.get("cardlistInfo", {})
        since_id = info.get("since_id", "0")

        if not cards:
            print(f"第 {page+1} 页无数据，停止翻页", file=sys.stderr)
            break

        for card in cards:
            if card.get("card_type") != 9:
                continue
            mblog = card.get("mblog", {})
            nid = str(mblog.get("id", ""))
            created = mblog.get("created_at", "")
            if not nid or not created:
                continue
            try:
                dt = datetime.strptime(created, "%a %b %d %H:%M:%S %z %Y")
            except ValueError:
                continue
            if dt > end:
                continue
            if dt < start:
                stop = True
                break
            note_ids.append(nid)

        page += 1
        if not since_id or since_id == "0":
            print(f"翻页结束（第 {page} 页无 since_id）", file=sys.stderr)
            break

    for nid in note_ids:
        print(nid)
    print(f"TOTAL:{len(note_ids)} posts in range ({args.start} ~ {args.end})", file=sys.stderr)


if __name__ == "__main__":
    main()
