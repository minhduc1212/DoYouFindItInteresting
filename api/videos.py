"""
Videos Module
Handles dynamic scraping of video details from YouTube channels,
and formatting fallback database items.
"""

import random
import logging
from urllib.parse import urlparse, parse_qs
from typing import Optional, Tuple, Dict, List
import yt_dlp

logger = logging.getLogger("api.videos")
from api.config import CHANNELS_BY_TOPIC

MOCK_VIDEOS = [
    {
        "title": "The CAP Theorem: Why Distributed Systems Can't Have Everything",
        "url": "https://www.youtube.com/watch?v=BHqjEjzAicA",
        "video_id": "BHqjEjzAicA",
        "channel": "System Design School",
        "topic": "Economics & Society"
    },
    {
        "title": "Git Internals: What Actually Happens When You Commit",
        "url": "https://www.youtube.com/watch?v=lG90LZotrpo",
        "video_id": "lG90LZotrpo",
        "channel": "Code Explainer",
        "topic": "Computer Science & Programming"
    }
]

def extract_youtube_id(url: str) -> Optional[str]:
    """Parses a YouTube URL to extract its video ID."""
    if not url:
        return None
    parsed_url = urlparse(url)
    if parsed_url.netloc in ("youtu.be", "www.youtu.be"):
        return parsed_url.path.lstrip('/')
    else:
        video_ids = parse_qs(parsed_url.query).get('v')
        return video_ids[0] if video_ids else None

def get_random_video_from_channel(channel_handle: str) -> Optional[Tuple[str, str]]:
    """Get a random video (URL and title) from a YouTube channel handle."""
    try:
        ydl_opts = {
            'extract_flat': 'in_playlist',
            'quiet': True,
            'simulate': True,
            'playlist_end': 100,  # limit to last 100 videos
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            url = f"https://www.youtube.com/{channel_handle}/videos"
            result = ydl.extract_info(url, download=False)
            
            if not result or 'entries' not in result:
                return None
                
            entries = list(result['entries'])
            if not entries:
                return None
                
            video = random.choice(entries)
            
            video_url = video.get('url', '')
            title = video.get('title', 'Unknown Title')
            
            if video_url and not video_url.startswith('http'):
                video_url = f"https://www.youtube.com/watch?v={video_url}"
                
            video_id = video.get('id')
            if video_id and not video_url:
                video_url = f"https://www.youtube.com/watch?v={video_id}"
                
            return video_url, title
    except Exception as e:
        logger.error(f"Error fetching videos for {channel_handle}: {e}")
        return None

def get_scraped_video() -> dict:
    """Scrapes a random video dynamically."""
    all_channels = []
    for topic, channels in CHANNELS_BY_TOPIC.items():
        for ch in channels:
            all_channels.append({'handle': ch, 'topic': topic})
            
    random.shuffle(all_channels)
    
    selected_video = None
    max_attempts = 8
    attempt = 0
    
    for ch_info in all_channels:
        attempt += 1
        if attempt > max_attempts:
            break
            
        video_info = get_random_video_from_channel(ch_info['handle'])
        if not video_info:
            continue
            
        video_url, video_title = video_info
        video_id = extract_youtube_id(video_url)
        if not video_id:
            continue
            
        selected_video = {
            'title': video_title,
            'url': video_url,
            'video_id': video_id,
            'channel': ch_info['handle'],
            'topic': ch_info['topic']
        }
        break

    if not selected_video:
        raise Exception("Failed to scrape a valid video.")

    return {
        "source_type": "Video",
        "title": selected_video['title'],
        "source_url": selected_video['url'],
        "video_id": selected_video['video_id'],
        "channel": selected_video['channel'],
        "topic": selected_video['topic']
    }

def get_fallback_video() -> dict:
    """Returns a random in-memory mock video formatted for the frontend."""
    video = random.choice(MOCK_VIDEOS)
    return {
        "source_type": "Video",
        "title": video["title"],
        "source_url": video["url"],
        "video_id": video["video_id"],
        "channel": video["channel"],
        "topic": video["topic"]
    }
