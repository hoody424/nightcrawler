// Products: Geizhals-style faceted search, result views, product drawer and comparison.
import {
  html, raw, render, $, $$, api, GET, POST, PATCH, state, store, money, num, ago, dateTime, attrDef, attrValue,
  CONDITION_LABEL, LISTING_LABEL, countryLabel, conditionBadge, safeUrl, toast, toastError, openDrawer, openModal,
  debounce, withBusy,
} from './core.js';
import { priceChart } from './charts.js';

const EMPTY_FILTER = {
  q: '', search_ids: [], conditions: [], sources: [], listing_types: [], countries: [],
  price_min: null, price_max: null, include_shipping: false, free_shipping: false, seller_rating_min: null,
  min_deal_pct: null, price_dropped: false, new_within_hours: null, status: 'active', favorites: false,
  include_hidden: false, include_rejected: false, attrs: {}, ranges: {}, flags: {}, sort: 'newest', page: 1,
  per_page: 48,
};
const SORTS = [
  ['newest', 'Newest first'], ['price_asc', 'Price: low → high'], ['price_desc', 'Price: high → low'],
  ['deal', 'Best deal (vs. median)'], ['drop', 'Biggest price drop'], ['seller_rating', 'Seller rating'],
  ['last_seen', 'Recently seen'], ['title', 'Title A–Z'],
];
const KEY_SPECS = ['brand', 'storage_gb', 'ram_gb', 'cpu', 'gpu', 'screen_in', 'resolution', 'color'];
const TABLE_SPECS = ['brand', 'category', 'storage_gb', 'ram_gb', 'cpu', 'gpu', 'screen_in'];

export const compare = {
  keys: new Map(Object.entries(store.get('compare', {}))),
  toggle(item) {
    if (this.keys.has(item.key)) this.keys.delete(item.key);
    else if (this.keys.size >= 6) { toast('You can compare up to 6 listings'); return; }
    else this.keys.set(item.key, { title: item.title, image_url: item.image_url });
    store.set('compare', Object.fromEntries(this.keys));
    renderCompareTray();
  },
  clear() { this.keys.clear(); store.set('compare', {}); renderCompareTray(); },
};

export function filterFromHash() {
  const params = new URLSearchParams(location.hash.split('?')[1] || '');
  let f = { ...structuredClone(EMPTY_FILTER) };
  if (params.get('f')) {
    try { f = { ...f, ...JSON.parse(params.get('f')) }; } catch { /* ignore broken link */ }
  }
  if (params.get('search')) f.search_ids = [Number(params.get('search'))];
  if (params.get('q')) f.q = params.get('q');
  if (params.get('sort')) f.sort = params.get('sort');
  return f;
}
export function productsHash(f) {
  const diff = Object.fromEntries(Object.entries(f).filter(([k, v]) => JSON.stringify(v) !== JSON.stringify(EMPTY_FILTER[k])));
  return '#/products' + (Object.keys(diff).length ? '?f=' + encodeURIComponent(JSON.stringify(diff)) : '');
}

