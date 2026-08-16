# -*- coding: utf-8 -*-
"""
Weibo Comment Scraper Driver
=============================
Reuses MediaCrawler's WeiboClient to scrape Weibo comments with filtering.

Two modes:
  1. Direct post:  --url <weibo_url> or --note-id <id>
  2. User + time:  --user-id <uid> --start-time <YYYY-MM-DD> [--end-time <YYYY-MM-DD>]

Filters applied:
  - Author replies (comment by the post author)  → skipped
  - Empty content (blank after HTML strip)       → skipped
  - Pure emoji / symbol-only content             → skipped

Sub-comments (楼中楼) are crawled recursively to any depth.

Usage:
  cd MediaCrawler
  uv run python ../.claude/skills/weibo-comment-scraper/scripts/driver.py \
      --cookies "SUB=xxx; SUBP=xxx; ..." \
      --url "https://m.weibo.cn/detail/4982041758140155"

  uv run python ../.claude/skills/weibo-comment-scraper/scripts/driver.py \
      --cookies ./weibo_cookies.txt \
      --user-id "5756404150" \
      --start-time "2026-01-01"
"""

import argparse
import asyncio
import json
import os
import re
import sys
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Dict, List, Optional, Tuple

# Skill at <workspace>/.claude/skills/weibo-comment-scraper/scripts/driver.py
# MediaCrawler at <workspace>/MediaCrawler/
_WORKSPACE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)))  # scripts → weibo-comment-scraper → skills → .claude → workspace
_MEDIACRAWLER_ROOT = os.path.join(_WORKSPACE_ROOT, "MediaCrawler")
sys.path.insert(0, _MEDIACRAWLER_ROOT)

import config
from media_platform.weibo.client import WeiboClient

# ---------------------------------------------------------------------------
# Playwright stubs — WeiboClient needs a page/context ref but we drive
# everything via httpx + cookies.  These stubs satisfy the constructor.
# ---------------------------------------------------------------------------

class _StubContext:
    def __init__(self, cookie_dict: Dict[str, str]):
        self._cookies = cookie_dict

    async def cookies(self, urls=None):
        return [{"name": k, "value": v} for k, v in self._cookies.items()]


class _StubPage:
    def __init__(self, cookie_dict: Dict[str, str]):
        self.context = _StubContext(cookie_dict)

    async def goto(self, url: str):
        pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_cookie_input(raw: str) -> Tuple[str, Dict[str, str]]:
    """Accept a cookie string or a file path, return (header_str, dict)."""
    if os.path.isfile(raw):
        with open(raw, "r", encoding="utf-8") as fh:
            raw = fh.read().strip()
    cookie_dict: Dict[str, str] = {}
    for item in raw.rstrip(";").split(";"):
        item = item.strip()
        if "=" in item:
            k, v = item.split("=", 1)
            cookie_dict[k.strip()] = v.strip()
    header = "; ".join(f"{k}={v}" for k, v in cookie_dict.items())
    return header, cookie_dict


# Natural day boundary: 08:00 (skill.md definition)
_NATURAL_DAY_OFFSET = timedelta(hours=8)


def _to_natural_day(dt: datetime) -> str:
    """
    将 datetime 转换为自然日字符串 ``YYYY-MM-DD``。

    自然日边界为 08:00：小于 08:00 的时刻归属前一日。
    例如：2026-06-06 07:59 → "2026-06-05"
         2026-06-06 08:00 → "2026-06-06"
    """
    adjusted = dt - _NATURAL_DAY_OFFSET
    return adjusted.strftime("%Y-%m-%d")


def _parse_datetime(value: str) -> datetime:
    """Parse YYYY-MM-DD or YYYY-MM-DD HH:MM into datetime."""
    value = value.strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError(f"Unrecognized datetime format: {value}")


def strip_html(text: str) -> str:
    return re.sub(r"<.*?>", "", text)


def remove_noise_patterns(text: str) -> str:
    """
    Remove noise patterns from comment content: image placeholders,
    web link placeholders, and raw URLs. Return cleaned text.
    """
    text = re.sub(r'图片评论', '', text)
    text = re.sub(r'网页链接', '', text)
    text = re.sub(r'网页连接', '', text)
    text = re.sub(r'https?://\S+', '', text)
    return text.strip()


