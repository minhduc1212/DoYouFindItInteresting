/**
 * Handles: API fetching, content rendering, and the glassmorphism tooltip system.
 */

/* ═══════════════════════════════════════════════════════════════════════════
   1. DOM References
   ═══════════════════════════════════════════════════════════════════════════ */
const randomizeBtn   = document.getElementById('randomize-btn');
const btnIcon        = randomizeBtn.querySelector('.btn__icon');
const card           = document.getElementById('knowledge-card');
const loadingState   = document.getElementById('loading-state');
const emptyState     = document.getElementById('empty-state');
const articleContent = document.getElementById('article-content');
const articleMeta    = document.getElementById('article-meta');
const articleTitle   = document.getElementById('article-title');
const articleBody    = document.getElementById('article-body');
const articleFooter  = document.getElementById('article-footer');
const counter        = document.getElementById('counter');
const counterText    = document.getElementById('counter-text');
const tooltip        = document.getElementById('tooltip');
const tooltipTerm    = document.getElementById('tooltip-term');
const tooltipDef     = document.getElementById('tooltip-definition');
const tooltipArrow   = document.getElementById('tooltip-arrow');

/* ═══════════════════════════════════════════════════════════════════════════
   2. State Machine — exactly ONE view is visible at a time
   ═══════════════════════════════════════════════════════════════════════════ */

/**
 * Switch the card to one of three mutually-exclusive views.
 * @param {'empty'|'loading'|'content'} view
 */
function showView(view) {
  emptyState.hidden     = true;
  loadingState.hidden   = true;
  articleContent.hidden = true;

  if (view === 'empty')   emptyState.hidden     = false;
  if (view === 'loading') loadingState.hidden   = false;
  if (view === 'content') articleContent.hidden = false;
}

// Initial state
showView('empty');

/* ═══════════════════════════════════════════════════════════════════════════
   3. State
   ═══════════════════════════════════════════════════════════════════════════ */
let fetchCount       = 0;
let activeTermEl     = null;
let tooltipHideTimer = null;

/* ═══════════════════════════════════════════════════════════════════════════
   4. API Fetch
   ═══════════════════════════════════════════════════════════════════════════ */
async function fetchRandomKnowledge() {
  randomizeBtn.disabled = true;
  btnIcon.classList.add('spinning');
  hideTooltip(true);
  showView('loading');

  try {
    const response = await fetch('/api/random-knowledge');
    if (!response.ok) throw new Error(`API error: ${response.status}`);
    const data = await response.json();
    renderArticle(data);
    fetchCount++;
    updateCounter(fetchCount);
  } catch (error) {
    console.error('Failed to fetch knowledge:', error);
    renderError();
  } finally {
    randomizeBtn.disabled = false;
    btnIcon.classList.remove('spinning');
  }
}

/* ═══════════════════════════════════════════════════════════════════════════
   5. Rendering
   ═══════════════════════════════════════════════════════════════════════════ */

function renderArticle(data) {
  activeTermEl = null;

  // Meta
  const sourceIcon = data.source_type === 'Video' ? '▶' : '◈';
  articleMeta.innerHTML = `
    <span class="meta__badge">${sourceIcon} ${escapeHTML(data.source_type)}</span>
    <span class="meta__sep">·</span>
    <span>${data.term_count} term${data.term_count !== 1 ? 's' : ''} explained</span>
  `;

  // Title
  articleTitle.textContent = data.title;

  // Body segments
  articleBody.innerHTML = '';
  const fragment = document.createDocumentFragment();
  data.segments.forEach(segment => {
    if (segment.type === 'text') {
      fragment.appendChild(document.createTextNode(segment.text));
    } else if (segment.type === 'term') {
      const span = document.createElement('span');
      span.className = 'term-trigger';
      span.textContent = segment.text;
      span.setAttribute('tabindex', '0');
      span.setAttribute('role', 'button');
      span.setAttribute('aria-describedby', 'tooltip');
      span.dataset.term       = segment.text;
      span.dataset.definition = segment.definition;
      fragment.appendChild(span);
    }
  });
  articleBody.appendChild(fragment);

  // Footer
  const sourceLink = data.source_url
    ? `<a class="footer__source-link" href="${escapeHTML(data.source_url)}" target="_blank" rel="noopener noreferrer">View original ${escapeHTML(data.source_type)}</a>`
    : '';
  articleFooter.innerHTML = `
    <span class="footer__terms-info">
      <strong>${data.term_count}</strong> technical ${data.term_count !== 1 ? 'terms' : 'term'} — hover to learn more
    </span>
    ${sourceLink}
  `;

  // Switch to content (hides loading + empty automatically)
  showView('content');
  card.classList.add('card--loaded');
}

function renderError() {
  emptyState.querySelector('.card__empty-icon').textContent = '⚠';
  emptyState.querySelector('.card__empty-text').textContent =
    'Could not connect to the API. Make sure the FastAPI server is running on port 8000.';
  showView('empty');
}

