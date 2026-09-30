// Runs: crawl history with errors, auto-refreshing while something is running.
import { html, render, $, GET, state, num, ago, dateTime, toastError } from './core.js';
import { refreshLists } from './watchlists.js';

export async function runsPage(container) {
  await refreshLists().catch(toastError);
  render(container, html`<div class="page-head"><h1>Runs</h1><span class="subtle">Crawl history and errors.</span><span class="spacer"></span>
    <select data-filter><option value="">All watchlists</option>${state.searches.map((s) => html`<option value="${s.id}">${s.name}</option>`)}</select></div>
    <div class="card tbl-wrap" id="runs"></div>`);
  const el = $('#runs', container);
  let timer;
  async function draw() {
    const id = $('[data-filter]', container).value;
    let runs;
    try { runs = await GET(`/api/runs?limit=200${id ? `&search_id=${id}` : ''}`); } catch (e) { toastError(e); return; }
    render(el, runs.length ? html`<table class="tbl"><thead><tr><th>Status</th><th>Watchlist</th><th>Trigger</th><th>Started</th><th class="num">Duration</th>
      <th class="num">Fetched</th><th class="num">Matched</th><th class="num">New</th><th class="num">Drops</th><th>Messages</th></tr></thead><tbody>
      ${runs.map((r) => {
        const dur = r.finished_at ? (new Date(r.finished_at) - new Date(r.started_at)) / 1000 : null;
        return html`<tr><td><span class="badge ${r.status}">${r.status === 'running' ? html`<span class="spinner" style="width:10px;height:10px"></span>` : ''}${r.status}</span></td>
          <td>${r.search_id ? html`<a href="#/products?search=${r.search_id}">${r.search_name}</a>` : r.search_name}</td><td class="subtle">${r.trigger}</td>
          <td title="${dateTime(r.started_at)}">${ago(r.started_at)}</td><td class="num">${dur === null ? '…' : dur < 60 ? `${dur.toFixed(0)} s` : `${(dur / 60).toFixed(1)} min`}</td>
          <td class="num">${num(r.fetched)}</td><td class="num">${num(r.matched)}</td><td class="num"><b>${num(r.new)}</b></td><td class="num">${num(r.price_drops)}</td>
          <td class="small" style="max-width:420px">${r.errors.length ? html`<details><summary style="color:var(--bad);cursor:pointer">${r.errors.length} message(s)</summary>${r.errors.map((e) => html`<div class="mono" style="white-space:pre-wrap;margin-top:4px">${e}</div>`)}</details>` : html`<span class="subtle">–</span>`}</td></tr>`;
      })}</tbody></table>` : html`<div class="empty"><div class="big">↻</div>No runs yet.</div>`);
    clearTimeout(timer);
    if (runs.some((r) => r.status === 'running') && document.body.contains(container)) timer = setTimeout(draw, 4000);
  }
  $('[data-filter]', container).onchange = draw;
  window.addEventListener('nc:crawl-finished', () => { if (document.body.contains(container)) draw(); });
  draw();
}
