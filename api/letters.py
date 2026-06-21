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


MOCK_ARTICLES = [
    {
        "title": "How Transformers Revolutionized Natural Language Processing",
        "source_url": "https://arxiv.org/abs/1706.03762",
        "content": [
            "Before the Transformer architecture arrived in 2017, sequence modeling relied heavily on recurrent neural networks and their gated variants like LSTM and GRU. These models processed tokens one by one, making parallelization nearly impossible during training. The Transformer solved this bottleneck with a mechanism called self-attention, which allows every token in a sequence to directly attend to every other token simultaneously.",
            "Instead of recurrence, positional encoding is injected into the input embeddings to preserve word order. The model stacks multiple layers of multi-head attention and feed-forward networks, enabling it to capture both local syntax and long-range semantic dependencies with remarkable efficiency. This architecture became the backbone of models like BERT, GPT, and T5, fundamentally reshaping how machines understand language."
        ]
    },
    {
        "title": "Understanding Docker: Containers vs. Virtual Machines",
        "source_url": "https://www.docker.com/resources/what-container/",
        "content": [
            "A container is a lightweight, portable unit that packages an application along with its dependencies, libraries, and configuration into a single runnable artifact. Unlike a virtual machine, a container does not include a full guest operating system. Instead, containers share the host kernel and isolate processes using Linux namespaces and control groups (cgroups). This makes containers dramatically faster to start and far more memory-efficient than VMs.",
            "Docker popularized containers by providing a simple CLI and a layered image format based on a union file system. Each instruction in a Dockerfile creates an immutable layer — unchanged layers are cached and reused, which accelerates builds significantly. Docker Compose extends this by letting you define multi-container applications in a single YAML manifest, orchestrating services like a web server, a database, and a cache together."
        ]
    },
    {
        "title": "How WebAssembly is Blurring the Line Between Native and Web",
        "source_url": "https://webassembly.org/getting-started/developers-guide/",
        "content": [
            "WebAssembly (Wasm) is a binary instruction format designed as a portable compilation target for languages like C, C++, and Rust. Unlike JavaScript, which is parsed and JIT-compiled at runtime, Wasm is delivered as a pre-compiled binary, enabling near-native execution speeds inside the browser sandbox. The browser's JavaScript engine validates and compiles Wasm modules using ahead-of-time (AOT) compilation.",
            "Wasm runs in the same sandboxed environment as JS and cannot directly access the DOM — it communicates with JavaScript via a Foreign Function Interface (FFI). This makes it ideal for performance-critical tasks like video encoding, 3D rendering, cryptography, and physics simulations. Beyond the browser, the WASI (WebAssembly System Interface) standard is pushing Wasm into server-side and edge computing environments as a universal, secure, and portable runtime."
        ]
    }
]

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
    
    # Exclude common utility/navigational links
    exclude_keywords = [
        'about', 'contact', 'privacy', 'terms', 'cookie', 'subscribe', 'jobs', 'career',
        'help', 'newsletter', 'sign-in', 'login', 'register', 'cart', 'checkout', 'wp-admin',
        'wp-content', 'wp-includes', 'index.php', 'wp-json', 'search', 'category', 'tag', 'author'
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
        
    if strict:
        last_segment = segments[-1]
        # Article slugs typically have multiple hyphens, underscores, or digits
        has_slug_pattern = (last_segment.count('-') >= 3) or (last_segment.count('_') >= 3) or re.search(r'\d{4,}', last_segment)
        if not has_slug_pattern and len(segments) < 2:
            return False
            
    return True

def get_article_links(site_url: str) -> list:
    """Fetches the homepage and extracts potential article URLs."""
    try:
        response = requests.get(site_url, headers=HEADERS, timeout=10)
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
        response = requests.get(article_url, headers=HEADERS, timeout=10)
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
    max_attempts = 10
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

def get_fallback_article() -> dict:
    """Returns a random in-memory mock article formatted for the frontend."""
    art = random.choice(MOCK_ARTICLES)
    return {
        "source_type": "Article",
        "title": art["title"],
        "source_url": art["source_url"],
        "source_name": "In-Memory Fallback",
        "topic": "General",
        "content": art["content"]
    }
