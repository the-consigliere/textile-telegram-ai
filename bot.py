import os, re, json, time, html, hashlib, requests, feedparser
from bs4 import BeautifulSoup
from datetime import datetime
from difflib import SequenceMatcher
from textblob import TextBlob
import telegram

# ============================================================
# BASIC CONFIG
# ============================================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8386226585:AAFamfLZ38bW44RXtWfOqBeejIYZiO5zP28")
CHANNEL_ID = os.getenv("CHANNEL_ID", "-1003554679496")
RUN_MODE = os.getenv("RUN_MODE", "regular").lower()

bot = telegram.Bot(token=BOT_TOKEN)

CACHE_FILE = "posted.json"
TRENDS_FILE = "trends.json"

ONE_POST_PER_HOUR = True
SIMILARITY_THRESHOLD = 0.93
CAPTION_LIMIT = 900  # Telegram photo caption safety

# ============================================================
# RSS FEEDS (TOP GLOBAL 30+)
# ============================================================
RSS_FEEDS = [
    "https://www.reuters.com/rssFeed/retailNews",
    "https://www.reuters.com/rssFeed/businessNews",
    "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
    "https://www.ft.com/retail?format=rss",
    "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml",
    "https://feeds.bbci.co.uk/news/business/rss.xml",
    "https://www.theguardian.com/business/rss",
    "https://www.cnbc.com/id/10001147/device/rss/rss.html",
    "https://www.marketwatch.com/rss/topstories",
    "https://www.forbes.com/business/feed2/",
    "https://www.retaildive.com/feeds/news/",
    "https://www.businessoffashion.com/rss",
    "https://www.voguebusiness.com/rss",
    "https://www.sourcingjournal.com/feed/",
    "https://www.ecotextile.com/rss.xml",
    "https://www.textileworld.com/feed/",
    "https://www.greenbiz.com/rss/feeds/latest.xml",
    "https://economictimes.indiatimes.com/rssfeeds/13352306.cms",
    "https://asia.nikkei.com/rss/feed/nar",
    "https://www.fastcompany.com/rss"
]

# ============================================================
# TOPICS
# ============================================================
TOPICS = {
    "M&A": ["acquire", "acquisition", "merger", "buyout", "stake"],
    "Funding": ["funding", "raises", "investment", "round"],
    "Supply Chain": ["supply", "logistics", "factory", "manufacturing"],
    "Policy": ["ban", "regulation", "law", "probe"],
    "Retail Strategy": ["store", "pricing", "expansion", "launch"]
}

BREAKING_KEYWORDS = [
    "breaking", "urgent", "exclusive", "ipo",
    "bankruptcy", "layoff", "shutdown", "strike"
]

# ============================================================
# IMAGE FALLBACKS
# ============================================================
TOPIC_IMAGES = {
    "M&A": "https://images.unsplash.com/photo-1523958203904-cdcb402031fd",
    "Funding": "https://images.unsplash.com/photo-1553729459-efe14ef6055d",
    "Supply Chain": "https://images.unsplash.com/photo-1586528116311-ad8dd3c8310d",
    "Policy": "https://images.unsplash.com/photo-1504711434969-e33886168f5c",
    "Retail Strategy": "https://images.unsplash.com/photo-1521335629791-ce4aec67dd47",
    "Industry": "https://images.unsplash.com/photo-1483985988355-763728e1935b"
}

# ============================================================
# HELPERS
# ============================================================
def safe_caption(text, limit=CAPTION_LIMIT):
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "..."

def clean(text):
    soup = BeautifulSoup(text or "", "html.parser")
    return re.sub(r"\s+", " ", soup.get_text()).strip()

def normalize(text):
    return re.sub(r"[^a-z0-9 ]+", " ", text.lower()).strip()

def fingerprint(title):
    return hashlib.sha256(normalize(title).encode()).hexdigest()

def similar(a, b):
    return SequenceMatcher(None, a, b).ratio()

