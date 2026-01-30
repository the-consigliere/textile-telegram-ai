import os
import re
import json
import time
import html
import feedparser
import requests
from bs4 import BeautifulSoup
import telegram

# ======================== CONFIG ==========================
# BOT TOKEN and CHANNEL_ID
BOT_TOKEN = os.getenv("BOT_TOKEN", "8386226585:AAFamfLZ38bW44RXtWfOqBeejIYZiO5zP28")
CHANNEL_ID = os.getenv("CHANNEL_ID", "-1003554679496")

if not BOT_TOKEN or not CHANNEL_ID:
    raise ValueError("Missing BOT_TOKEN or CHANNEL_ID. Set them as GitHub Secrets.")

bot = telegram.Bot(token=BOT_TOKEN)

# ======================== MODE ============================
RUN_MODE = os.getenv("RUN_MODE", "regular").strip().lower()  # regular or breaking

# ======================== SOURCES SETTINGS =================
MIN_VERIFIED_SOURCES = int(os.getenv("MIN_VERIFIED_SOURCES", "1"))
TOTAL_SOURCES_TO_SHOW = int(os.getenv("TOTAL_SOURCES_TO_SHOW", "2"))
ALLOW_FALLBACK_SOURCES = os.getenv("ALLOW_FALLBACK_SOURCES", "true").lower() == "true"

# ======================== BREAKING SETTINGS =================
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

# ======================== RSS FEEDS ========================
RSS_FEEDS = [
    "https://www.fibre2fashion.com/rss/news.xml",
    "https://www.just-style.com/feed/",
    "https://www.apparelresources.com/feed/",
    "https://www.retaildive.com/feeds/news/",
    "https://www.fashionunited.com/rss/news"
]

# ======================== VERIFIED DOMAINS =================
VERIFIED_DOMAINS = {
    "reuters.com", "ft.com", "bbc.com", "theguardian.com",
    "wsj.com", "nytimes.com", "cnbc.com", "bloomberg.com",
    "retaildive.com", "chainstoreage.com", "retailgazette.co.uk",
    "retaildetail.eu", "businessoffashion.com", "voguebusiness.com",
    "fashionunited.com", "fibre2fashion.com", "just-style.com", "apparelresources.com"
}

CACHE_FILE = "posted.json"

# ======================== HELPERS ==========================
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
    return re.sub(r"\s+", " ", clean).strip()

def safe_html(text: str) -> str:
    return html.escape(text or "")

def get_domain(url: str) -> str:
    try:
        u = re.sub(r"^https?://", "", url.strip())
        domain = u.split("/")[0].lower().replace("www.", "")
        return domain
    except:
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