// ====================================================================== page
export function productsPage(container, { aiExplanation } = {}) {
  const F = filterFromHash();
  let view = store.get('view', 'grid');
  let data = null;
  let controller = null;
  let expanded = new Set();
  const collapsed = new Set(store.get('collapsedFacets', ['model', 'color', 'year', 'megapixels', 'refresh_hz', 'vram_gb', 'countries', 'seller_rating', 'listing_types']));
  let explanation = aiExplanation || null;

  render(container, html`
    <div class="products-layout">
      <aside class="facets" id="facets"><div class="skeleton" style="height:400px"></div></aside>
      <section>
        <div id="aiBanner"></div>
        <div class="results-toolbar">
          <button class="btn sm only-narrow" id="openFacets">⚲ Filters</button>
          <span class="count" id="count">…</span>
          <span class="grow"></span>
          <select id="sort" aria-label="Sort">${SORTS.map(([v, l]) => html`<option value="${v}">${l}</option>`)}</select>
          <div class="seg" id="viewSeg">
            <button data-view="grid" title="Grid">▦</button><button data-view="list" title="List">☰</button><button data-view="table" title="Spec table">▤</button>
          </div>
          <button class="btn sm" id="saveWatchlist" title="Create a watchlist from these filters">＋ Watchlist</button>
          <button class="btn sm" id="share" title="Copy link to these filters">🔗</button>
          <button class="btn sm" id="export" title="Export results">⤓ CSV</button>
        </div>
        <div class="chips" id="chips"></div>
        <div id="results"></div>
        <div class="pager" id="pager"></div>
      </section>
    </div>`);

  const facetsEl = $('#facets', container);
  const resultsEl = $('#results', container);

  // ------------------------------------------------------------- loading
  async function load({ keepFacets = false } = {}) {
    controller?.abort();
    controller = new AbortController();
    history.replaceState(null, '', productsHash(F));
    $('#sort', container).value = F.sort;
    $$('#viewSeg button', container).forEach((b) => b.classList.toggle('on', b.dataset.view === view));
    resultsEl.style.opacity = '.55';
    try {
      data = await POST('/api/products/search', { ...F, facets: !keepFacets || !data }, { signal: controller.signal });
    } catch (e) {
      if (e.name !== 'AbortError') toastError(e);
      return;
    } finally { resultsEl.style.opacity = ''; }
    if (!data.facets && keepFacets) data.facets = lastFacets; else lastFacets = data.facets;
    renderAll();
  }
  let lastFacets = null;
  const reload = debounce(() => { F.page = 1; load(); }, 250);
  const set = (patch) => { Object.assign(F, patch); F.page = 1; load(); };

  function renderAll() {
    $('#count', container).textContent = `${num(data.total)} listing${data.total === 1 ? '' : 's'}`;
    renderBanner();
    renderChips();
    renderFacets();
    renderResults();
    renderPager();
  }

  function renderBanner() {
    render($('#aiBanner', container), explanation ? html`<div class="ai-banner"><span>✨</span><span class="grow">${explanation}</span><button class="btn sm ghost" data-dismiss>✕</button></div>` : '');
    const b = $('[data-dismiss]', container);
    if (b) b.onclick = () => { explanation = null; renderBanner(); };
  }

  // --------------------------------------------------------------- chips
  function chipList() {
    const chips = [];
    const facets = data?.facets || lastFacets;
    const searchLabel = (id) => state.searches.find((s) => s.id === id)?.name || facets?.searches.find((s) => s.value === id)?.label || `#${id}`;
    if (F.q) chips.push([`“${F.q}”`, () => set({ q: '' })]);
    F.search_ids.forEach((id) => chips.push([`Watchlist: ${searchLabel(id)}`, () => set({ search_ids: F.search_ids.filter((x) => x !== id) })]));
    F.conditions.forEach((c) => chips.push([CONDITION_LABEL[c] || c, () => set({ conditions: F.conditions.filter((x) => x !== c) })]));
    F.listing_types.forEach((c) => chips.push([LISTING_LABEL[c] || c, () => set({ listing_types: F.listing_types.filter((x) => x !== c) })]));
    F.sources.forEach((c) => chips.push([`Source: ${c}`, () => set({ sources: F.sources.filter((x) => x !== c) })]));
    F.countries.forEach((c) => chips.push([countryLabel(c), () => set({ countries: F.countries.filter((x) => x !== c) })]));
    if (F.price_min !== null || F.price_max !== null) {
      chips.push([`Price ${F.price_min ?? 0} – ${F.price_max ?? '∞'}${F.include_shipping ? ' incl. shipping' : ''}`, () => set({ price_min: null, price_max: null })]);
    }
    if (F.free_shipping) chips.push(['Free shipping', () => set({ free_shipping: false })]);
    if (F.seller_rating_min !== null) chips.push([`Seller ≥ ${F.seller_rating_min}%`, () => set({ seller_rating_min: null })]);
    if (F.min_deal_pct !== null) chips.push([`≥ ${F.min_deal_pct}% below median`, () => set({ min_deal_pct: null })]);
    if (F.price_dropped) chips.push(['Price dropped', () => set({ price_dropped: false })]);
    if (F.new_within_hours) chips.push([`New in last ${F.new_within_hours >= 24 ? F.new_within_hours / 24 + ' d' : F.new_within_hours + ' h'}`, () => set({ new_within_hours: null })]);
    if (F.favorites) chips.push(['★ Favourites', () => set({ favorites: false })]);
    if (F.status !== 'active') chips.push([F.status === 'gone' ? 'Sold / removed' : 'Active + removed', () => set({ status: 'active' })]);
    for (const [name, values] of Object.entries(F.attrs)) {
      values.forEach((v) => chips.push([`${attrDef(name)?.label || name}: ${attrValue(name, v)}`, () => {
        const next = { ...F.attrs, [name]: F.attrs[name].filter((x) => x !== v) };
        if (!next[name].length) delete next[name];
        set({ attrs: next });
      }]));
    }
    for (const [name, [lo, hi]] of Object.entries(F.ranges)) {
      if (lo === null && hi === null) continue;
      const unit = attrDef(name)?.unit || '';
      chips.push([`${attrDef(name)?.label || name}: ${lo ?? '…'} – ${hi ?? '…'} ${unit}`, () => {
        const next = { ...F.ranges }; delete next[name]; set({ ranges: next });
      }]);
    }
    for (const [name, mode] of Object.entries(F.flags)) {
      chips.push([`${mode === 'only' ? '' : 'No '}${attrDef(name)?.label || name}`, () => {
        const next = { ...F.flags }; delete next[name]; set({ flags: next });
      }]);
    }
    return chips;
  }
  function renderChips() {
    const chips = chipList();
    const el = $('#chips', container);
    render(el, chips.length ? html`${chips.map(([label], i) => html`<span class="fchip">${label}<button data-chip="${i}" aria-label="Remove">✕</button></span>`)}
      <button class="btn sm ghost" data-clear>Clear all</button>` : '');
    $$('[data-chip]', el).forEach((b) => { b.onclick = () => chips[Number(b.dataset.chip)][1](); });
    const clear = $('[data-clear]', el);
    if (clear) clear.onclick = () => { Object.assign(F, structuredClone(EMPTY_FILTER), { sort: F.sort, per_page: F.per_page }); load(); };
  }

  // -------------------------------------------------------------- facets
  function facet(id, title, body, active = false) {
    const isCollapsed = collapsed.has(id);
    return html`<div class="facet ${isCollapsed ? 'collapsed' : ''}" data-facet="${id}">
      <div class="facet-head" data-toggle="${id}"><span>${title}${active ? raw('<span class="active-dot"></span>') : ''}</span><span class="caret">▾</span></div>
      <div class="facet-body">${body}</div></div>`;
  }
  function checkList(id, values, selected, labelFn = (v) => v, { filterBox = true } = {}) {
    const sel = new Set(selected.map(String));
    const byValue = new Map(values.map((v) => [String(v.value), v]));
    selected.forEach((s) => { if (!byValue.has(String(s))) byValue.set(String(s), { value: s, count: 0 }); });
    let list = [...byValue.values()];
    const limit = expanded.has(id) ? Infinity : 8;
    const visible = list.filter((v, i) => i < limit || sel.has(String(v.value)));
    return html`
      ${filterBox && list.length > 12 && expanded.has(id) ? html`<input type="search" class="facet-filter" placeholder="Filter…" data-ffilter="${id}">` : ''}
      ${visible.map((v) => html`<label class="fv ${v.count ? '' : 'zero'}" data-fv-label="${String(labelFn(v.value, v)).toLowerCase()}">
        <input type="checkbox" data-check="${id}" value="${v.value}" ${sel.has(String(v.value)) ? 'checked' : ''}>
        <span class="fv-label" title="${labelFn(v.value, v)}">${labelFn(v.value, v)}</span><span class="fv-count">${num(v.count)}</span></label>`)}
      ${list.length > 8 ? html`<button class="facet-more" data-more="${id}">${expanded.has(id) ? 'Show less' : `Show all ${list.length}`}</button>` : ''}`;
  }
  function radioList(id, options, current) {
    return html`${options.map(([value, label, count]) => html`<label class="fv ${count === 0 ? 'zero' : ''}">
      <input type="radio" name="${id}" data-radio="${id}" value="${value ?? ''}" ${String(current ?? '') === String(value ?? '') ? 'checked' : ''}>
      <span class="fv-label">${label}</span>${count !== undefined ? html`<span class="fv-count">${num(count)}</span>` : ''}</label>`)}`;
  }

  function priceFacet(p) {
    const lo = p.min ?? 0, hi = p.max ?? 0;
    const maxCount = Math.max(1, ...p.histogram.map((b) => b.count));
    const curLo = F.price_min ?? lo, curHi = F.price_max ?? hi;
    const step = hi - lo > 1000 ? 10 : 1;
    return html`
      ${p.histogram.length ? html`<div class="histogram">${p.histogram.map((b, i) => html`<div data-bucket="${i}" class="${b.to >= curLo && b.from <= curHi ? 'in' : ''}" style="height:${(b.count / maxCount) * 100}%" title="${money(b.from)} – ${money(b.to)}: ${b.count}"></div>`)}</div>
      <div class="dual-range"><div class="track"><span style="left:${((curLo - lo) / (hi - lo || 1)) * 100}%;right:${100 - ((curHi - lo) / (hi - lo || 1)) * 100}%"></span></div>
        <input type="range" min="${lo}" max="${hi}" step="${step}" value="${curLo}" data-slider="min" aria-label="Minimum price">
        <input type="range" min="${lo}" max="${hi}" step="${step}" value="${curHi}" data-slider="max" aria-label="Maximum price"></div>` : ''}
      <div class="range-row"><input type="number" placeholder="${lo}" value="${F.price_min ?? ''}" data-price="min" aria-label="Min price"><span>–</span><input type="number" placeholder="${hi}" value="${F.price_max ?? ''}" data-price="max" aria-label="Max price"></div>
      <label class="check small" style="margin-top:8px"><input type="checkbox" data-bool="include_shipping" ${F.include_shipping ? 'checked' : ''}>Price incl. shipping</label>
      <label class="check small"><input type="checkbox" data-bool="free_shipping" ${F.free_shipping ? 'checked' : ''}>Free shipping only <span class="subtle">(${num(data.facets.shipping.free)})</span></label>`;
  }

  function attributeFacet(def, fa) {
    if (def.kind === 'flag') {
      const mode = F.flags[def.name] || '';
      if (!fa.only && !mode) return '';
      return html`<div class="tri"><span class="fv-label">${def.label}</span><div class="seg" data-flag="${def.name}">
        <button data-mode="" class="${mode === '' ? 'on' : ''}">Any</button>
        <button data-mode="only" class="${mode === 'only' ? 'on' : ''}" title="${fa.only} listings">Yes ${num(fa.only)}</button>
        <button data-mode="exclude" class="${mode === 'exclude' ? 'on' : ''}" title="${fa.exclude} listings">No</button></div></div>`;
    }
    const selected = F.attrs[def.name] || [];
    const range = F.ranges[def.name] || [null, null];
    if (!fa.values.length && !selected.length && range[0] === null && range[1] === null) return '';
    const label = (v) => attrValue(def.name, v);
    let body = checkList(`attr:${def.name}`, fa.values, selected, label);
    if (def.kind === 'number' && fa.values.length > 1) {
      body = html`${body}<div class="range-row"><input type="number" placeholder="min ${fa.min ?? ''}" value="${range[0] ?? ''}" data-range="${def.name}" data-end="0"><span>–</span><input type="number" placeholder="max ${fa.max ?? ''}" value="${range[1] ?? ''}" data-range="${def.name}" data-end="1"><span class="subtle small">${def.unit || ''}</span></div>`;
    }
    return facet(`attr:${def.name}`, def.label, body, selected.length > 0 || range[0] !== null || range[1] !== null);
  }

  function renderFacets() {
    const fc = data.facets;
    const groups = {};
    for (const def of state.meta.attributes) (groups[def.group] ||= []).push(def);
    const flagsHtml = (groups['Listing details'] || []).map((d) => attributeFacet(d, fc.attributes[d.name]));
    const dealOpts = [[null, 'Any'], ...fc.deal.map((d) => [d.value, `≥ ${d.value}% below median`, d.count])];
    const ratingOpts = [[null, 'Any'], ...fc.seller_rating.map((r) => [r.value, `≥ ${r.value}% positive`, r.count])];
    render(facetsEl, html`
      <div class="row" style="justify-content:space-between;margin-bottom:4px"><h2>Filters</h2><button class="icon-btn only-narrow" data-close-facets>✕</button></div>
      <input type="search" placeholder="Search in results…" value="${F.q}" data-q style="width:100%;margin:6px 0 4px">
      <div class="facet-group-title">Overview</div>
      <div class="facet"><div class="facet-body">
        <div class="seg" data-status style="margin-bottom:6px">${[['active', 'Active'], ['gone', 'Sold/removed'], ['all', 'All']].map(([v, l]) => html`<button data-v="${v}" class="${F.status === v ? 'on' : ''}">${l}</button>`)}</div>
        <div class="seg" data-new style="margin-bottom:6px">${[[null, 'Any time'], [24, '24 h'], [72, '3 d'], [168, '7 d']].map(([v, l]) => html`<button data-v="${v ?? ''}" class="${(F.new_within_hours ?? '') === (v ?? '') ? 'on' : ''}">${l}</button>`)}</div>
        <label class="check small"><input type="checkbox" data-bool="favorites" ${F.favorites ? 'checked' : ''}>★ Favourites only</label>
        <label class="check small"><input type="checkbox" data-bool="price_dropped" ${F.price_dropped ? 'checked' : ''}>📉 Price dropped</label>
        <label class="check small"><input type="checkbox" data-bool="include_hidden" ${F.include_hidden ? 'checked' : ''}>Show hidden</label>
        <label class="check small" title="Listings the AI filter judged irrelevant"><input type="checkbox" data-bool="include_rejected" ${F.include_rejected ? 'checked' : ''}>Show AI-rejected</label>
      </div></div>
      ${fc.searches.length || F.search_ids.length ? facet('searches', 'Watchlist', checkList('searches', fc.searches, F.search_ids, (v, o) => o?.label || state.searches.find((s) => s.id === Number(v))?.name || v), F.search_ids.length > 0) : ''}
      ${facet('price', 'Price', priceFacet(fc.price), F.price_min !== null || F.price_max !== null || F.free_shipping)}
      ${facet('conditions', 'Condition', checkList('conditions', fc.conditions, F.conditions, (v) => CONDITION_LABEL[v] || v), F.conditions.length > 0)}
      ${facet('deal', 'Deal score', radioList('min_deal_pct', dealOpts, F.min_deal_pct), F.min_deal_pct !== null)}
      ${facet('listing_types', 'Offer type', checkList('listing_types', fc.listing_types, F.listing_types, (v) => LISTING_LABEL[v] || v), F.listing_types.length > 0)}
      ${facet('sources', 'Source', checkList('sources', fc.sources, F.sources), F.sources.length > 0)}
      ${fc.countries.length ? facet('countries', 'Item location', checkList('countries', fc.countries, F.countries, countryLabel), F.countries.length > 0) : ''}
      ${fc.seller_rating.some((r) => r.count) ? facet('seller_rating', 'Seller rating', radioList('seller_rating_min', ratingOpts, F.seller_rating_min), F.seller_rating_min !== null) : ''}
      ${['General', 'Specs'].map((g) => {
        const parts = (groups[g] || []).map((d) => attributeFacet(d, fc.attributes[d.name])).filter((p) => String(p));
        return parts.length ? html`<div class="facet-group-title">${g === 'Specs' ? 'Specifications' : 'Product'}</div>${parts}` : '';
      })}
      ${flagsHtml.some((p) => String(p)) ? html`<div class="facet-group-title">Listing details</div><div class="facet"><div class="facet-body">${flagsHtml}</div></div>` : ''}
    `);
  }

  // ------------------------------------------------------------- results
  function priceBlock(p) {
    const dropped = p.first_price && p.price !== null && p.first_price > p.price;
    return html`<div class="pprice">${money(F.include_shipping && p.total_price !== null ? p.total_price : p.price, p.currency)}${dropped ? html`<span class="old">${money(p.first_price, p.currency)}</span>` : ''}</div>
      <div class="pship">${p.shipping === null ? 'shipping unknown' : p.shipping === 0 ? 'free shipping' : `+ ${money(p.shipping, p.currency)} shipping`}${F.include_shipping && p.shipping ? ' (incl.)' : ''}</div>`;
  }
  function badges(p) {
    return html`${p.deal_pct >= 5 ? html`<span class="badge deal" title="Below the median price of comparable listings">−${Math.round(p.deal_pct)}%</span>` : ''}
      ${p.drop_pct ? html`<span class="badge drop">📉 −${Math.round(p.drop_pct)}%</span>` : ''}
      ${p.gone ? html`<span class="badge gone">sold/removed</span>` : ''}`;
  }
  const specs = (p) => KEY_SPECS.filter((k) => p.attributes[k]).slice(0, 4).map((k) => html`<span class="chip">${attrValue(k, p.attributes[k])}</span>`);
  const img = (p) => (p.image_url ? html`<img src="${safeUrl(p.image_url)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : html`<span class="noimg">📦</span>`);
  const meta = (p) => html`<span>${p.source}</span>${p.location || p.country ? html`<span>📍 ${p.location || countryLabel(p.country)}</span>` : ''}${p.seller_rating ? html`<span>★ ${num(p.seller_rating, 1)}%</span>` : ''}<span title="${dateTime(p.first_seen)}">${ago(p.first_seen)}</span>`;

  function renderResults() {
    if (!data.items.length) {
      render(resultsEl, html`<div class="card empty"><div class="big">🔍</div><div>No listings match these filters.</div>
        ${chipList().length ? html`<p class="small">Try removing a filter above, or <a href="#/watchlists">add a watchlist</a>.</p>` : html`<p class="small">Add a <a href="#/watchlists">watchlist</a> and let the crawler run.</p>`}</div>`);
      return;
    }
    if (view === 'grid') {
      render(resultsEl, html`<div class="grid">${data.items.map((p, i) => html`
        <article class="card pcard ${p.gone ? 'is-gone' : ''}" data-open="${i}">
          <div class="pimg">${img(p)}</div>
          <div class="pbadges">${badges(p)}</div>
          <div class="pactions"><button class="${p.favorite ? 'on' : ''}" data-fav="${i}" title="Favourite">${p.favorite ? '★' : '☆'}</button><button data-hide="${i}" title="${p.hidden ? 'Unhide' : 'Hide'}">${p.hidden ? '👁' : '⨯'}</button></div>
          <div class="pbody">
            <div class="row" style="gap:4px">${conditionBadge(p.condition)}${p.listing_type !== 'fixed' && p.listing_type !== 'unknown' ? html`<span class="badge">${LISTING_LABEL[p.listing_type]}</span>` : ''}</div>
            <div class="ptitle" title="${p.title}">${p.title}</div>
            <div class="pspecs">${specs(p)}</div>
            ${priceBlock(p)}
            <div class="pmeta">${meta(p)}</div>
            <label class="pcompare" data-stop><input type="checkbox" data-cmp="${i}" ${compare.keys.has(p.key) ? 'checked' : ''}>Compare</label>
          </div></article>`)}</div>`);
    } else if (view === 'list') {
      render(resultsEl, html`<div class="list">${data.items.map((p, i) => html`
        <article class="card lrow ${p.gone ? 'is-gone' : ''}" data-open="${i}">
          <div class="pimg">${img(p)}</div>
          <div class="stack" style="gap:5px;min-width:0">
            <div class="row" style="gap:4px">${conditionBadge(p.condition)}${badges(p)}${p.listing_type !== 'fixed' && p.listing_type !== 'unknown' ? html`<span class="badge">${LISTING_LABEL[p.listing_type]}</span>` : ''}</div>
            <div class="ptitle">${p.title}</div>
            <div class="pspecs">${KEY_SPECS.filter((k) => p.attributes[k]).map((k) => html`<span class="chip">${attrDef(k)?.label}: ${attrValue(k, p.attributes[k])}</span>`)}</div>
            <div class="pmeta">${meta(p)}${p.seller ? html`<span>👤 ${p.seller}</span>` : ''}${p.searches ? html`<span>☰ ${p.searches}</span>` : ''}</div>
          </div>
          <div class="right">${priceBlock(p)}
            <div class="row"><button class="btn sm ${p.favorite ? 'primary' : ''}" data-fav="${i}">${p.favorite ? '★' : '☆'}</button>
            <label class="pcompare" data-stop><input type="checkbox" data-cmp="${i}" ${compare.keys.has(p.key) ? 'checked' : ''}>Compare</label></div>
          </div></article>`)}</div>`);
    } else {
      const cols = TABLE_SPECS.filter((k) => data.items.some((p) => p.attributes[k]));
      render(resultsEl, html`<div class="card tbl-wrap"><table class="tbl"><thead><tr><th></th><th>Listing</th><th>Condition</th>
        ${cols.map((k) => html`<th>${attrDef(k)?.label}</th>`)}<th class="num">Price</th><th class="num">Shipping</th><th class="num">Deal</th><th>Source</th><th>Seen</th></tr></thead>
        <tbody>${data.items.map((p, i) => html`<tr class="click" data-open="${i}">
          <td data-stop><input type="checkbox" data-cmp="${i}" ${compare.keys.has(p.key) ? 'checked' : ''} title="Compare"></td>
          <td style="max-width:380px">${p.favorite ? '★ ' : ''}${p.title}</td><td>${conditionBadge(p.condition)}</td>
          ${cols.map((k) => html`<td>${p.attributes[k] ? attrValue(k, p.attributes[k]) : html`<span class="subtle">–</span>`}</td>`)}
          <td class="num"><b>${money(p.price, p.currency)}</b></td>
          <td class="num">${p.shipping === null ? '?' : p.shipping === 0 ? 'free' : money(p.shipping, p.currency)}</td>
          <td class="num">${p.deal_pct !== null ? html`<span style="color:${p.deal_pct > 0 ? 'var(--good)' : 'var(--muted)'}">${p.deal_pct > 0 ? '−' : '+'}${Math.abs(Math.round(p.deal_pct))}%</span>` : '–'}</td>
          <td>${p.source}</td><td class="subtle">${ago(p.first_seen)}</td></tr>`)}</tbody></table></div>`);
    }
  }

  function renderPager() {
    const el = $('#pager', container);
    if (data.pages <= 1) { el.innerHTML = ''; return; }
    const pages = [];
    for (let i = 1; i <= data.pages; i++) {
      if (i === 1 || i === data.pages || Math.abs(i - F.page) <= 2) pages.push(i);
      else if (pages[pages.length - 1] !== '…') pages.push('…');
    }
    render(el, html`<button class="btn sm" data-page="${F.page - 1}" ${F.page <= 1 ? 'disabled' : ''}>‹</button>
      ${pages.map((p) => (p === '…' ? html`<span class="subtle">…</span>` : html`<button class="btn sm ${p === F.page ? 'primary' : ''}" data-page="${p}">${p}</button>`))}
      <button class="btn sm" data-page="${F.page + 1}" ${F.page >= data.pages ? 'disabled' : ''}>›</button>`);
  }

  // -------------------------------------------------------------- events
  facetsEl.addEventListener('click', (e) => {
    const t = e.target;
    const toggle = t.closest('[data-toggle]');
    if (toggle) {
      const id = toggle.dataset.toggle;
      collapsed.has(id) ? collapsed.delete(id) : collapsed.add(id);
      store.set('collapsedFacets', [...collapsed]);
      toggle.parentElement.classList.toggle('collapsed');
      return;
    }
    if (t.closest('[data-close-facets]')) { facetsEl.classList.remove('open'); return; }
    if (t.dataset.more) { expanded.has(t.dataset.more) ? expanded.delete(t.dataset.more) : expanded.add(t.dataset.more); renderFacets(); return; }
    const segBtn = t.closest('.seg button');
    if (segBtn) {
      const seg = segBtn.parentElement;
      if (seg.dataset.status !== undefined) set({ status: segBtn.dataset.v });
      else if (seg.dataset.new !== undefined) set({ new_within_hours: segBtn.dataset.v ? Number(segBtn.dataset.v) : null });
      else if (seg.dataset.flag) {
        const flags = { ...F.flags };
        if (segBtn.dataset.mode) flags[seg.dataset.flag] = segBtn.dataset.mode; else delete flags[seg.dataset.flag];
        set({ flags });
      }
      return;
    }
    if (t.dataset.bucket !== undefined) {
      const b = data.facets.price.histogram[Number(t.dataset.bucket)];
      set({ price_min: Math.floor(b.from), price_max: Math.ceil(b.to) });
    }
  });
  facetsEl.addEventListener('change', (e) => {
    const t = e.target;
    if (t.dataset.check) {
      const id = t.dataset.check;
      const values = $$(`[data-check="${CSS.escape(id)}"]:checked`, facetsEl).map((x) => x.value);
      if (id === 'searches') set({ search_ids: values.map(Number) });
      else if (id.startsWith('attr:')) {
        const name = id.slice(5);
        const attrs = { ...F.attrs, [name]: values };
        if (!values.length) delete attrs[name];
        set({ attrs });
      } else set({ [id]: values });
    } else if (t.dataset.radio) {
      set({ [t.dataset.radio]: t.value === '' ? null : Number(t.value) });
    } else if (t.dataset.bool) {
      set({ [t.dataset.bool]: t.checked });
    } else if (t.dataset.price) {
      set({ [t.dataset.price === 'min' ? 'price_min' : 'price_max']: t.value === '' ? null : Number(t.value) });
    } else if (t.dataset.range) {
      const r = [...(F.ranges[t.dataset.range] || [null, null])];
      r[Number(t.dataset.end)] = t.value === '' ? null : Number(t.value);
      const ranges = { ...F.ranges, [t.dataset.range]: r };
      if (r[0] === null && r[1] === null) delete ranges[t.dataset.range];
      set({ ranges });
    } else if (t.dataset.slider) {
      const [a, b] = $$('[data-slider]', facetsEl).map((x) => Number(x.value));
      const p = data.facets.price;
      set({ price_min: Math.min(a, b) <= p.min ? null : Math.min(a, b), price_max: Math.max(a, b) >= p.max ? null : Math.max(a, b) });
    }
  });
  facetsEl.addEventListener('input', (e) => {
    const t = e.target;
    if (t.dataset.q !== undefined) { F.q = t.value; reload(); }
    if (t.dataset.ffilter) {
      const q = t.value.toLowerCase();
      $$(`[data-check="${CSS.escape(t.dataset.ffilter)}"]`, facetsEl).forEach((cb) => {
        const label = cb.closest('.fv');
        label.hidden = !label.dataset.fvLabel.includes(q);
      });
    }
    if (t.dataset.slider) {  // live track feedback while dragging
      const [a, b] = $$('[data-slider]', facetsEl).map((x) => Number(x.value));
      const [pmin, pmax] = $$('[data-price]', facetsEl);
      pmin.value = Math.min(a, b); pmax.value = Math.max(a, b);
    }
  });

  resultsEl.addEventListener('click', async (e) => {
    const t = e.target;
    if (t.closest('[data-stop]') && !t.dataset.cmp) return;
    if (t.dataset.cmp !== undefined) { compare.toggle(data.items[Number(t.dataset.cmp)]); return; }
    const fav = t.closest('[data-fav]');
    if (fav) {
      e.stopPropagation();
      const p = data.items[Number(fav.dataset.fav)];
      try { const u = await PATCH(`/api/products/${encodeURIComponent(p.key)}`, { favorite: !p.favorite }); p.favorite = u.favorite; renderResults(); } catch (err) { toastError(err); }
      return;
    }
    const hide = t.closest('[data-hide]');
    if (hide) {
      e.stopPropagation();
      const p = data.items[Number(hide.dataset.hide)];
      try { await PATCH(`/api/products/${encodeURIComponent(p.key)}`, { hidden: !p.hidden }); toast(p.hidden ? 'Listing restored' : 'Listing hidden'); load({ keepFacets: false }); } catch (err) { toastError(err); }
      return;
    }
    const open = t.closest('[data-open]');
    if (open) openProduct(data.items[Number(open.dataset.open)].key, () => load());
  });

  $('#pager', container).addEventListener('click', (e) => {
    const b = e.target.closest('[data-page]');
    if (b && !b.disabled) { F.page = Number(b.dataset.page); load({ keepFacets: true }); window.scrollTo({ top: 0, behavior: 'smooth' }); }
  });
  $('#sort', container).onchange = (e) => { F.sort = e.target.value; F.page = 1; load({ keepFacets: true }); };
  $('#viewSeg', container).onclick = (e) => {
    const b = e.target.closest('[data-view]');
    if (!b) return;
    view = b.dataset.view; store.set('view', view);
    $$('#viewSeg button', container).forEach((x) => x.classList.toggle('on', x === b));
    renderResults();
  };
  $('#openFacets', container).onclick = () => facetsEl.classList.add('open');
  $('#share', container).onclick = async () => {
    try { await navigator.clipboard.writeText(location.href); toast('Link copied', 'ok'); } catch { prompt('Copy this link:', location.href); }
  };
  $('#export', container).onclick = () => {
    const { page, per_page, ...rest } = F;
    location.href = `/api/export?format=csv&filter=${encodeURIComponent(JSON.stringify(rest))}`;
  };
  $('#saveWatchlist', container).onclick = async () => {
    const { watchlistForm } = await import('./watchlists.js');
    watchlistForm({
      name: F.q || 'New watchlist', query: F.q,
      conditions: F.conditions.length ? F.conditions : undefined,
      min_price: F.price_min, max_price: F.price_max,
    });
  };

  window.addEventListener('nc:crawl-finished', onCrawlFinished);
  function onCrawlFinished() { if (document.body.contains(container)) load({ keepFacets: false }); else window.removeEventListener('nc:crawl-finished', onCrawlFinished); }

  renderCompareTray();
  load();
  return { setFilter(patch, why) { Object.assign(F, structuredClone(EMPTY_FILTER), patch); explanation = why || null; load(); } };
}

// ============================================================ product drawer
export async function openProduct(key, onChange) {
  const d = openDrawer('Listing');
  render(d.body, html`<div class="skeleton" style="height:260px"></div><div class="skeleton" style="height:120px"></div>`);
  let p;
  try { p = await GET(`/api/products/${encodeURIComponent(key)}`); } catch (e) { render(d.body, html`<div class="callout warn">${e.message}</div>`); return; }

  const draw = () => {
    const defs = state.meta.attributes;
    const attrRows = defs.filter((a) => p.attributes[a.name] !== undefined);
    const extra = Object.keys(p.attributes).filter((k) => !attrDef(k));
    const aiOn = Boolean(state.meta.ai?.backend);
    render(d.body, html`
      ${p.image_url ? html`<img class="hero-img" src="${safeUrl(p.image_url)}" alt="" referrerpolicy="no-referrer">` : ''}
      <div class="stack" style="gap:8px">
        <div class="row" style="gap:6px">${conditionBadge(p.condition)}<span class="badge">${LISTING_LABEL[p.listing_type] || p.listing_type}</span>${p.gone ? html`<span class="badge gone">sold / removed</span>` : ''}</div>
        <h2 style="font-size:18px">${p.title}</h2>
        <div class="row" style="align-items:baseline;gap:12px">
          <span class="pprice" style="font-size:26px">${money(p.price, p.currency)}</span>
          <span class="subtle">${p.shipping === null ? 'shipping unknown' : p.shipping === 0 ? 'free shipping' : `+ ${money(p.shipping, p.currency)} shipping`}</span>
        </div>
        <div class="row">
          <a class="btn primary" href="${safeUrl(p.url)}" target="_blank" rel="noopener noreferrer">Open listing ↗</a>
          <button class="btn" data-fav>${p.favorite ? '★ Favourite' : '☆ Favourite'}</button>
          <button class="btn" data-hide>${p.hidden ? 'Unhide' : 'Hide'}</button>
          <label class="btn"><input type="checkbox" data-cmp ${compare.keys.has(p.key) ? 'checked' : ''}> Compare</label>
        </div>
      </div>
      <div class="card card-pad stack">
        <div class="row"><h3 class="grow">✨ AI deal check</h3>
          <button class="btn sm ai" data-assess ${aiOn ? '' : 'disabled'} title="${aiOn ? 'Ask Claude to judge this listing' : 'Connect Claude in Settings → AI'}">${p.ai_assessment ? 'Re-check' : 'Check this deal'}</button></div>
        <div data-assessment>${p.ai_assessment ? assessmentView(p.ai_assessment, p.currency) : html`<div class="subtle small">${aiOn ? 'Claude compares the price with similar listings and its history, looks for scam signals and suggests questions for the seller.' : 'Connect your Claude subscription in Settings → AI to enable deal checks.'}</div>`}</div>
      </div>
      <div class="card card-pad"><h3 style="margin-bottom:8px">Price history</h3>${priceChart(p.history, p.currency)}</div>
      <div class="card card-pad">
        <h3 style="margin-bottom:10px">Details</h3>
        <dl class="kv">
          <dt>Source</dt><dd>${p.source}</dd>
          ${p.seller ? html`<dt>Seller</dt><dd>${p.seller}${p.seller_rating ? ` · ★ ${num(p.seller_rating, 1)}% positive` : ''}</dd>` : ''}
          ${p.location || p.country ? html`<dt>Location</dt><dd>${[p.location, countryLabel(p.country)].filter((x) => x && x !== '–').join(' · ')}</dd>` : ''}
          <dt>First seen</dt><dd>${dateTime(p.first_seen)}</dd>
          <dt>Last seen</dt><dd>${dateTime(p.last_seen)}</dd>
          ${attrRows.map((a) => html`<dt>${a.label}</dt><dd>${attrValue(a.name, p.attributes[a.name])}</dd>`)}
          ${extra.map((k) => html`<dt>${k.replace(/_/g, ' ')}</dt><dd>${p.attributes[k]}</dd>`)}
        </dl>
        ${p.description ? html`<p class="small subtle" style="margin-top:12px;white-space:pre-line">${p.description}</p>` : ''}
      </div>
      <div class="card card-pad"><h3 style="margin-bottom:8px">Watchlists</h3>
        ${p.matches.map((m) => html`<div class="row small" style="padding:4px 0"><a href="#/products?search=${m.search_id}" class="grow">${m.search_name}</a>
          ${m.deal_pct !== null ? html`<span class="badge ${m.deal_pct > 0 ? 'deal' : ''}">${m.deal_pct > 0 ? '−' : '+'}${Math.abs(Math.round(m.deal_pct))}% vs median</span>` : ''}
          ${m.ai_relevant === 0 ? html`<span class="badge error" title="${m.ai_reason}">AI: not relevant</span>` : m.ai_relevant === 1 ? html`<span class="badge ai" title="${m.ai_reason}">AI: relevant</span>` : ''}</div>
          ${m.ai_reason ? html`<div class="small subtle" style="margin:-2px 0 6px">${m.ai_reason}</div>` : ''}`)}
      </div>
      <div class="card card-pad"><h3 style="margin-bottom:8px">Note</h3>
        <textarea data-note placeholder="Your notes (e.g. asked seller about battery health)…" style="width:100%">${p.note || ''}</textarea></div>`);

    $('[data-fav]', d.body).onclick = async () => { p = { ...p, ...(await PATCH(`/api/products/${encodeURIComponent(key)}`, { favorite: !p.favorite })) }; draw(); onChange?.(); };
    $('[data-hide]', d.body).onclick = async () => { p = { ...p, ...(await PATCH(`/api/products/${encodeURIComponent(key)}`, { hidden: !p.hidden })) }; draw(); onChange?.(); };
    $('[data-cmp]', d.body).onchange = () => compare.toggle(p);
    $('[data-note]', d.body).onchange = async (e) => { await PATCH(`/api/products/${encodeURIComponent(key)}`, { note: e.target.value }); toast('Note saved', 'ok'); };
    $('[data-assess]', d.body).onclick = (e) => withBusy(e.currentTarget, async () => {
      try { p.ai_assessment = await POST(`/api/products/${encodeURIComponent(key)}/assess`); draw(); } catch (err) { toastError(err); }
    });
  };
  draw();
}

function assessmentView(a, currency) {
  const colors = { great: 'var(--good)', good: '#3f9d5a', fair: 'var(--warn)', overpriced: 'var(--bad)', suspicious: 'var(--bad)' };
  const list = (title, items, icon) => (items?.length ? html`<div><b class="small">${title}</b><ul class="small">${items.map((i) => html`<li>${icon} ${i}</li>`)}</ul></div>` : '');
  return html`<div class="assessment">
    <div class="row" style="gap:12px;flex-wrap:nowrap"><span class="score" style="background:${colors[a.verdict] || 'var(--muted)'}">${a.score}</span>
      <div><div style="font-weight:700;text-transform:capitalize">${a.verdict}${a.fair_price ? html` <span class="subtle small" style="font-weight:500">· fair price ≈ ${money(a.fair_price, currency)}</span>` : ''}</div><div class="small">${a.summary}</div></div></div>
    ${list('Pros', a.pros, '✓')}${list('Cons', a.cons, '–')}${list('Red flags', a.red_flags, '⚠')}${list('Ask the seller', a.questions_for_seller, '?')}
  </div>`;
}

// ================================================================= compare
export function renderCompareTray() {
  const tray = $('#compareTray');
  if (!compare.keys.size) { tray.hidden = true; return; }
  tray.hidden = false;
  render(tray, html`${[...compare.keys.values()].map((p) => (p.image_url ? html`<img src="${safeUrl(p.image_url)}" alt="" title="${p.title}" referrerpolicy="no-referrer">` : ''))}
    <b>${compare.keys.size}</b> selected
    <button class="btn sm primary" data-go ${compare.keys.size < 2 ? 'disabled' : ''}>Compare</button>
    <button class="btn sm ghost" data-clear>Clear</button>`);
  $('[data-go]', tray).onclick = openCompare;
  $('[data-clear]', tray).onclick = () => compare.clear();
}

async function openCompare() {
  const items = await POST('/api/compare', { keys: [...compare.keys.keys()] });
  const attrs = state.meta.attributes.filter((a) => items.some((p) => p.attributes[a.name] !== undefined));
  const totals = items.map((p) => (p.price === null ? Infinity : p.price + (p.shipping || 0)));
  const bestTotal = Math.min(...totals);
  const rows = [
    ['Price', (p) => money(p.price, p.currency)],
    ['Shipping', (p) => (p.shipping === null ? '?' : p.shipping === 0 ? 'free' : money(p.shipping, p.currency))],
    ['Total', (p, i) => raw(`<b>${money(totals[i] === Infinity ? null : totals[i], p.currency)}</b>`), (p, i) => totals[i] === bestTotal],
    ['Condition', (p) => conditionBadge(p.condition)],
    ['Offer type', (p) => LISTING_LABEL[p.listing_type] || p.listing_type],
    ['Seller', (p) => p.seller || '–'],
    ['Seller rating', (p) => (p.seller_rating ? `${num(p.seller_rating, 1)}%` : '–')],
    ['Location', (p) => [p.location, p.country].filter(Boolean).join(', ') || '–'],
    ['Source', (p) => p.source],
    ['First seen', (p) => ago(p.first_seen)],
    ...attrs.map((a) => [a.label, (p) => (p.attributes[a.name] !== undefined ? attrValue(a.name, p.attributes[a.name]) : '–'), null, a.name]),
  ];
  const cell = (r, p, i) => { const v = r[1](p, i); return v instanceof Object && v.s !== undefined ? v : String(v); };
  openModal({
    title: `Compare ${items.length} listings`,
    wide: true,
    body: html`<div class="tbl-wrap"><table class="tbl cmp"><thead><tr><th></th>${items.map((p) => html`<th style="min-width:200px;white-space:normal;vertical-align:top">
      ${p.image_url ? html`<img src="${safeUrl(p.image_url)}" alt="" style="width:100%;height:110px;object-fit:contain;background:#fff;border-radius:6px" referrerpolicy="no-referrer">` : ''}
      <a href="${safeUrl(p.url)}" target="_blank" rel="noopener noreferrer" style="color:var(--text)">${p.title}</a></th>`)}</tr></thead>
      <tbody>${rows.map((r) => {
        const values = items.map((p, i) => String(cell(r, p, i)));
        const differs = new Set(values).size > 1;
        return html`<tr><td class="subtle">${r[0]}</td>${items.map((p, i) => html`<td class="${r[2]?.(p, i) ? 'best' : differs && r[3] ? 'diff' : ''}">${cell(r, p, i)}</td>`)}</tr>`;
      })}</tbody></table></div>
      <p class="small subtle">Green = cheapest total price · highlighted = specs that differ.</p>`,
  });
}
