/**
 * Handles: API fetching, content rendering, and the video player load system.
 */

/* ═══════════════════════════════════════════════════════════════════════════
   1. DOM References
   ═══════════════════════════════════════════════════════════════════════════ */
const randomizeBtn      = document.getElementById('randomize-btn');
const btnIcon           = randomizeBtn.querySelector('.btn__icon');
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
const progressBar       = document.getElementById('reading-progress');

// Video Mode Elements
const videoContent      = document.getElementById('video-content');
const videoMeta         = document.getElementById('video-meta');
const videoTitle        = document.getElementById('video-title');
const videoFooter       = document.getElementById('video-footer');

// General Elements
const counter           = document.getElementById('counter');
const counterText       = document.getElementById('counter-text');

/* ═══════════════════════════════════════════════════════════════════════════
   2. State & Config
   ═══════════════════════════════════════════════════════════════════════════ */
let fetchCount        = 0;
let currentSourceType = 'Article'; // Tracks current loaded source type

// YouTube Player API State
let isYoutubeAPILoaded = false;
let ytPlayer           = null;
let playerReady        = false;

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
  }
  if (view === 'loading') {
    loadingState.hidden = false;
    progressBar.style.width = '0%';
  }
  if (view === 'content') {
    if (currentSourceType === 'Article') {
      articleContent.hidden = false;
    } else {
      videoContent.hidden = false;
    }
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
  btnIcon.classList.add('spinning');
  showView('loading');

  try {
    const response = await fetch('/api/random-knowledge');
    console.log('[APP] API responded with status:', response.status);
    if (!response.ok) throw new Error(`API error: ${response.status}`);
    const data = await response.json();
    
    console.log('[APP] Fetched knowledge data:', data);
    currentSourceType = data.source_type;
    
    if (currentSourceType === 'Article') {
      renderArticle(data);
    } else {
      renderVideo(data);
    }
    fetchCount++;
    updateCounter(fetchCount);
  } catch (error) {
    console.error('[APP] Error fetching random knowledge:', error);
    renderError();
  } finally {
    randomizeBtn.disabled = false;
    btnIcon.classList.remove('spinning');
    console.log('[APP] Fetch cycle complete.');
  }
}

/* ═══════════════════════════════════════════════════════════════════════════
   4. Rendering
   ═══════════════════════════════════════════════════════════════════════════ */

function renderArticle(data) {
  console.log('[APP] Rendering article:', data.title);
  // Meta
  articleMeta.innerHTML = `
    <span class="meta__badge">📖 Article</span>
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
    <span class="meta__badge">🎥 Video</span>
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

  // Initialize YouTube Iframe Player
  initYoutubePlayer(data.video_id);
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

function initYoutubePlayer(videoId) {
  console.log('[APP] Initializing YouTube Player for video ID:', videoId);
  if (window.YT && window.YT.Player) {
    createPlayer(videoId);
  } else {
    console.log('[APP] Loading YouTube Iframe API script...');
    loadYoutubeAPI().then(() => {
      createPlayer(videoId);
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
  
  // Ensure the placeholder div is present in the container
  const container = document.querySelector('.video-player-container');
  if (container && !document.getElementById('youtube-player')) {
    container.innerHTML = '<div id="youtube-player"></div>';
  }
}

function createPlayer(videoId) {
  console.log('[APP] Creating YT.Player instance for:', videoId);
  playerReady = false;
  
  stopOrDestroyPlayer();

  ytPlayer = new YT.Player('youtube-player', {
    videoId: videoId,
    playerVars: {
      'autoplay': 1,
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
   7. Action Bar
   ═══════════════════════════════════════════════════════════════════════════ */
randomizeBtn.addEventListener('click', fetchRandomKnowledge);

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