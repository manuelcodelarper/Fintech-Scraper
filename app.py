import streamlit as st
import asyncio
import aiohttp
import feedparser
import sqlite3
import json
import html
import re
import time
import requests
import threading
from datetime import datetime, timezone
from pathlib import Path

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="MENA Market Agent",
    page_icon="🌍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ─────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Red+Hat+Display:wght@500;700;800&family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap');

  :root {
    --brand:       var(--primary-color, #254886);
    --brand-soft:  rgba(37,72,134,0.10);
    --line:        rgba(37,72,134,0.16);
    --line-strong: rgba(37,72,134,0.30);
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --brand-soft:  rgba(126,163,222,0.16);
      --line:        rgba(142,168,214,0.18);
      --line-strong: rgba(142,168,214,0.32);
    }
  }

  .stApp { font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif !important; }
  .stApp h1, .stApp h2, .stApp h3, .stApp h4 {
    font-family: 'Red Hat Display', sans-serif !important;
    font-weight: 800; letter-spacing: -0.01em;
  }

  .block-container { padding-top: 2.5rem; padding-bottom: 2.5rem; }
  .metric-card {
    background: var(--background-color);
    border-radius: 12px; padding: 1.35rem 1.5rem;
    border: 1px solid var(--line);
    margin-top: 0.75rem; margin-bottom: 0.75rem;
  }
  .metric-card .label { font-size: 12px; margin: 0 0 6px; color: var(--text-color); opacity: 0.6; }
  .metric-card .value {
    font-family: ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
    font-variant-numeric: tabular-nums;
    font-size: 25px; font-weight: 600; margin: 0;
  }
  .news-card {
    background: var(--background-color);
    border-radius: 0 12px 12px 0; padding: 1.35rem 1.5rem;
    border: 1px solid var(--line);
    margin-bottom: 1.1rem;
  }
  .badge {
    display: inline-block; font-size: 11px; padding: 3px 11px;
    border-radius: 5px; font-weight: 600; margin-right: 8px;
  }
  .bullish  { background: #16a34a; color: #fff; }
  .bearish  { background: #dc2626; color: #fff; }
  .neutral  { background: rgba(148,163,184,0.25); color: var(--text-color); }
  .high     { background: #d97706; color: #fff; }
  .medium   { background: rgba(148,163,184,0.2); color: var(--text-color); }
  .low      { background: rgba(148,163,184,0.12); color: var(--text-color); opacity: 0.7; }
  .source-tag { font-size: 11px; opacity: 0.6; margin-bottom: 8px; color: var(--text-color); }
  .headline   { font-family: 'Red Hat Display', sans-serif; font-size: 16px; font-weight: 700; margin: 6px 0; color: var(--text-color); }
  .summary    { font-size: 12.5px; margin: 6px 0; color: var(--text-color); opacity: 0.75; line-height: 1.55; }
  .meta       { font-size: 11px; margin-top: 10px; color: var(--text-color); opacity: 0.7; }
  .content-box {
    background: var(--brand-soft);
    border-radius: 10px; padding: 1.35rem;
    border: 1px solid var(--line);
    font-size: 13px; color: var(--text-color);
    white-space: pre-wrap; line-height: 1.75;
  }
  a { color: var(--brand); text-decoration: none; }
  a:hover { text-decoration: underline; }

  /* -- Broadcast lower-third graphic (stays dark — mimics a physical TV overlay) -- */
  .lower-third-wrap {
    margin-top: 12px;
    font-family: 'Plus Jakarta Sans', sans-serif;
  }
  .lt-eyebrow {
    display: block;
    color: var(--brand);
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    margin-bottom: 4px;
  }
  .lt-bar {
    display: flex;
    align-items: stretch;
    border-radius: 0 6px 6px 0;
    overflow: hidden;
    box-shadow: 0 2px 8px rgba(0,0,0,0.4);
  }
  .lt-accent {
    width: 5px;
    background: var(--brand);
    flex-shrink: 0;
  }
  .lt-body {
    background: rgba(10,16,30,0.92);
    padding: 8px 16px 9px 12px;
    flex: 1;
  }
  .lt-headline {
    font-family: 'Red Hat Display', sans-serif;
    font-size: 15px;
    font-weight: 700;
    color: #f1f5f9;
    line-height: 1.25;
    letter-spacing: -0.01em;
    margin: 0 0 3px;
  }
  .lt-sub {
    font-size: 11px;
    font-weight: 500;
    color: #94a3b8;
    letter-spacing: 0.02em;
    margin: 0;
  }
  .lt-angle-tag {
    font-size: 10px;
    font-weight: 700;
    color: var(--brand);
    text-transform: uppercase;
    letter-spacing: 0.12em;
    margin-bottom: 8px;
  }
</style>
""", unsafe_allow_html=True)

# ── Constants ──────────────────────────────────────────────────────────────────
DB_PATH = Path("me_finance.db")

SOURCES = [
    # ═══════════════════════════════════════════════════════════════════════
    # GULF & MENA  (region = "gulf")
    #
    # Strategy: try the publisher's own RSS feed first (most reliable),
    # fall back to a focused Google News RSS query if it fails.
    # Every fallback query uses a SINGLE site: operator — Google News
    # rejects chained OR site: lists and returns nothing.
    # ═══════════════════════════════════════════════════════════════════════

    # The National — largest English UAE newspaper, strong business desk
    {"name": "The National",
     "label": "The National (UAE)",
     "country": "🇦🇪", "type": "news", "region": "gulf",
     "url": "https://www.thenationalnews.com/rss/business.xml",
     "fallback": "https://news.google.com/rss/search?q=UAE+business+finance+site:thenationalnews.com&hl=en-AE&gl=AE&ceid=AE:en"},

    # Arab News — Saudi Arabia's leading English newspaper
    {"name": "Arab News",
     "label": "Arab News (Saudi Arabia)",
     "country": "🇸🇦", "type": "news", "region": "gulf",
     "url": "https://www.arabnews.com/rss.xml",
     "fallback": "https://news.google.com/rss/search?q=Saudi+economy+finance+site:arabnews.com&hl=en-SA&gl=SA&ceid=SA:en"},

    # Arabian Business — premier GCC business magazine
    {"name": "Arabian Business",
     "label": "Arabian Business",
     "country": "🇦🇪", "type": "news", "region": "gulf",
     "url": "https://www.arabianbusiness.com/rss/latest-news",
     "fallback": "https://news.google.com/rss/search?q=UAE+Gulf+business+site:arabianbusiness.com&hl=en-AE&gl=AE&ceid=AE:en"},

    # Gulf Business — UAE/GCC business & finance monthly
    {"name": "Gulf Business",
     "label": "Gulf Business",
     "country": "🇦🇪", "type": "news", "region": "gulf",
     "url": "https://gulfbusiness.com/feed/",
     "fallback": "https://news.google.com/rss/search?q=UAE+Gulf+finance+site:gulfbusiness.com&hl=en-AE&gl=AE&ceid=AE:en"},

    # Zawya — Thomson Reuters MENA financial newswire
    {"name": "Zawya",
     "label": "Zawya (MENA)",
     "country": "🌍", "type": "news", "region": "gulf",
     "url": "https://www.zawya.com/rss/mena/economy.xml",
     "fallback": "https://news.google.com/rss/search?q=MENA+economy+markets+site:zawya.com&hl=en-AE&gl=AE&ceid=AE:en"},

    # Reuters — dedicated MENA search (one site: only)
    {"name": "Reuters MENA",
     "label": "Reuters — Gulf & MENA",
     "country": "🌐", "type": "news", "region": "gulf",
     "url": "https://news.google.com/rss/search?q=UAE+OR+Saudi+OR+Gulf+OR+MENA+finance+economy+site:reuters.com&hl=en-AE&gl=AE&ceid=AE:en"},

    # AGBI — Arabia Gulf Business Intelligence
    {"name": "AGBI",
     "label": "AGBI — Gulf Business Intelligence",
     "country": "🌍", "type": "news", "region": "gulf",
     "url": "https://agbi.com/feed/",
     "fallback": "https://news.google.com/rss/search?q=Gulf+MENA+business+site:agbi.com&hl=en-AE&gl=AE&ceid=AE:en"},

    # Khaleej Times — UAE daily, strong business section
    {"name": "Khaleej Times",
     "label": "Khaleej Times (UAE)",
     "country": "🇦🇪", "type": "news", "region": "gulf",
     "url": "https://www.khaleejtimes.com/rss/business.xml",
     "fallback": "https://news.google.com/rss/search?q=UAE+business+economy+site:khaleejtimes.com&hl=en-AE&gl=AE&ceid=AE:en"},

    # ═══════════════════════════════════════════════════════════════════════
    # US & GLOBAL  (region = "us")
    #
    # Direct feeds from credible US financial publishers where available.
    # ═══════════════════════════════════════════════════════════════════════

    # Reuters — top business RSS (publicly available)
    {"name": "Reuters Business",
     "label": "Reuters Business",
     "country": "🇺🇸", "type": "news", "region": "us",
     "url": "https://feeds.reuters.com/reuters/businessNews",
     "fallback": "https://news.google.com/rss/search?q=US+markets+finance+economy+site:reuters.com&hl=en&gl=US&ceid=US:en"},

    # Reuters — markets feed
    {"name": "Reuters Markets",
     "label": "Reuters Markets",
     "country": "🇺🇸", "type": "exchange", "region": "us",
     "url": "https://feeds.reuters.com/reuters/financialsNews",
     "fallback": "https://news.google.com/rss/search?q=stock+market+Wall+Street+earnings+site:reuters.com&hl=en&gl=US&ceid=US:en"},

    # AP Business — Associated Press business desk
    {"name": "AP Business",
     "label": "AP Business",
     "country": "🇺🇸", "type": "news", "region": "us",
     "url": "https://feeds.apnews.com/rss/apf-business",
     "fallback": "https://news.google.com/rss/search?q=US+business+economy+markets+site:apnews.com&hl=en&gl=US&ceid=US:en"},

    # CNBC — US markets & finance
    {"name": "CNBC Markets",
     "label": "CNBC Markets",
     "country": "🇺🇸", "type": "exchange", "region": "us",
     "url": "https://www.cnbc.com/id/20910258/device/rss/rss.html",
     "fallback": "https://news.google.com/rss/search?q=US+stock+market+finance+site:cnbc.com&hl=en&gl=US&ceid=US:en"},

    # MarketWatch — US markets news (filtered to markets/stocks only)
    {"name": "MarketWatch",
     "label": "MarketWatch — Markets",
     "country": "🇺🇸", "type": "exchange", "region": "us",
     "url": "https://news.google.com/rss/search?q=stock+market+OR+S%26P+OR+Nasdaq+OR+earnings+OR+Fed+site:marketwatch.com&hl=en&gl=US&ceid=US:en"},

    # WSJ Markets — Wall Street Journal markets desk
    {"name": "WSJ Markets",
     "label": "WSJ — Markets",
     "country": "🇺🇸", "type": "exchange", "region": "us",
     "url": "https://news.google.com/rss/search?q=markets+OR+stocks+OR+bonds+OR+earnings+site:wsj.com&hl=en&gl=US&ceid=US:en"},

    # Reuters — US tech & big earnings
    {"name": "Reuters Tech",
     "label": "Reuters — US Tech & Earnings",
     "country": "🇺🇸", "type": "exchange", "region": "us",
     "url": "https://news.google.com/rss/search?q=Apple+OR+Nvidia+OR+Microsoft+OR+Amazon+earnings+OR+results+site:reuters.com&hl=en&gl=US&ceid=US:en"},
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}

# ── Live market tickers (Yahoo Finance) ────────────────────────────────────────
LIVE_TICKERS = [
    # MENA indices
    {"symbol": "^TASI",   "label": "TASI (Saudi)",     "flag": "🇸🇦", "type": "index"},
    {"symbol": "^DFMGI",  "label": "DFM General",      "flag": "🇦🇪", "type": "index"},
    {"symbol": "^FTFADGI","label": "ADX General",       "flag": "🇦🇪", "type": "index"},
    {"symbol": "^CASE30", "label": "EGX 30 (Egypt)",    "flag": "🇪🇬", "type": "index"},
    {"symbol": "^QSI",    "label": "QE Index (Qatar)",  "flag": "🇶🇦", "type": "index"},
    # Commodities critical to MENA
    {"symbol": "BZ=F",    "label": "Brent Crude",       "flag": "🛢️",  "type": "commodity"},
    {"symbol": "CL=F",    "label": "WTI Crude",         "flag": "🛢️",  "type": "commodity"},
    {"symbol": "GC=F",    "label": "Gold",              "flag": "🥇",  "type": "commodity"},
    {"symbol": "NG=F",    "label": "Natural Gas",       "flag": "⚡",  "type": "commodity"},
    # Key currencies
    {"symbol": "USDAED=X","label": "USD/AED",           "flag": "💱",  "type": "fx"},
    {"symbol": "USDSAR=X","label": "USD/SAR",           "flag": "💱",  "type": "fx"},
    {"symbol": "USDEGP=X","label": "USD/EGP",           "flag": "💱",  "type": "fx"},
]

SECTOR_COLORS = {
    "Energy": "🟠", "Banking": "🔵", "Real Estate": "🟢",
    "Technology": "🟣", "Retail": "🟡", "Transport": "⚪",
    "Government": "🔴", "Macro": "⚫", "Other": "⬜",
}

def safe_url(url: str) -> str:
    """Only allow http(s) links in rendered HTML — neutralises javascript: URIs etc.
    Scraped/AI content is untrusted and gets rendered with unsafe_allow_html=True."""
    url = (url or "").strip()
    return url if url.startswith(("http://", "https://")) else "#"

# Classification is now driven by the "region" field on each source dict.
# For items already in the DB without a region field, we fall back to keyword matching.
GULF_KEYWORDS_FB = [
    "uae", "dubai", "abu dhabi", "saudi", "aramco", "adnoc", "riyadh",
    "gulf", "arabian", "khaleej", "mena", "opec", "qatar", "kuwait",
    "bahrain", "oman", "egypt", "egx", "tadawul", "dfm", "adx",
    "emaar", "aldar", "al rajhi", "emirates nbd", "first abu dhabi",
    "gcc", "jordan", "lebanon", "iraq", "libya", "tunisia", "algeria", "morocco",
]
US_KEYWORDS_FB = [
    "nasdaq", "s&p 500", "s&p500", "dow jones", "wall street", "federal reserve",
    "fed reserve", "u.s. economy", "us economy", "apple inc", "microsoft",
    "nvidia", "amazon", "apnews.com", "reuters.com/us",
]

def classify_region(item):
    """
    Primary: use the 'region' field stored on the item (set at scrape time from source dict).
    Fallback for legacy DB rows: keyword scan on title + source + link.
    """
    # Region stored directly
    region = (item.get("region") or "").lower()
    if region in ("gulf", "us"):
        return region

    # Keyword fallback
    haystack = " ".join([
        (item.get("source") or ""),
        (item.get("title")  or ""),
        (item.get("link")   or ""),
        (item.get("country") or ""),
    ]).lower()

    for kw in US_KEYWORDS_FB:
        if kw in haystack:
            return "us"
    for kw in GULF_KEYWORDS_FB:
        if kw in haystack:
            return "gulf"

    country = item.get("country", "")
    GULF_FLAGS = {
        "🇦🇪","🇸🇦","🇶🇦",
        "🇴🇲","🇧🇭","🇰🇼",
        "🇪🇬","🇯🇴","🇱🇧",
    }
    if country in GULF_FLAGS:
        return "gulf"
    if country == "🇺🇸":
        return "us"

    return "gulf"  # MENA-first default


# ── Database ───────────────────────────────────────────────────────────────────
def get_db_connection():
    return sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30.0)

def init_db():
    con = get_db_connection()
    con.execute("""
        CREATE TABLE IF NOT EXISTS items (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            source      TEXT, country TEXT, type TEXT,
            title       TEXT, link TEXT UNIQUE,
            summary     TEXT, published TEXT, fetched_at TEXT,
            ai_summary  TEXT, sentiment TEXT, tickers TEXT,
            sector      TEXT, importance TEXT, enriched INTEGER DEFAULT 0,
            session_id  INTEGER, region TEXT DEFAULT '', lower_third TEXT DEFAULT ''
        )
    """)
    # Add session_id column if upgrading from older schema
    try:
        con.execute("ALTER TABLE items ADD COLUMN session_id INTEGER")
        con.commit()
    except Exception:
        pass
    # Add region column if upgrading from older schema
    try:
        con.execute("ALTER TABLE items ADD COLUMN region TEXT DEFAULT ''")
        con.commit()
    except Exception:
        pass
    # Add lower_third column if upgrading from older schema
    try:
        con.execute("ALTER TABLE items ADD COLUMN lower_third TEXT DEFAULT ''")
        con.commit()
    except Exception:
        pass
    con.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT,
            label      TEXT,
            item_count INTEGER DEFAULT 0
        )
    """)
    con.commit()
    con.close()

def start_session(label=None):
    """Create a new scrape session and return its id."""
    con = get_db_connection()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    label = label or now
    con.execute("INSERT INTO sessions (started_at, label) VALUES (?, ?)", (now, label))
    con.commit()
    session_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
    con.close()
    return session_id

def update_session_count(session_id, count):
    con = get_db_connection()
    con.execute("UPDATE sessions SET item_count = item_count + ? WHERE id = ?", (count, session_id))
    con.commit()
    con.close()

def load_sessions():
    con = get_db_connection()
    rows = con.execute("SELECT id, started_at, label, item_count FROM sessions ORDER BY id DESC").fetchall()
    con.close()
    return [{"id": r[0], "started_at": r[1], "label": r[2], "item_count": r[3]} for r in rows]

def clear_all_items():
    con = get_db_connection()
    con.execute("DELETE FROM items")
    con.execute("DELETE FROM sessions")
    con.commit()
    con.close()

def save_items(con, items, session_id=None):
    saved = 0
    for item in items:
        try:
            con.execute("""
                INSERT OR IGNORE INTO items
                (source,country,type,title,link,summary,published,fetched_at,session_id,region)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (item["source"], item["country"], item["type"],
                 item["title"], item["link"], item["summary"],
                 item["published"], item["fetched_at"], session_id,
                 item.get("region", "")))
            if con.execute("SELECT changes()").fetchone()[0]:
                saved += 1
        except Exception:
            pass
    con.commit()
    return saved

def load_items(keyword="", sentiment="All", sector="All", importance="All", limit=100, session_id=None, min_id=None):
    con = get_db_connection()
    con.row_factory = sqlite3.Row
    q = "SELECT * FROM items WHERE 1=1"
    params = []
    if keyword:
        q += " AND (LOWER(title) LIKE ? OR LOWER(ai_summary) LIKE ? OR LOWER(summary) LIKE ?)"
        k = f"%{keyword.lower()}%"
        params += [k, k, k]
    if sentiment != "All":
        q += " AND sentiment = ?"
        params.append(sentiment)
    if sector != "All":
        q += " AND sector = ?"
        params.append(sector)
    if importance != "All":
        q += " AND importance = ?"
        params.append(importance)
    if session_id is not None:
        q += " AND session_id = ?"
        params.append(session_id)
    if min_id is not None:
        q += " AND id > ?"
        params.append(min_id)
    q += " ORDER BY published DESC, fetched_at DESC LIMIT ?"
    params.append(limit)
    rows = [dict(r) for r in con.execute(q, params).fetchall()]
    con.close()
    return rows

def update_item_ai(con, link, ai_data):
    con.execute("""
        UPDATE items SET ai_summary=?, sentiment=?, tickers=?, sector=?, importance=?,
        lower_third=?, enriched=1 WHERE link=?""",
        (ai_data.get("summary", ""), ai_data.get("sentiment", "Neutral"),
         json.dumps(ai_data.get("tickers", [])), ai_data.get("sector", "Other"),
         ai_data.get("importance", "Low"), ai_data.get("lower_third", ""), link))
    con.commit()

def get_stats():
    con = get_db_connection()
    total    = con.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    bullish  = con.execute("SELECT COUNT(*) FROM items WHERE sentiment='Bullish'").fetchone()[0]
    bearish  = con.execute("SELECT COUNT(*) FROM items WHERE sentiment='Bearish'").fetchone()[0]
    high_imp = con.execute("SELECT COUNT(*) FROM items WHERE importance='High'").fetchone()[0]
    enriched = con.execute("SELECT COUNT(*) FROM items WHERE enriched=1").fetchone()[0]
    con.close()
    return total, bullish, bearish, high_imp, enriched


# -- Live market data (Yahoo Finance v8 - no API key required) -----------------
def fetch_live_quote(symbol: str) -> dict:
    """Fetch a single quote from Yahoo Finance. Returns price, change, change_pct."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"interval": "1d", "range": "2d"}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }
    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()
        meta = data["chart"]["result"][0]["meta"]
        price      = meta.get("regularMarketPrice") or meta.get("previousClose", 0)
        prev_close = meta.get("previousClose") or meta.get("chartPreviousClose", price)
        change     = price - prev_close
        change_pct = (change / prev_close * 100) if prev_close else 0
        currency   = meta.get("currency", "")
        return {
            "price": price, "change": change, "change_pct": change_pct,
            "currency": currency, "ok": True,
        }
    except Exception as e:
        return {"price": None, "change": 0, "change_pct": 0, "currency": "", "ok": False, "error": str(e)}

def fetch_all_live_quotes() -> list:
    """Fetch all LIVE_TICKERS quotes. Returns list of ticker dicts with quote data."""
    results = []
    for t in LIVE_TICKERS:
        q = fetch_live_quote(t["symbol"])
        results.append({**t, **q})
        time.sleep(0.15)
    return results

# ── CoinDesk — real-time crypto prices + news (no API key required) ───────────

CRYPTO_ASSETS = [
    {"id": "bitcoin",   "symbol": "BTC", "name": "Bitcoin"},
    {"id": "ethereum",  "symbol": "ETH", "name": "Ethereum"},
    {"id": "solana",    "symbol": "SOL", "name": "Solana"},
    {"id": "ripple",    "symbol": "XRP", "name": "XRP"},
    {"id": "binancecoin","symbol": "BNB","name": "BNB"},
]

def fetch_crypto_prices() -> list:
    """Fetch live prices from CoinGecko public API (free, no key needed)."""
    try:
        ids = ",".join(a["id"] for a in CRYPTO_ASSETS)
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": ids, "vs_currencies": "usd",
                    "include_24hr_change": "true", "include_24hr_vol": "true"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        results = []
        for asset in CRYPTO_ASSETS:
            d = data.get(asset["id"], {})
            price  = d.get("usd", 0)
            change = d.get("usd_24h_change", 0) or 0
            results.append({
                "symbol":  asset["symbol"],
                "name":    asset["name"],
                "price":   price,
                "change":  change,
                "ok":      bool(price),
            })
        return results
    except Exception as e:
        return [{"symbol": a["symbol"], "name": a["name"],
                 "price": None, "change": 0, "ok": False, "error": str(e)}
                for a in CRYPTO_ASSETS]


def fetch_coindesk_news() -> list:
    """Fetch latest headlines from CoinDesk RSS feed (free, no key needed)."""
    try:
        r = requests.get(
            "https://www.coindesk.com/arc/outboundfeeds/rss/",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        r.raise_for_status()
        feed = feedparser.parse(r.text)
        news = []
        for e in feed.entries[:6]:
            title   = (e.get("title") or "").strip()
            summary = re.sub(r"<[^>]+>", "", e.get("summary", "")).strip()[:200]
            link    = e.get("link", "")
            pub     = getattr(e, "published", "")[:16]
            if title:
                news.append({"title": title, "summary": summary,
                             "link": link, "published": pub})
        return news
    except Exception as e:
        return [{"title": f"Could not fetch CoinDesk news: {e}",
                 "summary": "", "link": "", "published": ""}]


def fetch_coindesk_snapshot(api_key: str = None) -> dict:
    """Fetch crypto prices + CoinDesk news. api_key unused (kept for compat)."""
    prices = fetch_crypto_prices()
    news   = fetch_coindesk_news()
    return {"prices": prices, "news": news, "raw": "", "error": ""}


# ── Async scraper ─────────────────────────────────────────────────────────────
import email.utils as _email_utils
import calendar as _calendar

def parse_entry_date(e):
    """Return timezone-aware UTC datetime from a feedparser entry, or None."""
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(e, attr, None)
        if t:
            try:
                return datetime.fromtimestamp(_calendar.timegm(t), tz=timezone.utc)
            except Exception:
                pass
    for attr in ("published", "updated"):
        raw = getattr(e, attr, None)
        if raw:
            try:
                return _email_utils.parsedate_to_datetime(raw).astimezone(timezone.utc)
            except Exception:
                pass
    return None


async def fetch_one_url(session, url, source, now_dt, week_ago, year_floor):
    """Fetch a single RSS URL and return (ok, items, error)."""
    try:
        async with session.get(
            url, headers=HEADERS,
            timeout=aiohttp.ClientTimeout(total=6, connect=3)
        ) as r:
            if r.status == 403:
                return False, [], f"403 Forbidden"
            r.raise_for_status()
            raw = await r.text()

        parsed = feedparser.parse(raw)
        if not parsed.entries:
            return False, [], "Feed returned 0 entries"

        now_str = now_dt.strftime("%Y-%m-%d %H:%M UTC")
        items   = []

        for e in parsed.entries[:40]:
            title = (e.get("title") or "").strip()
            if not title:
                continue

            # Strip Google News " - Publisher" suffix from titles
            title = re.sub(r"\s+-\s+[A-Z][^-]{2,40}$", "", title).strip()

            # Relevance filter — must contain at least one finance/market keyword
            FINANCE_KEYWORDS = [
                "market", "stock", "share", "equity", "bond", "fund", "trade",
                "economy", "economic", "gdp", "inflation", "interest rate", "fed",
                "central bank", "bank", "finance", "financial", "invest", "earn",
                "profit", "revenue", "ipo", "merger", "acquisition", "oil", "gold",
                "crude", "opec", "currency", "dollar", "euro", "forex", "crypto",
                "bitcoin", "etf", "index", "nasdaq", "s&p", "dow", "tasi", "dfm",
                "adx", "tadawul", "gcc", "gulf", "mena", "uae", "saudi", "qatar",
                "debt", "deficit", "budget", "fiscal", "monetary", "rate", "growth",
                "recession", "rally", "selloff", "ipo", "dividend", "yield",
            ]
            title_lower = title.lower()
            summary_lower = (e.get("summary", "") or "").lower()
            if not any(kw in title_lower or kw in summary_lower for kw in FINANCE_KEYWORDS):
                continue

            pub_dt = parse_entry_date(e)
            # If date unreadable, assume today so we don't silently drop it
            if pub_dt is None:
                pub_dt = now_dt
            # Date gates: must be 2026, within last 7 days
            if pub_dt < year_floor or pub_dt < week_ago:
                continue

            summary = re.sub(r"<[^>]+>", "", e.get("summary", "")).strip()[:500]
            link    = e.get("link", "")

            items.append({
                "source":     source["name"],
                "country":    source["country"],
                "type":       source["type"],
                "region":     source.get("region", ""),
                "title":      title,
                "link":       link,
                "summary":    summary,
                "published":  pub_dt.strftime("%Y-%m-%d %H:%M"),
                "fetched_at": now_str,
                "_pub_dt":    pub_dt,
            })

        items.sort(key=lambda x: x["_pub_dt"], reverse=True)
        for it in items:
            it.pop("_pub_dt", None)

        return True, items, None

    except Exception as ex:
        return False, [], str(ex)


async def fetch_feed(session, source):
    """Try primary URL, then fallback if present."""
    from datetime import timedelta
    now_dt     = datetime.now(timezone.utc)
    week_ago   = now_dt - timedelta(days=7)
    year_floor = datetime(2026, 1, 1, tzinfo=timezone.utc)

    primary_url  = source["url"]
    fallback_url = source.get("fallback")

    ok, items, err = await fetch_one_url(session, primary_url, source, now_dt, week_ago, year_floor)
    if ok and items:
        return source["name"], True, items, None

    # Primary had 0 results or failed — try fallback
    if fallback_url:
        ok2, items2, err2 = await fetch_one_url(session, fallback_url, source, now_dt, week_ago, year_floor)
        if ok2 and items2:
            return source["name"], True, items2, None
        return source["name"], False, [], f"primary: {err} | fallback: {err2}"

    # No fallback, return whatever we got (even 0 items with ok=True is fine)
    if ok:
        return source["name"], True, items, None
    return source["name"], False, [], err


async def scrape_all(extra_sources=None):
    all_sources = SOURCES + (extra_sources or [])
    # High concurrency — all feeds fetched simultaneously
    connector = aiohttp.TCPConnector(
        limit=50, limit_per_host=3,
        ttl_dns_cache=300, use_dns_cache=True,
    )
    async with aiohttp.ClientSession(
        connector=connector,
        headers=HEADERS,
    ) as session:
        return await asyncio.gather(
            *[fetch_feed(session, s) for s in all_sources],
            return_exceptions=False,
        )


def run_scrape(extra_sources=None):
    try:
        results = asyncio.run(scrape_all(extra_sources))
    except RuntimeError:
        # Fallback if event loop already running (e.g. some Streamlit versions)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        results = loop.run_until_complete(scrape_all(extra_sources))
    session_id = start_session()
    con        = get_db_connection()
    total_new = 0
    log       = []

    for name, ok, items, err in results:
        if ok:
            new = save_items(con, items, session_id=session_id)
            total_new += new
            log.append(f"✅ {name}: {len(items)} fetched, {new} new")
        else:
            log.append(f"❌ {name}: {(err or '')[:80]}")

    con.close()
    update_session_count(session_id, total_new)
    return total_new, log


# ── Gemini API helpers ─────────────────────────────────────────────────────────
CLAUDE_MODEL = "claude-sonnet-4-6"

def claude_call(api_key: str, system: str, user: str, json_mode: bool = False) -> str:
    """Make a single call to the Claude API and return the text response."""
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": CLAUDE_MODEL,
            "max_tokens": 1024,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        },
        timeout=30,
    )
    resp.raise_for_status()
    text = resp.json()["content"][0]["text"].strip()
    if json_mode:
        # Strip markdown fences if present
        text = text.replace("```json", "").replace("```", "").strip()
    return text

# ── Enrich ─────────────────────────────────────────────────────────────────────
ENRICH_SYSTEM = (
    "You are a financial news analyst and broadcast producer. "
    "Return ONLY a valid JSON object — no markdown fences, no preamble."
)
ENRICH_USER = """Analyse this headline and return JSON with exactly these fields:
  summary     : one clear sentence (max 25 words) explaining what happened and why it matters
  sentiment   : one of: Bullish, Bearish, Neutral
  tickers     : list of stock tickers or company names mentioned (empty list if none)
  sector      : one of: Energy, Banking, Real Estate, Technology, Retail, Transport, Government, Macro, Other
  importance  : one of: High, Medium, Low
  lower_third : a broadcast lower-third subtitle (max 8 words). Must be a factual detail — a specific number, name, location or consequence. NOT a repeat of the headline. Example: "Brent crude falls 3.2% to $71.40" or "UAE central bank holds rate at 5.15%"

Headline: {title}
Summary: {summary}"""

def enrich_with_claude(api_key, title, summary):
    try:
        raw = claude_call(api_key, ENRICH_SYSTEM, ENRICH_USER.format(title=title, summary=summary[:300]), json_mode=True)
        result = json.loads(raw)
        if not result.get("lower_third"):
            result["lower_third"] = ""
        return result
    except Exception:
        return {"summary": summary[:100], "sentiment": "Neutral",
                "tickers": [], "sector": "Other", "importance": "Low",
                "lower_third": ""}

# ── Auto lower-third generator (called at scrape time) ────────────────────────
def generate_lower_third(api_key: str, title: str, summary: str) -> str:
    """Generate a single broadcast lower-third subtitle for a headline."""
    if not api_key:
        return ""
    try:
        system = "You are a broadcast news producer. Return ONLY the lower-third subtitle text — no quotes, no explanation, nothing else."
        user   = (
            f"Write ONE lower-third subtitle for this headline.\n"
            f"Rules: max 8 words, must be a specific factual detail (number, %, name, location or consequence), "
            f"must ADD information not in the headline, no punctuation at end.\n\n"
            f"Headline: {title}\n"
            f"Context: {summary[:200]}"
        )
        return claude_call(api_key, system, user).strip().strip('"').strip("'")
    except Exception:
        return ""


def auto_enrich_lower_thirds(api_key: str, new_items: list, con) -> int:
    """
    Generate lower thirds in parallel using a thread pool.
    5 concurrent Claude calls keeps it fast without hitting rate limits.
    """
    if not api_key or not new_items:
        return 0

    from concurrent.futures import ThreadPoolExecutor, as_completed

    def gen_one(item):
        lt = generate_lower_third(api_key, item.get("title", ""), item.get("summary", ""))
        return item.get("link", ""), lt

    updated = 0
    items_to_process = new_items[:20]
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(gen_one, item): item for item in items_to_process}
        for future in as_completed(futures):
            try:
                link, lt = future.result(timeout=10)
                if lt and link:
                    con.execute(
                        "UPDATE items SET lower_third=? WHERE link=?",
                        (lt, link)
                    )
                    updated += 1
            except Exception:
                pass
    con.commit()
    return updated


# ── Headline generation ────────────────────────────────────────────────────────
HEADLINE_SYSTEM = (
    "You are a financial news editor and broadcast graphics producer. "
    "Return ONLY a valid JSON array — no markdown, no preamble, no explanation."
)
HEADLINE_USER = """Generate 5 headline packages for this story. Each package has two parts:
  1. headline   : the main on-screen headline (max 12 words, punchy, clear)
  2. lower_third: the broadcast lower-third subtitle (max 8 words, factual detail that adds context — a name, figure, location, or consequence. NOT a repeat of the headline)

Vary the angle across the 5 packages:
  - Package 1: Data-focused (lead with the number or percentage)
  - Package 2: Market reaction (how markets or investors responded)
  - Package 3: Investor angle (what it means for portfolios or earnings)
  - Package 4: Impact-focused (consequence for the country or sector)
  - Package 5: Broad audience (plain-language, accessible framing)

Return a JSON array of 5 objects, each with keys "headline" and "lower_third".

Original: {title}
Summary:  {summary}
Sector:   {sector}
Sentiment:{sentiment}"""

def generate_headlines(api_key, item):
    try:
        raw = claude_call(
            api_key,
            HEADLINE_SYSTEM,
            HEADLINE_USER.format(
                title=item.get("title", ""),
                summary=(item.get("ai_summary") or item.get("summary", ""))[:300],
                sector=item.get("sector", "Other"),
                sentiment=item.get("sentiment", "Neutral"),
            ),
            json_mode=True,
        )
        parsed = json.loads(raw)
        # Normalise: accept either list of dicts or list of strings (fallback)
        result = []
        for item_p in parsed:
            if isinstance(item_p, dict):
                result.append({
                    "headline":    item_p.get("headline", str(item_p)),
                    "lower_third": item_p.get("lower_third", ""),
                })
            else:
                result.append({"headline": str(item_p), "lower_third": ""})
        return result
    except Exception as e:
        return [{"headline": f"Error generating headlines: {e}", "lower_third": ""}]

# ── Content generators ─────────────────────────────────────────────────────────
TEASER_SYSTEM = (
    "You are a sharp social media writer for a Middle East finance news account. "
    "Return only the tweet text, no preamble."
)
TEASER_USER = """Write a punchy Twitter/X teaser (max 240 chars) for this story.
Include 2-3 relevant hashtags at the end. Urgent and informative, not clickbait.

Headline: {title}
Summary:  {summary}
Sentiment:{sentiment}"""

VIDEO_SYSTEM = (
    "You are a financial news broadcaster writing 60-second video scripts. "
    "Structure: Hook (5s) → Context (15s) → Key facts (25s) → Impact/Outlook (10s) → Closing (5s). "
    "Label each section. Clear, confident broadcast tone. No fluff."
)
VIDEO_USER = """Write the full script.

Headline: {title}
Summary:  {summary}
Sector:   {sector}
Sentiment:{sentiment}"""

def generate_content(api_key, content_type, item):
    if content_type == "teaser":
        system, user = TEASER_SYSTEM, TEASER_USER.format(
            title=item.get("title", ""),
            summary=(item.get("ai_summary") or item.get("summary", ""))[:300],
            sentiment=item.get("sentiment", "Neutral"),
        )
    else:
        system, user = VIDEO_SYSTEM, VIDEO_USER.format(
            title=item.get("title", ""),
            summary=(item.get("ai_summary") or item.get("summary", ""))[:300],
            sentiment=item.get("sentiment", "Neutral"),
            sector=item.get("sector", "Other"),
        )
    for attempt in range(3):
        try:
            return claude_call(api_key, system, user)
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                time.sleep(15 * (attempt + 1))
                continue
            return f"Error: {e}"
        except Exception as e:
            return f"Error: {e}"
    return "Rate limit hit — please wait 30 seconds and try again."

# ── Auto-scrape scheduler ──────────────────────────────────────────────────────
def schedule_scrape(interval_minutes, extra_sources=None):
    while True:
        time.sleep(interval_minutes * 60)
        try:
            run_scrape(extra_sources)
        except Exception:
            pass

# ── Session state init ─────────────────────────────────────────────────────────
if "db_init" not in st.session_state:
    init_db()
    st.session_state["db_init"] = True
if "session_boundary_id" not in st.session_state:
    # Marks the newest item that existed before this browser session started —
    # the default feed view only shows items scraped after this, so a fresh
    # page load doesn't dump every headline ever scraped.
    _con = get_db_connection()
    st.session_state["session_boundary_id"] = _con.execute(
        "SELECT COALESCE(MAX(id), 0) FROM items"
    ).fetchone()[0]
    _con.close()
if "scheduler_started" not in st.session_state:
    st.session_state["scheduler_started"] = False
if "selected_item" not in st.session_state:
    st.session_state["selected_item"] = None
if "confirm_clear" not in st.session_state:
    st.session_state["confirm_clear"] = False
for k, v in [("live_quotes", []), ("live_ts", ""), ("live_open", False), ("cd_data", None), ("cd_ts", ""), ("cd_loading", False)]:
    if k not in st.session_state:
        st.session_state[k] = v
for key in ("generated_teaser", "generated_script", "generated_headlines"):
    if key not in st.session_state:
        st.session_state[key] = "" if key != "generated_headlines" else []

# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("## 🌍 MENA Market Agent")
    st.markdown("---")

    # ── API Key (loaded from Streamlit secrets — never shown in UI) ───────────
    anthropic_key    = st.secrets.get("ANTHROPIC_API_KEY", "")
    gemini_key       = anthropic_key   # alias — all AI now uses Claude
    ai_enabled       = bool(anthropic_key)
    coindesk_enabled = bool(anthropic_key)
    if not ai_enabled:
        st.warning("⚠️ Anthropic API key not configured. Add it in your Streamlit Cloud secrets.")

    st.markdown("---")

    # ── Search & scrape ────────────────────────────────────────────────────────
    st.markdown("### 🔍 Search & Scrape")
    search_query = st.text_input(
        "Search topic",
        placeholder="e.g. ADNOC, Fed rate decision, Bitcoin, Tadawul…",
        help="Scrapes live finance/market news matching your search, tagged to Gulf or US based on content",
        label_visibility="collapsed",
    )

    def build_search_sources(query: str) -> list:
        """Build Gulf + US scoped Google News sources for a free-text search."""
        if not query.strip():
            return []
        q = query.strip()
        q_encoded = q.replace(" ", "+")
        short_name = q[:20]
        return [
            {
                "name": f"Search: {short_name} (Gulf)",
                "label": f"Search — {q} (Gulf/MENA)",
                "country": "🌍", "type": "news", "region": "gulf",
                "url": f"https://news.google.com/rss/search?q={q_encoded}+UAE+OR+Saudi+OR+Gulf+OR+MENA+finance&hl=en-AE&gl=AE&ceid=AE:en",
            },
            {
                "name": f"Search: {short_name} (US)",
                "label": f"Search — {q} (US/Global)",
                "country": "🇺🇸", "type": "news", "region": "us",
                "url": f"https://news.google.com/rss/search?q={q_encoded}+finance+OR+market+OR+stock&hl=en&gl=US&ceid=US:en",
            },
        ]

    custom_sources = build_search_sources(search_query)

    # ── Keyword filter (filters already-scraped results, shown below search) ──
    keyword = st.text_input(
        "Filter loaded results",
        placeholder="Filter by keyword…",
        help="Narrows down articles already in your feed below"
    )

    st.markdown("---")

    # ── Scrape controls ────────────────────────────────────────────────────────
    st.markdown("### ⚡ Scrape controls")
    scrape_label = f"🔍 Search & Scrape: \"{search_query[:25]}\"" if search_query.strip() else "🔄 Scrape now"
    if st.button(scrape_label, use_container_width=True, type="primary"):
        spinner_msg = f"Searching for \"{search_query}\"…" if search_query.strip() else "Fetching all sources in parallel…"
        with st.spinner(spinner_msg):
            new_count, log = run_scrape(custom_sources)
        st.success(f"{new_count} new items saved")
        with st.expander("Scrape log"):
            for line in log:
                st.text(line)
        st.rerun()

    auto_scrape = st.toggle("Auto-scrape every 30 min", value=False)
    if auto_scrape and not st.session_state["scheduler_started"]:
        t = threading.Thread(
            target=schedule_scrape,
            args=(30, custom_sources),
            daemon=True
        )
        t.start()
        st.session_state["scheduler_started"] = True
        st.sidebar.success("Auto-scrape pipeline active.")

    st.markdown("---")

    # ── Session history ────────────────────────────────────────────────────────
    st.markdown("### 🕓 Session history")
    sessions = load_sessions()
    if not sessions:
        st.caption("No scrape sessions yet.")
        selected_session_id = None
        min_id_filter = st.session_state["session_boundary_id"]
    else:
        session_options = {"New headlines (this visit)": "__boundary__"}
        for s in sessions:
            label = f"{s['started_at']} — {s['item_count']} items"
            session_options[label] = s["id"]
        session_options["All history (every session)"] = "__all__"
        chosen = st.selectbox("View session", list(session_options.keys()), index=0)
        selection = session_options[chosen]
        if selection == "__boundary__":
            selected_session_id = None
            min_id_filter = st.session_state["session_boundary_id"]
        elif selection == "__all__":
            selected_session_id = None
            min_id_filter = None
        else:
            selected_session_id = selection
            min_id_filter = None

    st.markdown("---")

    # ── Clear results ──────────────────────────────────────────────────────────
    st.markdown("### 🗑️ Clear results")
    if st.button("Clear all items", use_container_width=True):
        st.session_state["confirm_clear"] = True

    if st.session_state.get("confirm_clear"):
        st.warning("This will delete **all** headlines and session history.")
        col_yes, col_no = st.columns(2)
        with col_yes:
            if st.button("Yes, clear", type="primary", use_container_width=True):
                clear_all_items()
                st.session_state["confirm_clear"] = False
                st.session_state["selected_item"] = None
                st.success("Cleared.")
                st.rerun()
        with col_no:
            if st.button("Cancel", use_container_width=True):
                st.session_state["confirm_clear"] = False
                st.rerun()

    # ── Filters ────────────────────────────────────────────────────────────────
    st.markdown("### 🎛️ Filters")
    sentiment_filter = st.selectbox("Sentiment", ["All", "Bullish", "Bearish", "Neutral"])
    sector_filter    = st.selectbox("Sector", ["All", "Energy", "Banking", "Real Estate",
                                                "Technology", "Retail", "Transport",
                                                "Government", "Macro", "Other"])
    importance_filter = st.selectbox("Importance", ["All", "High", "Medium", "Low"])
    limit = st.slider("Max headlines", 10, 500, 200)

# ══════════════════════════════════════════════════════════════════════════════
# MAIN AREA
# ══════════════════════════════════════════════════════════════════════════════
total, bullish, bearish, high_imp, enriched = get_stats()

st.markdown("<div style='margin-top:1rem'></div>", unsafe_allow_html=True)
# ══════════════════════════════════════════════════════════════════════════════
# COINDESK LIVE PANEL
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("""
<div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;">
  <span style="font-size:22px">₿</span>
  <span style="font-size:16px;font-weight:700;color:#f59e0b;letter-spacing:-0.01em">CoinDesk Live</span>
  <span style="font-size:11px;color:var(--text-color);opacity:0.6;margin-left:4px">Real-time crypto & market data</span>
</div>
""", unsafe_allow_html=True)

cd_col1, cd_col2 = st.columns([1, 5])
with cd_col1:
    if st.button("🔄 Fetch Live Data", key="cd_refresh", use_container_width=True, type="primary"):
        with st.spinner("Fetching live crypto prices & CoinDesk news…"):
            st.session_state["cd_data"] = fetch_coindesk_snapshot()
            st.session_state["cd_ts"]   = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        st.rerun()
with cd_col2:
    if st.session_state.get("cd_ts"):
        st.caption(f"Last updated: {st.session_state['cd_ts']}  ·  Prices via CoinGecko · News via CoinDesk RSS")

cd_data = st.session_state.get("cd_data")
if cd_data is None:
    st.info("Click **🔄 Fetch Live Data** to pull real-time crypto prices and CoinDesk headlines.")
elif cd_data.get("error") and not cd_data.get("prices"):
    st.error(f"Error: {cd_data['error']}")
else:
    prices = cd_data.get("prices", [])
    news   = cd_data.get("news", [])

    # ── Price tiles ──────────────────────────────────────────────────────────
    if prices:
        price_cols = st.columns(len(prices))
        for col, p in zip(price_cols, prices):
            with col:
                if p.get("ok") and p["price"]:
                    arrow  = "▲" if p["change"] >= 0 else "▼"
                    color  = "#16a34a" if p["change"] >= 0 else "#dc2626"
                    sign   = "+" if p["change"] >= 0 else ""
                    st.markdown(
                        f'<div class="metric-card" style="text-align:center;">'
                        f'<p class="label">{p["symbol"]}</p>'
                        f'<p class="value" style="font-size:18px">${p["price"]:,.2f}</p>'
                        f'<p style="font-size:12px;color:{color};margin:2px 0">'
                        f'{arrow} {sign}{p["change"]:.2f}%</p></div>',
                        unsafe_allow_html=True
                    )
                else:
                    st.markdown(
                        f'<div class="metric-card" style="text-align:center;">'
                        f'<p class="label">{p["symbol"]}</p>'
                        f'<p style="font-size:11px;color:var(--text-color);opacity:0.6">Unavailable</p></div>',
                        unsafe_allow_html=True
                    )

    # ── CoinDesk news ─────────────────────────────────────────────────────────
    if news:
        st.markdown("<div style='margin-top:12px'></div>", unsafe_allow_html=True)
        news_html = ""
        for n in news:
            news_html += (
                f'<div style="padding:10px 0;border-bottom:1px solid var(--line);">'
                f'<a href="{safe_url(n["link"])}" target="_blank" style="font-size:13px;font-weight:600;color:var(--text-color);">'
                f'{html.escape(n["title"])}</a>'
                + (f'<div style="font-size:11px;color:var(--text-color);opacity:0.6;margin-top:3px">{html.escape(n["summary"])}</div>' if n["summary"] else "")
                + f'</div>'
            )
        st.markdown(
            f'<div style="background:var(--background-color);border:1px solid var(--line);border-radius:12px;'
            f'padding:14px 18px;border-left:3px solid #f59e0b;">{news_html}</div>',
            unsafe_allow_html=True
        )

st.markdown("---")

c1, c2, c3, c4, c5 = st.columns(5)
with c1:
    st.markdown(f'<div class="metric-card"><p class="label">Total items</p><p class="value">{total}</p></div>', unsafe_allow_html=True)
with c2:
    st.markdown(f'<div class="metric-card"><p class="label">Bullish</p><p class="value" style="color:#16a34a">{bullish}</p></div>', unsafe_allow_html=True)
with c3:
    st.markdown(f'<div class="metric-card"><p class="label">Bearish</p><p class="value" style="color:#dc2626">{bearish}</p></div>', unsafe_allow_html=True)
with c4:
    st.markdown(f'<div class="metric-card"><p class="label">High importance</p><p class="value" style="color:#d97706">{high_imp}</p></div>', unsafe_allow_html=True)
with c5:
    st.markdown(f'<div class="metric-card"><p class="label">AI enriched</p><p class="value" style="color:#7c3aed">{enriched}</p></div>', unsafe_allow_html=True)

st.markdown("---")

# ── Load items ─────────────────────────────────────────────────────────────────
items = load_items(keyword, sentiment_filter, sector_filter, importance_filter, limit, session_id=selected_session_id, min_id=min_id_filter)

col_feed, col_detail = st.columns([3, 2], gap="large")

with col_feed:
    if not items:
        st.info("No items yet — click **Scrape now** in the sidebar to fetch headlines.")
    else:
        # ── Enrich button ──────────────────────────────────────────────────────
        unenriched = [i for i in items if not i.get("enriched")]
        missing_lt = [i for i in items if i.get("enriched") and not (i.get("lower_third") or "").strip()]

        if not ai_enabled:
            if unenriched:
                st.info("Add your Anthropic API key in the sidebar to enable AI features.")
        else:
            btn_col1, btn_col2 = st.columns(2)
            with btn_col1:
                if unenriched and st.button(f"✨ Enrich {min(len(unenriched), 20)} new", use_container_width=True):
                    con = get_db_connection()
                    bar = st.progress(0)
                    to_enrich = unenriched[:20]
                    for idx, enr_item in enumerate(to_enrich):
                        ai = enrich_with_claude(anthropic_key, enr_item["title"], enr_item.get("summary", ""))
                        update_item_ai(con, enr_item["link"], ai)
                        bar.progress((idx + 1) / len(to_enrich))
                        time.sleep(0.5)
                    con.close()
                    st.success(f"Enriched {len(to_enrich)} items!")
                    st.rerun()
            with btn_col2:
                if missing_lt and st.button(f"📺 Add lower thirds ({min(len(missing_lt), 20)})", use_container_width=True):
                    con = get_db_connection()
                    bar = st.progress(0)
                    to_update = missing_lt[:20]
                    for idx, lt_item in enumerate(to_update):
                        ai = enrich_with_claude(anthropic_key, lt_item["title"], lt_item.get("summary", ""))
                        update_item_ai(con, lt_item["link"], ai)
                        bar.progress((idx + 1) / len(to_update))
                        time.sleep(0.5)
                    con.close()
                    st.success(f"Lower thirds added to {len(to_update)} items!")
                    st.rerun()

        active_filters = any([keyword, sentiment_filter != "All", sector_filter != "All", importance_filter != "All"])

        gulf_items = [i for i in items if classify_region(i) == "gulf"]
        us_items   = [i for i in items if classify_region(i) == "us"]

        def render_news_card(item, prefix):
            sentiment  = item.get("sentiment") or ""
            importance = item.get("importance") or ""
            sector     = item.get("sector") or ""
            tickers    = json.loads(item.get("tickers") or "[]")
            ai_summary = item.get("ai_summary") or item.get("summary", "")
            pub        = item.get("published", "")[:16]

            sent_class  = sentiment.lower() if sentiment in ["Bullish", "Bearish", "Neutral"] else "neutral"
            imp_class   = importance.lower() if importance in ["High", "Medium", "Low"] else "low"
            sector_icon = SECTOR_COLORS.get(sector, "⬜")

            ticker_html = " ".join(
                f'<span style="font-size:11px;background:var(--brand-soft);color:var(--brand);padding:2px 8px;border-radius:5px;font-weight:600">{html.escape(str(t))}</span>'
                for t in tickers
            ) if tickers else ""

            display_title = html.escape(item["title"])
            if keyword:
                display_title = re.sub(
                    f"({re.escape(html.escape(keyword))})",
                    r'<mark style="background:#fef08a">\1</mark>',
                    display_title, flags=re.IGNORECASE
                )

            card_border = "#16a34a" if sentiment == "Bullish" else "#dc2626" if sentiment == "Bearish" else "#cbd5e1"
            lower_third_val = item.get("lower_third", "") or ""

            if item.get("enriched"):
                sentiment_badge  = f'<span class="badge {sent_class}">{html.escape(sentiment)}</span>' if sentiment else ""
                importance_badge = f'<span class="badge {imp_class}">{html.escape(importance)}</span>' if importance else ""
                sector_text      = f'{sector_icon} {html.escape(sector)}' if sector else ""
                ticker_block     = f'<span style="margin-left:6px">{ticker_html}</span>' if ticker_html else ""
                meta_html        = f"{sentiment_badge}{importance_badge}{sector_text}{ticker_block}"
            else:
                meta_html = '<span style="font-size:11px;color:#94a3b8;font-style:italic">Not enriched yet</span>'

            # Only show lower third on enriched items with a real subtitle
            if item.get("enriched") and lower_third_val and lower_third_val.strip():
                lt_html = (
                    '<div class="lower-third-wrap" style="margin-top:10px;">'
                    '<div class="lt-eyebrow">Lower Third</div>'
                    '<div class="lt-bar">'
                    '<div class="lt-accent"></div>'
                    '<div class="lt-body">'
                    f'<p class="lt-headline">{display_title}</p>'
                    f'<p class="lt-sub">{html.escape(lower_third_val)}</p>'
                    '</div></div></div>'
                )
            else:
                lt_html = ""

            with st.container():
                st.markdown(f"""
                <div class="news-card" style="border-left: 3px solid {card_border}; border-radius: 0 10px 10px 0; margin-bottom: 4px;">
                  <div class="source-tag">{html.escape(item['country'])} {html.escape(item['source'])} · {pub}</div>
                  <div class="headline"><a href="{safe_url(item['link'])}" target="_blank">{display_title}</a></div>
                  <div class="summary">{html.escape(ai_summary[:200])}</div>
                  <div class="meta">{meta_html}</div>
                  {lt_html}
                </div>
                """, unsafe_allow_html=True)

                btn1, btn2, btn3, _ = st.columns([1, 1, 1, 1])
                iid = item['id']
                with btn1:
                    if st.button("✦ Headlines", key=f"{prefix}_hl_{iid}", use_container_width=True):
                        st.session_state["selected_item"] = item
                        st.session_state["generated_teaser"] = ""
                        st.session_state["generated_script"] = ""
                        st.session_state["generated_headlines"] = []
                        st.rerun()
                with btn2:
                    if st.button("✍️ Teaser", key=f"{prefix}_teaser_{iid}", use_container_width=True):
                        st.session_state["selected_item"] = item
                        st.session_state["generated_teaser"] = ""
                        st.session_state["generated_script"] = ""
                        st.session_state["generated_headlines"] = []
                        st.rerun()
                with btn3:
                    if st.button("🎬 Script", key=f"{prefix}_video_{iid}", use_container_width=True):
                        st.session_state["selected_item"] = item
                        st.session_state["generated_teaser"] = ""
                        st.session_state["generated_script"] = ""
                        st.session_state["generated_headlines"] = []
                        st.rerun()
                st.markdown("<div style='margin-bottom:12px;'></div>", unsafe_allow_html=True)

        tab_gulf, tab_us, tab_all = st.tabs([
            f"🌍 Gulf & MENA ({len(gulf_items)})",
            f"🇺🇸 US & Global ({len(us_items)})",
            f"📋 All ({len(items)})",
        ])
        with tab_gulf:
            if not gulf_items:
                st.info("No Gulf/MENA headlines yet. Scrape to populate.")
            for item in gulf_items:
                render_news_card(item, "gulf")
        with tab_us:
            if not us_items:
                st.info("No US/Global headlines yet. Scrape to populate.")
            for item in us_items:
                render_news_card(item, "us")
        with tab_all:
            st.caption(f"{len(items)} total · {len(gulf_items)} Gulf/MENA · {len(us_items)} US/Global")
            for item in items:
                render_news_card(item, "all")

# ── Detail / content generation panel ─────────────────────────────────────────
with col_detail:
    selected = st.session_state.get("selected_item")

    if not selected:
        st.markdown("### Content studio")
        st.markdown("Click **✦ Headlines**, **✍️ Teaser**, or **🎬 Script** on any headline to generate content here.")
    else:
        st.markdown("### Content studio")
        st.markdown(f"**{selected['title']}**")
        st.caption(f"{selected['source']} · {selected.get('published', '')[:16]}")
        st.markdown("---")

        tab_hl, tab_teaser, tab_script = st.tabs(["✦ Headlines", "✍️ Teaser", "🎬 Video script"])

        # ── Headlines tab ──────────────────────────────────────────────────────
        with tab_hl:
            if not ai_enabled:
                st.warning("Add your Anthropic API key in the sidebar to generate headlines.")
            else:
                st.caption("Generate 5 headline packages with broadcast lower-third subtitles.")
                if st.button("✦ Generate Headlines + Lower Thirds", type="primary"):
                    with st.spinner("Writing headline packages + lower thirds…"):
                        headlines = generate_headlines(anthropic_key, selected)
                        st.session_state["generated_headlines"] = headlines
                        # Also save the first lower third back to the DB card
                        if headlines and isinstance(headlines[0], dict):
                            lt = headlines[0].get("lower_third", "")
                            if lt:
                                con = get_db_connection()
                                con.execute(
                                    "UPDATE items SET lower_third=?, enriched=1 WHERE link=?",
                                    (lt, selected.get("link", ""))
                                )
                                con.commit()
                                con.close()
                    st.rerun()

                angles = ["Data-focused", "Market reaction", "Investor angle", "Impact-focused", "Broad audience"]
                for idx, pkg in enumerate(st.session_state["generated_headlines"]):
                    angle       = angles[idx] if idx < len(angles) else f"Variant {idx + 1}"
                    headline    = html.escape(pkg.get("headline", str(pkg)) if isinstance(pkg, dict) else str(pkg))
                    lower_third = html.escape(pkg.get("lower_third", "") if isinstance(pkg, dict) else "")
                    lt_html = (
                        f'<div class="lower-third-wrap">'
                        f'<div class="lt-eyebrow">Lower Third</div>'
                        f'<div class="lt-bar">'
                        f'<div class="lt-accent"></div>'
                        f'<div class="lt-body">'
                        f'<p class="lt-headline">{headline}</p>'
                        + (f'<p class="lt-sub">{lower_third}</p>' if lower_third else "")
                        + '</div></div></div>'
                    )
                    st.markdown(
                        f'<div style="background:rgba(245,158,11,0.04);border:1px solid rgba(245,158,11,0.15);'
                        f'border-radius:8px;padding:12px 14px;margin-bottom:14px;">'
                        f'<div class="lt-angle-tag">{angle}</div>'
                        + lt_html
                        + '</div>',
                        unsafe_allow_html=True
                    )

        # ── Teaser tab ─────────────────────────────────────────────────────────
        with tab_teaser:
            if not ai_enabled:
                st.warning("Add your Anthropic API key in the sidebar to generate teasers.")
            else:
                if st.button("Generate teaser", type="primary"):
                    with st.spinner("Writing teaser…"):
                        st.session_state["generated_teaser"] = generate_content(
                            anthropic_key, "teaser", selected
                        )
                    st.rerun()
                if st.session_state["generated_teaser"]:
                    st.markdown(f'<div class="content-box">{html.escape(st.session_state["generated_teaser"])}</div>',
                                unsafe_allow_html=True)
                    char_count = len(st.session_state["generated_teaser"])
                    st.caption(f"{char_count} characters {'✅' if char_count <= 240 else '⚠️ over 240'}")

        # ── Video script tab ───────────────────────────────────────────────────
        with tab_script:
            if not ai_enabled:
                st.warning("Add your Anthropic API key in the sidebar to generate video scripts.")
            else:
                if st.button("Generate video script", type="primary"):
                    with st.spinner("Writing 60-second script…"):
                        st.session_state["generated_script"] = generate_content(
                            anthropic_key, "script", selected
                        )
                    st.rerun()
                if st.session_state["generated_script"]:
                    st.markdown(f'<div class="content-box">{html.escape(st.session_state["generated_script"])}</div>',
                                unsafe_allow_html=True)
                    word_count = len(st.session_state["generated_script"].split())
                    st.caption(f"~{word_count} words · approx {word_count // 130 + 1} min read aloud")
