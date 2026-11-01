"""Circuit breaker and financial spend safety controls with reservation lock."""

import asyncio
import logging
import time
from typing import Optional, Tuple
from src.db.state_store import StateStore

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """Thread-safe and async-safe circuit breaker preventing unauthorized or excessive spend."""

    def __init__(
        self,
        state_store: StateStore,
        daily_spend_limit_inr: float = 10000.0,
        max_single_item_price_inr: float = 5000.0,
        post_order_kill_switch_count: int = 1,
        cooldown_seconds: float = 60.0,
    ):
        self.state_store = state_store
        self.daily_spend_limit_inr = daily_spend_limit_inr
        self.max_single_item_price_inr = max_single_item_price_inr
        self.post_order_kill_switch_count = post_order_kill_switch_count
        self.cooldown_seconds = cooldown_seconds

        self._lock = asyncio.Lock()
        self._is_paused: bool = False
        self._is_killed: bool = False
        self._kill_reason: str = ""
        self._last_order_timestamp: float = 0.0

        # In-flight reservation counters to prevent concurrent race condition breaches
        self._pending_reserved_spend: float = 0.0
        self._pending_reserved_orders: int = 0

    @property
    def is_paused(self) -> bool:
        return self._is_paused

    @property
    def is_killed(self) -> bool:
        return self._is_killed

    @property
    def kill_reason(self) -> str:
        return self._kill_reason

    def set_paused(self, paused: bool) -> None:
        """Pauses or resumes checkout processing."""
        self._is_paused = paused
        logger.info("Circuit breaker paused state set to: %s", paused)

    def trigger_kill_switch(self, reason: str) -> None:
        """Permanently halts automated checkouts until manual restart."""
        self._is_killed = True
        self._kill_reason = reason
        logger.critical("KILL SWITCH TRIGGERED: %s", reason)

    def reset_kill_switch(self) -> None:
        """Manual reset of kill switch."""
        self._is_killed = False
        self._kill_reason = ""
        logger.info("Kill switch has been reset.")

    async def can_proceed_to_checkout(
        self, item_price: float, reserve: bool = False
    ) -> Tuple[bool, str]:
        """Evaluates whether checkout is permitted under strict safety limits."""
        async with self._lock:
            if self._is_killed:
                return False, f"Kill switch active: {self._kill_reason}"

            if self._is_paused:
                return False, "Hunter is paused by operator."

            if item_price <= 0:
                return False, f"Invalid price: ₹{item_price}"

            if item_price > self.max_single_item_price_inr:
                return (
                    False,
                    f"Item price ₹{item_price:.2f} exceeds single-item cap of ₹{self.max_single_item_price_inr:.2f}",
                )

            # Check cooldown
            elapsed = time.time() - self._last_order_timestamp
            if self._last_order_timestamp > 0 and elapsed < self.cooldown_seconds:
                return (
                    False,
                    f"In cooldown period ({int(self.cooldown_seconds - elapsed)}s remaining)",
                )

            # Check daily spend limit including in-flight reservations
            today_spent = await self.state_store.get_today_spent_amount()
            total_projected_spend = today_spent + self._pending_reserved_spend + item_price
            if total_projected_spend > self.daily_spend_limit_inr:
                return (
                    False,
                    f"Daily budget exceeded: Spent ₹{today_spent:.2f} (Reserved ₹{self._pending_reserved_spend:.2f}) + Item ₹{item_price:.2f} > Cap ₹{self.daily_spend_limit_inr:.2f}",
                )

            today_orders = await self.state_store.get_today_order_count()
            total_projected_orders = today_orders + self._pending_reserved_orders + 1
            if (
                self.post_order_kill_switch_count > 0
                and total_projected_orders > self.post_order_kill_switch_count
            ):
                return (
                    False,
                    f"Post-order kill limit reached ({today_orders} placed, {self._pending_reserved_orders} reserved / max {self.post_order_kill_switch_count})",
                )

            if reserve:
                self._pending_reserved_spend += item_price
                self._pending_reserved_orders += 1

            return True, "Approved"

    async def release_reservation(self, item_price: float) -> None:
        """Releases an in-flight checkout reservation if checkout failed or aborted."""
        async with self._lock:
            self._pending_reserved_spend = max(0.0, self._pending_reserved_spend - item_price)
            self._pending_reserved_orders = max(0, self._pending_reserved_orders - 1)

    async def record_order_success(
        self,
        order_id: str,
        product_id: str,
        platform: str,
        title: str,
        price: float,
        tracking_url: str = "",
        had_reservation: bool = False,
    ) -> None:
        """Records successful checkout and engages cooldown / kill switch."""
        async with self._lock:
            if had_reservation:
                self._pending_reserved_spend = max(0.0, self._pending_reserved_spend - price)
                self._pending_reserved_orders = max(0, self._pending_reserved_orders - 1)

            self._last_order_timestamp = time.time()
            await self.state_store.record_order(
                order_id=order_id,
                product_id=product_id,
                platform=platform,
                title=title,
                price=price,
                status="SUCCESS",
                tracking_url=tracking_url,
            )
            await self.state_store.log_audit_event(
                "ORDER_PLACED",
                f"Order {order_id} for {title} (₹{price}) placed successfully on {platform}",
            )

            # Check if kill switch limit reached
            today_orders = await self.state_store.get_today_order_count()
            if (
                self.post_order_kill_switch_count > 0
                and today_orders >= self.post_order_kill_switch_count
            ):
                self.trigger_kill_switch(
                    f"Daily max order count ({self.post_order_kill_switch_count}) reached after placing order {order_id}."
                )
