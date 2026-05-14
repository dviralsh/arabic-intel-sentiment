"""
Arabic Intelligence Sentiment Analysis — Main Orchestrator
Big-data pipeline with incremental state management.

Modes:
  demo     — generate 10k+ synthetic posts per group, run full analysis
  collect  — collect from live APIs (Twitter + Telegram + RSS + Web)
  analyze  — run NLP on cached/collected posts
  report   — generate dashboard JSON from analyzed results
  full     — collect + analyze + report
  incremental — collect only new posts since last watermark, then report
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml
from dotenv import load_dotenv
from loguru import logger
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table

load_dotenv()
console = Console()

# ── CONFIG ────────────────────────────────────────────────────────────────────

def load_config() -> dict:
    with open("config/settings.yaml") as f:
        raw = f.read()
    for key, val in os.environ.items():
        raw = raw.replace(f"${{{key}}}", val)
    return yaml.safe_load(raw)


def load_targets() -> dict:
    with open("config/targets.yaml") as f:
        return yaml.safe_load(f)


# ── MASSIVE DEMO DATA (10k+ per group) ────────────────────────────────────────

def generate_demo_data(target_per_group: int = 10000) -> list:
    """
    Generate statistically representative synthetic posts.
    Each group has:
      - Multiple source types with realistic sentiment distributions
      - Temporal trends (sentiment shifts over 18 months)
      - Varying engagement distributions by source type
    """
    import random
    import math
    from collectors.base_collector import RawPost

    random.seed(42)
    now = datetime.now(timezone.utc)

    # ── Source type configurations ─────────────────────────────────────────
    # (source_type, weight, platform, sentiment_bias)
    # sentiment_bias: (positive_base, negative_base, noise)
    SOURCE_CONFIGS = {
        "official_telegram":   (0.18, "telegram", (0.40, 0.35, 0.15)),  # balanced official
        "affiliated_telegram": (0.15, "telegram", (0.45, 0.30, 0.15)),  # slightly positive
        "civilian_telegram":   (0.25, "telegram", (0.20, 0.60, 0.20)),  # most negative — real
        "official_media":      (0.10, "rss",      (0.50, 0.25, 0.10)),  # most positive (propaganda)
        "twitter_official":    (0.08, "twitter",  (0.42, 0.33, 0.15)),
        "twitter_affiliated":  (0.07, "twitter",  (0.35, 0.45, 0.20)),
        "rss_feed":            (0.10, "rss",      (0.45, 0.28, 0.12)),
        "web_official":        (0.07, "web",      (0.48, 0.27, 0.12)),
    }

    # ── Group-specific content banks ──────────────────────────────────────
    CONTENT = {
        "hezbollah": {
            "positive_official": [
                "المقاومة الإسلامية في لبنان تؤكد جاهزيتها القتالية الكاملة وقدرتها على الردع",
                "انتصار المقاومة في معركة جنوب لبنان يؤكد قوة وصمود المجاهدين في مواجهة العدو",
                "السيد حسن نصر الله: المقاومة أقوى اليوم من أي وقت مضى وسنحمي لبنان",
                "كتائب المقاومة تشن عمليات ناجحة ضد تمركزات العدو في الجليل الأعلى",
                "وحدة الساحات تتجلى في التنسيق بين المقاومة اللبنانية والفلسطينية والعراقية",
                "حزب الله يعلن استشهاد مقاتليه بشرف بعد معارك ضارية مع جيش الاحتلال",
                "المقاومة الإسلامية تطلق وابلاً من الصواريخ على المستوطنات الإسرائيلية شمالاً",
                "إنجاز نوعي للمقاومة: تدمير دبابة ميركافا بعملية كمين محكمة في جنوب لبنان",
                "حزب الله: صمودنا يلهم شعوب المنطقة ويثبت أن الاحتلال قابل للهزيمة",
                "الشعب في الضاحية الجنوبية يحيي ذكرى شهداء المقاومة بفخر واعتزاز",
                "مقاتلو المقاومة يرفعون رايات النصر في جنوب لبنان رغم الضغوط المتواصلة",
                "الأمين العام لحزب الله: العدو يتهيب الدخول البري لأنه يعرف ما ينتظره",
            ],
            "negative_civilian": [
                "أزمة اقتصادية حادة تضرب الضاحية الجنوبية وجنوب لبنان، المواطنون يشتكون",
                "انهيار الليرة اللبنانية وارتفاع الأسعار يُثقل كاهل العائلات في المناطق الجنوبية",
                "سكان الجنوب يطالبون بوقف الحرب والعودة إلى قراهم التي هجروها قسراً",
                "مخاوف شديدة من التصعيد العسكري والخسائر البشرية في صفوف المدنيين",
                "خسائر فادحة في البنية التحتية جراء الغارات الإسرائيلية على جنوب لبنان",
                "أهالي الضحايا ينتقدون صمت القيادة على الأوضاع الإنسانية الصعبة في الجنوب",
                "نزوح آلاف العائلات من القرى الجنوبية بسبب الاشتباكات المتواصلة",
                "اللبنانيون يتساءلون: حتى متى ستستمر هذه الحرب وما ثمنها على المدنيين؟",
                "أزمة المستشفيات في جنوب لبنان: نقص الأدوية والأطباء يهدد حياة المرضى",
                "شباب لبناني يغادر البلاد هرباً من الحرب والأزمة الاقتصادية الخانقة",
                "مواطنون في الضاحية: الحرب دمرت مشاريعنا ومستقبل أطفالنا",
                "الحصار الجوي يعرقل واردات السلع الأساسية ويرفع الأسعار بشكل جنوني",
                "انقطاع الكهرباء لساعات طويلة يفاقم المعاناة في المناطق الجنوبية",
                "مطالب شعبية بوقف إطلاق النار وإطلاق مفاوضات دبلوماسية عاجلة",
                "عائلات النازحين في مراكز الإيواء تصف ظروفاً إنسانية صعبة",
            ],
            "negative_operational": [
                "مقاتلو حزب الله يواجهون ضغطاً عسكرياً متصاعداً من الغارات الإسرائيلية",
                "تقارير عن خسائر كبيرة في قيادات المقاومة جراء استهداف إسرائيلي دقيق",
                "الغارات الإسرائيلية تستهدف منشآت حزب الله في بعلبك والبقاع الغربي",
                "تقارير عن تراجع قدرات المقاومة الصاروخية بعد ضربات متواصلة",
                "مصادر ميدانية: خسائر المقاومة في العناصر المدربة أكبر مما يُعلن",
                "اختراق أمني خطير يكشف عن شبكة تجسس إسرائيلية داخل صفوف الحزب",
                "استهداف قيادات حزب الله في غارة نوعية يثير تساؤلات عن الأمن الداخلي",
                "مخاوف من نضوب مخزون الأسلحة المتطورة في ظل استمرار المعارك",
            ],
            "neutral": [
                "حزب الله يعقد اجتماعاً لمجلس شوراه لبحث المستجدات الميدانية والسياسية",
                "لقاء بين قيادة حزب الله وممثلي فصائل المقاومة لتنسيق المواقف",
                "إيران تؤكد دعمها المستمر لحزب الله في مواجهة التحديات الراهنة",
                "مباحثات دبلوماسية بشأن وقف إطلاق النار تشمل لبنان وأطراف إقليمية",
                "حزب الله يصدر بياناً بشأن الأوضاع الميدانية في جنوب لبنان",
            ],
        },
        "irgc_iran": {
            "positive_official": [
                "الجمهورية الإسلامية الإيرانية تؤكد دعمها المطلق لمحور المقاومة في مواجهة الصهيونية",
                "الحرس الثوري يعلن نجاح عملية الوعد الصادق ضد الكيان الصهيوني بأسلحة دقيقة",
                "إيران تتحدى العقوبات وتواصل تطوير قدراتها الصاروخية والدفاعية المتقدمة",
                "خامنئي: الثورة الإسلامية باقية وستنتصر على الاستكبار العالمي بإذن الله",
                "المرشد الأعلى: وحدة الأمة الإسلامية هي مفتاح الانتصار على أعداء الإسلام",
                "فيلق القدس يواصل دعمه لقوى المقاومة في المنطقة بكل الإمكانات",
                "إيران تطلق منظومة دفاع جوي جديدة تُعزز أمنها الاستراتيجي",
                "البرنامج الصاروخي الإيراني يتطور رغم الضغوط الغربية ويثير رهبة العدو",
                "إيران والصين وروسيا تعمق شراكتها الاستراتيجية في مواجهة الهيمنة الأمريكية",
                "الباسيج يحتفل بذكرى الثورة الإسلامية بمشاركة جماهيرية واسعة",
            ],
            "negative_civilian": [
                "الاحتجاجات الشعبية تتجدد في طهران وعدة مدن إيرانية احتجاجاً على غلاء المعيشة",
                "العقوبات الأمريكية تخنق الاقتصاد الإيراني والبطالة ترتفع لمستويات قياسية",
                "الريال الإيراني يواصل انهياره أمام الدولار ويُلقي بأعباء ثقيلة على المواطنين",
                "شباب إيراني يطالب بإصلاحات جذرية وينتقد الإنفاق على الحروب الخارجية",
                "مواطنون إيرانيون: نعاني من الفقر بينما تُصرف أموالنا على دعم أطراف خارجية",
                "أزمة المياه والكهرباء تضرب مناطق إيرانية عديدة وسط موجة غضب شعبي متصاعدة",
                "الحكومة الإيرانية تواجه انتقادات حادة بسبب فشلها في معالجة الأزمة الاقتصادية",
                "مظاهرات ضد ارتفاع أسعار المواد الغذائية تعم المدن الإيرانية الكبرى والصغيرة",
                "إيرانيون ينتقدون النظام: أين ذهبت عائدات النفط؟ المواطن يعيش في فقر",
                "تصاعد حدة الاحتجاجات العمالية في المناطق الصناعية الإيرانية",
                "النساء الإيرانيات يواصلن الاحتجاج على قوانين الحجاب الإلزامي",
                "تقارير عن موجة هجرة إيرانية واسعة بسبب الأوضاع الاقتصادية والسياسية",
                "أولياء أمور: المدارس الإيرانية تعاني من نقص حاد في الكتب والمستلزمات",
                "أطباء إيرانيون يحذرون: نقص الأدوية يهدد حياة المرضى في المستشفيات",
                "إيرانيون في وسائل التواصل: الحكومة تكذب علينا والأوضاع أسوأ مما يُصرَّح",
            ],
            "negative_operational": [
                "الغارات الإسرائيلية تستهدف منشآت إيرانية في سوريا وتُلحق خسائر بشرية",
                "اغتيال قيادات إيرانية بارزة في الخارج يكشف عن ثغرات أمنية خطيرة",
                "العقوبات الأمريكية تُعيق الوصول الإيراني إلى النظام المالي الدولي",
                "ضربات إسرائيلية تستهدف المستشارين العسكريين الإيرانيين في لبنان وسوريا",
                "تراجع نفوذ إيران في سوريا بعد سقوط نظام الأسد وإعادة الحسابات",
            ],
            "neutral": [
                "المفاوضات النووية الإيرانية مستمرة دون التوصل إلى نتيجة حاسمة",
                "بزشكيان يلتقي مع مسؤولين أوروبيين لبحث ملف العقوبات والعلاقات الثنائية",
                "إيران تعلن عن دورة انتخابية جديدة وسط مشاركة شعبية محدودة",
                "طهران وموسكو تعمقان تعاونهما في مجالي الطاقة والاقتصاد",
                "المرشد الأعلى يلقي خطاباً سنوياً حول السياسة الداخلية والخارجية",
            ],
        },
        "houthis": {
            "positive_official": [
                "أنصار الله يعلن استمرار عمليات البحر الأحمر دعماً للشعب الفلسطيني في غزة",
                "الصواريخ الباليستية والطائرات المسيّرة اليمنية تضرب السفن المتجهة لإسرائيل",
                "يحيى السريع: القوات المسلحة اليمنية لن تتوقف حتى يُرفع الحصار عن غزة",
                "عبد الملك الحوثي يتحدى الضربات الأمريكية البريطانية: سنمضي قدماً",
                "نجاح عملية بحرية جديدة في خليج عدن تستهدف سفينة إسرائيلية بصاروخ دقيق",
                "أنصار الله: قدراتنا الصاروخية تتطور ولا يمكن لأحد إيقاف المقاومة اليمنية",
                "اليمن يثبت أن الأمة يمكنها الدفاع عن نفسها بإمكانات محلية في مواجهة الهجمات",
                "قوات أنصار الله تتقدم ميدانياً في عدة جبهات وتُلحق خسائر بالعدو",
                "عملية نوعية في باب المندب تُقطع الطريق أمام السفن المتجهة للموانئ الإسرائيلية",
            ],
            "negative_civilian": [
                "الوضع الإنساني في اليمن يصل إلى حافة الانهيار ومنظمات أممية تطرق الأجراس",
                "المجاعة تضرب محافظات يمنية عديدة والأطفال يموتون جوعاً أمام كاميرات العالم",
                "الغارات الأمريكية والبريطانية تودي بحياة مدنيين يمنيين أبرياء في صنعاء",
                "أزمة الوقود تشل الحياة في المدن اليمنية والمستشفيات على حافة التوقف",
                "يمنيون يتساءلون: لماذا نحن نموت جوعاً بينما قياداتنا تشن حرباً لغزة؟",
                "تدهور الخدمات الأساسية في المناطق الخاضعة لسيطرة الحوثيين بشكل حاد",
                "النازحون اليمنيون يعيشون في مخيمات مكتظة وظروف إنسانية كارثية",
                "ارتفاع أسعار المواد الغذائية يتجاوز قدرة المواطنين على الشراء في صنعاء",
                "مستشفيات تعز تناشد: نحتاج أدوية وأطباء عاجلاً أو سيموت المرضى",
                "عمال اليمن يشكون: لم يصلنا راتب منذ أشهر والأسرة تعاني",
                "منظمة أممية: 80% من اليمنيين يحتاجون مساعدات إنسانية عاجلة",
                "أهالي الحديدة يعانون من نقص الماء النظيف وانتشار الأمراض",
                "شهادات نازحين: لقد فقدنا كل شيء ولا نعرف متى نعود لبيوتنا",
            ],
            "neutral": [
                "محادثات سلام اليمن تتواصل دون التوصل إلى اتفاق شامل بين الأطراف",
                "السعودية والحوثيون يجرون مباحثات غير مباشرة بوساطة عُمانية",
                "مجلس الأمن يعقد جلسة طارئة بشأن الهجمات الحوثية في البحر الأحمر",
                "الأمم المتحدة تطالب بهدنة إنسانية في اليمن لتخفيف المعاناة",
            ],
        },
        "hamas_pij": {
            "positive_official": [
                "كتائب عز الدين القسام تعلن عن عملية نوعية ضد قوات الاحتلال في غزة",
                "المقاومة الفلسطينية تواصل تصديها للاجتياح الإسرائيلي رغم الضغط العسكري",
                "حماس: لن نتنازل عن حقوق شعبنا وخيار المقاومة استراتيجي وثابت",
                "سرايا القدس تنفذ عملية كمين وتوقع خسائر في صفوف جنود الاحتلال",
                "صمود شعب غزة أمام الإبادة الجماعية يُلهم شعوب الأرض وضمير العالم",
                "القسام تطلق صواريخ على تل أبيب والمناطق الإسرائيلية رداً على مجازر المدنيين",
                "حماس تؤكد: وحدة فصائل المقاومة الفلسطينية هي سر صمودها في مواجهة الاحتلال",
                "مقاتلو القسام يخوضون معارك الأنفاق ويُكبدون قوات الاحتلال خسائر فادحة",
            ],
            "negative_civilian": [
                "مجزرة جديدة في غزة، عشرات الشهداء من الأطفال والنساء في قصف وحشي على المخيمات",
                "المستشفيات في غزة تنهار تحت وطأة القصف الإسرائيلي المتواصل والحصار الخانق",
                "أهالي غزة يصرخون: أين المساعدات والغذاء والدواء؟ نموت جوعاً تحت القصف",
                "الإبادة الجماعية في غزة مستمرة والمجتمع الدولي يكتفي بالإدانات الكلامية",
                "مخيم جباليا يتعرض لقصف وحشي يوقع مئات الشهداء والجرحى من المدنيين",
                "أزمة إنسانية غير مسبوقة في قطاع غزة، الأطفال يموتون جوعاً وعطشاً",
                "رفح تحت النار: العمليات الإسرائيلية تُهجّر الفلسطينيين من آخر ملاجئهم",
                "شهادات ناجين من مجازر غزة: لا كلمات تصف ما رأيناه من أهوال",
                "منظمات حقوق الإنسان: ما يجري في غزة جريمة حرب موثقة أمام التاريخ",
                "أطباء بلا حدود: المستشفيات في غزة تعمل بإمكانات مقطوعة ومحدودة جداً",
                "الدمار يطال كل مناطق غزة ولا مكان آمن للمدنيين، الكل في مرمى القصف",
                "فلسطينيون يناشدون العالم: أوقفوا هذه الإبادة قبل أن يُمحى شعبنا من الوجود",
                "إحصائيات مفجعة: أكثر من نصف شهداء غزة من الأطفال والنساء والمدنيين",
                "عمال الإغاثة يرفضون الاستمرار: لا يمكننا العمل والمنطقة بأكملها تُقصف",
                "شباب غزة: لم يبقَ لنا شيء، بيوتنا ومدارسنا وعائلاتنا ذهبت في القصف",
                "غزة تفقد كل يوم عشرات الأطباء والمهندسين والمعلمين في مجازر الاحتلال",
            ],
            "negative_political": [
                "انتقادات داخلية لأداء حماس السياسي وإدارة الأزمة الإنسانية في غزة",
                "خلافات حماس والسلطة الفلسطينية تُعمق الانقسام وتُضعف موقف الشعب",
                "فلسطينيون ينتقدون قرار حماس بشأن اتفاقية الهدنة ويطالبون بالإفراج عن المحتجزين",
                "أصوات فلسطينية معارضة: المقاومة بحاجة لاستراتيجية سياسية واضحة",
            ],
            "neutral": [
                "محادثات القاهرة بشأن صفقة تبادل المحتجزين تشهد تقدماً بطيئاً وعقبات",
                "حركة حماس تعلن عن موقفها من مقترح وقف إطلاق النار الأمريكي الأخير",
                "مصر وقطر تواصلان دور الوساطة بين حماس وإسرائيل بوساطة أمريكية",
                "اجتماع قيادات الفصائل الفلسطينية في القاهرة لبحث المستجدات الميدانية",
            ],
        },
    }

    # Engagement distributions by source type
    ENGAGEMENT_RANGES = {
        "official_telegram":   {"views": (5000, 200000), "forwards": (100, 8000)},
        "affiliated_telegram": {"views": (1000, 80000),  "forwards": (50, 4000)},
        "civilian_telegram":   {"views": (500, 50000),   "forwards": (20, 2000)},
        "official_media":      {"views": (0, 0),          "likes": (10, 500)},
        "twitter_official":    {"likes": (100, 20000),   "retweets": (50, 8000)},
        "twitter_affiliated":  {"likes": (50, 5000),     "retweets": (20, 2000)},
        "rss_feed":            {"views": (0, 0)},
        "web_official":        {"views": (0, 0)},
    }

    posts = []
    random_state = random.Random(42)

    for group_id, content in CONTENT.items():
        per_source_target = target_per_group // len(SOURCE_CONFIGS)

        for source_type, (weight, platform, (pos_base, neg_base, noise)) in SOURCE_CONFIGS.items():
            n_posts = int(target_per_group * weight)

            for i in range(n_posts):
                # Temporal: 18-month window (540 days)
                days_ago = random_state.randint(0, 540)
                ts = now - timedelta(days=days_ago)

                # Temporal trend: sentiment deteriorates over time (more negative recently)
                time_factor = days_ago / 540  # 1.0 = oldest, 0.0 = newest
                # More negative content in recent months
                neg_adj = neg_base + (1 - time_factor) * 0.15
                pos_adj = max(pos_base - (1 - time_factor) * 0.12, 0.05)
                neu_adj = max(1.0 - pos_adj - neg_adj, 0.05)

                # Normalise
                total = pos_adj + neg_adj + neu_adj
                pos_adj /= total
                neg_adj /= total

                roll = random_state.random()
                if roll < pos_adj:
                    # Pick from positive or official_positive pool
                    pool = (
                        content.get("positive_official", [])
                        if source_type in ("official_media", "official_telegram", "rss_feed", "web_official")
                        else content.get("positive_official", [])
                    )
                    sentiment_tag = "pos"
                elif roll < pos_adj + neg_adj:
                    if source_type in ("civilian_telegram", "twitter_affiliated"):
                        pool = content.get("negative_civilian", []) or content.get("negative_operational", [])
                    else:
                        pool = (
                            content.get("negative_civilian", []) if random_state.random() < 0.4
                            else content.get("negative_operational", content.get("negative_civilian", []))
                        )
                    sentiment_tag = "neg"
                else:
                    pool = content.get("neutral", [])
                    sentiment_tag = "neu"

                if not pool:
                    pool = content.get("positive_official", ["محتوى متعدد المصادر"])

                # Add slight variations to avoid exact duplicates
                text = random_state.choice(pool)
                suffixes = [
                    " #المقاومة", " - تقرير خاص", " | مصادر ميدانية", "",
                    " (تحديث)", " - متابعة", " #عاجل", "",
                ]
                text = text + random_state.choice(suffixes)

                # Engagement
                eng_range = ENGAGEMENT_RANGES.get(source_type, {})
                engagement = {}
                for metric, (lo, hi) in eng_range.items():
                    if lo == hi == 0:
                        engagement[metric] = 0
                    else:
                        # Log-normal distribution for realistic engagement
                        mean_log = math.log(max((lo + hi) / 4, 1))
                        val = int(math.exp(random_state.gauss(mean_log, 1.0)))
                        engagement[metric] = max(lo, min(hi, val))

                source_names = {
                    "official_telegram":   f"official_{group_id}_tg_{random_state.randint(1,7)}",
                    "affiliated_telegram": f"affiliated_{group_id}_tg_{random_state.randint(1,12)}",
                    "civilian_telegram":   f"civilian_{group_id}_tg_{random_state.randint(1,12)}",
                    "official_media":      f"media_{group_id}_{random_state.randint(1,6)}",
                    "twitter_official":    f"@{group_id}_official_{random_state.randint(1,4)}",
                    "twitter_affiliated":  f"@{group_id}_affiliated_{random_state.randint(1,6)}",
                    "rss_feed":            f"rss_{group_id}_{random_state.randint(1,4)}",
                    "web_official":        f"web_{group_id}_{random_state.randint(1,3)}",
                }

                posts.append(RawPost(
                    post_id=f"demo_{group_id}_{source_type}_{i}_{days_ago}",
                    platform=platform,
                    group_id=group_id,
                    source=source_names[source_type],
                    text=text,
                    timestamp=ts,
                    language="ar",
                    engagement=engagement,
                    raw={"source_type": source_type, "sentiment_hint": sentiment_tag},
                ))

    # Summary
    from collections import Counter
    group_counts = Counter(p.group_id for p in posts)
    for gid, count in sorted(group_counts.items()):
        logger.info(f"Demo data: {gid} → {count:,} posts")
    logger.info(f"Demo data total: {len(posts):,} posts")
    return posts


# ── PIPELINE ──────────────────────────────────────────────────────────────────

def run_pipeline(mode: str, use_demo: bool = False, incremental: bool = False):
    console.print(Panel.fit(
        f"[bold cyan]Arabic Intelligence Sentiment Analysis[/]\n"
        f"Mode: [yellow]{mode}[/] | Demo: [yellow]{use_demo}[/] | Incremental: [yellow]{incremental}[/]",
        border_style="cyan",
    ))

    config = load_config()
    targets = load_targets()
    analysis_cfg = targets.get("analysis", {})

    now = datetime.now(timezone.utc)
    baseline_start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    baseline_end   = datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
    current_start  = datetime(2025, 1, 1, tzinfo=timezone.utc)
    current_end    = now

    from collectors.state_manager import StateManager
    from processors.arabic_preprocessor import ArabicPreprocessor
    from analyzers.sentiment_engine import SentimentEngine
    from analyzers.comparative_engine import ComparativeEngine
    from analyzers.topic_modeler import TopicModeler
    from analyzers.source_comparator import SourceComparator
    from analyzers.intelligence_generator import IntelligenceGenerator

    state_mgr     = StateManager()
    preprocessor  = ArabicPreprocessor(config)
    sent_engine   = SentimentEngine(config, analysis_cfg.get("themes", []))
    comp_engine   = ComparativeEngine(targets)
    topic_modeler = TopicModeler(min_topic_size=10)
    source_comp   = SourceComparator(targets)
    intel_gen     = IntelligenceGenerator(
        targets,
        config["output"]["dashboard_output_dir"] + "/data",
    )

    raw_posts = []

    # ── COLLECT ───────────────────────────────────────────────────────────────
    if mode in ("collect", "full", "incremental"):
        if use_demo:
            raw_posts = generate_demo_data(
                target_per_group=analysis_cfg.get("target_samples_per_group", 10000)
            )
        else:
            from collectors import TwitterCollector, TelegramCollector, RSSCollector, WebScraper

            collectors_map = {
                "Twitter":  TwitterCollector(config, targets),
                "Telegram": TelegramCollector(config, targets),
                "RSS":      RSSCollector(config, targets),
                "Web":      WebScraper(config, targets),
            }

            for name, collector in collectors_map.items():
                console.print(f"[cyan]Collecting via {name}...[/]")
                for group_id in targets["groups"]:
                    # Incremental: start from watermark
                    watermark = None
                    if incremental:
                        watermark = state_mgr.get_watermark(f"{name.lower()}_{group_id}")
                    try:
                        new_posts = collector.collect_group(
                            group_id,
                            start_time=watermark or baseline_start,
                            end_time=current_end,
                        )
                        state_mgr.update_watermark(f"{name.lower()}_{group_id}", new_posts)
                        raw_posts.extend(new_posts)
                    except Exception as exc:
                        logger.error(f"{name}/{group_id}: {exc}")

            # Also load existing cached posts for full context
            if incremental:
                cached = state_mgr.load_cached_posts(
                    start_time=baseline_start, end_time=current_end
                )
                cached_raw = [state_mgr.dict_to_raw_post(d) for d in cached]
                # Deduplicate by post_id
                existing_ids = {p.post_id for p in raw_posts}
                raw_posts.extend(p for p in cached_raw if p.post_id not in existing_ids)

        # Save to state cache
        if not use_demo:
            state_mgr.save_posts(raw_posts)
            state_mgr.save_state()

        _persist_raw(raw_posts)
        console.print(f"[green]✓[/] Collected [bold]{len(raw_posts):,}[/] raw posts")

    elif mode in ("analyze", "report"):
        raw_posts = _load_raw_or_demo(use_demo, state_mgr, baseline_start, current_end, analysis_cfg)

    # ── ANALYZE ───────────────────────────────────────────────────────────────
    sentiment_results = []
    if mode in ("analyze", "full", "demo", "incremental"):
        if not raw_posts:
            raw_posts = _load_raw_or_demo(use_demo, state_mgr, baseline_start, current_end, analysis_cfg)

        console.print(f"\n[cyan]Preprocessing {len(raw_posts):,} posts...[/]")
        processed = preprocessor.process_batch(raw_posts)
        console.print(f"[green]✓[/] {len(processed):,} posts passed preprocessing")

        console.print(f"\n[cyan]Running sentiment analysis (batch size {analysis_cfg.get('batch_size', 64)})...[/]")
        with Progress(
            SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
            BarColumn(), TaskProgressColumn(), console=console,
        ) as progress:
            task = progress.add_task("Sentiment analysis", total=len(processed))
            batch_size = analysis_cfg.get("batch_size", 64)
            for i in range(0, len(processed), batch_size):
                batch = processed[i:i + batch_size]
                batch_results = sent_engine.analyze_batch(batch)
                sentiment_results.extend(batch_results)
                progress.advance(task, len(batch))

        console.print(f"[green]✓[/] Sentiment: {len(sentiment_results):,} posts analyzed")
        _persist_sentiment(sentiment_results)

    # ── REPORT ────────────────────────────────────────────────────────────────
    if mode in ("report", "full", "demo", "incremental"):
        if not sentiment_results:
            sentiment_results = _load_sentiment(targets)

        console.print(f"\n[cyan]Running comparative analysis...[/]")
        assessments = comp_engine.compare(
            sentiment_results,
            baseline_start, baseline_end,
            current_start, current_end,
        )
        console.print(f"[green]✓[/] {len(assessments)} intelligence assessments")

        console.print(f"\n[cyan]Running source-type analysis...[/]")
        source_results = source_comp.analyze(sentiment_results)
        source_data = source_comp.to_serializable(source_results)
        console.print(f"[green]✓[/] Source-type profiles for {len(source_results)} groups")

        console.print(f"\n[cyan]Running topic modeling...[/]")
        import pandas as pd
        df_all = pd.DataFrame([{
            "group_id": r.group_id,
            "text": r.text,
            "sentiment": r.sentiment,
            "timestamp": r.timestamp,
        } for r in sentiment_results])
        topics_by_group: dict = {}
        for group_id in targets["groups"]:
            g = df_all[df_all["group_id"] == group_id]
            if len(g) >= 20:
                topics_by_group[group_id] = topic_modeler.fit_group(
                    group_id,
                    g["text"].tolist(),
                    g["sentiment"].tolist(),
                    g["timestamp"].tolist(),
                )
        console.print(f"[green]✓[/] Topics modeled for {len(topics_by_group)} groups")

        console.print(f"\n[cyan]Generating intelligence report...[/]")
        report = intel_gen.generate(
            sentiment_results, assessments, topics_by_group,
            baseline_start, baseline_end, current_start, current_end,
            source_data=source_data,
            collection_stats=state_mgr.get_collection_stats(),
        )
        console.print(f"[green]✓[/] Report → dashboard/data/intelligence_report.json")

        if not use_demo and mode == "incremental":
            state_mgr.commit_to_github()

        _print_summary(console, report)

    console.print(Panel.fit("[bold green]Pipeline complete![/]", border_style="green"))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _persist_raw(posts: list):
    path = Path("data/raw/raw_posts.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            [{
                "post_id": p.post_id, "platform": p.platform,
                "group_id": p.group_id, "source": p.source,
                "text": p.text,
                "timestamp": p.timestamp.isoformat() if hasattr(p.timestamp, "isoformat") else str(p.timestamp),
                "language": p.language, "engagement": p.engagement,
                "source_type": p.raw.get("source_type", "unknown"),
            } for p in posts],
            f, ensure_ascii=False, separators=(",", ":"),
        )


def _persist_sentiment(results: list):
    path = Path("data/processed/sentiment_results.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            [{
                "post_id": r.post_id, "platform": r.platform,
                "group_id": r.group_id, "source": r.source,
                "text": r.text, "original_text": r.original_text,
                "timestamp": r.timestamp.isoformat() if hasattr(r.timestamp, "isoformat") else str(r.timestamp),
                "sentiment": r.sentiment, "confidence": r.confidence,
                "positive_score": r.positive_score,
                "negative_score": r.negative_score,
                "neutral_score": r.neutral_score,
                "engagement_weight": r.engagement_weight,
                "weighted_sentiment": r.weighted_sentiment,
                "themes": r.themes, "method": r.method,
            } for r in results],
            f, ensure_ascii=False, separators=(",", ":"),
        )


def _load_raw_or_demo(use_demo, state_mgr, baseline_start, current_end, analysis_cfg):
    raw_path = Path("data/raw/raw_posts.json")
    if raw_path.exists():
        from collectors.base_collector import RawPost
        with open(raw_path, encoding="utf-8") as f:
            data = json.load(f)
        posts = []
        for d in data:
            ts_raw = d.get("timestamp", "")
            try:
                ts = datetime.fromisoformat(ts_raw)
            except ValueError:
                ts = datetime.now(timezone.utc)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            posts.append(RawPost(
                post_id=d["post_id"], platform=d["platform"],
                group_id=d["group_id"], source=d["source"],
                text=d["text"], timestamp=ts,
                language=d.get("language", "ar"),
                engagement=d.get("engagement", {}),
                raw={"source_type": d.get("source_type", "unknown")},
            ))
        return posts

    # Fall back to cache or demo
    cached = state_mgr.load_cached_posts(start_time=baseline_start, end_time=current_end)
    if cached:
        return [state_mgr.dict_to_raw_post(d) for d in cached]

    if use_demo:
        return generate_demo_data(analysis_cfg.get("target_samples_per_group", 10000))
    return []


def _load_sentiment(targets: dict) -> list:
    from analyzers.sentiment_engine import SentimentResult
    path = Path("data/processed/sentiment_results.json")
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    results = []
    for d in data:
        ts_raw = d.get("timestamp", "")
        try:
            ts = datetime.fromisoformat(ts_raw)
        except ValueError:
            ts = datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        results.append(SentimentResult(
            post_id=d["post_id"], platform=d["platform"],
            group_id=d["group_id"], source=d["source"],
            text=d["text"], original_text=d.get("original_text", d["text"]),
            timestamp=ts,
            sentiment=d["sentiment"], confidence=d["confidence"],
            positive_score=d.get("positive_score", 0),
            negative_score=d.get("negative_score", 0),
            neutral_score=d.get("neutral_score", 0),
            engagement_weight=d.get("engagement_weight", 1.0),
            weighted_sentiment=d.get("weighted_sentiment", 0),
            themes=d.get("themes", []),
            method=d.get("method", "model"),
        ))
    return results


def _print_summary(console, report: dict):
    table = Table(title="Intelligence Summary", border_style="cyan")
    table.add_column("Group"); table.add_column("Posts", justify="right")
    table.add_column("Score", justify="right"); table.add_column("Neg %", justify="right")
    table.add_column("Divergence", justify="right")
    for gid, g in report["summary"].get("groups", {}).items():
        score = g["avg_sentiment_score"]
        color = "green" if score > 0.05 else "red" if score < -0.05 else "yellow"
        src_data = report.get("source_analysis", {}).get(gid, {})
        div_score = src_data.get("narrative_divergence_score", 0)
        div_color = "red" if div_score > 0.3 else "yellow" if div_score > 0.15 else "green"
        table.add_row(
            g["display_name"],
            f"{g['post_count']:,}",
            f"[{color}]{score:+.3f}[/]",
            f"{g['negative_pct']}%",
            f"[{div_color}]{div_score:.2f}[/]",
        )
    console.print(table)
    console.print("\n[bold]Critical Divergence Alerts:[/]")
    for gid, src in report.get("source_analysis", {}).items():
        for alert in src.get("divergence_alerts", []):
            if alert["severity"] in ("critical", "high"):
                console.print(f"  ⚠  [red bold]{alert['severity'].upper()}[/] — {alert['interpretation'][:150]}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Arabic Intel Sentiment Analysis")
    parser.add_argument(
        "--mode",
        choices=["collect", "analyze", "report", "full", "demo", "incremental"],
        default="demo",
    )
    parser.add_argument("--demo", action="store_true")
    args = parser.parse_args()
    use_demo = args.demo or args.mode == "demo"
    incremental = args.mode == "incremental"
    effective_mode = "full" if args.mode in ("demo", "incremental") else args.mode
    run_pipeline(effective_mode, use_demo=use_demo, incremental=incremental)
