"""
Twitter/X API v2 collector for Arabic OSINT intelligence.
Uses Academic/Basic tier endpoints with full-archive search where available.
"""

import time
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import tweepy
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from .base_collector import BaseCollector, RawPost


class TwitterCollector(BaseCollector):
    """Collect tweets from Twitter/X API v2."""

    def __init__(self, config: dict, targets_config: dict):
        super().__init__(config, targets_config)
        api_cfg = config["api"]["twitter"]
        self.bearer_token = api_cfg["bearer_token"]
        self.max_results = api_cfg.get("max_results_per_request", 100)
        self.client = tweepy.Client(
            bearer_token=self.bearer_token,
            wait_on_rate_limit=True,
        )
        logger.info("TwitterCollector initialized")

    # ──────────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────────

    def collect_group(
        self,
        group_id: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> list[RawPost]:
        """Collect all tweets for a target group."""
        group = self.targets_config["groups"].get(group_id)
        if not group:
            logger.error(f"Group '{group_id}' not found in targets config")
            return []

        posts: list[RawPost] = []

        # Collect by account handle
        for acct in group.get("twitter_accounts", []):
            handle = acct["handle"]
            logger.info(f"[Twitter] Collecting @{handle} for group '{group_id}'")
            posts.extend(self._collect_user_timeline(handle, group_id, start_time, end_time))
            time.sleep(1)  # gentle rate-limit buffer

        # Collect by keyword search
        keywords = group.get("keywords_ar", []) + group.get("keywords_en", [])
        for kw in keywords[:5]:  # cap to avoid quota exhaustion
            logger.info(f"[Twitter] Searching keyword '{kw}' for group '{group_id}'")
            posts.extend(self._search_keyword(kw, group_id, start_time, end_time))
            time.sleep(1)

        logger.info(f"[Twitter] Collected {len(posts)} posts for group '{group_id}'")
        return posts

    def collect_all_groups(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> list[RawPost]:
        """Collect tweets for all configured groups."""
        all_posts: list[RawPost] = []
        for group_id in self.targets_config["groups"]:
            all_posts.extend(self.collect_group(group_id, start_time, end_time))
        return all_posts

    # ──────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────────────────────

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=10, max=120))
    def _collect_user_timeline(
        self,
        handle: str,
        group_id: str,
        start_time: Optional[datetime],
        end_time: Optional[datetime],
    ) -> list[RawPost]:
        posts: list[RawPost] = []
        try:
            user_resp = self.client.get_user(username=handle, user_fields=["id"])
            if not user_resp.data:
                logger.warning(f"User @{handle} not found")
                return []
            user_id = user_resp.data.id

            paginator = tweepy.Paginator(
                self.client.get_users_tweets,
                id=user_id,
                start_time=start_time,
                end_time=end_time,
                tweet_fields=["created_at", "lang", "public_metrics", "text", "entities"],
                max_results=min(self.max_results, 100),
                limit=20,  # max 20 pages per call
            )
            for tweet in paginator.flatten(limit=2000):
                posts.append(self._tweet_to_raw_post(tweet, group_id, f"@{handle}"))
        except tweepy.TweepyException as exc:
            logger.error(f"Twitter API error for @{handle}: {exc}")
        return posts

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=10, max=120))
    def _search_keyword(
        self,
        keyword: str,
        group_id: str,
        start_time: Optional[datetime],
        end_time: Optional[datetime],
    ) -> list[RawPost]:
        posts: list[RawPost] = []
        query = f'"{keyword}" lang:ar -is:retweet'
        try:
            paginator = tweepy.Paginator(
                self.client.search_recent_tweets,
                query=query,
                start_time=start_time,
                end_time=end_time,
                tweet_fields=["created_at", "lang", "public_metrics", "text"],
                max_results=100,
                limit=10,
            )
            for tweet in paginator.flatten(limit=1000):
                posts.append(self._tweet_to_raw_post(tweet, group_id, f"kw:{keyword}"))
        except tweepy.TweepyException as exc:
            logger.error(f"Twitter search error for '{keyword}': {exc}")
        return posts

    def _tweet_to_raw_post(self, tweet, group_id: str, source: str) -> RawPost:
        metrics = tweet.public_metrics or {}
        return RawPost(
            post_id=str(tweet.id),
            platform="twitter",
            group_id=group_id,
            source=source,
            text=tweet.text,
            timestamp=tweet.created_at or datetime.now(timezone.utc),
            language=tweet.lang or "ar",
            engagement={
                "likes": metrics.get("like_count", 0),
                "retweets": metrics.get("retweet_count", 0),
                "replies": metrics.get("reply_count", 0),
                "quotes": metrics.get("quote_count", 0),
            },
            raw={"id": str(tweet.id), "text": tweet.text},
        )
