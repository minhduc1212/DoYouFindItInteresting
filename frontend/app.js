/**
 * Handles: API fetching, content rendering, and the video player load system.
 */

/* ═══════════════════════════════════════════════════════════════════════════
   1. DOM References
   ═══════════════════════════════════════════════════════════════════════════ */
const randomizeBtn      = document.getElementById('randomize-btn');
const card              = document.getElementById('knowledge-card');
const loadingState      = document.getElementById('loading-state');
const emptyState        = document.getElementById('empty-state');
const loaderText        = document.getElementById('loader-text');
const emptyText         = document.getElementById('empty-text');

// Article Mode Elements
const articleContent    = document.getElementById('article-content');
const articleMeta       = document.getElementById('article-meta');
const articleTitle      = document.getElementById('article-title');
const articleBody       = document.getElementById('article-body');
const articleFooter     = document.getElementById('article-footer');
const articleImage      = document.getElementById('article-image');
const progressBar       = document.getElementById('reading-progress');

// Video Mode Elements
const videoContent      = document.getElementById('video-content');
const videoMeta         = document.getElementById('video-meta');
const videoTitle        = document.getElementById('video-title');
const videoFooter       = document.getElementById('video-footer');
const videoPlayerContainer = document.querySelector('.video-player-container');

// AI Summary Elements
const summarizeBtn       = document.getElementById('summarize-btn');
const aiSummaryContainer = document.getElementById('ai-summary-container');
const aiSummaryBody      = document.getElementById('ai-summary-body');
const closeSummaryBtn    = document.getElementById('close-summary-btn');

// General Elements
const counter           = document.getElementById('counter');
const counterText       = document.getElementById('counter-text');

/* ═══════════════════════════════════════════════════════════════════════════
   2. State & Config
   ═══════════════════════════════════════════════════════════════════════════ */
let fetchCount        = 0;
let currentSourceType = 'Article'; // Tracks current loaded source type
let currentKnowledgeData = null; // Stores currently loaded knowledge data object

// YouTube Player API State
let isYoutubeAPILoaded = false;
let ytPlayer           = null;
let playerReady        = false;
let currentVideoId     = null; // Video shown as thumbnail (or playing)
let currentThumbUrl    = null; // Thumbnail URL to restore after destroying the player

/**
 * Switch the card to one of three mutually-exclusive views.
 * @param {'empty'|'loading'|'content'} view
 */
function showView(view) {
  emptyState.hidden     = true;
  loadingState.hidden   = true;
  articleContent.hidden = true;
  videoContent.hidden   = true;

  if (view === 'empty') {
    emptyState.hidden = false;
    progressBar.style.width = '0%';
    summarizeBtn.disabled = true;
    aiSummaryContainer.hidden = true;
    aiSummaryBody.innerHTML = '';
  }
  if (view === 'loading') {
    loadingState.hidden = false;
    progressBar.style.width = '0%';
    summarizeBtn.disabled = true;
    aiSummaryContainer.hidden = true;
    aiSummaryBody.innerHTML = '';
  }
  if (view === 'content') {
    if (currentSourceType === 'Article') {
      articleContent.hidden = false;
    } else {
      videoContent.hidden = false;
    }
    summarizeBtn.disabled = false;
  }
}

// Initial state
showView('empty');

/* ═══════════════════════════════════════════════════════════════════════════
   3. API Fetch
   ═══════════════════════════════════════════════════════════════════════════ */
async function fetchRandomKnowledge() {
  console.log('[APP] Randomize button clicked. Fetching random knowledge from API...');
  
  // Stop and destroy the player first to silence any audio immediately
  stopOrDestroyPlayer();

  randomizeBtn.disabled = true;
  showView('loading');

  try {
    const response = await fetch('/api/random-knowledge');
    console.log('[APP] API responded with status:', response.status);
    if (!response.ok) throw new Error(`API error: ${response.status}`);
    const data = await response.json();
    
    console.log('[APP] Fetched knowledge data:', data);
    currentSourceType = data.source_type;
    currentKnowledgeData = data; // Save loaded data
    
    if (currentSourceType === 'Article') {
      renderArticle(data);
    } else {
      renderVideo(data);
    }
    fetchCount++;
    updateCounter(fetchCount);
  } catch (error) {
    console.error('[APP] Error fetching random knowledge:', error);
    currentKnowledgeData = null; // Clear on error
    renderError();
  } finally {
    randomizeBtn.disabled = false;
    console.log('[APP] Fetch cycle complete.');
  }
}

