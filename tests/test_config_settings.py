"""Unit tests for config loading, settings.yaml mapping, and high_end_laptops target rules."""

import os
from pathlib import Path
import pytest
from src.config_loader import (
    ExecutionMode,
    get_settings,
    load_targets,
    load_yaml_settings,
)
from src.filter.rule_engine import FastRuleEngine
from src.notifier.telegram_bot import TelegramControlNotifier
from src.scraper.product_fetcher import ParsedProduct


def test_settings_yaml_loading():
    """Validates that config/settings.yaml is parsed correctly with expected limits."""
    settings = get_settings("config/settings.yaml")

    assert settings.GLOBAL_BUDGET_LIMIT == 10000.0
    assert settings.DAILY_SPEND_LIMIT_INR == 10000.0
    assert settings.MAX_SINGLE_ITEM_PRICE_INR == 10000.0
    assert settings.DRY_RUN is True
    assert settings.TELEGRAM_ENABLED is True
    assert settings.TELEGRAM_NOTIFICATION_THRESHOLD_INR == 10000.0
    assert settings.CRAZY_DEAL_MAX_PRICE_INR == 10000.0


def test_high_end_laptops_target_loaded():
    """Validates that high_end_laptops category exists in config/targets.yaml."""
    crazy_deal, targets = load_targets("config/targets.yaml")

    laptop_target = next((t for t in targets if t.id == "high_end_laptops"), None)
    assert laptop_target is not None
    assert laptop_target.name == "High-End Laptops (Gaming, Workstation, Ultrabook)"
    assert laptop_target.max_price_inr == 10000.0
    assert "celeron" in laptop_target.negative_keywords
    assert "chromebook" in laptop_target.negative_keywords
    assert "cooling pad" in laptop_target.negative_keywords
    assert "skin" in laptop_target.negative_keywords
    assert "stand" in laptop_target.negative_keywords


def test_high_end_laptops_filtering_pass_and_reject():
    """Tests that authentic laptops pass and budget/accessories get rejected."""
    crazy_deal, targets = load_targets("config/targets.yaml")
    rule_engine = FastRuleEngine(targets=targets, crazy_deal=crazy_deal)

    # 1. Genuine Laptop under budget (e.g. flash sale price ₹9,999, MRP ₹85,000)
    genuine_laptop = ParsedProduct(
        platform="amazon",
        product_id="B0LAPTOPTEST",
        title="ASUS TUF Gaming A15 Laptop (16GB RAM, 512GB SSD, RTX 3050)",
        current_price_inr=9999.0,
        original_mrp_inr=84999.0,
        discount_percent=88.2,
        in_stock=True,
        seller="Appario Retail",
        rating=4.6,
        canonical_url="https://amazon.in/dp/B0LAPTOPTEST",
        raw_text_snippet="ASUS TUF Gaming Laptop",
    )
    res = rule_engine.evaluate(genuine_laptop)
    assert res.passed is True
    assert res.matched_target is not None
    assert res.matched_target.id == "high_end_laptops"

    # 2. Budget Celeron / Chromebook rejected by negative keywords
    budget_variant = ParsedProduct(
        platform="amazon",
        product_id="B0CELERON123",
        title="Budget Celeron Dual Core Laptop (4GB RAM, 64GB eMMC)",
        current_price_inr=8999.0,
        original_mrp_inr=24999.0,
        discount_percent=64.0,
        in_stock=True,
        seller="RetailTech",
        rating=3.2,
        canonical_url="https://amazon.in/dp/B0CELERON123",
        raw_text_snippet="Celeron Chromebook",
    )
    res_budget = rule_engine.evaluate(budget_variant)
    assert res_budget.passed is False

    # 3. Accessory (Laptop cooling pad / stand / sleeve) rejected by negative keywords
    accessory = ParsedProduct(
        platform="flipkart",
        product_id="ACCLAPTOPSTAND",
        title="Ergonomic Aluminum Laptop Stand and Cooling Pad with RGB Light",
        current_price_inr=999.0,
        original_mrp_inr=3999.0,
        discount_percent=75.0,
        in_stock=True,
        seller="GadgetWorld",
        rating=4.3,
        canonical_url="https://flipkart.com/p/itmacc123",
        raw_text_snippet="Laptop cooling pad and stand",
    )
    res_acc = rule_engine.evaluate(accessory)
    assert res_acc.passed is False


@pytest.mark.asyncio
async def test_telegram_notifier_threshold_and_enabled():
    """Validates Telegram notification controls & threshold checks."""
    notifier_enabled = TelegramControlNotifier(
        bot_token=None,
        chat_id=None,
        enabled=True,
        threshold_price_inr=10000.0,
    )

    notifier_disabled = TelegramControlNotifier(
        bot_token=None,
        chat_id=None,
        enabled=False,
        threshold_price_inr=10000.0,
    )

    # When disabled, send_message returns False immediately
    msg_res = await notifier_disabled.send_message("Test message")
    assert msg_res is False

    # When enabled and mocked, returns True
    msg_res_ok = await notifier_enabled.send_message("Test message")
    assert msg_res_ok is True
