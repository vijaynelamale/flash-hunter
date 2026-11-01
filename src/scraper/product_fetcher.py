"""High-speed product scraper and parser for Amazon India and Flipkart.

Uses selectolax for sub-millisecond parsing with a BeautifulSoup4/lxml fallback.
"""

import logging
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)

# Check selectolax
SELECTOLAX_AVAILABLE = False
try:
    from selectolax.parser import HTMLParser as SelectolaxParser
    SELECTOLAX_AVAILABLE = True
except (ImportError, Exception):
    logger.warning("selectolax unavailable; falling back to BeautifulSoup4 + lxml")

from bs4 import BeautifulSoup


@dataclass
class ParsedProduct:
    platform: str  # "amazon" or "flipkart"
    product_id: str  # ASIN or FSN/PID
    title: str
    current_price_inr: float
    original_mrp_inr: Optional[float]
    discount_percent: float
    in_stock: bool
    seller: str
    rating: Optional[float]
    canonical_url: str
    raw_text_snippet: str


def clean_price_to_float(raw_price: Optional[str]) -> Optional[float]:
    """Converts price strings like '₹19,999.00', 'Rs. 2,999', '1,499' into float."""
    if not raw_price:
        return None
    # Strip currency abbreviations before extracting numbers
    cleaned_str = re.sub(r"(?i)\b(?:rs|inr)\b\.?", "", raw_price)
    cleaned_str = cleaned_str.replace(",", "")
    match = re.search(r"\d+(?:\.\d+)?", cleaned_str)
    if match:
        try:
            return float(match.group(0))
        except ValueError:
            return None
    return None


def extract_amazon_asin_from_url(url: str) -> Optional[str]:
    """Extracts 10-character Amazon ASIN from standard Amazon URLs."""
    match = re.search(r"(?:/dp/|/gp/product/|/d/|/gp/aw/d/)([A-Z0-9]{10})", url)
    if match:
        return match.group(1)
    # Check query param
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    if "asin" in qs:
        return qs["asin"][0]
    return None


def extract_flipkart_pid_from_url(url: str) -> Optional[str]:
    """Extracts Flipkart PID / FSN or itemId from URL."""
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    if "pid" in qs:
        return qs["pid"][0]
    match = re.search(r"/p/(itm[a-zA-Z0-9]+)", url)
    if match:
        return match.group(1)
    return None


