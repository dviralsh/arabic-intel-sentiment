"""
Comparative intelligence engine.
Computes deltas between baseline period (2024) and current period,
generating human-readable intelligence assessments.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
from loguru import logger

from .sentiment_engine import SentimentResult


SIGNIFICANCE_THRESHOLD = 0.05   # 5 percentage-point shift is reportable
HIGH_CONFIDENCE_THRESHOLD = 0.1  # 10pp shift is high-confidence intel


@dataclass
class PeriodStats:
    group_id: str
    period_label: str
    start: datetime
    end: datetime
    post_count: int
    avg_sentiment_score: float   # -1 (very neg) to +1 (very pos)
    positive_pct: float
    negative_pct: float
    neutral_pct: float
    avg_engagement_weight: float
    weighted_sentiment: float    # engagement-weighted average
    top_themes: list[tuple[str, float]]  # (theme_id, share)
    sample_posts: list[dict]     # top evidence posts


@dataclass
class IntelAssessment:
    """Single comparative intelligence finding."""
    group_id: str
    group_display_name: str
    theme: str                    # "overall" | theme_id
    theme_label: str
    direction: str                # "increase" | "decrease" | "stable"
    magnitude: str                # "significant" | "moderate" | "slight"
    confidence: str               # "high" | "medium" | "low"
    delta_pct: float              # absolute change in sentiment score
    baseline_score: float
    current_score: float
    narrative: str                # human-readable intelligence finding
    evidence: list[dict]          # supporting posts
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ComparativeEngine:
    """Compare sentiment across time periods and generate intel assessments."""

    def __init__(self, targets_config: dict):
        self.targets_config = targets_config
        self.groups = targets_config.get("groups", {})

    # ──────────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────────

    def compare(
        self,
        results: list[SentimentResult],
        baseline_start: datetime,
        baseline_end: datetime,
        current_start: datetime,
        current_end: datetime,
    ) -> list[IntelAssessment]:
        """
        Split results into baseline vs current period and generate assessments.
        """
        df = self._to_dataframe(results)
        if df.empty:
            logger.warning("No sentiment results to compare")
            return []

        baseline_df = df[(df["timestamp"] >= baseline_start) & (df["timestamp"] <= baseline_end)]
        current_df = df[(df["timestamp"] >= current_start) & (df["timestamp"] <= current_end)]

        logger.info(
            f"Comparing {len(baseline_df)} baseline posts vs {len(current_df)} current posts"
        )

        assessments: list[IntelAssessment] = []
        for group_id, group_cfg in self.groups.items():
            b_group = baseline_df[baseline_df["group_id"] == group_id]
            c_group = current_df[current_df["group_id"] == group_id]

            if b_group.empty or c_group.empty:
                logger.warning(f"Insufficient data for group '{group_id}' — skipping")
                continue

            # Overall sentiment assessment
            overall = self._compare_periods(
                group_id,
                group_cfg["display_name"],
                b_group, c_group,
                theme="overall",
                theme_label="Overall Sentiment",
            )
            if overall:
                assessments.append(overall)

            # Per-theme assessments
            analysis_cfg = self.targets_config.get("analysis", {})
            for theme_cfg in analysis_cfg.get("themes", []):
                theme_id = theme_cfg["id"]
                theme_label = theme_cfg["label"]
                b_theme = b_group[b_group["themes"].apply(lambda t: theme_id in t)]
                c_theme = c_group[c_group["themes"].apply(lambda t: theme_id in t)]
                if len(b_theme) < 10 or len(c_theme) < 10:
                    continue
                a = self._compare_periods(
                    group_id, group_cfg["display_name"],
                    b_theme, c_theme, theme_id, theme_label,
                )
                if a:
                    assessments.append(a)

        # Sort by magnitude of change (most significant first)
        assessments.sort(key=lambda a: abs(a.delta_pct), reverse=True)
        logger.info(f"Generated {len(assessments)} intelligence assessments")
        return assessments

    # ──────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _compare_periods(
        self,
        group_id: str,
        display_name: str,
        baseline: pd.DataFrame,
        current: pd.DataFrame,
        theme: str,
        theme_label: str,
    ) -> Optional[IntelAssessment]:
        b_score = self._weighted_sentiment_score(baseline)
        c_score = self._weighted_sentiment_score(current)
        delta = c_score - b_score

        if abs(delta) < SIGNIFICANCE_THRESHOLD:
            direction, magnitude, confidence = "stable", "negligible", "low"
        elif abs(delta) < HIGH_CONFIDENCE_THRESHOLD:
            direction = "increase" if delta > 0 else "decrease"
            magnitude = "slight"
            confidence = "medium"
        else:
            direction = "increase" if delta > 0 else "decrease"
            magnitude = "significant" if abs(delta) > 0.2 else "moderate"
            confidence = "high"

        narrative = self._generate_narrative(
            display_name, theme_label, direction, magnitude,
            b_score, c_score, delta, baseline, current,
        )
        evidence = self._select_evidence(current, limit=5)

        return IntelAssessment(
            group_id=group_id,
            group_display_name=display_name,
            theme=theme,
            theme_label=theme_label,
            direction=direction,
            magnitude=magnitude,
            confidence=confidence,
            delta_pct=round(delta * 100, 2),
            baseline_score=round(b_score, 3),
            current_score=round(c_score, 3),
            narrative=narrative,
            evidence=evidence,
        )

    def _weighted_sentiment_score(self, df: pd.DataFrame) -> float:
        """Engagement-weighted mean sentiment score (-1 to +1)."""
        if df.empty:
            return 0.0
        sign_map = {"positive": 1.0, "negative": -1.0, "neutral": 0.0}
        df = df.copy()
        df["sign"] = df["sentiment"].map(sign_map).fillna(0.0)
        df["ws"] = df["sign"] * df["confidence"] * df["engagement_weight"]
        total_weight = df["engagement_weight"].sum()
        if total_weight == 0:
            return float(df["ws"].mean())
        return float((df["ws"]).sum() / total_weight)

    def _generate_narrative(
        self,
        group: str,
        theme: str,
        direction: str,
        magnitude: str,
        b_score: float,
        c_score: float,
        delta: float,
        baseline: pd.DataFrame,
        current: pd.DataFrame,
    ) -> str:
        pct_change = abs(delta) * 100
        b_neg_pct = (baseline["sentiment"] == "negative").mean() * 100
        c_neg_pct = (current["sentiment"] == "negative").mean() * 100
        b_pos_pct = (baseline["sentiment"] == "positive").mean() * 100
        c_pos_pct = (current["sentiment"] == "positive").mean() * 100

        period_label = "compared to the 2024 baseline period"

        if direction == "stable":
            return (
                f"{group} {theme.lower()} sentiment remains stable {period_label}. "
                f"Negative content: {c_neg_pct:.1f}% (vs {b_neg_pct:.1f}% in 2024). "
                f"No statistically significant morale shift detected."
            )

        dir_word = "improved" if direction == "increase" else "deteriorated"
        adverb = {"significant": "significantly", "moderate": "moderately", "slight": "slightly"}.get(magnitude, "")

        narrative = (
            f"{group} {theme.lower()} sentiment has {adverb} {dir_word} {period_label} "
            f"(Δ {delta*100:+.1f} pp; score {b_score:+.2f} → {c_score:+.2f}). "
        )
        if direction == "decrease":
            narrative += (
                f"Negative content share rose from {b_neg_pct:.1f}% to {c_neg_pct:.1f}%, "
                f"while positive content fell from {b_pos_pct:.1f}% to {c_pos_pct:.1f}%. "
                f"This indicates increased internal stress, operational difficulties, "
                f"or declining public support within monitored channels."
            )
        else:
            narrative += (
                f"Positive content share rose from {b_pos_pct:.1f}% to {c_pos_pct:.1f}%. "
                f"This may reflect perceived operational success, propaganda surge, "
                f"or a rally-around-the-flag effect following recent events."
            )
        return narrative

    def _select_evidence(self, df: pd.DataFrame, limit: int = 5) -> list[dict]:
        """Select highest-engagement posts as evidence."""
        top = df.nlargest(limit, "engagement_weight")
        evidence = []
        for _, row in top.iterrows():
            evidence.append({
                "post_id": row["post_id"],
                "platform": row["platform"],
                "source": row["source"],
                "text": row.get("original_text", row["text"])[:500],
                "sentiment": row["sentiment"],
                "confidence": round(float(row["confidence"]), 3),
                "timestamp": row["timestamp"].isoformat() if hasattr(row["timestamp"], "isoformat") else str(row["timestamp"]),
                "engagement": row.get("engagement", {}),
            })
        return evidence

    def _to_dataframe(self, results: list[SentimentResult]) -> pd.DataFrame:
        records = []
        for r in results:
            ts = r.timestamp
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            records.append({
                "post_id": r.post_id,
                "platform": r.platform,
                "group_id": r.group_id,
                "source": r.source,
                "text": r.text,
                "original_text": r.original_text,
                "timestamp": ts,
                "sentiment": r.sentiment,
                "confidence": r.confidence,
                "positive_score": r.positive_score,
                "negative_score": r.negative_score,
                "neutral_score": r.neutral_score,
                "engagement_weight": r.engagement_weight,
                "weighted_sentiment": r.weighted_sentiment,
                "themes": r.themes,
                "engagement": r.engagement,
            })
        return pd.DataFrame(records)
