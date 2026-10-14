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


def render(search: dict, options: list[dict], reason: str, site_url: str | None) -> tuple[str, str, str]:
    best = options[0]
    cur = best["currency"]
    subject = f"✈ {search['name']}: {cur} {best['price']:.0f} ({reason})"

    def route(o):
        return " → ".join([o["segments"][0]["origin"]] + [s["destination"] for s in o["segments"]])

    rows, text = [], [f"{reason}\n{search['name']} on {search['date']}\n"]
    for o in options[:5]:
        links = o["links"] or [l for t in o.get("ticket_links", []) for l in t["links"]]
        link_html = " · ".join(f'<a href="{escape(l["url"])}">{escape(l["name"])}</a>' for l in links[:4])
        flags = []
        if o["separate_tickets"]:
            flags.append("separate tickets")
        if o["hidden_city"]:
            flags.append("hidden-city")
        rows.append(
            "<tr>"
            f"<td style='padding:6px 10px'><b>{escape(cur)} {o['price']:.0f}</b></td>"
            f"<td style='padding:6px 10px'>{escape(route(o))}<br><small>{escape(', '.join(o['airlines']))}"
            f" · {fmt_minutes(o['total_minutes'])} · departs {escape(o['segments'][0]['depart'].replace('T', ' '))}"
            f"{' · ' + escape(', '.join(flags)) if flags else ''}</small></td>"
            f"<td style='padding:6px 10px'><small>{escape(o['strategy'])} via {escape(o['source'])}</small><br>{link_html}</td>"
            "</tr>"
        )
        text.append(f"{cur} {o['price']:.0f}  {route(o)}  [{o['strategy']}, {o['source']}]  " + (links[0]["url"] if links else ""))
    site = f'<p><a href="{escape(site_url)}">Open dashboard</a></p>' if site_url else ""
    html = (
        f"<div style='font-family:system-ui,sans-serif'><h2 style='margin:0'>{escape(search['name'])}</h2>"
        f"<p>{escape(reason)} · {escape(str(search['date']))}</p>"
        f"<table style='border-collapse:collapse'>{''.join(rows)}</table>{site}"
        "<p style='color:#666;font-size:12px'>Prices change quickly; confirm on the booking site.</p></div>"
    )
    if site_url:
        text.append(f"\nDashboard: {site_url}")
    return subject, html, "\n".join(text)
