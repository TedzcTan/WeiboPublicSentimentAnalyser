#!/usr/bin/env python3
"""
PostToolUse Hook — 自动提交 CLAUDE.md 和 .claude/skills/ 下的变更。

当 Edit 或 Write 工具修改了以下文件时自动执行 git add + git commit：
  - CLAUDE.md          → chore: 更新 CLAUDE.md 项目文档
  - .claude/skills/**  → chore: 更新 Claude Code skills
"""

import json
import os
import subprocess
import sys


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, IOError):
        print("[post_tool_use_git] 跳过：无法读取 stdin JSON", file=sys.stderr)
        return

    file_path = data.get("tool_input", {}).get("file_path", "")
    if not file_path:
        print("[post_tool_use_git] 跳过：无 file_path", file=sys.stderr)
        return

    # 统一为 Unix 风格路径
    normalized = file_path.replace("\\", "/")

    # 判断提交类型
    if os.path.basename(file_path) == "CLAUDE.md":
        message = "chore: 更新 CLAUDE.md 项目文档"
    elif ".claude/skills/" in normalized:
        message = "chore: 更新 Claude Code skills"
    else:
        print(f"[post_tool_use_git] 跳过：{file_path} 不在监听范围内", file=sys.stderr)
        return

    print(f"[post_tool_use_git] 检测到文件变更: {file_path}")
    print(f"[post_tool_use_git] 提交信息: {message}")

    subprocess.run(["git", "add", file_path], check=True)
    subprocess.run(["git", "commit", "-m", message], check=True)

    print(f"[post_tool_use_git] 提交完成 ✓", file=sys.stderr)


if __name__ == "__main__":
    main()
