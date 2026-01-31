import os
import re
import json
import time
import hashlib
import random
import feedparser
import requests
from bs4 import BeautifulSoup
import telegram

# ============================================================
# BOT CONFIG
# ============================================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8386226585:AAFamfLZ38bW44RXtWfOqBeejIYZiO5zP28")
CHANNEL_ID = os.getenv("CHANNEL_ID", "-1003554679496")

bot = telegram.Bot(token=BOT_TOKEN)

RUN_MODE = os.getenv("RUN_MODE", "breaking").lower()
CACHE_FILE = "posted.json"
DUPLICATE_COOLDOWN = 2 * 3600  # 2 hours

MIN_VERIFIED_SOURCES = 1
TOTAL_SOURCES_TO_SHOW = 3

# ============================================================
# KEYWORDS & THEMES
# ============================================================
BREAKING_KEYWORDS = [
    "breaking", "urgent", "exclusive", "acquisition", "merger",
    "ipo", "bankruptcy", "funding", "raises", "layoffs",
    "shutdown", "ban", "probe", "lawsuit", "strike"
]

FASHION_KEYS = ["fashion", "luxury", "apparel", "brand", "designer"]
RETAIL_KEYS = ["retail", "store", "consumer", "sales", "pricing"]
TEXTILE_KEYS = ["textile", "fabric", "yarn", "fiber", "mills"]
SUPPLY_KEYS = ["supply", "logistics", "sourcing", "inventory", "warehouse"]
SUSTAIN_KEYS = ["sustainable", "esg", "carbon", "recycling", "environment"]

HOOKS = [
    "Most people will miss why this actually matters.",
    "At first glance this looks routine — it’s not.",
    "This decision signals a deeper shift in the industry.",
    "Quiet move. Big implications.",
    "This could reshape how the industry operates next."
]

# ============================================================
# RSS FEEDS (30+ GLOBAL)
# ============================================================
RSS_FEEDS = [
    "https://www.retaildive.com/feeds/news/",
    "https://www.businessoffashion.com/rss",
    "https://www.voguebusiness.com/rss",
    "https://www.fashionunited.com/rss/news",
    "https://www.fibre2fashion.com/rss/news.xml",
    "https://www.just-style.com/feed/",
    "https://www.apparelresources.com/feed/",
    "https://www.retailgazette.co.uk/feed/",
    "https://www.chainstoreage.com/rss.xml",
    "https://www.sourcingjournal.com/feed/",
    "https://www.ecotextile.com/rss.xml",
    "https://www.textiletoday.com.bd/feed/",
    "https://www.fashionnetwork.com/rss/news",
    "https://www.supplychaindive.com/feeds/news/",
    "https://www.forbes.com/retail/feed/",
    "https://www.reuters.com/rssFeed/retailNews",
    "https://www.ft.com/retail?format=rss",
    "https://www.bbc.co.uk/news/business/rss.xml",
    "https://www.theguardian.com/business/retail/rss",
    "https://www.cnbc.com/id/10001147/device/rss/rss.html",
    "https://www.marketwatch.com/rss/topstories",
    "https://fortune.com/feed/",
    "https://www.fastcompany.com/rss",
    "https://www.axios.com/rss/business",
    "https://asia.nikkei.com/rss/feed/nar",
    "https://www.scmp.com/rss/91/feed",
    "https://www.livemint.com/rss/companies",
    "https://www.business-standard.com/rss/companies"
]

# ============================================================
# VERIFIED DOMAINS (50+)
# ============================================================
VERIFIED_DOMAINS = {
    "reuters.com", "bloomberg.com", "ft.com", "wsj.com", "nytimes.com",
    "bbc.com", "theguardian.com", "forbes.com", "cnbc.com",
    "businessoffashion.com", "voguebusiness.com", "fashionunited.com",
    "retaildive.com", "sourcingjournal.com", "chainstoreage.com",
    "retailgazette.co.uk", "fibre2fashion.com", "just-style.com",
    "apparelresources.com", "fashionnetwork.com", "supplychaindive.com",
    "ecotextile.com", "textiletoday.com.bd", "livemint.com",
    "business-standard.com", "economictimes.indiatimes.com",
    "scmp.com", "asia.nikkei.com", "nikkei.com",
    "axios.com", "marketwatch.com", "fortune.com",
    "fastcompany.com", "cnn.com", "inc.com",
    "wired.com", "insideretail.asia", "forbesindia.com"
}

# ============================================================
# HELPERS
# ============================================================
def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_cache(cache):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)

def strip_html(text):
    return BeautifulSoup(text or "", "html.parser").get_text(" ", strip=True)

