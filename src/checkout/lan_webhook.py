"""Signed HTTP Webhook Checkout Offloading Driver."""

import hashlib
import hmac
import json
import logging
import time
from typing import Optional
import httpx
from src.checkout.base import AbstractCheckoutDriver, CheckoutResult
from src.scraper.product_fetcher import ParsedProduct

logger = logging.getLogger(__name__)


class LanWebhookCheckoutDriver(AbstractCheckoutDriver):
    """Offloads checkout execution to an external LAN runner via signed HMAC webhook."""

    def __init__(self, webhook_url: str, secret: Optional[str] = None, timeout: float = 15.0):
        self.webhook_url = webhook_url
        self.secret = (secret or "flash_hunter_default_secret").encode("utf-8")
        self.timeout = timeout

    def _generate_signature(self, payload_bytes: bytes) -> str:
        """Generates HMAC-SHA256 signature for the request body."""
        return hmac.new(self.secret, payload_bytes, hashlib.sha256).hexdigest()

    async def execute_checkout(
        self,
        product: ParsedProduct,
        max_authorized_price: float,
    ) -> CheckoutResult:
        """Transmits signed checkout intent to webhook endpoint."""
        payload = {
            "timestamp": int(time.time()),
            "platform": product.platform,
            "product_id": product.product_id,
            "title": product.title,
            "current_price_inr": product.current_price_inr,
            "max_authorized_price": max_authorized_price,
            "canonical_url": product.canonical_url,
        }

        payload_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
        signature = self._generate_signature(payload_bytes)

        headers = {
            "Content-Type": "application/json",
            "X-FlashHunter-Signature": signature,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(self.webhook_url, content=payload_bytes, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    return CheckoutResult(
                        success=data.get("success", False),
                        order_id=data.get("order_id", ""),
                        message=data.get("message", "Webhook checkout processed"),
                        final_price_paid=float(data.get("final_price_paid", product.current_price_inr)),
                        platform=product.platform,
                        tracking_url=data.get("tracking_url", ""),
                    )
                else:
                    return CheckoutResult(
                        success=False,
                        order_id="",
                        message=f"Webhook HTTP error {resp.status_code}: {resp.text}",
                        final_price_paid=0.0,
                        platform=product.platform,
                    )
        except Exception as e:
            logger.error("Failed to offload checkout via webhook: %s", e)
            return CheckoutResult(
                success=False,
                order_id="",
                message=f"Webhook connection failure: {e}",
                final_price_paid=0.0,
                platform=product.platform,
            )
