"""Sub-millisecond Rule Engine for deal filtering and crazy deal overrides."""

import logging
from dataclasses import dataclass
from typing import List, Optional
from src.config_loader import CrazyDealConfig, TargetItem
from src.scraper.product_fetcher import ParsedProduct

logger = logging.getLogger(__name__)


@dataclass
class FilterResult:
    passed: bool
    reason: str
    matched_target: Optional[TargetItem]
    is_crazy_deal: bool


class FastRuleEngine:
    """High-speed price, discount, stock, and negative-keyword filter."""

    def __init__(
        self,
        targets: List[TargetItem],
        crazy_deal: Optional[CrazyDealConfig] = None,
    ):
        self.targets = targets
        self.crazy_deal = crazy_deal or CrazyDealConfig()

    def evaluate(self, product: ParsedProduct) -> FilterResult:
        """Evaluates a product against target criteria and crazy deal overrides in <1ms."""
        # 1. Stock check
        if not product.in_stock:
            return FilterResult(
                passed=False,
                reason="Product is out of stock / unavailable",
                matched_target=None,
                is_crazy_deal=False,
            )

        # 2. Basic price validity
        if product.current_price_inr <= 0:
            return FilterResult(
                passed=False,
                reason=f"Invalid product price: ₹{product.current_price_inr}",
                matched_target=None,
                is_crazy_deal=False,
            )

        title_lower = product.title.lower()

        # 3. Global Crazy Deal Override Check
        if (
            self.crazy_deal.enabled
            and product.discount_percent >= self.crazy_deal.min_discount_percent
            and product.current_price_inr <= self.crazy_deal.max_price_inr
        ):
            # Check basic trap keywords even for crazy deals
            global_traps = ["dummy", "box only", "sample paper", "empty box"]
            if not any(trap in title_lower for trap in global_traps):
                return FilterResult(
                    passed=True,
                    reason=f"Crazy Deal Override: {product.discount_percent:.1f}% off at ₹{product.current_price_inr:.2f} (<= ₹{self.crazy_deal.max_price_inr})",
                    matched_target=None,
                    is_crazy_deal=True,
                )

        # 4. Target Categories Evaluation
        for target in self.targets:
            # Check maximum price cap
            if product.current_price_inr > target.max_price_inr:
                continue

            # Check minimum discount percentage
            if product.discount_percent < target.min_discount_percent:
                continue

            # Check negative keywords (accessories / traps / parts)
            matched_negative = None
            for neg_kw in target.negative_keywords:
                neg_clean = neg_kw.strip().lower()
                if neg_clean and neg_clean in title_lower:
                    matched_negative = neg_kw
                    break

            if matched_negative:
                logger.debug(
                    "Product '%s' rejected for target '%s' due to negative keyword: '%s'",
                    product.title,
                    target.id,
                    matched_negative,
                )
                continue

            # Matched target!
            return FilterResult(
                passed=True,
                reason=f"Matched target '{target.name}' (Price: ₹{product.current_price_inr} <= ₹{target.max_price_inr}, Discount: {product.discount_percent}% >= {target.min_discount_percent}%)",
                matched_target=target,
                is_crazy_deal=False,
            )

        return FilterResult(
            passed=False,
            reason="Did not match any target budget/discount criteria or triggered negative keywords",
            matched_target=None,
            is_crazy_deal=False,
        )