def is_empty_or_pure_emoji(text: str) -> bool:
    """
    Return True when *text* is empty / whitespace-only OR contains nothing
    but emoji, symbols, punctuation, and variation selectors.
    """
    if not text or not text.strip():
        return True

    cleaned = text.strip()

    # Has CJK characters? → real content, not pure emoji.
    if re.search(r"[一-鿿㐀-䶿]", cleaned):
        return False

    # Has Latin / Cyrillic / Arabic / Hangul / Kana letters?
    # We check the Unicode general category of every character.
    has_letter = False
    for ch in cleaned:
        cat = unicodedata.category(ch)
        if cat.startswith("L"):  # Letter (any script)
            has_letter = True
            break
        if cat.startswith("N"):  # Number
            has_letter = True
            break
    if has_letter:
        return False

    # Everything left is symbols, punctuation, marks, separators, emoji.
    return True


_MOBILE_BASE62_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _mblogid_to_mid(mblogid: str) -> str:
    """Convert a Weibo base-62 mblogid (e.g. QFtbrEEim) to a numeric mid."""
    # Pad to length multiple of 4, then decode each 4-char chunk → 7-digit group
    padding = 4 - len(mblogid) % 4
    if padding < 4:
        mblogid = "0" * padding + mblogid
    groups = []
    for i in range(0, len(mblogid), 4):
        val = 0
        for ch in mblogid[i:i + 4]:
            val = val * 62 + _MOBILE_BASE62_ALPHABET.index(ch)
        groups.append(str(val).zfill(7))
    return "".join(groups).lstrip("0")


def _extract_note_id_from_url(url: str) -> Optional[str]:
    """Pull the numeric note id from common Weibo URL formats."""
    # weibo.com/{uid}/{mblogid} — base62 → numeric mid, or plain numeric
    m = re.search(r"weibo\.com/\d+/([a-zA-Z0-9]+)", url)
    if m:
        slug = m.group(1)
        if slug.isdigit():
            return slug
        return _mblogid_to_mid(slug)

    patterns = [
        r"(?:m\.)?weibo\.(?:cn|com)/detail/(\d+)",
        r"m\.weibo\.cn/(?:status|detail)/(\d+)",
        r"weibo\.com/ttarticle/p/show\?id=(\d+)",
        r"m\.weibo\.cn/show\?id=(\d+)",
    ]
    for pat in patterns:
        m = re.search(pat, url)
        if m:
            return m.group(1)
    # Maybe the url IS the id
    if re.match(r"^\d{10,}$", url.strip()):
        return url.strip()
    return None


# ---------------------------------------------------------------------------
# Core — recursive comment fetch with filters
# ---------------------------------------------------------------------------

async def _process_comments_recursive(
    note_id: str,
    author_user_id: str,
    comment_list: List[Dict],
    depth: int = 0,
) -> List[Dict]:
    """
    Walk *comment_list* recursively, filter each node, and return a flat
    list of comments (sub-comments are flattened into the same list).
    """
    result: List[Dict] = []

    for comment in comment_list:
        if not isinstance(comment, dict):
            continue

        # ---- filter this comment first ----
        user_info = comment.get("user") or {}
        comment_user_id = str(user_info.get("id", ""))
        text_html = comment.get("text") or ""
        clean_text = remove_noise_patterns(strip_html(text_html))

        # (1) Author reply
        if comment_user_id == author_user_id:
            continue

        # (2) Empty after noise removal / pure emoji
        if is_empty_or_pure_emoji(clean_text):
            continue

        result.append({
            "comment_id": str(comment.get("id", "")),
            "parent_comment_id": str(comment.get("rootid", "")),
            "user_id": comment_user_id,
            "nickname": user_info.get("screen_name", ""),
            "avatar": user_info.get("profile_image_url", ""),
            "content": clean_text,
            "like_count": comment.get("like_count", 0),
            "sub_comment_count": comment.get("total_number", 0),
            "created_at": comment.get("created_at", ""),
            "ip_location": (comment.get("source") or "").replace("来自", ""),
            "depth": depth,
        })

        # ---- recurse into sub-comments, flatten into same list ----
        raw_subs: List[Dict] = comment.get("comments") or []
        if raw_subs:
            filtered_subs = await _process_comments_recursive(
                note_id, author_user_id, raw_subs, depth + 1,
            )
            result.extend(filtered_subs)

    return result


