// Dashboard: KPIs, activity chart, top deals, latest finds, recent runs.
import { html, render, $, GET, POST, state, money, num, ago, CONDITION_LABEL, safeUrl, conditionBadge, toastError } from './core.js';
import { barChart, stackedBar } from './charts.js';
import { openProduct } from './products.js';

const COND_COLORS = { new: 'var(--good)', used: 'var(--warn)', refurbished: 'var(--info)', unknown: 'var(--border)' };

function miniCard(p) {
  return html`<div class="lrow card" data-key="${p.key}" style="grid-template-columns:56px 1fr auto;padding:8px">
    <div class="pimg" style="border-radius:6px">${p.image_url ? html`<img src="${safeUrl(p.image_url)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : html`<span class="noimg" style="font-size:20px">📦</span>`}</div>
    <div style="min-width:0"><div class="ptitle small">${p.title}</div><div class="row small subtle" style="gap:6px">${conditionBadge(p.condition)}<span>${p.source}</span><span>${ago(p.first_seen)}</span></div></div>
    <div class="right"><b>${money(p.price, p.currency)}</b>${p.deal_pct >= 5 ? html`<span class="badge deal">−${Math.round(p.deal_pct)}%</span>` : ''}</div></div>`;
}

export async function dashboardPage(container) {
  render(container, html`<div class="page-head"><h1>Dashboard</h1><span class="spacer"></span>
    <button class="btn" data-runall>↻ Run all watchlists</button><a class="btn primary" href="#/products">Browse listings →</a></div>
    <div id="dash"><div class="tiles">${Array.from({ length: 6 }, () => html`<div class="card tile skeleton" style="height:84px"></div>`)}</div></div>`);
  $('[data-runall]', container).onclick = async () => {
    try { const r = await POST('/api/run-all'); window.dispatchEvent(new Event('nc:poll')); if (!r.queued.length) toastError('Nothing queued - add or enable a watchlist first'); } catch (e) { toastError(e); }
  };

  let stats, deals, latest, runs;
  try {
    [stats, deals, latest, runs] = await Promise.all([
      GET('/api/stats'),
      POST('/api/products/search', { sort: 'deal', per_page: 6, facets: false, min_deal_pct: 5 }),
      POST('/api/products/search', { sort: 'newest', per_page: 6, facets: false }),
      GET('/api/runs?limit=8'),
    ]);
  } catch (e) { toastError(e); return; }

  const days = [];
  for (let i = 13; i >= 0; i--) {
    const d = new Date(Date.now() - i * 86400000).toISOString().slice(0, 10);
    days.push({ label: d.slice(8, 10) + '.' + d.slice(5, 7), value: stats.daily_new.find((x) => x.day === d)?.n || 0 });
  }
  const conds = Object.entries(stats.by_condition).map(([k, v]) => ({ label: CONDITION_LABEL[k] || k, value: v, color: COND_COLORS[k] }));
  const noData = !stats.watchlists && !stats.active;

  render($('#dash', container), html`
    ${noData ? html`<div class="callout info" style="margin-bottom:16px"><b>Welcome to nightcrawler!</b>
      <ol><li>Add or enable a <a href="#/sources">source</a> (eBay API, Shopify shops or any web page).</li>
      <li>Create a <a href="#/watchlists">watchlist</a> — or describe what you want and let ✨ AI set it up.</li>
      <li>Optional: connect your Claude subscription in <a href="#/settings">Settings → AI</a> and add notifications.</li></ol></div>` : ''}
    <div class="tiles">
      <a class="card tile" href="#/products"><div class="label">Active listings</div><div class="value">${num(stats.active)}</div><div class="delta">${num(stats.gone)} sold / removed</div></a>
      <a class="card tile" href="#/products?f=${encodeURIComponent('{"new_within_hours":24}')}"><div class="label">New (24 h)</div><div class="value" style="color:var(--good)">${num(stats.new_24h)}</div><div class="delta">across ${num(stats.watchlists)} watchlists</div></a>
      <a class="card tile" href="#/products?f=${encodeURIComponent('{"price_dropped":true,"sort":"drop"}')}"><div class="label">Price drops (24 h)</div><div class="value" style="color:var(--bad)">${num(stats.price_drops_24h)}</div><div class="delta">vs. first seen price</div></a>
      <a class="card tile" href="#/products?f=${encodeURIComponent('{"favorites":true,"status":"all"}')}"><div class="label">Favourites</div><div class="value">${num(stats.favorites)}</div><div class="delta">★ saved listings</div></a>
      <a class="card tile" href="#/sources"><div class="label">Sources</div><div class="value">${num(stats.sources)}</div><div class="delta">enabled</div></a>
      <a class="card tile" href="#/runs"><div class="label">Runs (24 h)</div><div class="value">${num(stats.runs_24h)}</div><div class="delta" style="${stats.failed_runs_24h ? 'color:var(--bad)' : ''}">${num(stats.failed_runs_24h)} failed</div></a>
    </div>
    <div class="dash-grid">
      <div class="card"><div class="card-head"><h2>New listings per day</h2></div><div class="card-pad">${barChart(days)}</div></div>
      <div class="card"><div class="card-head"><h2>By condition</h2></div><div class="card-pad stack">
        ${stackedBar(conds)}
        ${conds.map((c) => html`<div class="row small"><span class="status-dot" style="background:${c.color}"></span><span class="grow">${c.label}</span><b>${num(c.value)}</b></div>`)}
        <div class="section-title" style="margin-top:8px">By source</div>
        ${stats.by_source.map((s) => html`<div class="row small"><a class="grow" href="#/products?f=${encodeURIComponent(JSON.stringify({ sources: [s.source] }))}">${s.source}</a><span class="subtle">+${num(s.new_24h)} today</span><b>${num(s.n)}</b></div>`)}
      </div></div>
      <div class="card"><div class="card-head"><h2>🔥 Top deals</h2><span class="spacer"></span><a class="small" href="#/products?sort=deal">All deals →</a></div>
        <div class="card-pad list" data-list>${deals.items.length ? deals.items.map(miniCard) : html`<div class="subtle small">Deal scores appear once a watchlist has at least 3 comparable listings.</div>`}</div></div>
      <div class="card"><div class="card-head"><h2>Recent runs</h2><span class="spacer"></span><a class="small" href="#/runs">All runs →</a></div>
        <div class="tbl-wrap"><table class="tbl"><tbody>${runs.length ? runs.map((r) => html`<tr>
          <td><span class="badge ${r.status}">${r.status}</span></td><td>${r.search_name}</td><td class="num subtle">+${r.new}</td><td class="subtle small">${ago(r.started_at)}</td></tr>`) : html`<tr><td class="subtle">No runs yet</td></tr>`}</tbody></table></div></div>
      <div class="card wide"><div class="card-head"><h2>Latest finds</h2><span class="spacer"></span><a class="small" href="#/products">All listings →</a></div>
        <div class="card-pad list" data-list style="display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr))">${latest.items.length ? latest.items.map(miniCard) : html`<div class="subtle small">Nothing found yet.</div>`}</div></div>
    </div>`);
  container.addEventListener('click', (e) => {
    const row = e.target.closest('[data-key]');
    if (row) openProduct(row.dataset.key);
  });
}
