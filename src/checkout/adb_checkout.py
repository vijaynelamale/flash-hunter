"""Android UIAutomator2 and Deep Link Intent Auto-Checkout Driver."""

import asyncio
import logging
import re
import time
import uuid
from typing import Optional
from src.checkout.base import AbstractCheckoutDriver, CheckoutResult
from src.config_loader import PaymentMethod
from src.scraper.product_fetcher import ParsedProduct, clean_price_to_float

logger = logging.getLogger(__name__)

# Package and Intent constants
AMAZON_PKG = "in.amazon.mShop.android.shopping"
FLIPKART_PKG = "com.flipkart.android"


class ADBCheckoutDriver(AbstractCheckoutDriver):
    """Executes high-speed Android deep-link and zero-OTP UI automation checkout."""

    def __init__(
        self,
        adb_serial: str = "127.0.0.1:5555",
        preferred_payment: PaymentMethod = PaymentMethod.AMAZON_PAY_BALANCE,
        dry_run: bool = False,
        device=None,
    ):
        self.adb_serial = adb_serial
        self.preferred_payment = preferred_payment
        self.dry_run = dry_run
        self._device = device  # Allows injecting mock device for host testing

    def _get_device(self):
        """Lazy connects to uiautomator2 device."""
        if self._device is None:
            import uiautomator2 as u2
            self._device = u2.connect(self.adb_serial)
        return self._device

    def extract_final_payable_price_from_hierarchy(self, xml_hierarchy: str) -> Optional[float]:
        """Parses final order summary payable amount from Android XML hierarchy."""
        if not xml_hierarchy:
            return None

        # Look for patterns like "Order Total: ₹19,999", "Total Payable ₹2,999", "Total: Rs. 1,499"
        patterns = [
            r"(?:Order\s*Total|Total\s*Payable|Amount\s*Payable|Total\s*Amount|Grand\s*Total)[^\d₹Rs]*[₹Rs.]*\s*([\d,]+(?:\.\d{1,2})?)",
            r"₹\s*([\d,]+(?:\.\d{1,2})?)",
        ]

        for pat in patterns:
            matches = re.finditer(pat, xml_hierarchy, re.IGNORECASE)
            for m in matches:
                val = clean_price_to_float(m.group(1))
                if val and val > 0:
                    return val
        return None

    async def execute_checkout(
        self,
        product: ParsedProduct,
        max_authorized_price: float,
    ) -> CheckoutResult:
        """Dispatches platform-specific checkout automation."""
        if self.dry_run:
            logger.info("[DRY_RUN ADB] Skipping real UI execution for %s", product.title)
            return CheckoutResult(
                success=True,
                order_id=f"DRYRUN-ADB-{uuid.uuid4().hex[:8].upper()}",
                message="DRY_RUN: Simulated ADB intent dispatched without clicking final place order.",
                final_price_paid=product.current_price_inr,
                platform=product.platform,
            )

        try:
            d = self._get_device()
            if product.platform == "amazon":
                return await self._checkout_amazon(d, product, max_authorized_price)
            elif product.platform == "flipkart":
                return await self._checkout_flipkart(d, product, max_authorized_price)
            else:
                return CheckoutResult(
                    success=False,
                    order_id="",
                    message=f"Unsupported checkout platform: {product.platform}",
                    final_price_paid=0.0,
                    platform=product.platform,
                )
        except Exception as e:
            logger.error("ADB Checkout execution crashed: %s", e)
            try:
                if self._device:
                    self._device.press("home")
            except Exception:
                pass
            return CheckoutResult(
                success=False,
                order_id="",
                message=f"ADB_EXECUTION_ERROR: {e}",
                final_price_paid=0.0,
                platform=product.platform,
            )

    async def _checkout_amazon(
        self, d, product: ParsedProduct, max_authorized_price: float
    ) -> CheckoutResult:
        """Automates Amazon India zero-OTP Buy Now flow."""
        logger.info("[ADB Amazon] Opening deep link for ASIN: %s", product.product_id)

        # 1. Launch Deep Link directly into Amazon App
        intent_url = f"https://www.amazon.in/dp/{product.product_id}"
        d.shell(f"am start -a android.intent.action.VIEW -d '{intent_url}' -p {AMAZON_PKG}")

        # Wait for Buy Now button to become clickable (timeout 3s)
        buy_now_btn = d(textContains="Buy Now")
        buy_now_btn.wait(timeout=3.0)
        if not buy_now_btn.exists:
            buy_now_btn = d(resourceIdMatches=r".*buyNow.*")
            buy_now_btn.wait(timeout=1.5)

        # Fallback: If deep link didn't load the product page directly, search ASIN via Search Bar
        if not buy_now_btn.exists:
            logger.info("[ADB Amazon] Deep link not landed on product page; trying high-speed ASIN search fallback...")
            search_box = d(resourceIdMatches=r".*(rs_search_src_text|chrome_search_hint_src|search_src_text).*")
            if not search_box.exists:
                search_box = d(textContains="Search")

            if search_box.exists:
                search_box.click()
                d.send_keys(product.product_id)
                d.press("enter")

                # Wait for search results and tap top product
                first_result = d(resourceIdMatches=r".*(item_title|product_title|item_image).*")
                first_result.wait(timeout=3.0)
                if first_result.exists:
                    first_result.click()
                    buy_now_btn = d(textContains="Buy Now")
                    buy_now_btn.wait(timeout=3.0)

        if not buy_now_btn.exists:
            d.press("home")
            return CheckoutResult(
                success=False,
                order_id="",
                message="AMAZON_BUY_NOW_NOT_FOUND: Item out of stock or Buy Now unavailable",
                final_price_paid=0.0,
                platform="amazon",
            )

        buy_now_btn.click()
        logger.info("[ADB Amazon] Clicked Buy Now. Navigating checkout summary...")

        # 2. Select Zero-OTP Payment Method (Amazon Pay Balance or COD, never UPI)
        # Check if payment selection screen is presented
        payment_screen = d(textContains="Select a payment method")
        payment_screen.wait(timeout=2.0)
        if payment_screen.exists or d(textContains="Payment Options").exists:
            if self.preferred_payment == PaymentMethod.AMAZON_PAY_BALANCE:
                pay_balance_opt = d(textContains="Amazon Pay Balance")
                if pay_balance_opt.exists:
                    pay_balance_opt.click()
                else:
                    cod_opt = d(textContains="Pay on Delivery")
                    if cod_opt.exists:
                        cod_opt.click()
            elif self.preferred_payment == PaymentMethod.COD:
                cod_opt = d(textContains="Pay on Delivery")
                if cod_opt.exists:
                    cod_opt.click()

            # Continue to Order Review
            continue_btn = d(textMatches=r"(?i)Continue|Proceed")
            if continue_btn.exists:
                continue_btn.click()

        # 3. MANDATORY FINAL CHECKOUT PRICE GUARD
        # Wait for final review screen
        place_order_btn = d(textMatches=r"(?i)Place Your Order|Place your order and pay")
        place_order_btn.wait(timeout=4.0)

        # Parse final payable price from XML hierarchy
        hierarchy_xml = d.dump_hierarchy()
        final_price = self.extract_final_payable_price_from_hierarchy(hierarchy_xml)

        if final_price and final_price > max_authorized_price:
            logger.critical(
                "PRICE_JUMP_ABORT: Final payable price ₹%.2f > Max Authorized ₹%.2f! Aborting order immediately.",
                final_price,
                max_authorized_price,
            )
            d.press("home")
            return CheckoutResult(
                success=False,
                order_id="",
                message=f"PRICE_JUMP_ABORT: Final payable total ₹{final_price:.2f} exceeded max budget ₹{max_authorized_price:.2f}",
                final_price_paid=final_price,
                platform="amazon",
            )

        # 4. Final Order Placement
        if place_order_btn.exists:
            place_order_btn.click()
            order_id = f"AMZ-ORD-{uuid.uuid4().hex[:10].upper()}"
            logger.info("[ADB Amazon] Order placed successfully! ID: %s", order_id)
            return CheckoutResult(
                success=True,
                order_id=order_id,
                message="AMAZON_ORDER_PLACED_SUCCESS",
                final_price_paid=final_price or product.current_price_inr,
                platform="amazon",
                tracking_url="https://www.amazon.in/gp/your-account/order-history",
            )

        d.press("home")
        return CheckoutResult(
            success=False,
            order_id="",
            message="AMAZON_PLACE_ORDER_BUTTON_NOT_FOUND",
            final_price_paid=0.0,
            platform="amazon",
        )

    async def _checkout_flipkart(
        self, d, product: ParsedProduct, max_authorized_price: float
    ) -> CheckoutResult:
        """Automates Flipkart zero-OTP Buy Now flow."""
        logger.info("[ADB Flipkart] Opening deep link for PID: %s", product.product_id)

        intent_url = f"https://www.flipkart.com/p/itm?pid={product.product_id}"
        d.shell(f"am start -a android.intent.action.VIEW -d '{intent_url}' -p {FLIPKART_PKG}")

        # Wait for BUY NOW button
        buy_now_btn = d(textMatches=r"(?i)BUY NOW|Order Now")
        buy_now_btn.wait(timeout=4.0)
        if not buy_now_btn.exists:
            d.press("home")
            return CheckoutResult(
                success=False,
                order_id="",
                message="FLIPKART_BUY_NOW_NOT_FOUND: Product unavailable",
                final_price_paid=0.0,
                platform="flipkart",
            )

        buy_now_btn.click()

        # Handle Skip & Continue (Add-ons / warranties popup)
        skip_btn = d(textMatches=r"(?i)Skip & Continue|Skip")
        skip_btn.wait(timeout=2.0)
        if skip_btn.exists:
            skip_btn.click()

        # Order Summary Continue button
        continue_summary_btn = d(textMatches=r"(?i)Continue")
        continue_summary_btn.wait(timeout=3.0)
        if continue_summary_btn.exists:
            continue_summary_btn.click()

        # Zero-OTP Payment Options (Gift Card / Wallet or COD, never UPI)
        if self.preferred_payment == PaymentMethod.FLIPKART_GIFT_CARD:
            gc_opt = d(textContains="Gift Card") or d(textContains="Wallet")
            if gc_opt.exists:
                gc_opt.click()
            else:
                cod_opt = d(textMatches=r"(?i)Cash on Delivery|Pay on Delivery")
                if cod_opt.exists:
                    cod_opt.click()
        elif self.preferred_payment == PaymentMethod.COD:
            cod_opt = d(textMatches=r"(?i)Cash on Delivery|Pay on Delivery")
            if cod_opt.exists:
                cod_opt.click()

        # MANDATORY FINAL CHECKOUT PRICE GUARD
        place_order_btn = d(textMatches=r"(?i)Place Order|Pay Now")
        place_order_btn.wait(timeout=4.0)

        hierarchy_xml = d.dump_hierarchy()
        final_price = self.extract_final_payable_price_from_hierarchy(hierarchy_xml)

        if final_price and final_price > max_authorized_price:
            logger.critical(
                "PRICE_JUMP_ABORT: Final Flipkart payable price ₹%.2f > Max Authorized ₹%.2f! Aborting.",
                final_price,
                max_authorized_price,
            )
            d.press("home")
            return CheckoutResult(
                success=False,
                order_id="",
                message=f"PRICE_JUMP_ABORT: Final payable total ₹{final_price:.2f} exceeded max budget ₹{max_authorized_price:.2f}",
                final_price_paid=final_price,
                platform="flipkart",
            )

        if place_order_btn.exists:
            place_order_btn.click()
            order_id = f"FKRT-ORD-{uuid.uuid4().hex[:10].upper()}"
            logger.info("[ADB Flipkart] Order placed successfully! ID: %s", order_id)
            return CheckoutResult(
                success=True,
                order_id=order_id,
                message="FLIPKART_ORDER_PLACED_SUCCESS",
                final_price_paid=final_price or product.current_price_inr,
                platform="flipkart",
                tracking_url="https://www.flipkart.com/account/orders",
            )

        d.press("home")
        return CheckoutResult(
            success=False,
            order_id="",
            message="FLIPKART_PLACE_ORDER_BUTTON_NOT_FOUND",
            final_price_paid=0.0,
            platform="flipkart",
        )
