"""Unit tests for circuit breaker financial safety and race-condition prevention."""

import asyncio
import os
import pytest
from src.db.state_store import StateStore
from src.safety.circuit_breaker import CircuitBreaker


@pytest.fixture
async def temp_state_store(tmp_path):
    db_file = str(tmp_path / "test_hunter.db")
    store = StateStore(db_file)
    await store.connect()
    yield store
    await store.close()


@pytest.fixture
def circuit_breaker(temp_state_store):
    return CircuitBreaker(
        state_store=temp_state_store,
        daily_spend_limit_inr=5000.0,
        max_single_item_price_inr=3000.0,
        post_order_kill_switch_count=2,
        cooldown_seconds=1.0,
    )


async def test_single_item_price_cap(circuit_breaker):
    # Under limit
    ok, reason = await circuit_breaker.can_proceed_to_checkout(2500.0)
    assert ok is True
    assert reason == "Approved"

    # Exceeds single item limit
    ok, reason = await circuit_breaker.can_proceed_to_checkout(3500.0)
    assert ok is False
    assert "exceeds single-item cap" in reason


async def test_daily_spend_limit(circuit_breaker):
    # Place first order
    await circuit_breaker.record_order_success(
        order_id="ORD-001",
        product_id="B001",
        platform="amazon",
        title="Test Item 1",
        price=2800.0,
    )

    # Next item would push total to 2800 + 2500 = 5300 > 5000
    # Wait for cooldown of 1s
    await asyncio.sleep(1.1)

    ok, reason = await circuit_breaker.can_proceed_to_checkout(2500.0)
    assert ok is False
    assert "Daily budget exceeded" in reason

    # Item that fits in remaining budget (e.g. 2000 => 4800 <= 5000)
    ok, reason = await circuit_breaker.can_proceed_to_checkout(2000.0)
    assert ok is True


async def test_post_order_kill_switch(circuit_breaker):
    # Place order 1
    await circuit_breaker.record_order_success("ORD-1", "P1", "amazon", "Item 1", 1000.0)
    assert circuit_breaker.is_killed is False

    await asyncio.sleep(1.1)

    # Place order 2 (limit is 2)
    await circuit_breaker.record_order_success("ORD-2", "P2", "flipkart", "Item 2", 1000.0)
    assert circuit_breaker.is_killed is True
    assert "Daily max order count (2) reached" in circuit_breaker.kill_reason

    # Subsequent checkout attempts blocked
    await asyncio.sleep(1.1)
    ok, reason = await circuit_breaker.can_proceed_to_checkout(500.0)
    assert ok is False
    assert "Kill switch active" in reason


async def test_pause_and_resume(circuit_breaker):
    circuit_breaker.set_paused(True)
    ok, reason = await circuit_breaker.can_proceed_to_checkout(500.0)
    assert ok is False
    assert "paused" in reason

    circuit_breaker.set_paused(False)
    ok, reason = await circuit_breaker.can_proceed_to_checkout(500.0)
    assert ok is True


async def test_concurrent_checkout_race_protection(circuit_breaker):
    # Test racing 5 concurrent checkout requests with cooldown=0
    circuit_breaker.cooldown_seconds = 0.0

    async def attempt_order(idx: int):
        ok, _ = await circuit_breaker.can_proceed_to_checkout(2000.0, reserve=True)
        if ok:
            await circuit_breaker.record_order_success(
                f"ORD-RACE-{idx}", f"P{idx}", "amazon", f"Item {idx}", 2000.0, had_reservation=True
            )
            return True
        return False

    results = await asyncio.gather(*(attempt_order(i) for i in range(5)))
    success_count = sum(1 for r in results if r)

    # Max 2 orders should succeed before daily cap or kill switch engages (each is 2000, daily cap 5000, max count 2)
    assert success_count == 2
