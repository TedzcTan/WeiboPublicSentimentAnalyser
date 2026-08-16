---
name: weibo-comment-scraper
description: 爬取微博评论（含楼中楼递归）。支持指定帖子链接和用户时间范围两种模式。自动过滤作者回复、空内容和纯表情评论。
---

## 执行模式

本技能直接在对话上下文中执行，通过 **Bash 后台进程** 实现并行爬取，不依赖 Agent 子代理。

- **单帖爬取**（`--url` / `--note-id`）：直接运行一次 driver.py
- **用户时间范围**（`--user-id`）：发现 → 分组 → Bash 并行 worker → 合并 → 汇总
- 每个 worker 是一个 Bash 后台进程（`&`），负责 5 个帖子的评论爬取
- 并行完成后用 `merge_by_day.py` 将单帖 JSON 按自然日合并为一个文件

---

# 微博评论爬虫

基于 MediaCrawler 的 API 客户端，爬取微博帖子的**全部评论**（包括嵌套的楼中楼子评论），
输出清洗后的 JSON，自动过滤作者回复、空内容和纯表情。

所有命令从 **MediaCrawler 项目根目录** 执行。

## 前置条件

- Python 3.11+
- MediaCrawler 的依赖已安装（`httpx`、`tenacity`、`playwright` 等）
- **有效的微博 Cookie** — 本脚本不启动浏览器，必须提供已登录微博账号的 Cookie 字符串或 Cookie 文件。

  最少需要的 Cookie 字段：`SUB`、`SUBP`、`M_WEIBO_PARAMS`。

  获取方式：在浏览器中登录 `m.weibo.cn`，打开开发者工具 → Application → Cookies，复制对应字段的值。

## 快速开始

Cookie 默认从技能目录的 `scripts/.weibo_cookies` 文件读取，无需每次指定。

### 按帖子链接爬取

```
cd MediaCrawler
uv run python ../.claude/skills/weibo-comment-scraper/scripts/driver.py \
    --url "https://m.weibo.cn/detail/4982041758140155"
```

### 按帖子ID爬取

```
uv run python ../.claude/skills/weibo-comment-scraper/scripts/driver.py \
    --note-id "4982041758140155"
```

### 按用户ID和时间范围爬取

```
uv run python ../.claude/skills/weibo-comment-scraper/scripts/driver.py \
    --user-id "5756404150" \
    --start-time "2026-01-01" \
    --end-time "2026-05-22"
```

如需使用其他 Cookie，通过 `--cookies` 指定字符串或文件路径即可。

输出默认保存到 `ClaudeWorkSpace/WeiboExtractData/{微博用户名}/{YYYY-MM-DD}/` 目录下，也可通过 `-o` 自定义单个文件路径。文件名规则：
- 单条微博模式（`--note-id`）：每个帖子独立输出 `{微博用户名}_{发布时间戳(YYYYMMDD_HHMM)}.json`，并行完成后由 `merge_by_day.py` 合并
- 用户时间范围模式（`--user-id`）：直接输出 `{微博用户名}_{YYYYMMDD}.json`（跨自然日自动拆分）
- **最终结果**：无论哪种模式，每个自然日一个合并文件 `{微博用户名}_{YYYYMMDD}.json`

## 自然日定义

用户说"X月X日"时，时间范围统一为 **当日 08:00 至次日 08:00**。

| 用户输入 | start_time | end_time |
|---|---|---|
| "6月6日" | `2026-06-06 08:00` | `2026-06-07 08:00` |
| "6月6-7日" | `2026-06-06 08:00` | `2026-06-08 08:00` |
| "6月6日0点" | `2026-06-06 00:00` | `2026-06-06 23:59` |

用户明确指定时间时以用户为准。

## 时间范围模式：发现 → 分组 → 并行 → 合并

收到 `--user-id` + 时间范围任务后，按以下流程执行。

### 第一步：发现帖子链接

通过微博 API 翻页获取用户帖子，使用 `reference/discover.py` 收集时间范围内的全部 note_id：

```bash
cd MediaCrawler
uv run python ../.claude/skills/weibo-comment-scraper/reference/discover.py \
    --user-id "{user_id}" \
    --start "{start_time}" \
    --end "{end_time}" \
    > _note_ids.txt
```

