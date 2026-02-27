"""Tests for server.types — dataclasses and enums."""

import pytest
from server.types import (
    SearchParams, MarketplaceItem, SearchResult, ItemDetails,
    MarketplaceCapability, ItemCondition, SortOrder, ItemCategory,
)


# =============================================================================
# ENUM TESTS
# =============================================================================

class TestItemCondition:
    def test_all_conditions_exist(self):
        conditions = [e.value for e in ItemCondition]
        assert "new_with_tags" in conditions
        assert "like_new" in conditions
        assert "good" in conditions
        assert "unknown" in conditions

    def test_string_comparison(self):
        assert ItemCondition.NEW_WITH_TAGS == "new_with_tags"
        assert ItemCondition.GOOD == "good"

    def test_count(self):
        assert len(ItemCondition) == 8


class TestSortOrder:
    def test_all_sorts_exist(self):
        sorts = [e.value for e in SortOrder]
        assert "relevance" in sorts
        assert "price_asc" in sorts
        assert "newest" in sorts

    def test_count(self):
        assert len(SortOrder) == 5


class TestItemCategory:
    def test_all_categories_exist(self):
        cats = [e.value for e in ItemCategory]
        expected = [
            "clothing", "shoes", "accessories", "bags", "luxury",
            "streetwear", "vintage", "electronics", "furniture",
            "sports", "kids", "home", "general",
        ]
        for c in expected:
            assert c in cats, f"Missing category: {c}"

    def test_count(self):
        assert len(ItemCategory) == 13


# =============================================================================
# SEARCH PARAMS TESTS
# =============================================================================

class TestSearchParams:
    def test_minimal(self):
        p = SearchParams(query="nike shoes")
        assert p.query == "nike shoes"
        assert p.category == ""
        assert p.brand == ""
        assert p.min_price == 0.0
        assert p.max_price == 0.0
        assert p.limit == 20
        assert p.page == 1

    def test_full_params(self):
        p = SearchParams(
            query="jordan 4",
            category="shoes",
            brand="Nike",
            min_price=100,
            max_price=300,
            condition="new_with_tags",
            size="42",
            color="black",
            sort="price_asc",
            limit=50,
            page=2,
            region="EU",
            currency="EUR",
        )
        assert p.query == "jordan 4"
        assert p.brand == "Nike"
        assert p.min_price == 100
        assert p.max_price == 300
        assert p.limit == 50
        assert p.page == 2
        assert p.region == "EU"

    def test_defaults_are_safe(self):
        p = SearchParams(query="test")
        assert p.sort == "relevance"
        assert p.currency == ""
        assert p.color == ""


# =============================================================================
# MARKETPLACE ITEM TESTS
# =============================================================================

class TestMarketplaceItem:
    def test_minimal(self):
        item = MarketplaceItem(
            item_id="123",
            marketplace="vinted",
            title="Test Item",
            url="https://example.com/123",
            price=25.0,
            currency="EUR",
        )
        assert item.item_id == "123"
        assert item.marketplace == "vinted"
        assert item.price == 25.0
        assert item.brand == ""
        assert item.favorites == 0
        assert item.promoted is False

    def test_to_dict(self):
        item = MarketplaceItem(
            item_id="456",
            marketplace="ebay",
            title="Jordan 1",
            url="https://ebay.com/456",
            price=150.0,
            currency="USD",
            brand="Nike",
            size="10",
        )
        d = item.to_dict()
        assert isinstance(d, dict)
        assert d["item_id"] == "456"
        assert d["marketplace"] == "ebay"
        assert d["price"] == 150.0
        assert d["brand"] == "Nike"
        assert d["size"] == "10"
        # to_dict includes specific keys
        assert "title" in d
        assert "url" in d
        assert "currency" in d

    def test_to_dict_keys(self):
        """Ensure to_dict returns exactly the expected keys."""
        item = MarketplaceItem(
            item_id="1", marketplace="test", title="T",
            url="http://x", price=1.0, currency="USD",
        )
        d = item.to_dict()
        expected_keys = {
            "item_id", "marketplace", "title", "url", "price", "currency",
            "brand", "size", "condition", "color", "image_url",
            "seller_name", "seller_rating", "favorites", "views",
            "listed_at", "location",
        }
        assert set(d.keys()) == expected_keys

    def test_image_urls_default_factory(self):
        """Ensure mutable default factory works correctly."""
        item1 = MarketplaceItem(
            item_id="a", marketplace="x", title="A",
            url="http://a", price=1.0, currency="EUR",
        )
        item2 = MarketplaceItem(
            item_id="b", marketplace="x", title="B",
            url="http://b", price=2.0, currency="EUR",
        )
        # Must be separate lists
        item1.image_urls.append("http://img1.jpg")
        assert len(item2.image_urls) == 0


# =============================================================================
# SEARCH RESULT TESTS
# =============================================================================

class TestSearchResult:
    def test_basic(self):
        result = SearchResult(
            items=[],
            total_found=0,
            marketplace="vinted",
            query="test",
        )
        assert result.total_found == 0
        assert result.page == 1
        assert result.pages_total == 1
        assert result.duration_ms == 0

    def test_to_summary(self):
        items = [
            MarketplaceItem(
                item_id=str(i), marketplace="vinted", title=f"Item {i}",
                url=f"http://x/{i}", price=10.0 * i, currency="EUR",
            )
            for i in range(1, 4)
        ]
        result = SearchResult(
            items=items,
            total_found=100,
            marketplace="vinted",
            query="test",
            duration_ms=450,
        )
        summary = result.to_summary()
        assert "vinted" in summary
        assert "3 items" in summary
        assert "100 total" in summary
        assert "450ms" in summary


# =============================================================================
# ITEM DETAILS TESTS
# =============================================================================

class TestItemDetails:
    def test_basic(self):
        item = MarketplaceItem(
            item_id="1", marketplace="vinted", title="T",
            url="http://x", price=10.0, currency="EUR",
        )
        details = ItemDetails(item=item)
        assert details.item is item
        assert details.description == ""
        assert details.all_photos == []
        assert details.seller_total_items == 0
        assert details.seller_verified is False
        assert details.raw_data == {}

    def test_mutable_defaults(self):
        """Ensure mutable default factory prevents shared state."""
        item = MarketplaceItem(
            item_id="1", marketplace="x", title="T",
            url="http://x", price=1.0, currency="E",
        )
        d1 = ItemDetails(item=item)
        d2 = ItemDetails(item=item)
        d1.all_photos.append("photo.jpg")
        assert len(d2.all_photos) == 0
        d1.raw_data["key"] = "val"
        assert "key" not in d2.raw_data


# =============================================================================
# MARKETPLACE CAPABILITY TESTS
# =============================================================================

class TestMarketplaceCapability:
    def test_defaults(self):
        cap = MarketplaceCapability()
        assert cap.categories == []
        assert cap.regions == []
        assert cap.has_api is False
        assert cap.requires_auth == "api_key"
        assert cap.max_results_per_page == 50
        assert cap.rate_limit_rpm == 60
        assert "query" in cap.supports_filters
        assert "price" in cap.supports_filters

    def test_full(self):
        cap = MarketplaceCapability(
            categories=["shoes", "clothing"],
            regions=["US", "EU"],
            has_api=True,
            requires_auth="oauth",
            max_results_per_page=200,
            rate_limit_rpm=5000,
            strengths=["global", "official_api"],
            notes="Test marketplace",
        )
        assert len(cap.categories) == 2
        assert cap.has_api is True
        assert cap.rate_limit_rpm == 5000
        assert "global" in cap.strengths