/* ═══════════════════════════════════════════════════════════════════════════
   4. Rendering
   ═══════════════════════════════════════════════════════════════════════════ */

function renderArticle(data) {
  console.log('[APP] Rendering article:', data.title);

  // Hero image (hidden until loaded, or if the URL is broken/missing)
  if (data.thumbnail_url) {
    articleImage.onload  = () => { articleImage.hidden = false; };
    articleImage.onerror = () => { articleImage.hidden = true; };
    articleImage.src = data.thumbnail_url;
  } else {
    articleImage.removeAttribute('src');
    articleImage.hidden = true;
  }

  // Meta
  articleMeta.innerHTML = `
    <span class="meta__badge">Article</span>
    <span class="meta__sep">·</span>
    <span class="meta__badge">${escapeHTML(data.source_name)}</span>
    <span class="meta__sep">·</span>
    <span>${escapeHTML(data.topic)}</span>
  `;

  // Title
  articleTitle.textContent = data.title;

  // Body paragraphs (Render all content directly)
  articleBody.innerHTML = '';
  const fragment = document.createDocumentFragment();
  data.content.forEach(pText => {
    const p = document.createElement('p');
    p.textContent = pText;
    fragment.appendChild(p);
  });
  articleBody.appendChild(fragment);

  // Footer
  const sourceLink = data.source_url
    ? `<a class="footer__source-link" href="${escapeHTML(data.source_url)}" target="_blank" rel="noopener noreferrer">View original site ↗</a>`
    : '';
  articleFooter.innerHTML = `
    <span class="footer__terms-info">
      Read mode active — scroll to read full content.
    </span>
    ${sourceLink}
  `;

  showView('content');
  card.classList.add('card--loaded');
  updateReadingProgress();
}

function renderVideo(data) {
  console.log('[APP] Rendering video:', data.title, 'with video ID:', data.video_id);
  // Meta
  videoMeta.innerHTML = `
    <span class="meta__badge">Video</span>
    <span class="meta__sep">·</span>
    <span class="meta__badge">${escapeHTML(data.channel)}</span>
    <span class="meta__sep">·</span>
    <span>${escapeHTML(data.topic)}</span>
  `;

  // Title
  videoTitle.textContent = data.title;

  // Footer
  const sourceLink = data.source_url
    ? `<a class="footer__source-link" href="${escapeHTML(data.source_url)}" target="_blank" rel="noopener noreferrer">Watch on YouTube ↗</a>`
    : '';
  videoFooter.innerHTML = `
    <span class="footer__terms-info">
      Watch mode active — watch the video above.
    </span>
    ${sourceLink}
  `;

  showView('content');
  card.classList.add('card--loaded');

  // Show thumbnail with a click-to-play overlay (iframe only loads on click)
  showVideoThumbnail(data.video_id, data.thumbnail_url);
}

function renderError() {
  console.log('[APP] Displaying error message to user');
  emptyState.querySelector('.card__empty-text').textContent =
    'Failed to gather knowledge from resources. Please check your backend connection.';
  showView('empty');
}

function updateCounter(count) {
  console.log('[APP] Updating session interaction counter to:', count);
  counter.hidden = false;
  counterText.textContent = `${count} randomization${count !== 1 ? 's' : ''} this session`;
}

/* ═══════════════════════════════════════════════════════════════════════════
   5. YouTube Integration
   ═══════════════════════════════════════════════════════════════════════════ */
function loadYoutubeAPI() {
  if (isYoutubeAPILoaded) return Promise.resolve();
  return new Promise((resolve) => {
    const tag = document.createElement('script');
    tag.src = "https://www.youtube.com/iframe_api";
    const firstScriptTag = document.getElementsByTagName('script')[0];
    firstScriptTag.parentNode.insertBefore(tag, firstScriptTag);
    
    window.onYouTubeIframeAPIReady = () => {
      isYoutubeAPILoaded = true;
      resolve();
    };
  });
}

