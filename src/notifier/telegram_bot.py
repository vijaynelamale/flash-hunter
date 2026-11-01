"""2-Way Telegram Notification & Remote Management Bot for Flash-Hunter."""

import asyncio
import logging
from typing import Callable, Dict, Optional
import httpx
from src.intelligence.llm_validator import DealVerificationResult
from src.safety.circuit_breaker import CircuitBreaker
from src.scraper.product_fetcher import ParsedProduct

logger = logging.getLogger(__name__)


class TelegramControlNotifier:
    """Manages Telegram broadcast alerts and interactive 2-way remote control commands."""

    def __init__(
        self,
        bot_token: Optional[str],
        chat_id: Optional[int],
        circuit_breaker: Optional[CircuitBreaker] = None,
        manual_buy_callback: Optional[Callable] = None,
    ):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.circuit_breaker = circuit_breaker
        self.manual_buy_callback = manual_buy_callback
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}" if self.bot_token else ""
        self._is_polling = False
        self._last_update_id = 0

    async def send_message(self, text: str, reply_markup: Optional[Dict] = None) -> bool:
        """Transmits Markdown message to operator Telegram chat."""
        if not self.bot_token or not self.chat_id:
            logger.debug("[TELEGRAM NOTIFIER (MOCKED)]:\n%s", text)
            return True

        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": False,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        url = f"{self.base_url}/sendMessage"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=payload)
                return resp.status_code == 200
        except Exception as e:
            logger.error("Failed to transmit Telegram message: %s", e)
            return False

    async def send_deal_alert(
        self,
        product: ParsedProduct,
        verification: DealVerificationResult,
        status_note: str = "AUTO-CHECKOUT TRIGGERED",
    ) -> bool:
        """Sends rich product deal alert."""
        text = (
            f"⚡ *FLASH SALE DETECTED* ⚡\n\n"
            f"🛒 *Product:* [{product.title[:100]}]({product.canonical_url})\n"
            f"🏷️ *Platform:* `{product.platform.upper()}` | *ID:* `{product.product_id}`\n"
            f"💰 *Deal Price:* `₹{product.current_price_inr:,.2f}`\n"
            f"📉 *MRP / Discount:* `₹{product.original_mrp_inr or 0:,.2f}` (*{product.discount_percent}% OFF*)\n"
            f"🏪 *Seller:* {product.seller} | *Rating:* ⭐ {product.rating or 'N/A'}\n\n"
            f"🧠 *LLM Verification:* `{verification.model_name}`\n"
            f"🔍 *Confidence:* `{int(verification.confidence_score * 100)}%`\n"
            f"📝 *Specs:* {verification.extracted_key_specs}\n"
            f"🎯 *Rationale:* {verification.rationale}\n\n"
            f"🚦 *Status:* `{status_note}`"
        )
        return await self.send_message(text)

    async def send_order_success(
        self,
        order_id: str,
        product: ParsedProduct,
        final_price: float,
        tracking_url: str = "",
    ) -> bool:
        """Sends order success confirmation."""
        text = (
            f"🎉 *ORDER PLACED SUCCESSFULLY* 🎉\n\n"
            f"📦 *Order ID:* `{order_id}`\n"
            f"🛍️ *Product:* {product.title[:80]}\n"
            f"💳 *Final Paid Amount:* `₹{final_price:,.2f}`\n"
            f"🛒 *Platform:* `{product.platform.upper()}`\n"
            f"🔗 *Tracking:* [View Order Details]({tracking_url or product.canonical_url})\n\n"
            f"🛡️ _Circuit breaker safety lock engaged._"
        )
        return await self.send_message(text)

    async def send_price_jump_abort(
        self,
        product: ParsedProduct,
        final_price: float,
        max_authorized: float,
    ) -> bool:
        """Sends critical price-jump abort warning."""
        text = (
            f"🚨 *PRICE JUMP DETECTED — CHECKOUT ABORTED* 🚨\n\n"
            f"⚠️ Flash sale expired or price surged at final checkout screen!\n"
            f"🛒 *Product:* {product.title[:80]}\n"
            f"❌ *Final Payable Total:* `₹{final_price:,.2f}`\n"
            f"🔒 *Max Authorized Budget:* `₹{max_authorized:,.2f}`\n\n"
            f"🛑 *Action:* Order cancelled & returned to home screen to protect funds."
        )
        return await self.send_message(text)

    async def send_circuit_breaker_alert(self, reason: str) -> bool:
        """Sends emergency circuit breaker alert."""
        text = f"🛑 *CIRCUIT BREAKER ALERT* 🛑\n\n⚠️ {reason}\nAutomated checkouts halted."
        return await self.send_message(text)

    async def handle_command(self, cmd_text: str) -> str:
        """Processes incoming 2-way control commands."""
        cmd = cmd_text.strip().lower()

        if cmd == "/status":
            if not self.circuit_breaker:
                return "Circuit breaker not linked."
            today_spent = await self.circuit_breaker.state_store.get_today_spent_amount()
            today_orders = await self.circuit_breaker.state_store.get_today_order_count()
            status_str = "KILLED" if self.circuit_breaker.is_killed else ("PAUSED" if self.circuit_breaker.is_paused else "ACTIVE")
            return (
                f"📊 *Flash-Hunter System Status*\n\n"
                f"• Operational State: `{status_str}`\n"
                f"• Spent Today: `₹{today_spent:,.2f}` / `₹{self.circuit_breaker.daily_spend_limit_inr:,.2f}`\n"
                f"• Orders Today: `{today_orders}` / `{self.circuit_breaker.post_order_kill_switch_count}`\n"
                f"• Single Item Cap: `₹{self.circuit_breaker.max_single_item_price_inr:,.2f}`"
            )

        elif cmd == "/pause":
            if self.circuit_breaker:
                self.circuit_breaker.set_paused(True)
                return "⏸️ Flash-Hunter auto-checkouts *PAUSED*."
            return "Circuit breaker not linked."

        elif cmd == "/resume":
            if self.circuit_breaker:
                self.circuit_breaker.set_paused(False)
                return "▶️ Flash-Hunter auto-checkouts *RESUMED*."
            return "Circuit breaker not linked."

        elif cmd == "/kill":
            if self.circuit_breaker:
                self.circuit_breaker.trigger_kill_switch("Manual emergency kill triggered via Telegram.")
                return "🛑 *EMERGENCY KILL SWITCH ENGAGED.*"
            return "Circuit breaker not linked."

        elif cmd == "/reset_kill":
            if self.circuit_breaker:
                self.circuit_breaker.reset_kill_switch()
                return "✅ Kill switch *RESET*. Auto-hunter is back online."
            return "Circuit breaker not linked."

        elif cmd == "/help":
            return (
                "🤖 *Flash-Hunter Control Commands*\n\n"
                "/status — Check budget, orders, and running state\n"
                "/pause — Pause auto-checkout\n"
                "/resume — Resume auto-checkout\n"
                "/kill — Emergency halt all checkouts\n"
                "/reset_kill — Reset emergency kill switch"
            )

        return "Unknown command. Send /help for available commands."

    async def start_polling(self) -> None:
        """Lightweight command polling loop for 2-way interactive control."""
        if not self.bot_token:
            return

        self._is_polling = True
        logger.info("Starting Telegram 2-way bot command listener...")

        while self._is_polling:
            try:
                url = f"{self.base_url}/getUpdates"
                params = {"offset": self._last_update_id + 1, "timeout": 20}
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.get(url, params=params)
                    if resp.status_code == 200:
                        data = resp.json()
                        for update in data.get("result", []):
                            self._last_update_id = update["update_id"]
                            msg = update.get("message", {})
                            text = msg.get("text", "")
                            chat = msg.get("chat", {})
                            if text and (not self.chat_id or chat.get("id") == self.chat_id):
                                response_text = await self.handle_command(text)
                                await self.send_message(response_text)
            except Exception as e:
                logger.debug("Telegram polling tick error: %s", e)
            await asyncio.sleep(2)

    def stop_polling(self) -> None:
        """Stops Telegram polling."""
        self._is_polling = False
