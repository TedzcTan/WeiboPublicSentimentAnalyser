# -*- coding: utf-8 -*-
"""
微博评论并行爬取结果 — 按自然日合并
======================================

并行 worker 每个帖子输出一个独立 JSON 文件（如 ``广州天气_20260606_1403.json``），
此脚本读取所有单帖 JSON，按 **自然日（08:00 至次日 08:00）** 重新分组，
合并为一个文件，遵循技能规定的目录结构：

    WeiboExtractData/{微博用户名}/{YYYY-MM-DD}/{微博用户名}_{YYYYMMDD}.json

自然日定义（与技能文档一致）：当日 08:00 至次日 08:00。
帖子的 ``created_at`` 时间 < 08:00 时归属前一日，>= 08:00 时归属当日。

同时清理：根目录及 ``tmp/`` 下的空 ``weibo_*_HHMMSS.json``（爬取失败的帖子）。
driver.py 在爬取失败时将空结果写入 ``WeiboExtractData/tmp/``，本脚本负责识别并清理。

用法:
  cd MediaCrawler
  uv run python ../.claude/skills/weibo-comment-scraper/scripts/merge_by_day.py

  # 指定扫描目录
  uv run python ../.claude/skills/weibo-comment-scraper/scripts/merge_by_day.py \\
      --base-dir ../WeiboExtractData

  # 合并后删除原单帖文件
  uv run python ../.claude/skills/weibo-comment-scraper/scripts/merge_by_day.py --cleanup

  # 仅合并指定昵称
  uv run python ../.claude/skills/weibo-comment-scraper/scripts/merge_by_day.py \\
      --nickname "广州天气"
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Dict, List, Set, Tuple

# Skill at <workspace>/.claude/skills/weibo-comment-scraper/scripts/merge_by_day.py
# Workspace root is 5 levels up
_WORKSPACE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)))
_DEFAULT_BASE_DIR = os.path.join(_WORKSPACE_ROOT, "WeiboExtractData")

# Natural day boundary: 08:00 (skill.md definition)
_NATURAL_DAY_OFFSET = timedelta(hours=8)

# Matches individual post files: {nickname}_{YYYYMMDD}_{HHMM}.json
_INDIVIDUAL_FILE_RE = re.compile(
    r"^(.+)_(\d{8})_(\d{4})\.json$"
)

# Matches already-merged files: {nickname}_{YYYYMMDD}.json  (no underscore + time)
_MERGED_FILE_RE = re.compile(
    r"^(.+)_(\d{8})\.json$"
)

# Matches root-level "weibo_" prefixed files (empty results from failed posts)
_ROOT_EMPTY_FILE_RE = re.compile(
    r"^weibo_\d{8}_\d{6}\.json$"
)


def _parse_created_at(created_str: str) -> datetime:
    """解析微博 ``created_at`` 字段为 datetime，失败返回 datetime.min。"""
    if not created_str:
        return datetime.min
    try:
        return parsedate_to_datetime(created_str)
    except (ValueError, TypeError):
        try:
            return datetime.fromisoformat(created_str)
        except (ValueError, TypeError):
            return datetime.min


def _to_natural_day(dt: datetime) -> str:
    """
    将 datetime 转换为自然日字符串 ``YYYY-MM-DD``。

    自然日边界为 08:00：小于 08:00 的时刻归属前一日。
    例如：2026-06-06 07:59 → "2026-06-05"
         2026-06-06 08:00 → "2026-06-06"
    """
    if dt == datetime.min:
        return datetime.now().strftime("%Y-%m-%d")
    adjusted = dt - _NATURAL_DAY_OFFSET
    return adjusted.strftime("%Y-%m-%d")


def _is_individual_file(filename: str) -> bool:
    """单帖文件：``{nickname}_{YYYYMMDD}_{HHMM}.json``"""
    return bool(_INDIVIDUAL_FILE_RE.match(filename))


def _is_root_empty_file(filename: str) -> bool:
    """根目录空文件：``weibo_YYYYMMDD_HHMMSS.json``"""
    return bool(_ROOT_EMPTY_FILE_RE.match(filename))


def collect_files(
    base_dir: str,
    nickname_filter: str = None,
) -> Tuple[List[Path], List[Path]]:
    """
    遍历 *base_dir* 收集文件，不做日期分组（分组由加载后按自然日进行）。

    Returns:
        (individual_files, root_empty_files)
    """
    base = Path(base_dir).resolve()
    individual_files: List[Path] = []
    root_empty_files: List[Path] = []

    for file_path in base.rglob("*.json"):
        if not file_path.is_file():
            continue

        fname = file_path.name
        rel_parent = file_path.parent

        # Empty fallback files: root-level OR under tmp/ (driver.py writes
        # failed-crawl empty results to WeiboExtractData/tmp/weibo_*.json)
        if _is_root_empty_file(fname) and (
            rel_parent == base or rel_parent == base / "tmp"
        ):
            root_empty_files.append(file_path)
            continue

        # Individual post files
        if not _is_individual_file(fname):
            continue

        # Apply nickname filter (match the nickname folder or filename prefix)
        if nickname_filter:
            nickname_safe = re.sub(r'[\\/:*?"<>|]', '_', nickname_filter)
            # Check parent dir name (should be the nickname folder)
            parent_nick = rel_parent.parent.name if rel_parent.parent != base else rel_parent.name
            if parent_nick != nickname_safe and not fname.startswith(nickname_safe + "_"):
                continue

        individual_files.append(file_path)

    return individual_files, root_empty_files


def load_all_posts(file_paths: List[Path]) -> Tuple[List[Dict], List[Path]]:
    """
    读取所有单帖 JSON 文件，返回 (posts, skipped_paths)。
    每个 post dict 会附带 ``_source_path`` 用于后续清理。

    去重：相同 note_id 只保留一份。
    跳过：空列表、解析失败的文件。
    """
    all_posts: List[Dict] = []
    seen_note_ids: Set[str] = set()
    skipped: List[Path] = []

    for fp in sorted(file_paths):
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, Exception) as exc:
            print(f"WARN: 解析失败 {fp}: {exc}", file=sys.stderr)
            skipped.append(fp)
            continue

        if not isinstance(data, list):
            skipped.append(fp)
            continue

        has_valid_post = False
        for post in data:
            if not isinstance(post, dict):
                continue
            nid = str(post.get("note_id", ""))
            if not nid:
                continue
            if nid in seen_note_ids:
                continue
            seen_note_ids.add(nid)
            # Attach source path for later cleanup
            post["_source_path"] = str(fp)
            all_posts.append(post)
            has_valid_post = True

        if not has_valid_post:
            # Empty result file (post had no comments after filtering)
            skipped.append(fp)

    return all_posts, skipped


def group_by_natural_day(posts: List[Dict]) -> Dict[str, List[Dict]]:
    """
    按 (nickname, 自然日) 分组。

    自然日基于每个帖子的 ``created_at`` 字段 + 08:00 偏移计算。
    nickname 取自 ``author_nickname`` 字段。
    同时收集每个帖子来源文件路径（``_source_path``）用于后续清理。
    """
    groups: Dict[str, List[Dict]] = defaultdict(list)

    for post in posts:
        created_str = post.get("created_at", "")
        dt = _parse_created_at(created_str)
        natural_day = _to_natural_day(dt)

        nickname = str(post.get("author_nickname", "unknown"))
        nickname_safe = re.sub(r'[\\/:*?"<>|]', '_', nickname)

        group_key = f"{nickname_safe}|{natural_day}"
        groups[group_key].append(post)

    return dict(groups)


def write_merged_file(
    posts: List[Dict],
    nickname: str,
    day_key: str,
    base_dir: str,
) -> Path:
    """
    写入合并文件到 ``{base_dir}/{nickname}/{day_key}/{nickname}_{YYYYMMDD}.json``。

    如果目标文件已存在（幂等合并），会与已有内容合并去重。
    """
    base = Path(base_dir).resolve()
    date_compact = day_key.replace("-", "")

    day_dir = base / nickname / day_key
    day_dir.mkdir(parents=True, exist_ok=True)

    output_name = f"{nickname}_{date_compact}.json"
    output_path = day_dir / output_name

    # Idempotent: merge with existing file if present
    existing_posts: List[Dict] = []
    if output_path.exists():
        try:
            existing_posts = json.loads(output_path.read_text(encoding="utf-8"))
            if not isinstance(existing_posts, list):
                existing_posts = []
        except Exception:
            existing_posts = []

    seen = set()
    combined: List[Dict] = []
    for p in existing_posts + posts:
        nid = str(p.get("note_id", ""))
        if nid and nid not in seen:
            seen.add(nid)
            # Strip internal _source_path before writing
            clean = {k: v for k, v in p.items() if k != "_source_path"}
            combined.append(clean)

    combined.sort(key=lambda p: _parse_created_at(p.get("created_at", "")))

    output_path.write_text(
        json.dumps(combined, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output_path


def cleanup_files(file_paths: List[Path], dry_run: bool = False) -> int:
    """删除指定文件列表，返回删除数量。"""
    count = 0
    for fp in file_paths:
        if dry_run:
            print(f"  [dry-run] 将删除: {fp}", file=sys.stderr)
            count += 1
            continue
        try:
            fp.unlink()
            print(f"  已删除: {fp}", file=sys.stderr)
            count += 1
        except OSError as exc:
            print(f"WARN: 无法删除 {fp}: {exc}", file=sys.stderr)
    return count


def main():
    parser = argparse.ArgumentParser(
        description="合并微博评论并行爬取的单帖 JSON，按自然日（08:00边界）合并输出",
    )
    parser.add_argument(
        "--base-dir", default=_DEFAULT_BASE_DIR,
        help=f"WeiboExtractData 目录路径（默认: {_DEFAULT_BASE_DIR}）",
    )
    parser.add_argument(
        "--nickname", default=None,
        help="仅合并指定微博用户昵称的文件",
    )
    parser.add_argument(
        "--cleanup", action="store_true",
        help="合并后删除原始单帖文件和根目录空文件",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="仅扫描预览，不实际合并或删除",
    )
    args = parser.parse_args()

    base_dir = os.path.abspath(args.base_dir)
    if not os.path.isdir(base_dir):
        print(f"ERROR: 目录不存在: {base_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"扫描目录: {base_dir}", file=sys.stderr)

    # ---- 1. 收集文件 ----
    individual_files, root_empty_files = collect_files(base_dir, args.nickname)

    if not individual_files and not root_empty_files:
        print("没有找到需要合并的单帖 JSON 文件。", file=sys.stderr)
        return

    # ---- 2. 处理根目录空文件 ----
    if root_empty_files:
        print(
            f"\n发现 {len(root_empty_files)} 个根目录空文件（无评论结果）:",
            file=sys.stderr,
        )
        for fp in root_empty_files:
            print(f"  {fp}", file=sys.stderr)
        if args.cleanup:
            deleted = cleanup_files(root_empty_files, args.dry_run)
            print(f"清理了 {deleted} 个根目录空文件", file=sys.stderr)
        elif not args.dry_run:
            print("提示: 使用 --cleanup 参数可自动删除这些空文件", file=sys.stderr)

    if not individual_files:
        return

    # ---- 3. 加载所有帖子 ----
    print(f"\n加载 {len(individual_files)} 个单帖文件 ...", file=sys.stderr)
    all_posts, skipped_files = load_all_posts(individual_files)
    print(
        f"有效帖子: {len(all_posts)}，跳过空文件: {len(skipped_files)}",
        file=sys.stderr,
    )

    if not all_posts:
        if skipped_files and args.cleanup:
            cleanup_files(skipped_files, args.dry_run)
        return

    # ---- 4. 按自然日分组 ----
    groups = group_by_natural_day(all_posts)

    # ---- 5. 输出合并文件 ----
    print(f"\n按自然日（08:00边界）分为 {len(groups)} 组：", file=sys.stderr)

    total_posts = 0
    merged_files: List[Path] = []

    for group_key, posts in sorted(groups.items()):
        nickname, day_key = group_key.split("|", 1)
        print(
            f"\n  [{nickname} | {day_key}] {len(posts)} 个帖子",
            file=sys.stderr,
        )

        if args.dry_run:
            # Show source files that contributed
            src_files = set(p.get("_source_path", "") for p in posts)
            for src in sorted(src_files):
                if src:
                    print(f"    [dry-run] 来源: {src}", file=sys.stderr)
            continue

        output_path = write_merged_file(posts, nickname, day_key, base_dir)
        merged_files.append(output_path)
        total_posts += len(posts)
        print(f"    → 合并输出: {output_path}", file=sys.stderr)

    # ---- 6. 清理 ----
    if args.cleanup:
        # Collect all source files that were successfully merged
        all_source_paths = set()
        for posts in groups.values():
            for p in posts:
                src = p.get("_source_path", "")
                if src:
                    all_source_paths.add(Path(src))

        # Also include skipped (empty) files for cleanup
        all_cleanup = list(all_source_paths) + skipped_files
        if all_cleanup:
            print(f"\n清理 {len(all_cleanup)} 个单帖文件 ...", file=sys.stderr)
            deleted = cleanup_files(all_cleanup, args.dry_run)
            total_deleted = deleted
            print(f"共清理 {total_deleted} 个单帖文件", file=sys.stderr)

    # ---- 7. 汇总 ----
    if args.dry_run:
        print(
            f"\n[dry-run] 共 {total_posts} 个帖子，{len(groups)} 个自然日分组",
            file=sys.stderr,
        )
    else:
        print(
            f"\n完成: {total_posts} 个帖子 → {len(merged_files)} 个合并文件",
            file=sys.stderr,
        )
        for f in merged_files:
            print(f"  {f}", file=sys.stderr)


if __name__ == "__main__":
    main()
