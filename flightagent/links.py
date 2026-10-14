"""Deep links into booking sites so a found fare can be verified and booked there."""

from __future__ import annotations

from datetime import date as Date
from urllib.parse import quote, urlparse

from .models import Link


def search_links(origin: str, dest: str, day: str, adults: int = 1, google_url: str | None = None) -> list[Link]:
    d = Date.fromisoformat(day)
    o, t = quote(origin), quote(dest)
    links = []
    if google_url:
        links.append(Link("Google Flights", google_url))
    links += [
        Link("Skyscanner", f"https://www.skyscanner.com/transport/flights/{o.lower()}/{t.lower()}/{d:%y%m%d}/?adultsv2={adults}"),
        Link(
            "Expedia",
            "https://www.expedia.com/Flights-Search?trip=oneway"
            f"&leg1=from:{o},to:{t},departure:{d.month}/{d.day}/{d.year}TANYT"
            f"&passengers=adults:{adults}&mode=search",
        ),
        Link("Kayak", f"https://www.kayak.com/flights/{o}-{t}/{day}/{adults}adults?sort=price_a"),
        Link("Skiplagged", f"https://skiplagged.com/flights/{o}/{t}/{day}"),
    ]
    return links


def safe_url(url: str | None) -> str | None:
    """Only pass through http(s) URLs from third-party data to the UI/email."""
    if not url:
        return None
    return url if urlparse(url).scheme in ("http", "https") else None
