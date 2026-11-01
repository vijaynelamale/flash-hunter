"""Flash-Hunter: Asynchronous Orchestrator and Deal Processing Pipeline."""

import asyncio
import logging
from pathlib import Path
import signal
import sys
from typing import Optional

# Ensure project root is in sys.path when running script directly
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Check uvloop for high performance async loop
try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
except (ImportError, Exception):
    pass

from src.checkout.adb_checkout import ADBCheckoutDriver
from src.checkout.base import AbstractCheckoutDriver
from src.checkout.lan_webhook import LanWebhookCheckoutDriver
from src.checkout.mock_checkout import MockCheckoutDriver
from src.config_loader import CheckoutDriverType, ExecutionMode, get_settings, load_targets
from src.db.state_store import StateStore
from src.filter.rule_engine import FastRuleEngine
from src.ingestion.category_poller import CategoryPoller
from src.ingestion.telegram_stream import TelegramDealStream
from src.intelligence.llm_validator import LLMDealValidator
from src.notifier.telegram_bot import TelegramControlNotifier
from src.safety.circuit_breaker import CircuitBreaker
from src.scraper.product_fetcher import ProductFetcher
from src.transport.http_client import ResilientHttpClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("flash_hunter.orchestrator")


class FlashHunterOrchestrator:
    """Central event coordinator and deal processing pipeline."""

    def __init__(self):
        self.settings = get_settings()
        self.crazy_deal_config, self.targets = load_targets()
        self.deal_queue = asyncio.Queue(maxsize=1000)
        self.running = False

        # Core subsystems
        self.http_client = ResilientHttpClient()
        self.product_fetcher = ProductFetcher(self.http_client)
        self.rule_engine = FastRuleEngine(self.targets, self.crazy_deal_config)
        self.state_store = StateStore(self.settings.DATABASE_PATH)
        self.circuit_breaker = CircuitBreaker(
            state_store=self.state_store,
            daily_spend_limit_inr=self.settings.DAILY_SPEND_LIMIT_INR,
            max_single_item_price_inr=self.settings.MAX_SINGLE_ITEM_PRICE_INR,
            post_order_kill_switch_count=self.settings.POST_ORDER_KILL_SWITCH_COUNT,
            cooldown_seconds=self.settings.CHECKOUT_COOLDOWN_SECONDS,
        )
        self.llm_validator = LLMDealValidator(
            gemini_api_key=self.settings.GEMINI_API_KEY,
            groq_api_key=self.settings.GROQ_API_KEY,
            confidence_threshold=self.settings.LLM_CONFIDENCE_THRESHOLD,
        )
        self.notifier = TelegramControlNotifier(
            bot_token=self.settings.TELEGRAM_BOT_TOKEN,
            chat_id=self.settings.TELEGRAM_CHAT_ID,
            circuit_breaker=self.circuit_breaker,
        )

        # Checkout driver initialization
        self.checkout_driver = self._init_checkout_driver()

        # Ingestion sources
        self.telegram_stream = TelegramDealStream(
            api_id=self.settings.TELEGRAM_API_ID,
            api_hash=self.settings.TELEGRAM_API_HASH,
            channels=self.settings.get_telegram_channels_list(),
            deal_queue=self.deal_queue,
            bot_token=self.settings.TELEGRAM_BOT_TOKEN,
            http_client=self.http_client,
        )
        self.category_poller = CategoryPoller(
            targets=self.targets,
            deal_queue=self.deal_queue,
            http_client=self.http_client,
        )

    def _init_checkout_driver(self) -> AbstractCheckoutDriver:
        """Instantiates appropriate checkout driver based on topology and driver settings."""
        if (
            self.settings.EXECUTION_MODE == ExecutionMode.MOCK
            or self.settings.CHECKOUT_DRIVER == CheckoutDriverType.MOCK
        ):
            logger.info("Initializing MOCK Checkout Driver.")
            return MockCheckoutDriver()

        elif self.settings.CHECKOUT_DRIVER == CheckoutDriverType.WEBHOOK:
            if not self.settings.WEBHOOK_URL:
                raise ValueError("WEBHOOK_URL is required when CHECKOUT_DRIVER=webhook")
            logger.info("Initializing LAN Webhook Checkout Driver targeting %s", self.settings.WEBHOOK_URL)
            return LanWebhookCheckoutDriver(
                webhook_url=self.settings.WEBHOOK_URL,
                secret=self.settings.WEBHOOK_SECRET,
            )

        else:
            # ADB Driver (for STANDALONE Termux or REMOTE_LAN mode)
            logger.info(
                "Initializing ADB Checkout Driver targeting %s (Dry Run: %s)",
                self.settings.ADB_TARGET,
                self.settings.DRY_RUN,
            )
            return ADBCheckoutDriver(
                adb_serial=self.settings.ADB_TARGET,
                preferred_payment=self.settings.PREFERRED_PAYMENT_METHOD,
                dry_run=self.settings.DRY_RUN,
            )

    async def start(self) -> None:
        """Starts all pipeline background tasks and worker pool."""
        logger.info("Starting Flash-Hunter System in %s mode...", self.settings.EXECUTION_MODE.value)
        await self.state_store.connect()
        self.running = True

        tasks = [
            asyncio.create_task(self._deal_processor_worker(worker_id=1)),
            asyncio.create_task(self._deal_processor_worker(worker_id=2)),
            asyncio.create_task(self.category_poller.start()),
            asyncio.create_task(self.telegram_stream.start()),
            asyncio.create_task(self.notifier.start_polling()),
        ]

        logger.info("Flash-Hunter Pipeline fully operational. Monitoring deals...")
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            logger.info("Pipeline cancellation requested.")

    async def _deal_processor_worker(self, worker_id: int) -> None:
        """Consumes candidate deals from queue and executes filtering, verification, and checkout."""
        logger.info("Deal Processor Worker #%d started.", worker_id)

        while self.running:
            item = await self.deal_queue.get()
            raw_url = item.get("raw_url", "")
            target_url = item.get("url", "")

            try:
                # 1. Fetch & Parse Listing
                resp = await self.http_client.get(target_url, timeout=10.0)
                if resp.status_code != 200 or not resp.text:
                    continue

                product = self.product_fetcher.parse_product_html(resp.text, resp.url)
                if not product or not product.product_id or product.product_id.startswith("UNKNOWN"):
                    continue

                # 2. Check Deduplication in SQLite State Store
                if await self.state_store.is_deal_seen(product.product_id, product.platform):
                    continue

                # 3. Sub-Millisecond Rule Engine Evaluation
                filter_res = self.rule_engine.evaluate(product)
                if not filter_res.passed:
                    await self.state_store.record_seen_deal(
                        product.product_id, product.platform, product.title, product.current_price_inr, "FILTER_REJECTED"
                    )
                    continue

                logger.info(
                    "🔥 [RULE ENGINE PASS] %s | %s | ₹%.2f (MRP: ₹%.2f, %d%% OFF)",
                    product.platform.upper(),
                    product.title,
                    product.current_price_inr,
                    product.original_mrp_inr or 0,
                    int(product.discount_percent),
                )

                # 4. Cloud LLM Verification
                verification = await self.llm_validator.verify_deal(
                    product,
                    matched_target=filter_res.matched_target,
                    is_crazy_deal=filter_res.is_crazy_deal,
                )

                if not verification.is_approved_for_checkout(self.settings.LLM_CONFIDENCE_THRESHOLD):
                    logger.info(
                        "❌ [LLM REJECTED] %s | Trap=%s | Conf=%.2f | Rationale: %s",
                        product.title,
                        verification.is_accessory_or_trap,
                        verification.confidence_score,
                        verification.rationale,
                    )
                    await self.state_store.record_seen_deal(
                        product.product_id, product.platform, product.title, product.current_price_inr, "LLM_REJECTED"
                    )
                    continue

                logger.info(
                    "✅ [LLM APPROVED] %s | Confidence: %.2f | Specs: %s",
                    product.title,
                    verification.confidence_score,
                    verification.extracted_key_specs,
                )

                # Send Deal Broadcast Alert
                await self.notifier.send_deal_alert(product, verification)

                # 5. Circuit Breaker Safety Check & Slot Reservation
                max_auth_price = (
                    filter_res.matched_target.max_price_inr
                    if filter_res.matched_target
                    else self.settings.CRAZY_DEAL_MAX_PRICE_INR
                )

                can_proceed, reason = await self.circuit_breaker.can_proceed_to_checkout(
                    product.current_price_inr, reserve=True
                )

                if not can_proceed:
                    logger.warning("🛑 [CIRCUIT BREAKER BLOCKED] %s: %s", product.title, reason)
                    await self.notifier.send_circuit_breaker_alert(reason)
                    await self.state_store.record_seen_deal(
                        product.product_id, product.platform, product.title, product.current_price_inr, f"CB_BLOCKED: {reason}"
                    )
                    continue

                # 6. Execute Automated Checkout
                logger.info("🚀 [TRIGGERING AUTO-CHECKOUT] %s via %s", product.title, self.settings.CHECKOUT_DRIVER)
                checkout_res = await self.checkout_driver.execute_checkout(product, max_auth_price)

                if checkout_res.success:
                    logger.info("🏆 [CHECKOUT COMPLETED] Order ID: %s", checkout_res.order_id)
                    await self.circuit_breaker.record_order_success(
                        order_id=checkout_res.order_id,
                        product_id=product.product_id,
                        platform=product.platform,
                        title=product.title,
                        price=checkout_res.final_price_paid,
                        tracking_url=checkout_res.tracking_url,
                        had_reservation=True,
                    )
                    await self.notifier.send_order_success(
                        order_id=checkout_res.order_id,
                        product=product,
                        final_price=checkout_res.final_price_paid,
                        tracking_url=checkout_res.tracking_url,
                    )
                    await self.state_store.record_seen_deal(
                        product.product_id, product.platform, product.title, product.current_price_inr, "ORDERED_SUCCESS"
                    )
                else:
                    # Release reservation on failure or price-jump abort
                    await self.circuit_breaker.release_reservation(product.current_price_inr)

                    if "PRICE_JUMP_ABORT" in checkout_res.message:
                        logger.critical("🚨 %s", checkout_res.message)
                        await self.notifier.send_price_jump_alert(
                            product=product,
                            final_price=checkout_res.final_price_paid,
                            max_authorized=max_auth_price,
                        )
                    else:
                        logger.error("❌ Checkout execution failed: %s", checkout_res.message)

                    await self.state_store.record_seen_deal(
                        product.product_id, product.platform, product.title, product.current_price_inr, f"CHECKOUT_FAILED: {checkout_res.message}"
                    )

            except Exception as e:
                logger.exception("Error processing deal URL %s: %s", target_url, e)
            finally:
                self.deal_queue.task_done()

    async def shutdown(self) -> None:
        """Gracefully shuts down all network connections and DB pools."""
        logger.info("Initiating graceful shutdown...")
        self.running = False
        self.category_poller.stop()
        self.notifier.stop_polling()
        await self.telegram_stream.stop()
        await self.http_client.close()
        await self.state_store.close()
        logger.info("Flash-Hunter shutdown completed successfully.")


async def main():
    orchestrator = FlashHunterOrchestrator()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(orchestrator.shutdown()))
        except (NotImplementedError, RuntimeError):
            pass

    try:
        await orchestrator.start()
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        await orchestrator.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
