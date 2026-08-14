"""
Letters/Articles Module
Handles dynamic scraping of articles from predefined sources and formatting fallback database items.
"""

import re
import random
import requests
import logging
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin, parse_qs
from api.config import HEADERS, SITES_BY_TOPIC

logger = logging.getLogger("api.letters")

# Module-level requests Session for connection pooling/Keep-Alive
session = requests.Session()


# ── URL-level hub sets ──────────────────────────────────────────────────────────
# Shared by BOTH the fast heuristic (is_valid_article_url) and the deep gate
# (_is_real_article) so the two layers can never drift out of sync. Exact
# last-segment match only — never substring (a slug like "the-live-music-experience"
# must not be caught by "video").
_TERMINAL_HUBS = {
    # generic utility / listing pages
    'about', 'about-us', 'contact', 'contact-us', 'privacy', 'privacy-policy',
    'terms', 'terms-of-service', 'terms-and-conditions', 'cookie-policy',
    'cookie-declaration', 'subscribe', 'subscription', 'newsletter',
    'newsletter-subscribe', 'jobs', 'careers', 'career', 'help', 'faq', 'sign-in',
    'signin', 'login', 'register', 'signup', 'log-in', 'cart', 'checkout', 'search',
    'feed', 'rss', 'rss-feeds', 'atom', 'author', 'authors', 'category', 'categories',
    'tag', 'tags', 'topic', 'topics', 'subject', 'subjects', 'archive', 'archives',
    'index', 'page', 'blog', 'blogs', 'news', 'podcast', 'podcasts', 'videos',
    'video', 'features', 'essays', 'articles', 'magazine', 'shop', 'store',
    'sitemap', '404', 'donate', 'donation', 'support', 'submit', 'guidelines',
    'writers-guidelines', 'fulfillment-policies', 'membership', 'membership-account',
    'membership-levels', 'renew-membership', 'gift-membership', 'media-center',
    'press-room', 'pressroom', 'press-center', 'newsroom', 'our-team', 'follow-us',
    'get-in-touch', 'action-center', 'how-tos', 'audio-edition', 'videos-visuals',
    'sci-tech', 'night-sky',
    # brand-specific section/utility slugs (exact, zero false-positive risk)
    'article-short', 'planetary-report', 'planetary-radio', 'uiv-book',
    'a-velocity-of-being', 'code-of-ethics', 'gift-acceptance-practices',
    'freelance-pitches', 'local-reporting-network', 'submit-neuroscience-news',
    'neuroscience-news-sitemap', 'support-3qd',
    # promo / landing / section pages that pass the generic hub words but are
    # not real articles (exact terminal slugs found by the leak scan)
    'awards-and-press', 'planetary-academy', 'defend-earth', 'explore-worlds',
    'save-nasa-science', 'space-missions', 'behavioral-scientist-in-print',
    'neuroscience-programs', 'interactive-travel', 'cancel-recurring-donation',
    'knowledge-project-podcast-chat', 'steal-our-stories',
}

_STRUCTURAL_HUBS = {
    'category', 'categories', 'tag', 'tags', 'author', 'authors', 'archive',
    'archives', 'collection', 'collections', 'series', 'feed', 'rss', 'search',
    'topic', 'topics', 'subject', 'subjects', 'videos', 'video', 'page', 'issues',
    'quiz', 'quizzes', 'about', 'about-us', 'donate', 'campaign',
    # taxonomy archives (Behavioral Scientist /fields/ + /formats/, JSTOR /type/,
    # PsyPost /exclusive/ + /membership-account/, Archaeology /department/):
    # these mid-path sections never contain real articles
    'department', 'fields', 'formats', 'type', 'exclusive', 'membership-account',
}


