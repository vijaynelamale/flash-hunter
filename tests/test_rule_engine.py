"""Unit tests for FastRuleEngine filtering, negative keywords, and crazy deal overrides."""

import pytest
from src.config_loader import CrazyDealConfig, TargetItem
from src.filter.rule_engine import FastRuleEngine
from src.scraper.product_fetcher import ParsedProduct


@pytest.fixture
def sample_targets():
    return [
        TargetItem(
            id="smartphone_deal",
            name="Flagship Smartphone",
            natural_language_spec="High-end smartphone with modern chipset",
            max_price_inr=25000.0,
            min_discount_percent=30.0,
            negative_keywords=["cover", "case", "tempered glass", "screen protector", "cable", "skin"],
        ),
        TargetItem(
            id="tws_earbuds",
            name="ANC TWS Earbuds",
            natural_language_spec="TWS with Active Noise Cancellation",
            max_price_inr=4000.0,
            min_discount_percent=50.0,
            negative_keywords=["case cover", "strap", "ear tips", "cable"],
        ),
    ]


@pytest.fixture
def crazy_deal_config():
    return CrazyDealConfig(
        enabled=True,
        min_discount_percent=90.0,
        max_price_inr=1000.0,
    )


@pytest.fixture
def rule_engine(sample_targets, crazy_deal_config):
    return FastRuleEngine(targets=sample_targets, crazy_deal=crazy_deal_config)


def test_valid_deal_passes(rule_engine):
    # Authentic smartphone deal: ₹19,999 (MRP 65,000 => ~69% off)
    product = ParsedProduct(
        platform="amazon",
        product_id="B0CQPLJPTM",
        title="OnePlus 12 (12GB RAM, 256GB Storage)",
        current_price_inr=19999.0,
        original_mrp_inr=64999.0,
        discount_percent=69.2,
        in_stock=True,
        seller="Appario Retail",
        rating=4.5,
        canonical_url="https://amazon.in/dp/B0CQPLJPTM",
        raw_text_snippet="OnePlus 12 12GB RAM",
    )

    result = rule_engine.evaluate(product)
    assert result.passed is True
    assert result.matched_target is not None
    assert result.matched_target.id == "smartphone_deal"
    assert result.is_crazy_deal is False


def test_accessory_rejected_by_negative_keywords(rule_engine):
    # A phone case costing ₹499 with 50% discount shouldn't match phone target
    accessory = ParsedProduct(
        platform="amazon",
        product_id="B00CASE123",
        title="Luxury Leather Case Cover for OnePlus 12 with Magnetic Stand",
        current_price_inr=499.0,
        original_mrp_inr=1999.0,
        discount_percent=75.0,
        in_stock=True,
        seller="CaseWorld",
        rating=4.1,
        canonical_url="https://amazon.in/dp/B00CASE123",
        raw_text_snippet="Case Cover",
    )

    result = rule_engine.evaluate(accessory)
    assert result.passed is False
    assert "Did not match" in result.reason or "negative" in result.reason.lower()


def test_over_budget_rejected(rule_engine):
    # Phone priced at ₹35,000 (above target max of 25,000)
    product = ParsedProduct(
        platform="amazon",
        product_id="B0OVERBUDGET",
        title="Samsung Galaxy S24 Ultra",
        current_price_inr=35000.0,
        original_mrp_inr=120000.0,
        discount_percent=70.0,
        in_stock=True,
        seller="Samsung Official",
        rating=4.7,
        canonical_url="https://amazon.in/dp/B0OVERBUDGET",
        raw_text_snippet="Galaxy S24 Ultra",
    )

    result = rule_engine.evaluate(product)
    assert result.passed is False


def test_low_discount_rejected(rule_engine):
    # Earbuds priced at ₹3,000 (under 4000 cap), but only 10% discount (min is 50%)
    product = ParsedProduct(
        platform="flipkart",
        product_id="ACCLOWDISC",
        title="Realme Buds Air 5 Pro ANC Earbuds",
        current_price_inr=3000.0,
        original_mrp_inr=3333.0,
        discount_percent=10.0,
        in_stock=True,
        seller="RetailNet",
        rating=4.3,
        canonical_url="https://flipkart.com/p/itm123",
        raw_text_snippet="Realme Buds Air 5 Pro",
    )

    result = rule_engine.evaluate(product)
    assert result.passed is False


def test_out_of_stock_rejected(rule_engine):
    product = ParsedProduct(
        platform="amazon",
        product_id="B0OOS12345",
        title="OnePlus 12 (12GB RAM, 256GB Storage)",
        current_price_inr=19999.0,
        original_mrp_inr=64999.0,
        discount_percent=69.2,
        in_stock=False,
        seller="Appario Retail",
        rating=4.5,
        canonical_url="https://amazon.in/dp/B0OOS12345",
        raw_text_snippet="OnePlus 12",
    )

    result = rule_engine.evaluate(product)
    assert result.passed is False
    assert "out of stock" in result.reason.lower()


def test_crazy_deal_override(rule_engine):
    # A high-end gadget (e.g., ₹8,000 item discounted to ₹499 -> 93.7% off)
    # Does not match smartphone or earbuds category, but satisfies crazy deal override!
    crazy_product = ParsedProduct(
        platform="amazon",
        product_id="B0CRAZYLOOT",
        title="Logitech MX Master 3S Wireless Performance Mouse",
        current_price_inr=499.0,
        original_mrp_inr=8999.0,
        discount_percent=94.4,
        in_stock=True,
        seller="Appario Retail",
        rating=4.8,
        canonical_url="https://amazon.in/dp/B0CRAZYLOOT",
        raw_text_snippet="MX Master 3S",
    )

    result = rule_engine.evaluate(crazy_product)
    assert result.passed is True
    assert result.is_crazy_deal is True
    assert "Crazy Deal Override" in result.reason
