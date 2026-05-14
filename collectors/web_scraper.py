"""
HTML web scraper for official party/organization websites.
Extracts article text using CSS selector heuristics.
Respects robots.txt and rate-limits.
"""

from __future__ import annotations

import hashlib
import re
import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from .base_collector import BaseCollector, RawPost

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (OSINT Research Bot; Academic Use)",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "ar,en;q=0.5",
}
_TIMEOUT = 25
_REQUEST_DELAY = 3.0
_MAX_PAGES_PER_SITE = 50

# Common article selectors tried in priority order
_ARTICLE_SELECTORS = [
    "article",
    "[class*='article-body']",
    "[class*='post-content']",
    "[class*='news-content']",
    "[class*='entry-content']",
    ".content",
    "main",
]
_TITLE_SELECTORS = ["h1", "h2.entry-title", "[class*='title']", "title"]
_DATE_PATTERNS = [
    r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})",
    r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})",
    r"(\d{4}/\d{2}/\d{2})",
    r"(\d{4}-\d{2}-\d{2})",
]
_HTML_TAG = re.compile(r"<[^>]+>")
_SCRIPT = re.compile(r"<script[^>]*>.*?</script>", re.DOTALL)
_STYLE = re.compile(r"<style[^>]*>.*?</style>", re.DOTALL)
_WHITESPACE = re.compile(r"\s+")


class WebScraper(BaseCollector):
    """Scrape article text from official Arabic party/media websites."""

    def __init__(self, config: dict, targets_config: dict):
        super().__init__(config, targets_config)
        self.session = requests.Session()
        self.session.headers.update(_HEADERS)
        self._robots: dict[str, RobotFileParser] = {}
        self.request_delay = _REQUEST_DELAY
        logger.info("WebScraper initialized")

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
            url = source.get("url")
            if not url or source.get("rss"):
                # Skip if RSS already covers it (prefer RSS)
                continue
            logger.info(f"[Web] Scraping {group_id}/{source['id']} ← {url}")
            scraped = self._scrape_site(
                url, group_id, source["id"],
                source.get("name", source["id"]),
                start_time, end_time,
            )
            posts.extend(scraped)
        return posts

    def collect_all_groups(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> list[RawPost]:
        all_posts: list[RawPost] = []
        for group_id in self.targets_config["groups"]:
            all_posts.extend(self.collect_group(group_id, start_time, end_time))
        return all_posts

    # ── Scraping logic ────────────────────────────────────────────────────────

    def _scrape_site(
        self,
        base_url: str,
        group_id: str,
        source_id: str,
        source_name: str,
        start_time: Optional[datetime],
        end_time: Optional[datetime],
    ) -> list[RawPost]:
        if not self._robots_allowed(base_url):
            logger.warning(f"[Web] robots.txt disallows: {base_url}")
            return []

        article_urls = self._discover_article_urls(base_url)
        posts: list[RawPost] = []
        for url in article_urls[:_MAX_PAGES_PER_SITE]:
            post = self._scrape_article(url, group_id, source_id, source_name)
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
            time.sleep(self.request_delay)
        logger.info(f"[Web] {source_id}: {len(posts)} articles scraped")
        return posts

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=2, min=5, max=30))
    def _discover_article_urls(self, base_url: str) -> list[str]:
        """Find article links from homepage/index pages."""
        urls: set[str] = set()
        try:
            resp = self.session.get(base_url, timeout=_TIMEOUT)
            resp.raise_for_status()
            href_pattern = re.compile(r'href=["\']([^"\']+)["\']')
            for href in href_pattern.findall(resp.text):
                full = urljoin(base_url, href)
                if self._looks_like_article(full, base_url):
                    urls.add(full)
        except Exception as exc:
            logger.debug(f"[Web] Discovery error {base_url}: {exc}")
        return list(urls)[:_MAX_PAGES_PER_SITE]

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=2, min=3, max=20))
    def _scrape_article(
        self,
        url: str,
        group_id: str,
        source_id: str,
        source_name: str,
    ) -> Optional[RawPost]:
        try:
            resp = self.session.get(url, timeout=_TIMEOUT)
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding or "utf-8"
        except Exception as exc:
            logger.debug(f"[Web] Fetch error {url}: {exc}")
            return None

        html = resp.text
        text = self._extract_text(html)
        if len(text.strip()) < 30:
            return None

        ts = self._extract_date(html)
        post_id = f"web_{source_id}_{hashlib.md5(url.encode()).hexdigest()[:12]}"

        return RawPost(
            post_id=post_id,
            platform="web",
            group_id=group_id,
            source=source_name,
            text=text[:4000],  # cap length
            timestamp=ts,
            language="ar",
            engagement={"url": url},
            raw={"url": url, "source_type": "web_official"},
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _extract_text(self, html: str) -> str:
        html = _SCRIPT.sub(" ", html)
        html = _STYLE.sub(" ", html)
        html = _HTML_TAG.sub(" ", html)
        html = _WHITESPACE.sub(" ", html)
        return html.strip()

    def _extract_date(self, html: str) -> datetime:
        for pattern in _DATE_PATTERNS:
            m = re.search(pattern, html)
            if m:
                raw = m.group(1)
                for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
                            "%Y/%m/%d", "%Y-%m-%d"):
                    try:
                        dt = datetime.strptime(raw[:len(fmt)], fmt)
                        return dt.replace(tzinfo=timezone.utc)
                    except ValueError:
                        pass
        return datetime.now(timezone.utc)

    def _looks_like_article(self, url: str, base_url: str) -> bool:
        parsed_base = urlparse(base_url)
        parsed = urlparse(url)
        if parsed.netloc and parsed.netloc != parsed_base.netloc:
            return False
        path = parsed.path
        # Article paths usually have a numeric ID or date segment
        if re.search(r"/\d{4}/\d{2}/\d{2}/", path):
            return True
        if re.search(r"/\d{5,}/", path):
            return True
        if re.search(r"/(article|news|report|story|post|khabar|akhbar)/", path, re.I):
            return True
        return False

    def _robots_allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        if base not in self._robots:
            rp = RobotFileParser()
            rp.set_url(f"{base}/robots.txt")
            try:
                rp.read()
            except Exception:
                pass
            self._robots[base] = rp
        return self._robots[base].can_fetch(_HEADERS["User-Agent"], url)
