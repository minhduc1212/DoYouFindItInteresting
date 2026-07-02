"""
Today I Learned (TIL) - FastAPI Backend
Serves random knowledge snippets (articles and videos with transcripts) combined into a single random feed.
Completely database-free: relies on live scraping and in-memory mock data fallbacks.
"""

import os
import sys
import random
import logging
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

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

from api.letters import get_scraped_article
from api.videos import get_scraped_video

app = FastAPI(title="Do You Find It Interesting API", version="1.0.0")

# ── API Endpoints ──────────────────────────────────────────────────────────────
@app.get("/api/random-knowledge")
def get_random_knowledge():
    """
    Returns a random piece of knowledge.
    Decides randomly between Article (50%) and Video (50%).
    Scrapes content live, falling back to local in-memory fallback data on failure.
    """
    logger.info("Received request for random knowledge")
    choices = ["Article", "Video"]
    random.shuffle(choices)
    
    for choice in choices:
        try:
            logger.info(f"Attempting live scrape for {choice}...")
            if choice == "Article":
                result = get_scraped_article()
                logger.info(f"Successfully scraped article: '{result.get('title')}'")
                return result
            else:
                result = get_scraped_video()
                logger.info(f"Successfully scraped video: '{result.get('title')}'")
                return result
        except Exception as e:
            logger.warning(f"Live scrape failed for {choice}: {e}. Trying alternate option...")
            continue

    # All scraping failed: raise a 503 Service Unavailable error
    logger.error("All live scraping attempts failed.")
    raise HTTPException(status_code=503, detail="All scraping attempts failed. Please try again.")

# ── Static Frontend Serving ────────────────────────────────────────────────────
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")