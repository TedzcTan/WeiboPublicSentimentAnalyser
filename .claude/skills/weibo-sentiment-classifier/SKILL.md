---
name: weibo-sentiment-classifier
description: 对微博评论爬取结果进行情感分类（正面/负面/中性），由 Claude AI 在对话中直接逐条判断，无需外部 API，输出统计 EXCEL 报告，含汇总和明细两个 Sheet。
---

# 微博评论情感分类

读取微博评论爬虫输出的 JSON 文件，由 Claude AI 直接在对话中逐条分析每条评论的情感倾向，
按正面反馈（期待/喜欢/感谢）、负面反馈（讨厌/抱怨/担忧）、中性（询问/事实陈述）三类归类，
输出 EXCEL 统计报告。

所有命令从 **MediaCrawler 项目根目录** 执行。

## 依赖

```bash
cd MediaCrawler
uv pip install openpyxl
```

## 工作流程

情感分类由 Claude AI 在对话中完成，无需配置任何 API Key。

### 第一步：查看待分类评论

```bash
uv run python ../.claude/skills/weibo-sentiment-classifier/scripts/sentiment_classifier.py \
    --input "../WeiboExtractData/广州天气/2026-05-22/广州天气_20260522.json" \
    --review
```

该命令输出所有去重后的评论列表（含 comment_id 和内容），供 Claude 逐条分析。

### 第二步：Claude 分析并生成 EXCEL

Claude 阅读评论内容后，在脚本顶部的 `CLASSIFICATIONS` 字典中填入每条评论的分类结果，
格式为 `"comment_id": ("情感分类", 分数)`，然后重新运行脚本：

```bash
uv run python ../.claude/skills/weibo-sentiment-classifier/scripts/sentiment_classifier.py \
    --input "../WeiboExtractData/广州天气/2026-05-22/广州天气_20260522.json"
```

## 完整参数

| 参数 | 是否必填 | 说明 |
|---|---|---|
| `-i` / `--input` | 必填 | 微博评论爬虫输出的 JSON 文件路径 |
| `-o` / `--output` | 可选 | EXCEL 输出路径（默认在输入文件同目录自动生成） |
| `--review` | 可选 | 仅打印去重评论列表供 Claude 分析，不生成 EXCEL |

## 分类标准

- **正面**：表达喜欢、感谢、期待、满意、赞扬、开心、支持、感动等积极情绪
- **负面**：表达讨厌、抱怨、担忧、愤怒、不满、讽刺、失望、质疑等消极情绪
- **中性**：纯信息询问、客观事实陈述、中性问候、无明显情感倾向

情感强度 score 范围：-1.0（极负面）到 1.0（极正面），0 表示完全中性。

注意事项：
- 讽刺、反语应判为负面（如"这天气预报真准"实际表达不准时）
- 纯"晚安""早上好""你好"等问候语 → 中性
- 仅问句无情绪词 → 中性
- 气象局/政府官方账号的回复一般标记为中性

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
| **情感分数** | 情感强度（-1.0 极负面 ~ 1.0 极正面） |
| 情感分类 | 正面 / 负面 / 中性 |
| 点赞数 | 评论点赞数 |