async def scrape_note_comments(
    client: WeiboClient,
    note_id: str,
    max_comments: int = 99999,
) -> Optional[Dict]:
    """
    Fetch every comment (including 楼中楼) for a single Weibo post,
    apply filters, and return a result dict.
    """
    # Get post metadata to learn the author's user_id.
    try:
        note_info = await client.get_note_info_by_id(note_id)
    except Exception as exc:
        print(f"WARN: Failed to fetch note info for {note_id}: {exc}", file=sys.stderr)
        return None

    mblog = (note_info or {}).get("mblog") or {}
    author_user_id = str((mblog.get("user") or {}).get("id", ""))
    note_text = strip_html(mblog.get("text") or "")
    note_created_at = mblog.get("created_at") or ""

    # Ensure sub-comments are enabled (they are consumed elsewhere by
    # get_comments_all_sub_comments, which gates on this config flag).
    config.ENABLE_GET_SUB_COMMENTS = True

    # Collect raw comment items from the paginated API.
    raw_comments: List[Dict] = []

    async def _collect(_note_id: str, comments: List[Dict]):
        raw_comments.extend(comments)

    try:
        await client.get_note_all_comments(
            note_id=note_id,
            crawl_interval=1.0,
            callback=_collect,
            max_count=max_comments,
        )
    except Exception as exc:
        print(f"WARN: Failed to fetch comments for {note_id}: {exc}", file=sys.stderr)

    # Process recursively → filter → tree structure.
    filtered = await _process_comments_recursive(
        note_id, author_user_id, raw_comments,
    )

    return {
        "note_id": note_id,
        "note_url": f"https://m.weibo.cn/detail/{note_id}",
        "note_text": note_text[:300] + ("..." if len(note_text) > 300 else ""),
        "author_user_id": author_user_id,
        "author_nickname": (mblog.get("user") or {}).get("screen_name", ""),
        "created_at": note_created_at,
        "comments_count_on_post": mblog.get("comments_count", 0),
        "attitudes_count": mblog.get("attitudes_count", 0),
        "reposts_count": mblog.get("reposts_count", 0),
        "total_comments_scraped": len(raw_comments),
        "total_after_filter": len(filtered),
        "comments": filtered,
    }


# ---------------------------------------------------------------------------
# User time-range mode
# ---------------------------------------------------------------------------

