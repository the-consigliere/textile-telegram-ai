import os
import json
import time
import feedparser
import telegram

# Read secrets from GitHub Actions secrets
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")

if not BOT_TOKEN or not CHANNEL_ID:
    raise ValueError("Missing BOT_TOKEN or CHANNEL_ID. Add them in GitHub Secrets → Actions.")

bot = telegram.Bot(token=BOT_TOKEN)

# RSS FEEDS (Retail / Brand / Textile)
RSS_FEEDS = [
    "https://www.fibre2fashion.com/rss/news.xml",
    "https://www.just-style.com/feed/",
    "https://www.apparelresources.com/feed/"
]

CACHE_FILE = "posted.json"

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

def clean_text(html_text: str) -> str:
    # Basic cleanup for RSS summaries (keeps it simple & safe)
    txt = html_text.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    # Remove very common tags quickly (not perfect but fine for beginner bot)
    for tag in ["<p>", "</p>", "<b>", "</b>", "<i>", "</i>", "<strong>", "</strong>", "<em>", "</em>"]:
        txt = txt.replace(tag, "")
    return " ".join(txt.split())

def build_post(entry):
    title = entry.get("title", "Latest update")
    link = entry.get("link", "")
    summary = entry.get("summary", "")
    summary = clean_text(summary)

    # Keep message short (Telegram safe)
    if len(summary) > 700:
        summary = summary[:700] + "..."

    message = (
        f"🧵 *Retail & Textile Update*\n\n"
        f"🔥 *{title}*\n\n"
        f"📌 {summary}\n\n"
        f"🔗 {link}\n\n"
        f"#Textile #Retail #Apparel #FashionBusiness"
    )
    return message

def get_latest_entry():
    latest = None
    latest_time = 0

    for url in RSS_FEEDS:
        feed = feedparser.parse(url)
        if not feed.entries:
            continue

        for e in feed.entries[:5]:  # check few latest
            # Try multiple date fields
            published_parsed = e.get("published_parsed") or e.get("updated_parsed")
            if published_parsed:
                ts = int(time.mktime(published_parsed))
            else:
                ts = int(time.time())  # fallback

            if ts > latest_time:
                latest = e
                latest_time = ts

    return latest

def main():
    cache = load_cache()

    entry = get_latest_entry()
    if not entry:
        print("No RSS entries found.")
        return

    # Unique ID for duplicates
    uid = entry.get("id") or entry.get("link") or entry.get("title")

    if cache.get(uid):
        print("Already posted this entry. Skipping.")
        return

    text = build_post(entry)

    # Send to Telegram
    bot.send_message(
        chat_id=CHANNEL_ID,
        text=text,
        parse_mode="Markdown"
    )

    cache[uid] = True
    save_cache(cache)
    print("Posted successfully:", entry.get("title"))

if __name__ == "__main__":
    main()
