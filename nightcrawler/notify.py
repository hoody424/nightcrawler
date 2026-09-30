"""Notifications through Apprise (Discord, Telegram, Slack, ntfy, e-mail, Gotify, Pushover, ...).

See https://github.com/caronc/apprise/wiki for URL formats, e.g.
  discord://webhook_id/webhook_token   tgram://bot_token/chat_id   ntfy://topic
  mailtos://user:pass@gmail.com        slack://tokenA/tokenB/tokenC
"""

from __future__ import annotations

import logging

import apprise

from .models import Product

log = logging.getLogger(__name__)


def _price(value: float | None, currency: str | None) -> str:
    return "n/a" if value is None else f"{value:,.2f} {currency or ''}".strip()


def send(urls: list[str], title: str, body: str) -> tuple[bool, str]:
    urls = [u for u in urls if u and u.strip()]
    if not urls:
        return False, "no notification URLs configured"
    ap = apprise.Apprise()
    invalid = [u for u in urls if not ap.add(u.strip())]
    if invalid:
        log.warning("ignoring %d invalid notification URL(s)", len(invalid))
    if not len(ap):
        return False, "none of the notification URLs is valid"
    ok = ap.notify(title=title, body=body, body_format=apprise.NotifyFormat.MARKDOWN)
    return bool(ok), "sent" if ok else "delivery failed (see logs)"


def format_alert(search_name: str, new: list[tuple[Product, float | None]],
                 drops: list[tuple[Product, float]], base_url: str = "") -> tuple[str, str]:
    parts = []
    if new:
        parts.append(f"{len(new)} new")
    if drops:
        parts.append(f"{len(drops)} price drop{'s' if len(drops) > 1 else ''}")
    title = f"nightcrawler · {search_name}: {', '.join(parts)}"
    lines = []
    for p, deal in new[:15]:
        deal_txt = f" · **{deal:.0f}% below median**" if deal and deal > 0 else ""
        if p.shipping is None:
            ship = ""
        else:
            ship = " + free shipping" if p.shipping == 0 else f" + {_price(p.shipping, p.currency)} shipping"
        price = _price(p.price, p.currency)
        lines.append(f"🆕 [{p.condition.value}] [{p.title}]({p.url}) — {price}{ship}{deal_txt}")
    for p, old in drops[:15]:
        pct = (old - p.price) / old * 100 if old else 0
        was, now = _price(old, p.currency), _price(p.price, p.currency)
        lines.append(f"📉 [{p.title}]({p.url}) — {was} → **{now}** (−{pct:.0f}%)")
    remaining = max(0, len(new) - 15) + max(0, len(drops) - 15)
    if remaining:
        lines.append(f"…and {remaining} more")
    if base_url:
        lines.append(f"\n[Open nightcrawler]({base_url.rstrip('/')}/#/products)")
    return title, "\n".join(lines)
