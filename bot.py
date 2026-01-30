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

# ===================== SOURCE REQUIREMENTS (YOUR RULES) =====================
# Minimum 2 VERIFIED sources required to "confirm" the news
MIN_VERIFIED_SOURCES = int(os.getenv("MIN_VERIFIED_SOURCES", "2"))

# Total sources to display (we’ll output exactly 2 to match your requirement)
TOTAL_SOURCES_TO_SHOW = int(os.getenv("TOTAL_SOURCES_TO_SHOW", "2"))

# If True, we can fill missing sources with non-verified “additional” links.
# You asked for confirmation links, so keep this FALSE.
ALLOW_FALLBACK_SOURCES = os.getenv("ALLOW_FALLBACK_SOURCES", "false").lower() == "true"

# ===================== BREAKING SETTINGS =====================
BREAKING_KEYWORDS = [
    "breaking", "urgent", "exclusive", "acquire", "acquires", "acquisition", "merger",
    "ipo", "bankruptcy", "funding", "raises", "layoff", "layoffs", "security breach",
    "recall", "ban", "probe", "lawsuit", "regulator", "strike", "shutdown"
]
BREAKING_MAX_AGE_HOURS = int(os.getenv("BREAKING_MAX_AGE_HOURS", "6"))
BREAKING_SCAN_PER_FEED = int(os.getenv("BREAKING_SCAN_PER_FEED", "12"))

# ===================== RSS FEEDS (RETAIL / FASHION / TEXTILE ONLY) =====================
RSS_FEEDS = [
    "https://www.fibre2fashion.com/rss/news.xml",
    "https://www.just-style.com/feed/",
    "https://www.apparelresources.com/feed/",
    "https://www.retaildive.com/feeds/news/",
    "https://www.fashionunited.com/rss/news"
]

# ===================== VERIFIED DOMAINS (ALLOWLIST) =====================
# Add more if you want to broaden confirmation sources
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
def gdelt_verified_sources(query: str, max_needed: int = 10):
    """
    Returns verified source URLs only (filtered by allowlist).
    Free + public API.
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

# ===================== SOURCE SELECTION =====================
def ensure_sources(entry, total_needed: int = 2):
    """
    Return (sources_list, verified_count).
    We aim for total_needed sources, verified first.
    """
    title = strip_html(entry.get("title", ""))
    link = entry.get("link", "")

    verified = []
    others = []

    # 1) Entry link
    if link:
        if is_verified(link):
            verified.append(link)
        else:
            others.append(link)

    # 2) Verified from GDELT using title
    query = f"{title} retail fashion textile"
    for u in gdelt_verified_sources(query=query, max_needed=15):
        if u not in verified:
            verified.append(u)
        if len(verified) >= total_needed:
            break

    # 3) Broader verified search
    if len(verified) < total_needed:
        for u in gdelt_verified_sources(query=title, max_needed=20):
            if u not in verified:
                verified.append(u)
            if len(verified) >= total_needed:
                break

    sources = verified[:total_needed]

    # Optional fallback (disabled by default)
    if len(sources) < total_needed and ALLOW_FALLBACK_SOURCES:
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
        lines.append(f"Source {i}: {s}")
    return "\n".join(lines)

# ===================== CONTENT BUILDERS =====================
def build_linkedin_style_post(entry, sources: list):
    title = strip_html(entry.get("title", "Industry Update"))
    summary = strip_html(entry.get("summary", ""))

    if len(summary) > 900:
        summary = summary[:900].rstrip() + "..."

    hook = f"🧵✨ *Retail / Fashion / Textile Pulse:* {title} ✨🧵"

    what = (
        "🧾 *What’s this about?*\n"
        f"• {summary}"
    )

    deep = (
        "🔎 *Deeper context (quick analysis):*\n"
        "• This could influence sourcing strategies, vendor negotiations, and lead times.\n"
        "• Watch pricing pressure, inventory cycles, and how brands respond across channels.\n"
        "• The next 30–90 days will reveal execution quality through KPIs (sell-through, margin, OTIF, returns)."
    )

    insight = (
        "✅ *Conclusion (key insight in short):*\n"
        "• Strong execution here can improve competitiveness, but weak rollout can hit margin and customer trust.\n"
        "• The smartest players will move fast, test small, and scale what works."
    )

    src_lines = format_sources(sources)

    cta = (
        "💬 *Your suggestion?*\n"
        "If you were leading the team, what’s the ONE move you’d prioritize next — and why? 👇"
    )

    hashtags = (
        "#Retail #Fashion #Textile #Apparel #Merchandising #Sourcing #SupplyChain #RetailStrategy #BrandStrategy\n"
        "#FashionBusiness #TextileIndustry #RetailTrends #ApparelIndustry"
    )

    post = "\n\n".join([hook, what, deep, insight, "🔗 *Confirmed Sources (min 2):*", src_lines, cta, hashtags])
    return post

def build_breaking_post(entry, sources: list):
    title = strip_html(entry.get("title", "Breaking Update"))
    summary = strip_html(entry.get("summary", ""))

    if len(summary) > 450:
        summary = summary[:450].rstrip() + "..."

    src_lines = format_sources(sources)

    post = (
        f"🚨🔥 *BREAKING (Retail / Fashion / Textile)* 🔥🚨\n\n"
        f"🧵 *{title}*\n\n"
        f"📌 {summary}\n\n"
        f"🔗 *Confirmed Sources (min 2):*\n{src_lines}\n\n"
        f"💬 *What’s your take?* Opportunity or risk for brands/retailers? 👇\n\n"
        f"#BreakingNews #Retail #Fashion #Textile #Apparel"
    )
    return post

# ===================== FEED PICKERS =====================
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

# ===================== MAIN =====================
def main():
    cache = load_cache()

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

    # Your confirmation rule: require at least 2 verified sources
    if verified_count < MIN_VERIFIED_SOURCES or len(sources) < 2:
        print(f"Not enough verified sources ({verified_count}/{MIN_VERIFIED_SOURCES}). Skipping item safely.")
        return

    if RUN_MODE == "breaking":
        post = build_breaking_post(entry, sources)
    else:
        post = build_linkedin_style_post(entry, sources)

    bot.send_message(
        chat_id=CHANNEL_ID,
        text=post,
        parse_mode="Markdown",
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
