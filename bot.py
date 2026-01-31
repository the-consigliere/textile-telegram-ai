import os
import re
import json
import time
import html
import hashlib
import feedparser
from bs4 import BeautifulSoup
import telegram

# ============================================================
# BASIC CONFIG
# ============================================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8386226585:AAFamfLZ38bW44RXtWfOqBeejIYZiO5zP28")
CHANNEL_ID = os.getenv("CHANNEL_ID", "-1003554679496")
RUN_MODE = os.getenv("RUN_MODE", "regular").lower()

if not BOT_TOKEN or not CHANNEL_ID:
    raise ValueError("Missing BOT_TOKEN or CHANNEL_ID")

bot = telegram.Bot(token=BOT_TOKEN)
CACHE_FILE = "posted.json"

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

def make_fingerprint(title, summary):
    base = f"{title.lower()}::{summary.lower()[:400]}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()

# ============================================================
# LINKEDIN-STYLE POST BUILDER
# ============================================================
def build_post(title, summary, link, mode):
    header = "🚨🔥 BREAKING NEWS" if mode == "breaking" else "🧵📊 INDUSTRY UPDATE"

    return f"""
{header}

🔹 **{title}**

📰 **What’s happening?**  
{summary}

🎯 **Why it matters**  
This development has real implications for brands, retailers, suppliers, and investors — from sourcing strategies to cost structures and competitive positioning.

💡 **My take**  
The companies that react early, adjust supply chains, and align with shifting market dynamics will have the edge going forward.

🔗 **Source**  
{link}

💬 What’s your view? Let’s discuss 👇
""".strip()

# ============================================================
# MAIN LOGIC
# ============================================================
def main():
    cache = load_cache()

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

            fingerprint = make_fingerprint(title, summary)

            # 🔥 DUPLICATE KILL SWITCH
            if fingerprint in cache:
                continue

            post = build_post(
                title=title,
                summary=summary[:800] + "...",
                link=link,
                mode=RUN_MODE
            )

            bot.send_message(
                chat_id=CHANNEL_ID,
                text=html.escape(post),
                parse_mode="HTML",
                disable_web_page_preview=False
            )

            # SAVE PERMANENTLY (NO REPEAT EVER)
            cache[fingerprint] = {
                "title": title,
                "time": int(time.time()),
                "mode": RUN_MODE
            }
            save_cache(cache)

            print("Posted:", title)
            return  # ONE POST PER RUN ONLY

    print("No new unique news found.")

# ============================================================
if __name__ == "__main__":
    main()