参数说明见 `reference/discover.py --help`。输出每行一个 note_id，stderr 输出总数。

### 第二步：分组并行

将 note_ids 按 5 个一组分成多个批次，每个批次写成一个 shell 脚本，然后全部并行执行：

```bash
cd MediaCrawler
IDS=(id1 id2 id3 id4 id5 id6 id7 id8)  # 替换为实际列表

BATCH_SIZE=5
COUNT=0
for ((i=0; i<${#IDS[@]}; i+=BATCH_SIZE)); do
    COUNT=$((COUNT+1))
    BATCH=("${IDS[@]:i:BATCH_SIZE}")
    (
        for nid in "${BATCH[@]}"; do
            uv run python ../.claude/skills/weibo-comment-scraper/scripts/driver.py --note-id "$nid"
        done
        echo "BATCH_DONE:$COUNT"
    ) &
done

echo "已启动 $COUNT 个并行 worker（每 worker 5 条）"
wait
echo "全部 worker 完成"
```

### 第三步：合并

等待所有 worker 完成后，每个帖子各自生成了独立的 `{昵称}_{YYYYMMDD_HHMM}.json` 文件。
使用 `merge_by_day.py` 将同一自然日的帖子合并为一个 JSON 文件，并清理原始散文件、根目录及 `tmp/` 下的空文件（爬取失败的帖子）：

```bash
cd MediaCrawler
uv run python ../.claude/skills/weibo-comment-scraper/scripts/merge_by_day.py \
    --base-dir ../WeiboExtractData --cleanup
```

合并后输出结构：

```
WeiboExtractData/
├── {微博用户名}/
│   └── {YYYY-MM-DD}/
│       └── {微博用户名}_{YYYYMMDD}.json   ← 合并后的唯一结果
```

`merge_by_day.py` 参数：

| 参数 | 说明 |
|---|---|
| `--base-dir` | WeiboExtractData 目录路径 |
| `--nickname` | 可选，仅合并指定昵称的文件 |
| `--cleanup` | 合并后删除原始单帖文件、根目录空文件及 `tmp/` 下的失败空文件 |
| `--dry-run` | 仅扫描预览，不实际合并或删除 |

合并后统计帖子总数、评论总数，汇总报告。

## 完整参数列表

| 参数 | 是否必填 | 说明 |
|---|---|---|
| `--cookies` | 可选 | Cookie 字符串或文件路径（默认读取 `scripts/.weibo_cookies`） |
| `--url` | 三选一 | 微博帖子链接 |
| `--note-id` | 三选一 | 微博帖子数字ID |
| `--user-id` | 三选一 | 微博用户ID（时间范围模式） |
| `--start-time` | 用户模式必填 | 起始日期或时间 `YYYY-MM-DD` 或 `YYYY-MM-DD HH:MM` |
| `--end-time` | 可选 | 结束日期或时间（默认当前时间） |
| `--max-notes` | 可选 | 用户模式下最多扫描的帖子数（默认 50） |
| `--max-comments` | 可选 | 每个帖子最多爬取的评论数（默认 99999 即全部） |
| `-o` / `--output` | 可选 | JSON 输出文件路径（默认自动生成；爬取失败时输出到 `WeiboExtractData/tmp/weibo_时间戳.json`） |

`--url`、`--note-id`、`--user-id` 三者必须且只能提供一个。

## 输出格式

```json
[{
  "note_id": "4982041758140155",
  "note_url": "https://m.weibo.cn/detail/4982041758140155",
  "note_text": "帖子正文前300字...",
  "author_user_id": "5756404150",
  "author_nickname": "用户名",
  "created_at": "Mon Jan 15 12:30:00 +0800 2026",
  "comments_count_on_post": 523,
  "attitudes_count": 1200,
  "reposts_count": 45,
  "total_comments_scraped": 500,
  "total_after_filter": 412,
  "comments": [
    {
      "comment_id": "xxx",
      "parent_comment_id": "",
      "user_id": "12345",
      "nickname": "评论者",
      "avatar": "https://...",
      "content": "评论内容（已去除HTML标签）",
      "like_count": 10,
      "sub_comment_count": 3,
      "created_at": "Mon Jan 15 13:00:00 +0800 2026",
      "ip_location": "北京",
      "depth": 0
    },
    {
      "comment_id": "yyy",
      "parent_comment_id": "xxx",
      "user_id": "67890",
      "nickname": "回复者",
      "content": "回复内容",
      "depth": 1
    }
  ]
}]
```

