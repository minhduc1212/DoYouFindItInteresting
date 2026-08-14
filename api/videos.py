"""
Videos Module
Handles dynamic scraping of video details from YouTube channels,
and formatting fallback database items.
"""

import re
import random
import logging
import requests
import xml.etree.ElementTree as ET
from urllib.parse import urlparse, parse_qs
from typing import Optional, Tuple

logger = logging.getLogger("api.videos")
from api.config import CHANNELS_BY_TOPIC, CHANNEL_FEEDS, HEADERS

# Module-level requests Session for connection pooling/Keep-Alive
session = requests.Session()


def extract_youtube_id(url: str) -> Optional[str]:
    """Parses a YouTube URL (watch, shorts, embed, live, youtu.be) to extract its video ID."""
    if not url:
        return None
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    segs = [s for s in parsed.path.strip('/').split('/') if s]

    if host in ('youtu.be', 'www.youtu.be') or host.endswith('youtube-nocookie.com'):
        candidate = segs[-1] if segs else None
    else:
        v = parse_qs(parsed.query).get('v')
        candidate = v[0] if v else None
        if not candidate and segs and segs[0] in ('shorts', 'embed', 'live', 'v'):
            candidate = segs[1] if len(segs) > 1 else None

    if not candidate:
        return None
    if re.fullmatch(r'[A-Za-z0-9_-]{11}', candidate):
        return candidate
    if re.fullmatch(r'[A-Za-z0-9_-]{6,16}', candidate):
        return candidate
    return None


def get_random_video_from_channel(channel_handle: str) -> Optional[Tuple[str, str, Optional[str]]]:
    """Get a random video (URL, title, thumbnail) from a YouTube channel handle using its RSS feed."""
    rss_url = CHANNEL_FEEDS.get(channel_handle)
    if not rss_url:
        logger.warning(f"No RSS URL found for channel handle: {channel_handle}")
        return None

    try:
        response = session.get(rss_url, headers=HEADERS, timeout=10)
        response.raise_for_status()

        root = ET.fromstring(response.content)
        namespace = {
            'atom': 'http://www.w3.org/2005/Atom',
            'yt': 'http://www.youtube.com/xml/schemas/2015',
            'media': 'http://search.yahoo.com/mrss/',
        }
        entries = root.findall('atom:entry', namespace)

        if not entries:
            logger.warning(f"No entries found in RSS feed for {channel_handle}")
            return None

        entry = random.choice(entries)

        video_id_el = entry.find('yt:videoId', namespace)
        title_el = entry.find('atom:title', namespace)
        link_el = entry.find('atom:link', namespace)

        video_id = video_id_el.text if video_id_el is not None else None
        title = title_el.text if title_el is not None else "Unknown Title"

        if not video_id:
            return None

        video_url = link_el.attrib.get('href') if link_el is not None else f"https://www.youtube.com/watch?v={video_id}"

        # Thumbnail from the RSS media namespace (fallback handled by caller)
        thumb_el = entry.find('media:group/media:thumbnail', namespace) or entry.find('media:thumbnail', namespace)
        thumb_url = thumb_el.attrib.get('url') if thumb_el is not None else None

        return video_url, title, thumb_url
    except Exception as e:
        logger.error(f"Error fetching RSS videos for {channel_handle}: {e}")
        return None


def get_scraped_video() -> dict:
    """Scrapes a random video dynamically."""
    all_channels = []
    for topic, channels in CHANNELS_BY_TOPIC.items():
        for ch in channels:
            all_channels.append({'handle': ch, 'topic': topic})

    random.shuffle(all_channels)

    selected_video = None
    max_attempts = 3
    attempt = 0

    for ch_info in all_channels:
        attempt += 1
        if attempt > max_attempts:
            break

        video_info = get_random_video_from_channel(ch_info['handle'])
        if not video_info:
            continue

        video_url, video_title, rss_thumb = video_info
        video_id = extract_youtube_id(video_url)
        if not video_id:
            continue

        thumbnail_url = rss_thumb or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"

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
        "topic": selected_video['topic'],
        "thumbnail_url": thumbnail_url
    }
