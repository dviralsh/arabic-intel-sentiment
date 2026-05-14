"""
RSS/Atom feed collector for official Arabic media outlets.
Handles pagination, deduplication, and encoding issues common in Arabic feeds.
"""

from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from typing import Optional
from xml.etree import ElementTree as ET

import requests
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from .base_collector import BaseCollector, RawPost

_FEED_TIMEOUT = 30
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (OSINT Research Bot; Academic Use)",
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
    "Accept-Language": "ar,en;q=0.5",
}

# Atom namespace
_ATOM_NS = "http://www.w3.org/2005/Atom"
_CONTENT_NS = "http://purl.org/rss/1.0/modules/content/"
_DC_NS = "http://purl.org/dc/elements/1.1/"


class RSSCollector(BaseCollector):
    """Collect posts from RSS/Atom feeds of official media outlets."""

    def __init__(self, config: dict, targets_config: dict):
        super().__init__(config, targets_config)
        self.session = requests.Session()
        self.session.headers.update(_HEADERS)
        self.request_delay = 2.0
        logger.info("RSSCollector initialized")

    # ── Public API ────────────────────────────────────────────────────────────

    def collect_group(
        self,
        group_id: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> list[RawPost]:
        group = self.targets_config["groups"].get(group_id)
        if not group:
            return []
        posts: list[RawPost] = []
        for source in group.get("official_media", []):
            rss_url = source.get("rss")
            if not rss_url:
                continue
            logger.info(f"[RSS] {group_id}/{source['id']} ← {rss_url}")
            fetched = self._fetch_feed(
                rss_url, group_id, source["id"],
                source.get("name", source["id"]),
                "official_media", start_time, end_time,
            )
            posts.extend(fetched)
            time.sleep(self.request_delay)
        return posts

    def collect_all_groups(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> list[RawPost]:
        all_posts: list[RawPost] = []
        for group_id in self.targets_config["groups"]:
            all_posts.extend(self.collect_group(group_id, start_time, end_time))
        logger.info(f"[RSS] Total collected: {len(all_posts)}")
        return all_posts

    # ── Feed fetching ─────────────────────────────────────────────────────────

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=5, max=60))
    def _fetch_feed(
        self,
        url: str,
        group_id: str,
        source_id: str,
        source_name: str,
        source_type: str,
        start_time: Optional[datetime],
        end_time: Optional[datetime],
    ) -> list[RawPost]:
        try:
            resp = self.session.get(url, timeout=_FEED_TIMEOUT)
            resp.raise_for_status()
            # Force UTF-8 for Arabic content
            resp.encoding = resp.apparent_encoding or "utf-8"
            return self._parse_feed(
                resp.text, group_id, source_id, source_name, source_type,
                start_time, end_time,
            )
        except requests.RequestException as exc:
            logger.warning(f"[RSS] Failed {url}: {exc}")
            return []

    def _parse_feed(
        self,
        xml_text: str,
        group_id: str,
        source_id: str,
        source_name: str,
        source_type: str,
        start_time: Optional[datetime],
        end_time: Optional[datetime],
    ) -> list[RawPost]:
        posts: list[RawPost] = []
        try:
            root = ET.fromstring(xml_text.encode("utf-8"))
        except ET.ParseError as exc:
            logger.debug(f"[RSS] XML parse error for {source_id}: {exc}")
            return []

        # Detect feed format
        tag = root.tag.lower()
        if "feed" in tag or root.tag == f"{{{_ATOM_NS}}}feed":
            items = (
                root.findall(f"{{{_ATOM_NS}}}entry")
                or root.findall("entry")
            )
            parser = self._parse_atom_entry
        else:
            channel = root.find("channel") or root
            items = channel.findall("item")
            parser = self._parse_rss_item

        for item in items:
            post = parser(
                item, group_id, source_id, source_name, source_type,
            )
            if post is None:
                continue
            ts = post.timestamp
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if start_time and ts < start_time:
                continue
            if end_time and ts > end_time:
                continue
            posts.append(post)

        logger.debug(f"[RSS] {source_id}: {len(posts)} items")
        return posts

    def _parse_rss_item(
        self, item: ET.Element,
        group_id: str, source_id: str, source_name: str, source_type: str,
    ) -> Optional[RawPost]:
        title = self._text(item, "title") or ""
        desc = self._text(item, "description") or ""
        content = self._text(item, f"{{{_CONTENT_NS}}}encoded") or ""
        text = self._best_text(title, desc, content)
        if len(text.strip()) < 10:
            return None

        link = self._text(item, "link") or ""
        pub_date = self._text(item, "pubDate") or self._text(item, f"{{{_DC_NS}}}date") or ""
        ts = self._parse_date(pub_date)
        post_id = f"rss_{source_id}_{hashlib.md5(link.encode()).hexdigest()[:10]}"

        return RawPost(
            post_id=post_id,
            platform="rss",
            group_id=group_id,
            source=source_name,
            text=text,
            timestamp=ts,
            language="ar",
            engagement={"url": link},
            raw={"link": link, "source_type": source_type},
        )

    def _parse_atom_entry(
        self, entry: ET.Element,
        group_id: str, source_id: str, source_name: str, source_type: str,
    ) -> Optional[RawPost]:
        ns = _ATOM_NS
        title = self._text(entry, f"{{{ns}}}title") or self._text(entry, "title") or ""
        summary = self._text(entry, f"{{{ns}}}summary") or self._text(entry, "summary") or ""
        content = self._text(entry, f"{{{ns}}}content") or self._text(entry, "content") or ""
        text = self._best_text(title, summary, content)
        if len(text.strip()) < 10:
            return None

        link_el = entry.find(f"{{{ns}}}link") or entry.find("link")
        link = link_el.get("href", "") if link_el is not None else ""
        updated = (
            self._text(entry, f"{{{ns}}}updated")
            or self._text(entry, f"{{{ns}}}published")
            or self._text(entry, "updated")
            or ""
        )
        ts = self._parse_date(updated)
        post_id = f"atom_{source_id}_{hashlib.md5(link.encode()).hexdigest()[:10]}"

        return RawPost(
            post_id=post_id,
            platform="rss",
            group_id=group_id,
            source=source_name,
            text=text,
            timestamp=ts,
            language="ar",
            engagement={"url": link},
            raw={"link": link, "source_type": source_type},
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _text(el: ET.Element, tag: str) -> str:
        child = el.find(tag)
        return (child.text or "").strip() if child is not None else ""

    @staticmethod
    def _best_text(*candidates: str) -> str:
        """Return the longest non-empty candidate, stripped of HTML tags."""
        import re
        _html = re.compile(r"<[^>]+>")
        best = ""
        for c in candidates:
            cleaned = _html.sub(" ", c).strip()
            if len(cleaned) > len(best):
                best = cleaned
        return best

    @staticmethod
    def _parse_date(raw: str) -> datetime:
        """Parse RSS/Atom date strings to datetime."""
        if not raw:
            return datetime.now(timezone.utc)
        raw = raw.strip()
        # Try RFC 2822 (RSS)
        try:
            return parsedate_to_datetime(raw)
        except Exception:
            pass
        # Try ISO 8601 (Atom)
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ",
                    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(raw[:len(fmt)], fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                pass
        return datetime.now(timezone.utc)