字段说明：
- `depth`: 0 = 一级评论，1 = 二级回复，2+ = 更深层嵌套
- `comments_count_on_post`: 帖子上显示的总评论数
- `attitudes_count`: 帖子点赞数
- `reposts_count`: 帖子转发数
- `total_comments_scraped`: API 返回的原始评论数（过滤前）
- `total_after_filter`: 过滤后的评论总数（含所有子评论）
- `parent_comment_id`: 父评论ID，一级评论为空字符串

## 过滤规则

以下规则在每一层评论（包括楼中楼）都会生效（按顺序执行）：

1. **作者回复** — 评论者的 `user_id` 与帖子作者的 `user_id` 相同 → 跳过
2. **噪声清洗** — 去除 HTML 标签后，移除「图片评论」「网页链接」「网页连接」及 URL 链接，清洗后若为空则跳过
3. **空内容** — 去除 HTML 标签后文本为空或仅空白字符 → 跳过
4. **纯表情** — 内容只包含 emoji、符号和标点，不含任何中日韩文字、拉丁字母或数字 → 跳过

## 注意事项

- **Cookie 有效期**：微博 Cookie（尤其是 `SUB`）通常几天后就会过期。如果返回空结果或认证失败，请在浏览器中重新登录 `m.weibo.cn` 获取新 Cookie。
- **请求频率**：脚本在每个 API 分页之间休眠 1 秒。微博仍可能对高频请求进行风控 — 如果遇到 432 错误或空响应，请适当减少 `--max-notes` 或增加等待时间后重试。
- **无需浏览器**：本脚本不启动 Playwright/Chromium。它复用了 MediaCrawler 的 `WeiboClient` 并通过存根对象替代浏览器依赖，所有 API 调用均通过 `httpx` + Cookie 完成。
- **用户模式分页**：`--max-notes` 限制扫描的帖子总数（包括时间范围外的帖子也会被扫描但被过滤）。如果预期中的帖子没有出现，请增大该值（默认 50）。
- **楼中楼深度**：微博 API 将子评论嵌套在父评论的 `comments` 字段中。脚本会递归遍历任意深度，但实际微博数据很少超过 2-3 层。
- **输出目录**：不指定 `-o` 时，结果按 `WeiboExtractData/{微博用户名}/{YYYY-MM-DD}/` 层级自动分类存放。用户时间范围模式下，跨越多个自然日的数据会按天拆分到不同文件。**爬取失败**（无任何结果）时，空结果文件会写入 `WeiboExtractData/tmp/weibo_时间戳.json`，由 `merge_by_day.py --cleanup` 识别并清理。

## 验证码处理

微博 API 对高频请求会触发验证码（`errno: -100`，返回 captcha 页面）。遇到验证码时：

1. **立即停止**当前请求，不要继续重试（tenacity 重试也无效）
2. **告知用户**"微博触发了验证码保护，等待 5-10 分钟后自动重试"
3. **等待 300-600 秒**让验证码冷却
4. **自动重试**：降低请求频率（增大 `crawl_interval`，减少单次 `max_notes`）
5. 重试仍失败则终止，建议用户等待更长时间

**预防**：单次 `max_notes` 不宜超过 200；连续爬取多次时应间隔 30 秒以上。

## 常见问题

| 现象 | 可能原因 | 解决方法 |
|---|---|---|
| Cookie 验证失败 | Cookie 已过期或格式错误 | 从 `m.weibo.cn` 浏览器会话中重新复制 Cookie |
| 获取帖子信息时 `DataFetchError` | 帖子ID不存在或为私密帖 | 在浏览器中打开该链接确认是否可以访问 |
| 评论列表为空 | 帖子无评论，或 Cookie 权限不足 | 用无痕模式打开帖子确认是否限制了评论查看 |
| 无法从URL提取帖子ID | 不支持的链接格式 | 直接使用 `--note-id` 传入数字ID |
| 触发验证码（errno: -100） | 请求频率过高被风控 | 遵循上方「验证码处理」流程：停止→等待5-10分钟→重试 |