function showVideoThumbnail(videoId, thumbUrl) {
  currentVideoId  = videoId;
  currentThumbUrl = thumbUrl || `https://i.ytimg.com/vi/${videoId}/hqdefault.jpg`;

  videoPlayerContainer.classList.remove('video-thumb--placeholder');
  videoPlayerContainer.innerHTML = `
    <button class="video-thumb__play" id="video-play-btn" aria-label="Play video">
      <img class="video-thumb" src="${escapeHTML(currentThumbUrl)}" alt="Video thumbnail" />
      <span class="video-thumb__play-icon">▶</span>
    </button>
  `;

  // Fallback chain for broken thumbnails: try hqdefault, then a neutral placeholder
  const thumbImg = videoPlayerContainer.querySelector('.video-thumb');
  let fallbackTried = false;
  thumbImg.onerror = () => {
    if (!fallbackTried) {
      fallbackTried = true;
      thumbImg.src = `https://i.ytimg.com/vi/${videoId}/hqdefault.jpg`;
    } else {
      videoPlayerContainer.classList.add('video-thumb--placeholder');
      thumbImg.style.display = 'none';
    }
  };

  document.getElementById('video-play-btn').addEventListener('click', () => {
    initYoutubePlayer(currentVideoId, { autoplay: true });
  });
}

function initYoutubePlayer(videoId, opts = {}) {
  console.log('[APP] Initializing YouTube Player for video ID:', videoId);
  if (window.YT && window.YT.Player) {
    createPlayer(videoId, opts);
  } else {
    console.log('[APP] Loading YouTube Iframe API script...');
    loadYoutubeAPI().then(() => {
      createPlayer(videoId, opts);
    });
  }
}

function stopOrDestroyPlayer() {
  if (ytPlayer) {
    console.log('[APP] Stopping and destroying YouTube player...');
    try {
      if (typeof ytPlayer.destroy === 'function') {
        ytPlayer.destroy();
      }
    } catch (e) {
      console.warn("YouTube player destroy error:", e);
    }
    ytPlayer = null;
    playerReady = false;
  }

  // Restore the thumbnail so the card isn't left as an empty black box
  if (currentVideoId) {
    showVideoThumbnail(currentVideoId, currentThumbUrl);
  } else if (!document.getElementById('youtube-player')) {
    videoPlayerContainer.innerHTML = '<div id="youtube-player"></div>';
  }
}

function createPlayer(videoId, opts = {}) {
  console.log('[APP] Creating YT.Player instance for:', videoId);
  playerReady = false;

  // Replace the thumbnail with the actual player div
  videoPlayerContainer.innerHTML = '<div id="youtube-player"></div>';

  ytPlayer = new YT.Player('youtube-player', {
    videoId: videoId,
    playerVars: {
      'autoplay': opts.autoplay ? 1 : 0,
      'playsinline': 1,
      'rel': 0,
      'modestbranding': 1
    },
    events: {
      'onReady': () => {
        console.log('[APP] YouTube player is ready');
        playerReady = true;
      },
      'onStateChange': onPlayerStateChange
    }
  });
}

function onPlayerStateChange(event) {
  console.log('[APP] YouTube player state changed to:', event.data);
}

/* ═══════════════════════════════════════════════════════════════════════════
   6. Reading Progress Bar & Scroll Controls
   ═══════════════════════════════════════════════════════════════════════════ */
function updateReadingProgress() {
  if (currentSourceType !== 'Article' || articleContent.hidden) {
    progressBar.style.width = '0%';
    return;
  }
  
  const scrollY = window.scrollY;
  const docHeight = document.documentElement.scrollHeight;
  const winHeight = window.innerHeight;
  const totalScroll = docHeight - winHeight;
  
  if (totalScroll <= 0) {
    progressBar.style.width = '0%';
    return;
  }
  
  const percentage = Math.min(100, Math.max(0, (scrollY / totalScroll) * 100));
  progressBar.style.width = `${percentage}%`;
}

window.addEventListener('scroll', updateReadingProgress, { passive: true });

/* ═══════════════════════════════════════════════════════════════════════════
   7. Action Bar & AI summary
   ═══════════════════════════════════════════════════════════════════════════ */
randomizeBtn.addEventListener('click', fetchRandomKnowledge);
summarizeBtn.addEventListener('click', generateAISummary);
closeSummaryBtn.addEventListener('click', () => {
  aiSummaryContainer.hidden = true;
  aiSummaryBody.innerHTML = '';
});

/* ═══════════════════════════════════════════════════════════════════════════
   7a. AI Summarizer Integration
   ═══════════════════════════════════════════════════════════════════════════ */
