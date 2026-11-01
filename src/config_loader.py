"""Configuration and settings loader for Flash-Hunter."""

import os
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ExecutionMode(str, Enum):
    STANDALONE = "STANDALONE"
    REMOTE_LAN = "REMOTE_LAN"
    MOCK = "MOCK"


class PaymentMethod(str, Enum):
    AMAZON_PAY_BALANCE = "AMAZON_PAY_BALANCE"
    FLIPKART_GIFT_CARD = "FLIPKART_GIFT_CARD"
    COD = "COD"


class CheckoutDriverType(str, Enum):
    ADB = "adb"
    WEBHOOK = "webhook"
    MOCK = "mock"


class CrazyDealConfig(BaseModel):
    enabled: bool = True
    min_discount_percent: float = Field(default=90.0, ge=0.0, le=100.0)
    max_price_inr: float = Field(default=1000.0, ge=0.0)
    description: str = "Instant trigger on any high-discount loot across all monitored streams"


class TargetItem(BaseModel):
    id: str
    name: str
    natural_language_spec: str
    max_price_inr: float = Field(gt=0.0)
    min_discount_percent: float = Field(default=0.0, ge=0.0, le=100.0)
    negative_keywords: List[str] = Field(default_factory=list)
    category_poll_urls: Dict[str, List[str]] = Field(default_factory=dict)


class TargetsConfig(BaseModel):
    global_rules: Dict[str, Any] = Field(default_factory=dict)
    targets: List[TargetItem] = Field(default_factory=list)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Topology & Runtime
    EXECUTION_MODE: ExecutionMode = ExecutionMode.STANDALONE
    DRY_RUN: bool = True
    LOG_LEVEL: str = "INFO"

    # Android ADB Automation
    ADB_TARGET: str = "127.0.0.1:5555"
    CHECKOUT_DRIVER: CheckoutDriverType = CheckoutDriverType.ADB
    PREFERRED_PAYMENT_METHOD: PaymentMethod = PaymentMethod.AMAZON_PAY_BALANCE

    # LAN Webhook Offload
    WEBHOOK_URL: Optional[str] = None
    WEBHOOK_SECRET: Optional[str] = None

    # State Store & Database
    DATABASE_PATH: str = "data/flash_hunter.db"

    # Circuit Breaker & Safety Caps
    DAILY_SPEND_LIMIT_INR: float = 10000.0
    MAX_SINGLE_ITEM_PRICE_INR: float = 5000.0
    POST_ORDER_KILL_SWITCH_COUNT: int = 1
    CHECKOUT_COOLDOWN_SECONDS: int = 60

    # Crazy Deal Global Override
    CRAZY_DEAL_ENABLED: bool = True
    CRAZY_DEAL_MIN_DISCOUNT_PERCENT: float = 90.0
    CRAZY_DEAL_MAX_PRICE_INR: float = 1000.0

    # Telegram Credentials & Config
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    TELEGRAM_CHAT_ID: Optional[int] = None
    TELEGRAM_API_ID: Optional[int] = None
    TELEGRAM_API_HASH: Optional[str] = None
    TELEGRAM_CHANNELS: str = "@deals_india,@looter_deals"

    # Cloud LLM Credentials
    GEMINI_API_KEY: Optional[str] = None
    GROQ_API_KEY: Optional[str] = None
    LLM_CONFIDENCE_THRESHOLD: float = 0.85

    def get_telegram_channels_list(self) -> List[str]:
        return [c.strip() for c in self.TELEGRAM_CHANNELS.split(",") if c.strip()]


def load_targets(config_path: str = "config/targets.yaml") -> tuple[CrazyDealConfig, List[TargetItem]]:
    """Loads and validates target categories from YAML config file."""
    path = Path(config_path)
    if not path.is_file():
        # Fallback to empty if not found
        return CrazyDealConfig(), []

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    crazy_deal_data = data.get("global_rules", {}).get("crazy_deal_override", {})
    crazy_deal = CrazyDealConfig(**crazy_deal_data) if crazy_deal_data else CrazyDealConfig()

    raw_targets = data.get("targets", [])
    targets = [TargetItem(**t) for t in raw_targets]
    return crazy_deal, targets


_settings_instance: Optional[Settings] = None


def get_settings() -> Settings:
    """Singleton getter for application settings."""
    global _settings_instance
    if _settings_instance is None:
        _settings_instance = Settings()
    return _settings_instance
