"""Telegram deal stream listener and URL unshortener."""

import asyncio
import logging
import re
from typing import AsyncGenerator, List, Optional, Set
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# URL Extraction Regex
URL_REGEX = re.compile(
    r"https?://(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}(?:/[^\s<>\"']*)?",
    re.IGNORECASE,
)

SUPPORTED_DOMAINS = {
    "amazon.in",
    "amzn.to",
    "amzn.in",
    "flipkart.com",
    "fkrt.it",
    "fkrt.co",
    "dl.flipkart.com",
    "bit.ly",
    "tinyurl.com",
    "cutt.ly",
    "rb.gy",
}


def extract_potential_deal_urls(text: str) -> List[str]:
    """Extracts candidate product and affiliate URLs from incoming stream text."""
    if not text:
        return []
    urls = URL_REGEX.findall(text)
    filtered = []
    for url in urls:
        # Strip trailing punctuation often attached in chat messages
        cleaned = re.sub(r"[.,;:!?)\]]+$", "", url)
        domain = urlparse(cleaned).netloc.lower()
        if any(supported in domain for supported in SUPPORTED_DOMAINS):
            filtered.append(cleaned)
    return filtered


class TelegramDealStream:
    """Listens to configured Telegram deal channels and pushes extracted links to a queue."""

    def __init__(
        self,
        api_id: Optional[int],
        api_hash: Optional[str],
        channels: List[str],
        deal_queue: asyncio.Queue,
        bot_token: Optional[str] = None,
        http_client=None,
    ):
        self.api_id = api_id
        self.api_hash = api_hash
        self.channels = channels
        self.deal_queue = deal_queue
        self.bot_token = bot_token
        self.http_client = http_client
        self.client = None
        self._is_running = False

    async def start(self) -> None:
        """Starts Telethon client and registers new message handlers."""
        if not self.api_id or not self.api_hash:
            logger.info("Telegram API credentials not configured; skipping Telegram stream ingestion.")
            return

        try:
            from telethon import TelegramClient, events
            self.client = TelegramClient("flash_hunter_session", self.api_id, self.api_hash)
            if self.bot_token:
                await self.client.start(bot_token=self.bot_token)
            else:
                await self.client.start()
            self._is_running = True
            logger.info("Connected to Telegram deal stream. Monitoring %d channels.", len(self.channels))

            @self.client.on(events.NewMessage(chats=self.channels))
            async def handler(event):
                text = event.message.message or ""
                urls = extract_potential_deal_urls(text)
                for raw_url in urls:
                    asyncio.create_task(self._process_and_enqueue(raw_url, text))

            await self.client.run_until_disconnected()
        except Exception as e:
            logger.error("Telegram stream error: %s", e)

    async def _process_and_enqueue(self, raw_url: str, message_text: str) -> None:
        """Unshortens URL and pushes canonical deal candidate to processing queue."""
        canonical_url = raw_url
        if self.http_client:
            canonical_url = await self.http_client.unshorten_url(raw_url)

        domain = urlparse(canonical_url).netloc.lower()
        if "amazon" in domain or "amzn" in domain or "flipkart" in domain or "fkrt" in domain:
            await self.deal_queue.put({
                "url": canonical_url,
                "raw_url": raw_url,
                "source": "telegram",
                "message": message_text,
            })
            logger.debug("Enqueued Telegram deal URL: %s", canonical_url)

    async def stop(self) -> None:
        """Stops Telethon client safely."""
        self._is_running = False
        if self.client:
            await self.client.disconnect()
            self.client = None