async function generateAISummary() {
  if (!currentKnowledgeData) return;
  
  console.log('[APP] Summarize button clicked. Fetching summary for:', currentKnowledgeData.title);
  
  // Disable buttons
  summarizeBtn.disabled = true;
  randomizeBtn.disabled = true;
  
  aiSummaryContainer.hidden = false;
  aiSummaryBody.innerHTML = `
    <div class="ai-summary__loading">
      <div class="ai-summary__spinner"></div>
      <p>Analyzing resources and generating summary...</p>
    </div>
  `;
  
  // Scroll to summary box
  aiSummaryContainer.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

  try {
    const response = await fetch('/api/summarize', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(currentKnowledgeData)
    });
    
    if (!response.ok) {
      throw new Error(`API returned status ${response.status}`);
    }
    
    const result = await response.json();
    console.log('[APP] Summary generated successfully');
    
    aiSummaryBody.innerHTML = parseMarkdown(result.summary);
    aiSummaryContainer.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    
  } catch (error) {
    console.error('[APP] Error generating AI summary:', error);
    aiSummaryBody.innerHTML = `
      <div class="ai-summary__error" style="color: var(--color-accent); font-family: var(--font-ui); font-size: 0.85rem; padding: 20px 0; text-align: center;">
        <strong>Error:</strong> Failed to generate AI summary. Please check your internet connection or backend logs.
      </div>
    `;
  } finally {
    summarizeBtn.disabled = false;
    randomizeBtn.disabled = false;
  }
}

function parseMarkdown(mdText) {
  if (!mdText) return '';
  
  // Escape HTML first to prevent XSS injection
  let html = escapeHTML(mdText);
  
  // Split the text into lines
  const lines = html.split('\n');
  let resultHtml = [];
  let inList = false;
  let listType = null; // 'ul' or 'ol'
  
  for (let i = 0; i < lines.length; i++) {
    let line = lines[i].trim();
    
    if (line === '') {
      if (inList) {
        resultHtml.push(`</${listType}>`);
        inList = false;
        listType = null;
      }
      continue;
    }
    
    // Headings
    if (line.startsWith('#### ')) {
      if (inList) { resultHtml.push(`</${listType}>`); inList = false; listType = null; }
      resultHtml.push(`<h4>${line.slice(5)}</h4>`);
      continue;
    }
    if (line.startsWith('### ')) {
      if (inList) { resultHtml.push(`</${listType}>`); inList = false; listType = null; }
      resultHtml.push(`<h3>${line.slice(4)}</h3>`);
      continue;
    }
    if (line.startsWith('## ')) {
      if (inList) { resultHtml.push(`</${listType}>`); inList = false; listType = null; }
      resultHtml.push(`<h3>${line.slice(3)}</h3>`);
      continue;
    }
    
    // Unordered List items
    const ulMatch = line.match(/^[\*\-\+]\s+(.*)/);
    if (ulMatch) {
      if (!inList || listType !== 'ul') {
        if (inList) resultHtml.push(`</${listType}>`);
        resultHtml.push('<ul>');
        inList = true;
        listType = 'ul';
      }
      resultHtml.push(`<li>${ulMatch[1]}</li>`);
      continue;
    }
    
    // Ordered List items
    const olMatch = line.match(/^(\d+)\.\s+(.*)/);
    if (olMatch) {
      if (!inList || listType !== 'ol') {
        if (inList) resultHtml.push(`</${listType}>`);
        resultHtml.push('<ol>');
        inList = true;
        listType = 'ol';
      }
      resultHtml.push(`<li>${olMatch[2]}</li>`);
      continue;
    }
    
    // Normal paragraph
    if (inList) {
      resultHtml.push(`</${listType}>`);
      inList = false;
      listType = null;
    }
    
    resultHtml.push(`<p>${line}</p>`);
  }
  
  if (inList) {
    resultHtml.push(`</${listType}>`);
  }
  
  let processedHtml = resultHtml.join('\n');
  
  // Bold formatting: **text**
  processedHtml = processedHtml.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
  // Italic formatting: *text* or _text_
  processedHtml = processedHtml.replace(/\*(.*?)\*/g, '<em>$1</em>');
  processedHtml = processedHtml.replace(/_(.*?)_/g, '<em>$1</em>');
  
  return processedHtml;
}

/* ═══════════════════════════════════════════════════════════════════════════
   8. Utilities
   ═══════════════════════════════════════════════════════════════════════════ */
function escapeHTML(str) {
  if (!str) return '';
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}