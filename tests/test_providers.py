"""Tests for server.providers — marketplace providers and registry."""

import os
import time
import pytest
from unittest.mock import patch, MagicMock

from server.types import SearchParams, SearchResult, MarketplaceItem, ItemDetails
from server.providers import (
    BaseMarketplaceProvider, ProviderHealth,
    MARKETPLACE_REGISTRY, CATEGORY_ROUTING, VALID_MARKETPLACES,
    PROVIDER_CLASSES,
    get_providers, get_provider, get_available_providers,
    get_best_marketplace_for_category, get_health, get_all_health,
    VintedProvider, EbayProvider, GrailedProvider,
    VestiaireProvider, DepopProvider, ApifyProvider,
)


# =============================================================================
# PROVIDER HEALTH TESTS
# =============================================================================

class TestProviderHealth:
    def test_initial_state(self):
        h = ProviderHealth()
        assert h.total_calls == 0
        assert h.successful_calls == 0
        assert h.failed_calls == 0
        assert h.consecutive_failures == 0
        assert h.circuit_open is False
        assert h.success_rate == 1.0
        assert h.avg_latency_ms == 0

    def test_record_success(self):
        h = ProviderHealth()
        h.record_success(100)
        assert h.total_calls == 1
        assert h.successful_calls == 1
        assert h.avg_latency_ms == 100
        assert h.success_rate == 1.0

    def test_record_failure(self):
        h = ProviderHealth()
        h.record_failure("timeout")
        assert h.total_calls == 1
        assert h.failed_calls == 1
        assert h.consecutive_failures == 1
        assert h.last_error == "timeout"
        assert h.circuit_open is False

    def test_circuit_breaker_opens_after_3_failures(self):
        h = ProviderHealth()
        h.record_failure("err1")
        h.record_failure("err2")
        assert h.circuit_open is False

        h.record_failure("err3")
        assert h.circuit_open is True
        assert h.circuit_open_until > 0

    def test_circuit_breaker_blocks_requests(self):
        h = ProviderHealth()
        h.record_failure("e1")
        h.record_failure("e2")
        h.record_failure("e3")

        assert h.is_healthy() is False  # Circuit open, within cooldown

    def test_circuit_breaker_recovers_after_cooldown(self):
        h = ProviderHealth()
        h.record_failure("e1")
        h.record_failure("e2")
        h.record_failure("e3")

        # Simulate cooldown expiry
        h.circuit_open_until = time.monotonic() - 1
        assert h.is_healthy() is True

    def test_success_after_failure_resets_consecutive(self):
        h = ProviderHealth()
        h.record_failure("err")
        h.record_failure("err")
        assert h.consecutive_failures == 2

        h.record_success(50)
        assert h.consecutive_failures == 0

    def test_success_closes_circuit(self):
        h = ProviderHealth()
        h.record_failure("e1")
        h.record_failure("e2")
        h.record_failure("e3")
        assert h.circuit_open is True

        h.record_success(100)
        assert h.circuit_open is False

    def test_success_rate_calculation(self):
        h = ProviderHealth()
        h.record_success(100)
        h.record_success(200)
        h.record_failure("err")
        assert abs(h.success_rate - 2/3) < 0.01

    def test_avg_latency(self):
        h = ProviderHealth()
        h.record_success(100)
        h.record_success(200)
        h.record_success(300)
        assert h.avg_latency_ms == 200


# =============================================================================
# MARKETPLACE REGISTRY TESTS
# =============================================================================

class TestMarketplaceRegistry:
    def test_all_9_marketplaces_registered(self):
        assert len(MARKETPLACE_REGISTRY) == 9
        expected = {"vinted", "ebay", "grailed", "vestiaire", "depop", "apify", "allegro", "olx", "stockx"}
        assert set(MARKETPLACE_REGISTRY.keys()) == expected

    def test_vinted_capabilities(self):
        cap = MARKETPLACE_REGISTRY["vinted"]
        assert "clothing" in cap.categories
        assert "shoes" in cap.categories
        assert "EU" in cap.regions
        assert cap.has_api is False
        assert cap.requires_auth == "cookies"

    def test_ebay_capabilities(self):
        cap = MARKETPLACE_REGISTRY["ebay"]
        assert cap.has_api is True
        assert cap.requires_auth == "api_key"
        assert "US" in cap.regions
        assert cap.rate_limit_rpm >= 5000

    def test_grailed_capabilities(self):
        cap = MARKETPLACE_REGISTRY["grailed"]
        assert "streetwear" in cap.categories
        assert cap.requires_auth == "cookies"

    def test_all_have_strengths(self):
        for name, cap in MARKETPLACE_REGISTRY.items():
            assert len(cap.strengths) > 0, f"{name} has no strengths"

    def test_all_have_categories(self):
        for name, cap in MARKETPLACE_REGISTRY.items():
            assert len(cap.categories) > 0, f"{name} has no categories"