# ── Hub-title patterns (deep gate) ───────────────────────────────────────────────
# 'news' appears only as an EXACT match or ENDING word — never as a leading word —
# because Archaeology's real articles are titled "News - Colonial-Era ..." and Hakai
# publishes real articles under /news/, while the taxonomy leaks end in "… News" /
# "… Archives" ("Education & Learning News", "Political Science Archives").
_HUB_TITLE_LEAD = re.compile(
    r'^(favorite|favorites|must[-_ ]?read|reading[-_ ]?list|recommended|top[-_ ]?stories'
    r'|trending|editors?[-_ ]?picks|round[-_ ]?up|archive|archives|category|categories'
    r'|tag|tags|topics?|search|author|authors|listing|index|about|about[-_ ]?us'
    r'|our[-_ ]?team|meet[-_ ]?the[-_ ]?team|media[-_ ]?center|press[-_ ]?room'
    r'|press[-_ ]?center|newsroom|contact|faq|support|submit|subscribe|newsletter'
    r'|membership|donate|donation|sitemap|guidelines?|writers?[-_ ]?guidelines'
    r'|follow[-_ ]?us|log[-_ ]?in|sign[-_ ]?in|terms?[-_ ]?and[-_ ]?conditions'
    r'|cookie[-_ ]?declaration|fulfillment[-_ ]?policies|action[-_ ]?center'
    r'|code[-_ ]?of[-_ ]?ethics|quick[-_ ]?reads?|audio[-_ ]?edition|rss[-_ ]?feeds?)\b', re.I)

_HUB_TITLE_END = re.compile(r'\b(news|newsletters?|archives?|sitemaps?)\s*$', re.I)

_HUB_TITLE_EXACT = {
    'news', 'blog', 'blogs', 'videos', 'video', 'contact', 'about', 'faq', 'home',
    'subscribe', 'sitemap', 'support', 'donate', 'guides', 'archives', 'archive',
    'search', 'login', 'sign in', 'log in', 'categories', 'category', 'tags', 'tag',
}


def _looks_like_hub_title(title_text: str, og_title: str, site_name: str) -> bool:
    """True when the <title> or og:title reads as a landing/hub/taxonomy page."""
    for raw in (title_text, og_title):
        if not raw:
            continue
        core = _strip_site_suffix(raw.strip(), site_name)
        if not core:
            continue
        lower = core.lower()
        if lower in _HUB_TITLE_EXACT:
            return True
        if _HUB_TITLE_LEAD.search(lower) or _HUB_TITLE_END.search(lower):
            return True
    return False


def is_valid_article_url(url: str, base_url: str, strict: bool = True) -> bool:
    """Determines whether a URL looks like an actual article/post rather than a utility or landing page."""
    parsed_base = urlparse(base_url)
    parsed_url = urlparse(url)

    # 1. Same-domain check (exact match or subdomain — no lookalikes)
    base_domain = parsed_base.netloc.replace('www.', '').lower()
    cand_domain = parsed_url.netloc.replace('www.', '').lower()
    if cand_domain != base_domain and not cand_domain.endswith('.' + base_domain):
        return False

    path = parsed_url.path.lower()
    path_strip = path.strip('/')

    # 2. Reject empty / index paths
    if not path_strip or path_strip in ('index.html', 'index.htm', 'index.php'):
        return False

    # 3. Exclude image or non-article assets
    if path_strip.endswith(('.png', '.jpg', '.jpeg', '.gif', '.pdf', '.txt', '.xml', '.json')):
        return False

    segments = [s for s in path_strip.split('/') if s]
    if not segments:
        return False

    # 4. Terminal hub pages — exact last-segment match only (no substring)
    if segments[-1] in _TERMINAL_HUBS:
        return False

    # 5. Structural mid-path hubs — any non-last segment that is a listing/taxonomy path
    if any(seg in _STRUCTURAL_HUBS for seg in segments[:-1]):
        return False

    # 6. Listing-style query params
    listing_params = {'s', 'search', 'query', 'q', 'cat', 'category', 'tag', 'paged'}
    query_keys = set(parse_qs(parsed_url.query).keys())
    if query_keys & listing_params:
        return False

    # 7. Strict mode: article slugs usually contain hyphens, underscores, or digits
    if strict:
        last_segment = segments[-1]
        has_marker = ('-' in last_segment) or ('_' in last_segment) or any(c.isdigit() for c in last_segment)
        if not has_marker:
            if len(segments) == 1:
                return False
            # Multi-segment: require a date-like segment (digit) somewhere before the last
            if not any(any(c.isdigit() for c in s) for s in segments[:-1]):
                return False

    return True


