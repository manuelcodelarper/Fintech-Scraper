# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single-file Streamlit app (`app.py`) that scrapes MENA/Gulf and US financial news RSS feeds, enriches headlines with Claude (sentiment, sector, tickers, importance, broadcast "lower third" subtitles), and generates broadcast content (headline packages, social teasers, 60-second video scripts) from selected stories. It also shows live market tickers (Yahoo Finance), crypto prices (CoinGecko), and CoinDesk news — all pulled from free, keyless public endpoints.

## Commands

```bash
pip install -r requirements.txt
streamlit run app.py
```

There is no test suite, linter, or build step in this repo.

### Secrets

The Anthropic API key must be set in `.streamlit/secrets.toml`:

```toml
ANTHROPIC_API_KEY = "sk-ant-..."
```

This file is gitignored. Without it, `ai_enabled` is `False` and all Claude-powered features (enrichment, headlines, teasers, scripts, lower thirds) are disabled in the UI, but scraping and live-data panels still work.

## Architecture

Everything lives in `app.py` — there is no package structure. The file is organized top-to-bottom as: config/constants → DB layer → live data fetchers → async RSS scraper → Claude helpers/content generators → Streamlit UI (sidebar, then main area). Streamlit reruns the whole script top-to-bottom on every interaction, so control flow and caching are driven by `st.session_state`, not by conventional app structure.

### Data pipeline

1. **`SOURCES`** — a hardcoded list of RSS feed dicts, each tagged with a `region` (`"gulf"` or `"us"`). Most sources define a primary publisher feed and a Google News `fallback` query (single `site:` operator only — Google News rejects chained `OR site:` lists).
2. **`scrape_all` / `fetch_feed` / `fetch_one_url`** — concurrent `aiohttp` fetch of every source (primary, then fallback if primary returns 0 entries/errors). Entries are filtered by a finance keyword allowlist (`FINANCE_KEYWORDS`) and a date gate (last 7 days, and a hardcoded `year_floor` of 2026 — bump this constant in `fetch_feed` in future years). `run_scrape` wraps the async call with `asyncio.run` (falling back to a manual event loop if one is already running) and persists results.
3. **SQLite (`me_finance.db`)** — two tables: `items` (deduped on `link` via `UNIQUE` + `INSERT OR IGNORE`) and `sessions` (one row per scrape run, so the UI can filter by session). `init_db()` runs `ALTER TABLE ... ADD COLUMN` inside try/except for `session_id`, `region`, `lower_third` — this is the migration mechanism; add new columns the same way rather than editing the `CREATE TABLE` alone, since existing `me_finance.db` files won't get new columns otherwise.
4. **Region classification (`classify_region`)** — trusts the `region` column set at scrape time; only falls back to keyword/flag matching (`GULF_KEYWORDS_FB`/`US_KEYWORDS_FB`) for legacy rows that predate that column.
5. **Enrichment** — `enrich_with_claude` calls Claude once per headline to fill `ai_summary`, `sentiment`, `tickers`, `sector`, `importance`, `lower_third` (persisted via `update_item_ai`). Enrichment is manual (a sidebar button, capped at 20 items per click) and idempotent-ish (only unenriched items, or enriched items missing a lower third, are targeted).
6. **Lower thirds at scrape time** — `auto_enrich_lower_thirds` fires a `ThreadPoolExecutor` (5 workers) of `generate_lower_third` Claude calls for newly scraped items, separate from the full enrichment pass above.

### Claude integration

All Claude calls go through the single `claude_call(api_key, system, user, json_mode)` helper (`POST /v1/messages`, model pinned in `CLAUDE_MODEL`). Higher-level generators (`enrich_with_claude`, `generate_lower_third`, `generate_headlines`, `generate_content`) each define their own system/user prompt templates and parse the response (JSON-mode calls strip markdown fences before `json.loads`). `generate_content` is shared by both the teaser and video-script tabs, branching on a `content_type` string, and retries with backoff on HTTP 429.

### UI / state

The sidebar drives scraping (manual, search-scoped via `build_search_sources`, and an optional 30-minute auto-scrape background thread) and filtering (keyword/sentiment/sector/importance/session, applied in `load_items`). The main area splits into a feed column (Gulf/US/All tabs over `render_news_card`) and a "Content studio" detail column keyed off `st.session_state["selected_item"]`, which is set when a user clicks Headlines/Teaser/Script on a card and persists across reruns until another card is selected or results are cleared.