# =============================================================================
# CATEGORY ROUTING TESTS
# =============================================================================

class TestCategoryRouting:
    def test_all_13_categories_routed(self):
        assert len(CATEGORY_ROUTING) == 13
        expected = {
            "clothing", "shoes", "accessories", "bags", "luxury",
            "streetwear", "vintage", "electronics", "furniture",
            "sports", "kids", "home", "general",
        }
        assert set(CATEGORY_ROUTING.keys()) == expected

    def test_each_route_has_entries(self):
        for cat, routes in CATEGORY_ROUTING.items():
            assert len(routes) >= 2, f"Category '{cat}' has < 2 routes"

    def test_route_format(self):
        """Each route should be (marketplace_name, region) tuple."""
        for cat, routes in CATEGORY_ROUTING.items():
            for marketplace, region in routes:
                assert marketplace in VALID_MARKETPLACES, \
                    f"Unknown marketplace '{marketplace}' in {cat} routing"
                assert isinstance(region, str) and len(region) >= 2

    def test_luxury_routes_to_vestiaire_first(self):
        routes = CATEGORY_ROUTING["luxury"]
        assert routes[0][0] == "vestiaire"

    def test_streetwear_routes_to_grailed_first(self):
        routes = CATEGORY_ROUTING["streetwear"]
        assert routes[0][0] == "grailed"

    def test_electronics_routes_to_ebay_first(self):
        routes = CATEGORY_ROUTING["electronics"]
        assert routes[0][0] == "ebay"


# =============================================================================
# PROVIDER CLASSES TESTS
# =============================================================================

class TestProviderClasses:
    def test_provider_classes_count(self):
        assert len(PROVIDER_CLASSES) == 6  # 5 direct + 1 ApifyProvider (meta)

    def test_all_have_required_attrs(self):
        for cls in PROVIDER_CLASSES:
            assert hasattr(cls, "name")
            assert hasattr(cls, "display_name")
            assert hasattr(cls, "base_url")
            assert hasattr(cls, "api_key_env")
            assert cls.name != "", f"{cls.__name__} has empty name"

    def test_provider_names_subset_of_registry(self):
        """Provider classes are a subset of registry (allegro/olx/stockx are Apify-only)."""
        provider_names = {cls.name for cls in PROVIDER_CLASSES}
        registry_names = set(MARKETPLACE_REGISTRY.keys())
        # All provider names should be in registry
        assert provider_names.issubset(registry_names)
        # Apify-only marketplaces don't have their own Provider class
        apify_only = {"allegro", "olx", "stockx"}
        assert apify_only.issubset(registry_names - provider_names)

    def test_valid_marketplaces_matches(self):
        assert set(VALID_MARKETPLACES) == set(MARKETPLACE_REGISTRY.keys())


# =============================================================================
# PROVIDER INSTANTIATION TESTS
# =============================================================================

class TestProviderInstantiation:
    """Test provider init with test env vars."""

    def test_vinted_init(self):
        p = VintedProvider()
        assert p.name == "vinted"
        assert p.display_name == "Vinted"
        assert p._cookies == os.environ.get("VINTED_COOKIE", "")

    def test_ebay_init(self):
        p = EbayProvider()
        assert p.name == "ebay"
        assert p._api_key == os.environ.get("EBAY_API_KEY", "")

    def test_grailed_init(self):
        p = GrailedProvider()
        assert p.name == "grailed"
        assert p.ALGOLIA_APP_ID == "MNRWEFSS2Q"

    def test_vestiaire_init(self):
        p = VestiaireProvider()
        assert p.name == "vestiaire"

    def test_depop_init(self):
        p = DepopProvider()
        assert p.name == "depop"

    def test_all_available_with_env_vars(self):
        """With test env vars set, all should be available."""
        for cls in PROVIDER_CLASSES:
            p = cls()
            # Vinted is_available checks for cookie OR playwright
            if p.name == "vinted":
                # With VINTED_COOKIE set, should be available
                assert p.is_available() is True
            elif p.name == "apify":
                # With APIFY_API_TOKEN set, should be available
                assert p.is_available() is True
            else:
                assert p.is_available() is True, f"{p.name} not available"