def get_article_links(site_url: str) -> list:
    """Fetches the homepage and extracts potential article URLs."""
    try:
        response = session.get(site_url, headers=HEADERS, timeout=10)
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
        # Keep the query string (some sites key articles by it); drop only the fragment
        normalized_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        if parsed.query:
            normalized_url += f"?{parsed.query}"

        if is_valid_article_url(normalized_url, site_url, strict=True):
            links.append(normalized_url)

    # Fallback to moderate/loose heuristics if strict returns nothing
    if not links:
        for a in soup.find_all('a', href=True):
            href = a['href']
            full_url = urljoin(site_url, href)
            parsed = urlparse(full_url)
            normalized_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            if parsed.query:
                normalized_url += f"?{parsed.query}"

            if is_valid_article_url(normalized_url, site_url, strict=False):
                links.append(normalized_url)

    return list(set(links))


# ── HTML helpers ────────────────────────────────────────────────────────────────

def _meta_content(soup, key: str):
    """Reads a <meta> tag's content by property or name attribute."""
    el = soup.find('meta', attrs={'property': key}) or soup.find('meta', attrs={'name': key})
    if el and el.get('content'):
        return el['content'].strip()
    return None


def _is_real_article(soup, site_name_hint: str = '', article_url: str = '') -> bool:
    """
    Gate that rejects listing / category / utility / video pages before content extraction.
    Returns True only when the page looks like an actual article.
    """
    # Video/watch pages — must run before the og:type short-circuit: sites like Aeon
    # stamp og:type='article' on their video pages too. Exact path-segment match so a
    # slug like "the-live-music-experience" is not caught.
    if article_url:
        segs = urlparse(article_url).path.lower().strip('/').split('/')
        # Video/watch pages — exact path-segment match so a slug like
        # "the-live-music-experience" is not caught.
        if any(s in ('video', 'videos') for s in segs) or (segs and segs[0] in ('watch', 'embed', 'shorts', 'clips')):
            return False
        # Terminal + structural hub URLs (shared sets with the fast heuristic).
        # Runs before the og:type short-circuit because WordPress stamps
        # og:type='article' on taxonomy/utility pages too.
        if segs and segs[-1] in _TERMINAL_HUBS:
            return False
        if any(s in segs[:-1] for s in _STRUCTURAL_HUBS):
            return False

    og_type = _meta_content(soup, 'og:type')
    if og_type:
        og_type = og_type.lower()
    site_name = _meta_content(soup, 'og:site_name') or site_name_hint or ''
    title_tag = soup.find('title')
    title_text = title_tag.get_text(strip=True) if title_tag else ''
    h1s = soup.find_all('h1')
    articles = soup.find_all('article')

    # Hub-page title check — MUST run before the og:type short-circuit: WordPress
    # stamps og:type='article' on every page, so a bare hub title like
    # "favorite reads" would otherwise pass immediately. Tests both the <title>
    # and og:title (some sites put the hub word only in one of them).
    og_title = _meta_content(soup, 'og:title') or _meta_content(soup, 'twitter:title')
    if _looks_like_hub_title(title_text, og_title, site_name):
        return False

    # Members-gate / paywall landing pages (e.g. Visual Capitalist's "VC+ Archive"):
    # the first <h1> announces a members-only area, not an article title. This must
    # run before the og:type short-circuit — WordPress stamps og:type='article' on
    # these pages too.
    for h in h1s[:2]:
        if re.search(r'members?\s+(only|area|zone)\b|paywall\b|premium\s+members?', h.get_text(strip=True).lower()):
            return False

    if og_type == 'article':
        return True
    if og_type and og_type not in ('article', 'website'):
        return False
    # og:type is None or 'website' — a real article page almost always carries og:title.
    # Section/category landing pages (e.g. space.com/space-exploration) typically don't.
    if not (_meta_content(soup, 'og:title') or _meta_content(soup, 'twitter:title')):
        return False
    if not h1s:
        return False
    if not articles:
        return False
    if len(articles) > 3:
        return False
    if site_name and title_text.lower() in (site_name.lower(), site_name.lower() + ' - home'):
        return False
    return True


