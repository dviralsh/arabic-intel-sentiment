"""
Named entity and keyword extraction for Arabic text.
Tracks mentions of key figures, locations, operations, and events.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass

from loguru import logger


# ── Key entity dictionaries (Arabic + transliteration) ───────────────────────

ENTITIES = {
    "people": {
        "حسن نصر الله": "Hassan Nasrallah",
        "نصر الله": "Nasrallah",
        "خامنئي": "Khamenei",
        "علي خامنئي": "Ali Khamenei",
        "قاسم سليماني": "Qasem Soleimani",
        "إسماعيل قاآني": "Esmail Qaani",
        "عبد الملك الحوثي": "Abdul-Malik al-Houthi",
        "يحيى السنوار": "Yahya Sinwar",
        "محمد الضيف": "Mohammed Deif",
        "إبراهيم رئيسي": "Ebrahim Raisi",
        "مسعود بزشكيان": "Masoud Pezeshkian",
        "نعيم قاسم": "Naim Qassem",
        "هاشم صفي الدين": "Hashem Safieddine",
    },
    "locations": {
        "جنوب لبنان": "South Lebanon",
        "الضاحية": "Dahiya (Beirut)",
        "بيروت": "Beirut",
        "طهران": "Tehran",
        "صنعاء": "Sanaa",
        "الحديدة": "Hodeidah",
        "غزة": "Gaza",
        "رفح": "Rafah",
        "جنين": "Jenin",
        "الضفة الغربية": "West Bank",
        "البحر الأحمر": "Red Sea",
        "باب المندب": "Bab al-Mandab",
        "خليج عدن": "Gulf of Aden",
        "العراق": "Iraq",
        "سوريا": "Syria",
    },
    "organizations": {
        "كتائب القسام": "Al-Qassam Brigades",
        "حزب الله": "Hezbollah",
        "الحرس الثوري": "IRGC",
        "سرايا القدس": "Saraya al-Quds (PIJ)",
        "أنصار الله": "Ansar Allah (Houthis)",
        "الحشد الشعبي": "Popular Mobilization Forces",
        "فيلق القدس": "Quds Force",
        "حماس": "Hamas",
        "الجهاد الإسلامي": "Islamic Jihad",
        "اليونيفيل": "UNIFIL",
    },
    "operations": {
        "طوفان الأقصى": "Al-Aqsa Flood (Oct 7)",
        "السيف الحديدي": "Iron Sword",
        "الوعد الصادق": "True Promise",
        "وعد الآخرة": "Final Promise",
        "فجر الجليل": "Galilee Dawn",
        "نور الجليل": "Light of Galilee",
    },
    "concepts": {
        "محور المقاومة": "Axis of Resistance",
        "وحدة الساحات": "Unity of Arenas",
        "الوحدة": "Unity",
        "الصمود": "Steadfastness",
        "الاستشهاد": "Martyrdom",
        "المقاومة": "Resistance",
        "الجهاد": "Jihad",
        "الانتفاضة": "Intifada",
        "النصر": "Victory",
        "الهزيمة": "Defeat",
    },
}

# Flatten for fast lookup
_FLAT_ENTITIES: dict[str, tuple[str, str]] = {}
for category, items in ENTITIES.items():
    for ar, en in items.items():
        _FLAT_ENTITIES[ar] = (category, en)


@dataclass
class EntityMention:
    entity_ar: str
    entity_en: str
    category: str
    count: int
    contexts: list[str]  # surrounding text snippets


class EntityExtractor:
    """Extract and count entity mentions across posts."""

    def extract_from_texts(
        self, texts: list[str], group_id: str
    ) -> dict[str, list[EntityMention]]:
        """
        Returns {category: [EntityMention, ...]} sorted by frequency.
        """
        counts: dict[str, Counter] = defaultdict(Counter)
        contexts: dict[str, list[str]] = defaultdict(list)

        for text in texts:
            for ar_entity, (category, en_entity) in _FLAT_ENTITIES.items():
                if ar_entity in text:
                    counts[category][ar_entity] += 1
                    # extract snippet around entity
                    idx = text.find(ar_entity)
                    snippet = text[max(0, idx - 40): idx + len(ar_entity) + 40]
                    if len(contexts[ar_entity]) < 3:
                        contexts[ar_entity].append(snippet)

        result: dict[str, list[EntityMention]] = {}
        for category, counter in counts.items():
            mentions = []
            for ar_entity, count in counter.most_common():
                cat, en = _FLAT_ENTITIES[ar_entity]
                mentions.append(EntityMention(
                    entity_ar=ar_entity,
                    entity_en=en,
                    category=category,
                    count=count,
                    contexts=contexts.get(ar_entity, []),
                ))
            result[category] = mentions
        return result

    def to_serializable(
        self, entity_data: dict[str, list[EntityMention]]
    ) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {}
        for cat, mentions in entity_data.items():
            out[cat] = [
                {
                    "entity_ar": m.entity_ar,
                    "entity_en": m.entity_en,
                    "count": m.count,
                    "contexts": m.contexts,
                }
                for m in mentions
            ]
        return out