# =============================================================================
# PROVIDER REGISTRY FUNCTIONS TESTS
# =============================================================================

class TestProviderRegistry:
    # Note: reset_providers autouse fixture handles cleanup

    def test_get_providers_returns_all(self):
        providers = get_providers()
        assert len(providers) == 6  # 6 Provider classes (allegro/olx/stockx are Apify-only)
        assert "vinted" in providers
        assert "ebay" in providers
        assert "apify" in providers

    def test_get_provider_by_name(self):
        p = get_provider("vinted")
        assert p.name == "vinted"

    def test_get_provider_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown marketplace"):
            get_provider("aliexpress")

    def test_get_available_providers(self):
        available = get_available_providers()
        assert isinstance(available, list)
        # With test env vars, all should be available
        assert len(available) >= 4  # At least 4 (Vinted may need Playwright)

    def test_get_best_marketplace_for_category(self):
        result = get_best_marketplace_for_category("luxury")
        assert result is not None
        marketplace, region = result
        assert marketplace in VALID_MARKETPLACES

    def test_get_best_for_unknown_category_uses_general(self):
        result = get_best_marketplace_for_category("nonexistent")
        assert result is not None  # Falls back to "general"

    def test_health_registry(self):
        h = get_health("test_provider")
        assert isinstance(h, ProviderHealth)

        h.record_success(100)
        h2 = get_health("test_provider")
        assert h2.total_calls == 1  # Same instance

    def test_get_all_health(self):
        get_health("p1").record_success(50)
        get_health("p2").record_failure("err")

        all_h = get_all_health()
        assert "p1" in all_h
        assert "p2" in all_h


# =============================================================================
# BASE PROVIDER BEHAVIOR TESTS
# =============================================================================

class TestBaseProviderBehavior:
    """Test search/get_item orchestration without real API calls."""

    def test_search_raises_when_not_available(self):
        """Provider without credentials should raise."""
        # Create provider with missing key
        with patch.dict(os.environ, {"EBAY_API_KEY": ""}, clear=False):
            import server.providers as prov_mod
            prov_mod._providers = None
            p = EbayProvider()
            p._api_key = ""  # Force no key

            with pytest.raises(RuntimeError, match="not configured"):
                p.search(SearchParams(query="test"))

    def test_search_raises_when_circuit_open(self):
        """Provider with open circuit should raise."""
        p = VintedProvider()
        health = get_health(p.name)
        health.record_failure("e1")
        health.record_failure("e2")
        health.record_failure("e3")

        with pytest.raises(RuntimeError, match="circuit breaker"):
            p.search(SearchParams(query="test"))

        # Cleanup
        health.circuit_open = False
        health.consecutive_failures = 0

    def test_rate_limiting(self):
        """Rate limiter should throttle requests."""
        p = EbayProvider()
        p.min_request_interval = 0.1  # Short for testing

        start = time.monotonic()
        p._rate_limit()
        p._rate_limit()
        elapsed = time.monotonic() - start

        # Second call should have waited
        assert elapsed >= 0.09  # ~0.1s interval

    def test_get_item_returns_none_when_unavailable(self):
        """get_item should return None gracefully when not available."""
        p = EbayProvider()
        p._api_key = ""
        result = p.get_item("nonexistent")
        assert result is None


# =============================================================================
# VINTED PROVIDER SPECIFIC TESTS
# =============================================================================

class TestVintedProvider:
    def test_domain_selection(self):
        with patch.dict(os.environ, {"VINTED_DOMAIN": "de"}, clear=False):
            p = VintedProvider()
            assert "vinted.de" in p.base_url

    def test_cookie_refresh_needed_when_empty(self):
        p = VintedProvider()
        p._cookies = ""
        assert p._needs_cookie_refresh() is True

    def test_cookie_not_needed_when_fresh(self):
        p = VintedProvider()
        p._cookies = "valid=cookie"
        p._cookie_obtained_at = time.monotonic()
        assert p._needs_cookie_refresh() is False

    def test_cookie_expired_after_ttl(self):
        p = VintedProvider()
        p._cookies = "old=cookie"
        p._cookie_obtained_at = time.monotonic() - 1600  # > 25min
        assert p._needs_cookie_refresh() is True

    def test_condition_mapping(self):
        """Verify condition ID mapping."""
        assert VintedProvider.CONDITIONS["new_with_tags"] == 6
        assert VintedProvider.CONDITIONS["very_good"] == 2
        assert VintedProvider.CONDITIONS["fair"] == 4

    def test_domains_count(self):
        assert len(VintedProvider.DOMAINS) == 8

    def test_is_available_with_cookie(self):
        p = VintedProvider()
        p._api_key = "some_cookie"
        assert p.is_available() is True

    def test_item_url(self):
        p = VintedProvider()
        url = p.get_item_url("12345")
        assert "12345" in url
        assert "vinted" in url


