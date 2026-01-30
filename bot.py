import os
import re
import json
import time
import html
import feedparser
import requests
from bs4 import BeautifulSoup
import telegram

# ============================================================
# 🔐 CREDENTIALS (USE GITHUB SECRETS)
# ============================================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8386226585:AAFamfLZ38bW44RXtWfOqBeejIYZiO5zP28")
CHANNEL_ID = os.getenv("CHANNEL_ID", "-1003554679496")

if not BOT_TOKEN or not CHANNEL_ID:
    raise ValueError("Missing BOT_TOKEN or CHANNEL_ID. Set them as GitHub Secrets.")

bot = telegram.Bot(token=BOT_TOKEN)

# ============================================================
# MODE CONTROL
# regular  = full LinkedIn-style post
# breaking = short urgent post
# ============================================================
RUN_MODE = os.getenv("RUN_MODE", "regular").strip().lower()

# ============================================================
# SOURCE RULES
# ============================================================
MIN_VERIFIED_SOURCES = int(os.getenv("MIN_VERIFIED_SOURCES", "1"))
TOTAL_SOURCES_TO_SHOW = int(os.getenv("TOTAL_SOURCES_TO_SHOW", "2"))
ALLOW_FALLBACK_SOURCES = os.getenv("ALLOW_FALLBACK_SOURCES", "true").lower() == "true"

# ============================================================
# BREAKING MODE SETTINGS
# ============================================================
BREAKING_KEYWORDS = [
    "breaking", "urgent", "exclusive",
    "acquire", "acquires", "acquisition", "merger",
    "ipo", "bankruptcy", "funding", "raises",
    "layoff", "layoffs", "recall", "ban",
    "probe", "lawsuit", "regulator", "strike",
    "shutdown"
]

BREAKING_MAX_AGE_HOURS = int(os.getenv("BREAKING_MAX_AGE_HOURS", "6"))
BREAKING_SCAN_PER_FEED = int(os.getenv("BREAKING_SCAN_PER_FEED", "12"))

# ============================================================
# RSS FEEDS (RETAIL / FASHION / TEXTILE)
# ============================================================
RSS_FEEDS = [
    "https://www.fibre2fashion.com/rss/news.xml",
    "https://www.just-style.com/feed/",
    "https://www.apparelresources.com/feed/",
    "https://www.retaildive.com/feeds/news/",
    "https://www.fashionunited.com/rss/news"
]

# ============================================================
# VERIFIED DOMAINS (ALLOWLIST)
# ============================================================
VERIFIED_DOMAINS = {
    "reuters.com", "ft.com", "bbc.com", "theguardian.com",
    "wsj.com", "nytimes.com", "cnbc.com", "bloomberg.com",

    "retaildive.com", "chainstoreage.com", "retailgazette.co.uk",
    "retaildetail.eu",

    "businessoffashion.com", "voguebusiness.com",
    "fashionunited.com", "fibre2fashion.com",
    "just-style.com", "apparelresources.com"
}

CACHE_FILE = "posted.json"

# ============================================================
# CACHE HELPERS
# ============================================================
def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_cache(cache):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

# Ensure cache exists on first run
if not os.path.exists(CACHE_FILE):
    save_cache({})

# ============================================================
# TEXT HELPERS
# ============================================================
def strip_html(text):
    if not text:
        return ""
    soup = BeautifulSoup(text, "html.parser")
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True))

def safe_html(text):
    return html.escape(text or "")

def get_domain(url):
    try:
        return re.sub(r"^https?://", "", url).split("/")[0].replace("www.", "").lower()
    except Exception:
        return ""

def is_verified(url):
    d = get_domain(url)
    return any(d == vd or d.endswith("." + vd) for vd in VERIFIED_DOMAINS)

def entry_timestamp(entry):
    p = entry.get("published_parsed") or entry.get("updated_parsed")
    return int(time.mktime(p)) if p else int(time.time())

def looks_breaking(title):
    t = (title or "").lower()
    return any(k in t for k in BREAKING_KEYWORDS)

