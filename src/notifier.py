"""Discord webhook alert delivery."""
import json
import logging
import ssl
import urllib.error
import urllib.request
from urllib.parse import urlparse

log = logging.getLogger("hd_tracker")

ALLOWED_HOSTS = {"discord.com", "discordapp.com", "ptb.discord.com", "canary.discord.com"}
REQUEST_TIMEOUT_SEC = 10


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def is_valid_discord_webhook(url: str) -> bool:
    if not url:
        return False
    parsed = urlparse(url.strip())
    return (
        parsed.scheme == "https"
        and parsed.netloc.lower() in ALLOWED_HOSTS
        and parsed.path.startswith("/api/webhooks/")
    )


def send_discord_message(webhook_url: str, content: str) -> bool:
    """Post a message to a Discord webhook. Returns True on success."""
    if not is_valid_discord_webhook(webhook_url):
        return False

    payload = json.dumps({"content": content[:2000]}).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "DiscordBot (https://github.com/DOM-LAB-X/claude-HD-checker, 1.0)",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SEC, context=_ssl_context()) as resp:
            if 200 <= resp.status < 300:
                return True
            log.error("Discord webhook returned HTTP %d", resp.status)
            return False
    except urllib.error.HTTPError as e:
        log.error("Discord webhook HTTP error %d: %s", e.code, e.reason)
        return False
    except urllib.error.URLError as e:
        log.error("Discord webhook failed: %s", e)
        return False
