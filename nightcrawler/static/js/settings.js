// Settings: AI (Claude subscription), notifications, crawling, data, import/export.
import { html, render, $, $$, GET, PUT, POST, api, state, loadMeta, toast, toastError, withBusy, splitList } from './core.js';

function aiStatusCard(s) {
  const ok = Boolean(s.backend);
  const label = { claude_code: 'Claude subscription (Claude Code)', api: 'Anthropic API key' }[s.backend] || 'not connected';
  return html`<div class="callout ${ok ? 'info' : 'warn'}"><div class="row"><span class="status-dot ${ok ? 'ok' : 'error'}"></span>
    <b class="grow">AI: ${label}</b><button class="btn sm" data-aitest ${ok ? '' : 'disabled'}>Test connection</button></div>
    <div class="small subtle" style="margin-top:6px">Claude CLI ${s.claude_cli_installed ? 'installed' : 'missing'} ·
      subscription ${s.subscription_configured ? 'configured' : 'not configured'}${s.token_from_env ? ' (token from environment)' : ''} ·
      API key ${s.api_key_configured ? 'set' : 'not set'} · ${s.calls_last_hour}/${s.max_calls_per_hour || '∞'} calls in the last hour</div></div>`;
}

export async function settingsPage(container) {
  let s, ai;
  try { [s, ai] = await Promise.all([GET('/api/settings'), GET('/api/ai/status')]); } catch (e) { toastError(e); return; }
  render(container, html`<div class="page-head"><h1>Settings</h1><span class="spacer"></span><button class="btn primary" data-save>Save settings</button></div>
  <form class="stack" data-form style="max-width:980px;gap:16px">
    <section class="card">
      <div class="card-head"><h2>✨ AI · Claude</h2></div>
      <div class="card-pad stack">
        <div data-aistatus>${aiStatusCard(ai)}</div>
        <div class="callout small"><b>Use your Claude Pro / Max subscription</b> (no API billing):
          <ol><li>On any machine with Claude Code - or inside the container: <code>docker compose exec -it nightcrawler claude setup-token</code></li>
          <li>Log in with your Claude account in the browser; copy the token it prints (starts with <code>sk-ant-oat</code>).</li>
          <li>Paste it below (or set <code>CLAUDE_CODE_OAUTH_TOKEN</code> in <code>.env</code>) and save.</li></ol>
          AI calls count towards your subscription usage limits - keep the hourly cap reasonable.</div>
        <div class="form-grid">
          <label class="field">Backend<select name="ai_backend">${[['auto', 'Auto (subscription first)'], ['claude_code', 'Claude subscription (Claude Code)'], ['api', 'Anthropic API key'], ['off', 'Off']].map(([v, l]) => html`<option value="${v}" ${s.ai_backend === v ? 'selected' : ''}>${l}</option>`)}</select></label>
          <label class="field span-2">Subscription token<input type="password" name="ai_oauth_token" autocomplete="off" value="${s.ai_oauth_token}" placeholder="sk-ant-oat…"><span class="hint">Stored in the local database. The environment variable takes precedence.</span></label>
          <label class="field">Model<input type="text" name="ai_model" value="${s.ai_model}" placeholder="default"><span class="hint">Empty = default. e.g. <code>sonnet</code>, <code>opus</code></span></label>
          <label class="field">Effort<select name="ai_effort">${['low', 'medium', 'high'].map((v) => html`<option ${s.ai_effort === v ? 'selected' : ''}>${v}</option>`)}</select><span class="hint">For bulk listing analysis.</span></label>
          <label class="field">Max AI calls / hour<input type="number" min="0" name="ai_max_calls_per_hour" value="${s.ai_max_calls_per_hour}"><span class="hint">0 = unlimited. One call analyses up to 25 listings.</span></label>
          <label class="switch span-all"><input type="checkbox" name="ai_extract_attributes" ${s.ai_extract_attributes ? 'checked' : ''}>Extract specs with AI for every new listing (better filters, uses more of your limit)</label>
        </div>
      </div>
    </section>
    <section class="card">
      <div class="card-head"><h2>🔔 Notifications</h2></div>
      <div class="card-pad form-grid">
        <label class="field span-all">Notification URLs <span class="hint">One per line, <a href="https://github.com/caronc/apprise/wiki" target="_blank" rel="noopener">Apprise format</a>: <code>discord://id/token</code>, <code>tgram://bottoken/chatid</code>, <code>ntfy://topic</code>, <code>mailtos://user:pass@gmail.com</code>, <code>slack://…</code></span>
          <textarea name="notification_urls" rows="3" class="mono">${s.notification_urls.join('\n')}</textarea></label>
        <label class="field">Alert on price drops ≥ %<input type="number" min="0" step="any" name="notify_price_drop_pct" value="${s.notify_price_drop_pct ?? ''}"></label>
        <label class="field">Only alert new listings ≥ % below median<input type="number" step="any" name="notify_min_deal_pct" value="${s.notify_min_deal_pct ?? ''}" placeholder="all new listings"></label>
        <label class="field span-2">Public URL of this app<input type="url" name="base_url" value="${s.base_url}" placeholder="https://nightcrawler.example.com"><span class="hint">Adds a link to notifications.</span></label>
        <div class="span-all"><button type="button" class="btn" data-testnotify>Send test notification</button></div>
      </div>
    </section>
    <section class="card">
      <div class="card-head"><h2>🕸 Crawling</h2></div>
      <div class="card-pad form-grid">
        <label class="field span-2">User agent<input type="text" name="http_user_agent" value="${s.http_user_agent}"></label>
        <label class="field">Delay between requests (s)<input type="number" step="any" min="0" name="http_delay_seconds" value="${s.http_delay_seconds}"><span class="hint">Per host - be polite.</span></label>
        <label class="field">Timeout (s)<input type="number" step="any" min="1" name="http_timeout_seconds" value="${s.http_timeout_seconds}"></label>
        <label class="field">Retries<input type="number" min="0" max="10" name="http_retries" value="${s.http_retries}"></label>
        <label class="switch"><input type="checkbox" name="respect_robots_txt" ${s.respect_robots_txt ? 'checked' : ''}>Respect robots.txt</label>
      </div>
    </section>
    <section class="card">
      <div class="card-head"><h2>🗄 Data</h2></div>
      <div class="card-pad form-grid">
        <label class="field">Mark as sold/removed after<input type="number" min="1" name="gone_after_missed_runs" value="${s.gone_after_missed_runs}"><span class="hint">runs in which a listing wasn't found</span></label>
        <label class="field">Delete old listings after (days)<input type="number" min="0" name="retention_days" value="${s.retention_days}"><span class="hint">0 = keep forever. Favourites are kept.</span></label>
        <div class="span-all row"><a class="btn" href="/api/config/export">⤓ Export configuration (YAML)</a>
          <label class="btn">⤒ Import YAML<input type="file" accept=".yaml,.yml" data-import hidden></label>
          <a class="btn" href="/api/export?format=csv">⤓ All listings (CSV)</a><a class="btn" href="/api/docs" target="_blank">API docs</a></div>
      </div>
    </section>
  </form>`);

  const form = $('[data-form]', container);
  const collect = () => {
    const fd = new FormData(form);
    const out = {};
    for (const el of form.elements) {
      if (!el.name) continue;
      if (el.type === 'checkbox') out[el.name] = el.checked;
      else if (el.name === 'notification_urls') out[el.name] = splitList(fd.get(el.name).replace(/,/g, '\n'));
      else if (el.type === 'number') out[el.name] = el.value === '' ? null : Number(el.value);
      else out[el.name] = el.value;
    }
    for (const k of ['notify_price_drop_pct', 'retention_days', 'ai_max_calls_per_hour', 'http_retries']) if (out[k] === null) out[k] = 0;
    return out;
  };
  $('[data-save]', container).onclick = (e) => withBusy(e.currentTarget, async () => {
    try {
      await PUT('/api/settings', collect());
      await loadMeta();
      render($('[data-aistatus]', container), aiStatusCard(state.meta.ai));
      toast('Settings saved', 'ok');
    } catch (err) { toastError(err); }
  });
  container.addEventListener('click', async (e) => {
    const t = e.target.closest('button');
    if (!t) return;
    if (t.dataset.testnotify !== undefined) {
      await withBusy(t, async () => {
        const urls = splitList(form.elements.notification_urls.value.replace(/,/g, '\n'));
        try { const r = await POST('/api/settings/test-notification', { urls }); toast(r.message, r.ok ? 'ok' : 'error'); } catch (err) { toastError(err); }
      });
    }
    if (t.dataset.aitest !== undefined) {
      await withBusy(t, async () => {
        try { const r = await POST('/api/ai/test'); toast(r.ok ? `Claude connected via ${r.backend} ✓` : 'Unexpected answer', r.ok ? 'ok' : 'error'); } catch (err) { toastError(err); }
      });
    }
  });
  $('[data-import]', container).onchange = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    try { const r = await api('POST', '/api/config/import', await file.text()); toast(`Imported ${r.sources} sources, ${r.searches} watchlists`, 'ok'); } catch (err) { toastError(err); }
  };
}
