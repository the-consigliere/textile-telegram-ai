import os
import re
import json
import time
import feedparser
import requests
from bs4 import BeautifulSoup
import telegram

# ===================== TELEGRAM CONFIG =====================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")

if not BOT_TOKEN or not CHANNEL_ID:
    raise ValueError("Missing BOT_TOKEN or CHANNEL_ID. Add them in GitHub → Settings → Secrets → Actions.")

bot = telegram.Bot(token=BOT_TOKEN)

# ===================== RUN MODES =====================
# regular  = full LinkedIn-style post (runs every 2 hours)
# breaking = short urgent post (runs every 15 minutes)
RUN_MODE = os.getenv("RUN_MODE", "regular").lower()

# Source requirements
ALLOW_FALLBACK_SOURCES = os.getenv("ALLOW_FALLBACK_SOURCES", "true").lower() == "true"
MIN_VERIFIED_SOURCES = int(os.getenv("MIN_VERIFIED_SOURCES", "1"))  # recommended: 1

# Breaking logic knobs
BREAKING_KEYWORDS = [
    "breaking", "urgent", "exclusive", "acquire", "acquires", "acquisition", "merger",
    "ipo", "bankruptcy", "funding", "raises", "layoff", "layoffs", "security breach",
    "recall", "ban", "probe", "lawsuit", "regulator", "strike", "shutdown"
]
BREAKING_MAX_AGE_HOURS = int(os.getenv("BREAKING_MAX_AGE_HOURS", "6"))
BREAKING_SCAN_PER_FEED = int(os.getenv("BREAKING_SCAN_PER_FEED", "12"))

# ===================== RSS FEEDS =====================
RETAIL_FASHION_FEEDS = [
    "https://www.fibre2fashion.com/rss/news.xml",
    "https://www.just-style.com/feed/",
    "https://www.apparelresources.com/feed/",
    "https://www.retaildive.com/feeds/news/",
    "https://www.fashionunited.com/rss/news"
]

TECH_FEEDS = [
    "https://techcrunch.com/feed/",
    "https://www.theverge.com/rss/index.xml",
    "https://www.wired.com/feed/rss",
    "https://arstechnica.com/feed/"
]

RSS_FEEDS = [
    ("Retail/Fashion", RETAIL_FASHION_FEEDS),
    ("Tech", TECH_FEEDS)
]

# ===================== VERIFIED DOMAINS (ALLOWLIST) =====================
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
    "apparelresources.com",

    "techcrunch.com",
    "theverge.com",
    "wired.com",
    "arstechnica.com",
    "zdnet.com",
    "engadget.com"
}

CACHE_FILE = "posted.json"

# ===================== HELPERS =====================
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

# ===================== GDELT SEARCH =====================
def gdelt_verified_sources(query: str, max_needed: int = 5):
    """
    Returns verified source URLs only (filtered by allowlist).
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

def gdelt_any_sources(query: str, max_needed: int = 10):
    """
    Returns any source URLs (not filtered) for fallback.
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
            if u and u.startswith("http"):
                if u not in urls:
                    urls.append(u)
            if len(urls) >= max_needed:
                break
    except Exception:
        pass
    return urls

# ===================== SOURCE SELECTION =====================
def ensure_sources(category: str, entry, total_needed: int = 3):
    """
    Returns (sources_list, verified_count).
    - Aim for total_needed sources.
    - Prefer verified sources.
    - If ALLOW_FALLBACK_SOURCES = true, fill remaining with additional (non-verified) sources.
    - Enforces MIN_VERIFIED_SOURCES in main().
    """
    title = strip_html(entry.get("title", ""))
    link = entry.get("link", "")

    verified = []
    others = []

    # Entry link first
    if link:
        if is_verified(link):
            verified.append(link)
        else:
            others.append(link)

    # Verified from GDELT using category context
    query = f"{title} {category}"
    for u in gdelt_verified_sources(query=query, max_needed=10):
        if u not in verified:
            verified.append(u)
        if len(verified) >= total_needed:
            break

    # Broader verified search
    if len(verified) < total_needed:
        for u in gdelt_verified_sources(query=title, max_needed=15):
            if u not in verified:
                verified.append(u)
            if len(verified) >= total_needed:
                break

    sources = verified[:total_needed]

    # Fallback to any sources (still real links) so you always get 3 lines
    if len(sources) < total_needed and ALLOW_FALLBACK_SOURCES:
        # Add more candidates from GDELT (any domains)
        any_urls = gdelt_any_sources(query=query, max_needed=15) + gdelt_any_sources(query=title, max_needed=15)

        # Merge others list
        for u in any_urls:
            if u not in verified and u not in others:
                others.append(u)

        for u in others:
            if u not in sources:
                sources.append(u)
            if len(sources) >= total_needed:
                break

    sources = sources[:total_needed]
    verified_count = sum(1 for s in sources if is_verified(s))
    return sources, verified_count

def format_sources(sources):
    lines = []
    for i, s in enumerate(sources, start=1):
        tag = "✅ Verified" if is_verified(s) else "➕ Additional"
        lines.append(f"Source {i} ({tag}): {s}")
    return "\n".join(lines)

