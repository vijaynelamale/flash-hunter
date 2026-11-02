"""Configuration and settings loader for Flash-Hunter."""

import os
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml
from pydantic import BaseModel, Field, field_validator
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
    max_price_inr: float = Field(default=10000.0, ge=0.0)
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
    GLOBAL_BUDGET_LIMIT: float = 10000.0
    DAILY_SPEND_LIMIT_INR: float = 10000.0
    MAX_SINGLE_ITEM_PRICE_INR: float = 10000.0
    POST_ORDER_KILL_SWITCH_COUNT: int = 1
    CHECKOUT_COOLDOWN_SECONDS: int = 60

    # Crazy Deal Global Override
    CRAZY_DEAL_ENABLED: bool = True
    CRAZY_DEAL_MIN_DISCOUNT_PERCENT: float = 90.0
    CRAZY_DEAL_MAX_PRICE_INR: float = 10000.0

    # Telegram Credentials & Notification Controls
    TELEGRAM_ENABLED: bool = True
    TELEGRAM_NOTIFICATION_THRESHOLD_INR: float = 10000.0
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    TELEGRAM_CHAT_ID: Optional[int] = None
    TELEGRAM_API_ID: Optional[int] = None
    TELEGRAM_API_HASH: Optional[str] = None
    TELEGRAM_CHANNELS: str = "@deals_india,@looter_deals,@flipkart_amazon_loots"

    # Cloud LLM Credentials
    GEMINI_API_KEY: Optional[str] = None
    GROQ_API_KEY: Optional[str] = None
    LLM_CONFIDENCE_THRESHOLD: float = 0.85

    @field_validator(
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "TELEGRAM_API_ID",
        "TELEGRAM_API_HASH",
        "GEMINI_API_KEY",
        "GROQ_API_KEY",
        "WEBHOOK_URL",
        "WEBHOOK_SECRET",
        mode="before",
    )
    @classmethod
    def empty_str_to_none(cls, v: Any) -> Any:
        if isinstance(v, str) and not v.strip():
            return None
        return v

    def get_telegram_channels_list(self) -> List[str]:
        return [c.strip() for c in self.TELEGRAM_CHANNELS.split(",") if c.strip()]


def load_yaml_settings(yaml_path: str = "config/settings.yaml") -> Dict[str, Any]:
    """Reads declarative settings.yaml and converts nested keys into Settings dict."""
    path = Path(yaml_path)
    if not path.is_file():
        return {}

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    data: Dict[str, Any] = {}
    bot = raw.get("bot", {})
    budget = raw.get("budget", {})
    crazy = raw.get("crazy_deal", {})
    notif = raw.get("notifications", {}).get("telegram", {})
    db = raw.get("database", {})
    intel = raw.get("intelligence", {})

    if "execution_mode" in bot:
        data["EXECUTION_MODE"] = bot["execution_mode"]
    if "dry_run" in bot:
        data["DRY_RUN"] = bot["dry_run"]
    if "log_level" in bot:
        data["LOG_LEVEL"] = bot["log_level"]
    if "adb_target" in bot:
        data["ADB_TARGET"] = bot["adb_target"]
    if "checkout_driver" in bot:
        data["CHECKOUT_DRIVER"] = bot["checkout_driver"]
    if "preferred_payment_method" in bot:
        data["PREFERRED_PAYMENT_METHOD"] = bot["preferred_payment_method"]

    if "global_budget_limit" in budget:
        data["GLOBAL_BUDGET_LIMIT"] = float(budget["global_budget_limit"])
        data["DAILY_SPEND_LIMIT_INR"] = float(budget["global_budget_limit"])
    if "daily_spend_limit_inr" in budget:
        data["DAILY_SPEND_LIMIT_INR"] = float(budget["daily_spend_limit_inr"])
    if "max_single_item_price_inr" in budget:
        data["MAX_SINGLE_ITEM_PRICE_INR"] = float(budget["max_single_item_price_inr"])
    if "post_order_kill_switch_count" in budget:
        data["POST_ORDER_KILL_SWITCH_COUNT"] = int(budget["post_order_kill_switch_count"])
    if "checkout_cooldown_seconds" in budget:
        data["CHECKOUT_COOLDOWN_SECONDS"] = int(budget["checkout_cooldown_seconds"])

    if "enabled" in crazy:
        data["CRAZY_DEAL_ENABLED"] = bool(crazy["enabled"])
    if "min_discount_percent" in crazy:
        data["CRAZY_DEAL_MIN_DISCOUNT_PERCENT"] = float(crazy["min_discount_percent"])
    if "max_price_inr" in crazy:
        data["CRAZY_DEAL_MAX_PRICE_INR"] = float(crazy["max_price_inr"])

    if "enabled" in notif:
        data["TELEGRAM_ENABLED"] = bool(notif["enabled"])
    if "threshold_price_inr" in notif:
        data["TELEGRAM_NOTIFICATION_THRESHOLD_INR"] = float(notif["threshold_price_inr"])
    if notif.get("bot_token"):
        data["TELEGRAM_BOT_TOKEN"] = str(notif["bot_token"])
    if notif.get("chat_id") is not None:
        data["TELEGRAM_CHAT_ID"] = int(notif["chat_id"])
    if notif.get("api_id") is not None:
        data["TELEGRAM_API_ID"] = int(notif["api_id"])
    if notif.get("api_hash"):
        data["TELEGRAM_API_HASH"] = str(notif["api_hash"])
    if notif.get("channels"):
        data["TELEGRAM_CHANNELS"] = str(notif["channels"])

    if "path" in db:
        data["DATABASE_PATH"] = str(db["path"])

    if intel.get("gemini_api_key"):
        data["GEMINI_API_KEY"] = str(intel["gemini_api_key"])
    if intel.get("groq_api_key"):
        data["GROQ_API_KEY"] = str(intel["groq_api_key"])
    if "llm_confidence_threshold" in intel:
        data["LLM_CONFIDENCE_THRESHOLD"] = float(intel["llm_confidence_threshold"])

    return data


def load_targets(config_path: str = "config/targets.yaml") -> tuple[CrazyDealConfig, List[TargetItem]]:
    """Loads and validates target categories from YAML config file."""
    path = Path(config_path)
    if not path.is_file():
        return CrazyDealConfig(), []

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    crazy_deal_data = data.get("global_rules", {}).get("crazy_deal_override", {})
    crazy_deal = CrazyDealConfig(**crazy_deal_data) if crazy_deal_data else CrazyDealConfig()

    raw_targets = data.get("targets", [])
    targets = [TargetItem(**t) for t in raw_targets]
    return crazy_deal, targets


_settings_instance: Optional[Settings] = None


def get_settings(yaml_path: str = "config/settings.yaml") -> Settings:
    """Singleton getter for application settings, loading from config/settings.yaml and .env."""
    global _settings_instance
    if _settings_instance is None:
        yaml_overrides = load_yaml_settings(yaml_path)
        _settings_instance = Settings(**yaml_overrides)
    return _settings_instance
