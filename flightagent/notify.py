"""Gmail notifications over SMTP using an App Password.

Needs env vars GMAIL_ADDRESS and GMAIL_APP_PASSWORD (Google Account ->
Security -> 2-Step Verification -> App passwords). EMAIL_TO is optional and
defaults to GMAIL_ADDRESS. Credentials are never written to disk.
"""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from html import escape

log = logging.getLogger(__name__)


def configured() -> bool:
    return bool(os.environ.get("GMAIL_ADDRESS") and os.environ.get("GMAIL_APP_PASSWORD"))


def send(subject: str, html_body: str, text_body: str) -> bool:
    if not configured():
        log.info("email not configured; would have sent: %s", subject)
        return False
    sender = os.environ["GMAIL_ADDRESS"]
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = os.environ.get("EMAIL_TO") or sender
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=30) as s:
        s.login(sender, os.environ["GMAIL_APP_PASSWORD"])
        s.send_message(msg)
    log.info("email sent: %s", subject)
    return True


def fmt_minutes(m: int) -> str:
    return f"{m // 60}h {m % 60:02d}m"


def _route(o: dict) -> str:
    """AMD → KWI (4h 50m) → IST (3h 10m) → IAD"""
    segs = o["segments"]
    parts = [segs[0]["origin"]]
    for a, b in zip(segs, segs[1:]):
        lay = int((datetime.fromisoformat(b["depart"]) - datetime.fromisoformat(a["arrive"])).total_seconds() // 60)
        parts.append(f"{a['destination']} ({fmt_minutes(lay)})")
    parts.append(segs[-1]["destination"])
    return " → ".join(parts)


def _stops(o: dict) -> str:
    return f"{o['stops']} stop{'s' if o['stops'] != 1 else ''}"


def render_digest(searches: list[dict], site_url: str | None) -> tuple[str, str, str]:
    """One email covering every search: what changed, then the top options for each."""
    top = min(searches, key=lambda d: d["options"][0]["score"])
    b0, cur = top["options"][0], top["options"][0]["currency"]
    improved = any(d["change"].startswith("better") for d in searches)
    subject = (
        f"✈ {'New best: ' if improved else ''}{cur} {b0['price']:.0f} on {top['date']}, "
        f"{fmt_minutes(b0['total_minutes'])}, {_stops(b0)}"
    )
    html, text = [], []
    for d in searches:
        rows = []
        text.append(f"\n{d['name']} ({d['date']}): {d['change']}")
        for o in d["options"][:4]:
            links = o["links"] or [l for t in o.get("ticket_links", []) for l in t["links"]]
            link_html = " · ".join(f'<a href="{escape(l["url"])}">{escape(l["name"])}</a>' for l in links[:4])
            flags = []
            if o["separate_tickets"]:
                flags.append("separate tickets")
            if o["hidden_city"]:
                flags.append("hidden-city")
            for code, l in (o.get("lounges") or {}).items():
                best = f", best {l['best']['rating']:.1f}★" if l["best"]["rating"] else ""
                flags.append(f"Priority Pass at {code}: {l['count']} lounge(s){best}")
            rows.append(
                "<tr>"
                f"<td style='padding:6px 10px;vertical-align:top'><b>{escape(cur)} {o['price']:.0f}</b></td>"
                f"<td style='padding:6px 10px'>{escape(_route(o))}<br><small>{escape(', '.join(o['airlines']))}"
                f" · {fmt_minutes(o['total_minutes'])} · {_stops(o)} · departs {escape(o['segments'][0]['depart'].replace('T', ' '))}"
                f"{'<br>' + escape(' · '.join(flags)) if flags else ''}</small></td>"
                f"<td style='padding:6px 10px;vertical-align:top'><small>{escape(o['source'])}</small><br>{link_html}</td>"
                "</tr>"
            )
            text.append(f"  {cur} {o['price']:.0f}  {_route(o)}  {fmt_minutes(o['total_minutes'])}, {_stops(o)}  " + (links[0]["url"] if links else ""))
        html.append(
            f"<h3 style='margin:18px 0 2px'>{escape(d['name'])}</h3>"
            f"<p style='margin:0 0 6px;color:#555'>{escape(d['change'])}</p>"
            f"<table style='border-collapse:collapse'>{''.join(rows)}</table>"
        )
    site = f'<p><a href="{escape(site_url)}">Open dashboard</a></p>' if site_url else ""
    body = (
        "<div style='font-family:system-ui,sans-serif'>" + "".join(html) + site
        + "<p style='color:#666;font-size:12px'>Ranked by price + travel time + layovers. Prices change quickly; confirm on the booking site.</p></div>"
    )
    if site_url:
        text.append(f"\nDashboard: {site_url}")
    return subject, body, "\n".join(text).strip()
