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


def validate_product_url(url: str) -> str:
    """Validate a watchlist URL: must be a homedepot.com /p/.../<itemId> link.

    Raises InvalidProductUrlError if invalid. Returns the normalized URL.
    Restricting to this host/path prevents the browser automation from being
    pointed at arbitrary (potentially malicious) sites via watchlist entries.
    """
    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc.lower() not in ALLOWED_HOSTS:
        raise InvalidProductUrlError("URL must be an https://www.homedepot.com link")
    if "/p/" not in parsed.path:
        raise InvalidProductUrlError("URL must be a product page (contains /p/)")
    _extract_internet_number(url)  # raises if no trailing Internet #
    return url


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
    lines = ["# One product URL per line. Lines starting with # are ignored."]
    for url in urls:
        lines.append(validate_product_url(url))
    Path(path).write_text("\n".join(lines) + "\n")