async def scrape_user_posts(
    client: WeiboClient,
    user_id: str,
    start_time: datetime,
    end_time: datetime,
    max_notes: int = 50,
) -> List[Dict]:
    """
    Fetch all posts by *user_id* within [start_time, end_time], then scrape
    comments for each matching post.

    When the target date is 5 or more days in the past, uses the time-scoped
    API (get_notes_by_creator_and_time) to avoid paginating through irrelevant
    recent posts. Otherwise uses the standard user-timeline API.
    """
    container_info = await client.get_creator_container_info(user_id)
    lfid = container_info.get("lfid_container_id") or f"107603{user_id}"

    raw_notes: List[Dict] = []
    days_diff = (datetime.now() - start_time).days

    if days_diff >= 5:
        # ---- Time-scoped path: add timescope filter to reduce pagination ----
        day_str = start_time.strftime("%Y-%m-%d")
        end_day_str = end_time.strftime("%Y-%m-%d")
        print(
            f"Date is {days_diff} days ago (>= 5), using time-scoped API for {day_str} ~ {end_day_str} ...",
            file=sys.stderr,
        )

        async def _collect_notes(notes: List[Dict]):
            filtered = [n for n in notes if n.get("card_type") == 9]
            raw_notes.extend(filtered)

        # Replicate the pagination loop from get_all_notes_by_creator_id
        # but with time scope appended to containerid.
        notes_has_more = True
        since_id = ""
        crawler_total_count = 0
        while notes_has_more and len(raw_notes) < max_notes:
            notes_res = await client.get_notes_by_creator_and_time(
                creator=user_id,
                container_id=lfid,
                since_id=since_id,
                start_time=day_str,
                end_time=end_day_str,
            )
            if not notes_res:
                print("WARN: empty response from time-scoped API", file=sys.stderr)
                break
            since_id = notes_res.get("cardlistInfo", {}).get("since_id", "0")
            if "cards" not in notes_res:
                break
            notes = notes_res["cards"]
            await _collect_notes(notes)
            await asyncio.sleep(1.0)
            crawler_total_count += 10
            if max_notes > 0 and len(raw_notes) >= max_notes:
                raw_notes = raw_notes[:max_notes]
                break
            notes_has_more = notes_res.get("cardlistInfo", {}).get("total", 0) > crawler_total_count

    else:
        # ---- Original path: scan user timeline (no time filter) ----
        async def _collect_notes(notes: List[Dict]):
            raw_notes.extend(notes)

        await client.get_all_notes_by_creator_id(
            creator_id=user_id,
            container_id=lfid,
            crawl_interval=1.0,
            callback=_collect_notes,
            max_notes=max_notes,
        )

    results: List[Dict] = []
    for note_wrapper in raw_notes:
        mblog = (note_wrapper.get("mblog") or {})
        if not mblog:
            # Some card formats wrap differently
            if "status" in note_wrapper:
                mblog = note_wrapper["status"]
            else:
                continue

        created_str = mblog.get("created_at") or ""
        try:
            created_dt = parsedate_to_datetime(created_str).replace(tzinfo=None)
        except (ValueError, TypeError):
            print(f"WARN: Could not parse date '{created_str}', skipping", file=sys.stderr)
            continue

        if not (start_time <= created_dt <= end_time):
            continue

        note_id = str(mblog.get("id", ""))
        if not note_id:
            continue

        print(f"Scraping comments for note {note_id} ({created_dt.date()}) ...", file=sys.stderr)
        result = await scrape_note_comments(client, note_id)
        if result:
            results.append(result)

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

