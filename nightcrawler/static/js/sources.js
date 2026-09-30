// Sources: configure adapters with dynamic forms, live test preview, ✨ AI selector detection.
import {
  html, render, $, $$, GET, POST, PUT, DEL, state, money, attrValue, attrDef, conditionBadge, toast, toastError,
  openModal, confirmDialog, withBusy, numOrNull,
} from './core.js';
import { refreshLists } from './watchlists.js';

const typeInfo = (type) => state.meta.source_types.find((t) => t.type === type);

function fieldInput(f, value) {
  const v = value ?? f.default ?? '';
  const hint = f.help ? html`<span class="hint">${f.help}</span>` : '';
  switch (f.type) {
    case 'bool':
      return html`<div class="field"><label class="switch"><input type="checkbox" data-opt="${f.name}" data-kind="bool" ${value ?? f.default ? 'checked' : ''}>${f.label}</label>${hint}</div>`;
    case 'select':
      return html`<label class="field">${f.label}<select data-opt="${f.name}">${f.choices.map((c) => html`<option ${c === v ? 'selected' : ''}>${c}</option>`)}</select>${hint}</label>`;
    case 'number':
      return html`<label class="field">${f.label}<input type="number" step="any" data-opt="${f.name}" data-kind="number" value="${value ?? f.default ?? ''}">${hint}</label>`;
    case 'secret':
      return html`<label class="field span-2">${f.label}${f.required ? ' *' : ''}<input type="text" autocomplete="off" data-opt="${f.name}" value="${v}" ${f.required ? 'required' : ''}>${hint}</label>`;
    case 'selectors': {
      const cur = value || {};
      return html`<div class="field span-all"><span>${f.label}${f.required ? ' *' : ''} ${hint}</span>
        <div class="form-grid" style="grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:8px">${f.keys.map((k) => html`<label class="field small"><span class="mono">${k}${['item', 'title'].includes(k) ? ' *' : ''}</span><input type="text" class="mono" data-sel="${k}" value="${cur[k] || ''}" placeholder="${k === 'item' ? 'e.g. li.result' : ''}"></label>`)}</div></div>`;
    }
    case 'map': {
      const rows = Object.entries(value || {});
      return html`<div class="field span-all"><span>${f.label} ${hint}</span><div class="stack" style="gap:6px" data-map="${f.name}">
        ${[...rows, ['', '']].map(([k, val]) => html`<div class="kvrows"><input type="text" placeholder="attribute (e.g. brand)" value="${k}" data-mk><input type="text" class="mono" placeholder="CSS selector" value="${val}" data-mv><span></span></div>`)}
        </div><button type="button" class="btn sm" data-addrow="${f.name}" style="align-self:flex-start">＋ Row</button></div>`;
    }
    default:
      return html`<label class="field ${f.name.includes('url') ? 'span-all' : ''}">${f.label}${f.required ? ' *' : ''}<input type="text" data-opt="${f.name}" value="${v}" ${f.required ? 'required' : ''}>${hint}</label>`;
  }
}

function readOptions(root, type) {
  const opts = {};
  for (const f of typeInfo(type).fields) {
    if (f.type === 'selectors') {
      const sel = {};
      $$('[data-sel]', root).forEach((i) => { if (i.value.trim()) sel[i.dataset.sel] = i.value.trim(); });
      opts[f.name] = sel;
    } else if (f.type === 'map') {
      const m = {};
      $$(`[data-map="${f.name}"] .kvrows`, root).forEach((r) => { const k = $('[data-mk]', r).value.trim(); const v = $('[data-mv]', r).value.trim(); if (k && v) m[k] = v; });
      if (Object.keys(m).length) opts[f.name] = m;
    } else {
      const input = $(`[data-opt="${f.name}"]`, root);
      if (!input) continue;
      if (input.dataset.kind === 'bool') opts[f.name] = input.checked;
      else if (input.dataset.kind === 'number') { const n = numOrNull(input.value); if (n !== null) opts[f.name] = n; }
      else if (input.value.trim()) opts[f.name] = input.value.trim();
    }
  }
  return opts;
}