def load_json(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

# ============================================================
# DETECTION
# ============================================================
def is_breaking(title):
    return any(k in title.lower() for k in BREAKING_KEYWORDS)

def detect_topic(title, summary):
    text = (title + " " + summary).lower()
    for topic, keys in TOPICS.items():
        if any(k in text for k in keys):
            return topic
    return "Industry"

# ============================================================
# SENTIMENT
# ============================================================
def sentiment(text):
    p = TextBlob(text).sentiment.polarity
    if p > 0.15: return "🟢 Positive"
    if p < -0.15: return "🔴 Negative"
    return "🟡 Neutral"

# ============================================================
# AI SUMMARY
# ============================================================
def ai_summary(title, summary):
    sentences = summary.split(". ")
    bullets = [s for s in sentences if len(s) > 40][:4]
    return {
        "overview": f"{title} highlights a significant development reshaping the retail, fashion, and textile sector.",
        "bullets": [f"• {b.strip()}." for b in bullets]
    }

# ============================================================
# AI TAKE
# ============================================================
def ai_take(topic):
    return {
        "M&A": "This signals accelerated consolidation as brands chase scale and pricing power.",
        "Funding": "Capital is flowing toward efficiency-driven, profitable models.",
        "Supply Chain": "Supply resilience is now a competitive moat, not a cost center.",
        "Policy": "Regulation is becoming a strategic variable, not just compliance.",
        "Retail Strategy": "Execution speed matters more than store count.",
        "Industry": "This reflects deeper structural shifts in global consumption."
    }.get(topic)

# ============================================================
# HASHTAGS
# ============================================================
def hashtags(topic):
    base = ["#Retail", "#FashionBusiness", "#TextileIndustry"]
    extra = {
        "M&A": ["#Mergers", "#Acquisitions"],
        "Funding": ["#Funding", "#VentureCapital"],
        "Supply Chain": ["#SupplyChain"],
        "Policy": ["#Regulation"],
        "Retail Strategy": ["#RetailStrategy"]
    }
    return " ".join(base + extra.get(topic, []))

# ============================================================
# IMAGE FETCH
# ============================================================
def fetch_image(url, topic):
    try:
        r = requests.get(url, timeout=6, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(r.text, "html.parser")
        og = soup.find("meta", property="og:image")
        if og and og.get("content"):
            return og["content"]
    except:
        pass
    return TOPIC_IMAGES.get(topic)

# ============================================================
# POST FORMAT (LINKEDIN-STYLE)
# ============================================================
def build_post(e, sent, ai):
    return f"""
🔥 {e['title']}

🏷️ Topic: {e['topic']}

📌 What’s happening  
{ai['overview']}

📊 Key highlights  
{chr(10).join(ai['bullets'])}

📈 Sentiment: {sent}

💡 My take  
{ai_take(e['topic'])}

🔗 Source: {e['link']}

{hashtags(e['topic'])}
""".strip()

# ============================================================
# MAIN
# ============================================================
def main():
    cache = load_json(CACHE_FILE)
    current_hour = datetime.utcnow().strftime("%Y-%m-%d-%H")

    if ONE_POST_PER_HOUR:
        if any(v.get("hour") == current_hour for v in cache.values()):
            return

    seen_titles = [normalize(v["title"]) for v in cache.values()]
    candidates = []

    for feed in RSS_FEEDS:
        data = feedparser.parse(feed)
        for e in data.entries[:10]:
            title = clean(e.get("title"))
            summary = clean(e.get("summary", ""))
            link = e.get("link", "")

            if not title or not summary or not link:
                continue

            if RUN_MODE == "breaking" and not is_breaking(title):
                continue
            if RUN_MODE == "regular" and is_breaking(title):
                continue

            norm = normalize(title)
            if any(similar(norm, old) >= SIMILARITY_THRESHOLD for old in seen_titles):
                continue

            fp = fingerprint(title)
            if fp in cache:
                continue

            topic = detect_topic(title, summary)

            candidates.append({
                "title": title,
                "summary": summary[:1200],
                "link": link,
                "topic": topic,
                "breaking": is_breaking(title)
            })

    if not candidates:
        return

    best = max(candidates, key=lambda x: (x["breaking"], len(x["summary"])))

    sent = sentiment(best["summary"])
    ai = ai_summary(best["title"], best["summary"])
    image = fetch_image(best["link"], best["topic"])
    full_post = build_post(best, sent, ai)

    short_caption = safe_caption(
        f"🧵 {best['title']}\n\n🏷️ {best['topic']} | {sent}"
    )

    bot.send_photo(
        chat_id=CHANNEL_ID,
        photo=image,
        caption=html.escape(short_caption),
        parse_mode="HTML"
    )

    bot.send_message(
        chat_id=CHANNEL_ID,
        text=html.escape(full_post),
        parse_mode="HTML",
        disable_web_page_preview=False
    )

    cache[fingerprint(best["title"])] = {
        "title": best["title"],
        "hour": current_hour,
        "time": int(time.time())
    }

    save_json(CACHE_FILE, cache)

# ============================================================
if __name__ == "__main__":
    main()