async def _main():
    parser = argparse.ArgumentParser(
        description="Weibo Comment Scraper — fetch all comments with 楼中楼 and filtering",
    )
    # Auth
    parser.add_argument(
        "--cookies",
        help="Weibo cookie string OR path to a cookie file (default: .weibo_cookies in scripts dir)",
    )
    # Target (mutually exclusive groups in spirit)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--url", help="Weibo post URL")
    target.add_argument("--note-id", help="Weibo post numeric ID")
    target.add_argument("--user-id", help="Weibo user ID (for time-range scanning)")
    # Time range (only meaningful with --user-id)
    parser.add_argument("--start-time", help="Start date YYYY-MM-DD or YYYY-MM-DD HH:MM (user mode)")
    parser.add_argument("--end-time", help="End date YYYY-MM-DD or YYYY-MM-DD HH:MM (user mode); defaults to now")
    parser.add_argument("--max-notes", type=int, default=50,
                        help="Max posts to scan in user mode (default: 50)")
    # Output
    parser.add_argument("--output", "-o", help="Output JSON file path; auto-generated if omitted")
    # Misc
    parser.add_argument("--max-comments", type=int, default=99999,
                        help="Max comments per post (default: 99999 = all)")

    args = parser.parse_args()

    # ---- resolve cookies ----
    if not args.cookies:
        default_cookie_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".weibo_cookies")
        if os.path.isfile(default_cookie_file):
            args.cookies = default_cookie_file
        else:
            print(
                f"ERROR: --cookies not specified and default file not found: {default_cookie_file}",
                file=sys.stderr,
            )
            sys.exit(1)
    cookie_header, cookie_dict = parse_cookie_input(args.cookies)

    # ---- build WeiboClient ----
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

    # ---- validate login state ----
    print("Validating cookies ...", file=sys.stderr)
    try:
        ok = await client.pong()
    except Exception as exc:
        print(f"ERROR: Cookie validation request failed: {exc}", file=sys.stderr)
        sys.exit(1)

    if not ok:
        print(
            "ERROR: Cookie validation failed — login state not detected. "
            "Please refresh your Weibo cookies.",
            file=sys.stderr,
        )
        sys.exit(1)
    print("Cookies OK.", file=sys.stderr)

    # ---- run ----
    results: List[Dict] = []
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None

    if args.url or args.note_id:
        note_id = args.note_id or _extract_note_id_from_url(args.url)
        if not note_id:
            print("ERROR: Could not extract note ID from URL.", file=sys.stderr)
            sys.exit(1)
        print(f"Scraping comments for note {note_id} ...", file=sys.stderr)
        result = await scrape_note_comments(client, note_id, args.max_comments)
        if result:
            results.append(result)

    elif args.user_id:
        if not args.start_time:
            print("ERROR: --start-time is required with --user-id", file=sys.stderr)
            sys.exit(1)
        start_time = _parse_datetime(args.start_time)
        end_time = _parse_datetime(args.end_time) if args.end_time else datetime.now()
        print(
            f"Scanning posts by user {args.user_id} "
            f"from {start_time.date()} to {end_time.date()} ...",
            file=sys.stderr,
        )
        results = await scrape_user_posts(
            client, args.user_id, start_time, end_time, args.max_notes,
        )

    # ---- output ----
    out_str = json.dumps(results, ensure_ascii=False, indent=2)

    if args.output:
        # Explicit output path — write single file as-is
        os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(out_str)
        total = sum(r.get("total_after_filter", 0) for r in results)
        print(f"Done: {len(results)} posts, {total} comments → {args.output}", file=sys.stderr)
        return

    # Auto-generate output under WeiboExtractData/{nickname}/{YYYY-MM-DD}/
    out_dir = os.path.join(_WORKSPACE_ROOT, "WeiboExtractData")
    os.makedirs(out_dir, exist_ok=True)

    if not results:
        # Failed crawl — write the empty fallback under tmp/ so the
        # root WeiboExtractData dir stays clean. merge_by_day.py cleans these.
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        tmp_dir = os.path.join(out_dir, "tmp")
        os.makedirs(tmp_dir, exist_ok=True)
        filename = re.sub(r'[\\/:*?"<>|]', '_', f"weibo_{ts}.json")
        dump_path = os.path.join(tmp_dir, filename)
        with open(dump_path, "w", encoding="utf-8") as fh:
            fh.write(out_str)
        print(f"Done: 0 posts, 0 comments → {dump_path}", file=sys.stderr)
        return

    # Group results by natural day (08:00 boundary, per skill.md)
    day_groups: defaultdict = defaultdict(list)
    for r in results:
        try:
            day_key = _to_natural_day(parsedate_to_datetime(r["created_at"]))
        except (ValueError, TypeError):
            day_key = _to_natural_day(datetime.now())
        day_groups[day_key].append(r)

    nickname = results[0]["author_nickname"]
    nickname_safe = re.sub(r'[\\/:*?"<>|]', '_', nickname)

    output_files = []
    for day_key, day_results in day_groups.items():
        day_dir = os.path.join(out_dir, nickname_safe, day_key)
        os.makedirs(day_dir, exist_ok=True)

        if args.user_id:
            filename = f"{nickname_safe}_{day_key.replace('-', '')}.json"
        else:
            try:
                post_ts = parsedate_to_datetime(day_results[0]["created_at"]).strftime("%Y%m%d_%H%M")
            except (ValueError, TypeError):
                post_ts = datetime.now().strftime("%Y%m%d_%H%M")
            filename = f"{nickname_safe}_{post_ts}.json"

        filepath = os.path.join(day_dir, filename)
        with open(filepath, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(day_results, ensure_ascii=False, indent=2))
        output_files.append(filepath)

    total = sum(r.get("total_after_filter", 0) for r in results)
    print(f"Done: {len(results)} posts, {total} comments → {len(output_files)} file(s)", file=sys.stderr)
    for f in output_files:
        print(f"  {f}", file=sys.stderr)


def main():
    asyncio.run(_main())


if __name__ == "__main__":
    main()
