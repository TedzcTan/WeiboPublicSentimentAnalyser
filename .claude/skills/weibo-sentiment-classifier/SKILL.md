---
name: weibo-sentiment-classifier
description: 对微博评论爬取结果进行情感分类（正面/负面/中性），基于 Claude AI 逐条判断，输出统计 EXCEL 报告，含汇总和明细两个 Sheet。
---

# 微博评论情感分类

读取微博评论爬虫输出的 JSON 文件，将评论分批发送给 Claude AI 进行情感分析，
按正面反馈（期待/喜欢/感谢）、负面反馈（讨厌/抱怨/担忧）、中性（询问/事实陈述）三类归类，
输出 EXCEL 统计报告。

所有命令从 **MediaCrawler 项目根目录** 执行。

## 依赖

```bash
cd MediaCrawler
uv pip install openpyxl anthropic
```

## API Key 配置

通过环境变量或命令行参数提供 Anthropic API Key：

```bash
# 方式一：环境变量（推荐）
export ANTHROPIC_API_KEY="sk-ant-..."

# 方式二：命令行参数
--api-key "sk-ant-..."
```

## 快速开始

```bash
cd MediaCrawler
uv run python ../.claude/skills/weibo-sentiment-classifier/scripts/sentiment_classifier.py \
    --input "../WeiboExtractData/广州天气/2026-05-22/广州天气_20260522.json"
```

## 完整参数

| 参数 | 是否必填 | 说明 |
|---|---|---|
| `-i` / `--input` | 必填 | 微博评论爬虫输出的 JSON 文件路径 |
| `-o` / `--output` | 可选 | EXCEL 输出路径（默认在输入文件同目录自动生成） |
| `--api-key` | 可选 | Anthropic API Key（默认从 `ANTHROPIC_API_KEY` 环境变量读取） |
| `--model` | 可选 | 模型名称（默认 `claude-sonnet-4-6`） |
| `--batch-size` | 可选 | 每批处理的评论数（默认 40） |

## 分类原理

每条评论直接交由 Claude AI 判断情感倾向，不再依赖本地词典库匹配。

- **批量处理**：评论按批次（默认 40 条/批）发送，减少 API 调用次数
- **自动重试**：API 调用失败时自动重试 3 次，带指数退避
- **空评论处理**：清洗后为空的评论自动标记为中性

## 输出格式

EXCEL 包含两个 Sheet：

### 汇总

| 列 | 说明 |
|---|---|
| 微博作者名称 | 帖子作者昵称 |
| 发布时间 | 帖子创建时间 |
| 微博内容 | 帖子正文 |
| 点赞数 | 帖子点赞数 |
| 评论数 | 有效评论总数 |
| 正面/负面/中性 数量 | 各类情感评论数 |
| 正面/负面/中性 占比 | 百分比 |

### 评论明细

| 列 | 说明 |
|---|---|
| 微博作者 | 帖子作者昵称 |
| 微博内容 | 帖子正文 |
| 评论者 | 评论者昵称 |
| 评论内容 | 评论正文 |
| **情感分数** | AI 判断的情感强度（-1.0 极负面 ~ 1.0 极正面） |
| 情感分类 | 正面 / 负面 / 中性 |
| 点赞数 | 评论点赞数 |
