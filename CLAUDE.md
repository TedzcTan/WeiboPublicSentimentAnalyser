# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

本仓库包含三个主要部分：
- **MediaCrawler** — 多平台自媒体爬虫（小红书、抖音、快手、B站、微博、贴吧、知乎）
- **WeiboExtractData** — 微博评论爬取结果输出目录
- **slides-workspace** — open-slide 幻灯片项目，用于将舆情分析结果生成演示文稿
- **`.claude/skills/`** — 微博评论技能链：爬取 → 情感分类 → 话题聚类 → 舆情分析报告 → 幻灯片生成
- **舆情分析/** — 舆情分析报告 Markdown 输出目录

## 常用命令

所有命令在 `MediaCrawler` 目录下执行，使用 `uv` 作为包管理器。

```bash
# 安装依赖
cd MediaCrawler && uv sync

# 运行爬虫（默认配置来自 config/base_config.py）
uv run main.py

# 命令行覆盖配置
uv run main.py --platform wb --type search --keywords "广州天气"

# 初始化数据库表结构
uv run main.py --init_db sqlite

# 启动 WebUI API 服务
cd MediaCrawler && uvicorn api.main:app --port 8080 --reload

# 构建文档站点
cd MediaCrawler && npm run docs:dev

# 微博评论爬虫（单帖 / 用户时间范围）
cd MediaCrawler
uv run python ../.claude/skills/weibo-comment-scraper/scripts/driver.py --note-id "4982041758140155"
uv run python ../.claude/skills/weibo-comment-scraper/scripts/driver.py --user-id "5756404150" --start-time "2026-01-01"

# 微博评论情感分类
uv run python ../.claude/skills/weibo-sentiment-classifier/scripts/sentiment_classifier.py \
    --input "../WeiboExtractData/广州天气/2026-05-22/广州天气_20260522.json"

# 运行测试
cd MediaCrawler && uv run pytest

# ─── open-slide 幻灯片相关 ───
# 初始化幻灯片项目（首次使用需要）
cd slides-workspace && npm install

# 启动幻灯片开发服务器
cd slides-workspace && npm run dev

# 构建静态 HTML（输出到 slides-workspace/dist/）
cd slides-workspace && npm run build

# 预览构建结果
cd slides-workspace && npm run preview
```

## 核心架构

### 爬虫抽象层 (`base/`)

- `AbstractCrawler` — 所有平台爬虫的基类，定义 `start()`、`search()`、`launch_browser()` 接口
- `AbstractLogin` — 登录基类，支持扫码/手机号/Cookie 三种方式
- `AbstractStore` — 存储基类，定义 `store_content()`、`store_comment()`、`store_creator()`

### 平台模块 (`media_platform/`)

每个平台是一个包，结构统一：

```
media_platform/<platform>/
├── client.py    # API 客户端，封装 HTTP 请求（继承 ProxyRefreshMixin）
├── core.py      # 爬虫核心逻辑（继承 AbstractCrawler）
├── login.py     # 登录实现（继承 AbstractLogin）
├── field.py     # 平台枚举、数据模型定义
├── help.py      # 辅助函数（去重、过滤等）
└── exception.py # 平台专用异常
```

`main.py` 中的 `CrawlerFactory` 根据 `config.PLATFORM` 值选择对应的爬虫实现。

### 配置系统 (`config/`)

- `base_config.py` — 全局配置（平台、登录方式、爬取类型、存储选项、CDP 模式等）
- 每个平台有独立配置文件（`xhs_config.py`、`weibo_config.py` 等），通过 `base_config.py` 末尾的 `import *` 汇入

### 存储层 (`store/`)

每个平台实现 `_store_impl.py`，根据 `SAVE_DATA_OPTION` 支持多种存储后端：
`csv` | `json` | `jsonl` | `db`(MySQL) | `sqlite` | `mongodb` | `excel` | `postgres`

### CDP 模式 (`tools/cdp_browser.py`)

通过 Chrome DevTools Protocol 连接用户本地浏览器，使用真实浏览器环境（含 Cookie、扩展），反检测能力强。配置项：
- `ENABLE_CDP_MODE` — 启用 CDP
- `CDP_CONNECT_EXISTING` — 连接已打开的浏览器而非启动新实例

### API WebUI (`api/`)

FastAPI 服务，提供 REST API + WebSocket 控制爬虫。前端静态文件在 `api/webui/`。

### 缓存 (`cache/`)

支持本地缓存和 Redis 缓存的抽象层，工厂模式创建。

### 代理池 (`proxy/`)

IP 代理池支持，提供商包括快代理、豌豆HTTP 等。

## 数据流

1. `main.py` 解析命令行参数 → 覆盖 `config` 模块的全局变量
2. `CrawlerFactory` 根据 `config.PLATFORM` 实例化对应爬虫
3. 爬虫 `start()` → 登录 → 根据 `CRAWLER_TYPE` 执行 search/detail/creator
4. API 客户端 (`client.py`) 通过 `httpx` + Playwright 浏览器上下文发起请求
5. 数据通过 `store/` 层持久化到指定后端

## 微博技能链

位于 `.claude/skills/`，五个技能形成完整分析流水线，均从 `MediaCrawler/` 目录执行。

| 技能 | 功能 | 输入 | 输出 |
|---|---|---|---|
| `weibo-comment-scraper` | 爬取评论（含楼中楼递归） | 帖子URL/ID 或 用户ID+时间范围 | JSON |
| `weibo-sentiment-classifier` | 情感分类（正面/负面/中性） | 爬虫输出的 JSON | EXCEL（汇总+明细） |
| `weibo-topic-clusterer` | AI语义聚类，提取核心话题 | 爬虫输出的 JSON | AI分析结果（话题名/频次/代表评论） |
| `weibo-opinion-analyzer` | 一键舆情分析，串联上述三步 | 日期 + 账号名 | Markdown 分析报告 + 可选PPT |
| `weibo-to-slides` | 舆情报告转演示文稿 | 分析报告 MD + 情感 EXCEL | open-slide React 幻灯片 |

- 爬虫复用 MediaCrawler 的 `WeiboClient`，Cookie 认证，不启动浏览器
- 情感分类由 Claude AI 直接在对话中逐条判断，无需外部 API 或本地词典
- 输出目录：爬取结果 → `WeiboExtractData/`，分析报告 → `舆情分析/`
- 幻灯片输出到 `slides-workspace/slides/`，基于 open-slide 框架（React + Vite）
- 完整流水线：爬取 → 情感分类 → 话题聚类 → 报告 → **PPT演示文稿**

## open-slide 幻灯片项目

`slides-workspace/` 是基于 [open-slide](https://github.com/1weiho/open-slide) 框架的幻灯片项目，用于将舆情分析结果自动生成精美的演示文稿。

### 项目结构

```
slides-workspace/
├── slides/           # 幻灯片目录，每个子目录一个幻灯片
│   └── <id>/
│       ├── index.tsx # React 组件（1920×1080 画布）
│       └── assets/   # 幻灯片专用资源
├── themes/           # 主题定义（markdown 格式）
├── assets/           # 全局资源
└── .claude/skills/   # open-slide 自带技能（自动同步，不要手动修改）
    ├── create-slide       # 创建新幻灯片
    ├── slide-authoring    # 幻灯片编写技术参考
    ├── apply-comments     # 应用检查器批注
    ├── create-theme       # 创建/提取主题
    └── current-slide      # 解析当前幻灯片上下文
```

### open-slide 命令

```bash
# 启动开发服务器（带 HMR 热更新）
cd slides-workspace && npm run dev

# 构建静态 HTML（输出到 dist/）
cd slides-workspace && npm run build

# 预览构建结果
cd slides-workspace && npm run preview
```

### 幻灯片编写核心规则

- 每个幻灯片是一组零参数 React 组件（`Page[]`），渲染到固定 1920×1080 画布
- 文件结构：`export const design`（配色） + `export const meta`（元数据） + `export default [Page1, Page2, ...] satisfies Page[]`
- 使用绝对像素值，内联 `style`，不引入额外依赖
- 内容必须在 1080px 高度内（含 padding 100-160px），不可滚动
- 详细规范见 `slides-workspace/.claude/skills/slide-authoring/SKILL.md`

### 舆情→幻灯片集成

1. 运行 `weibo-opinion-analyzer` 生成分析报告
2. 调用 `weibo-to-slides` 技能，传入报告路径
3. 幻灯片自动生成到 `slides-workspace/slides/<date>-<account>-report/index.tsx`
4. `npm run dev` 实时预览，`npm run build` 构建部署

## CLAUDE.md 自动提交规范

CLAUDE.md 及 `.claude/skills/` 的修改通过 `PostToolUse` hook 自动提交，无需手动执行 git 命令。Hook 配置在 `.claude/settings.local.json` 中，当 `Edit` 或 `Write` 工具修改了以下文件时自动触发：
- `CLAUDE.md` → 提交信息 `chore: 更新 CLAUDE.md 项目文档`
- `.claude/skills/` 目录下的文件 → 提交信息 `chore: 更新 Claude Code skills`
