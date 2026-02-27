"""Pytest fixtures for MCP Marketplace Search tests."""

import os
import tempfile
import pytest

# Set test environment BEFORE any server imports
os.environ["VINTED_COOKIE"] = "test_vinted_cookie=abc123"
os.environ["EBAY_API_KEY"] = "test_ebay_key_12345"
os.environ["GRAILED_ALGOLIA_KEY"] = "test_grailed_algolia_key"
os.environ["VESTIAIRE_COOKIE"] = "test_vestiaire_cookie=xyz"
os.environ["DEPOP_COOKIE"] = "test_depop_cookie=def456"
os.environ["APIFY_API_TOKEN"] = "test_apify_token_abc123"


@pytest.fixture
def temp_db_path():
    """Create a temporary database file for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    yield path
    # Cleanup — ignore Windows file lock errors (SQLite keeps files open)
    for p in [path, path + "-wal", path + "-shm"]:
        try:
            os.unlink(p)
        except (FileNotFoundError, PermissionError):
            pass


@pytest.fixture
def db(temp_db_path):
    """Create a fresh SearchDB instance for testing."""
    # Reset singleton
    import server.db as db_mod
    db_mod._db_instance = None
    os.environ["MARKETPLACE_DB_PATH"] = temp_db_path
    db_instance = db_mod.get_db(temp_db_path)
    yield db_instance
    # Close connection BEFORE cleanup to avoid Windows file lock
    try:
        db_instance.conn.close()
    except Exception:
        pass
    # Cleanup singleton
    db_mod._db_instance = None
    if "MARKETPLACE_DB_PATH" in os.environ:
        del os.environ["MARKETPLACE_DB_PATH"]


@pytest.fixture(autouse=True)
def reset_providers():
    """Reset provider registry between tests to avoid state leaks."""
    import server.providers as prov_mod
    prov_mod._providers = None
    yield
    prov_mod._providers = None


@pytest.fixture
def sample_items():
    """Sample MarketplaceItem dicts for testing."""
    return [
        {
            "item_id": "item_001",
            "marketplace": "vinted",
            "title": "Nike Air Max 90 White",
            "url": "https://www.vinted.fr/items/12345",
            "price": 45.0,
            "currency": "EUR",
            "brand": "Nike",
            "size": "42",
            "condition": "very_good",
            "image_url": "https://img.vinted.net/photo1.jpg",
            "seller_name": "fashionista99",
            "seller_rating": 4.8,
            "favorites": 12,
            "views": 156,
            "listed_at": "2026-02-25T10:00:00Z",
            "location": "Paris, France",
        },
        {
            "item_id": "item_002",
            "marketplace": "vinted",
            "title": "Adidas Stan Smith Green",
            "url": "https://www.vinted.fr/items/67890",
            "price": 30.0,
            "currency": "EUR",
            "brand": "Adidas",
            "size": "44",
            "condition": "good",
            "image_url": "https://img.vinted.net/photo2.jpg",
            "seller_name": "sneakerhead42",
            "seller_rating": 4.5,
            "favorites": 8,
            "views": 89,
            "listed_at": "2026-02-24T15:30:00Z",
            "location": "Berlin, Germany",
        },
        {
            "item_id": "item_003",
            "marketplace": "ebay",
            "title": "Jordan 4 Retro Black Cat",
            "url": "https://www.ebay.com/itm/999888",
            "price": 250.0,
            "currency": "USD",
            "brand": "Nike",
            "size": "10",
            "condition": "new_with_tags",
            "image_url": "https://i.ebayimg.com/photo3.jpg",
            "seller_name": "kicks_dealer",
            "seller_rating": 99.5,
            "favorites": 0,
            "views": 0,
            "listed_at": "2026-02-26T08:00:00Z",
            "location": "US",
        },
    ]