class ProductFetcher:
    """Scrapes and parses product details from Amazon.in and Flipkart.com."""

    def __init__(self, http_client=None):
        self.http_client = http_client

    def detect_platform(self, url: str) -> str:
        """Determines e-commerce platform from URL domain."""
        domain = urlparse(url).netloc.lower()
        if "amazon" in domain or "amzn.to" in domain:
            return "amazon"
        elif "flipkart" in domain or "fkrt.it" in domain:
            return "flipkart"
        return "unknown"

    def parse_amazon_html(self, html: str, url: str) -> Optional[ParsedProduct]:
        """Parses Amazon India product page."""
        asin = extract_amazon_asin_from_url(url) or ""
        title = ""
        current_price = 0.0
        mrp = None
        in_stock = True
        seller = "Amazon Seller"
        rating = None

        if SELECTOLAX_AVAILABLE:
            tree = SelectolaxParser(html)
            # ASIN from DOM if not in URL
            if not asin:
                dp = tree.css_first("div#dp")
                if dp and dp.attributes.get("data-asin"):
                    asin = dp.attributes.get("data-asin")

            # Title
            title_node = tree.css_first("#productTitle, #title, span.product-title-word-break")
            if title_node:
                title = title_node.text(strip=True)

            # Current Price
            price_node = tree.css_first(".priceToPay span.a-offscreen, #corePriceDisplay_desktop_feature_div span.a-offscreen, #priceblock_ourprice, #priceblock_dealprice")
            if price_node:
                current_price = clean_price_to_float(price_node.text()) or 0.0

            # MRP
            mrp_node = tree.css_first(".a-text-price span.a-offscreen, #corePriceDisplay_desktop_feature_div span.a-text-price span.a-offscreen")
            if mrp_node:
                mrp = clean_price_to_float(mrp_node.text())

            # Stock check
            avail_node = tree.css_first("#availability")
            if avail_node:
                avail_text = avail_node.text(strip=True).lower()
                if "currently unavailable" in avail_text or "out of stock" in avail_text:
                    in_stock = False

            # Seller
            merchant_node = tree.css_first("#merchant-info, #tabular-buybox")
            if merchant_node:
                seller = merchant_node.text(strip=True)

            # Rating
            rating_node = tree.css_first("#acrPopover, span.a-icon-alt")
            if rating_node:
                r_match = re.search(r"([\d.]+)\s*out of", rating_node.text())
                if r_match:
                    try:
                        rating = float(r_match.group(1))
                    except ValueError:
                        pass
        else:
            soup = BeautifulSoup(html, "lxml")
            if not asin:
                dp = soup.find("div", id="dp")
                if dp and dp.get("data-asin"):
                    asin = dp["data-asin"]

            title_node = soup.select_one("#productTitle, #title, span.product-title-word-break")
            if title_node:
                title = title_node.get_text(strip=True)

            price_node = soup.select_one(".priceToPay span.a-offscreen, #priceblock_ourprice, #priceblock_dealprice")
            if price_node:
                current_price = clean_price_to_float(price_node.get_text()) or 0.0

            mrp_node = soup.select_one(".a-text-price span.a-offscreen")
            if mrp_node:
                mrp = clean_price_to_float(mrp_node.get_text())

            avail_node = soup.select_one("#availability")
            if avail_node:
                avail_text = avail_node.get_text(strip=True).lower()
                if "currently unavailable" in avail_text or "out of stock" in avail_text:
                    in_stock = False

            merchant_node = soup.select_one("#merchant-info")
            if merchant_node:
                seller = merchant_node.get_text(strip=True)

            rating_node = soup.select_one("#acrPopover, span.a-icon-alt")
            if rating_node:
                r_match = re.search(r"([\d.]+)\s*out of", rating_node.get_text())
                if r_match:
                    try:
                        rating = float(r_match.group(1))
                    except ValueError:
                        pass

        if not title and current_price == 0.0:
            return None

        # Calculate discount %
        discount_percent = 0.0
        if mrp and mrp > current_price and mrp > 0:
            discount_percent = round(((mrp - current_price) / mrp) * 100.0, 1)

        snippet = f"Amazon Product: {title} | Price: ₹{current_price} | MRP: ₹{mrp or 'N/A'} | Discount: {discount_percent}% | Seller: {seller} | Stock: {'In Stock' if in_stock else 'Out of Stock'}"

        return ParsedProduct(
            platform="amazon",
            product_id=asin or "UNKNOWN_ASIN",
            title=title,
            current_price_inr=current_price,
            original_mrp_inr=mrp,
            discount_percent=discount_percent,
            in_stock=in_stock,
            seller=seller,
            rating=rating,
            canonical_url=url,
            raw_text_snippet=snippet,
        )

    def parse_flipkart_html(self, html: str, url: str) -> Optional[ParsedProduct]:
        """Parses Flipkart product page."""
        pid = extract_flipkart_pid_from_url(url) or ""
        title = ""
        current_price = 0.0
        mrp = None
        in_stock = True
        seller = "Flipkart Seller"
        rating = None

        if SELECTOLAX_AVAILABLE:
            tree = SelectolaxParser(html)
            # Title
            title_node = tree.css_first("span.B_NuCI, h1.yhB1nd, span._35KyD6, h1._6EBuvT")
            if title_node:
                title = title_node.text(strip=True)

            # Price
            price_node = tree.css_first("div._30jeq3._16Jk6d, div._30jeq3, div._16Jk6d, div.Nx9bqj.CxhGGd")
            if price_node:
                current_price = clean_price_to_float(price_node.text()) or 0.0

            # MRP
            mrp_node = tree.css_first("div._3I9_wc._2p6lqe, div._3I9_wc, div.yRaY8j.A6cAOperation")
            if mrp_node:
                mrp = clean_price_to_float(mrp_node.text())

            # Stock / Buy button check
            buy_btn = tree.css_first("button._2KpZ6l._2U9uOA, button.QqFHMw")
            out_of_stock_node = tree.css_first("div._16FRp0, div._2JC05C")
            if out_of_stock_node and ("out of stock" in out_of_stock_node.text().lower() or "sold out" in out_of_stock_node.text().lower()):
                in_stock = False

            # Seller
            seller_node = tree.css_first("#sellerName, div._1RL2An")
            if seller_node:
                seller = seller_node.text(strip=True)

            # Rating
            rating_node = tree.css_first("div._3LWZlK, div.XQDdHH")
            if rating_node:
                r_match = re.search(r"([\d.]+)", rating_node.text())
                if r_match:
                    try:
                        rating = float(r_match.group(1))
                    except ValueError:
                        pass
        else:
            soup = BeautifulSoup(html, "lxml")
            title_node = soup.select_one("span.B_NuCI, h1.yhB1nd, span._35KyD6, h1._6EBuvT")
            if title_node:
                title = title_node.get_text(strip=True)

            price_node = soup.select_one("div._30jeq3._16Jk6d, div._30jeq3, div._16Jk6d, div.Nx9bqj.CxhGGd")
            if price_node:
                current_price = clean_price_to_float(price_node.get_text()) or 0.0

            mrp_node = soup.select_one("div._3I9_wc._2p6lqe, div._3I9_wc, div.yRaY8j.A6cAOperation")
            if mrp_node:
                mrp = clean_price_to_float(mrp_node.get_text())

            out_of_stock_node = soup.select_one("div._16FRp0, div._2JC05C")
            if out_of_stock_node and ("out of stock" in out_of_stock_node.get_text().lower() or "sold out" in out_of_stock_node.get_text().lower()):
                in_stock = False

            seller_node = soup.select_one("#sellerName, div._1RL2An")
            if seller_node:
                seller = seller_node.get_text(strip=True)

            rating_node = soup.select_one("div._3LWZlK, div.XQDdHH")
            if rating_node:
                r_match = re.search(r"([\d.]+)", rating_node.get_text())
                if r_match:
                    try:
                        rating = float(r_match.group(1))
                    except ValueError:
                        pass

        if not title and current_price == 0.0:
            return None

        # Calculate discount %
        discount_percent = 0.0
        if mrp and mrp > current_price and mrp > 0:
            discount_percent = round(((mrp - current_price) / mrp) * 100.0, 1)

        snippet = f"Flipkart Product: {title} | Price: ₹{current_price} | MRP: ₹{mrp or 'N/A'} | Discount: {discount_percent}% | Seller: {seller} | Stock: {'In Stock' if in_stock else 'Out of Stock'}"

        return ParsedProduct(
            platform="flipkart",
            product_id=pid or "UNKNOWN_PID",
            title=title,
            current_price_inr=current_price,
            original_mrp_inr=mrp,
            discount_percent=discount_percent,
            in_stock=in_stock,
            seller=seller,
            rating=rating,
            canonical_url=url,
            raw_text_snippet=snippet,
        )

    def parse_product_html(self, html: str, url: str) -> Optional[ParsedProduct]:
        """Auto-detects platform and parses product."""
        platform = self.detect_platform(url)
        if platform == "amazon":
            return self.parse_amazon_html(html, url)
        elif platform == "flipkart":
            return self.parse_flipkart_html(html, url)
        else:
            # Try Amazon first, then Flipkart
            res = self.parse_amazon_html(html, url)
            if res:
                return res
            return self.parse_flipkart_html(html, url)