def _find_meta_image(soup):
    """Finds a representative image from OpenGraph / Twitter meta tags."""
    for prop in ('og:image', 'og:image:url', 'og:image:secure_url',
                 'twitter:image', 'twitter:image:src', 'article:image'):
        url = _meta_content(soup, prop)
        if url:
            return url.strip()
    link = soup.find('link', attrs={'rel': 'image_src'})
    if link and link.get('href'):
        return link['href'].strip()
    return None


def _find_container_image(container, base_url: str):
    """Finds a content image inside the article container, skipping logos/ads/placeholders."""
    if container is None:
        return None
    bad_class = re.compile(r'logo|avatar|icon|spacer|track|pixel|advert|banner|share|button|arrow|svg|sprite|favicon', re.I)
    src_attrs = ('src', 'data-src', 'data-lazy-src', 'data-original', 'data-url', 'data-lazy', 'data-srcset', 'srcset')

    for img in container.find_all('img'):
        cls = ' '.join(img.get('class', []) or [])
        if bad_class.search(cls):
            continue
        try:
            width = img.get('width')
            height = img.get('height')
            if width and int(width) < 120:
                continue
            if height and int(height) < 90:
                continue
        except (TypeError, ValueError):
            pass

        for attr in src_attrs:
            raw = img.get(attr)
            if not raw:
                continue
            candidate = raw.strip().split(' ')[0]
            if not candidate or candidate.startswith('data:'):
                continue
            if candidate.startswith('//'):
                candidate = 'https:' + candidate
            return urljoin(base_url, candidate)
    return None


def _strip_boilerplate(container):
    """Removes navigation / ads / related links from the content container in place."""
    if container is None:
        return
    for sel in ('aside', 'nav', 'script', 'style', 'noscript', 'iframe', 'form', 'button', 'header', 'footer'):
        for el in container.find_all(sel):
            el.decompose()
    # Word-boundary-wrapped so a keyword like "promo" can't match inside a longer
    # legitimate class token (e.g. The Conversation's "inline-promos" content wrapper).
    boiler_classes = re.compile(
        r'\b(?:related|recommended|share|author-bio|byline|newsletter|subscribe|promo'
        r'|advert|advertisement|comments|tags|social|see-also|more-articles'
        r'|recommended-reading|read-more|related-articles)\b', re.I)
    for el in container.find_all(['div', 'section', 'aside']):
        if el.parent is None:
            continue  # already detached by an ancestor's decompose (bs4 invalidates .attrs)
        cls = ' '.join(el.get('class', []) or [])
        if boiler_classes.search(cls):
            el.decompose()
    for el in container.find_all('figure'):
        el.decompose()


def _strip_site_suffix(t: str, site_name: str) -> str:
    """Removes a trailing 'SEP SiteName' / 'SEP SiteName <section>' from a title."""
    if not t or not site_name:
        return t
    site_lower = site_name.strip().lower()
    t = t.strip()
    if not t or not site_lower:
        return t
    # Separator forms: "Title | Site" / "Title – Site" / "Title » Site" / "Title • Site"
    # / "Title -- Site" (Science Daily)
    parts = re.split(r'\s*(?:[|–—»•]|--)\s*', t)
    if len(parts) > 1:
        last = parts[-1].strip().lower()
        if last == site_lower or last.startswith(site_lower + ' '):
            return ' '.join(p.strip() for p in parts[:-1])
    # Plain-hyphen form: "Title - Site" (only strip when the tail matches the site name)
    m = re.search(r'\s-\s+(.+)$', t)
    if m:
        last = m.group(1).strip().lower()
        if last == site_lower or last.startswith(site_lower + ' '):
            return t[:m.start()].strip()
    # Sites that never set og:site_name (e.g. Aeon): the trailing segment shares the
    # site's first meaningful word — "… | Aeon Essays" vs site "Aeon Magazine" → "aeon".
    if parts and len(parts) > 1:
        bare = re.sub(r'^(?:the|a|an)\s+', '', site_lower)
        site_word = bare.split()[0] if bare.split() else ''
        if len(site_word) >= 4 and parts[-1].strip().lower().split()[0] == site_word:
            return ' '.join(p.strip() for p in parts[:-1])
    return t


