// Core helpers: safe HTML templating, API client, formatting, modal/drawer/toast.

// ---------------------------------------------------------------- templating
// Every interpolated value is HTML-escaped unless wrapped in raw(). Scraped
// listing data is untrusted, so never build markup by string concatenation.
export class Raw { constructor(s) { this.s = s; } toString() { return this.s; } }
export const raw = (s) => new Raw(String(s ?? ''));
const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;', '`': '&#96;' };
export const esc = (v) => String(v ?? '').replace(/[&<>"'`]/g, (c) => ESC[c]);
function val(v) {
  if (v === null || v === undefined || v === false) return '';
  if (v instanceof Raw) return v.s;
  if (Array.isArray(v)) return v.map(val).join('');
  return esc(v);
}
export function html(strings, ...values) {
  let out = strings[0];
  values.forEach((v, i) => { out += val(v) + strings[i + 1]; });
  return new Raw(out);
}
export function render(el, content) { el.innerHTML = String(content); return el; }
export function safeUrl(u) {
  try { const url = new URL(u, location.href); return ['http:', 'https:'].includes(url.protocol) ? url.href : '#'; }
  catch { return '#'; }
}
export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

// ---------------------------------------------------------------- storage (best effort)
export const store = {
  get(key, fallback) { try { const v = localStorage.getItem('nc.' + key); return v === null ? fallback : JSON.parse(v); } catch { return fallback; } },
  set(key, value) { try { localStorage.setItem('nc.' + key, JSON.stringify(value)); } catch { /* ignore */ } },
};

// ---------------------------------------------------------------- API
export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}
export async function api(method, path, body, { signal } = {}) {
  const opts = { method, headers: {}, signal };
  if (body !== undefined) {
    if (typeof body === 'string') { opts.body = body; opts.headers['Content-Type'] = 'text/plain'; }
    else { opts.body = JSON.stringify(body); opts.headers['Content-Type'] = 'application/json'; }
  }
  const res = await fetch(path, opts);
  if (res.status === 204) return null;
  const type = res.headers.get('content-type') || '';
  const data = type.includes('json') ? await res.json() : await res.text();
  if (!res.ok) {
    let msg = typeof data === 'string' ? data : data.detail;
    if (Array.isArray(msg)) msg = msg.map((d) => `${d.loc?.slice(1).join('.')}: ${d.msg}`).join('; ');
    throw new ApiError(res.status, msg || res.statusText);
  }
  return data;
}
export const GET = (p, o) => api('GET', p, undefined, o);
export const POST = (p, b, o) => api('POST', p, b ?? {}, o);
export const PUT = (p, b) => api('PUT', p, b);
export const PATCH = (p, b) => api('PATCH', p, b);
export const DEL = (p) => api('DELETE', p);

// ---------------------------------------------------------------- app state
export const state = { meta: null, sources: [], searches: [] };
export async function loadMeta() { state.meta = await GET('/api/meta'); return state.meta; }
export const attrDef = (name) => state.meta?.attributes.find((a) => a.name === name);

// ---------------------------------------------------------------- formatting
const LOCALE = navigator.language || 'en';
export function money(v, currency) {
  if (v === null || v === undefined) return '–';
  try {
    if (currency && /^[A-Z]{3}$/.test(currency)) {
      return new Intl.NumberFormat(LOCALE, { style: 'currency', currency, maximumFractionDigits: v % 1 ? 2 : 0 }).format(v);
    }
  } catch { /* fall through */ }
  return `${new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 2 }).format(v)} ${currency || ''}`.trim();
}
export const num = (v, d = 0) => (v === null || v === undefined ? '–' : new Intl.NumberFormat(LOCALE, { maximumFractionDigits: d }).format(v));
export function ago(iso) {
  if (!iso) return 'never';
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 0) return 'in ' + ago(new Date(Date.now() + (Date.now() - new Date(iso).getTime())).toISOString()).replace(' ago', '');
  if (s < 60) return 'just now';
  const units = [[60, 'min'], [3600, 'h'], [86400, 'd'], [604800, 'w']];
  let label = `${Math.floor(s / 60)} min`;
  for (const [sec, u] of units) if (s >= sec) label = `${Math.floor(s / sec)} ${u}`;
  return label + ' ago';
}
export const dateTime = (iso) => (iso ? new Date(iso).toLocaleString(LOCALE, { dateStyle: 'medium', timeStyle: 'short' }) : '–');
export const shortDate = (iso) => new Date(iso).toLocaleDateString(LOCALE, { day: '2-digit', month: '2-digit' });