# ============================================================
# GDELT SOURCE DISCOVERY
# ============================================================
def gdelt_sources_any(query, max_needed=10):
    end = time.strftime("%Y%m%d%H%M%S", time.gmtime())
    start = time.strftime("%Y%m%d%H%M%S", time.gmtime(time.time() - 7 * 86400))

    params = {
        "query": query,
        "mode": "ArtList",
        "format": "json",
        "maxrecords": 50,
        "sort": "HybridRel",
        "startdatetime": start,
        "enddatetime": end
    }

    urls = []
    try:
        r = requests.get("https://api.gdeltproject.org/api/v2/doc/doc", params=params, timeout=20)
        for a in r.json().get("articles", []):
            u = a.get("url")
            if u and u.startswith("http") and u not in urls:
                urls.append(u)
            if len(urls) >= max_needed:
                break
    except Exception:
        pass
    return urls

def gdelt_sources_verified(query, max_needed=10):
    return [u for u in gdelt_sources_any(query, 50) if is_verified(u)][:max_needed]

# ============================================================
# SOURCE ENFORCEMENT
# ============================================================
def ensure_sources(entry):
    title = strip_html(entry.get("title", ""))
    link = entry.get("link", "")

    verified, fallback = [], []

    if link:
        (verified if is_verified(link) else fallback).append(link)

    query = f"{title} retail fashion textile"

    for u in gdelt_sources_verified(query):
        if u not in verified:
            verified.append(u)

    sources = verified[:TOTAL_SOURCES_TO_SHOW]

    if len(sources) < TOTAL_SOURCES_TO_SHOW and ALLOW_FALLBACK_SOURCES:
        for u in gdelt_sources_any(query):
            if u not in sources:
                sources.append(u)
            if len(sources) >= TOTAL_SOURCES_TO_SHOW:
                break

    verified_count = sum(1 for s in sources if is_verified(s))
    return sources[:TOTAL_SOURCES_TO_SHOW], verified_count

def format_sources(sources):
    lines = []
    for i, s in enumerate(sources, 1):
        tag = "✅ Verified" if is_verified(s) else "➕ Additional"
        lines.append(f"Source {i} ({tag}): {safe_html(s)}")
    return "\n".join(lines)

# ============================================================
# POST BUILDERS
# ============================================================
def build_breaking_post(entry, sources):
    title = safe_html(strip_html(entry.get("title")))
    summary = safe_html(strip_html(entry.get("summary")))[:450]

    return "\n\n".join([
        "🚨🔥 <b>BREAKING — Retail / Fashion / Textile</b> 🔥🚨",
        f"🧵 <b>{title}</b>",
        f"📌 {summary}",
        "🔗 <b>Sources (min 1 verified):</b>",
        format_sources(sources),
        "#BreakingNews #Retail #Fashion #Textile"
    ])

# ============================================================
# FEED SELECTION
# ============================================================
def find_breaking_candidate():
    now = int(time.time())
    for url in RSS_FEEDS:
        feed = feedparser.parse(url)
        for e in feed.entries[:BREAKING_SCAN_PER_FEED]:
            if looks_breaking(e.get("title", "")) and (now - entry_timestamp(e)) <= BREAKING_MAX_AGE_HOURS * 3600:
                return e
    return None

# ============================================================
# MAIN
# ============================================================
def main():
    cache = load_cache()

    entry = find_breaking_candidate() if RUN_MODE == "breaking" else None
    if not entry:
        print("No eligible breaking news.")
        return

    uid = entry.get("id") or entry.get("link")
    if uid in cache:
        print("Already posted.")
        return

    sources, verified_count = ensure_sources(entry)
    if verified_count < MIN_VERIFIED_SOURCES:
        print("Not enough verified sources.")
        return

    post = build_breaking_post(entry, sources)

    bot.send_message(
        chat_id=CHANNEL_ID,
        text=post,
        parse_mode="HTML",
        disable_web_page_preview=False
    )

    cache[uid] = {"time": int(time.time()), "mode": RUN_MODE}
    save_cache(cache)

    print("Posted:", strip_html(entry.get("title")))

if __name__ == "__main__":
    main()

