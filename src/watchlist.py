import re
from dataclasses import dataclass
from pathlib import Path
from typing import List
from urllib.parse import urlparse

ALLOWED_HOSTS = {"www.homedepot.com", "homedepot.com"}


@dataclass
class WatchlistEntry:
    url: str
    internet_number: str


class InvalidProductUrlError(ValueError):
    pass


def _extract_internet_number(url: str) -> str:
    match = re.search(r"/(\d+)/?$", url.strip())
    if not match:
        raise InvalidProductUrlError(f"Could not extract Internet # from URL: {url}")
    return match.group(1)


def normalize_product_input(raw: str) -> str:
    """Accept a bare item number or any Home Depot product URL.

    Returns a clean canonical URL: https://www.homedepot.com/p/<item_id>
    This means users can paste:
      - Just the item number:   301424967
      - A clean product URL:    https://www.homedepot.com/p/Name/301424967
      - An affiliate/tracking URL that contains the item number anywhere

    Raises InvalidProductUrlError if no valid item number can be found.
    """
    raw = raw.strip()
    if not raw:
        raise InvalidProductUrlError("Please enter an item number or URL.")

    # Bare numeric item number (Home Depot item #s are 6–9 digits)
    if re.match(r"^\d{6,9}$", raw):
        return f"https://www.homedepot.com/p/{raw}"

    # Try to parse as a URL
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")

    if parsed.netloc.lower() not in ALLOWED_HOSTS:
        raise InvalidProductUrlError(
            "Paste an item number (e.g. 301424967) or a homedepot.com product URL."
        )

    # Extract the item number from the URL path — it is the trailing numeric segment
    match = re.search(r"/(\d{6,9})(?:[/?#]|$)", parsed.path)
    if not match:
        raise InvalidProductUrlError(
            "Couldn't find a Home Depot item number in that URL.\n"
            "Try pasting just the item number instead (e.g. 301424967)."
        )

    return f"https://www.homedepot.com/p/{match.group(1)}"


def validate_product_url(raw: str) -> str:
    """Normalize and validate a watchlist entry. Returns the canonical URL."""
    return normalize_product_input(raw)


def load_watchlist(path: str) -> List[WatchlistEntry]:
    entries = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        url = validate_product_url(line)
        entries.append(WatchlistEntry(url=url, internet_number=_extract_internet_number(url)))
    return entries


def write_watchlist(path: str, urls: List[str]) -> None:
    lines = ["# One Home Depot item # or URL per line. Lines starting with # are ignored."]
    for url in urls:
        lines.append(validate_product_url(url))
    Path(path).write_text("\n".join(lines) + "\n")