def _extract_title(soup, body_container, site_name: str) -> str:
    """Extracts the article title with a robust priority chain."""
    # 1. Structured meta (og:title / twitter:title)
    for prop in ('og:title', 'twitter:title'):
        t = _meta_content(soup, prop)
        if t:
            return _strip_site_suffix(t, site_name)

    # 2. h1/h2 scoped inside the content container (fallback: <article>)
    scope = body_container or soup.find('article') or soup
    for tag in ('h1', 'h2'):
        for el in scope.find_all(tag):
            t = el.get_text(strip=True)
            if not t:
                continue
            if site_name and t.lower() == site_name.lower():
                continue
            return t

    # 3. <title> with site-name suffix stripped ("Title | Site" / "Title - Site" / "Title » Site")
    title_tag = soup.find('title')
    if title_tag:
        t = title_tag.get_text(strip=True)
        if t:
            t = _strip_site_suffix(t, site_name)
            if t:
                return t

    return "Untitled Article"


def extract_content(article_url: str, site_name_hint: str = '') -> dict:
    """Scrapes the article URL and extracts the main content (title and body paragraphs).

    site_name_hint is the display name from config (e.g. "Aeon Magazine"); it is used
    when the page omits og:site_name so the site suffix can still be stripped from titles.
    """
    try:
        response = session.get(article_url, headers=HEADERS, timeout=10)
        response.raise_for_status()
    except Exception as e:
        logger.warning(f"Error fetching article {article_url}: {e}")
        return None

    soup = BeautifulSoup(response.text, 'html.parser')

    # Gate: reject listing / category / utility / video pages before extracting anything
    if not _is_real_article(soup, site_name_hint, article_url):
        logger.info(f"Skipping non-article page: {article_url}")
        return None

    site_name = _meta_content(soup, 'og:site_name') or site_name_hint or ''

    # Content container — prefer <article> and explicit article-body markers
    content_selectors = [
        ('article', {}),
        ('div', {'itemprop': 'articleBody'}),
        ('div', {'id': re.compile(r'article-body|post-body|entry-content|article-content|main-content', re.I)}),
        ('div', {'class': re.compile(r'article-body|post-body|entry-content|article-content|main-content|story-content', re.I)}),
        ('main', {}),
        ('section', {'class': re.compile(r'article|post|entry|content', re.I)}),
    ]

    body_container = None
    for tag, attrs in content_selectors:
        body_container = soup.find(tag, attrs)
        if body_container:
            break

    # Image extraction — BEFORE boilerplate stripping so we don't lose the hero figure
    thumb = _find_meta_image(soup) or (_find_container_image(body_container, article_url) if body_container else None)

    # Strip boilerplate from the container
    _strip_boilerplate(body_container)

    # Title extraction
    title = _extract_title(soup, body_container, site_name)

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
    if not body_container or len(cleaned_paras) < 3:
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
        'paragraphs': cleaned_paras,
        'thumbnail_url': thumb
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
    max_attempts = 4
    attempt = 0

    for site in all_sites:
        attempt += 1
        if attempt > max_attempts:
            break

        article_links = get_article_links(site['url'])
        if not article_links:
            continue

        random.shuffle(article_links)
        for article_url in article_links[:3]:
            extracted = extract_content(article_url, site['name'])
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
        "content": content['paragraphs'],
        "thumbnail_url": content['thumbnail_url']
    }
