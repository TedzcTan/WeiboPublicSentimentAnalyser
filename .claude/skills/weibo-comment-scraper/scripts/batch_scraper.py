# -*- coding: utf-8 -*-
"""
Batch Weibo Comment Scraper
============================
Reads URLs from a docx file, scrapes comments for each post,
groups results by date, and saves to WeiboExtractData/.
"""

import argparse
import asyncio
import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Dict, List

# Setup paths
_WORKSPACE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)))
_MEDIACRAWLER_ROOT = os.path.join(_WORKSPACE_ROOT, "MediaCrawler")
sys.path.insert(0, _MEDIACRAWLER_ROOT)

# Import from the driver module
from driver import (
    parse_cookie_input, _StubPage, _extract_note_id_from_url,
    scrape_note_comments, _mblogid_to_mid,
)
from media_platform.weibo.client import WeiboClient


def extract_urls_from_docx(docx_path: str) -> Dict[str, List[str]]:
    """Read docx and return {date: [urls]} grouped by date header."""
    from docx import Document
    doc = Document(docx_path)

    date_groups: Dict[str, List[str]] = {}
    current_date = None
    url_pattern = re.compile(r'https://weibo\.com/\d+/([a-zA-Z0-9]+)\?')

    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        # Check if this is a date header
        if re.match(r'^\d{4}-\d{2}-\d{2}$', text):
            current_date = text
            if current_date not in date_groups:
                date_groups[current_date] = []
        elif url_pattern.search(text):
            if current_date:
                date_groups[current_date].append(text)

    return date_groups


async def batch_scrape(urls: List[str], client: WeiboClient, delay: float = 2.0) -> List[Dict]:
    """Scrape comments for all URLs, with delay between posts."""
    results = []
    total = len(urls)

    for i, url in enumerate(urls):
        note_id = _extract_note_id_from_url(url)
        if not note_id:
            print(f"[{i+1}/{total}] SKIP: Could not extract note ID from {url}")
            continue

        print(f"[{i+1}/{total}] Scraping note {note_id} ...", flush=True)

        try:
            result = await scrape_note_comments(client, note_id)
            if result:
                comment_count = result.get("total_after_filter", 0)
                print(f"  -> {comment_count} comments (filtered)", flush=True)
                results.append(result)
            else:
                print(f"  -> No data returned", flush=True)
        except Exception as exc:
            print(f"  -> ERROR: {exc}", flush=True)

        # Delay between posts to avoid rate limiting
        if i < total - 1:
            await asyncio.sleep(delay)

    return results


def group_and_save(results: List[Dict], out_dir: str) -> List[str]:
    """Group results by date and save to output directory. Returns list of output files."""
    day_groups: defaultdict = defaultdict(list)
    for r in results:
        try:
            day_key = parsedate_to_datetime(r["created_at"]).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            day_key = "unknown_date"
        day_groups[day_key].append(r)

    nickname = results[0]["author_nickname"] if results else "unknown"
    nickname_safe = re.sub(r'[\\/:*?"<>|]', '_', nickname)

    output_files = []
    for day_key, day_results in sorted(day_groups.items()):
        day_dir = os.path.join(out_dir, nickname_safe, day_key)
        os.makedirs(day_dir, exist_ok=True)

        filename = f"{nickname_safe}_{day_key.replace('-', '')}.json"
        filepath = os.path.join(day_dir, filename)

        with open(filepath, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(day_results, ensure_ascii=False, indent=2))

        total_comments = sum(r.get("total_after_filter", 0) for r in day_results)
        print(f"  {day_key}: {len(day_results)} posts, {total_comments} comments -> {filepath}")
        output_files.append(filepath)

    return output_files


async def main():
    parser = argparse.ArgumentParser(description="Batch Weibo Comment Scraper")
    parser.add_argument("--docx", required=True, help="Path to docx file with Weibo URLs")
    parser.add_argument("--cookies", help="Cookie string or file path")
    parser.add_argument("--delay", type=float, default=2.0, help="Delay between posts (seconds)")
    parser.add_argument("--max-posts", type=int, default=0, help="Max posts to scrape (0=all)")
    args = parser.parse_args()

    # Resolve cookies
    if not args.cookies:
        default_cookie_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".weibo_cookies")
        if os.path.isfile(default_cookie_file):
            args.cookies = default_cookie_file
        else:
            print(f"ERROR: No cookies provided and default file not found", file=sys.stderr)
            sys.exit(1)

    cookie_header, cookie_dict = parse_cookie_input(args.cookies)

    # Build client
    stub_page = _StubPage(cookie_dict)
    client = WeiboClient(
        timeout=30,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                "Version/16.0 Mobile/15E148 Safari/604.1"
            ),
            "Cookie": cookie_header,
            "Origin": "https://m.weibo.cn",
            "Referer": "https://m.weibo.cn",
            "Content-Type": "application/json;charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
        },
        playwright_page=stub_page,
        cookie_dict=cookie_dict,
    )

    # Validate cookies
    print("Validating cookies ...", flush=True)
    ok = await client.pong()
    if not ok:
        print("ERROR: Cookie validation failed", file=sys.stderr)
        sys.exit(1)
    print("Cookies OK.", flush=True)

    # Extract URLs from docx
    date_groups = extract_urls_from_docx(args.docx)

    all_urls = []
    for date in sorted(date_groups.keys()):
        urls = date_groups[date]
        # Deduplicate within each day
        seen = set()
        unique = []
        for u in urls:
            if u not in seen:
                seen.add(u)
                unique.append(u)
        print(f"  {date}: {len(unique)} unique URLs ({len(urls)} total)")
        all_urls.extend(unique)

    total = len(all_urls)
    print(f"\nTotal: {total} unique URLs to scrape\n")

    if args.max_posts > 0:
        all_urls = all_urls[:args.max_posts]
        print(f"Limited to first {args.max_posts} posts")

    # Estimate time
    est_seconds = total * (args.delay + 3)  # rough: delay + 3s for API calls
    est_minutes = est_seconds / 60
    print(f"Estimated time: ~{est_minutes:.0f} minutes\n")

    # Scrape
    start_time = time.time()
    results = await batch_scrape(all_urls, client, args.delay)
    elapsed = time.time() - start_time

    total_comments = sum(r.get("total_after_filter", 0) for r in results)
    print(f"\n{'='*60}")
    print(f"DONE: {len(results)}/{total} posts scraped in {elapsed/60:.1f} minutes")
    print(f"Total filtered comments: {total_comments}")

    # Save results
    out_dir = os.path.join(_WORKSPACE_ROOT, "WeiboExtractData")
    output_files = group_and_save(results, out_dir)

    print(f"\nOutput files:")
    for f in output_files:
        print(f"  {f}")


if __name__ == "__main__":
    asyncio.run(main())
