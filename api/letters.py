"""
Letters/Articles Module
Handles dynamic scraping of articles from predefined sources and formatting fallback database items.
"""

import re
import random
import requests
import logging
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
from api.config import HEADERS, SITES_BY_TOPIC

logger = logging.getLogger("api.letters")

# Module-level requests Session for connection pooling/Keep-Alive
session = requests.Session()



def is_valid_article_url(url: str, base_url: str, strict: bool = True) -> bool:
    """Determines whether a URL looks like an actual article/post rather than a utility or landing page."""
    parsed_base = urlparse(base_url)
    parsed_url = urlparse(url)
    
    # Ensure it belongs to the same domain
    base_domain = parsed_base.netloc.replace('www.', '')
    cand_domain = parsed_url.netloc.replace('www.', '')
    if not cand_domain.endswith(base_domain):
        return False
        
    path = parsed_url.path.lower()
    
    # Exclude common utility/navigational/landing links
    exclude_keywords = [
        'about', 'contact', 'privacy', 'terms', 'cookie', 'subscribe', 'jobs', 'career',
        'help', 'newsletter', 'sign-in', 'login', 'register', 'cart', 'checkout', 'wp-admin',
        'wp-content', 'wp-includes', 'index.php', 'wp-json', 'search', 'category', 'categories',
        'tag', 'tags', 'author', 'authors', 'archive', 'archives', 'feed', 'rss', 'page', 'pages',
        'topics', 'topic', 'subject', 'subjects', 'series', 'collections', 'collection',
        'issue', 'issues', 'videos', 'podcasts', 'newsletters', 'news', 'blog', 'blogs'
    ]
    for kw in exclude_keywords:
        if kw in path or kw in parsed_url.query.lower():
            return False
            
    # Exclude homepage / empty paths
    path_strip = path.strip('/')
    if not path_strip or path_strip in ['index.html', 'index.htm', 'index.php']:
        return False
        
    # Heuristics for detecting slugs/articles
    segments = [s for s in path_strip.split('/') if s]
    if not segments:
        return False
        
    last_segment = segments[-1]
    
    # Exclude image or non-article assets
    if last_segment.endswith(('.png', '.jpg', '.jpeg', '.gif', '.pdf', '.txt', '.xml', '.json')):
        return False
        
    if strict:
        # Article slugs typically have multiple hyphens, underscores, or digits
        has_slug_pattern = (last_segment.count('-') >= 3) or (last_segment.count('_') >= 3) or re.search(r'\d{4,}', last_segment)
        if not has_slug_pattern and len(segments) < 2:
            return False
    else:
        # Non-strict fallback mode: require the last segment to have some complexity.
        # This prevents simple sub-genre pages (e.g. /science/, /maths/, /health/) from matching.
        has_complexity = (len(last_segment) >= 15) or (last_segment.count('-') >= 2) or (last_segment.count('_') >= 2) or any(c.isdigit() for c in last_segment)
        if not has_complexity:
            return False
            
    return True

def get_article_links(site_url: str) -> list:
    """Fetches the homepage and extracts potential article URLs."""
    try:
        response = session.get(site_url, headers=HEADERS, timeout=3)
        response.raise_for_status()
    except Exception as e:
        logger.warning(f"Error fetching homepage {site_url}: {e}")
        return []
        
    soup = BeautifulSoup(response.text, 'html.parser')
    links = []
    
    for a in soup.find_all('a', href=True):
        href = a['href']
        full_url = urljoin(site_url, href)
        parsed = urlparse(full_url)
        normalized_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        
        if is_valid_article_url(normalized_url, site_url, strict=True):
            links.append(normalized_url)
            
    # Fallback to moderate/loose heuristics if strict returns nothing
    if not links:
        for a in soup.find_all('a', href=True):
            href = a['href']
            full_url = urljoin(site_url, href)
            parsed = urlparse(full_url)
            normalized_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            
            if is_valid_article_url(normalized_url, site_url, strict=False):
                links.append(normalized_url)
                
    return list(set(links))

