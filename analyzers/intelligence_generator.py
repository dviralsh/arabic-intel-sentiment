"""
Master intelligence report generator.
Aggregates sentiment results, comparative assessments, source-type profiles,
topics, entities and collection stats into the final JSON consumed by the dashboard.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
from loguru import logger

from .comparative_engine import IntelAssessment
from .sentiment_engine import SentimentResult
from .topic_modeler import TopicResult
from .entity_extractor import EntityExtractor


class IntelligenceGenerator:
    def __init__(self, targets_config: dict, output_dir: str = "dashboard/data"):
        self.targets_config = targets_config
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.entity_extractor = EntityExtractor()

    def generate(
        self,
        sentiment_results: list[SentimentResult],
        assessments: list[IntelAssessment],
        topics: dict[str, list[TopicResult]],
        baseline_start: datetime,
        baseline_end: datetime,
        current_start: datetime,
        current_end: datetime,
        generated_at: Optional[datetime] = None,
        source_data: Optional[dict] = None,
        collection_stats: Optional[dict] = None,
    ) -> dict:
        if generated_at is None:
            generated_at = datetime.now(timezone.utc)

        df = self._results_to_df(sentiment_results)

        report = {
            "meta": {
                "generated_at": generated_at.isoformat(),
                "baseline_period": {
                    "start": baseline_start.isoformat(),
                    "end": baseline_end.isoformat(),
                    "label": "2024 Baseline",
                },
                "current_period": {
                    "start": current_start.isoformat(),
                    "end": current_end.isoformat(),
                    "label": "Current (2025–2026)",
                },
                "total_posts_analyzed": len(sentiment_results),
                "groups": list(self.targets_config["groups"].keys()),
                "collection_stats": collection_stats or {},
            },
            "summary": self._build_summary(df, assessments),
            "assessments": self._serialize_assessments(assessments),
            "timeline": self._build_timeline(df),
            "group_profiles": self._build_group_profiles(df, topics),
            "entity_map": self._build_entity_map(df),
            "theme_matrix": self._build_theme_matrix(df),
            "top_evidence": self._build_top_evidence(df),
            "source_analysis": source_data or {},
            "source_type_timeline": self._build_source_type_timeline(df),
            "platform_breakdown": self._build_platform_breakdown(df),
        }

        output_path = self.output_dir / "intelligence_report.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)
        logger.info(f"Intelligence report → {output_path} ({output_path.stat().st_size // 1024} KB)")

        # Lightweight summary for fast initial load
        summary_path = self.output_dir / "summary.json"
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump({
                "meta": report["meta"],
                "summary": report["summary"],
                "assessments": report["assessments"][:20],
            }, f, ensure_ascii=False, indent=2, default=str)

        return report

    # ── Builders ──────────────────────────────────────────────────────────────

    def _results_to_df(self, results: list[SentimentResult]) -> pd.DataFrame:
        records = []
        for r in results:
            ts = r.timestamp
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            source_type = getattr(r, "source_type", None) or r.raw.get("source_type", "unknown") if hasattr(r, "raw") else "unknown"
            records.append({
                "post_id": r.post_id,
                "platform": r.platform,
                "group_id": r.group_id,
                "source": r.source,
                "source_type": source_type,
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
            })
        return pd.DataFrame(records)

    def _build_summary(self, df: pd.DataFrame, assessments: list[IntelAssessment]) -> dict:
        summary: dict = {
            "total_posts": len(df),
            "platforms": df["platform"].value_counts().to_dict() if not df.empty else {},
            "groups": {},
            "top_assessments": [],
        }
        if not df.empty:
            sign_map = {"positive": 1.0, "negative": -1.0, "neutral": 0.0}
            df2 = df.copy()
            df2["sign"] = df2["sentiment"].map(sign_map).fillna(0.0)
            df2["ws"] = df2["sign"] * df2["confidence"] * df2["engagement_weight"]
            for group_id, gcfg in self.targets_config["groups"].items():
                g = df2[df2["group_id"] == group_id]
                if g.empty:
                    continue
                total_w = g["engagement_weight"].sum()
                avg_sent = float(g["ws"].sum() / total_w) if total_w > 0 else 0.0
                summary["groups"][group_id] = {
                    "display_name": gcfg["display_name"],
                    "color": gcfg.get("color", "#888"),
                    "post_count": len(g),
                    "avg_sentiment_score": round(avg_sent, 3),
                    "positive_pct": round((g["sentiment"] == "positive").mean() * 100, 1),
                    "negative_pct": round((g["sentiment"] == "negative").mean() * 100, 1),
                    "neutral_pct": round((g["sentiment"] == "neutral").mean() * 100, 1),
                    "platforms": g["platform"].value_counts().to_dict(),
                    "source_types": g["source_type"].value_counts().to_dict(),
                }
        summary["top_assessments"] = [
            {
                "group": a.group_display_name,
                "theme": a.theme,
                "theme_label": a.theme_label,
                "narrative": a.narrative,
                "delta_pct": a.delta_pct,
                "direction": a.direction,
                "confidence": a.confidence,
                "magnitude": a.magnitude,
            }
            for a in assessments[:15]
        ]
        return summary

    def _serialize_assessments(self, assessments: list[IntelAssessment]) -> list[dict]:
        return [
            {
                "group_id": a.group_id,
                "group_display_name": a.group_display_name,
                "theme": a.theme,
                "theme_label": a.theme_label,
                "direction": a.direction,
                "magnitude": a.magnitude,
                "confidence": a.confidence,
                "delta_pct": a.delta_pct,
                "baseline_score": a.baseline_score,
                "current_score": a.current_score,
                "narrative": a.narrative,
                "evidence": a.evidence,
                "timestamp": a.timestamp,
            }
            for a in assessments
        ]

    def _build_timeline(self, df: pd.DataFrame) -> dict:
        if df.empty:
            return {}
        df2 = df.copy()
        df2["month"] = df2["timestamp"].dt.to_period("M").astype(str)
        sign_map = {"positive": 1.0, "negative": -1.0, "neutral": 0.0}
        df2["sign"] = df2["sentiment"].map(sign_map).fillna(0.0)
        df2["ws"] = df2["sign"] * df2["confidence"]
        timeline: dict = {}
        for group_id in df2["group_id"].unique():
            g = df2[df2["group_id"] == group_id]
            monthly = g.groupby("month").agg(
                avg_sentiment=("ws", "mean"),
                post_count=("post_id", "count"),
                positive_pct=("sentiment", lambda x: (x == "positive").mean() * 100),
                negative_pct=("sentiment", lambda x: (x == "negative").mean() * 100),
            ).reset_index()
            timeline[group_id] = monthly.to_dict("records")
        return timeline

    def _build_source_type_timeline(self, df: pd.DataFrame) -> dict:
        """Monthly timeline per group per source type."""
        if df.empty:
            return {}
        df2 = df.copy()
        df2["month"] = df2["timestamp"].dt.to_period("M").astype(str)
        sign_map = {"positive": 1.0, "negative": -1.0, "neutral": 0.0}
        df2["sign"] = df2["sentiment"].map(sign_map).fillna(0.0)
        result: dict = {}
        for group_id in df2["group_id"].unique():
            result[group_id] = {}
            g = df2[df2["group_id"] == group_id]
            for src_type in g["source_type"].unique():
                st = g[g["source_type"] == src_type]
                monthly = st.groupby("month").agg(
                    avg_sentiment=("sign", "mean"),
                    post_count=("post_id", "count"),
                    negative_pct=("sentiment", lambda x: (x == "negative").mean() * 100),
                ).reset_index()
                result[group_id][src_type] = monthly.to_dict("records")
        return result

    def _build_platform_breakdown(self, df: pd.DataFrame) -> dict:
        if df.empty:
            return {}
        result: dict = {}
        for group_id in df["group_id"].unique():
            g = df[df["group_id"] == group_id]
            sign_map = {"positive": 1.0, "negative": -1.0, "neutral": 0.0}
            g2 = g.copy()
            g2["sign"] = g2["sentiment"].map(sign_map).fillna(0.0)
            result[group_id] = {}
            for platform in g["platform"].unique():
                p = g2[g2["platform"] == platform]
                result[group_id][platform] = {
                    "count": len(p),
                    "avg_sentiment": round(float(p["sign"].mean()), 3),
                    "positive_pct": round((p["sentiment"] == "positive").mean() * 100, 1),
                    "negative_pct": round((p["sentiment"] == "negative").mean() * 100, 1),
                    "source_types": p["source_type"].value_counts().to_dict(),
                }
        return result

    def _build_group_profiles(self, df: pd.DataFrame, topics: dict[str, list[TopicResult]]) -> dict:
        profiles: dict = {}
        for group_id, gcfg in self.targets_config["groups"].items():
            g = df[df["group_id"] == group_id] if not df.empty else pd.DataFrame()
            group_topics = topics.get(group_id, [])
            profiles[group_id] = {
                "display_name": gcfg["display_name"],
                "color": gcfg.get("color", "#888"),
                "post_count": len(g),
                "topics": [
                    {
                        "topic_id": t.topic_id,
                        "label": t.label,
                        "size": t.size,
                        "share": t.share,
                        "top_words": t.top_words,
                        "sentiment_distribution": t.sentiment_distribution,
                        "avg_sentiment_score": t.avg_sentiment_score,
                        "trend": t.trend,
                        "representative_texts": t.representative_texts[:3],
                    }
                    for t in group_topics[:10]
                ],
            }
        return profiles

    def _build_entity_map(self, df: pd.DataFrame) -> dict:
        entity_map: dict = {}
        for group_id in self.targets_config["groups"]:
            g = df[df["group_id"] == group_id] if not df.empty else pd.DataFrame()
            if g.empty:
                entity_map[group_id] = {}
                continue
            raw = self.entity_extractor.extract_from_texts(g["text"].tolist(), group_id)
            entity_map[group_id] = self.entity_extractor.to_serializable(raw)
        return entity_map

    def _build_theme_matrix(self, df: pd.DataFrame) -> dict:
        if df.empty:
            return {}
        analysis_cfg = self.targets_config.get("analysis", {})
        themes = [t["id"] for t in analysis_cfg.get("themes", [])]
        sign_map = {"positive": 1.0, "negative": -1.0, "neutral": 0.0}
        df2 = df.copy()
        df2["sign"] = df2["sentiment"].map(sign_map).fillna(0.0)
        matrix: dict = {}
        for group_id in self.targets_config["groups"]:
            matrix[group_id] = {}
            g = df2[df2["group_id"] == group_id]
            for theme_id in themes:
                t = g[g["themes"].apply(lambda ts: theme_id in ts)]
                if t.empty:
                    matrix[group_id][theme_id] = {"count": 0, "avg_sentiment": 0.0}
                else:
                    matrix[group_id][theme_id] = {
                        "count": len(t),
                        "avg_sentiment": round(float(t["sign"].mean()), 3),
                        "positive_pct": round((t["sentiment"] == "positive").mean() * 100, 1),
                        "negative_pct": round((t["sentiment"] == "negative").mean() * 100, 1),
                    }
        return matrix

    def _build_top_evidence(self, df: pd.DataFrame, limit: int = 30) -> dict:
        evidence: dict = {}
        if df.empty:
            return evidence
        for group_id in self.targets_config["groups"]:
            g = df[df["group_id"] == group_id]
            if g.empty:
                evidence[group_id] = []
                continue
            top = g.nlargest(limit, "engagement_weight")
            evidence[group_id] = [
                {
                    "post_id": row["post_id"],
                    "platform": row["platform"],
                    "source": row["source"],
                    "source_type": row.get("source_type", "unknown"),
                    "text": row.get("original_text", row["text"])[:600],
                    "timestamp": row["timestamp"].isoformat(),
                    "sentiment": row["sentiment"],
                    "confidence": round(float(row["confidence"]), 3),
                    "themes": row["themes"],
                }
                for _, row in top.iterrows()
            ]
        return evidence
