"""
Arabic text preprocessing pipeline.
Handles diacritics removal, normalization, transliteration hints,
URL/emoji stripping, and language filtering.
"""

import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

import emoji
from langdetect import detect, LangDetectException
from loguru import logger

# Arabic Unicode ranges
_AR_LETTERS = "؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿"
_AR_PATTERN = re.compile(f"[{_AR_LETTERS}]")

# Normalization maps
_ALEF_VARIANTS = re.compile(r"[أإآٱ]")
_WAW_VARIANTS = re.compile(r"[ؤ]")
_YEH_VARIANTS = re.compile(r"[يىئ]")
_HAMZA_ABOVE = re.compile(r"[ء]")
_TEH_MARBUTA = re.compile(r"ة")
_DIACRITICS = re.compile(r"[ً-ٟؐ-ؚۖ-ۜ۟-ۤۧ-ۭ]")
_TATWEEL = re.compile(r"ـ+")
_URL = re.compile(r"https?://\S+|www\.\S+")
_HASHTAG = re.compile(r"#(\S+)")
_MENTION = re.compile(r"@\S+")
_PUNCT = re.compile(r"[!\"#$%&'()*+,\-./:;<=>?@\[\\\]^_`{|}~،؟؛«»]+")
_WHITESPACE = re.compile(r"\s+")
_ELONGATION = re.compile(r"(.)\1{2,}")  # 3+ repeated chars → 1


@dataclass
class ProcessedPost:
    post_id: str
    platform: str
    group_id: str
    source: str
    original_text: str
    cleaned_text: str
    normalized_text: str
    timestamp: object
    language: str
    is_arabic: bool
    arabic_ratio: float
    hashtags: list[str]
    mentions: list[str]
    engagement: dict
    media_urls: list[str]
    char_count: int
    word_count: int


class ArabicPreprocessor:
    """Full Arabic text preprocessing pipeline."""

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        nlp_cfg = self.config.get("nlp", {})
        self.remove_diacritics = nlp_cfg.get("remove_diacritics", True)
        self.normalize_alef = nlp_cfg.get("normalize_alef", True)
        self.normalize_hamza = nlp_cfg.get("normalize_hamza", True)
        self.remove_elongation = nlp_cfg.get("remove_elongation", True)
        self.min_arabic_ratio = 0.3  # at least 30% Arabic chars to be "Arabic"

    # ──────────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────────

    def process(self, raw_post) -> Optional[ProcessedPost]:
        """
        Process a RawPost → ProcessedPost.
        Returns None if text is not Arabic or too short.
        """
        text = raw_post.text.strip()
        if not text:
            return None

        hashtags = _HASHTAG.findall(text)
        mentions = _MENTION.findall(text)
        arabic_ratio = self._arabic_ratio(text)
        is_arabic = arabic_ratio >= self.min_arabic_ratio or self._detect_arabic(text)

        cleaned = self._clean(text)
        normalized = self._normalize(cleaned) if is_arabic else cleaned

        if len(normalized.split()) < 3:
            return None

        return ProcessedPost(
            post_id=raw_post.post_id,
            platform=raw_post.platform,
            group_id=raw_post.group_id,
            source=raw_post.source,
            original_text=text,
            cleaned_text=cleaned,
            normalized_text=normalized,
            timestamp=raw_post.timestamp,
            language=raw_post.language,
            is_arabic=is_arabic,
            arabic_ratio=round(arabic_ratio, 3),
            hashtags=hashtags,
            mentions=mentions,
            engagement=raw_post.engagement,
            media_urls=raw_post.media_urls,
            char_count=len(normalized),
            word_count=len(normalized.split()),
        )

    def process_batch(self, raw_posts: list) -> list[ProcessedPost]:
        results: list[ProcessedPost] = []
        for post in raw_posts:
            try:
                processed = self.process(post)
                if processed:
                    results.append(processed)
            except Exception as exc:
                logger.debug(f"Skipped post {post.post_id}: {exc}")
        logger.info(f"Preprocessed {len(results)}/{len(raw_posts)} posts")
        return results

    # ──────────────────────────────────────────────────────────────────────────
    # Internal methods
    # ──────────────────────────────────────────────────────────────────────────

    def _clean(self, text: str) -> str:
        """Remove URLs, emojis, extra whitespace; keep hashtags demarcated."""
        text = _URL.sub(" ", text)
        text = emoji.replace_emoji(text, replace=" ")
        text = _MENTION.sub(" ", text)
        # keep hashtag text but strip the #
        text = _HASHTAG.sub(r" \1 ", text)
        text = _PUNCT.sub(" ", text)
        text = _WHITESPACE.sub(" ", text)
        return text.strip()

    def _normalize(self, text: str) -> str:
        """Normalize Arabic-specific orthographic variants."""
        if self.remove_diacritics:
            text = _DIACRITICS.sub("", text)
        text = _TATWEEL.sub("", text)
        if self.remove_elongation:
            text = _ELONGATION.sub(r"\1", text)
        if self.normalize_alef:
            text = _ALEF_VARIANTS.sub("ا", text)
        if self.normalize_hamza:
            text = _WAW_VARIANTS.sub("و", text)
            text = _YEH_VARIANTS.sub("ي", text)
        text = _TEH_MARBUTA.sub("ه", text)
        text = unicodedata.normalize("NFC", text)
        text = _WHITESPACE.sub(" ", text)
        return text.strip()

    def _arabic_ratio(self, text: str) -> float:
        ar_chars = len(_AR_PATTERN.findall(text))
        total = max(len(text.replace(" ", "")), 1)
        return ar_chars / total

    def _detect_arabic(self, text: str) -> bool:
        try:
            return detect(text) in ("ar", "fa", "ur")
        except LangDetectException:
            return False