def get_domain(url):
    return re.sub(r"^https?://", "", url).split("/")[0].replace("www.", "").lower()

def is_verified(url):
    d = get_domain(url)
    return any(d == v or d.endswith("." + v) for v in VERIFIED_DOMAINS)

def entry_timestamp(entry):
    p = entry.get("published_parsed") or entry.get("updated_parsed")
    return int(time.mktime(p)) if p else int(time.time())

def make_uid(entry):
    title = strip_html(entry.get("title", "")).lower()
    domain = get_domain(entry.get("link", ""))
    hour = entry_timestamp(entry) // 3600
    raw = f"{title}|{domain}|{hour}"
    return hashlib.sha256(raw.encode()).hexdigest()

def looks_breaking(title):
    return any(k in title.lower() for k in BREAKING_KEYWORDS)

def detect_theme(text):
    t = text.lower()
    if any(k in t for k in SUSTAIN_KEYS):
        return "sustainability"
    if any(k in t for k in SUPPLY_KEYS):
        return "supply"
    if any(k in t for k in FASHION_KEYS):
        return "fashion"
    if any(k in t for k in RETAIL_KEYS):
        return "retail"
    if any(k in t for k in TEXTILE_KEYS):
        return "textile"
    return "industry"

# ============================================================
# GDELT SOURCES
# ============================================================
def gdelt_sources(query):
    urls = []
    try:
        r = requests.get(
            "https://api.gdeltproject.org/api/v2/doc/doc",
            params={"query": query, "mode": "ArtList", "format": "json", "maxrecords": 50},
            timeout=15
        )
        for a in r.json().get("articles", []):
            u = a.get("url", "")
            if u and is_verified(u) and u not in urls:
                urls.append(u)
    except:
        pass
    return urls[:TOTAL_SOURCES_TO_SHOW]

# ============================================================
# LINKEDIN POST BUILDER (FINAL)
# ============================================================
def build_linkedin_post(entry, sources):
    title = strip_html(entry.get("title", ""))
    summary = strip_html(entry.get("summary", ""))
    theme = detect_theme(title + " " + summary)
    hook = random.choice(HOOKS)

    why_map = {
        "fashion": "Brand positioning, speed-to-market, and consumer perception are now under pressure.",
        "retail": "Margins, pricing power, and demand forecasting are becoming increasingly fragile.",
        "textile": "Upstream suppliers may face changes in volumes, pricing, and sourcing commitments.",
        "supply": "Resilience is overtaking pure cost efficiency as the top priority.",
        "sustainability": "Regulatory pressure and consumer expectations are accelerating fast.",
        "industry": "Strategic clarity matters more now than short-term optimization."
    }

    post = f"""
🚨 **{title}**

{hook}

📰 **What’s going on?**
{summary}

This development reflects broader structural shifts across the global retail, fashion, and textile ecosystem — driven by cost pressures, evolving demand patterns, and strategic recalibration.

🎯 **Why this matters**
{why_map.get(theme)}

Moves like this don’t stay isolated. They ripple across brands, retailers, suppliers, and investors — reshaping planning cycles, partnerships, and capital allocation decisions.

💡 **My take**
We’ve crossed the point where operational tweaks are enough.
The companies that win next will treat sourcing, supply chains, and pricing as long-term strategic assets — not just cost levers.

Those who adapt early will shape the market.
Those who don’t will spend the next cycle reacting.

🔗 **Sources**
{chr(10).join([f"{i+1}. {s}" for i, s in enumerate(sources)])}

💬 **Your perspective?**
Is the industry moving fast enough — or still playing catch-up?

#Retail 🛍️ #Fashion 👗 #Textile 🧶 #SupplyChain 🚢 #Strategy 📊 #Leadership
"""
    return post.strip()

# ============================================================
# MAIN
# ============================================================
def main():
    cache = load_cache()
    now = int(time.time())

    for feed_url in RSS_FEEDS:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries[:25]:
            title = strip_html(entry.get("title", ""))
            if not title:
                continue

            if RUN_MODE == "breaking" and not looks_breaking(title):
                continue

            uid = make_uid(entry)
            if uid in cache and now - cache[uid]["time"] < DUPLICATE_COOLDOWN:
                continue

            sources = gdelt_sources(title)
            if len(sources) < MIN_VERIFIED_SOURCES:
                continue

            post = build_linkedin_post(entry, sources)

            bot.send_message(
                chat_id=CHANNEL_ID,
                text=post,
                disable_web_page_preview=False
            )

            cache[uid] = {"title": title, "time": now}
            save_cache(cache)

            print("Posted:", title)
            return

    print("No new unique news found.")

if __name__ == "__main__":
    main()





