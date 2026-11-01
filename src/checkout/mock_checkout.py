"""Mock checkout driver for Host Development and DRY_RUN simulation."""

import logging
import uuid
from src.checkout.base import AbstractCheckoutDriver, CheckoutResult
from src.scraper.product_fetcher import ParsedProduct

logger = logging.getLogger(__name__)


class MockCheckoutDriver(AbstractCheckoutDriver):
    """Simulated checkout driver for offline testing and DRY_RUN mode."""

    def __init__(self, simulate_failure: bool = False, failure_reason: str = "Simulated error"):
        self.simulate_failure = simulate_failure
        self.failure_reason = failure_reason
        self.executed_checkouts = []

    async def execute_checkout(
        self,
        product: ParsedProduct,
        max_authorized_price: float,
    ) -> CheckoutResult:
        """Simulates automated checkout."""
        logger.info(
            "[MOCK CHECKOUT] Triggered for %s (%s) at ₹%.2f (Max auth: ₹%.2f)",
            product.title,
            product.platform,
            product.current_price_inr,
            max_authorized_price,
        )

        if self.simulate_failure:
            return CheckoutResult(
                success=False,
                order_id="",
                message=f"MOCK_CHECKOUT_FAILED: {self.failure_reason}",
                final_price_paid=0.0,
                platform=product.platform,
            )

        # Price guard verification
        if product.current_price_inr > max_authorized_price:
            return CheckoutResult(
                success=False,
                order_id="",
                message=f"PRICE_JUMP_ABORT: Final price ₹{product.current_price_inr:.2f} > Max Auth ₹{max_authorized_price:.2f}",
                final_price_paid=product.current_price_inr,
                platform=product.platform,
            )

        order_id = f"MOCK-ORD-{uuid.uuid4().hex[:8].upper()}"
        self.executed_checkouts.append({
            "order_id": order_id,
            "product_id": product.product_id,
            "platform": product.platform,
            "price": product.current_price_inr,
        })

        return CheckoutResult(
            success=True,
            order_id=order_id,
            message="MOCK_CHECKOUT_SUCCESS: Simulated order placed successfully in DRY_RUN mode.",
            final_price_paid=product.current_price_inr,
            platform=product.platform,
            tracking_url=f"https://{product.platform}.in/orders/{order_id}",
        )
