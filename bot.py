import os
import re
import json
import time
import html
import hashlib
import feedparser
from difflib import SequenceMatcher
from bs4 import BeautifulSoup
import telegram

# ============================================================
# CONFIG
# ============================================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8386226585:AAFamfLZ38bW44RXtWfOqBeejIYZiO5zP28")
CHANNEL_ID = os.getenv("CHANNEL_ID", "-1003554679496")
RUN_MODE = os.getenv("RUN_MODE", "regular").lower()

if not BOT_TOKEN or not CHANNEL_ID:
    raise ValueError("Missing BOT_TOKEN or CHANNEL_ID")

bot = telegram.Bot(token=BOT_TOKEN)
CACHE_FILE = "posted.json"

SIMILARITY_THRESHOLD = 0.92  # 92% similarity = duplicate

# ============================================================
# BREAKING KEYWORDS
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
    "https://www.sourcingjournal.com/feed/",
    "https://www.ecotextile.com/rss.xml",
    "https://www.textileworld.com/feed/",
    "https://www.fashionnetwork.com/rss.xml",
    "https://www.marketwatch.com/rss/topstories"
]

# ============================================================
# HELPERS
# ============================================================
def clean_text(text):
    soup = BeautifulSoup(text or "", "html.parser")
    return re.sub(r"\s+", " ", soup.get_text()).strip()

def looks_breaking(title):
    title = title.lower()
    return any(k in title for k in BREAKING_KEYWORDS)

def normalize_title(title):
    title = title.lower()

    # remove source branding
    title = re.sub(
        r"\b(reuters|bloomberg|ft|bbc|cnbc|wsj|nytimes|guardian|forbes)\b",
        "",
        title
    )

    # remove punctuation
    title = re.sub(r"[^a-z0-9 ]+", " ", title)
    title = re.sub(r"\s+", " ", title).strip()
    return title

def make_fingerprint(title):
    normalized = normalize_title(title)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

def is_similar(a, b):
    return SequenceMatcher(None, a, b).ratio() >= SIMILARITY_THRESHOLD

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
        json.dump(cache, f, indent=2, ensure_ascii=False)

# ============================================================
# LINKEDIN POST FORMAT
# ============================================================
def build_post(title, summary, link, mode):
    header = "🚨🔥 BREAKING NEWS" if mode == "breaking" else "🧵📊 INDUSTRY UPDATE"

    return f"""
{header}

🔹 **{title}**

📰 **What’s happening?**  
{summary}

🎯 **Why it matters**  
This development impacts sourcing, cost structures, brand strategy, and competitive dynamics across the retail, fashion, and textile ecosystem.

💡 **My take**  
The companies that move early—adjusting supply chains, partnerships, and execution speed—will gain a clear advantage in the next cycle.

🔗 **Source**  
{link}

💬 What’s your take? Let’s discuss 👇
""".strip()

# ============================================================
# MAIN LOGIC
# ============================================================
def main():
    cache = load_cache()

    existing_titles = [
        normalize_title(v["title"])
        for v in cache.values()
        if "title" in v
    ]

    for feed_url in RSS_FEEDS:
        feed = feedparser.parse(feed_url)

        for entry in feed.entries[:10]:
            title = clean_text(entry.get("title", ""))
            summary = clean_text(entry.get("summary", ""))
            link = entry.get("link", "")

            if not title or not summary or not link:
                continue

            is_breaking = looks_breaking(title)

            # STRICT MODE SEPARATION
            if RUN_MODE == "breaking" and not is_breaking:
                continue
            if RUN_MODE == "regular" and is_breaking:
                continue

            normalized = normalize_title(title)

            # 🔥 FUZZY DUPLICATE CHECK
            if any(is_similar(normalized, old) for old in existing_titles):
                continue

            fingerprint = make_fingerprint(title)

            if fingerprint in cache:
                continue

            post = build_post(
                title=title,
                summary=summary[:900] + "...",
                link=link,
                mode=RUN_MODE
            )

            bot.send_message(
                chat_id=CHANNEL_ID,
                text=html.escape(post),
                parse_mode="HTML",
                disable_web_page_preview=False
            )

            cache[fingerprint] = {
                "title": title,
                "time": int(time.time()),
                "mode": RUN_MODE
            }

            save_cache(cache)
            print("Posted:", title)
            return  # ONE POST PER RUN

    print("No new unique news found.")

# ============================================================
if __name__ == "__main__":
    main()







