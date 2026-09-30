// Minimal inline-SVG charts (no dependencies).
import { html, raw, money, shortDate, esc } from './core.js';

export function barChart(data, { height = 160, label = (d) => d.label, value = (d) => d.value, fmt = String } = {}) {
  if (!data.length) return html`<div class="empty small">No data yet</div>`;
  const w = 600, h = height, pad = { l: 8, r: 8, t: 16, b: 22 };
  const max = Math.max(1, ...data.map(value));
  const bw = (w - pad.l - pad.r) / data.length;
  const bars = data.map((d, i) => {
    const v = value(d), bh = (v / max) * (h - pad.t - pad.b);
    const x = pad.l + i * bw + bw * 0.15, y = h - pad.b - bh;
    return `<g><title>${esc(label(d))}: ${esc(fmt(v))}</title>
      <rect x="${x}" y="${y}" width="${bw * 0.7}" height="${Math.max(bh, 1)}" rx="3" fill="var(--accent)" opacity="${v ? 0.85 : 0.2}"/>
      ${v ? `<text x="${x + bw * 0.35}" y="${y - 4}" text-anchor="middle">${esc(fmt(v))}</text>` : ''}
      <text x="${x + bw * 0.35}" y="${h - 6}" text-anchor="middle">${esc(label(d))}</text></g>`;
  }).join('');
  return html`<svg class="chart" viewBox="0 0 ${w} ${h}" role="img">${raw(bars)}</svg>`;
}

export function priceChart(history, currency) {
  const pts = history.filter((h) => h.price !== null);
  if (pts.length < 2) {
    return html`<div class="callout small">Price unchanged since first seen${pts.length ? ` (${money(pts[0].price, currency)})` : ''}.</div>`;
  }
  const now = Date.now();
  const series = [...pts, { price: pts[pts.length - 1].price, seen_at: new Date(now).toISOString() }];
  const w = 600, h = 180, pad = { l: 64, r: 12, t: 12, b: 26 };
  const xs = series.map((p) => new Date(p.seen_at).getTime());
  const ys = series.map((p) => p.price);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), yMin = Math.min(...ys), yMax = Math.max(...ys);
  const ySpan = yMax - yMin || yMax * 0.1 || 1;
  const lo = yMin - ySpan * 0.15, hi = yMax + ySpan * 0.15;
  const X = (t) => pad.l + ((t - x0) / (x1 - x0 || 1)) * (w - pad.l - pad.r);
  const Y = (v) => pad.t + (1 - (v - lo) / (hi - lo)) * (h - pad.t - pad.b);
  let d = `M ${X(xs[0])} ${Y(ys[0])}`;
  for (let i = 1; i < series.length; i++) d += ` H ${X(xs[i])} V ${Y(ys[i])}`;
  const grid = [lo + (hi - lo) * 0.2, (lo + hi) / 2, hi - (hi - lo) * 0.2].map((v) =>
    `<line x1="${pad.l}" x2="${w - pad.r}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--border)" stroke-dasharray="3 3"/>
     <text x="${pad.l - 6}" y="${Y(v) + 4}" text-anchor="end">${esc(money(v, currency))}</text>`).join('');
  const dots = pts.map((p) => `<circle cx="${X(new Date(p.seen_at).getTime())}" cy="${Y(p.price)}" r="3.5" fill="var(--accent)"><title>${esc(shortDate(p.seen_at))}: ${esc(money(p.price, currency))}</title></circle>`).join('');
  const labels = `<text x="${pad.l}" y="${h - 6}">${esc(shortDate(series[0].seen_at))}</text><text x="${w - pad.r}" y="${h - 6}" text-anchor="end">today</text>`;
  const svg = `${grid}<path d="${d}" fill="none" stroke="var(--accent)" stroke-width="2.2"/>${dots}${labels}`;
  return html`<svg class="chart" viewBox="0 0 ${w} ${h}" role="img" aria-label="Price history">${raw(svg)}</svg>`;
}

export function stackedBar(parts) {
  const total = parts.reduce((s, p) => s + p.value, 0) || 1;
  return html`<div class="bar">${parts.map((p) => html`<span title="${p.label}: ${p.value}" style="width:${(p.value / total) * 100}%;background:${p.color}"></span>`)}</div>`;
}
