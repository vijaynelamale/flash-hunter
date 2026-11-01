"""Abstract base interface for Flash-Hunter checkout drivers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
from src.scraper.product_fetcher import ParsedProduct


@dataclass
class CheckoutResult:
    success: bool
    order_id: str
    message: str
    final_price_paid: float
    platform: str
    tracking_url: str = ""


class AbstractCheckoutDriver(ABC):
    """Base class for all checkout execution drivers."""

    @abstractmethod
    async def execute_checkout(
        self,
        product: ParsedProduct,
        max_authorized_price: float,
    ) -> CheckoutResult:
        """Executes automated checkout for the given product."""
        raise NotImplementedError