# ===================== CONTENT BUILDERS =====================
def build_linkedin_style_post(category: str, entry, sources: list):
    title = strip_html(entry.get("title", "Breaking Update"))
    summary = strip_html(entry.get("summary", ""))

    if len(summary) > 900:
        summary = summary[:900].rstrip() + "..."

    topic = "🌍 Retail & Fashion" if category == "Retail/Fashion" else "💻 Tech"

    hook = f"🚨✨ *{topic} Pulse:* {title} ✨🚨"

    what = (
        "🧾 *What’s happening?*\n"
        f"• {summary}"
    )

    deep = (
        "🔎 *Deeper take (why it matters):*\n"
        "• This suggests a strategic shift with ripple effects across pricing, supply chain, and consumer demand.\n"
        "• Watch for who benefits: brands, retailers, suppliers — and where margins get pressured.\n"
        "• The next 30–90 days (execution + KPIs) will reveal whether this move sticks."
        if category == "Retail/Fashion" else
        "🔎 *Deeper take (why it matters):*\n"
        "• This shows how fast the stack is evolving — product choices and ecosystem moves matter.\n"
        "• Watch adoption signals: pilots, developer traction, and real performance/security benchmarks.\n"
        "• The next 30–90 days (roadmap + releases) will prove real-world value."
    )

    insight = (
        "✅ *Quick insight (in short):*\n"
        "• Strong execution can improve positioning and efficiency.\n"
        "• Winners will measure outcomes tightly and move faster than competitors.\n"
        "• Track: margin impact + customer response + operational stability."
        if category == "Retail/Fashion" else
        "✅ *Quick insight (in short):*\n"
        "• Winners will ship faster, prove ROI, and reduce deployment risk.\n"
        "• Trust (security + reliability) will drive adoption.\n"
        "• Track: measurable ROI + scalability + compliance."
    )

    src_lines = format_sources(sources)

    cta = (
        "💬 *Your take?*\n"
        "If you were leading strategy here—what would you do next? What risks or opportunities do you see?"
    )

    hashtags = (
        "#Retail #Fashion #Apparel #Textiles #BrandStrategy #Ecommerce #SupplyChain #RetailTech #ConsumerTrends\n"
        "#Technology #AI #Cloud #CyberSecurity #ProductStrategy #Innovation #DigitalTransformation"
    )

    post = "\n\n".join([hook, what, deep, insight, "🔗 *Sources:*", src_lines, cta, hashtags])
    return post

def build_breaking_post(category: str, entry, sources: list):
    title = strip_html(entry.get("title", "Breaking Update"))
    summary = strip_html(entry.get("summary", ""))

    if len(summary) > 450:
        summary = summary[:450].rstrip() + "..."

    src_lines = format_sources(sources)

    post = (
        f"🚨🔥 *BREAKING NEWS* 🔥🚨\n\n"
        f"🧠 *{title}*\n\n"
        f"📌 {summary}\n\n"
        f"🔗 *Sources:*\n{src_lines}\n\n"
        f"💬 *Quick question:* What’s your take—opportunity or risk?\n\n"
        f"#BreakingNews #Retail #Fashion #Tech #Business"
    )
    return post

# ===================== FEED PICKERS =====================
def pick_latest_entry():
    latest = None
    latest_ts = 0
    latest_category = None

    for category, feeds in RSS_FEEDS:
        for feed_url in feeds:
            feed = feedparser.parse(feed_url)
            if not feed.entries:
                continue
            for e in feed.entries[:10]:
                ts = entry_timestamp(e)
                if ts > latest_ts and e.get("title") and e.get("link"):
                    latest = e
                    latest_ts = ts
                    latest_category = category
    return latest_category, latest

def find_breaking_candidate():
    now = int(time.time())
    max_age = BREAKING_MAX_AGE_HOURS * 3600

    for category, feeds in RSS_FEEDS:
        for feed_url in feeds:
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
                    return category, e

    return None, None

# ===================== MAIN =====================
def main():
    cache = load_cache()

    if RUN_MODE == "breaking":
        category, entry = find_breaking_candidate()
        if not entry:
            print("No breaking candidate found.")
            return
    else:
        category, entry = pick_latest_entry()
        if not entry:
            print("No entries found.")
            return

    uid = entry.get("id") or entry.get("link") or entry.get("title")
    if cache.get(uid):
        print("Already posted. Skipping.")
        return

    sources, verified_count = ensure_sources(category, entry, total_needed=3)

    # Trust gate: must have at least MIN_VERIFIED_SOURCES verified sources
    if verified_count < MIN_VERIFIED_SOURCES:
        print(f"Not enough verified sources ({verified_count}/{MIN_VERIFIED_SOURCES}). Skipping item.")
        return

    if RUN_MODE == "breaking":
        post = build_breaking_post(category, entry, sources)
    else:
        post = build_linkedin_style_post(category, entry, sources)

    bot.send_message(
        chat_id=CHANNEL_ID,
        text=post,
        parse_mode="Markdown",
        disable_web_page_preview=False
    )

    cache[uid] = {
        "title": strip_html(entry.get("title", "")),
        "time": int(time.time()),
        "category": category,
        "mode": RUN_MODE
    }
    save_cache(cache)

    print("Posted:", cache[uid]["title"], "| mode:", RUN_MODE)

if __name__ == "__main__":
    main()
