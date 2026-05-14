"""
Topic modeling for Arabic social media content using BERTopic.
Identifies dominant narratives and propaganda themes per group.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
from loguru import logger

try:
    from bertopic import BERTopic
    from sklearn.feature_extraction.text import CountVectorizer
    from umap import UMAP
    from hdbscan import HDBSCAN
    BERTOPIC_AVAILABLE = True
except ImportError:
    BERTOPIC_AVAILABLE = False
    logger.warning("BERTopic not available — falling back to keyword frequency")


@dataclass
class TopicResult:
    group_id: str
    topic_id: int
    label: str
    size: int           # number of posts in this topic
    share: float        # fraction of group posts
    top_words: list[str]
    representative_texts: list[str]
    sentiment_distribution: dict[str, float]  # {positive, negative, neutral}
    avg_sentiment_score: float
    trend: str          # "rising" | "falling" | "stable" compared to baseline


class TopicModeler:
    """BERTopic-based topic discovery for Arabic texts."""

    def __init__(self, min_topic_size: int = 15):
        self.min_topic_size = min_topic_size
        self._models: dict[str, any] = {}

    def fit_group(
        self,
        group_id: str,
        texts: list[str],
        sentiments: list[str],
        timestamps: Optional[list] = None,
    ) -> list[TopicResult]:
        if len(texts) < self.min_topic_size * 2:
            logger.warning(f"[Topics] Too few texts for '{group_id}' ({len(texts)}) — skipping")
            return []

        if BERTOPIC_AVAILABLE:
            return self._bertopic_fit(group_id, texts, sentiments, timestamps)
        else:
            return self._keyword_fallback(group_id, texts, sentiments)

    def fit_all_groups(
        self,
        results_by_group: dict[str, dict],
    ) -> dict[str, list[TopicResult]]:
        output: dict[str, list[TopicResult]] = {}
        for group_id, data in results_by_group.items():
            texts = data.get("texts", [])
            sentiments = data.get("sentiments", [])
            timestamps = data.get("timestamps")
            output[group_id] = self.fit_group(group_id, texts, sentiments, timestamps)
        return output

    # ──────────────────────────────────────────────────────────────────────────

    def _bertopic_fit(
        self,
        group_id: str,
        texts: list[str],
        sentiments: list[str],
        timestamps: Optional[list],
    ) -> list[TopicResult]:
        try:
            umap_model = UMAP(n_neighbors=15, n_components=5, min_dist=0.0, metric="cosine", random_state=42)
            hdbscan_model = HDBSCAN(min_cluster_size=self.min_topic_size, metric="euclidean", prediction_data=True)
            vectorizer = CountVectorizer(
                ngram_range=(1, 2),
                stop_words=None,  # Arabic stopwords handled in preprocessing
                min_df=3,
            )
            topic_model = BERTopic(
                umap_model=umap_model,
                hdbscan_model=hdbscan_model,
                vectorizer_model=vectorizer,
                language="multilingual",
                calculate_probabilities=False,
                verbose=False,
            )
            topics, _ = topic_model.fit_transform(texts)
            self._models[group_id] = topic_model

            results: list[TopicResult] = []
            topic_info = topic_model.get_topic_info()
            for _, row in topic_info.iterrows():
                tid = row["Topic"]
                if tid == -1:
                    continue  # outlier cluster
                indices = [i for i, t in enumerate(topics) if t == tid]
                topic_sents = [sentiments[i] for i in indices]
                topic_texts = [texts[i] for i in indices[:5]]
                top_words_raw = topic_model.get_topic(tid)
                top_words = [w for w, _ in (top_words_raw or [])[:10]]
                sent_dist = {
                    "positive": topic_sents.count("positive") / max(len(topic_sents), 1),
                    "negative": topic_sents.count("negative") / max(len(topic_sents), 1),
                    "neutral": topic_sents.count("neutral") / max(len(topic_sents), 1),
                }
                avg_s = sent_dist["positive"] - sent_dist["negative"]
                results.append(TopicResult(
                    group_id=group_id,
                    topic_id=tid,
                    label=" | ".join(top_words[:3]),
                    size=len(indices),
                    share=round(len(indices) / len(texts), 3),
                    top_words=top_words,
                    representative_texts=topic_texts,
                    sentiment_distribution=sent_dist,
                    avg_sentiment_score=round(avg_s, 3),
                    trend="stable",  # trend computed by comparative engine
                ))
            logger.info(f"[Topics] {group_id}: {len(results)} topics discovered")
            return results
        except Exception as exc:
            logger.error(f"BERTopic error for '{group_id}': {exc}")
            return self._keyword_fallback(group_id, texts, sentiments)

    def _keyword_fallback(
        self,
        group_id: str,
        texts: list[str],
        sentiments: list[str],
    ) -> list[TopicResult]:
        """Simple TF-IDF-style keyword frequency fallback."""
        from collections import Counter
        word_freq: Counter = Counter()
        for text in texts:
            word_freq.update(text.split())
        # Remove very common/short words
        top_words = [w for w, _ in word_freq.most_common(200) if len(w) > 2][:50]

        # Group into a single "all content" pseudo-topic
        sent_dist = {
            "positive": sentiments.count("positive") / max(len(sentiments), 1),
            "negative": sentiments.count("negative") / max(len(sentiments), 1),
            "neutral": sentiments.count("neutral") / max(len(sentiments), 1),
        }
        avg_s = sent_dist["positive"] - sent_dist["negative"]
        return [TopicResult(
            group_id=group_id,
            topic_id=0,
            label=" | ".join(top_words[:3]),
            size=len(texts),
            share=1.0,
            top_words=top_words[:10],
            representative_texts=texts[:5],
            sentiment_distribution=sent_dist,
            avg_sentiment_score=round(avg_s, 3),
            trend="stable",
        )]
