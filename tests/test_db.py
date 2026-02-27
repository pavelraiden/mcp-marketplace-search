"""Tests for server.db — SQLite persistence layer."""

import pytest
import threading
from datetime import datetime, timezone, timedelta


class TestSearchDB:
    """Test SearchDB CRUD operations."""

    def test_save_and_retrieve_search(self, db):
        search_id = db.save_search(
            query="nike air max",
            marketplace="vinted",
            brand="Nike",
            min_price=20.0,
            max_price=100.0,
            total_results=42,
            items_returned=20,
            duration_ms=350,
        )
        assert search_id is not None
        assert len(search_id) == 36  # UUID format

        # Retrieve via history
        history = db.get_search_history(limit=1)
        assert len(history) == 1
        assert history[0]["query"] == "nike air max"
        assert history[0]["marketplace"] == "vinted"
        assert history[0]["brand"] == "Nike"
        assert history[0]["total_results"] == 42

    def test_save_search_minimal(self, db):
        """Save with only required fields."""
        search_id = db.save_search(query="test query")
        assert search_id is not None
        history = db.get_search_history()
        assert len(history) == 1
        assert history[0]["marketplace"] is None
        assert history[0]["brand"] is None

    def test_search_history_filter_by_marketplace(self, db):
        db.save_search(query="shoes", marketplace="vinted")
        db.save_search(query="shoes", marketplace="ebay")
        db.save_search(query="shoes", marketplace="vinted")

        vinted_history = db.get_search_history(marketplace="vinted")
        # Should include vinted AND NULL marketplace entries
        assert all(h["marketplace"] in ("vinted", None) for h in vinted_history)

        all_history = db.get_search_history()
        assert len(all_history) == 3

    def test_search_history_limit(self, db):
        for i in range(10):
            db.save_search(query=f"query_{i}")

        limited = db.get_search_history(limit=5)
        assert len(limited) == 5

    def test_search_history_order(self, db):
        """Most recent searches first."""
        db.save_search(query="first")
        db.save_search(query="second")
        db.save_search(query="third")

        history = db.get_search_history()
        assert history[0]["query"] == "third"
        assert history[2]["query"] == "first"

    def test_save_and_retrieve_search_items(self, db, sample_items):
        search_id = db.save_search(query="test", marketplace="vinted")
        db.save_search_items(search_id, sample_items)

        results = db.get_search_results(search_id)
        assert len(results) == 3
        assert results[0]["title"] in [i["title"] for i in sample_items]

    def test_search_items_ordered_by_price(self, db, sample_items):
        """Results should be ordered by price ASC."""
        search_id = db.save_search(query="test")
        db.save_search_items(search_id, sample_items)

        results = db.get_search_results(search_id)
        prices = [r["price"] for r in results]
        assert prices == sorted(prices)

    def test_search_items_empty(self, db):
        search_id = db.save_search(query="empty")
        db.save_search_items(search_id, [])
        results = db.get_search_results(search_id)
        assert len(results) == 0

    def test_save_item_bookmark(self, db):
        saved_id = db.save_item(
            item_id="v_12345",
            marketplace="vinted",
            title="Nike Dunk Low",
            url="https://vinted.fr/items/12345",
            price=55.0,
            currency="EUR",
            brand="Nike",
            notes="Good deal, size matches",
        )
        assert saved_id is not None

        saved = db.get_saved_items()
        assert len(saved) == 1
        assert saved[0]["item_id"] == "v_12345"
        assert saved[0]["marketplace"] == "vinted"
        assert saved[0]["notes"] == "Good deal, size matches"

    def test_save_item_upsert(self, db):
        """Same item_id + marketplace = replace."""
        db.save_item(item_id="x1", marketplace="ebay", title="V1", price=100)
        db.save_item(item_id="x1", marketplace="ebay", title="V2", price=90)

        saved = db.get_saved_items()
        # UNIQUE(item_id, marketplace) — INSERT OR REPLACE
        assert len(saved) == 1
        assert saved[0]["title"] == "V2"
        assert saved[0]["price"] == 90

    def test_saved_items_filter_by_marketplace(self, db):
        db.save_item(item_id="a", marketplace="vinted", title="A")
        db.save_item(item_id="b", marketplace="ebay", title="B")
        db.save_item(item_id="c", marketplace="vinted", title="C")

        vinted = db.get_saved_items(marketplace="vinted")
        assert len(vinted) == 2
        assert all(s["marketplace"] == "vinted" for s in vinted)

    def test_get_stats(self, db, sample_items):
        db.save_search(query="q1", marketplace="vinted", items_returned=10, duration_ms=200)
        db.save_search(query="q2", marketplace="ebay", items_returned=5, duration_ms=300)
        db.save_search(query="q3", marketplace="vinted", items_returned=8, duration_ms=150)

        stats = db.get_stats()
        assert stats["summary"]["total_searches"] == 3
        assert stats["summary"]["total_items"] == 23
        assert stats["saved_items"] == 0

        by_mp = {r["marketplace"]: r for r in stats["by_marketplace"]}
        assert by_mp["vinted"]["searches"] == 2
        assert by_mp["ebay"]["searches"] == 1

    def test_get_stats_by_marketplace(self, db):
        db.save_search(query="q1", marketplace="vinted", items_returned=10)
        db.save_search(query="q2", marketplace="ebay", items_returned=5)

        stats = db.get_stats(marketplace="vinted")
        assert stats["summary"]["total_searches"] == 1
        assert stats["summary"]["total_items"] == 10

    def test_cleanup_old_searches(self, db):
        """Old searches should be cleaned up."""
        # Create a recent search
        recent_id = db.save_search(query="recent")

        # Create an old search by manually inserting
        old_time = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
        db.conn.execute(
            """INSERT INTO searches (id, query, created_at)
               VALUES (?, ?, ?)""",
            ("old-search-id", "old query", old_time),
        )
        db.conn.commit()

        # Add items to old search
        db.save_search_items("old-search-id", [
            {"item_id": "old1", "marketplace": "vinted", "title": "Old Item"},
        ])

        # Verify both exist
        all_history = db.get_search_history(limit=100)
        assert len(all_history) == 2

        # Cleanup (30 days default)
        deleted = db.cleanup_old_searches(days=30)
        assert deleted == 1

        # Old one gone, recent stays
        remaining = db.get_search_history(limit=100)
        assert len(remaining) == 1
        assert remaining[0]["query"] == "recent"

        # Items also cleaned
        old_items = db.get_search_results("old-search-id")
        assert len(old_items) == 0

    def test_cleanup_nothing_to_delete(self, db):
        db.save_search(query="recent")
        deleted = db.cleanup_old_searches(days=30)
        assert deleted == 0

    def test_foreign_key_constraint(self, db):
        """search_items should reference valid search_id."""
        # This should work
        sid = db.save_search(query="valid")
        db.save_search_items(sid, [{"item_id": "x", "marketplace": "v", "title": "T"}])
        results = db.get_search_results(sid)
        assert len(results) == 1


class TestDBThreadSafety:
    """Test thread safety of DB operations."""

    def test_concurrent_saves(self, db):
        """Multiple threads saving simultaneously."""
        errors = []
        ids = []

        def save_search(n):
            try:
                sid = db.save_search(
                    query=f"thread_query_{n}",
                    marketplace="vinted",
                    items_returned=n,
                )
                ids.append(sid)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=save_search, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(errors) == 0, f"Thread errors: {errors}"
        assert len(ids) == 10

        history = db.get_search_history(limit=20)
        assert len(history) == 10

    def test_concurrent_save_items(self, db, sample_items):
        """Multiple threads saving items to different searches."""
        errors = []

        def save_items(n):
            try:
                sid = db.save_search(query=f"search_{n}")
                db.save_search_items(sid, sample_items)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=save_items, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(errors) == 0, f"Thread errors: {errors}"


class TestDBSingleton:
    """Test singleton pattern."""

    def test_singleton_returns_same_instance(self, temp_db_path):
        import server.db as db_mod
        db_mod._db_instance = None

        db1 = db_mod.get_db(temp_db_path)
        db2 = db_mod.get_db()  # Should return same instance

        assert db1 is db2

        db_mod._db_instance = None  # Cleanup