# ======================== GDELT SOURCES ====================
def gdelt_sources_any(query: str, max_needed: int = 10):
    end = time.strftime("%Y%m%d%H%M%S", time.gmtime())
    start = time.strftime("%Y%m%d%H%M%S", time.gmtime(time.time() - 7*24*3600))
    urls = []
    try:
        params = {"query": query, "mode": "ArtList", "format": "json", "maxrecords":50, "sort":"HybridRel",
                  "startdatetime": start, "enddatetime": end}
        r = requests.get("https://api.gdeltproject.org/api/v2/doc/doc", params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
        for a in data.get("articles", []):
            u = a.get("url", "")
            if u.startswith("http") and u not in urls:
                urls.append(u)
            if len(urls) >= max_needed:
                break
    except:
        pass
    return urls

def gdelt_sources_verified(query: str, max_needed: int = 10):
    urls = []
    for u in gdelt_sources_any(query, max_needed=50):
        if is_verified(u) and u not in urls:
            urls.append(u)
        if len(urls) >= max_needed:
            break
    return urls

# ======================== SOURCES ==========================
def ensure_sources(entry, total_needed: int = 2):
    title = strip_html(entry.get("title", ""))
    link = entry.get("link", "")

    verified, fallback = [], []

    if link:
        if is_verified(link):
            verified.append(link)
        else:
            fallback.append(link)

    query = f"{title} retail fashion textile"
    for u in gdelt_sources_verified(query=query, max_needed=15):
        if u not in verified:
            verified.append(u)
        if len(verified) >= total_needed:
            break

    if len(verified) < 1:
        for u in gdelt_sources_verified(title, max_needed=20):
            if u not in verified:
                verified.append(u)
            if len(verified) >= total_needed:
                break

    sources = verified[:total_needed]

    if len(sources) < total_needed and ALLOW_FALLBACK_SOURCES:
        any_urls = gdelt_sources_any(query=query, max_needed=20) + gdelt_sources_any(title, max_needed=20)
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
    lines = []
    for i, s in enumerate(sources, start=1):
        tag = "✅ Verified" if is_verified(s) else "➕ Additional"
        lines.append(f"Source {i} ({tag}): {html.escape(s)}")
    return "\n".join(lines)

# ======================== POST BUILDERS ===================
def build_regular_post(entry, sources):
    title = safe_html(strip_html(entry.get("title", "")))
    summary = safe_html(strip_html(entry.get("summary", "")))[:900] + "..." if len(strip_html(entry.get("summary",""))) > 900 else strip_html(entry.get("summary",""))
    hook = f"🧵✨ <b>Retail / Fashion / Textile Pulse:</b> {title} ✨🧵"
    what = f"🧾 <b>What’s happening?</b>\n• {summary}"
    deep = "🔎 <b>Deeper context (quick analysis):</b>\n• This may affect sourcing strategy, inventory, pricing, channel mix, and KPIs."
    insight = "✅ <b>Conclusion:</b>\n• Strong execution improves competitiveness; weak rollout can hit margin & trust."
    cta = "💬 <b>Your suggestion?</b>\nIf you were leading the team, what’s the ONE move you’d prioritize next?"
    hashtags = "#Retail #Fashion #Textile #Apparel #Merchandising #Sourcing #SupplyChain #RetailStrategy #BrandStrategy #FashionBusiness #TextileIndustry #RetailTrends"

    post = "\n\n".join([hook, what, deep, insight, "🔗 <b>Sources (min 1 verified):</b>", format_sources(sources), cta, hashtags])
    return post

def build_breaking_post(entry, sources):
    title = safe_html(strip_html(entry.get("title", "")))
    summary = safe_html(strip_html(entry.get("summary", "")))[:450] + "..." if len(strip_html(entry.get("summary",""))) > 450 else strip_html(entry.get("summary",""))
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

# ======================== FEED PICKERS ====================
def pick_latest_entry():
    latest, latest_ts = None, 0
    for feed_url in RSS_FEEDS:
        feed = feedparser.parse(feed_url)
        if not feed.entries:
            continue
        for e in feed.entries[:12]:
            ts = entry_timestamp(e)
            if ts > latest_ts and e.get("title") and e.get("link"):
                latest, latest_ts = e, ts
    return latest

def find_breaking_candidate():
    now, max_age = int(time.time()), BREAKING_MAX_AGE_HOURS*3600
    for feed_url in RSS_FEEDS:
        feed = feedparser.parse(feed_url)
        if not feed.entries:
            continue
        for e in feed.entries[:BREAKING_SCAN_PER_FEED]:
            title, link = strip_html(e.get("title","")), e.get("link","")
            if not title or not link:
                continue
            ts = entry_timestamp(e)
            if (now - ts) <= max_age and looks_breaking(title):
                return e
    return None

# ======================== MAIN ============================
def main():
    cache = load_cache()

    # Select entry
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
    if verified_count < MIN_VERIFIED_SOURCES:
        print(f"Not enough verified sources ({verified_count}/{MIN_VERIFIED_SOURCES}). Skipping safely.")
        return

    post = build_breaking_post(entry, sources) if RUN_MODE=="breaking" else build_regular_post(entry, sources)

    bot.send_message(
        chat_id=CHANNEL_ID,
        text=post,
        parse_mode="HTML",
        disable_web_page_preview=False
    )

    cache[uid] = {"title": strip_html(entry.get("title","")), "time": int(time.time()), "mode": RUN_MODE}
    save_cache(cache)
    print("Posted:", cache[uid]["title"], "| mode:", RUN_MODE)

if __name__ == "__main__":
    main()



