"""Jittered asynchronous category and deals page poller."""

import asyncio
import logging
import random
import re
from typing import List, Optional
from urllib.parse import urljoin
from src.config_loader import TargetItem
from src.transport.http_client import ResilientHttpClient

logger = logging.getLogger(__name__)

AMAZON_PRODUCT_HREF_REGEX = re.compile(r"/(?:dp|gp/product)/([A-Z0-9]{10})")
FLIPKART_PRODUCT_HREF_REGEX = re.compile(r"/p/(itm[a-zA-Z0-9]+)")


class CategoryPoller:
    """Asynchronously polls target category listing pages with anti-ban jitter."""

    def __init__(
        self,
        targets: List[TargetItem],
        deal_queue: asyncio.Queue,
        http_client: ResilientHttpClient,
        min_interval_seconds: float = 20.0,
        max_interval_seconds: float = 50.0,
    ):
        self.targets = targets
        self.deal_queue = deal_queue
        self.http_client = http_client
        self.min_interval_seconds = min_interval_seconds
        self.max_interval_seconds = max_interval_seconds
        self._is_running = False

    def get_all_poll_urls(self) -> List[tuple[str, str]]:
        """Collects (platform, url) pairs from all loaded targets."""
        urls = []
        for target in self.targets:
            for platform, url_list in target.category_poll_urls.items():
                for url in url_list:
                    urls.append((platform, url))
        return urls

    async def start(self) -> None:
        """Main polling loop running continuously in background."""
        self._is_running = True
        poll_targets = self.get_all_poll_urls()
        if not poll_targets:
            logger.info("No category poll URLs configured; category poller idle.")
            return

        logger.info("Category poller started with %d target category URLs.", len(poll_targets))

        while self._is_running:
            random.shuffle(poll_targets)
            for platform, url in poll_targets:
                if not self._is_running:
                    break
                try:
                    await self._poll_url(platform, url)
                except Exception as e:
                    logger.debug("Category poll failed for %s: %s", url, e)

                # Anti-ban jitter sleep between target URLs
                jitter = random.uniform(self.min_interval_seconds, self.max_interval_seconds)
                await asyncio.sleep(jitter)

    async def _poll_url(self, platform: str, url: str) -> None:
        """Fetches category HTML and extracts individual product links."""
        resp = await self.http_client.get(url, timeout=10.0)
        if resp.status_code != 200 or not resp.text:
            return

        product_links = self.extract_product_urls_from_html(platform, resp.text, url)
        for prod_url in product_links:
            await self.deal_queue.put({
                "url": prod_url,
                "raw_url": prod_url,
                "source": "category_poller",
                "message": f"Polled from {url}",
            })

    def extract_product_urls_from_html(
        self, platform: str, html: str, base_url: str
    ) -> List[str]:
        """Extracts unique canonical product links from category or search listing HTML."""
        extracted: set[str] = set()

        if platform == "amazon":
            matches = AMAZON_PRODUCT_HREF_REGEX.findall(html)
            for asin in set(matches):
                canonical = f"https://www.amazon.in/dp/{asin}"
                extracted.add(canonical)
        elif platform == "flipkart":
            # Match full product path including slug: /slug-name/p/itm...
            full_matches = re.findall(r'href=["\'](/[^"\'\s]+/p/itm[a-zA-Z0-9]+[^"\'\s]*)["\']', html)
            for path in set(full_matches):
                # Clean tracking params except pid
                clean_path = path.split("&lid=")[0].split("&marketplace=")[0]
                full_url = urljoin("https://www.flipkart.com", clean_path)
                extracted.add(full_url)

            # Fallback if slug wasn't in href
            if not full_matches:
                matches = FLIPKART_PRODUCT_HREF_REGEX.findall(html)
                for itm_id in set(matches):
                    canonical = f"https://www.flipkart.com/product/p/{itm_id}"
                    extracted.add(canonical)

        return list(extracted)

    def stop(self) -> None:
        """Stops the poller loop."""
        self._is_running = False
