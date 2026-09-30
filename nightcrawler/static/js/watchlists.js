// Watchlists: list, create/edit (incl. ✨ AI drafting), run, delete.
import {
  html, render, $, $$, GET, POST, PUT, DEL, state, money, num, ago, CONDITION_LABEL, toast, toastError, openModal,
  confirmDialog, withBusy, splitList, numOrNull,
} from './core.js';

const INTERVALS = [[15, '15 min'], [30, '30 min'], [60, '1 hour'], [180, '3 hours'], [360, '6 hours'], [720, '12 hours'], [1440, 'daily']];

export async function refreshLists() {
  [state.searches, state.sources] = await Promise.all([GET('/api/searches'), GET('/api/sources')]);
}

export function watchlistForm(initial = {}, onSaved) {
  const w = {
    name: '', query: '', conditions: ['new', 'used', 'refurbished', 'unknown'], min_price: null, max_price: null,
    include_keywords: [], exclude_keywords: [], sources: null, max_results: 50, interval_minutes: 60,
    enabled: true, notify: true, ai_filter: '', ...Object.fromEntries(Object.entries(initial).filter(([, v]) => v !== undefined)),
  };
  const editing = Boolean(w.id);
  const aiOn = Boolean(state.meta.ai?.backend);
  const body = document.createElement('div');
  const draw = () => render(body, html`
    ${!editing ? html`<div class="callout" style="margin-bottom:16px">
      <div class="row"><b class="grow">✨ Describe what you're looking for</b></div>
      <div class="row" style="margin-top:8px"><input type="text" data-describe class="grow" placeholder="e.g. a used Sony A7 III body with low shutter count, max 1100 €, no broken ones" ${aiOn ? '' : 'disabled'}>
      <button class="btn ai" data-draft ${aiOn ? '' : 'disabled'} title="${aiOn ? '' : 'Connect Claude in Settings → AI'}">Fill in</button></div></div>` : ''}
    <form class="form-grid" data-form>
      <label class="field span-2">Name<input type="text" name="name" required value="${w.name}"></label>
      <label class="field span-2">Search query<input type="text" name="query" required value="${w.query}"><span class="hint">Words sellers use in listing titles.</span></label>
      <div class="field span-all"><span>Condition</span><div class="row">${['new', 'used', 'refurbished', 'unknown'].map((c) => html`<label class="check"><input type="checkbox" name="conditions" value="${c}" ${w.conditions.includes(c) ? 'checked' : ''}>${CONDITION_LABEL[c]}</label>`)}</div></div>
      <label class="field">Min price<input type="number" name="min_price" min="0" step="any" value="${w.min_price ?? ''}"></label>
      <label class="field">Max price<input type="number" name="max_price" min="0" step="any" value="${w.max_price ?? ''}"></label>
      <label class="field span-2">Must contain<input type="text" name="include_keywords" value="${w.include_keywords.join(', ')}"><span class="hint">Comma separated; all must appear in the title.</span></label>
      <label class="field span-all">Exclude words<input type="text" name="exclude_keywords" value="${w.exclude_keywords.join(', ')}"><span class="hint">Comma separated, e.g. defekt, suche, tausch, hülle</span></label>
      <div class="field span-all"><span>Sources</span><div class="row">
        ${state.sources.length ? state.sources.map((s) => html`<label class="check"><input type="checkbox" name="sources" value="${s.name}" ${!w.sources || w.sources.includes(s.name) ? 'checked' : ''}>${s.name}${s.enabled ? '' : ' (disabled)'}</label>`) : html`<span class="subtle small">No sources yet - <a href="#/sources">add one</a>.</span>`}
      </div></div>
      <label class="field">Check every<select name="interval_minutes">${INTERVALS.map(([v, l]) => html`<option value="${v}" ${Number(w.interval_minutes) === v ? 'selected' : ''}>${l}</option>`)}</select></label>
      <label class="field">Max results per source<input type="number" name="max_results" min="1" max="1000" value="${w.max_results}"></label>
      <label class="field span-all">✨ AI relevance rule <span class="hint">${aiOn ? 'Claude checks every new listing against this rule and hides the rest.' : 'Needs a Claude connection (Settings → AI). Without it the rule is ignored.'}</span>
        <textarea name="ai_filter" placeholder="e.g. Only complete cameras (body), no lenses/accessories alone, no defective units or 'Suche' posts.">${w.ai_filter || ''}</textarea></label>
      <label class="switch"><input type="checkbox" name="notify" ${w.notify ? 'checked' : ''}>Notifications</label>
      <label class="switch"><input type="checkbox" name="enabled" ${w.enabled ? 'checked' : ''}>Enabled</label>
    </form>`);
  draw();
  const footer = document.createElement('div');
  footer.className = 'row';
  render(footer, html`<button class="btn" data-cancel>Cancel</button><button class="btn primary" data-save>${editing ? 'Save' : 'Create & run'}</button>`);
  const m = openModal({ title: editing ? `Edit “${w.name}”` : 'New watchlist', body, footer });

  body.addEventListener('click', (e) => {
    const b = e.target.closest('[data-draft]');
    if (!b) return;
    const text = $('[data-describe]', body).value.trim();
    if (!text) return;
    withBusy(b, async () => {
      try {
        const d = await POST('/api/ai/draft-watchlist', { text });
        Object.assign(w, { ...d, min_price: d.min_price ?? null, max_price: d.max_price ?? null });
        draw();
        $('[data-describe]', body).value = text;
        toast('Watchlist drafted - review and save', 'ok');
      } catch (err) { toastError(err); }
    });
  });
  $('[data-cancel]', footer).onclick = m.close;
  $('[data-save]', footer).onclick = (e) => withBusy(e.currentTarget, async () => {
    const form = $('[data-form]', body);
    if (!form.reportValidity()) return;
    const fd = new FormData(form);
    const selectedSources = fd.getAll('sources');
    const payload = {
      name: fd.get('name').trim(), query: fd.get('query').trim(),
      conditions: fd.getAll('conditions'),
      min_price: numOrNull(fd.get('min_price')), max_price: numOrNull(fd.get('max_price')),
      include_keywords: splitList(fd.get('include_keywords')), exclude_keywords: splitList(fd.get('exclude_keywords')),
      sources: selectedSources.length === state.sources.length ? null : selectedSources,
      interval_minutes: Number(fd.get('interval_minutes')), max_results: Number(fd.get('max_results')),
      ai_filter: fd.get('ai_filter').trim() || null, notify: fd.has('notify'), enabled: fd.has('enabled'),
    };
    if (!payload.conditions.length) { toastError('Select at least one condition'); return; }
    try {
      const saved = editing ? await PUT(`/api/searches/${w.id}`, payload) : await POST('/api/searches', payload);
      m.close();
      toast(editing ? 'Watchlist saved' : 'Watchlist created - first crawl queued', 'ok');
      await refreshLists();
      window.dispatchEvent(new Event('nc:poll'));
      onSaved?.(saved);
      if (!onSaved && !editing) location.hash = '#/watchlists';
    } catch (err) { toastError(err); }
  });
}