function updateCounter(count) {
  counter.hidden = false;
  counterText.textContent = `${count} randomization${count !== 1 ? 's' : ''} this session`;
}

/* ═══════════════════════════════════════════════════════════════════════════
   6. Tooltip System
   ═══════════════════════════════════════════════════════════════════════════ */

const TOOLTIP_OFFSET     = 12;
const TOOLTIP_HIDE_DELAY = 180;

function showTooltip(termEl) {
  clearTimeout(tooltipHideTimer);

  tooltipTerm.textContent = termEl.dataset.term;
  tooltipDef.textContent  = termEl.dataset.definition;
  tooltip.setAttribute('aria-hidden', 'false');

  tooltip.style.visibility = 'hidden';
  tooltip.classList.add('is-visible');

  const termRect = termEl.getBoundingClientRect();
  const tipW     = tooltip.offsetWidth;
  const tipH     = tooltip.offsetHeight;
  const viewW    = window.innerWidth;
  const viewH    = window.innerHeight;
  const scrollY  = window.scrollY;

  const placeAbove = termRect.top > tipH + TOOLTIP_OFFSET || termRect.top > viewH - termRect.bottom;

  let top = placeAbove
    ? termRect.top + scrollY - tipH - TOOLTIP_OFFSET
    : termRect.bottom + scrollY + TOOLTIP_OFFSET;

  placeAbove
    ? tooltip.classList.remove('tooltip--above')
    : tooltip.classList.add('tooltip--above');

  let left = termRect.left + termRect.width / 2 - tipW / 2;
  left = Math.max(16, Math.min(left, viewW - tipW - 16));

  const arrowX = Math.max(16, Math.min((termRect.left + termRect.width / 2) - left, tipW - 16));
  tooltipArrow.style.left      = `${arrowX}px`;
  tooltipArrow.style.translate = 'none';

  tooltip.style.top        = `${top}px`;
  tooltip.style.left       = `${left}px`;
  tooltip.style.visibility = '';
}

function hideTooltip(immediate = false) {
  clearTimeout(tooltipHideTimer);
  const doHide = () => {
    tooltip.classList.remove('is-visible');
    tooltip.setAttribute('aria-hidden', 'true');
    if (activeTermEl) activeTermEl.classList.remove('is-active');
    activeTermEl = null;
  };
  immediate ? doHide() : (tooltipHideTimer = setTimeout(doHide, TOOLTIP_HIDE_DELAY));
}

/* ═══════════════════════════════════════════════════════════════════════════
   7. Term Event Delegation
   ═══════════════════════════════════════════════════════════════════════════ */
articleBody.addEventListener('mouseenter', (e) => {
  const term = e.target.closest('.term-trigger');
  if (!term) return;
  showTooltip(term);
  term.classList.add('is-active');
  activeTermEl = term;
}, true);

articleBody.addEventListener('mouseleave', (e) => {
  const term = e.target.closest('.term-trigger');
  if (!term) return;
  tooltipHideTimer = setTimeout(() => {
    if (!tooltip.matches(':hover')) hideTooltip(true);
  }, TOOLTIP_HIDE_DELAY);
}, true);

tooltip.addEventListener('mouseenter', () => clearTimeout(tooltipHideTimer));
tooltip.addEventListener('mouseleave', () => hideTooltip());

articleBody.addEventListener('keydown', (e) => {
  if (e.key !== 'Enter' && e.key !== ' ') return;
  const term = e.target.closest('.term-trigger');
  if (!term) return;
  e.preventDefault();
  if (activeTermEl === term && tooltip.classList.contains('is-visible')) {
    hideTooltip(true);
  } else {
    if (activeTermEl && activeTermEl !== term) activeTermEl.classList.remove('is-active');
    showTooltip(term);
    activeTermEl = term;
    term.classList.add('is-active');
  }
});

articleBody.addEventListener('click', (e) => {
  const term = e.target.closest('.term-trigger');
  if (!term) return;
  if (activeTermEl === term && tooltip.classList.contains('is-visible')) {
    hideTooltip(true);
  } else {
    if (activeTermEl && activeTermEl !== term) activeTermEl.classList.remove('is-active');
    showTooltip(term);
    activeTermEl = term;
    term.classList.add('is-active');
  }
});

document.addEventListener('click', (e) => {
  if (!e.target.closest('.term-trigger') && !e.target.closest('#tooltip')) hideTooltip(true);
});

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') hideTooltip(true);
});

let resizeTimer;
function repositionTooltip() {
  if (activeTermEl && tooltip.classList.contains('is-visible')) showTooltip(activeTermEl);
}
window.addEventListener('scroll', repositionTooltip, { passive: true });
window.addEventListener('resize', () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(repositionTooltip, 100);
}, { passive: true });

/* ═══════════════════════════════════════════════════════════════════════════
   8. Button
   ═══════════════════════════════════════════════════════════════════════════ */
randomizeBtn.addEventListener('click', fetchRandomKnowledge);

/* ═══════════════════════════════════════════════════════════════════════════
   9. Utilities
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