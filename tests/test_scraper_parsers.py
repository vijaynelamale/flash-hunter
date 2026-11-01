"""Unit tests for product scraping and parsing pipeline."""

from pathlib import Path
import pytest
from src.scraper.product_fetcher import (
    ProductFetcher,
    clean_price_to_float,
    extract_amazon_asin_from_url,
    extract_flipkart_pid_from_url,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_clean_price_to_float():
    assert clean_price_to_float("₹19,999.00") == 19999.0
    assert clean_price_to_float("Rs. 2,499") == 2499.0
    assert clean_price_to_float("999") == 999.0
    assert clean_price_to_float("") is None
    assert clean_price_to_float(None) is None


def test_url_id_extractors():
    # Amazon
    amazon_url_1 = "https://www.amazon.in/dp/B0CQPLJPTM?ref_=cm_sw_r_cp_ud_dp"
    amazon_url_2 = "https://www.amazon.in/OnePlus-Silky-Black-12GB-Storage/dp/B0CQPLJPTM"
    assert extract_amazon_asin_from_url(amazon_url_1) == "B0CQPLJPTM"
    assert extract_amazon_asin_from_url(amazon_url_2) == "B0CQPLJPTM"

    # Flipkart
    fk_url_1 = "https://www.flipkart.com/oneplus-buds-pro-2/p/itm123456?pid=ACCGH789XYZ"
    fk_url_2 = "https://www.flipkart.com/p/itm123456789abcdef"
    assert extract_flipkart_pid_from_url(fk_url_1) == "ACCGH789XYZ"
    assert extract_flipkart_pid_from_url(fk_url_2) == "itm123456789abcdef"


def test_parse_amazon_product():
    html_file = FIXTURES_DIR / "amazon_product_sample.html"
    with open(html_file, "r", encoding="utf-8") as f:
        html = f.read()

    fetcher = ProductFetcher()
    product = fetcher.parse_amazon_html(html, "https://www.amazon.in/dp/B0CQPLJPTM")

    assert product is not None
    assert product.platform == "amazon"
    assert product.product_id == "B0CQPLJPTM"
    assert "OnePlus 12" in product.title
    assert product.current_price_inr == 19999.0
    assert product.original_mrp_inr == 64999.0
    assert product.discount_percent == 69.2 or round(product.discount_percent) == 69
    assert product.in_stock is True
    assert "Appario Retail" in product.seller
    assert product.rating == 4.5


def test_parse_flipkart_product():
    html_file = FIXTURES_DIR / "flipkart_product_sample.html"
    with open(html_file, "r", encoding="utf-8") as f:
        html = f.read()

    fetcher = ProductFetcher()
    product = fetcher.parse_flipkart_html(html, "https://www.flipkart.com/oneplus-buds/p/itm123?pid=ACCGH789XYZ")

    assert product is not None
    assert product.platform == "flipkart"
    assert product.product_id == "ACCGH789XYZ"
    assert "OnePlus Buds Pro 2" in product.title
    assert product.current_price_inr == 2999.0
    assert product.original_mrp_inr == 11999.0
    assert product.discount_percent == 75.0
    assert product.in_stock is True
    assert "SuperComNet" in product.seller
    assert product.rating == 4.4