# =============================================================================
# EBAY PROVIDER SPECIFIC TESTS
# =============================================================================

class TestEbayProvider:
    def test_marketplace_ids(self):
        assert EbayProvider.MARKETPLACES["US"] == "EBAY_US"
        assert EbayProvider.MARKETPLACES["UK"] == "EBAY_GB"
        assert len(EbayProvider.MARKETPLACES) == 7

    def test_oauth_uses_apikey_without_secret(self):
        p = EbayProvider()
        p._app_secret = ""
        token = p._get_oauth_token()
        assert token == p._api_key  # Falls back to API key

    def test_item_url(self):
        p = EbayProvider()
        url = p.get_item_url("v1|123456|0")
        assert "ebay.com" in url


# =============================================================================
# GRAILED PROVIDER SPECIFIC TESTS
# =============================================================================

class TestGrailedProvider:
    def test_algolia_config(self):
        p = GrailedProvider()
        assert p.ALGOLIA_APP_ID == "MNRWEFSS2Q"
        assert p.ALGOLIA_INDEX == "Listing_production"

    def test_item_url(self):
        p = GrailedProvider()
        url = p.get_item_url("78901")
        assert "grailed.com/listings/78901" in url

    def test_get_item_returns_none(self):
        """Grailed doesn't support individual item fetch."""
        p = GrailedProvider()
        result = p._do_get_item("12345")
        assert result is None


# =============================================================================
# APIFY PROVIDER SPECIFIC TESTS
# =============================================================================

