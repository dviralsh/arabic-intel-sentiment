"""
Arabic Intelligence Sentiment Analysis — Main Orchestrator
Usage:
    python main.py --mode collect          # collect raw posts
    python main.py --mode analyze          # analyze collected posts
    python main.py --mode report           # generate dashboard JSON
    python main.py --mode demo             # run full pipeline on demo data
    python main.py --mode full             # collect + analyze + report
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml
from dotenv import load_dotenv
from loguru import logger
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

load_dotenv()
console = Console()


def load_config():
    with open("config/settings.yaml") as f:
        raw = f.read()
    # expand env vars
    for key, val in os.environ.items():
        raw = raw.replace(f"${{{key}}}", val)
    return yaml.safe_load(raw)


def load_targets():
    with open("config/targets.yaml") as f:
        return yaml.safe_load(f)


# ── DEMO DATA GENERATOR ───────────────────────────────────────────────────────

def generate_demo_data() -> list:
    """Generate synthetic demo posts for demonstration without live API keys."""
    import random
    from collectors.base_collector import RawPost

    random.seed(42)

    demo_posts_by_group = {
        "hezbollah": {
            "positive": [
                "انتصار المقاومة الإسلامية في معركة جنوب لبنان يؤكد قوة وصمود المجاهدين",
                "حزب الله يعلن عن عملية ناجحة ضد العدو الصهيوني في الجليل",
                "شهداء المقاومة يرفعون رايتنا عالياً، النصر آتٍ لا محالة",
                "تضامن الشعب مع حزب الله لا حدود له، المقاومة تكبر يوماً بعد يوم",
                "السيد حسن نصر الله يؤكد: المقاومة أقوى من أي وقت مضى",
            ],
            "negative": [
                "أزمة اقتصادية حادة تضرب الضاحية الجنوبية، المواطنون يعانون من الغلاء",
                "خسائر فادحة في صفوف المقاومة، الشهداء بالعشرات",
                "انهيار الليرة اللبنانية يزيد من معاناة العائلات في جنوب لبنان",
                "الحصار الإسرائيلي يخنق المناطق الجنوبية وسط صمت دولي مريب",
                "مخاوف شديدة من التصعيد بعد الضربات الأخيرة على الضاحية",
                "أهالي الضحايا ينتقدون القيادة، أين الدعم لعائلات الشهداء؟",
                "الوضع الإنساني في جنوب لبنان كارثي والمساعدات تتأخر",
            ],
        },
        "irgc_iran": {
            "positive": [
                "الجمهورية الإسلامية تؤكد دعمها لمحور المقاومة في مواجهة الاستكبار العالمي",
                "الحرس الثوري يعلن نجاح عملية الوعد الصادق ضد الكيان الصهيوني",
                "إيران تتحدى العقوبات وتواصل تطوير قدراتها الصاروخية والدفاعية",
                "خامنئي: الثورة الإسلامية باقية وستنتصر على أعدائها",
            ],
            "negative": [
                "الاحتجاجات تتواصل في طهران وعدة مدن إيرانية احتجاجاً على غلاء المعيشة",
                "العقوبات الأمريكية تخنق الاقتصاد الإيراني، البطالة ترتفع لمستويات قياسية",
                "الريال الإيراني يواصل انهياره أمام الدولار، الأسعار تضاعفت",
                "شباب إيراني يطالب بإصلاحات جذرية وينتقد الإنفاق العسكري",
                "مواطنون إيرانيون: نعاني من الفقر بينما تُصرف أموالنا على حروب خارجية",
                "أزمة المياه والكهرباء تضرب عدة مناطق إيرانية وسط موجة غضب شعبي",
                "إيرانيون ينتقدون الحكومة بسبب فساد ومحسوبية في توزيع المساعدات",
                "الاحتجاجات تجدد ذاتها في إيران، الأمن يواجه المتظاهرين بعنف",
            ],
        },
        "houthis": {
            "positive": [
                "أنصار الله يؤكد استمرار العمليات في البحر الأحمر دعماً لغزة",
                "صواريخ المقاومة اليمنية تصل إلى قلب العدو، نصر جديد للمقاومة",
                "الشعب اليمني يتوحد خلف قيادة أنصار الله في مواجهة الاستكبار",
                "اليمن يثبت أنه قادر على الصمود رغم الحصار المفروض منذ سنوات",
            ],
            "negative": [
                "الوضع الإنساني في اليمن يصل إلى حافة الانهيار، ملايين يعانون من المجاعة",
                "الغارات الأمريكية البريطانية تودي بحياة مدنيين يمنيين أبرياء",
                "أزمة الوقود تشل الحياة في صنعاء، المستشفيات على وشك التوقف",
                "يمنيون ينتقدون قرار الحرب البحرية في ظل معاناة المواطنين",
                "المجاعة تضرب محافظات يمنية عديدة وسط استمرار الصراع",
                "تدهور الخدمات الأساسية في المناطق الخاضعة لسيطرة الحوثيين",
            ],
        },
        "hamas_pij": {
            "positive": [
                "المقاومة الفلسطينية تواصل عملياتها رغم الحصار الوحشي على غزة",
                "كتائب عز الدين القسام تعلن عن عمليات ناجحة ضد جيش الاحتلال",
                "صمود شعب غزة أمام الإبادة الجماعية يُلهم العالم بأسره",
                "حماس: لن نتنازل عن حقوق شعبنا، المقاومة خيارنا الاستراتيجي",
            ],
            "negative": [
                "مجزرة جديدة في غزة، عشرات الشهداء من الأطفال والنساء",
                "المستشفيات في غزة تنهار تحت وطأة القصف الإسرائيلي المتواصل",
                "أهالي غزة يصرخون: أين المساعدات والغذاء والدواء؟",
                "الإبادة الجماعية مستمرة والمجتمع الدولي يكتفي بالمتابعة",
                "أزمة إنسانية غير مسبوقة في قطاع غزة، السكان يموتون جوعاً",
                "الدمار يطال كل مناطق غزة، المدنيون لا يجدون مكاناً آمناً",
                "فلسطينيون ينادون: الحرب دمرت كل شيء، متى يعود السلام؟",
            ],
        },
    }

    posts: list[RawPost] = []
    now = datetime.now(timezone.utc)

    for group_id, content in demo_posts_by_group.items():
        platforms = ["twitter", "telegram"]

        # Current period (2025-2026) — weighted toward negative for most groups
        for _ in range(200):
            sentiment_type = random.choices(
                ["positive", "negative"],
                weights=[30, 70],
                k=1
            )[0]
            text = random.choice(content[sentiment_type])
            days_ago = random.randint(0, 500)  # last ~16 months
            ts = now - timedelta(days=days_ago)
            platform = random.choice(platforms)
            views = random.randint(100, 50000)
            posts.append(RawPost(
                post_id=f"demo_{group_id}_{len(posts)}",
                platform=platform,
                group_id=group_id,
                source=f"demo_{group_id}_channel" if platform == "telegram" else f"@demo_{group_id}",
                text=text,
                timestamp=ts,
                language="ar",
                engagement={
                    "likes": random.randint(10, 5000),
                    "retweets": random.randint(5, 2000),
                    "views": views,
                    "forwards": random.randint(0, 1000),
                    "replies": random.randint(0, 500),
                },
            ))

        # Baseline period (2024) — more positive (simulate deterioration)
        for _ in range(150):
            sentiment_type = random.choices(
                ["positive", "negative"],
                weights=[55, 45],
                k=1
            )[0]
            text = random.choice(content[sentiment_type])
            days_ago = random.randint(500, 870)  # 2024
            ts = now - timedelta(days=days_ago)
            platform = random.choice(platforms)
            posts.append(RawPost(
                post_id=f"demo_baseline_{group_id}_{len(posts)}",
                platform=platform,
                group_id=group_id,
                source=f"demo_{group_id}_channel",
                text=text,
                timestamp=ts,
                language="ar",
                engagement={
                    "likes": random.randint(50, 8000),
                    "retweets": random.randint(10, 3000),
                    "views": random.randint(500, 100000),
                    "forwards": random.randint(5, 2000),
                    "replies": random.randint(10, 1000),
                },
            ))

    logger.info(f"Generated {len(posts)} demo posts")
    return posts


# ── PIPELINE ──────────────────────────────────────────────────────────────────

def run_pipeline(mode: str, use_demo: bool = False):
    console.print(Panel.fit(
        f"[bold cyan]Arabic Intelligence Sentiment Analysis[/]\n"
        f"Mode: [yellow]{mode}[/] | Demo: [yellow]{use_demo}[/]",
        border_style="cyan"
    ))

    config = load_config()
    targets = load_targets()
    analysis_cfg = targets.get("analysis", {})

    now = datetime.now(timezone.utc)
    baseline_start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    baseline_end = datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
    current_start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    current_end = now

    from processors.arabic_preprocessor import ArabicPreprocessor
    from analyzers.sentiment_engine import SentimentEngine
    from analyzers.comparative_engine import ComparativeEngine
    from analyzers.topic_modeler import TopicModeler
    from analyzers.intelligence_generator import IntelligenceGenerator

    preprocessor = ArabicPreprocessor(config)
    sentiment_engine = SentimentEngine(config, analysis_cfg.get("themes", []))
    comparative_engine = ComparativeEngine(targets)
    topic_modeler = TopicModeler(min_topic_size=10)
    intel_gen = IntelligenceGenerator(targets, config["output"]["dashboard_output_dir"] + "/data")

    # ── COLLECT ───────────────────────────────────────────────────────────────
    raw_posts = []
    if mode in ("collect", "full"):
        if use_demo:
            raw_posts = generate_demo_data()
        else:
            from collectors import TwitterCollector, TelegramCollector
            twitter = TwitterCollector(config, targets)
            telegram = TelegramCollector(config, targets)
            raw_posts.extend(twitter.collect_all_groups(
                start_time=baseline_start,
                end_time=current_end,
            ))
            raw_posts.extend(telegram.collect_all_groups(
                start_time=baseline_start,
                end_time=current_end,
            ))

        # Persist raw
        raw_path = Path("data/raw/raw_posts.json")
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        with open(raw_path, "w", encoding="utf-8") as f:
            json.dump(
                [{
                    "post_id": p.post_id, "platform": p.platform,
                    "group_id": p.group_id, "source": p.source,
                    "text": p.text, "timestamp": p.timestamp.isoformat(),
                    "language": p.language, "engagement": p.engagement,
                } for p in raw_posts],
                f, ensure_ascii=False, indent=2,
            )
        console.print(f"[green]✓[/] Collected {len(raw_posts)} raw posts → {raw_path}")

    elif mode in ("analyze", "report"):
        # Load persisted raw
        raw_path = Path("data/raw/raw_posts.json")
        if raw_path.exists():
            from collectors.base_collector import RawPost
            from datetime import datetime
            with open(raw_path) as f:
                data = json.load(f)
            raw_posts = [
                RawPost(
                    post_id=d["post_id"], platform=d["platform"],
                    group_id=d["group_id"], source=d["source"],
                    text=d["text"],
                    timestamp=datetime.fromisoformat(d["timestamp"]),
                    language=d.get("language", "ar"),
                    engagement=d.get("engagement", {}),
                )
                for d in data
            ]
        elif use_demo:
            raw_posts = generate_demo_data()

    # ── ANALYZE ───────────────────────────────────────────────────────────────
    sentiment_results = []
    if mode in ("analyze", "full", "demo"):
        if use_demo and not raw_posts:
            raw_posts = generate_demo_data()

        console.print(f"\n[cyan]Preprocessing {len(raw_posts)} posts...[/]")
        processed = preprocessor.process_batch(raw_posts)
        console.print(f"[green]✓[/] {len(processed)} posts passed preprocessing")

        console.print(f"\n[cyan]Running sentiment analysis...[/]")
        sentiment_results = sentiment_engine.analyze_batch(processed)
        console.print(f"[green]✓[/] Sentiment analyzed: {len(sentiment_results)} posts")

        # Persist
        sent_path = Path("data/processed/sentiment_results.json")
        sent_path.parent.mkdir(parents=True, exist_ok=True)
        with open(sent_path, "w", encoding="utf-8") as f:
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
                    "engagement": {},  # already in weights
                } for r in sentiment_results],
                f, ensure_ascii=False, indent=2,
            )
        console.print(f"[green]✓[/] Saved sentiment results → {sent_path}")

    # ── REPORT ────────────────────────────────────────────────────────────────
    if mode in ("report", "full", "demo"):
        if not sentiment_results:
            sent_path = Path("data/processed/sentiment_results.json")
            if sent_path.exists():
                from analyzers.sentiment_engine import SentimentResult
                from datetime import datetime
                with open(sent_path) as f:
                    data = json.load(f)

                class _SR:
                    pass
                sentiment_results = []
                for d in data:
                    sr = SentimentResult(
                        post_id=d["post_id"], platform=d["platform"],
                        group_id=d["group_id"], source=d["source"],
                        text=d["text"], original_text=d.get("original_text", d["text"]),
                        timestamp=datetime.fromisoformat(d["timestamp"]),
                        sentiment=d["sentiment"], confidence=d["confidence"],
                        positive_score=d.get("positive_score", 0),
                        negative_score=d.get("negative_score", 0),
                        neutral_score=d.get("neutral_score", 0),
                        engagement_weight=d.get("engagement_weight", 1.0),
                        weighted_sentiment=d.get("weighted_sentiment", 0),
                        themes=d.get("themes", []),
                        method=d.get("method", "model"),
                    )
                    sentiment_results.append(sr)

        console.print(f"\n[cyan]Running comparative analysis...[/]")
        assessments = comparative_engine.compare(
            sentiment_results,
            baseline_start, baseline_end,
            current_start, current_end,
        )
        console.print(f"[green]✓[/] Generated {len(assessments)} intelligence assessments")

        # Topic modeling
        console.print(f"\n[cyan]Running topic modeling...[/]")
        topics_by_group: dict = {}
        import pandas as pd
        df_all = pd.DataFrame([{
            "group_id": r.group_id,
            "text": r.text,
            "sentiment": r.sentiment,
            "timestamp": r.timestamp,
        } for r in sentiment_results])

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

        # Generate report
        console.print(f"\n[cyan]Generating intelligence report...[/]")
        report = intel_gen.generate(
            sentiment_results, assessments, topics_by_group,
            baseline_start, baseline_end, current_start, current_end,
        )
        console.print(f"[green]✓[/] Intelligence report saved → dashboard/data/intelligence_report.json")

        # Print summary table
        _print_summary_table(console, report["summary"])

    console.print(Panel.fit("[bold green]Pipeline complete![/]", border_style="green"))


def _print_summary_table(console, summary: dict):
    table = Table(title="Intelligence Summary", border_style="cyan")
    table.add_column("Group", style="bold")
    table.add_column("Posts", justify="right")
    table.add_column("Avg Sentiment", justify="right")
    table.add_column("Positive %", justify="right")
    table.add_column("Negative %", justify="right")

    for gid, data in summary.get("groups", {}).items():
        score = data["avg_sentiment_score"]
        color = "green" if score > 0.1 else ("red" if score < -0.1 else "yellow")
        table.add_row(
            data["display_name"],
            str(data["post_count"]),
            f"[{color}]{score:+.3f}[/]",
            f"{data['positive_pct']}%",
            f"{data['negative_pct']}%",
        )
    console.print(table)

    console.print("\n[bold]Top Intelligence Assessments:[/]")
    for i, a in enumerate(summary.get("top_assessments", [])[:5], 1):
        icon = "📉" if a["direction"] == "decrease" else ("📈" if a["direction"] == "increase" else "➡️")
        console.print(f"  {i}. {icon} [bold]{a['group']}[/] — {a['theme_label'] if 'theme_label' in a else a['theme']}: {a['narrative'][:120]}...")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Arabic Intel Sentiment Analysis")
    parser.add_argument("--mode", choices=["collect", "analyze", "report", "full", "demo"], default="demo")
    parser.add_argument("--demo", action="store_true", help="Use demo data instead of live APIs")
    args = parser.parse_args()

    use_demo = args.demo or args.mode == "demo"
    run_pipeline(args.mode if args.mode != "demo" else "full", use_demo=use_demo)
