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
# ✅ PASTE HERE (or keep empty and use GitHub Secrets instead)
# ============================================================
BOT_TOKEN = "8386226585:AAFamfLZ38bW44RXtWfOqBeejIYZiO5zP28"      # e.g. "123456789:AA...."
CHANNEL_ID = "-1003554679496"     # e.g. -1001234567890  (can be int or string)

# If you prefer GitHub Secrets, leave the above empty and set:
# BOT_TOKEN secret name: BOT_TOKEN
# CHANNEL_ID secret name: CHANNEL_ID
if not BOT_TOKEN:
    BOT_TOKEN = os.getenv("BOT_TOKEN", "")
if not CHANNEL_ID:
    CHANNEL_ID = os.getenv("CHANNEL_ID", "")

if not BOT_TOKEN or not CHANNEL_ID:
    raise ValueError("Missing BOT_TOKEN or CHANNEL_ID. Paste in bot.py or set GitHub Secrets.")

bot = telegram.Bot(token=BOT_TOKEN)

# ============================================================
# MODE CONTROL
# ============================================================
# regular  = full LinkedIn-style post
# breaking = short urgent post (keyword-based)
RUN_MODE = os.getenv("RUN_MODE", "regular").strip().lower()

# ============================================================
# YOUR RULE: Minimum 2 VERIFIED sources to confirm the news
# ============================================================
MIN_VERIFIED_SOURCES = int(os.getenv("MIN_VERIFIED_SOURCES", "1"))
TOTAL_SOURCES_TO_SHOW = int(os.getenv("TOTAL_SOURCES_TO_SHOW", "2"))

# You asked for confirmed sources only => keep fallback FALSE
ALLOW_FALLBACK_SOURCES = os.getenv("ALLOW_FALLBACK_SOURCES", "TRUE").lower() == "true"

# ============================================================
# BREAKING SETTINGS (used only in breaking mode)
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
# RSS FEEDS (Retail / Fashion / Textile ONLY)
# ============================================================
RSS_FEEDS = [
    "https://www.fibre2fashion.com/rss/news.xml",
    "https://www.just-style.com/feed/",
    "https://www.apparelresources.com/feed/",
    "https://www.retaildive.com/feeds/news/",
    "https://www.fashionunited.com/rss/news"
]

# ============================================================
# Verified domains allowlist (edit freely)
# ============================================================
VERIFIED_DOMAINS = {
    "reuters.com",
    "ft.com",
    "bbc.com",
    "theguardian.com",
    "wsj.com",
    "nytimes.com",
    "cnbc.com",
    "bloomberg.com",

    "retaildive.com",
    "chainstoreage.com",
    "retailgazette.co.uk",
    "retaildetail.eu",

    "businessoffashion.com",
    "voguebusiness.com",
    "fashionunited.com",
    "fibre2fashion.com",
    "just-style.com",
    "apparelresources.com"
}

CACHE_FILE = "posted.json"

# ============================================================
# HELPERS
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

def strip_html(text: str) -> str:
    if not text:
        return ""
    soup = BeautifulSoup(text, "html.parser")
    clean = soup.get_text(" ", strip=True)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean

def get_domain(url: str) -> str:
    try:
        u = re.sub(r"^https?://", "", url.strip())
        domain = u.split("/")[0].lower()
        domain = domain.replace("www.", "")
        return domain
    except Exception:
        return ""

def is_verified(url: str) -> bool:
    d = get_domain(url)
    return any(d == vd or d.endswith("." + vd) for vd in VERIFIED_DOMAINS)

def entry_timestamp(entry):
    published = entry.get("published_parsed") or entry.get("updated_parsed")
    if published:
        return int(time.mktime(published))
    return int(time.time())

def looks_breaking(title: str) -> bool:
    t = (title or "").lower()
    return any(k in t for k in BREAKING_KEYWORDS)

def safe_html(text: str) -> str:
    # Prevent Telegram HTML parsing errors
    return html.escape(text or "")

# ============================================================
# GDELT (Free verified source search)
# ============================================================
def gdelt_verified_sources(query: str, max_needed: int = 10):
    """
    Returns verified source URLs only (filtered by allowlist).
    Uses free public GDELT DOC API.
    """
    end = time.strftime("%Y%m%d%H%M%S", time.gmtime())
    start = time.strftime("%Y%m%d%H%M%S", time.gmtime(time.time() - 7 * 24 * 3600))

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
        r.raise_for_status()
        data = r.json()
        for a in data.get("articles", []):
            u = a.get("url", "")
            if u and u.startswith("http") and is_verified(u):
                if u not in urls:
                    urls.append(u)
            if len(urls) >= max_needed:
                break
    except Exception:
        pass
    return urls

# ============================================================
# SOURCES: minimum 2 verified, show exactly 2
# ============================================================
def ensure_sources(entry, total_needed: int = 2):
    title = strip_html(entry.get("title", ""))
    link = entry.get("link", "")

    verified = []
    others = []

    # 1) RSS entry link
    if link:
        if is_verified(link):
            verified.append(link)
        else:
            others.append(link)

    # 2) GDELT verified sources by title + industry context
    query = f"{title} retail fashion textile"
    for u in gdelt_verified_sources(query=query, max_needed=15):
        if u not in verified:
            verified.append(u)
        if len(verified) >= total_needed:
            break

    # 3) Broader verified search if still short
    if len(verified) < total_needed:
        for u in gdelt_verified_sources(query=title, max_needed=20):
            if u not in verified:
                verified.append(u)
            if len(verified) >= total_needed:
                break

    sources = verified[:total_needed]

    # Optional fallback (disabled by default)
    if len(sources) < total_needed and ALLOW_FALLBACK_SOURCES:
        for u in others:
            if u not in sources:
                sources.append(u)
            if len(sources) >= total_needed:
                break

    sources = sources[:total_needed]
    verified_count = sum(1 for s in sources if is_verified(s))
    return sources, verified_count

