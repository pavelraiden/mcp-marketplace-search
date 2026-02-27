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
    VestiaireProvider, DepopProvider,
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
    def test_all_5_marketplaces_registered(self):
        assert len(MARKETPLACE_REGISTRY) == 5
        expected = {"vinted", "ebay", "grailed", "vestiaire", "depop"}
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
    def test_5_provider_classes(self):
        assert len(PROVIDER_CLASSES) == 5

    def test_all_have_required_attrs(self):
        for cls in PROVIDER_CLASSES:
            assert hasattr(cls, "name")
            assert hasattr(cls, "display_name")
            assert hasattr(cls, "base_url")
            assert hasattr(cls, "api_key_env")
            assert cls.name != "", f"{cls.__name__} has empty name"

    def test_provider_names_match_registry(self):
        provider_names = {cls.name for cls in PROVIDER_CLASSES}
        registry_names = set(MARKETPLACE_REGISTRY.keys())
        assert provider_names == registry_names

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
            else:
                assert p.is_available() is True, f"{p.name} not available"


# =============================================================================
# PROVIDER REGISTRY FUNCTIONS TESTS
# =============================================================================

class TestProviderRegistry:
    # Note: reset_providers autouse fixture handles cleanup

    def test_get_providers_returns_all(self):
        providers = get_providers()
        assert len(providers) == 5
        assert "vinted" in providers
        assert "ebay" in providers

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
