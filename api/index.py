"""
Today I Learned (TIL) - FastAPI Backend
Serves random knowledge snippets (articles and videos with transcripts) combined into a single random feed.
Completely database-free: relies on live scraping and in-memory mock data fallbacks.
"""

import os
import sys
import random
import logging
import threading
from typing import List, Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv
from google import genai

# Configure standard logging to output to stdout
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout
)
logger = logging.getLogger("api.index")

# Add parent directory to sys.path to import local modules
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

# Load .env file
load_dotenv(os.path.join(BASE_DIR, ".env"))

from api.letters import get_scraped_article
from api.videos import get_scraped_video
from api.fallback_data import FALLBACK_ARTICLES, FALLBACK_VIDEOS

app = FastAPI(title="Do You Find It Interesting API", version="1.0.0")

# ── Pydantic Request Models ───────────────────────────────────────────────────
class SummarizeRequest(BaseModel):
    source_type: str
    title: str
    source_url: Optional[str] = None
    source_name: Optional[str] = None
    topic: Optional[str] = None
    content: Optional[List[str]] = None
    channel: Optional[str] = None
    video_id: Optional[str] = None

# ── Gemini Client Setup ───────────────────────────────────────────────────────
gemini_client = None

def get_gemini_client():
    global gemini_client
    if gemini_client is None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            logger.error("GEMINI_API_KEY environment variable is not set!")
            raise HTTPException(status_code=500, detail="GEMINI_API_KEY environment variable is not set.")
        gemini_client = genai.Client(api_key=api_key)
    return gemini_client

# ── In-Memory Cache and Background Replenishing ───────────────────────────────
# Initialize with fallback data so startup and first requests are instant
scraped_articles_cache = list(FALLBACK_ARTICLES)
scraped_videos_cache = list(FALLBACK_VIDEOS)

# Thread safety lock for cache modifications
cache_lock = threading.Lock()

def replenish_article_cache():
    """Scrapes a fresh article in a background thread and adds it to the cache."""
    try:
        logger.info("Background task: Scraping a fresh article to replenish cache...")
        new_article = get_scraped_article()
        with cache_lock:
            if len(scraped_articles_cache) < 10:
                scraped_articles_cache.append(new_article)
                logger.info(f"Background task: Added scraped article to cache. Current cache size: {len(scraped_articles_cache)}")
            else:
                logger.info("Background task: Article cache is full. Scraped item discarded.")
    except Exception as e:
        logger.warning(f"Background task: Failed to scrape article to replenish cache: {e}")

def replenish_video_cache():
    """Scrapes a fresh video in a background thread and adds it to the cache."""
    try:
        logger.info("Background task: Scraping a fresh video to replenish cache...")
        new_video = get_scraped_video()
        with cache_lock:
            if len(scraped_videos_cache) < 10:
                scraped_videos_cache.append(new_video)
                logger.info(f"Background task: Added scraped video to cache. Current cache size: {len(scraped_videos_cache)}")
            else:
                logger.info("Background task: Video cache is full. Scraped item discarded.")
    except Exception as e:
        logger.warning(f"Background task: Failed to scrape video to replenish cache: {e}")

@app.on_event("startup")
def startup_event():
    """
    Trigger background threads to fetch fresh content into the cache on startup.
    This guarantees that by the time users make requests, the cache contains newly scraped content.
    """
    logger.info("Application startup: spawning background threads to pre-populate caches with live content...")
    # Spin up threads to load items in the background
    for _ in range(2):
        threading.Thread(target=replenish_article_cache, daemon=True).start()
        threading.Thread(target=replenish_video_cache, daemon=True).start()

