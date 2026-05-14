"""
Arabic sentiment analysis engine.
Primary model: UBC-NLP/MARBERTv2 (fine-tuned on Arabic sentiment)
Fallback:      aubmindlab/bert-base-arabertv02

Outputs per-post: sentiment label (positive/negative/neutral),
                  confidence score, and weighted engagement score.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

import torch
from loguru import logger
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    pipeline,
)

from processors.arabic_preprocessor import ProcessedPost


# ── Sentiment lexicon for rule-based fallback ─────────────────────────────────
_POSITIVE_LEXICON = {
    "انتصار", "نصر", "فرح", "سعادة", "تحرير", "بطولة", "مجد", "شرف",
    "صمود", "قوة", "كرامة", "تضامن", "وحدة", "أمل", "بشارة", "ثقة",
    "عظيم", "رائع", "ممتاز", "مبارك", "حمد", "شكر", "إنجاز",
}
_NEGATIVE_LEXICON = {
    "هزيمة", "خسارة", "موت", "دمار", "كارثة", "مجزرة", "إبادة", "احتلال",
    "خيانة", "فساد", "ذل", "عار", "انهيار", "أزمة", "معاناة", "فقر",
    "جوع", "مرض", "حرب", "دماء", "حزن", "أسى", "خوف", "غضب", "يأس",
    "احتجاج", "ثورة", "عصيان", "رفض", "إدانة",
}


@dataclass
class SentimentResult:
    post_id: str
    platform: str
    group_id: str
    source: str
    timestamp: object
    text: str
    original_text: str
    sentiment: str          # "positive" | "negative" | "neutral"
    confidence: float       # 0-1
    positive_score: float
    negative_score: float
    neutral_score: float
    engagement_weight: float
    weighted_sentiment: float  # sentiment × engagement_weight; + for positive, - for negative
    themes: list[str] = field(default_factory=list)
    method: str = "model"   # "model" | "lexicon"


class SentimentEngine:
    """
    Multi-model Arabic sentiment analysis.
    Tries HuggingFace transformer, falls back to lexicon scoring.
    """

    MODEL_OPTIONS = [
        "CAMeL-Lab/bert-base-arabic-camelbert-mix-sentiment",
        "UBC-NLP/MARBERTv2",
        "aubmindlab/bert-base-arabertv02",
    ]

    def __init__(self, config: Optional[dict] = None, theme_config: Optional[list] = None):
        self.config = config or {}
        self.theme_config = theme_config or []
        self.device = 0 if torch.cuda.is_available() else -1
        self._pipe = None
        self._load_model()

    # ──────────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────────

    def analyze(self, post: ProcessedPost) -> SentimentResult:
        text = post.normalized_text
        if self._pipe:
            result = self._model_predict(text)
            method = "model"
        else:
            result = self._lexicon_predict(text)
            method = "lexicon"

        sentiment = result["label"]
        confidence = result["confidence"]
        pos = result.get("positive", 0.0)
        neg = result.get("negative", 0.0)
        neu = result.get("neutral", 0.0)

        ew = self._engagement_weight(post.engagement)
        sign = 1.0 if sentiment == "positive" else (-1.0 if sentiment == "negative" else 0.0)
        weighted = sign * confidence * ew

        themes = self._detect_themes(text)

        return SentimentResult(
            post_id=post.post_id,
            platform=post.platform,
            group_id=post.group_id,
            source=post.source,
            timestamp=post.timestamp,
            text=post.normalized_text,
            original_text=post.original_text,
            sentiment=sentiment,
            confidence=confidence,
            positive_score=pos,
            negative_score=neg,
            neutral_score=neu,
            engagement_weight=ew,
            weighted_sentiment=weighted,
            themes=themes,
            method=method,
        )

    def analyze_batch(self, posts: list[ProcessedPost]) -> list[SentimentResult]:
        results: list[SentimentResult] = []
        for i, post in enumerate(posts):
            try:
                results.append(self.analyze(post))
            except Exception as exc:
                logger.debug(f"Sentiment error on {post.post_id}: {exc}")
            if (i + 1) % 100 == 0:
                logger.info(f"  Sentiment: {i+1}/{len(posts)} processed")
        logger.info(f"Sentiment analysis done: {len(results)}/{len(posts)} posts")
        return results

    # ──────────────────────────────────────────────────────────────────────────
    # Model loading
    # ──────────────────────────────────────────────────────────────────────────

    def _load_model(self):
        for model_name in self.MODEL_OPTIONS:
            try:
                logger.info(f"Loading sentiment model: {model_name}")
                self._pipe = pipeline(
                    "text-classification",
                    model=model_name,
                    tokenizer=model_name,
                    device=self.device,
                    max_length=512,
                    truncation=True,
                    top_k=None,
                )
                logger.info(f"Loaded {model_name} successfully")
                self._model_name = model_name
                return
            except Exception as exc:
                logger.warning(f"Could not load {model_name}: {exc}")
        logger.warning("All transformer models failed — using lexicon fallback")
        self._pipe = None

    # ──────────────────────────────────────────────────────────────────────────
    # Prediction helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _model_predict(self, text: str) -> dict:
        raw = self._pipe(text[:512])[0]  # list of {label, score}
        label_map: dict[str, float] = {}
        for item in raw:
            lbl = item["label"].lower()
            # normalize various model label conventions
            if lbl in ("1", "pos", "positive", "label_2"):
                label_map["positive"] = item["score"]
            elif lbl in ("0", "neg", "negative", "label_0"):
                label_map["negative"] = item["score"]
            else:
                label_map["neutral"] = label_map.get("neutral", 0.0) + item["score"]

        # if model only outputs pos/neg with no neutral label
        if "neutral" not in label_map:
            label_map["neutral"] = max(0.0, 1.0 - label_map.get("positive", 0) - label_map.get("negative", 0))

        best = max(label_map, key=lambda k: label_map[k])
        return {
            "label": best,
            "confidence": label_map[best],
            "positive": label_map.get("positive", 0.0),
            "negative": label_map.get("negative", 0.0),
            "neutral": label_map.get("neutral", 0.0),
        }

    def _lexicon_predict(self, text: str) -> dict:
        words = set(text.split())
        pos = len(words & _POSITIVE_LEXICON)
        neg = len(words & _NEGATIVE_LEXICON)
        total = max(pos + neg, 1)
        pos_score = pos / total
        neg_score = neg / total
        if pos > neg:
            label, conf = "positive", pos_score
        elif neg > pos:
            label, conf = "negative", neg_score
        else:
            label, conf = "neutral", 0.5
        neu_score = 1.0 - pos_score - neg_score
        return {
            "label": label,
            "confidence": conf,
            "positive": pos_score,
            "negative": neg_score,
            "neutral": max(0.0, neu_score),
        }

    def _engagement_weight(self, engagement: dict) -> float:
        """Log-scaled engagement weight so viral posts count more but don't dominate."""
        import math
        total = (
            engagement.get("likes", 0)
            + engagement.get("retweets", 0) * 2
            + engagement.get("views", 0) * 0.01
            + engagement.get("forwards", 0) * 2
            + engagement.get("replies", 0)
        )
        return 1.0 + math.log1p(total) / 10.0

    def _detect_themes(self, text: str) -> list[str]:
        matched: list[str] = []
        for theme in self.theme_config:
            kws = theme.get("keywords_ar", []) + theme.get("keywords_en", [])
            if any(kw in text for kw in kws):
                matched.append(theme["id"])
        return matched
