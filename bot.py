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
# ✅ PASTE HERE (or leave empty and use GitHub Secrets)
# ============================================================
BOT_TOKEN = "8386226585:AAFamfLZ38bW44RXtWfOqBeejIYZiO5zP28"      # e.g. "123456789:AA...."
CHANNEL_ID = "-1003554679496"     # e.g. -1001234567890  (can be int or string)

# If you prefer GitHub Secrets, leave above empty and set:
# Secrets names: BOT_TOKEN and CHANNEL_ID
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
# ✅ YOUR NEW RULE: Minimum 1 VERIFIED source required
# ============================================================
MIN_VERIFIED_SOURCES = int(os.getenv("MIN_VERIFIED_SOURCES", "1"))

# Show exactly 2 source links in the post
TOTAL_SOURCES_TO_SHOW = int(os.getenv("TOTAL_SOURCES_TO_SHOW", "2"))

# ✅ Now fallback is allowed to fill Source 2 if needed
ALLOW_FALLBACK_SOURCES = os.getenv("ALLOW_FALLBACK_SOURCES", "true").lower() == "true"

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
# VERIFIED DOMAINS (ALLOWLIST)
# Add more trusted sites if you want higher "verified" hit-rate
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

def safe_html(text: str) -> str:
    # Prevent Telegram HTML parsing errors
    return html.escape(text or "")

def get_domain(url: str) -> str:
    try:
        u = re.sub(r"^https?://", "", url.strip())
        domain = u.split("/")[0].lower().replace("www.", "")
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

# ============================================================
# GDELT (Free global news index) – used to find extra coverage
# ============================================================
def gdelt_sources_any(query: str, max_needed: int = 10):
    """
    Returns ANY source URLs (fallback pool).
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
            if u and u.startswith("http") and u not in urls:
                urls.append(u)
            if len(urls) >= max_needed:
                break
    except Exception:
        pass
    return urls

def gdelt_sources_verified(query: str, max_needed: int = 10):
    """
    Returns VERIFIED source URLs only (filtered by allowlist).
    """
    urls = []
    for u in gdelt_sources_any(query, max_needed=50):
        if is_verified(u) and u not in urls:
            urls.append(u)
        if len(urls) >= max_needed:
            break
    return urls

# ============================================================
# SOURCES: require at least 1 verified, show 2 total
# ============================================================
def ensure_sources(entry, total_needed: int = 2):
    title = strip_html(entry.get("title", ""))
    link = entry.get("link", "")

    verified = []
    fallback = []

    # 1) Entry link first
    if link:
        if is_verified(link):
            verified.append(link)
        else:
            fallback.append(link)

    # 2) Verified from GDELT (title + industry context)
    query = f"{title} retail fashion textile"
    for u in gdelt_sources_verified(query=query, max_needed=15):
        if u not in verified:
            verified.append(u)
        if len(verified) >= total_needed:
            break

    # 3) If still short, broaden query
    if len(verified) < 1:
        for u in gdelt_sources_verified(query=title, max_needed=20):
            if u not in verified:
                verified.append(u)
            if len(verified) >= total_needed:
                break

    # Start sources list with verified sources
    sources = verified[:total_needed]

    # Fallback fill (Source 2) if allowed
    if len(sources) < total_needed and ALLOW_FALLBACK_SOURCES:
        # Pull additional candidates from GDELT (any)
        any_urls = gdelt_sources_any(query=query, max_needed=20) + gdelt_sources_any(query=title, max_needed=20)
        for u in any_urls:
            if u not in fallback and u not in sources:
                fallback.append(u)

        for u in fallback:
            if u not in sources:
                sources.append(u)
            if len(sources) >= total_needed:
                break

    sources = sources[:total_needed]
    verified_count = sum(1 for s in sources if is_verified(s))
    return sources, verified_count

def format_sources(sources):
    # Two lines: Source 1 and Source 2
    lines = []
    for i, s in enumerate(sources, start=1):
        tag = "✅ Verified" if is_verified(s) else "➕ Additional"
        lines.append(f"Source {i} ({tag}): {html.escape(s)}")
    return "\n".join(lines)

# ============================================================
# POST BUILDERS (LinkedIn-style, professional, emoji rich)
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
        "• This may affect sourcing strategy, vendor negotiations, lead times, and cost pressure.\n"
        "• Watch inventory cycles, pricing actions, and channel mix (store vs online).\n"
        "• The next 30–90 days will reveal execution via KPIs (margin, OTIF, returns, sell-through)."
    )

    insight = (
        "✅ <b>Conclusion (short insight):</b>\n"
        "• Strong execution improves competitiveness; weak rollout can hit margin and customer trust.\n"
        "• Best move: test fast → measure hard → scale what works."
    )

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
        "🔗 <b>Sources (min 1 verified):</b>",
        format_sources(sources),
        cta,
        hashtags
    ])
    return post

def build_breaking_post(entry, sources):
    title = safe_html(strip_html(entry.get("title", "Breaking Update")))
    summary = safe_html(strip_html(entry.get("summary", "")))

    if len(summary) > 450:
        summary = summary[:450].rstrip() + "..."

    post = "\n\n".join([
        "🚨🔥 <b>BREAKING (Retail / Fashion / Textile)</b> 🔥🚨",
        f"🧵 <b>{title}</b>",
        f"📌 {summary}",
        "🔗 <b>Sources (min 1 verified):</b>",
        format_sources(sources),
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

    # ✅ Your new rule: at least 1 verified source required
    if verified_count < MIN_VERIFIED_SOURCES:
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