# ── API Endpoints ──────────────────────────────────────────────────────────────
@app.post("/api/summarize")
def summarize_knowledge(req: SummarizeRequest):
    """
    Summarizes and explains the current knowledge item using Google GenAI SDK and Gemini with Search Grounding.
    """
    logger.info(f"Summarize request received for {req.source_type}: '{req.title}'")
    
    try:
        client = get_gemini_client()
    except Exception as e:
        logger.error(f"Failed to initialize GenAI client: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to initialize GenAI client: {str(e)}")

    if req.source_type == "Article":
        article_text = "\n\n".join(req.content) if req.content else ""
        prompt = (
            f"Please summarize and explain the key knowledge/ideas from this article in English. "
            f"Please also use Google Search to verify details and add any relevant context:\n"
            f"Title: {req.title}\n"
            f"Source: {req.source_name or 'Unknown'}\n"
            f"URL: {req.source_url or 'N/A'}\n"
            f"Topic: {req.topic or 'N/A'}\n\n"
            f"--- Article Content ---\n"
            f"{article_text}\n"
            f"-----------------------\n\n"
            f"Your output should be beautifully formatted in Markdown (heading levels 3 and 4, bullet points, key concepts in bold). "
            f"Outline the central message, explain any difficult scientific/philosophical/historical concepts in an engaging and easy-to-understand way, "
            f"and provide a list of key takeaways."
        )
    else:
        # Video
        prompt = (
            f"Please summarize and explain the key knowledge/ideas from this video in English. "
            f"Since we only have the metadata, you MUST use Google Search to search for the transcript, details, summaries, "
            f"or reviews about this specific video to generate a detailed summary:\n"
            f"Title: {req.title}\n"
            f"Channel: {req.channel or 'Unknown'}\n"
            f"URL: {req.source_url or 'N/A'}\n"
            f"Topic: {req.topic or 'N/A'}\n\n"
            f"Provide a thorough explanation in Markdown (heading levels 3 and 4) summarizing the video's content, "
            f"explaining the scientific/philosophical/historical concepts covered, and presenting a list of key takeaways."
        )

    try:
        tools = [{'type': 'google_search'}]
        generation_config = {
            'temperature': 1,
            'max_output_tokens': 65536,
            'top_p': 0.95,
        }

        interaction = client.interactions.create(
            model='models/gemini-2.5-flash',
            input=prompt,
            tools=tools,
            generation_config=generation_config,
        )

        output_text = interaction.output_text
        if not output_text and interaction.steps:
            last_step = interaction.steps[-1]
            if hasattr(last_step, 'content') and last_step.content:
                parts = last_step.content
                if isinstance(parts, list):
                    output_text = "".join(getattr(p, 'text', '') for p in parts)
                else:
                    output_text = getattr(parts, 'text', '')

        if not output_text:
            raise Exception("No text response generated from Gemini.")

        logger.info("Successfully generated summary via Gemini.")
        return {"summary": output_text}

    except Exception as e:
        logger.error(f"Error calling Gemini API: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Gemini API error: {str(e)}")

@app.get("/api/random-knowledge")
def get_random_knowledge(background_tasks: BackgroundTasks):
    """
    Returns a random piece of knowledge instantly from the in-memory cache.
    Decides randomly between Article (50%) and Video (50%).
    Schedules a background task to scrape a replacement item to keep the cache full.
    """
    logger.info("Received request for random knowledge")
    
    choice = random.choice(["Article", "Video"])
    logger.info(f"Popping item of type: {choice}")
    
    with cache_lock:
        if choice == "Article":
            if scraped_articles_cache:
                result = scraped_articles_cache.pop(0)
                logger.info(f"Popped article '{result.get('title')}' from cache. Left in cache: {len(scraped_articles_cache)}")
                background_tasks.add_task(replenish_article_cache)
                return result
            else:
                logger.warning("Article cache is empty! Returning fallback item and triggering replenishment...")
                background_tasks.add_task(replenish_article_cache)
                return random.choice(FALLBACK_ARTICLES)
        else: # Video
            if scraped_videos_cache:
                result = scraped_videos_cache.pop(0)
                logger.info(f"Popped video '{result.get('title')}' from cache. Left in cache: {len(scraped_videos_cache)}")
                background_tasks.add_task(replenish_video_cache)
                return result
            else:
                logger.warning("Video cache is empty! Returning fallback item and triggering replenishment...")
                background_tasks.add_task(replenish_video_cache)
                return random.choice(FALLBACK_VIDEOS)

# ── Static Frontend Serving ────────────────────────────────────────────────────
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")