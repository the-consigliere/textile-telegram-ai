import feedparser
import requests
import telegram
from transformers import pipeline
from diffusers import StableDiffusionPipeline
import torch
import random

# TELEGRAM CONFIG
BOT_TOKEN = "PASTE_BOT_TOKEN"
CHANNEL_ID = "PASTE_CHANNEL_ID"

bot = telegram.Bot(token=BOT_TOKEN)

# RSS FEEDS (Retailers & Brands)
RSS_FEEDS = [
    "https://www.fibre2fashion.com/rss/news.xml",
    "https://www.just-style.com/feed/",
    "https://www.apparelresources.com/feed/"
]

# AI TEXT
summarizer = pipeline("summarization", model="facebook/bart-large-cnn")

# AI IMAGE
image_model = StableDiffusionPipeline.from_pretrained(
    "stabilityai/stable-diffusion-2",
    torch_dtype=torch.float16
)
image_model.to("cpu")

def generate_post(article):
    title = f"🧵🔥 {article.title}"

    intro = summarizer(article.summary, max_length=120, min_length=80)[0]['summary_text']
    deep = summarizer(article.summary, max_length=90, min_length=60)[0]['summary_text']
    conclusion = summarizer(article.summary, max_length=70, min_length=40)[0]['summary_text']

    content = f"""
{title}

📌 {intro}

🔍 {deep}

✅ {conclusion}

💬 What are your views on this development?
Do you think this will impact retail & textile brands?

#TextileIndustry #RetailBrands #FashionBusiness
#ApparelIndustry #BrandStrategy
"""
    return content

def generate_image(prompt):
    image = image_model(prompt).images[0]
    image.save("news.png")

for feed_url in RSS_FEEDS:
    feed = feedparser.parse(feed_url)
    for entry in feed.entries[:1]:
        text = generate_post(entry)
        prompt = f"editorial illustration of {entry.title}, fashion retail, textile industry"
        generate_image(prompt)

        bot.send_photo(
            chat_id=CHANNEL_ID,
            photo=open("news.png", "rb"),
            caption=text
        )
