# Arabic OSINT Intelligence Sentiment Analysis Platform

Automated OSINT pipeline for Arabic-language social media sentiment analysis targeting publicly monitored channels associated with Hezbollah, Iran/IRGC, Houthis, and Hamas/PIJ.

## Architecture

```
arabic-intel-sentiment/
├── collectors/          # Twitter API v2 + Telegram MTProto collectors
├── processors/          # Arabic NLP preprocessing (diacritics, normalization)
├── analyzers/           # Sentiment (MARBERTv2), topics (BERTopic), comparative
├── config/              # Target accounts & analysis parameters
├── dashboard/           # GitHub Pages static dashboard
│   ├── data/            # Generated JSON reports (committed)
│   ├── css/             # Dark-mode intelligence UI
│   └── js/              # Chart.js visualizations + filtering
└── .github/workflows/   # Daily analysis + Pages deployment
```

## Quick Start (Demo Mode — no API keys needed)

```bash
pip install -r requirements.txt
python main.py --mode demo
# Opens dashboard/data/intelligence_report.json — serve dashboard/ with any HTTP server
```

## Full Pipeline with Live APIs

1. Copy `.env.example` → `.env` and fill credentials
2. `python main.py --mode collect` — collect from Twitter + Telegram
3. `python main.py --mode analyze` — run NLP + sentiment
4. `python main.py --mode report` — generate dashboard JSON

## GitHub Pages Deployment

1. Push to `main` → Actions auto-deploys `dashboard/` to Pages
2. Enable Pages: Settings → Pages → Source: GitHub Actions
3. Add secrets: `TWITTER_BEARER_TOKEN`, `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, etc.

## Intelligence Output

The dashboard shows:
- **Sentiment KPIs** per group with delta vs 2024 baseline
- **Timeline chart** — monthly weighted sentiment score (2024→current)
- **Theme × Group heatmap** — sentiment across 6 strategic themes
- **Comparative assessments** — human-readable findings with evidence posts
- **Filters** — by group, theme, and confidence level

## NLP Stack

| Component | Model / Library |
|---|---|
| Sentiment | `CAMeL-Lab/bert-base-arabic-camelbert-mix-sentiment` → `UBC-NLP/MARBERTv2` |
| Preprocessing | `pyarabic`, `camel-tools`, custom normalization |
| Topic Modeling | `BERTopic` + UMAP + HDBSCAN |
| Entity Extraction | Custom Arabic entity dictionary |

## Disclaimer

This tool analyzes **publicly available** social media content for OSINT/research purposes only.
Data sources: public Telegram channels, public Twitter accounts.
