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
# BOT CONFIG
# ============================================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8386226585:AAFamfLZ38bW44RXtWfOqBeejIYZiO5zP28")
CHANNEL_ID = os.getenv("CHANNEL_ID", "-1003554679496")

if not BOT_TOKEN or not CHANNEL_ID:
    raise ValueError("BOT_TOKEN or CHANNEL_ID missing")

bot = telegram.Bot(token=BOT_TOKEN)

RUN_MODE = os.getenv("RUN_MODE", "regular").lower()
MIN_VERIFIED_SOURCES = int(os.getenv("MIN_VERIFIED_SOURCES", "1"))
TOTAL_SOURCES_TO_SHOW = int(os.getenv("TOTAL_SOURCES_TO_SHOW", "2"))
DUPLICATE_COOLDOWN = int(os.getenv("DUPLICATE_COOLDOWN", "7200"))  # 2 hours

CACHE_FILE = "posted.json"

# ============================================================
# BREAKING LOGIC
# ============================================================
BREAKING_KEYWORDS = [
    "breaking", "urgent", "exclusive", "acquire", "acquisition",
    "merger", "ipo", "bankruptcy", "funding", "raises",
    "layoff", "strike", "ban", "lawsuit", "probe", "shutdown"
]

# ============================================================
# RSS FEEDS (30+)
# ============================================================
RSS_FEEDS = [
    "https://www.reuters.com/rssFeed/retailNews",
    "https://www.reuters.com/rssFeed/fashion",
    "https://www.bloomberg.com/feeds/markets",
    "https://www.businessoffashion.com/rss",
    "https://www.voguebusiness.com/rss",
    "https://www.fibre2fashion.com/rss/news.xml",
    "https://www.just-style.com/feed/",
    "https://www.apparelresources.com/feed/",
    "https://www.retaildive.com/feeds/news/",
    "https://www.fashionunited.com/rss/news",
    "https://www.chainstoreage.com/rss.xml",
    "https://www.retailgazette.co.uk/feed/",
    "https://www.ft.com/retail?format=rss",
    "https://www.cnbc.com/id/10000108/device/rss/rss.html",
    "https://www.bbc.com/news/business/rss.xml",
    "https://www.nytimes.com/services/xml/rss/nyt/Business.xml",
    "https://www.wsj.com/xml/rss/3_7014.xml",
    "https://www.theguardian.com/business/retail/rss",
    "https://www.forbes.com/retail/feed/",
    "https://www.mckinsey.com/industries/retail/rss",
    "https://www.sourcingjournal.com/feed/",
    "https://www.ecotextile.com/rss.xml",
    "https://www.textileworld.com/feed/",
    "https://www.fashionnetwork.com/rss.xml",
    "https://www.euromonitor.com/rss",
    "https://www.prnewswire.com/rss/news-releases-list.rss",
    "https://www.businesswire.com/rss/home",
    "https://www.wgsn.com/rss",
    "https://www.marketwatch.com/rss/topstories"
]

# ============================================================
# VERIFIED DOMAINS (50+)
# ============================================================
VERIFIED_DOMAINS = {
    "reuters.com", "bloomberg.com", "ft.com", "bbc.com", "nytimes.com",
    "wsj.com", "cnbc.com", "forbes.com", "businesswire.com", "prnewswire.com",
    "theguardian.com", "fashionunited.com", "businessoffashion.com",
    "voguebusiness.com", "fibre2fashion.com", "just-style.com",
    "apparelresources.com", "retaildive.com", "chainstoreage.com",
    "retailgazette.co.uk", "fashionnetwork.com", "textileworld.com",
    "ecotextile.com", "sourcingjournal.com", "euromonitor.com",
    "mckinsey.com", "wgsn.com", "marketwatch.com", "statista.com",
    "economist.com", "nikkei.com", "fortune.com", "axios.com",
    "fastcompany.com", "hbr.org", "insider.com", "cnn.com",
    "apnews.com", "aljazeera.com", "scmp.com", "thehindubusinessline.com",
    "livemint.com", "economicstimes.indiatimes.com"
}

# ============================================================
# HELPERS
# ============================================================
def clean(text):
    return re.sub(r"\s+", " ", BeautifulSoup(text or "", "html.parser").get_text()).strip()

def get_domain(url):
    return re.sub(r"^https?://", "", url).split("/")[0].replace("www.", "")

def is_verified(url):
    d = get_domain(url)
    return any(d.endswith(v) for v in VERIFIED_DOMAINS)

def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_cache(cache):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)

def looks_breaking(title):
    return any(k in title.lower() for k in BREAKING_KEYWORDS)

# ============================================================
# POST FORMAT (LINKEDIN READY)
# ============================================================
def build_post(title, summary, sources, mode):
    emoji = "🚨🔥 BREAKING" if mode == "breaking" else "🧵📊 INDUSTRY UPDATE"

    return f"""
{emoji}

🔹 **{title}**

📰 **What’s happening?**
{summary}

🎯 **Why it matters**
This development could reshape sourcing strategies, cost structures, and competitive positioning across the retail, fashion, and textile ecosystem. Brands, suppliers, and investors will be watching closely.

💡 **My take**
The winners will be those who act early—reworking supply chains, strengthening partnerships, and aligning faster with consumer and regulatory shifts.

🔗 **Sources**
{chr(10).join(sources)}

💬 What’s your perspective? Let’s discuss 👇
""".strip()

# ============================================================
# MAIN
# ============================================================
def main():
    cache = load_cache()
    now = int(time.time())

    for feed_url in RSS_FEEDS:
        feed = feedparser.parse(feed_url)

        for e in feed.entries[:10]:
            title = clean(e.get("title", ""))
            link = e.get("link", "")
            summary = clean(e.get("summary", ""))

            if not title or not link:
                continue

            uid = link
            last_posted = cache.get(uid, 0)

            if now - last_posted < DUPLICATE_COOLDOWN:
                continue

            is_breaking = looks_breaking(title)

            if RUN_MODE == "breaking" and not is_breaking:
                continue
            if RUN_MODE == "regular" and is_breaking:
                continue

            sources = []
            if is_verified(link):
                sources.append(f"✅ {link}")

            if len(sources) < MIN_VERIFIED_SOURCES:
                continue

            post = build_post(title, summary[:700] + "...", sources, RUN_MODE)

            bot.send_message(
                chat_id=CHANNEL_ID,
                text=html.escape(post),
                parse_mode="HTML",
                disable_web_page_preview=False
            )

            cache[uid] = now
            save_cache(cache)
            return

if __name__ == "__main__":
    main()





