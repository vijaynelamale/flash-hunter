"""Asynchronous SQLite state store with WAL mode for Flash-Hunter."""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import aiosqlite

logger = logging.getLogger(__name__)


class StateStore:
    """Manages persistent deduplication, order ledger, and audit logs using aiosqlite."""

    def __init__(self, db_path: str = "data/flash_hunter.db"):
        self.db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        """Connects to SQLite and configures WAL mode and memory optimisations."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)

        # Performance pragmas for embedded low-RAM ARM64 target
        await self._db.execute("PRAGMA journal_mode = WAL;")
        await self._db.execute("PRAGMA synchronous = NORMAL;")
        await self._db.execute("PRAGMA temp_store = MEMORY;")
        await self._db.execute("PRAGMA cache_size = -2000;")  # 2MB max memory cache

        await self._create_tables()

    async def _create_tables(self) -> None:
        """Initializes database schema."""
        if not self._db:
            return

        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS seen_deals (
                product_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                title TEXT,
                price REAL,
                seen_timestamp TEXT NOT NULL,
                processed_status TEXT NOT NULL,
                PRIMARY KEY (product_id, platform)
            );
        """)

        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS order_ledger (
                order_id TEXT PRIMARY KEY,
                product_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                title TEXT,
                price_paid REAL NOT NULL,
                order_timestamp TEXT NOT NULL,
                status TEXT NOT NULL,
                tracking_url TEXT
            );
        """)

        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                details TEXT NOT NULL,
                timestamp TEXT NOT NULL
            );
        """)

        await self._db.commit()

    async def is_deal_seen(self, product_id: str, platform: str) -> bool:
        """Returns True if the deal has already been seen and processed."""
        if not self._db:
            return False
        async with self._db.execute(
            "SELECT 1 FROM seen_deals WHERE product_id = ? AND platform = ? LIMIT 1;",
            (product_id, platform),
        ) as cursor:
            row = await cursor.fetchone()
            return row is not None

    async def record_seen_deal(
        self, product_id: str, platform: str, title: str, price: float, status: str
    ) -> None:
        """Records or updates a deal in the deduplication ledger."""
        if not self._db:
            return
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            """
            INSERT INTO seen_deals (product_id, platform, title, price, seen_timestamp, processed_status)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(product_id, platform) DO UPDATE SET
                price = excluded.price,
                seen_timestamp = excluded.seen_timestamp,
                processed_status = excluded.processed_status;
            """,
            (product_id, platform, title, price, now, status),
        )
        await self._db.commit()

    async def record_order(
        self,
        order_id: str,
        product_id: str,
        platform: str,
        title: str,
        price: float,
        status: str,
        tracking_url: str = "",
    ) -> None:
        """Logs a completed checkout order to the ledger."""
        if not self._db:
            return
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            """
            INSERT OR REPLACE INTO order_ledger (order_id, product_id, platform, title, price_paid, order_timestamp, status, tracking_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (order_id, product_id, platform, title, price, now, status, tracking_url),
        )
        await self._db.commit()

    async def get_today_spent_amount(self) -> float:
        """Calculates total INR spent today (UTC)."""
        if not self._db:
            return 0.0
        today_prefix = datetime.now(timezone.utc).strftime("%Y-%m-%d") + "%"
        async with self._db.execute(
            "SELECT COALESCE(SUM(price_paid), 0.0) FROM order_ledger WHERE order_timestamp LIKE ? AND status = 'SUCCESS';",
            (today_prefix,),
        ) as cursor:
            row = await cursor.fetchone()
            return float(row[0]) if row else 0.0

    async def get_today_order_count(self) -> int:
        """Counts successful orders placed today (UTC)."""
        if not self._db:
            return 0
        today_prefix = datetime.now(timezone.utc).strftime("%Y-%m-%d") + "%"
        async with self._db.execute(
            "SELECT COUNT(*) FROM order_ledger WHERE order_timestamp LIKE ? AND status = 'SUCCESS';",
            (today_prefix,),
        ) as cursor:
            row = await cursor.fetchone()
            return int(row[0]) if row else 0

    async def log_audit_event(self, event_type: str, details: str) -> None:
        """Appends an event to the audit log."""
        if not self._db:
            return
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "INSERT INTO audit_log (event_type, details, timestamp) VALUES (?, ?, ?);",
            (event_type, details, now),
        )
        await self._db.commit()

    async def close(self) -> None:
        """Closes the database connection safely."""
        if self._db:
            await self._db.close()
            self._db = None
