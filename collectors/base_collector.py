"""Base collector interface and shared data models."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class RawPost:
    post_id: str
    platform: str          # "twitter" | "telegram"
    group_id: str          # e.g. "hezbollah"
    source: str            # account handle or channel name
    text: str
    timestamp: datetime
    language: str = "ar"
    engagement: dict = field(default_factory=dict)
    media_urls: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)


class BaseCollector:
    def __init__(self, config: dict, targets_config: dict):
        self.config = config
        self.targets_config = targets_config

    def collect_group(self, group_id: str, start_time=None, end_time=None) -> list[RawPost]:
        raise NotImplementedError

    def collect_all_groups(self, start_time=None, end_time=None) -> list[RawPost]:
        raise NotImplementedError
