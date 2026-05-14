"""
GitHub State Manager — incremental collection with persistent watermarks.

State schema (data/state/collection_state.json):
{
  "sources": {
    "<source_id>": {
      "last_post_id":   "...",
      "last_timestamp": "2025-03-01T00:00:00+00:00",
      "total_collected": 4521,
      "last_run":       "2026-05-14T06:00:00+00:00"
    }
  },
  "partitions": {
    "2025-01": { "hezbollah": 890, "irgc_iran": 1100, ... },
    ...
  },
  "schema_version": 2
}

Cached posts are stored as monthly JSON partitions:
  data/cache/posts_2024_01.json
  data/cache/posts_2024_02.json
  ...

On each run:
  1. Load state → know where each source left off
  2. Collect only new posts (after last_timestamp)
  3. Merge new posts into existing monthly partitions
  4. Update watermarks and commit state + new partitions to GitHub
"""

from __future__ import annotations

import json
import os
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from loguru import logger

from .base_collector import RawPost

_STATE_FILE = Path("data/state/collection_state.json")
_CACHE_DIR = Path("data/cache")
_SCHEMA_VERSION = 2


class StateManager:
    """Manages persistent collection state and cached post partitions."""

    def __init__(self, state_file: Path = _STATE_FILE, cache_dir: Path = _CACHE_DIR):
        self.state_file = Path(state_file)
        self.cache_dir = Path(cache_dir)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._state: dict = self._load_state()

    # ── State I/O ─────────────────────────────────────────────────────────────

    def _load_state(self) -> dict:
        if self.state_file.exists():
            try:
                with open(self.state_file, encoding="utf-8") as f:
                    state = json.load(f)
                if state.get("schema_version") != _SCHEMA_VERSION:
                    logger.warning("State schema mismatch — resetting state")
                    return self._empty_state()
                return state
            except Exception as exc:
                logger.warning(f"State load error: {exc} — resetting")
        return self._empty_state()

    def _empty_state(self) -> dict:
        return {
            "schema_version": _SCHEMA_VERSION,
            "sources": {},
            "partitions": {},
            "total_posts": 0,
            "last_full_run": None,
        }

    def save_state(self):
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(self._state, f, ensure_ascii=False, indent=2, default=str)
        logger.info(f"State saved → {self.state_file}")

    # ── Watermarks ────────────────────────────────────────────────────────────

    def get_watermark(self, source_id: str) -> Optional[datetime]:
        """Return the last-seen timestamp for a source, or None if new."""
        src = self._state["sources"].get(source_id)
        if not src or not src.get("last_timestamp"):
            return None
        try:
            return datetime.fromisoformat(src["last_timestamp"])
        except ValueError:
            return None

    def update_watermark(self, source_id: str, posts: list[RawPost]):
        """Update watermark to the newest post seen for this source."""
        if not posts:
            return
        newest = max(
            (p.timestamp for p in posts),
            default=None,
        )
        if newest is None:
            return
        if newest.tzinfo is None:
            newest = newest.replace(tzinfo=timezone.utc)

        existing = self._state["sources"].get(source_id, {})
        prev_total = existing.get("total_collected", 0)
        self._state["sources"][source_id] = {
            "last_post_id": posts[-1].post_id,
            "last_timestamp": newest.isoformat(),
            "total_collected": prev_total + len(posts),
            "last_run": datetime.now(timezone.utc).isoformat(),
        }

    # ── Post cache ────────────────────────────────────────────────────────────

    def load_cached_posts(
        self,
        group_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> list[dict]:
        """Load cached posts from monthly partitions."""
        posts: list[dict] = []
        for partition_file in sorted(self.cache_dir.glob("posts_*.json")):
            # Extract year-month from filename
            stem = partition_file.stem  # posts_2024_01
            parts = stem.split("_")
            if len(parts) < 3:
                continue
            year, month = int(parts[1]), int(parts[2])
            partition_dt = datetime(year, month, 1, tzinfo=timezone.utc)

            # Skip out-of-range months
            if end_time and partition_dt > end_time:
                continue
            import calendar
            last_day = calendar.monthrange(year, month)[1]
            partition_end = datetime(year, month, last_day, 23, 59, 59, tzinfo=timezone.utc)
            if start_time and partition_end < start_time:
                continue

            try:
                with open(partition_file, encoding="utf-8") as f:
                    batch = json.load(f)
                if group_id:
                    batch = [p for p in batch if p.get("group_id") == group_id]
                posts.extend(batch)
            except Exception as exc:
                logger.warning(f"Cache read error {partition_file}: {exc}")

        logger.info(f"Loaded {len(posts)} cached posts from disk")
        return posts

    def save_posts(self, posts: list[RawPost]):
        """Merge new posts into monthly partition files."""
        by_month: dict[str, list[dict]] = defaultdict(list)
        for p in posts:
            ts = p.timestamp
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            key = ts.strftime("%Y_%m")
            by_month[key].append(self._post_to_dict(p))

        for month_key, new_records in by_month.items():
            partition_file = self.cache_dir / f"posts_{month_key}.json"
            existing: list[dict] = []
            if partition_file.exists():
                try:
                    with open(partition_file, encoding="utf-8") as f:
                        existing = json.load(f)
                except Exception:
                    pass

            # Deduplicate by post_id
            seen_ids = {r["post_id"] for r in existing}
            new_unique = [r for r in new_records if r["post_id"] not in seen_ids]
            merged = existing + new_unique

            with open(partition_file, "w", encoding="utf-8") as f:
                json.dump(merged, f, ensure_ascii=False, separators=(",", ":"), default=str)

            logger.info(f"Partition {month_key}: {len(merged)} posts (+{len(new_unique)} new)")

            # Update partition stats
            if month_key not in self._state["partitions"]:
                self._state["partitions"][month_key] = {}
            # Update group counts in partition
            from collections import Counter
            group_counts = Counter(r["group_id"] for r in merged)
            self._state["partitions"][month_key] = dict(group_counts)

        self._state["total_posts"] = sum(
            sum(gc.values()) for gc in self._state["partitions"].values()
            if isinstance(gc, dict)
        )

    def get_collection_stats(self) -> dict:
        """Return current collection statistics."""
        groups: dict[str, int] = defaultdict(int)
        source_types: dict[str, int] = defaultdict(int)
        months: list[str] = []
        for month_key, group_counts in self._state.get("partitions", {}).items():
            months.append(month_key)
            if isinstance(group_counts, dict):
                for gid, count in group_counts.items():
                    groups[gid] += count
        return {
            "total_posts": self._state.get("total_posts", 0),
            "by_group": dict(groups),
            "months_covered": sorted(months),
            "sources_tracked": len(self._state.get("sources", {})),
        }

    def needs_more_data(self, group_id: str, target: int = 10000) -> bool:
        """True if a group has fewer than target posts in current period."""
        stats = self.get_collection_stats()
        return stats["by_group"].get(group_id, 0) < target

    # ── GitHub sync ───────────────────────────────────────────────────────────

    def commit_to_github(self, message: Optional[str] = None):
        """Commit state and cache files to git. Used in CI."""
        if message is None:
            stats = self.get_collection_stats()
            message = f"data: update state ({stats['total_posts']:,} total posts) [skip ci]"

        files_to_add = [
            str(self.state_file),
            str(self.cache_dir),
        ]
        try:
            subprocess.run(
                ["git", "config", "user.email", "actions@github.com"],
                check=False, capture_output=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "github-actions[bot]"],
                check=False, capture_output=True,
            )
            subprocess.run(["git", "add"] + files_to_add, check=True, capture_output=True)
            result = subprocess.run(
                ["git", "diff", "--cached", "--quiet"],
                capture_output=True,
            )
            if result.returncode != 0:
                subprocess.run(["git", "commit", "-m", message], check=True, capture_output=True)
                subprocess.run(["git", "push"], check=True, capture_output=True)
                logger.info("State committed and pushed to GitHub")
            else:
                logger.info("No state changes to commit")
        except subprocess.CalledProcessError as exc:
            logger.error(f"Git commit failed: {exc}")

    # ── Serialization ─────────────────────────────────────────────────────────

    @staticmethod
    def _post_to_dict(p: RawPost) -> dict:
        ts = p.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return {
            "post_id": p.post_id,
            "platform": p.platform,
            "group_id": p.group_id,
            "source": p.source,
            "text": p.text,
            "timestamp": ts.isoformat(),
            "language": p.language,
            "engagement": p.engagement,
            "source_type": p.raw.get("source_type", "unknown"),
        }

    @staticmethod
    def dict_to_raw_post(d: dict) -> RawPost:
        from .base_collector import RawPost as RP
        ts_raw = d.get("timestamp", "")
        try:
            ts = datetime.fromisoformat(ts_raw)
        except ValueError:
            ts = datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return RP(
            post_id=d["post_id"],
            platform=d.get("platform", "unknown"),
            group_id=d["group_id"],
            source=d.get("source", ""),
            text=d.get("text", ""),
            timestamp=ts,
            language=d.get("language", "ar"),
            engagement=d.get("engagement", {}),
            raw={"source_type": d.get("source_type", "unknown")},
        )
