"""Discord webhook alert delivery.

Uses only the standard library (urllib) to avoid adding a dependency. The
webhook URL is a secret (anyone with it can post to your channel) - it is
never logged, and is validated to be an actual Discord webhook URL before use
so a misconfigured value can't send your data somewhere else.
"""
import json
import urllib.error
import urllib.request
from urllib.parse import urlparse

ALLOWED_HOSTS = {"discord.com", "discordapp.com", "ptb.discord.com", "canary.discord.com"}
REQUEST_TIMEOUT_SEC = 10


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
    """Post a message to a Discord webhook. Returns True on success.

    Never raises - logs a generic failure message (without the webhook URL)
    and returns False so a notification failure can't crash a check cycle.
    """
    if not is_valid_discord_webhook(webhook_url):
        print("Discord alert skipped: webhook URL is missing or not a valid Discord webhook URL.")
        return False

    payload = json.dumps({"content": content[:2000]}).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SEC) as resp:
            return 200 <= resp.status < 300
    except urllib.error.URLError as e:
        print(f"Discord alert failed: {e}")
        return False