class TestApifyProvider:
    def test_init(self):
        p = ApifyProvider()
        assert p.name == "apify"
        assert p.display_name == "Apify (Cloud Scraping)"
        assert p.api_key_env == "APIFY_API_TOKEN"
        assert p.base_url == "https://api.apify.com/v2"

    def test_is_available_with_token(self):
        p = ApifyProvider()
        assert p.is_available() is True

    def test_is_available_without_token(self):
        p = ApifyProvider()
        p._token = ""
        assert p.is_available() is False

    def test_actor_map_has_8_marketplaces(self):
        expected = {"vinted", "grailed", "ebay", "vestiaire", "depop", "allegro", "olx", "stockx"}
        assert set(ApifyProvider.ACTOR_MAP.keys()) == expected
        assert ApifyProvider.ACTOR_MAP["vinted"] == "bebity/vinted-premium-actor"
        assert ApifyProvider.ACTOR_MAP["grailed"] == "vmscrapers/grailed"
        assert ApifyProvider.ACTOR_MAP["ebay"] == "dtrungtin/ebay-items-scraper"
        assert ApifyProvider.ACTOR_MAP["allegro"] == "tri_angle/allegro-fast-product-scraper"
        assert ApifyProvider.ACTOR_MAP["stockx"] == "ecomscrape/stockx-product-search-scraper"

    def test_get_supported_marketplaces(self):
        p = ApifyProvider()
        supported = p.get_supported_marketplaces()
        assert len(supported) == 8
        for m in ["vinted", "grailed", "ebay", "vestiaire", "depop", "allegro", "olx", "stockx"]:
            assert m in supported

    def test_build_actor_input_vinted(self):
        p = ApifyProvider()
        params = SearchParams(
            query="nike air max",
            min_price=10.0,
            max_price=100.0,
            brand="Nike",
            limit=15,
        )
        inp = p._build_actor_input("vinted", params)
        assert inp["search"] == "nike air max"
        assert inp["maxItems"] == 15
        assert inp["priceFrom"] == 10.0
        assert inp["priceTo"] == 100.0
        assert inp["brand"] == "Nike"
        assert "url" in inp
        assert "vinted." in inp["url"]

    def test_build_actor_input_vinted_no_price_filter(self):
        p = ApifyProvider()
        params = SearchParams(query="test", limit=20)
        inp = p._build_actor_input("vinted", params)
        assert "priceFrom" not in inp
        assert "priceTo" not in inp

    def test_build_actor_input_grailed(self):
        p = ApifyProvider()
        params = SearchParams(
            query="rick owens",
            min_price=50.0,
            max_price=500.0,
            limit=10,
        )
        inp = p._build_actor_input("grailed", params)
        # vmscrapers/grailed uses URL-based input
        assert "startUrls" in inp
        assert len(inp["startUrls"]) == 1
        assert "grailed.com/shop" in inp["startUrls"][0]["url"]
        assert "rick+owens" in inp["startUrls"][0]["url"]

    def test_build_actor_input_generic(self):
        p = ApifyProvider()
        params = SearchParams(query="test item", limit=5)
        inp = p._build_actor_input("unknown_marketplace", params)
        assert inp["search"] == "test item"
        assert inp["maxItems"] == 5

    def test_parse_vinted_result(self):
        p = ApifyProvider()
        raw = {
            "id": 12345,
            "title": "Nike Air Max 90",
            "url": "https://www.vinted.fr/items/12345",
            "price": 45.0,
            "currency": "EUR",
            "brand_title": "Nike",
            "size_title": "42",
            "photo": "https://img.vinted.net/photo1.jpg",
            "status": "very_good",
            "city": "Paris",
            "user": {"login": "fashionista99"},
        }
        item = p._parse_vinted_result(raw)
        assert item.item_id == "12345"
        assert item.marketplace == "vinted"
        assert item.title == "Nike Air Max 90"
        assert item.price == 45.0
        assert item.currency == "EUR"
        assert item.brand == "Nike"
        assert item.size == "42"
        assert item.image_url == "https://img.vinted.net/photo1.jpg"
        assert item.seller_name == "fashionista99"

    def test_parse_vinted_result_fallback_fields(self):
        """Test that parser handles alternative field names."""
        p = ApifyProvider()
        raw = {
            "item_id": "99999",
            "title": "Test Item",
            "path": "/items/99999",
            "total_item_price": 30.0,
            "brand": "Adidas",
            "size": "L",
            "image_url": "https://img.test/photo.jpg",
            "user": "simple_string_user",
        }
        item = p._parse_vinted_result(raw)
        assert item.item_id == "99999"
        assert item.url == "/items/99999"
        assert item.price == 30.0
        assert item.brand == "Adidas"
        assert item.seller_name == "simple_string_user"

    def test_parse_grailed_result(self):
        p = ApifyProvider()
        raw = {
            "id": 67890,
            "title": "Rick Owens DRKSHDW",
            "url": "https://www.grailed.com/listings/67890",
            "price": 350.0,
            "currency": "USD",
            "designer": "Rick Owens",
            "size": "M",
            "image": "https://img.grailed.com/photo.jpg",
            "condition": "like_new",
            "seller": {"username": "archive_dealer"},
        }
        item = p._parse_grailed_result(raw)
        assert item.item_id == "67890"
        assert item.marketplace == "grailed"
        assert item.title == "Rick Owens DRKSHDW"
        assert item.price == 350.0
        assert item.brand == "Rick Owens"
        assert item.seller_name == "archive_dealer"

    def test_parse_generic_result(self):
        p = ApifyProvider()
        raw = {
            "id": "abc",
            "title": "Generic Item",
            "url": "https://example.com/item/abc",
            "price": 25.0,
            "currency": "GBP",
            "brand": "TestBrand",
        }
        item = p._parse_generic_result(raw, "test_marketplace")
        assert item.item_id == "abc"
        assert item.marketplace == "test_marketplace"
        assert item.title == "Generic Item"
        assert item.price == 25.0

    def test_parse_result_routes_to_correct_parser(self):
        p = ApifyProvider()
        vinted_raw = {"id": 1, "title": "V", "price": 10, "url": "u", "currency": "EUR"}
        grailed_raw = {"id": 2, "title": "G", "price": 20, "url": "u", "currency": "USD"}
        unknown_raw = {"id": 3, "title": "U", "price": 30, "url": "u", "currency": "GBP"}

        v = p._parse_result(vinted_raw, "vinted")
        assert v.marketplace == "vinted"

        g = p._parse_result(grailed_raw, "grailed")
        assert g.marketplace == "grailed"

        u = p._parse_result(unknown_raw, "depop")
        assert u.marketplace == "depop"

    def test_parse_result_handles_error_gracefully(self):
        """If marketplace-specific parser fails, falls back to generic."""
        p = ApifyProvider()
        # Cause error by passing non-dict for nested field
        raw = {"id": "x", "title": "Test", "price": "not_a_number", "url": "u"}
        # Should not raise — fallback to generic parser
        item = p._parse_result(raw, "vinted")
        assert item.title == "Test"

    def test_do_get_item_returns_none(self):
        """Apify doesn't support individual item fetch."""
        p = ApifyProvider()
        result = p._do_get_item("12345")
        assert result is None

    def test_get_item_url_empty(self):
        p = ApifyProvider()
        assert p.get_item_url("12345") == ""

    def test_actor_timeout_and_poll_interval(self):
        assert ApifyProvider.ACTOR_TIMEOUT == 300
        assert ApifyProvider.POLL_INTERVAL == 5

    def test_min_request_interval(self):
        p = ApifyProvider()
        assert p.min_request_interval == 1.0

    def test_marketplace_registry_has_apify(self):
        assert "apify" in MARKETPLACE_REGISTRY
        cap = MARKETPLACE_REGISTRY["apify"]
        assert cap.has_api is True
        assert cap.requires_auth == "api_key"
        assert "cloud_scraping" in cap.strengths
        assert "multi_marketplace" in cap.strengths
        assert "8_actors" in cap.strengths

    def test_valid_marketplaces_includes_apify(self):
        assert "apify" in VALID_MARKETPLACES

    def test_category_routing_has_apify_fallback(self):
        """Apify should appear as fallback in category routing."""
        categories_with_apify = [
            cat for cat, chain in CATEGORY_ROUTING.items()
            if any(m == "apify" for m, r in chain)
        ]
        assert len(categories_with_apify) >= 5  # At least 5 categories have apify

    # --- eBay actor input/parser tests ---

    def test_build_actor_input_ebay(self):
        p = ApifyProvider()
        params = SearchParams(
            query="nike shoes",
            min_price=50.0,
            max_price=200.0,
            limit=15,
            region="US",
        )
        inp = p._build_actor_input("ebay", params)
        assert "startUrls" in inp
        assert "ebay.com" in inp["startUrls"][0]["url"]
        assert "nike+shoes" in inp["startUrls"][0]["url"]
        assert inp["maxItems"] == 15

    def test_build_actor_input_ebay_uk(self):
        p = ApifyProvider()
        params = SearchParams(query="trainers", limit=10, region="UK")
        inp = p._build_actor_input("ebay", params)
        assert "ebay.co.uk" in inp["startUrls"][0]["url"]

    def test_parse_ebay_result(self):
        p = ApifyProvider()
        raw = {
            "itemNumber": "123456789",
            "title": "Nike Air Max 90 White",
            "url": "https://www.ebay.com/itm/123456789",
            "price": 89.99,
            "currency": "USD",
            "brand": "Nike",
            "condition": "New",
            "image": "https://i.ebayimg.com/photo.jpg",
            "seller": "shoe_dealer",
            "itemLocation": "New York, US",
        }
        item = p._parse_ebay_result(raw)
        assert item.item_id == "123456789"
        assert item.marketplace == "ebay"
        assert item.price == 89.99
        assert item.brand == "Nike"
        assert item.seller_name == "shoe_dealer"

    # --- Vestiaire actor input/parser tests ---

    def test_build_actor_input_vestiaire(self):
        p = ApifyProvider()
        params = SearchParams(query="gucci bag", brand="Gucci", limit=10)
        inp = p._build_actor_input("vestiaire", params)
        # parseforge actor uses startUrl (singular string), NOT startUrls (plural array)
        assert "startUrl" in inp
        assert "vestiairecollective.com" in inp["startUrl"]
        assert inp["maxItems"] == 10

    def test_parse_vestiaire_result(self):
        p = ApifyProvider()
        raw = {
            "id": "vc_001",
            "name": "Gucci Marmont Bag",
            "url": "https://www.vestiairecollective.com/product/vc_001",
            "price": {"amount": 850.0, "currency": "EUR"},
            "brand": {"name": "Gucci"},
            "condition": "Very good",
            "pictures": [{"url": "https://img.vc.com/photo.jpg"}],
            "seller": {"username": "luxury_seller", "country": "France"},
        }
        item = p._parse_vestiaire_result(raw)
        assert item.item_id == "vc_001"
        assert item.marketplace == "vestiaire"
        assert item.price == 850.0
        assert item.brand == "Gucci"
        assert item.seller_name == "luxury_seller"

    def test_parse_vestiaire_result_flat_price(self):
        """Handle flat price (not dict)."""
        p = ApifyProvider()
        raw = {"id": "1", "name": "Test", "url": "u", "price": 100.0}
        item = p._parse_vestiaire_result(raw)
        assert item.price == 100.0

    # --- Depop actor input/parser tests ---

    def test_build_actor_input_depop(self):
        p = ApifyProvider()
        params = SearchParams(query="vintage nike", brand="Nike", limit=20)
        inp = p._build_actor_input("depop", params)
        assert inp["searchQueries"] == ["Nike vintage nike"]
        assert inp["maxResults"] == 20

    def test_parse_depop_result(self):
        p = ApifyProvider()
        raw = {
            "id": "dep_001",
            "description": "Vintage Nike windbreaker from the 90s",
            "url": "https://www.depop.com/products/dep_001",
            "price": {"amount": 35.0, "currency": "GBP"},
            "brand": "Nike",
            "size": "M",
            "condition": "good",
            "images": [{"url": "https://img.depop.com/photo.jpg"}],
            "seller": {"username": "vintage_finds"},
            "likes": 42,
        }
        item = p._parse_depop_result(raw)
        assert item.item_id == "dep_001"
        assert item.marketplace == "depop"
        assert item.price == 35.0
        assert item.brand == "Nike"
        assert item.favorites == 42

    # --- Allegro actor input/parser tests ---

    def test_build_actor_input_allegro(self):
        p = ApifyProvider()
        params = SearchParams(query="buty nike", limit=10)
        inp = p._build_actor_input("allegro", params)
        assert inp["search"] == "buty nike"
        assert inp["searchDomain"] == "allegro.pl"
        assert inp["maxProducts"] == 10

    def test_build_actor_input_allegro_cz(self):
        p = ApifyProvider()
        params = SearchParams(query="boty", limit=5, region="CZ")
        inp = p._build_actor_input("allegro", params)
        assert inp["searchDomain"] == "allegro.cz"

    def test_parse_allegro_result(self):
        p = ApifyProvider()
        raw = {
            "id": "alg_001",
            "name": "Nike Air Force 1 białe",
            "url": "https://allegro.pl/oferta/alg_001",
            "price": {"amount": 399.0, "currency": "PLN"},
            "images": [{"url": "https://img.allegro.pl/photo.jpg"}],
            "seller": {"login": "sklep_sportowy"},
            "location": "Warszawa",
        }
        item = p._parse_allegro_result(raw)
        assert item.item_id == "alg_001"
        assert item.marketplace == "allegro"
        assert item.price == 399.0
        assert item.currency == "PLN"
        assert item.seller_name == "sklep_sportowy"

    # --- OLX actor input/parser tests ---

    def test_build_actor_input_olx(self):
        p = ApifyProvider()
        params = SearchParams(query="iphone 15", min_price=1000, max_price=3000, limit=10)
        inp = p._build_actor_input("olx", params)
        assert "startUrls" in inp
        assert "olx.pl" in inp["startUrls"][0]
        assert inp["maxItems"] == 10
        assert inp["priceMin"] == 1000
        assert inp["priceMax"] == 3000

    def test_build_actor_input_olx_ukraine(self):
        p = ApifyProvider()
        params = SearchParams(query="ноутбук", limit=10, region="UA")
        inp = p._build_actor_input("olx", params)
        assert "olx.ua" in inp["startUrls"][0]

    def test_parse_olx_result(self):
        p = ApifyProvider()
        raw = {
            "id": "olx_001",
            "name": "iPhone 15 Pro 256GB",
            "url": "https://www.olx.pl/d/oferta/olx_001",
            "price": 4500.0,
            "currency": "PLN",
            "images": ["https://img.olx.pl/photo.jpg"],
            "location": "Kraków",
            "seller": {"name": "jan_kowalski"},
        }
        item = p._parse_olx_result(raw)
        assert item.item_id == "olx_001"
        assert item.marketplace == "olx"
        assert item.price == 4500.0
        assert item.location == "Kraków"

    def test_parse_olx_result_string_price(self):
        """OLX sometimes returns price as string like '4 500 zł'."""
        p = ApifyProvider()
        raw = {"id": "1", "name": "Test", "url": "u", "price": "4500.00"}
        item = p._parse_olx_result(raw)
        assert item.price == 4500.0

    # --- StockX actor input/parser tests ---

    def test_build_actor_input_stockx(self):
        p = ApifyProvider()
        params = SearchParams(query="jordan 4 retro", brand="Nike", limit=15)
        inp = p._build_actor_input("stockx", params)
        assert inp["keyword"] == "Nike jordan 4 retro"
        assert inp["maxItems"] == 15

    def test_parse_stockx_result(self):
        p = ApifyProvider()
        raw = {
            "id": "stx_001",
            "name": "Jordan 4 Retro Black Cat",
            "url": "https://stockx.com/jordan-4-retro-black-cat",
            "retailPrice": 200.0,
            "currency": "USD",
            "brand": "Nike",
            "condition": "New",
            "images": ["https://img.stockx.com/photo.jpg"],
            "category": "sneakers",
        }
        item = p._parse_stockx_result(raw)
        assert item.item_id == "stx_001"
        assert item.marketplace == "stockx"
        assert item.price == 200.0
        assert item.brand == "Nike"
        assert item.category == "sneakers"

    def test_parse_stockx_result_lastSale(self):
        """StockX may return lastSale instead of retailPrice."""
        p = ApifyProvider()
        raw = {"id": "1", "name": "Test", "url": "u", "lastSale": 180.0}
        item = p._parse_stockx_result(raw)
        assert item.price == 180.0

    # --- Parse result routing with new marketplaces ---

    def test_parse_result_routes_new_marketplaces(self):
        p = ApifyProvider()
        ebay_raw = {"itemNumber": "1", "title": "E", "price": 10, "url": "u"}
        allegro_raw = {"id": "2", "name": "A", "price": 20, "url": "u"}
        stockx_raw = {"id": "3", "name": "S", "retailPrice": 30, "url": "u"}

        e = p._parse_result(ebay_raw, "ebay")
        assert e.marketplace == "ebay"

        a = p._parse_result(allegro_raw, "allegro")
        assert a.marketplace == "allegro"

        s = p._parse_result(stockx_raw, "stockx")
        assert s.marketplace == "stockx"

    # --- Registry tests for new marketplaces ---

    def test_allegro_in_registry(self):
        assert "allegro" in MARKETPLACE_REGISTRY
        cap = MARKETPLACE_REGISTRY["allegro"]
        assert "PL" in cap.regions
        assert "electronics" in cap.categories
        assert "CEE_coverage" in cap.strengths

    def test_olx_in_registry(self):
        assert "olx" in MARKETPLACE_REGISTRY
        cap = MARKETPLACE_REGISTRY["olx"]
        assert "PL" in cap.regions
        assert "UA" in cap.regions
        assert "classifieds" in cap.strengths

    def test_stockx_in_registry(self):
        assert "stockx" in MARKETPLACE_REGISTRY
        cap = MARKETPLACE_REGISTRY["stockx"]
        assert "US" in cap.regions
        assert "shoes" in cap.categories
        assert "sneakers" in cap.strengths

    def test_valid_marketplaces_includes_new(self):
        for m in ["allegro", "olx", "stockx"]:
            assert m in VALID_MARKETPLACES

    def test_category_routing_includes_new_marketplaces(self):
        """New marketplaces should appear in relevant category routing."""
        # StockX should be in shoes routing
        shoes_chain = [m for m, r in CATEGORY_ROUTING["shoes"]]
        assert "stockx" in shoes_chain

        # Allegro should be in electronics routing
        elec_chain = [m for m, r in CATEGORY_ROUTING["electronics"]]
        assert "allegro" in elec_chain

        # OLX should be in furniture routing
        furn_chain = [m for m, r in CATEGORY_ROUTING["furniture"]]
        assert "olx" in furn_chain

    # --- Graceful error handling tests ---

    def test_do_search_unsupported_marketplace_returns_error(self):
        """Unsupported marketplace should return SearchResult with error, not raise."""
        p = ApifyProvider()
        params = SearchParams(query="test", category="nonexistent_marketplace")
        result = p._do_search(params)
        assert result.error != ""
        assert "nonexistent_marketplace" in result.error
        assert result.total_found == 0
        assert len(result.items) == 0

    def test_search_result_error_field_default(self):
        """SearchResult.error should default to empty string."""
        from server.types import SearchResult
        result = SearchResult(
            items=[], total_found=0, marketplace="test", query="q"
        )
        assert result.error == ""

    def test_search_result_to_summary_with_error(self):
        """to_summary should show error when present."""
        from server.types import SearchResult
        result = SearchResult(
            items=[], total_found=0, marketplace="test", query="q",
            error="Actor not rented"
        )
        summary = result.to_summary()
        assert "ERROR" in summary
        assert "Actor not rented" in summary

    def test_search_result_to_summary_normal(self):
        """to_summary should show item count when no error."""
        from server.types import SearchResult
        result = SearchResult(
            items=[], total_found=5, marketplace="vinted", query="q",
            duration_ms=150
        )
        summary = result.to_summary()
        assert "vinted" in summary
        assert "150ms" in summary
