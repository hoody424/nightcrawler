// nightcrawler web UI entry point: routing, theme, global (AI) search, crawl status.
import { html, render, $, $$, GET, POST, state, loadMeta, store, toast, toastError } from './js/core.js';
import { dashboardPage } from './js/dashboard.js';
import { productsPage, productsHash } from './js/products.js';
import { watchlistsPage, refreshLists } from './js/watchlists.js';
import { sourcesPage } from './js/sources.js';
import { runsPage } from './js/runs.js';
import { settingsPage } from './js/settings.js';

const ROUTES = {
  '': ['dashboard', dashboardPage], products: ['products', productsPage], watchlists: ['watchlists', watchlistsPage],
  sources: ['sources', sourcesPage], runs: ['runs', runsPage], settings: ['settings', settingsPage],
};
let pendingAi = null;

function route() {
  const path = location.hash.replace(/^#\/?/, '').split('?')[0];
  const [name, page] = ROUTES[path] || ROUTES[''];
  $$('.sidenav a').forEach((a) => a.classList.toggle('active', a.dataset.route === name));
  $('#sidenav').classList.remove('open');
  const main = $('#main');
  main.innerHTML = '';
  const container = document.createElement('div');
  main.append(container);
  const opts = pendingAi ? { aiExplanation: pendingAi } : {};
  pendingAi = null;
  Promise.resolve(page(container, opts)).catch(toastError);
  window.scrollTo(0, 0);
}

// Scraped image URLs die all the time - hide broken ones instead of showing an icon.
document.addEventListener('error', (e) => {
  const img = e.target;
  if (img instanceof HTMLImageElement && !img.classList.contains('broken')) {
    img.classList.add('broken');
    if (img.closest('.pimg') && !img.parentElement.querySelector('.noimg')) img.insertAdjacentHTML('afterend', '<span class="noimg">📦</span>');
    else if (img.classList.contains('hero-img')) img.remove();
  }
}, true);

// ------------------------------------------------------------------ theme
function applyTheme(theme) {
  if (theme) document.documentElement.dataset.theme = theme; else delete document.documentElement.dataset.theme;
}
applyTheme(store.get('theme', null));
$('#themeToggle').onclick = () => {
  const dark = document.documentElement.dataset.theme
    ? document.documentElement.dataset.theme === 'dark'
    : matchMedia('(prefers-color-scheme: dark)').matches;
  const next = dark ? 'light' : 'dark';
  store.set('theme', next);
  applyTheme(next);
};
$('#navToggle').onclick = () => $('#sidenav').classList.toggle('open');

// ---------------------------------------------------------- global search
const aiToggle = $('#aiSearchToggle');
aiToggle.checked = store.get('aiSearch', false);
aiToggle.onchange = () => {
  if (aiToggle.checked && !state.meta?.ai?.backend) {
    aiToggle.checked = false;
    toast('Connect Claude in Settings → AI to use AI search', 'error');
    return;
  }
  store.set('aiSearch', aiToggle.checked);
};
$('#globalSearch').addEventListener('submit', async (e) => {
  e.preventDefault();
  const input = $('#globalSearchInput');
  const text = input.value.trim();
  if (!text) { location.hash = '#/products'; return; }
  if (!aiToggle.checked) { location.hash = productsHash({ q: text }); return; }
  input.disabled = true;
  const icon = $('.gs-icon');
  icon.innerHTML = '<span class="spinner"></span>';
  try {
    const r = await POST('/api/ai/parse-filter', { text });
    const { explanation, ...filter } = r;
    const clean = Object.fromEntries(Object.entries(filter).filter(([, v]) => v !== null && v !== undefined && !(Array.isArray(v) && !v.length) && !(typeof v === 'object' && !Array.isArray(v) && !Object.keys(v).length)));
    pendingAi = explanation || 'Filters set by AI';
    const target = productsHash(clean);
    if (location.hash === target) route(); else location.hash = target;
    input.value = '';
  } catch (err) { toastError(err); } finally { input.disabled = false; icon.textContent = '⌕'; }
});

// ----------------------------------------------------------- crawl status
let wasRunning = false;
let pollTimer;
async function poll() {
  clearTimeout(pollTimer);
  try {
    const s = await GET('/api/status');
    const el = $('#crawlStatus');
    const busy = s.running || s.queued.length;
    el.hidden = !busy && !s.paused;
    render(el, s.running ? html`<span class="spinner"></span>Crawling “${s.running.name}”${s.queued.length ? ` +${s.queued.length} queued` : ''}`
      : s.paused ? html`⏸ Scheduler paused` : html`<span class="spinner"></span>${s.queued.length} queued`);
    if (wasRunning && !busy) window.dispatchEvent(new Event('nc:crawl-finished'));
    wasRunning = Boolean(busy);
    pollTimer = setTimeout(poll, busy ? 2500 : 10000);
  } catch { pollTimer = setTimeout(poll, 15000); }
}
window.addEventListener('nc:poll', () => setTimeout(poll, 300));

// ------------------------------------------------------------------- boot
(async () => {
  try {
    await Promise.all([loadMeta(), refreshLists()]);
  } catch (e) {
    render($('#main'), html`<div class="callout warn">Could not reach the nightcrawler API: ${e.message}</div>`);
    return;
  }
  render($('#navFoot'), html`v${state.meta.version}<br>${state.meta.ai.backend ? html`✨ AI: ${state.meta.ai.backend === 'claude_code' ? 'Claude subscription' : 'API'}` : html`<a href="#/settings">✨ Connect Claude</a>`}`);
  window.addEventListener('hashchange', route);
  route();
  poll();
})();
