"""
Source-type comparative analyzer.

KEY INTELLIGENCE VALUE: When official media sentiment diverges significantly
from civilian/grassroots channels, it signals:
  - Propaganda disconnected from reality (official positive, civilian negative)
  - Rallying or genuine support (both positive)
  - Internal crisis being suppressed (official neutral, civilian very negative)

Produces per-source-type breakdowns and divergence alerts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
from loguru import logger

from .sentiment_engine import SentimentResult

SOURCE_TYPE_ORDER = [
    "official_media",
    "official_telegram",
    "affiliated_telegram",
    "civilian_telegram",
    "twitter_official",
    "twitter_affiliated",
    "rss_feed",
    "web_official",
    "rss",
    "web",
    "twitter",
    "telegram",
]

SOURCE_TYPE_LABELS = {
    "official_media":      "Official Media",
    "official_telegram":   "Official Telegram",
    "affiliated_telegram": "Affiliated Telegram",
    "civilian_telegram":   "Civilian Telegram",
    "twitter_official":    "Official Twitter",
    "twitter_affiliated":  "Affiliated Twitter",
    "rss_feed":            "RSS / News",
    "web_official":        "Official Websites",
    "rss":                 "RSS / News",
    "web":                 "Official Websites",
    "twitter":             "Twitter/X",
    "telegram":            "Telegram",
}

SOURCE_TYPE_COLORS = {
    "official_media":      "#ef4444",
    "official_telegram":   "#f97316",
    "affiliated_telegram": "#eab308",
    "civilian_telegram":   "#22c55e",
    "twitter_official":    "#818cf8",
    "twitter_affiliated":  "#a78bfa",
    "rss_feed":            "#06b6d4",
    "web_official":        "#64748b",
    "rss":                 "#06b6d4",
    "web":                 "#64748b",
    "twitter":             "#818cf8",
    "telegram":            "#f97316",
}

# "Propaganda" source types — output is controlled/curated
PROPAGANDA_TYPES = {"official_media", "official_telegram", "twitter_official",
                    "rss_feed", "web_official", "rss", "web"}
# "Grassroots" source types — more authentic signal
GRASSROOTS_TYPES = {"civilian_telegram", "twitter_affiliated"}
# Middle layer
AMPLIFIER_TYPES = {"affiliated_telegram"}


@dataclass
class SourceTypeProfile:
    source_type: str
    label: str
    color: str
    post_count: int
    avg_sentiment: float
    positive_pct: float
    negative_pct: float
    neutral_pct: float
    engagement_weighted_sentiment: float
    top_sources: list[str]       # top individual sources by volume
    top_themes: list[str]


@dataclass
class DivergenceAlert:
    """Fired when propaganda vs civilian sentiment diverges significantly."""
    group_id: str
    group_display_name: str
    propaganda_score: float
    grassroots_score: float
    delta: float                  # grassroots - propaganda
    severity: str                 # "critical" | "high" | "moderate"
    interpretation: str           # human-readable intelligence finding
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class SourceComparativeResult:
    group_id: str
    group_display_name: str
    profiles: dict[str, SourceTypeProfile]   # source_type → profile
    divergence_alerts: list[DivergenceAlert]
    source_timeline: dict[str, list[dict]]   # source_type → monthly timeline
    narrative_divergence_score: float         # 0-1; how much official ≠ civilian


class SourceComparator:
    """Compare sentiment across source types within each group."""

    DIVERGENCE_CRITICAL = 0.35
    DIVERGENCE_HIGH = 0.20
    DIVERGENCE_MODERATE = 0.10

    def __init__(self, targets_config: dict):
        self.targets_config = targets_config
        self.groups = targets_config.get("groups", {})

    # ── Public API ────────────────────────────────────────────────────────────

    def analyze(self, results: list[SentimentResult]) -> list[SourceComparativeResult]:
        df = self._to_df(results)
        if df.empty:
            return []

        output: list[SourceComparativeResult] = []
        for group_id, group_cfg in self.groups.items():
            g = df[df["group_id"] == group_id]
            if g.empty:
                continue
            result = self._analyze_group(group_id, group_cfg["display_name"], g)
            output.append(result)
        return output

    def to_serializable(self, results: list[SourceComparativeResult]) -> dict:
        out: dict = {}
        for r in results:
            out[r.group_id] = {
                "group_display_name": r.group_display_name,
                "narrative_divergence_score": round(r.narrative_divergence_score, 3),
                "profiles": {
                    st: {
                        "label": p.label,
                        "color": p.color,
                        "post_count": p.post_count,
                        "avg_sentiment": round(p.avg_sentiment, 3),
                        "positive_pct": round(p.positive_pct, 1),
                        "negative_pct": round(p.negative_pct, 1),
                        "neutral_pct": round(p.neutral_pct, 1),
                        "engagement_weighted_sentiment": round(p.engagement_weighted_sentiment, 3),
                        "top_sources": p.top_sources[:5],
                    }
                    for st, p in r.profiles.items()
                },
                "divergence_alerts": [
                    {
                        "propaganda_score": round(a.propaganda_score, 3),
                        "grassroots_score": round(a.grassroots_score, 3),
                        "delta": round(a.delta, 3),
                        "severity": a.severity,
                        "interpretation": a.interpretation,
                        "timestamp": a.timestamp,
                    }
                    for a in r.divergence_alerts
                ],
                "source_timeline": r.source_timeline,
            }
        return out

    # ── Internal ──────────────────────────────────────────────────────────────

    def _analyze_group(
        self,
        group_id: str,
        display_name: str,
        df: pd.DataFrame,
    ) -> SourceComparativeResult:
        profiles: dict[str, SourceTypeProfile] = {}
        df = df.copy()
        sign_map = {"positive": 1.0, "negative": -1.0, "neutral": 0.0}
        df["sign"] = df["sentiment"].map(sign_map).fillna(0.0)
        df["ws"] = df["sign"] * df["confidence"] * df["engagement_weight"]

        for st in df["source_type"].unique():
            g = df[df["source_type"] == st]
            if g.empty:
                continue
            total_w = g["engagement_weight"].sum()
            avg_sent = float(g["sign"].mean())
            ew_sent = float(g["ws"].sum() / total_w) if total_w > 0 else avg_sent
            top_sources = (
                g.groupby("source")["post_id"].count()
                .sort_values(ascending=False).head(5).index.tolist()
            )
            top_themes = self._top_themes(g)
            profiles[st] = SourceTypeProfile(
                source_type=st,
                label=SOURCE_TYPE_LABELS.get(st, st),
                color=SOURCE_TYPE_COLORS.get(st, "#888"),
                post_count=len(g),
                avg_sentiment=avg_sent,
                positive_pct=(g["sentiment"] == "positive").mean() * 100,
                negative_pct=(g["sentiment"] == "negative").mean() * 100,
                neutral_pct=(g["sentiment"] == "neutral").mean() * 100,
                engagement_weighted_sentiment=ew_sent,
                top_sources=top_sources,
                top_themes=top_themes,
            )

        alerts = self._check_divergence(group_id, display_name, profiles)
        timeline = self._build_source_timeline(df)
        divergence_score = self._compute_divergence_score(profiles)

        return SourceComparativeResult(
            group_id=group_id,
            group_display_name=display_name,
            profiles=profiles,
            divergence_alerts=alerts,
            source_timeline=timeline,
            narrative_divergence_score=divergence_score,
        )

    def _check_divergence(
        self,
        group_id: str,
        display_name: str,
        profiles: dict[str, SourceTypeProfile],
    ) -> list[DivergenceAlert]:
        alerts: list[DivergenceAlert] = []

        prop_types = [st for st in PROPAGANDA_TYPES if st in profiles]
        grass_types = [st for st in GRASSROOTS_TYPES if st in profiles]

        if not prop_types or not grass_types:
            return alerts

        prop_score = sum(profiles[st].avg_sentiment for st in prop_types) / len(prop_types)
        grass_score = sum(profiles[st].avg_sentiment for st in grass_types) / len(grass_types)
        delta = grass_score - prop_score  # negative = civilians more negative than official

        severity = (
            "critical" if abs(delta) >= self.DIVERGENCE_CRITICAL
            else "high" if abs(delta) >= self.DIVERGENCE_HIGH
            else "moderate" if abs(delta) >= self.DIVERGENCE_MODERATE
            else None
        )
        if severity is None:
            return alerts

        interp = self._interpret_divergence(display_name, prop_score, grass_score, delta)
        alerts.append(DivergenceAlert(
            group_id=group_id,
            group_display_name=display_name,
            propaganda_score=prop_score,
            grassroots_score=grass_score,
            delta=delta,
            severity=severity,
            interpretation=interp,
        ))
        return alerts

    def _interpret_divergence(
        self,
        group: str,
        prop: float,
        grass: float,
        delta: float,
    ) -> str:
        if delta < -self.DIVERGENCE_CRITICAL:
            return (
                f"CRITICAL DIVERGENCE: {group} official channels score {prop:+.2f} while "
                f"civilian channels score {grass:+.2f} (Δ {delta:+.2f}). "
                f"Official propaganda is significantly more positive than grassroots reality. "
                f"High likelihood of suppressed internal crisis, censored casualties, "
                f"or widening gap between leadership narrative and on-the-ground sentiment."
            )
        elif delta < -self.DIVERGENCE_HIGH:
            return (
                f"HIGH DIVERGENCE: {group} official messaging ({prop:+.2f}) diverges significantly "
                f"from civilian channels ({grass:+.2f}). "
                f"Indicates active narrative management — possible morale issues being masked."
            )
        elif delta > self.DIVERGENCE_HIGH:
            return (
                f"POSITIVE DIVERGENCE: {group} civilian channels ({grass:+.2f}) are MORE positive "
                f"than official messaging ({prop:+.2f}). "
                f"Suggests genuine grassroots support or a propaganda surge from below. "
                f"Assess for organic vs. coordinated amplification."
            )
        else:
            return (
                f"MODERATE DIVERGENCE: {group} official ({prop:+.2f}) vs civilian ({grass:+.2f}) "
                f"channels show meaningful but not crisis-level differences (Δ {delta:+.2f})."
            )

    def _build_source_timeline(self, df: pd.DataFrame) -> dict[str, list[dict]]:
        df = df.copy()
        df["month"] = df["timestamp"].dt.to_period("M").astype(str)
        timeline: dict[str, list[dict]] = {}
        for st in df["source_type"].unique():
            g = df[df["source_type"] == st]
            monthly = (
                g.groupby("month")
                .agg(
                    avg_sentiment=("sign", "mean"),
                    post_count=("post_id", "count"),
                    positive_pct=("sentiment", lambda x: (x == "positive").mean() * 100),
                    negative_pct=("sentiment", lambda x: (x == "negative").mean() * 100),
                )
                .reset_index()
            )
            timeline[st] = monthly.to_dict("records")
        return timeline

    def _compute_divergence_score(self, profiles: dict[str, SourceTypeProfile]) -> float:
        prop_types = [st for st in PROPAGANDA_TYPES if st in profiles]
        grass_types = [st for st in GRASSROOTS_TYPES if st in profiles]
        if not prop_types or not grass_types:
            return 0.0
        prop_score = sum(profiles[st].avg_sentiment for st in prop_types) / len(prop_types)
        grass_score = sum(profiles[st].avg_sentiment for st in grass_types) / len(grass_types)
        return min(abs(grass_score - prop_score), 1.0)

    @staticmethod
    def _top_themes(df: pd.DataFrame) -> list[str]:
        from collections import Counter
        theme_counter: Counter = Counter()
        for themes in df["themes"]:
            theme_counter.update(themes)
        return [t for t, _ in theme_counter.most_common(3)]

    def _to_df(self, results: list[SentimentResult]) -> pd.DataFrame:
        records = []
        for r in results:
            ts = r.timestamp
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            # Determine source_type from platform or raw metadata
            source_type = getattr(r, "source_type", None) or self._infer_source_type(r)
            records.append({
                "post_id": r.post_id,
                "platform": r.platform,
                "group_id": r.group_id,
                "source": r.source,
                "source_type": source_type,
                "text": r.text,
                "timestamp": ts,
                "sentiment": r.sentiment,
                "confidence": r.confidence,
                "engagement_weight": r.engagement_weight,
                "themes": r.themes,
            })
        return pd.DataFrame(records)

    @staticmethod
    def _infer_source_type(r: SentimentResult) -> str:
        """Infer source type from platform if not explicitly set."""
        platform = r.platform.lower()
        source = r.source.lower()
        if platform in ("rss", "web"):
            return platform
        if platform == "twitter":
            return "twitter_official" if not source.startswith("kw:") else "twitter_affiliated"
        if platform == "telegram":
            # Heuristic: source names containing "civilian" or "locals" etc.
            civilian_hints = ["civilian", "locals", "daily", "forum", "diaspora",
                              "opposition", "protest", "economy", "famine", "inflation"]
            if any(h in source.lower() for h in civilian_hints):
                return "civilian_telegram"
            official_hints = ["official", "media", "spokesman", "military", "news", "gov"]
            if any(h in source.lower() for h in official_hints):
                return "official_telegram"
            return "affiliated_telegram"
        return "unknown"