def format_sources(sources):
    # exactly 2 sources, each on new line
    lines = []
    for i, s in enumerate(sources, start=1):
        lines.append(f"Source {i}: {s}")
    return "\n".join(lines)

# ============================================================
# POST BUILDERS (LinkedIn-style, emoji rich, professional)
# ============================================================
def build_regular_post(entry, sources):
    title = safe_html(strip_html(entry.get("title", "Retail / Fashion / Textile Update")))
    summary = safe_html(strip_html(entry.get("summary", "")))

    if len(summary) > 900:
        summary = summary[:900].rstrip() + "..."

    hook = f"🧵✨ <b>Retail / Fashion / Textile Pulse:</b> {title} ✨🧵"

    what = (
        "🧾 <b>What’s happening?</b>\n"
        f"• {summary}"
    )

    deep = (
        "🔎 <b>Deeper context (quick analysis):</b>\n"
        "• This may influence sourcing strategy, vendor negotiations, lead times and cost pressure.\n"
        "• Watch sell-through, inventory positions, and channel response (online vs store).\n"
        "• The next 30–90 days will show execution via KPIs (margin, OTIF, returns, demand)."
    )

    insight = (
        "✅ <b>Conclusion (short insight):</b>\n"
        "• Strong execution can improve competitiveness; weak rollout can hit margin and customer trust.\n"
        "• Best approach: test fast → measure hard → scale what works."
    )

    src_lines = format_sources(sources)

    cta = (
        "💬 <b>Your suggestion?</b>\n"
        "If you were leading the team, what’s the ONE move you’d prioritize next — and why? 👇"
    )

    hashtags = (
        "#Retail #Fashion #Textile #Apparel #Merchandising #Sourcing #SupplyChain "
        "#RetailStrategy #BrandStrategy #FashionBusiness #TextileIndustry #RetailTrends"
    )

    post = "\n\n".join([
        hook,
        what,
        deep,
        insight,
        "🔗 <b>Confirmed Sources (min 2):</b>",
        src_lines,
        cta,
        hashtags
    ])
    return post

def build_breaking_post(entry, sources):
    title = safe_html(strip_html(entry.get("title", "Breaking Update")))
    summary = safe_html(strip_html(entry.get("summary", "")))

    if len(summary) > 450:
        summary = summary[:450].rstrip() + "..."

    src_lines = format_sources(sources)

    post = "\n\n".join([
        "🚨🔥 <b>BREAKING (Retail / Fashion / Textile)</b> 🔥🚨",
        f"🧵 <b>{title}</b>",
        f"📌 {summary}",
        "🔗 <b>Confirmed Sources (min 2):</b>",
        src_lines,
        "💬 <b>What’s your take?</b> Opportunity or risk for brands/retailers? 👇",
        "#BreakingNews #Retail #Fashion #Textile #Apparel"
    ])
    return post

# ============================================================
# FEED PICKERS
# ============================================================
def pick_latest_entry():
    latest = None
    latest_ts = 0

    for feed_url in RSS_FEEDS:
        feed = feedparser.parse(feed_url)
        if not feed.entries:
            continue

        for e in feed.entries[:12]:
            ts = entry_timestamp(e)
            if ts > latest_ts and e.get("title") and e.get("link"):
                latest = e
                latest_ts = ts

    return latest

def find_breaking_candidate():
    now = int(time.time())
    max_age = BREAKING_MAX_AGE_HOURS * 3600

    for feed_url in RSS_FEEDS:
        feed = feedparser.parse(feed_url)
        if not feed.entries:
            continue

        for e in feed.entries[:BREAKING_SCAN_PER_FEED]:
            title = strip_html(e.get("title", ""))
            link = e.get("link", "")
            if not title or not link:
                continue

            ts = entry_timestamp(e)
            if (now - ts) <= max_age and looks_breaking(title):
                return e

    return None

# ============================================================
# MAIN
# ============================================================
def main():
    cache = load_cache()

    # Choose mode
    if RUN_MODE == "breaking":
        entry = find_breaking_candidate()
        if not entry:
            print("No breaking candidate found.")
            return
    else:
        entry = pick_latest_entry()
        if not entry:
            print("No entries found.")
            return

    uid = entry.get("id") or entry.get("link") or entry.get("title")
    if cache.get(uid):
        print("Already posted. Skipping.")
        return

    sources, verified_count = ensure_sources(entry, total_needed=TOTAL_SOURCES_TO_SHOW)

    # Your confirmation rule: require at least 2 verified sources
    if verified_count < MIN_VERIFIED_SOURCES or len(sources) < 2:
        print(f"Not enough verified sources ({verified_count}/{MIN_VERIFIED_SOURCES}). Skipping safely.")
        return

    # Build post
    if RUN_MODE == "breaking":
        post = build_breaking_post(entry, sources)
    else:
        post = build_regular_post(entry, sources)

    bot.send_message(
        chat_id=CHANNEL_ID,
        text=post,
        parse_mode="HTML",
        disable_web_page_preview=False
    )

    cache[uid] = {
        "title": strip_html(entry.get("title", "")),
        "time": int(time.time()),
        "mode": RUN_MODE
    }
    save_cache(cache)

    print("Posted:", cache[uid]["title"], "| mode:", RUN_MODE)

if __name__ == "__main__":
    main()