export const CONDITION_LABEL = { new: 'New', used: 'Used', refurbished: 'Refurbished', unknown: 'Unknown' };
export const LISTING_LABEL = { fixed: 'Buy now', auction: 'Auction', offer: 'Negotiable (VB)', unknown: 'Unknown' };
const regionNames = (() => { try { return new Intl.DisplayNames([LOCALE], { type: 'region' }); } catch { return null; } })();
export function countryLabel(code) {
  if (!code) return '–';
  const flag = /^[A-Z]{2}$/.test(code) ? String.fromCodePoint(...[...code].map((c) => 0x1f1a5 + c.charCodeAt(0))) : '';
  let name = code;
  try { name = regionNames?.of(code) || code; } catch { /* invalid code */ }
  return `${flag} ${name}`.trim();
}
export function attrValue(name, value) {
  const def = attrDef(name);
  if (!def) return value;
  if (def.kind === 'flag') return value === 'yes' ? '✓' : value;
  if (def.kind === 'number' && def.unit) {
    if (def.unit === 'GB' && Number(value) >= 1000) return `${Number(value) / 1000} TB`;
    return def.unit === '″' ? `${value}″` : `${value} ${def.unit}`;
  }
  return value;
}
export const conditionBadge = (c) => html`<span class="badge ${c}">${CONDITION_LABEL[c] || c}</span>`;

// ---------------------------------------------------------------- toast
export function toast(message, kind = '') {
  const el = document.createElement('div');
  el.className = `toast ${kind}`;
  el.textContent = message;
  $('#toastRoot').append(el);
  setTimeout(() => el.remove(), kind === 'error' ? 7000 : 3500);
}
export function toastError(err) { toast(err?.message || String(err), 'error'); }

// ---------------------------------------------------------------- modal / drawer
function overlay(root, onClose) {
  const ov = document.createElement('div');
  ov.className = 'overlay';
  ov.addEventListener('click', onClose);
  root.append(ov);
  return ov;
}
let escHandlers = [];
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && escHandlers.length) escHandlers[escHandlers.length - 1](); });

export function openModal({ title, body, footer, wide = false, onClose }) {
  const root = $('#modalRoot');
  const wrap = document.createElement('div');
  const close = () => { wrap.remove(); escHandlers = escHandlers.filter((h) => h !== close); onClose?.(); };
  overlay(wrap, close);
  const el = document.createElement('div');
  el.className = 'modal' + (wide ? ' wide' : '');
  el.setAttribute('role', 'dialog');
  render(el, html`<div class="modal-head"><h2 class="grow">${title}</h2><button class="icon-btn" data-close aria-label="Close">✕</button></div>
    <div class="modal-body"></div>${footer ? html`<div class="modal-foot"></div>` : ''}`);
  const bodyEl = $('.modal-body', el);
  if (body instanceof Node) bodyEl.append(body); else render(bodyEl, body ?? '');
  if (footer) { const f = $('.modal-foot', el); if (footer instanceof Node) f.append(footer); else render(f, footer); }
  $('[data-close]', el).addEventListener('click', close);
  wrap.append(el);
  root.append(wrap);
  escHandlers.push(close);
  return { el, body: bodyEl, close };
}

export function openDrawer(title) {
  const root = $('#drawerRoot');
  root.innerHTML = '';
  const wrap = document.createElement('div');
  const close = () => { wrap.remove(); escHandlers = escHandlers.filter((h) => h !== close); };
  overlay(wrap, close);
  const el = document.createElement('aside');
  el.className = 'drawer';
  render(el, html`<div class="drawer-head"><h2 class="grow">${title}</h2><button class="icon-btn" data-close aria-label="Close">✕</button></div><div class="drawer-body"></div>`);
  $('[data-close]', el).addEventListener('click', close);
  wrap.append(el);
  root.append(wrap);
  escHandlers.push(close);
  return { el, body: $('.drawer-body', el), close };
}

export function confirmDialog(message, { confirmLabel = 'Delete', danger = true } = {}) {
  return new Promise((resolve) => {
    let answered = false;
    const m = openModal({
      title: 'Please confirm',
      body: html`<p>${message}</p>`,
      footer: html`<button class="btn" data-no>Cancel</button><button class="btn ${danger ? 'primary' : 'primary'}" data-yes>${confirmLabel}</button>`,
      onClose: () => { if (!answered) resolve(false); },
    });
    $('[data-no]', m.el).onclick = () => { answered = true; m.close(); resolve(false); };
    $('[data-yes]', m.el).onclick = () => { answered = true; m.close(); resolve(true); };
  });
}

export async function withBusy(button, fn) {
  const label = button.innerHTML;
  button.disabled = true;
  button.innerHTML = '<span class="spinner"></span>' + label;
  try { return await fn(); } finally { button.disabled = false; button.innerHTML = label; }
}

export function debounce(fn, ms = 300) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

export const splitList = (s) => String(s || '').split(/[,\n]/).map((x) => x.trim()).filter(Boolean);
export const numOrNull = (v) => (v === '' || v === null || v === undefined || Number.isNaN(Number(v)) ? null : Number(v));
