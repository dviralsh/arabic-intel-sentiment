"""
Telegram collector using Telethon (MTProto).
Reads public channels — no authentication bypass, public data only.
"""

import asyncio
import time
from datetime import datetime, timezone
from typing import Optional

from loguru import logger
from telethon import TelegramClient
from telethon.errors import (
    ChannelPrivateError,
    UsernameNotOccupiedError,
    FloodWaitError,
)
from telethon.tl.types import Message, MessageMediaPhoto, MessageMediaDocument

from .base_collector import BaseCollector, RawPost


class TelegramCollector(BaseCollector):
    """Collect messages from public Telegram channels."""

    def __init__(self, config: dict, targets_config: dict):
        super().__init__(config, targets_config)
        tg_cfg = config["api"]["telegram"]
        self.api_id = int(tg_cfg["api_id"])
        self.api_hash = tg_cfg["api_hash"]
        self.session_name = tg_cfg.get("session_name", "intel_collector")
        self.request_delay = tg_cfg.get("request_delay", 2)
        self.max_messages = tg_cfg.get("max_messages_per_channel", 5000)
        self._client: Optional[TelegramClient] = None
        logger.info("TelegramCollector initialized")

    # ──────────────────────────────────────────────────────────────────────────
    # Public API (sync wrappers around async internals)
    # ──────────────────────────────────────────────────────────────────────────

    def collect_group(
        self,
        group_id: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> list[RawPost]:
        return asyncio.run(self._async_collect_group(group_id, start_time, end_time))

    def collect_all_groups(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> list[RawPost]:
        return asyncio.run(self._async_collect_all(start_time, end_time))

    # ──────────────────────────────────────────────────────────────────────────
    # Async internals
    # ──────────────────────────────────────────────────────────────────────────

    async def _get_client(self) -> TelegramClient:
        if self._client is None or not self._client.is_connected():
            self._client = TelegramClient(self.session_name, self.api_id, self.api_hash)
            await self._client.start()
        return self._client

    async def _async_collect_group(
        self,
        group_id: str,
        start_time: Optional[datetime],
        end_time: Optional[datetime],
    ) -> list[RawPost]:
        group = self.targets_config["groups"].get(group_id)
        if not group:
            logger.error(f"Group '{group_id}' not found")
            return []

        client = await self._get_client()
        posts: list[RawPost] = []

        for channel_info in group.get("telegram_channels", []):
            username = channel_info["username"]
            logger.info(f"[Telegram] Collecting @{username} for '{group_id}'")
            try:
                channel_posts = await self._collect_channel(
                    client, username, group_id, start_time, end_time
                )
                posts.extend(channel_posts)
            except ChannelPrivateError:
                logger.warning(f"Channel @{username} is private — skipping")
            except UsernameNotOccupiedError:
                logger.warning(f"Channel @{username} does not exist — skipping")
            except FloodWaitError as e:
                logger.warning(f"FloodWait {e.seconds}s for @{username} — sleeping")
                await asyncio.sleep(e.seconds + 5)
            except Exception as exc:
                logger.error(f"Error collecting @{username}: {exc}")
            await asyncio.sleep(self.request_delay)

        logger.info(f"[Telegram] Collected {len(posts)} posts for '{group_id}'")
        return posts

    async def _async_collect_all(
        self,
        start_time: Optional[datetime],
        end_time: Optional[datetime],
    ) -> list[RawPost]:
        all_posts: list[RawPost] = []
        for group_id in self.targets_config["groups"]:
            all_posts.extend(
                await self._async_collect_group(group_id, start_time, end_time)
            )
        return all_posts

    async def _collect_channel(
        self,
        client: TelegramClient,
        username: str,
        group_id: str,
        start_time: Optional[datetime],
        end_time: Optional[datetime],
    ) -> list[RawPost]:
        posts: list[RawPost] = []
        kwargs = {"limit": self.max_messages}
        if end_time:
            kwargs["offset_date"] = end_time

        async for msg in client.iter_messages(username, **kwargs):
            if not isinstance(msg, Message):
                continue
            if not msg.text and not msg.caption:
                continue
            msg_time = msg.date
            if msg_time.tzinfo is None:
                msg_time = msg_time.replace(tzinfo=timezone.utc)
            if start_time and msg_time < start_time:
                break  # messages are newest-first; stop when older than window

            text = msg.text or msg.caption or ""
            if len(text.strip()) < 10:
                continue

            media_urls: list[str] = []
            if isinstance(msg.media, (MessageMediaPhoto, MessageMediaDocument)):
                media_urls = [f"tg://{username}/{msg.id}/media"]

            posts.append(
                RawPost(
                    post_id=f"tg_{username}_{msg.id}",
                    platform="telegram",
                    group_id=group_id,
                    source=username,
                    text=text,
                    timestamp=msg_time,
                    language="ar",
                    engagement={
                        "views": getattr(msg, "views", 0) or 0,
                        "forwards": getattr(msg, "forwards", 0) or 0,
                        "replies": getattr(msg.replies, "replies", 0) if msg.replies else 0,
                    },
                    media_urls=media_urls,
                    raw={"id": msg.id, "peer_id": str(msg.peer_id)},
                )
            )
        return posts
