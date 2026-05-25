"""情感词典管理器 — 持久化词典库的加载、查询、更新与反思。"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional


class DictManager:
    """管理情感词典 JSON 文件，支持置信度加权查询、触发计数和自动反思。"""

    def __init__(self, dict_path: Optional[str] = None):
        if dict_path is None:
            dict_path = Path(__file__).parent / "sentiment_dict.json"
        self.dict_path = Path(dict_path)
        self.data = self._load()
        # 本次运行中匹配的词及次数
        self.session_hits: dict[str, dict[str, int]] = {
            "positive": {},
            "negative": {},
            "greeting": {},
            "question_context": {},
        }
        self.session_borderlines: list[dict] = []  # 边界案例
        self.session_unmatched: list[str] = []  # 无词匹配的评论文本

    # ── 加载 / 保存 ─────────────────────────────────

    def _load(self) -> dict:
        with open(self.dict_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def save(self):
        self.data["meta"]["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        with open(self.dict_path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    # ── 查询接口 ─────────────────────────────────────

    def is_greeting(self, text: str) -> bool:
        return text in self.data["neutral_greetings"]

    def get_positive_words(self) -> set:
        return set(self.data["positive_words"].keys())

    def get_negative_words(self) -> set:
        return set(self.data["negative_words"].keys())

    def get_greetings(self) -> set:
        return set(self.data["neutral_greetings"].keys())

    @property
    def negators(self) -> list:
        return self.data["patterns"]["negators"]

    @property
    def degree_words(self) -> list:
        return self.data["patterns"]["degree_words"]

    @property
    def question_markers(self) -> list:
        return self.data["patterns"]["question_markers"]

    @property
    def question_context_positive(self) -> set:
        return set(self.data["patterns"]["question_context_positive"])

    def get_confidence(self, word: str, polarity: str) -> float:
        """根据触发次数返回置信度权重（0.5 ~ 2.0）。

        权重映射：
          0 次（冷启动） → 0.6
          1-5 次        → 0.8
          6-20 次       → 1.0
          21-50 次      → 1.3
          51-100 次     → 1.6
          >100 次       → 2.0
        """
        entry = self.data[f"{polarity}_words"].get(word)
        if entry is None:
            return 0.5  # 未知词
        cnt = entry.get("count", 0)
        if cnt == 0:
            return 0.6
        elif cnt <= 5:
            return 0.8
        elif cnt <= 20:
            return 1.0
        elif cnt <= 50:
            return 1.3
        elif cnt <= 100:
            return 1.6
        else:
            return 2.0

    def word_exists(self, word: str) -> Optional[str]:
        """检查词是否在词典中，返回 'positive' / 'negative' / 'greeting' / None。"""
        if word in self.data["positive_words"]:
            return "positive"
        if word in self.data["negative_words"]:
            return "negative"
        if word in self.data["neutral_greetings"]:
            return "greeting"
        return None

    # ── 计数更新 ─────────────────────────────────────

    def record_hit(self, word: str, polarity: str):
        """记录本次运行中某个词的触发。"""
        self.session_hits[polarity][word] = self.session_hits[polarity].get(word, 0) + 1

    def record_borderline(self, text: str, score: float, result: str):
        """记录边界案例（情感分 <= 1）。"""
        self.session_borderlines.append({"text": text, "score": score, "result": result})

    def record_unmatched(self, text: str):
        """记录无情感词匹配的评论。"""
        self.session_unmatched.append(text)

    # session_hits polarity → dict section 映射
    _POLARITY_KEY_MAP = {
        "positive": "positive_words",
        "negative": "negative_words",
        "greeting": "neutral_greetings",
        "question_context": "positive_words",  # 问句语境词本身是正面词
    }

    def commit_session(self):
        """将本次运行的所有触发计数写回词典。"""
        for polarity, words in self.session_hits.items():
            dict_key = self._POLARITY_KEY_MAP.get(polarity)
            if dict_key is None:
                continue
            for word, count in words.items():
                if word in self.data.get(dict_key, {}):
                    self.data[dict_key][word]["count"] += count
        self.data["meta"]["total_runs"] += 1
        self.save()

    # ── 反思 ─────────────────────────────────────────

    def reflect(self) -> str:
        """运行后反思，检测候选新词并生成报告。

        返回一个多行字符串报告，同时将候选词写入 pending_candidates。
        """
        lines = []
        lines.append("=" * 50)
        lines.append("词典反思报告")
        lines.append("=" * 50)

        # 1. 统计本次触发
        total_hits = sum(sum(v.values()) for v in self.session_hits.values())
        lines.append(f"\n本次触发情感词 {total_hits} 次:")
        for polarity, words in self.session_hits.items():
            if words:
                sorted_words = sorted(words.items(), key=lambda x: -x[1])
                top = sorted_words[:10]
                label = {"positive": "正面", "negative": "负面", "greeting": "问候", "question_context": "问句语境"}
                lines.append(f"  [{label.get(polarity, polarity)}] {', '.join(f'{w}(×{c})' for w, c in top)}")

        # 2. 边界案例
        if self.session_borderlines:
            lines.append(f"\n边界案例 ({len(self.session_borderlines)} 条，|score|<=1):")
            for case in self.session_borderlines[:10]:
                lines.append(f"  [{case['result']}] score={case['score']:+.1f}  {case['text'][:60]}")

        # 3. 从无匹配评论中提取候选新词
        candidates = self._extract_candidates()
        if candidates:
            lines.append(f"\n发现 {len(candidates)} 个候选新词（高频出现但不在词典中）:")
            for word, freq in sorted(candidates.items(), key=lambda x: -x[1])[:15]:
                existing = self.word_exists(word)
                lines.append(f"  {word} (出现 {freq} 次){' [已存在: ' + existing + ']' if existing else ' → 待审核'}")
                if not existing:
                    self._add_candidate(word, freq)

        # 4. 词典健康度
        positive_count = len(self.data["positive_words"])
        negative_count = len(self.data["negative_words"])
        greeting_count = len(self.data["neutral_greetings"])
        lines.append(f"\n词典状态: 正面词 {positive_count} | 负面词 {negative_count} | 问候语 {greeting_count}")
        lines.append(f"累计运行 {self.data['meta']['total_runs']} 次")

        self.save()
        return "\n".join(lines)

    def _extract_candidates(self) -> dict[str, int]:
        """从无匹配评论文本中提取高频 n-gram 候选词。"""
        if not self.session_unmatched:
            return {}

        # 按空格/标点分块，提取 2-4 字的 n-gram
        freq: dict[str, int] = {}
        all_positive = self.get_positive_words()
        all_negative = self.get_negative_words()
        all_greetings = self.get_greetings()
        all_known = all_positive | all_negative | all_greetings

        for text in self.session_unmatched:
            # 只保留中文字符
            chinese = re.sub(r"[^一-鿿]", "", text)
            if len(chinese) < 2:
                continue
            # 提取 2-4 字片段
            for wlen in (2, 3, 4):
                for i in range(len(chinese) - wlen + 1):
                    ngram = chinese[i : i + wlen]
                    if ngram not in all_known and len(ngram.strip()) == wlen:
                        freq[ngram] = freq.get(ngram, 0) + 1

        # 只返回出现 >= 2 次的候选词
        return {k: v for k, v in freq.items() if v >= 2}

    def _add_candidate(self, word: str, freq: int):
        """将候选词加入待审核列表。"""
        if word not in self.data["pending_candidates"]:
            self.data["pending_candidates"][word] = {"first_seen": datetime.now().strftime("%Y-%m-%d %H:%M"), "occurrence_count": freq}
        else:
            self.data["pending_candidates"][word]["occurrence_count"] += freq

    def get_stats(self) -> dict:
        """返回词典统计信息。"""
        return {
            "version": self.data["meta"]["version"],
            "total_runs": self.data["meta"]["total_runs"],
            "positive_count": len(self.data["positive_words"]),
            "negative_count": len(self.data["negative_words"]),
            "greeting_count": len(self.data["neutral_greetings"]),
            "candidate_count": len(self.data["pending_candidates"]),
            "top_positive": sorted(self.data["positive_words"].items(), key=lambda x: -x[1]["count"])[:5],
            "top_negative": sorted(self.data["negative_words"].items(), key=lambda x: -x[1]["count"])[:5],
        }