export async function watchlistsPage(container) {
  render(container, html`<div class="page-head"><h1>Watchlists</h1><span class="subtle">What the crawler looks for, and how often.</span><span class="spacer"></span>
    <button class="btn" data-runall>↻ Run all</button><button class="btn primary" data-new>＋ New watchlist</button></div><div id="wl"></div>`);
  const list = $('#wl', container);

  async function draw() {
    await refreshLists();
    if (!state.searches.length) {
      render(list, html`<div class="card empty"><div class="big">☰</div><div>No watchlists yet.</div><p><button class="btn primary" data-new>Create your first watchlist</button></p></div>`);
      return;
    }
    render(list, html`<div class="card">${state.searches.map((s) => html`<div class="wl-card">
      <label class="switch" title="${s.enabled ? 'Enabled' : 'Disabled'}"><input type="checkbox" data-enable="${s.id}" ${s.enabled ? 'checked' : ''}></label>
      <div class="stack" style="gap:4px;min-width:0">
        <div class="row"><a href="#/products?search=${s.id}"><h3>${s.name}</h3></a>
          <span class="status-dot ${s.last_status || 'off'}" title="${s.last_status || 'never run'}"></span>
          ${s.ai_filter ? html`<span class="badge ai" title="${s.ai_filter}">✨ AI filter</span>` : ''}${s.notify ? '' : html`<span class="badge">🔕 muted</span>`}</div>
        <div class="row small subtle" style="gap:6px">
          <span class="chip">⌕ ${s.query}</span>
          <span class="chip">${s.conditions.length === 4 ? 'any condition' : s.conditions.map((c) => CONDITION_LABEL[c]).join(' / ')}</span>
          ${s.min_price !== null || s.max_price !== null ? html`<span class="chip">${s.min_price ?? 0} – ${s.max_price ?? '∞'}</span>` : ''}
          ${s.exclude_keywords.length ? html`<span class="chip" title="${s.exclude_keywords.join(', ')}">−${s.exclude_keywords.length} words</span>` : ''}
          <span class="chip">${s.sources ? s.sources.join(', ') : 'all sources'}</span>
          <span class="chip">every ${INTERVALS.find(([v]) => v === s.interval_minutes)?.[1] || s.interval_minutes + ' min'}</span>
        </div>
        <div class="small subtle">${num(s.product_count)} listings · best ${money(s.best_price)} · last run ${ago(s.last_run_at)}</div>
      </div>
      <div class="row">
        <button class="btn sm" data-run="${s.id}">↻ Run</button>
        <a class="btn sm" href="#/products?search=${s.id}">Listings</a>
        <button class="btn sm" data-edit="${s.id}">Edit</button>
        <button class="btn sm ghost danger" data-del="${s.id}" title="Delete">🗑</button>
      </div></div>`)}</div>`);
  }

  container.addEventListener('click', async (e) => {
    const t = e.target.closest('button, input');
    if (!t) return;
    const byId = (id) => state.searches.find((s) => s.id === Number(id));
    try {
      if (t.dataset.new !== undefined) watchlistForm({}, draw);
      else if (t.dataset.runall !== undefined) { const r = await POST('/api/run-all'); toast(`${r.queued.length} watchlist(s) queued`, 'ok'); window.dispatchEvent(new Event('nc:poll')); }
      else if (t.dataset.run) { await POST(`/api/searches/${t.dataset.run}/run`); toast('Crawl queued', 'ok'); window.dispatchEvent(new Event('nc:poll')); }
      else if (t.dataset.edit) watchlistForm(byId(t.dataset.edit), draw);
      else if (t.dataset.del) {
        const s = byId(t.dataset.del);
        if (await confirmDialog(`Delete watchlist “${s.name}”? Its listings are removed too (favourites are kept).`)) { await DEL(`/api/searches/${s.id}`); toast('Deleted'); draw(); }
      }
    } catch (err) { toastError(err); }
  });
  container.addEventListener('change', async (e) => {
    const id = e.target.dataset.enable;
    if (!id) return;
    const s = state.searches.find((x) => x.id === Number(id));
    const { id: _, product_count, best_price, last_status, last_run_at, created_at, updated_at, ...payload } = s;
    try { await PUT(`/api/searches/${id}`, { ...payload, enabled: e.target.checked }); toast(e.target.checked ? 'Enabled' : 'Disabled'); draw(); } catch (err) { toastError(err); }
  });
  window.addEventListener('nc:crawl-finished', () => { if (document.body.contains(container)) draw(); });
  draw();
}
