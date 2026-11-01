"""Unit tests for ADB UIAutomator2 checkout driver with offline mocked fixtures."""

from unittest.mock import MagicMock
import pytest
from src.checkout.adb_checkout import ADBCheckoutDriver
from src.config_loader import PaymentMethod
from src.scraper.product_fetcher import ParsedProduct


@pytest.fixture
def sample_phone():
    return ParsedProduct(
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
        raw_text_snippet="OnePlus 12",
    )


@pytest.fixture
def sample_flipkart_item():
    return ParsedProduct(
        platform="flipkart",
        product_id="ACCGH789XYZ",
        title="OnePlus Buds Pro 2 Bluetooth Headset",
        current_price_inr=2999.0,
        original_mrp_inr=11999.0,
        discount_percent=75.0,
        in_stock=True,
        seller="SuperComNet",
        rating=4.4,
        canonical_url="https://flipkart.com/p/itm123?pid=ACCGH789XYZ",
        raw_text_snippet="OnePlus Buds Pro 2",
    )


def test_extract_final_payable_price_from_hierarchy():
    driver = ADBCheckoutDriver(dry_run=False)

    xml_1 = """<hierarchy><node text="Order Total: ₹19,999.00" resource-id="subtotals-marketplace-table" /></hierarchy>"""
    assert driver.extract_final_payable_price_from_hierarchy(xml_1) == 19999.0

    xml_2 = """<hierarchy><node text="Total Payable ₹2,999" class="android.widget.TextView" /></hierarchy>"""
    assert driver.extract_final_payable_price_from_hierarchy(xml_2) == 2999.0

    xml_empty = """<hierarchy><node text="Welcome to store" /></hierarchy>"""
    assert driver.extract_final_payable_price_from_hierarchy(xml_empty) is None


async def test_amazon_successful_zero_otp_checkout(sample_phone):
    # Mock uiautomator2 device
    mock_d = MagicMock()

    # Mock UI elements
    mock_element = MagicMock()
    mock_element.exists = True
    mock_element.wait.return_value = True
    mock_d.return_value = mock_element

    # XML hierarchy shows valid deal price ₹19,999
    mock_d.dump_hierarchy.return_value = """<hierarchy><node text="Order Total: ₹19,999" /></hierarchy>"""

    driver = ADBCheckoutDriver(
        adb_serial="127.0.0.1:5555",
        preferred_payment=PaymentMethod.AMAZON_PAY_BALANCE,
        dry_run=False,
        device=mock_d,
    )

    result = await driver.execute_checkout(sample_phone, max_authorized_price=25000.0)

    assert result.success is True
    assert "AMAZON_ORDER_PLACED_SUCCESS" in result.message
    assert result.final_price_paid == 19999.0
    assert mock_d.shell.called
    assert mock_element.click.called


async def test_mandatory_price_jump_abort_amazon(sample_phone):
    """Refinement 4 Verification: Flash sale expired mid-checkout, price jumped from 19,999 to 64,999."""
    mock_d = MagicMock()

    mock_element = MagicMock()
    mock_element.exists = True
    mock_element.wait.return_value = True
    mock_d.return_value = mock_element

    # XML hierarchy indicates price jumped to ₹64,999 on the final screen
    mock_d.dump_hierarchy.return_value = """<hierarchy><node text="Order Total: ₹64,999" /></hierarchy>"""

    driver = ADBCheckoutDriver(
        adb_serial="127.0.0.1:5555",
        preferred_payment=PaymentMethod.AMAZON_PAY_BALANCE,
        dry_run=False,
        device=mock_d,
    )

    # Max authorized price is ₹25,000
    result = await driver.execute_checkout(sample_phone, max_authorized_price=25000.0)

    assert result.success is False
    assert "PRICE_JUMP_ABORT" in result.message
    assert result.final_price_paid == 64999.0
    # Must press home to abort
    assert mock_d.press.called
    mock_d.press.assert_called_with("home")


async def test_mandatory_price_jump_abort_flipkart(sample_flipkart_item):
    """Refinement 4 Verification for Flipkart price jump abort."""
    mock_d = MagicMock()

    mock_element = MagicMock()
    mock_element.exists = True
    mock_element.wait.return_value = True
    mock_d.return_value = mock_element

    # Price jumped to ₹11,999 (above max authorized 4,000)
    mock_d.dump_hierarchy.return_value = """<hierarchy><node text="Total Payable ₹11,999" /></hierarchy>"""

    driver = ADBCheckoutDriver(
        adb_serial="127.0.0.1:5555",
        preferred_payment=PaymentMethod.FLIPKART_GIFT_CARD,
        dry_run=False,
        device=mock_d,
    )

    result = await driver.execute_checkout(sample_flipkart_item, max_authorized_price=4000.0)

    assert result.success is False
    assert "PRICE_JUMP_ABORT" in result.message
    assert result.final_price_paid == 11999.0
    assert mock_d.press.called
    mock_d.press.assert_called_with("home")


async def test_dry_run_mode(sample_phone):
    driver = ADBCheckoutDriver(dry_run=True)
    result = await driver.execute_checkout(sample_phone, max_authorized_price=25000.0)

    assert result.success is True
    assert "DRY_RUN" in result.message
