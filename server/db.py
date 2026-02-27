"""SQLite persistence layer for marketplace search history.

Stores search queries, results, and item details for analytics
and deduplication. Same singleton pattern as multi-ai MCP.
"""

import sqlite3
import uuid
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

# Default DB path — can be overridden via MARKETPLACE_DB_PATH env var
DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "searches.db"

_db_instance = None
_db_lock = threading.Lock()


def get_db(db_path: str | None = None) -> "SearchDB":
    """Get thread-safe singleton database instance."""
    global _db_instance
    if _db_instance is None:
        with _db_lock:
            if _db_instance is None:  # Double-checked locking
                import os
                path = db_path or os.environ.get("MARKETPLACE_DB_PATH", str(DEFAULT_DB_PATH))
                _db_instance = SearchDB(path)
    return _db_instance


class SearchDB:
    """SQLite database for storing marketplace search history."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.Lock()
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._create_tables()

    def _create_tables(self):
        """Create tables if they don't exist."""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS searches (
                id TEXT PRIMARY KEY,
                query TEXT NOT NULL,
                marketplace TEXT,
                category TEXT,
                brand TEXT,
                min_price REAL,
                max_price REAL,
                condition TEXT,
                region TEXT,
                total_results INTEGER DEFAULT 0,
                items_returned INTEGER DEFAULT 0,
                duration_ms INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS search_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                search_id TEXT NOT NULL,
                item_id TEXT NOT NULL,
                marketplace TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT,
                price REAL,
                currency TEXT,
                brand TEXT,
                size TEXT,
                condition TEXT,
                image_url TEXT,
                seller_name TEXT,
                seller_rating REAL,
                favorites INTEGER DEFAULT 0,
                views INTEGER DEFAULT 0,
                listed_at TEXT,
                location TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (search_id) REFERENCES searches(id)
            );

            CREATE TABLE IF NOT EXISTS saved_items (
                id TEXT PRIMARY KEY,
                item_id TEXT NOT NULL,
                marketplace TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT,
                price REAL,
                currency TEXT,
                brand TEXT,
                notes TEXT,
                saved_at TEXT NOT NULL,
                UNIQUE(item_id, marketplace)
            );

            CREATE INDEX IF NOT EXISTS idx_search_items_search
                ON search_items(search_id);
            CREATE INDEX IF NOT EXISTS idx_search_items_marketplace
                ON search_items(marketplace);
            CREATE INDEX IF NOT EXISTS idx_searches_query
                ON searches(query);
            CREATE INDEX IF NOT EXISTS idx_searches_created
                ON searches(created_at);
            CREATE INDEX IF NOT EXISTS idx_saved_marketplace
                ON saved_items(marketplace);
        """)
        self.conn.commit()

    def _now(self) -> str:
        """ISO8601 timestamp."""
        return datetime.now(timezone.utc).isoformat()

    def save_search(
        self,
        query: str,
        marketplace: str | None = None,
        category: str | None = None,
        brand: str | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
        condition: str | None = None,
        region: str | None = None,
        total_results: int = 0,
        items_returned: int = 0,
        duration_ms: int = 0,
    ) -> str:
        """Save a search query. Returns search ID."""
        search_id = str(uuid.uuid4())
        with self._lock:
            self.conn.execute(
                """INSERT INTO searches
                   (id, query, marketplace, category, brand, min_price, max_price,
                    condition, region, total_results, items_returned, duration_ms, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (search_id, query, marketplace, category, brand,
                 min_price, max_price, condition, region,
                 total_results, items_returned, duration_ms, self._now()),
            )
            self.conn.commit()
        return search_id

    def save_search_items(self, search_id: str, items: list[dict]):
        """Save items from a search result."""
        now = self._now()
        with self._lock:
            for item in items:
                self.conn.execute(
                    """INSERT INTO search_items
                       (search_id, item_id, marketplace, title, url, price, currency,
                        brand, size, condition, image_url, seller_name, seller_rating,
                        favorites, views, listed_at, location, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (search_id, item.get("item_id", ""), item.get("marketplace", ""),
                     item.get("title", ""), item.get("url", ""),
                     item.get("price", 0), item.get("currency", ""),
                     item.get("brand", ""), item.get("size", ""),
                     item.get("condition", ""), item.get("image_url", ""),
                     item.get("seller_name", ""), item.get("seller_rating", 0),
                     item.get("favorites", 0), item.get("views", 0),
                     item.get("listed_at", ""), item.get("location", ""), now),
                )
            self.conn.commit()

    def get_search_history(
        self,
        marketplace: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Get recent search history."""
        if marketplace:
            rows = self.conn.execute(
                """SELECT * FROM searches
                   WHERE marketplace = ? OR marketplace IS NULL
                   ORDER BY created_at DESC LIMIT ?""",
                (marketplace, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                """SELECT * FROM searches
                   ORDER BY created_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_search_results(self, search_id: str) -> list[dict]:
        """Get items from a specific search."""
        rows = self.conn.execute(
            "SELECT * FROM search_items WHERE search_id = ? ORDER BY price ASC",
            (search_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def save_item(
        self,
        item_id: str,
        marketplace: str,
        title: str,
        url: str = "",
        price: float = 0,
        currency: str = "",
        brand: str = "",
        notes: str = "",
    ) -> str:
        """Save/bookmark an item for later. Returns saved item ID."""
        saved_id = str(uuid.uuid4())
        with self._lock:
            self.conn.execute(
                """INSERT OR REPLACE INTO saved_items
                   (id, item_id, marketplace, title, url, price, currency, brand, notes, saved_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (saved_id, item_id, marketplace, title, url,
                 price, currency, brand, notes, self._now()),
            )
            self.conn.commit()
        return saved_id

    def get_saved_items(
        self,
        marketplace: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Get saved/bookmarked items."""
        if marketplace:
            rows = self.conn.execute(
                """SELECT * FROM saved_items
                   WHERE marketplace = ?
                   ORDER BY saved_at DESC LIMIT ?""",
                (marketplace, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                """SELECT * FROM saved_items
                   ORDER BY saved_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_stats(self, marketplace: str | None = None) -> dict:
        """Get search statistics."""
        if marketplace:
            search_row = self.conn.execute(
                """SELECT COUNT(*) as total_searches,
                   COALESCE(SUM(items_returned), 0) as total_items,
                   COALESCE(AVG(duration_ms), 0) as avg_duration
                   FROM searches WHERE marketplace = ?""",
                (marketplace,),
            ).fetchone()
        else:
            search_row = self.conn.execute(
                """SELECT COUNT(*) as total_searches,
                   COALESCE(SUM(items_returned), 0) as total_items,
                   COALESCE(AVG(duration_ms), 0) as avg_duration
                   FROM searches""",
            ).fetchone()

        # Per-marketplace breakdown
        by_marketplace = self.conn.execute(
            """SELECT marketplace, COUNT(*) as searches,
               COALESCE(SUM(items_returned), 0) as items
               FROM searches
               WHERE marketplace IS NOT NULL
               GROUP BY marketplace
               ORDER BY searches DESC""",
        ).fetchall()

        saved_count = self.conn.execute(
            "SELECT COUNT(*) as c FROM saved_items",
        ).fetchone()

        return {
            "summary": dict(search_row),
            "by_marketplace": [dict(r) for r in by_marketplace],
            "saved_items": saved_count["c"],
        }

    def cleanup_old_searches(self, days: int = 30) -> int:
        """Delete searches older than N days. Returns count deleted."""
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        # Get search IDs to delete
        old_ids = self.conn.execute(
            "SELECT id FROM searches WHERE created_at < ?",
            (cutoff,),
        ).fetchall()

        if not old_ids:
            return 0

        id_list = [r["id"] for r in old_ids]
        placeholders = ",".join("?" * len(id_list))

        # Delete items first (FK)
        with self._lock:
            self.conn.execute(
                f"DELETE FROM search_items WHERE search_id IN ({placeholders})",
                id_list,
            )
            cursor = self.conn.execute(
                f"DELETE FROM searches WHERE id IN ({placeholders})",
                id_list,
            )
            self.conn.commit()
        return cursor.rowcount