def extract_content(article_url: str) -> dict:
    """Scrapes the article URL and extracts the main content (title and body paragraphs)."""
    try:
        response = session.get(article_url, headers=HEADERS, timeout=3)
        response.raise_for_status()
    except Exception as e:
        logger.warning(f"Error fetching article {article_url}: {e}")
        return None
        
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # Title extraction
    title = None
    h1 = soup.find('h1')
    if h1:
        title = h1.get_text(strip=True)
    if not title:
        title_tag = soup.find('title')
        if title_tag:
            title = title_tag.get_text(strip=True)
    if not title:
        title = "Untitled Article"
        
    # Look for common article containers to limit boilerplate
    content_selectors = [
        ('article', {}),
        ('main', {}),
        ('div', {'id': re.compile(r'article-body|post-body|entry-content|article-content|main-content', re.I)}),
        ('div', {'class': re.compile(r'article-body|post-body|entry-content|article-content|main-content|story-content', re.I)}),
        ('section', {'class': re.compile(r'article|post|entry|content', re.I)}),
    ]
    
    body_container = None
    for tag, attrs in content_selectors:
        body_container = soup.find(tag, attrs)
        if body_container:
            break
            
    source_elem = body_container if body_container else soup
    paragraphs = source_elem.find_all('p')
    
    cleaned_paras = []
    boilerplate_indicators = [
        'subscribe to', 'sign up for', 'newsletter', 'follow us on',
        'cookie policy', 'privacy policy', 'terms of service', 'copyright ©',
        'all rights reserved', 'read more:', 'photo:', 'image credit:'
    ]
    
    for p in paragraphs:
        text = p.get_text(strip=True)
        # Skip very short paragraphs
        if len(text) < 40:
            continue
            
        # Filter typical boilerplate text
        text_lower = text.lower()
        is_boilerplate = False
        for indicator in boilerplate_indicators:
            if indicator in text_lower and len(text) < 150:
                is_boilerplate = True
                break
                
        if not is_boilerplate:
            cleaned_paras.append(text)
            
    # Fallback to general paragraph collection if too little content was extracted
    if body_container and len(cleaned_paras) < 3:
        paragraphs = soup.find_all('p')
        cleaned_paras = []
        for p in paragraphs:
            text = p.get_text(strip=True)
            if len(text) < 40:
                continue
            text_lower = text.lower()
            is_boilerplate = False
            for indicator in boilerplate_indicators:
                if indicator in text_lower and len(text) < 150:
                    is_boilerplate = True
                    break
            if not is_boilerplate:
                cleaned_paras.append(text)
                
    return {
        'title': title,
        'paragraphs': cleaned_paras
    }

def get_scraped_article() -> dict:
    """Scrapes a random article dynamically."""
    all_sites = []
    for topic, entries in SITES_BY_TOPIC.items():
        for name, url in entries:
            all_sites.append({'name': name, 'url': url, 'topic': topic})
            
    random.shuffle(all_sites)
    
    selected_site = None
    selected_article_url = None
    content = None
    max_attempts = 3
    attempt = 0
    
    for site in all_sites:
        attempt += 1
        if attempt > max_attempts:
            break
            
        article_links = get_article_links(site['url'])
        if not article_links:
            continue
            
        random.shuffle(article_links)
        for article_url in article_links[:2]:
            extracted = extract_content(article_url)
            if extracted and len(extracted['paragraphs']) >= 3 and sum(len(p) for p in extracted['paragraphs']) >= 400:
                selected_site = site
                selected_article_url = article_url
                content = extracted
                break
                
        if selected_site:
            break

    if not selected_site or not content:
        raise Exception("Failed to scrape a valid article dynamically.")

    return {
        "source_type": "Article",
        "title": content['title'],
        "source_url": selected_article_url,
        "source_name": selected_site['name'],
        "topic": selected_site['topic'],
        "content": content['paragraphs']
    }