function sourceForm(existing, onSaved) {
  let type = existing?.type || state.meta.source_types[0].type;
  let options = existing?.options || {};
  const body = document.createElement('div');
  const draw = () => {
    const info = typeInfo(type);
    render(body, html`
      ${existing ? '' : html`<div class="form-grid" style="margin-bottom:14px">${state.meta.source_types.map((t) => html`
        <button type="button" class="card card-pad" data-type="${t.type}" style="text-align:left;cursor:pointer;${t.type === type ? 'border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-weak)' : ''}">
          <b>${t.label}</b><div class="small subtle" style="margin-top:4px">${t.description}</div></button>`)}</div>`}
      <form class="form-grid" data-form>
        <label class="field">Name *<input type="text" name="name" required pattern="[\\w.-]+" value="${existing?.name || ''}" placeholder="e.g. ebay-de"><span class="hint">Letters, digits, - _ .</span></label>
        <label class="switch" style="align-self:end"><input type="checkbox" name="enabled" ${existing?.enabled ?? true ? 'checked' : ''}>Enabled</label>
        ${info.fields.map((f) => fieldInput(f, options[f.name]))}
      </form>
      <div class="card card-pad stack" style="margin-top:16px">
        <div class="row"><h3 class="grow">Test</h3><input type="text" data-testq placeholder="test query" value="thinkpad" style="width:180px">
          ${type === 'html' ? html`<button type="button" class="btn sm ai" data-detect ${state.meta.ai?.backend ? '' : 'disabled title="Connect Claude in Settings → AI"'}>✨ Detect selectors</button>` : ''}
          <button type="button" class="btn sm" data-test>▶ Run test</button></div>
        <div data-testout class="small subtle">Runs the source once without saving and shows what would be found, including extracted specs.</div>
      </div>`);
  };
  draw();

  const footer = document.createElement('div');
  footer.className = 'row';
  render(footer, html`<button class="btn" data-cancel>Cancel</button><button class="btn primary" data-save>Save</button>`);
  const m = openModal({ title: existing ? `Edit source “${existing.name}”` : 'Add source', body, footer, wide: true });

  const collect = () => {
    const form = $('[data-form]', body);
    return { name: form.elements.name.value.trim() || 'test', type, enabled: form.elements.enabled.checked, options: readOptions(body, type) };
  };

  body.addEventListener('click', async (e) => {
    const t = e.target.closest('button');
    if (!t) return;
    if (t.dataset.type) { options = readOptions(body, type); type = t.dataset.type; draw(); return; }
    if (t.dataset.addrow) {
      const wrap = $(`[data-map="${t.dataset.addrow}"]`, body);
      wrap.insertAdjacentHTML('beforeend', String(html`<div class="kvrows"><input type="text" placeholder="attribute" data-mk><input type="text" class="mono" placeholder="CSS selector" data-mv><span></span></div>`));
      return;
    }
    const out = $('[data-testout]', body);
    const query = $('[data-testq]', body).value.trim() || 'test';
    if (t.dataset.test !== undefined) {
      await withBusy(t, async () => {
        try {
          const r = await POST('/api/sources/test', { source: collect(), query, limit: 12 });
          if (!r.ok) { render(out, html`<div class="callout warn">${r.error}</div>`); return; }
          if (!r.items.length) { render(out, html`<div class="callout warn">No listings found. Check the URL and selectors (item/title).</div>`); return; }
          render(out, html`<div class="subtle" style="margin-bottom:6px">${r.items.length} listings parsed:</div><div class="tbl-wrap"><table class="tbl"><thead><tr><th>Title</th><th>Condition</th><th class="num">Price</th><th class="num">Shipping</th><th>Extracted specs</th></tr></thead><tbody>
            ${r.items.map((p) => html`<tr><td><a href="${p.url}" target="_blank" rel="noopener noreferrer">${p.title}</a></td><td>${conditionBadge(p.condition)}</td><td class="num">${money(p.price, p.currency)}</td><td class="num">${p.shipping ?? '?'}</td>
            <td>${Object.entries(p.attributes).map(([k, v]) => html`<span class="chip" style="margin:1px">${attrDef(k)?.label || k}: ${attrValue(k, v)}</span>`)}</td></tr>`)}</tbody></table></div>`);
        } catch (err) { toastError(err); }
      });
    }
    if (t.dataset.detect !== undefined) {
      const url = ($('[data-opt="search_url"]', body)?.value || '').replace('{query}', encodeURIComponent(query)).replace('{page}', '1');
      if (!url) { toastError('Enter the search URL first'); return; }
      await withBusy(t, async () => {
        try {
          const s = await POST('/api/ai/suggest-selectors', { url });
          for (const [k, v] of Object.entries(s)) { const input = $(`[data-sel="${k}"]`, body); if (input && v) input.value = v; }
          render(out, html`<div class="callout info">✨ Selectors filled in. ${s.notes || ''} ${s.html_truncated ? '(Page was large - only the first part was analysed.)' : ''} Click “Run test” to verify.</div>`);
        } catch (err) { toastError(err); }
      });
    }
  });

  $('[data-cancel]', footer).onclick = m.close;
  $('[data-save]', footer).onclick = (e) => withBusy(e.currentTarget, async () => {
    const form = $('[data-form]', body);
    if (!form.reportValidity()) return;
    try {
      const payload = collect();
      if (existing) await PUT(`/api/sources/${existing.id}`, payload); else await POST('/api/sources', payload);
      toast('Source saved', 'ok');
      m.close();
      onSaved?.();
    } catch (err) { toastError(err); }
  });
}

