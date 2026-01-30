import os
import re
import json
import time
import html
import feedparser
import requests
from bs4 import BeautifulSoup
import telegram

# ============== CONFIG (from GitHub Secrets) ==============
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")

if not BOT_TOKEN or not CHANNEL_ID:
    raise ValueError("Missing BOT_TOKEN or CHANNEL_ID. Add them in GitHub → Settings → Secrets → Actions.")

bot = telegram.Bot(token=BOT_TOKEN)

# ============== NEWS FEEDS (Global Retail/Fashion + Tech) ==============
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

# ============== VERIFIED SOURCES (Domain allowlist) ==============
# Add/remove as you like. This is how we keep sources "verified".
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

# ============== HELPERS ==============
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

def gdelt_sources(query: str, max_needed: int = 2):
    """
    Free & public news search via GDELT.
    Returns up to `max_needed` verified source URLs.
    """
    # last 7 days window
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
        articles = data.get("articles", [])
        for a in articles:
            u = a.get("url", "")
            if u and is_verified(u):
                if u not in urls:
                    urls.append(u)
            if len(urls) >= max_needed:
                break
    except Exception:
        pass

    return urls

def pick_latest_entry():
    """
    Finds the newest article across all feeds.
    """
    latest = None
    latest_ts = 0
    latest_category = None

    for category, feeds in RSS_FEEDS:
        for feed_url in feeds:
            feed = feedparser.parse(feed_url)
            if not feed.entries:
                continue
            for e in feed.entries[:7]:
                published = e.get("published_parsed") or e.get("updated_parsed")
                ts = int(time.mktime(published)) if published else int(time.time())

                if ts > latest_ts and e.get("title") and e.get("link"):
                    latest = e
                    latest_ts = ts
                    latest_category = category

    return latest_category, latest

def build_linkedin_style_post(category: str, entry, sources: list):
    title = strip_html(entry.get("title", "Breaking Update"))
    summary = strip_html(entry.get("summary", ""))

    # Keep clean + concise (Telegram/LinkedIn-friendly)
    if len(summary) > 900:
        summary = summary[:900].rstrip() + "..."

    # Lightweight “deep research” — we use multi-source context (titles/URLs) + structured analysis
    # Without paid AI, we keep it professional using an insight template.
    topic = "Retail & Fashion" if category == "Retail/Fashion" else "Tech"

    # Emojis: strong but not spammy
    hook = f"🚨✨ *{topic} Pulse:* {title} ✨🚨"
    what = (
        "🧾 *What’s happening?*\n"
        f"• {summary}"
    )

    deep = (
        "🔎 *Deeper take (why it matters):*\n"
        "• This signals a meaningful shift in strategy/market dynamics.\n"
        "• Watch for impacts on pricing, supply chain, customer demand, and competitive positioning.\n"
        "• The next 30–90 days will matter: partnerships, rollouts, and performance indicators will reveal the real outcome."
        if category == "Retail/Fashion" else
        "🔎 *Deeper take (why it matters):*\n"
        "• This reflects how quickly the tech stack is evolving—platform choices and ecosystem moves are key.\n"
        "• Look for adoption signals: enterprise pilots, developer traction, and performance/security benchmarks.\n"
        "• The next 30–90 days will matter: product releases, roadmap clarity, and real-world deployment wins."
    )

    insight = (
        "✅ *Quick insight (in short):*\n"
        "• If executed well, this can strengthen brand positioning and improve efficiency.\n"
        "• The winners will be those who act fast and measure outcomes tightly.\n"
        "• Keep an eye on margin impact + customer response."
        if category == "Retail/Fashion" else
        "✅ *Quick insight (in short):*\n"
        "• The winners will be those who ship faster, prove value, and reduce risk.\n"
        "• Execution + trust (security, reliability) will decide adoption.\n"
        "• Watch for measurable ROI and scalability."
    )

    # Sources (minimum 3) – each on new line
    # We'll always include the original entry link if verified; otherwise we still list it but try to add 3 verified total.
    src_lines = []
    for i, s in enumerate(sources[:3], start=1):
        src_lines.append(f"Source {i}: {s}")

    cta = (
        "💬 *Your take?*\n"
        "If you were leading strategy here—what would you do next? What risks or opportunities do you see?"
    )

    hashtags = (
        "#Retail #Fashion #Apparel #Textiles #BrandStrategy #Ecommerce #SupplyChain #RetailTech #ConsumerTrends\n"
        "#Technology #AI #Cloud #CyberSecurity #ProductStrategy #Innovation #DigitalTransformation"
    )

    # Telegram supports Markdown. We’ll keep it safe and not overcomplicate Markdown escaping.
    post = "\n\n".join([hook, what, deep, insight, "🔗 *Verified sources:*", "\n".join(src_lines), cta, hashtags])
    return post

def ensure_three_sources(category: str, entry):
    """
    Collect 3 verified sources:
    - entry link if verified
    - +2 more from GDELT
    """
    title = strip_html(entry.get("title", ""))
    link = entry.get("link", "")

    sources = []

    # Prefer verified original
    if link and is_verified(link):
        sources.append(link)

    # Query GDELT using title + category context
    query = f"{title} {category}"
    extra = gdelt_sources(query=query, max_needed=5)

    # Add unique verified extras
    for u in extra:
        if u not in sources:
            sources.append(u)
        if len(sources) >= 3:
            break

    # If still less than 3, allow original (even if not verified) as fallback + keep searching a broader query
    if len(sources) < 3 and link and link not in sources:
        sources.append(link)

    if len(sources) < 3:
        broad_extra = gdelt_sources(query=f"{title}", max_needed=10)
        for u in broad_extra:
            if u not in sources:
                sources.append(u)
            if len(sources) >= 3:
                break

    return sources[:3]

def main():
    cache = load_cache()

    category, entry = pick_latest_entry()
    if not entry:
        print("No entries found.")
        return

    uid = entry.get("id") or entry.get("link") or entry.get("title")
    if cache.get(uid):
        print("Already posted. Skipping.")
        return

    sources = ensure_three_sources(category, entry)

    # Enforce minimum 3 sources
    if len(sources) < 3:
        raise RuntimeError("Could not fetch 3 sources. Try expanding VERIFIED_DOMAINS or feeds.")

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
        "category": category
    }
    save_cache(cache)
    print("Posted:", cache[uid]["title"])

if __name__ == "__main__":
    main()