export async function sourcesPage(container) {
  render(container, html`<div class="page-head"><h1>Sources</h1><span class="subtle">Where the crawler looks.</span><span class="spacer"></span><button class="btn primary" data-new>＋ Add source</button></div><div id="src"></div>`);
  const list = $('#src', container);
  async function draw() {
    await refreshLists();
    if (!state.sources.length) {
      render(list, html`<div class="card empty"><div class="big">⛁</div><div>No sources configured.</div><p><button class="btn primary" data-new>Add a source</button></p></div>`);
      return;
    }
    render(list, html`<div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(300px,1fr))">${state.sources.map((s) => html`
      <div class="card card-pad stack" style="gap:8px">
        <div class="row"><h3 class="grow">${s.name}</h3><label class="switch"><input type="checkbox" data-enable="${s.id}" ${s.enabled ? 'checked' : ''}></label></div>
        <div class="small subtle">${typeInfo(s.type)?.label || s.type}</div>
        <div class="small mono" style="word-break:break-all">${s.options.search_url || s.options.store_url || s.options.marketplace || ''}</div>
        <div class="row"><button class="btn sm" data-edit="${s.id}">Edit & test</button><a class="btn sm" href="#/products?f=${encodeURIComponent(JSON.stringify({ sources: [s.name] }))}">Listings</a><span class="grow"></span><button class="btn sm ghost danger" data-del="${s.id}">🗑</button></div>
      </div>`)}</div>`);
  }
  container.addEventListener('click', async (e) => {
    const t = e.target.closest('button');
    if (!t) return;
    const byId = (id) => state.sources.find((s) => s.id === Number(id));
    if (t.dataset.new !== undefined) sourceForm(null, draw);
    if (t.dataset.edit) sourceForm(byId(t.dataset.edit), draw);
    if (t.dataset.del) {
      const s = byId(t.dataset.del);
      if (await confirmDialog(`Delete source “${s.name}”? Stored listings stay until they expire.`)) {
        try { await DEL(`/api/sources/${s.id}`); draw(); } catch (err) { toastError(err); }
      }
    }
  });
  container.addEventListener('change', async (e) => {
    const id = e.target.dataset.enable;
    if (!id) return;
    const s = state.sources.find((x) => x.id === Number(id));
    try { await PUT(`/api/sources/${id}`, { name: s.name, type: s.type, options: s.options, enabled: e.target.checked }); toast(e.target.checked ? 'Enabled' : 'Disabled'); draw(); } catch (err) { toastError(err); }
  });
  draw();
}
