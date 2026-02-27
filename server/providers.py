"""Marketplace provider implementations.

Architecture mirrors multi-ai MCP:
- BaseMarketplaceProvider (abstract) with health tracking + circuit breaker
- Concrete providers: Vinted, eBay, Grailed, Vestiaire, Depop (direct API/scraping)
- ApifyProvider: meta-provider for 8 marketplaces via Apify cloud actors
- 9 total marketplaces: Vinted, eBay, Grailed, Vestiaire, Depop + Allegro, OLX, StockX
- Provider registry with lazy initialization
- Category-based smart routing

Adding a new marketplace via Apify:
1. Find the Apify Actor at apify.com/store
2. Add actor ID to ApifyProvider.ACTOR_MAP
3. Add _build_actor_input() case
4. Add _parse_*_result() method
5. Add to MARKETPLACE_REGISTRY, CATEGORY_ROUTING, VALID_MARKETPLACES
"""

import os
import time
import json
import logging
from dataclasses import dataclass, field

from server.types import (
    SearchParams, SearchResult, MarketplaceItem, ItemDetails,
    MarketplaceCapability,
)

logger = logging.getLogger("marketplace.providers")


# =============================================================================
# MARKETPLACE CAPABILITY REGISTRY
# =============================================================================

MARKETPLACE_REGISTRY: dict[str, MarketplaceCapability] = {
    "vinted": MarketplaceCapability(
        categories=["clothing", "shoes", "accessories", "bags", "kids", "home", "electronics"],
        regions=["EU", "UK"],
        has_api=False,
        requires_auth="cookies",
        max_results_per_page=96,
        rate_limit_rpm=15,
        strengths=["fashion", "secondhand", "EU_coverage", "large_inventory"],
        notes="No official API. Uses cookie-based HTTP access via Playwright.",
    ),
    "ebay": MarketplaceCapability(
        categories=["clothing", "shoes", "accessories", "electronics", "furniture", "sports", "general"],
        regions=["US", "UK", "EU", "AU"],
        has_api=True,
        requires_auth="api_key",
        max_results_per_page=200,
        rate_limit_rpm=5000,
        strengths=["global", "everything", "sold_data", "official_api"],
        notes="Official Browse/Finding API. Requires eBay developer credentials.",
    ),
    "grailed": MarketplaceCapability(
        categories=["clothing", "shoes", "accessories", "streetwear", "luxury", "vintage"],
        regions=["US", "EU"],
        has_api=False,
        requires_auth="cookies",
        max_results_per_page=40,
        rate_limit_rpm=20,
        strengths=["menswear", "streetwear", "designer", "archive"],
        notes="No official API. Algolia-based search with cookie auth.",
    ),
    "vestiaire": MarketplaceCapability(
        categories=["luxury", "bags", "clothing", "shoes", "accessories"],
        regions=["EU", "US", "UK"],
        has_api=False,
        requires_auth="cookies",
        max_results_per_page=48,
        rate_limit_rpm=15,
        strengths=["luxury", "authenticated", "bags", "designer"],
        notes="No official API. Luxury-focused with authentication service.",
    ),
    "depop": MarketplaceCapability(
        categories=["clothing", "vintage", "streetwear", "accessories", "shoes"],
        regions=["US", "UK"],
        has_api=False,
        requires_auth="cookies",
        max_results_per_page=24,
        rate_limit_rpm=20,
        strengths=["vintage", "gen_z", "unique", "creative"],
        notes="No official API. Mobile-first marketplace.",
    ),
    "apify": MarketplaceCapability(
        categories=["clothing", "shoes", "accessories", "bags", "streetwear", "luxury", "vintage", "general"],
        regions=["EU", "US"],
        has_api=True,
        requires_auth="api_key",
        max_results_per_page=100,
        rate_limit_rpm=30,
        strengths=["cloud_scraping", "multi_marketplace", "no_cookies_needed", "8_actors"],
        notes="Cloud scraping via Apify Actors. Supports 8 marketplace actors: "
              "Vinted, Grailed, eBay, Vestiaire, Depop, Allegro, OLX, StockX. "
              "Requires APIFY_API_TOKEN.",
    ),
    "allegro": MarketplaceCapability(
        categories=["clothing", "shoes", "electronics", "home", "kids", "sports", "general"],
        regions=["PL", "CZ", "SK", "HU"],
        has_api=True,
        requires_auth="api_key",
        max_results_per_page=60,
        rate_limit_rpm=30,
        strengths=["CEE_coverage", "large_inventory", "electronics", "polish_market"],
        notes="Largest e-commerce in Poland/CEE. Via Apify Actor. "
              "Supports allegro.pl, allegro.cz, allegro.sk.",
    ),
    "olx": MarketplaceCapability(
        categories=["electronics", "furniture", "clothing", "home", "sports", "general"],
        regions=["PL", "UA", "RO", "PT", "BG"],
        has_api=False,
        requires_auth="api_key",
        max_results_per_page=50,
        rate_limit_rpm=30,
        strengths=["classifieds", "local_deals", "CEE_coverage", "diverse_categories"],
        notes="Classifieds marketplace. No search API — via Apify Actor. "
              "Multi-country: Poland, Ukraine, Romania, Portugal, Bulgaria.",
    ),
    "stockx": MarketplaceCapability(
        categories=["shoes", "streetwear", "accessories", "electronics"],
        regions=["US", "EU", "UK"],
        has_api=True,
        requires_auth="api_key",
        max_results_per_page=50,
        rate_limit_rpm=30,
        strengths=["sneakers", "authenticated", "market_data", "bid_ask"],
        notes="Stock exchange for sneakers and collectibles. Bid/Ask system. "
              "Physical authentication. Via Apify Actor.",
    ),
}


# =============================================================================
# CATEGORY ROUTING (like TASK_ROUTING in multi-ai)
# =============================================================================

CATEGORY_ROUTING: dict[str, list[tuple[str, str]]] = {
    # category: [(marketplace, region), ...]
    # "apify" is listed as last fallback — cloud scraping when direct fails
    "clothing":     [("vinted", "EU"), ("grailed", "US"), ("depop", "US"), ("allegro", "PL"), ("ebay", "US"), ("apify", "EU")],
    "shoes":        [("vinted", "EU"), ("stockx", "US"), ("grailed", "US"), ("ebay", "US"), ("depop", "US"), ("apify", "EU")],
    "accessories":  [("vinted", "EU"), ("vestiaire", "EU"), ("grailed", "US"), ("ebay", "US"), ("apify", "EU")],
    "bags":         [("vestiaire", "EU"), ("vinted", "EU"), ("ebay", "US"), ("grailed", "US"), ("apify", "EU")],
    "luxury":       [("vestiaire", "EU"), ("grailed", "US"), ("vinted", "EU"), ("ebay", "US"), ("apify", "EU")],
    "streetwear":   [("grailed", "US"), ("depop", "US"), ("stockx", "US"), ("vinted", "EU"), ("ebay", "US"), ("apify", "US")],
    "vintage":      [("depop", "US"), ("grailed", "US"), ("vinted", "EU"), ("ebay", "US"), ("apify", "EU")],
    "electronics":  [("ebay", "US"), ("allegro", "PL"), ("olx", "PL"), ("vinted", "EU")],
    "furniture":    [("olx", "PL"), ("vinted", "EU"), ("allegro", "PL"), ("ebay", "US")],
    "sports":       [("ebay", "US"), ("allegro", "PL"), ("vinted", "EU"), ("depop", "US")],
    "kids":         [("vinted", "EU"), ("allegro", "PL"), ("ebay", "US"), ("depop", "US")],
    "home":         [("olx", "PL"), ("allegro", "PL"), ("vinted", "EU"), ("ebay", "US")],
    "general":      [("vinted", "EU"), ("ebay", "US"), ("allegro", "PL"), ("olx", "PL"), ("depop", "US"), ("grailed", "US"), ("apify", "EU")],
}


# =============================================================================
# PROVIDER HEALTH TRACKING (same pattern as multi-ai)
# =============================================================================

@dataclass
class ProviderHealth:
    """Track provider health for circuit breaker pattern."""
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    consecutive_failures: int = 0
    total_latency_ms: int = 0
    last_error: str | None = None
    last_error_time: float | None = None
    circuit_open: bool = False
    circuit_open_until: float = 0.0

    @property
    def success_rate(self) -> float:
        if self.total_calls == 0:
            return 1.0
        return self.successful_calls / self.total_calls

    @property
    def avg_latency_ms(self) -> int:
        if self.successful_calls == 0:
            return 0
        return self.total_latency_ms // self.successful_calls

    def record_success(self, latency_ms: int):
        self.total_calls += 1
        self.successful_calls += 1
        self.consecutive_failures = 0
        self.total_latency_ms += latency_ms
        if self.circuit_open:
            self.circuit_open = False
            logger.info("Circuit breaker CLOSED (provider recovered)")

    def record_failure(self, error: str):
        self.total_calls += 1
        self.failed_calls += 1
        self.consecutive_failures += 1
        self.last_error = error
        self.last_error_time = time.monotonic()
        if self.consecutive_failures >= 3 and not self.circuit_open:
            self.circuit_open = True
            self.circuit_open_until = time.monotonic() + 120  # 2min cooldown
            logger.warning("Circuit breaker OPEN (3 consecutive failures)")

    def is_healthy(self) -> bool:
        if not self.circuit_open:
            return True
        if time.monotonic() > self.circuit_open_until:
            return True
        return False


# Global health registry
_health: dict[str, ProviderHealth] = {}


def get_health(provider_name: str) -> ProviderHealth:
    if provider_name not in _health:
        _health[provider_name] = ProviderHealth()
    return _health[provider_name]


def get_all_health() -> dict[str, ProviderHealth]:
    return dict(_health)


# =============================================================================
# BASE MARKETPLACE PROVIDER
# =============================================================================

class BaseMarketplaceProvider:
    """Base class for marketplace providers.

    Enhanced with:
    - Retry with exponential backoff
    - Health tracking + circuit breaker
    - Rate limiting
    - Standardized error handling

    To add a new marketplace:
    1. Subclass this
    2. Set class attributes (name, display_name, etc.)
    3. Implement search() and get_item()
    4. Add to PROVIDER_CLASSES list at bottom of file
    """

    name: str = ""
    display_name: str = ""
    base_url: str = ""
    api_key_env: str = ""

    # Retry config
    max_retries: int = 2
    base_delay: float = 1.0
    max_delay: float = 10.0

    # Rate limit
    min_request_interval: float = 2.0  # seconds between requests

    def __init__(self):
        self._client = None
        self._last_request_time: float = 0  # Instance attr, not class-shared
        api_key = os.environ.get(self.api_key_env, "")
        if not api_key and self.api_key_env:
            logger.warning(f"{self.name}: {self.api_key_env} not set")
        self._api_key = api_key
        self._init_client()

    def _init_client(self):
        """Initialize HTTP client. Override for custom setup."""
        try:
            import httpx
            self._client = httpx.Client(
                timeout=30.0,
                follow_redirects=True,
                headers={"User-Agent": self._get_user_agent()},
            )
        except ImportError:
            logger.warning("httpx not installed, using urllib")
            self._client = None

    def _get_user_agent(self) -> str:
        """Realistic browser user agent."""
        return (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        )

    def is_available(self) -> bool:
        """Check if provider has required credentials."""
        if not self.api_key_env:
            return True  # No auth needed
        return bool(self._api_key)

    def _rate_limit(self):
        """Enforce rate limiting between requests."""
        now = time.monotonic()
        elapsed = now - self._last_request_time
        if elapsed < self.min_request_interval:
            time.sleep(self.min_request_interval - elapsed)
        self._last_request_time = time.monotonic()

    def search(
        self,
        params: SearchParams,
    ) -> SearchResult:
        """Search marketplace with retry and health tracking.

        Subclasses implement _do_search() for the actual API call.
        This method handles retry, health, rate limiting.
        """
        if not self.is_available():
            raise RuntimeError(
                f"{self.name} is not configured. "
                f"Set {self.api_key_env} environment variable."
            )

        health = get_health(self.name)
        if not health.is_healthy():
            raise RuntimeError(
                f"{self.name} circuit breaker is OPEN "
                f"(consecutive failures: {health.consecutive_failures}). "
                f"Retry in {int(health.circuit_open_until - time.monotonic())}s."
            )

        last_error = None
        for attempt in range(self.max_retries):
            self._rate_limit()
            start = time.monotonic()
            try:
                result = self._do_search(params)
                duration_ms = int((time.monotonic() - start) * 1000)
                result.duration_ms = duration_ms
                health.record_success(duration_ms)
                return result

            except Exception as e:
                last_error = e
                error_str = str(e)

                is_retryable = any(kw in error_str.lower() for kw in [
                    "rate limit", "429", "500", "502", "503", "504",
                    "connection", "timeout", "overloaded",
                ])

                if not is_retryable or attempt == self.max_retries - 1:
                    health.record_failure(error_str)
                    logger.error(
                        f"{self.name} search error (attempt {attempt + 1}): {e}"
                    )
                    raise

                delay = min(self.base_delay * (2 ** attempt), self.max_delay)
                logger.warning(
                    f"{self.name} retryable error: {error_str[:100]}. "
                    f"Retrying in {delay:.1f}s..."
                )
                time.sleep(delay)

        health.record_failure(str(last_error))
        raise last_error

    def get_item(self, item_id: str) -> ItemDetails | None:
        """Get detailed item info with retry and health tracking.

        Subclasses implement _do_get_item() for the actual API call.
        """
        if not self.is_available():
            return None

        health = get_health(self.name)
        if not health.is_healthy():
            return None

        self._rate_limit()
        start = time.monotonic()
        try:
            result = self._do_get_item(item_id)
            duration_ms = int((time.monotonic() - start) * 1000)
            health.record_success(duration_ms)
            return result
        except Exception as e:
            health.record_failure(str(e))
            logger.error(f"{self.name} get_item error: {e}")
            return None

    def get_item_url(self, item_id: str) -> str:
        """Construct item URL from ID. Override per marketplace."""
        return f"{self.base_url}/item/{item_id}"

    # --- Abstract methods for subclasses ---

    def _do_search(self, params: SearchParams) -> SearchResult:
        """Actual search implementation. Override in subclass."""
        raise NotImplementedError(f"{self.name}._do_search() not implemented")

    def _do_get_item(self, item_id: str) -> ItemDetails | None:
        """Actual get_item implementation. Override in subclass."""
        raise NotImplementedError(f"{self.name}._do_get_item() not implemented")


# =============================================================================
# VINTED PROVIDER
# =============================================================================

class VintedProvider(BaseMarketplaceProvider):
    """Vinted marketplace — cookie-based HTTP access.

    No official API. Uses cookies obtained via Playwright browser automation.
    Cookies are refreshed automatically when expired (25-minute TTL).

    Auth: Set VINTED_COOKIE env var with a valid session cookie string,
    OR leave empty to auto-obtain via Playwright (requires playwright installed).

    Domain support: vinted.fr, vinted.de, vinted.it, vinted.es, vinted.nl,
    vinted.be, vinted.co.uk, vinted.pl, vinted.pt, vinted.cz, vinted.lt
    """
    name = "vinted"
    display_name = "Vinted"
    base_url = "https://www.vinted.fr"
    api_key_env = "VINTED_COOKIE"  # Cookie string or empty for auto-obtain

    min_request_interval = 3.0  # Vinted rate limits aggressively

    # Domains and locales
    DOMAINS = {
        "fr": {"url": "https://www.vinted.fr", "locale": "fr", "tz": "Europe/Paris"},
        "de": {"url": "https://www.vinted.de", "locale": "de", "tz": "Europe/Berlin"},
        "it": {"url": "https://www.vinted.it", "locale": "it", "tz": "Europe/Rome"},
        "es": {"url": "https://www.vinted.es", "locale": "es", "tz": "Europe/Madrid"},
        "nl": {"url": "https://www.vinted.nl", "locale": "nl", "tz": "Europe/Amsterdam"},
        "be": {"url": "https://www.vinted.be", "locale": "fr", "tz": "Europe/Brussels"},
        "uk": {"url": "https://www.vinted.co.uk", "locale": "en", "tz": "Europe/London"},
        "pl": {"url": "https://www.vinted.pl", "locale": "pl", "tz": "Europe/Warsaw"},
    }

    # Condition mapping
    CONDITIONS = {
        "new_with_tags": 6,
        "new_without_tags": 1,
        "very_good": 2,
        "good": 3,
        "fair": 4,
    }

    def __init__(self):
        super().__init__()
        domain_key = os.environ.get("VINTED_DOMAIN", "fr")
        domain_info = self.DOMAINS.get(domain_key, self.DOMAINS["fr"])
        self.base_url = domain_info["url"]
        self._cookies = self._api_key or ""
        self._cookie_obtained_at = 0.0
        self._cookie_ttl = 25 * 60  # 25 minutes

    def is_available(self) -> bool:
        """Vinted is available if we have cookies or Playwright is installed."""
        if self._api_key:
            return True
        # Check if Playwright is available for auto-obtain
        try:
            import playwright  # noqa: F401
            return True
        except ImportError:
            return False

    def _needs_cookie_refresh(self) -> bool:
        """Check if cookies need refreshing."""
        if not self._cookies:
            return True
        elapsed = time.monotonic() - self._cookie_obtained_at
        return elapsed > self._cookie_ttl

    def _refresh_cookies(self):
        """Obtain fresh cookies via Playwright or use env var."""
        if self._api_key:
            # User provided cookie string
            self._cookies = self._api_key
            self._cookie_obtained_at = time.monotonic()
            return

        # Auto-obtain via Playwright
        try:
            self._cookies = self._obtain_cookies_playwright()
            self._cookie_obtained_at = time.monotonic()
            logger.info(f"Vinted cookies refreshed (TTL: {self._cookie_ttl}s)")
        except Exception as e:
            logger.error(f"Failed to obtain Vinted cookies: {e}")
            raise RuntimeError(
                f"Cannot obtain Vinted cookies. Either:\n"
                f"1. Set VINTED_COOKIE env var with valid cookie string\n"
                f"2. Install playwright: pip install playwright && playwright install chromium\n"
                f"Error: {e}"
            )

    def _obtain_cookies_playwright(self) -> str:
        """Use Playwright to obtain Vinted session cookies."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise RuntimeError(
                "Playwright not installed. Run:\n"
                "pip install playwright && playwright install chromium"
            )

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                ],
            )
            context = browser.new_context(
                user_agent=self._get_user_agent(),
                viewport={"width": 1920, "height": 1080},
                locale="fr-FR",
                timezone_id="Europe/Paris",
            )

            page = context.new_page()

            # Stealth patches
            page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => false});
                window.chrome = { runtime: {} };
            """)

            page.goto(self.base_url, wait_until="domcontentloaded", timeout=30000)

            # Accept cookies banner if present
            try:
                accept_btn = page.locator('[id*="accept"], [class*="accept"]').first
                if accept_btn.is_visible(timeout=3000):
                    accept_btn.click()
                    page.wait_for_timeout(1000)
            except Exception:
                pass

            page.wait_for_timeout(3000)  # Let cookies settle

            # Extract cookies
            cookies = context.cookies()
            cookie_string = "; ".join(
                f"{c['name']}={c['value']}"
                for c in cookies
                if "vinted" in c.get("domain", "") or "datadome" in c.get("domain", "")
            )

            browser.close()

            if not cookie_string:
                raise RuntimeError("No Vinted cookies obtained from browser")

            return cookie_string

    def _api_request(self, path: str, params: dict | None = None) -> dict:
        """Make authenticated API request to Vinted."""
        if self._needs_cookie_refresh():
            self._refresh_cookies()

        url = f"{self.base_url}/api/v2{path}"
        headers = {
            "Cookie": self._cookies,
            "Accept": "application/json, text/plain, */*",
            "User-Agent": self._get_user_agent(),
            "X-Requested-With": "XMLHttpRequest",
        }

        if self._client:
            response = self._client.get(url, params=params, headers=headers)
            if response.status_code == 401 or response.status_code == 403:
                # Cookie expired — force refresh and retry once
                self._cookies = ""
                self._refresh_cookies()
                headers["Cookie"] = self._cookies
                response = self._client.get(url, params=params, headers=headers)

            response.raise_for_status()
            return response.json()
        else:
            # Fallback to urllib
            import urllib.request
            import urllib.parse
            if params:
                url += "?" + urllib.parse.urlencode(params, doseq=True)
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())

    def _do_search(self, params: SearchParams) -> SearchResult:
        """Search Vinted catalog."""
        api_params: dict = {
            "search_text": params.query,
            "per_page": min(params.limit, 96),
            "page": params.page,
        }

        if params.sort:
            sort_map = {
                "relevance": "relevance",
                "price_asc": "price_low_to_high",
                "price_desc": "price_high_to_low",
                "newest": "newest_first",
            }
            api_params["order"] = sort_map.get(params.sort, "relevance")

        if params.min_price > 0:
            api_params["price_from"] = params.min_price
        if params.max_price > 0:
            api_params["price_to"] = params.max_price

        if params.brand:
            # Vinted uses brand_ids, but text search works too
            api_params["search_text"] = f"{params.brand} {params.query}".strip()

        if params.condition:
            cond_id = self.CONDITIONS.get(params.condition)
            if cond_id:
                api_params["status_ids[]"] = [cond_id]

        data = self._api_request("/catalog/items", api_params)

        items = []
        for raw in data.get("items", []):
            price_data = raw.get("price", {})
            price = float(price_data.get("amount", "0")) if isinstance(price_data, dict) else 0

            photo = raw.get("photo", {})
            image_url = ""
            if photo:
                image_url = photo.get("full_size_url") or photo.get("url", "")

            user = raw.get("user", {})

            items.append(MarketplaceItem(
                item_id=str(raw.get("id", "")),
                marketplace="vinted",
                title=raw.get("title", ""),
                url=f"{self.base_url}{raw.get('path', '')}",
                price=price,
                currency=price_data.get("currency_code", "EUR") if isinstance(price_data, dict) else "EUR",
                brand=raw.get("brand_title", ""),
                size=raw.get("size_title", ""),
                condition="",  # Need status_id mapping
                image_url=image_url,
                seller_name=user.get("login", ""),
                seller_id=str(user.get("id", "")),
                favorites=raw.get("favourite_count", 0),
                views=raw.get("view_count", 0),
            ))

        total = data.get("pagination", {}).get("total_entries", len(items))
        pages = data.get("pagination", {}).get("total_pages", 1)

        return SearchResult(
            items=items,
            total_found=total,
            marketplace="vinted",
            query=params.query,
            page=params.page,
            pages_total=pages,
        )

    def _do_get_item(self, item_id: str) -> ItemDetails | None:
        """Get detailed Vinted item info."""
        data = self._api_request(f"/items/{item_id}")
        raw = data.get("item", data)

        if not raw:
            return None

        price_data = raw.get("price", {})
        price = float(price_data.get("amount", "0")) if isinstance(price_data, dict) else 0
        user = raw.get("user", {})

        photos = []
        for p in raw.get("photos", []):
            url = p.get("full_size_url") or p.get("url", "")
            if url:
                photos.append(url)

        item = MarketplaceItem(
            item_id=str(raw.get("id", "")),
            marketplace="vinted",
            title=raw.get("title", ""),
            url=f"{self.base_url}/items/{item_id}",
            price=price,
            currency=price_data.get("currency_code", "EUR") if isinstance(price_data, dict) else "EUR",
            brand=raw.get("brand_title", ""),
            size=raw.get("size_title", ""),
            description=raw.get("description", ""),
            image_url=photos[0] if photos else "",
            image_urls=photos,
            seller_name=user.get("login", ""),
            seller_id=str(user.get("id", "")),
            favorites=raw.get("favourite_count", 0),
            views=raw.get("view_count", 0),
        )

        return ItemDetails(
            item=item,
            description=raw.get("description", ""),
            all_photos=photos,
            seller_total_items=user.get("item_count", 0),
            raw_data=raw,
        )

    def get_item_url(self, item_id: str) -> str:
        return f"{self.base_url}/items/{item_id}"


# =============================================================================
# EBAY PROVIDER
# =============================================================================

class EbayProvider(BaseMarketplaceProvider):
    """eBay marketplace — official Browse API.

    Uses eBay Browse API (v1) for searching items.
    Auth: Set EBAY_API_KEY env var with your Application token (Client ID).
    Optionally set EBAY_APP_SECRET for OAuth token generation.

    API docs: https://developer.ebay.com/api-docs/buy/browse/overview.html
    """
    name = "ebay"
    display_name = "eBay"
    base_url = "https://api.ebay.com"
    api_key_env = "EBAY_API_KEY"

    min_request_interval = 0.5  # eBay API is generous

    # eBay marketplace IDs
    MARKETPLACES = {
        "US": "EBAY_US",
        "UK": "EBAY_GB",
        "DE": "EBAY_DE",
        "FR": "EBAY_FR",
        "IT": "EBAY_IT",
        "ES": "EBAY_ES",
        "AU": "EBAY_AU",
    }

    def __init__(self):
        super().__init__()
        self._oauth_token = ""
        self._oauth_expires = 0.0
        self._app_secret = os.environ.get("EBAY_APP_SECRET", "")

    def _get_oauth_token(self) -> str:
        """Get OAuth application access token."""
        if self._oauth_token and time.monotonic() < self._oauth_expires:
            return self._oauth_token

        if not self._api_key or not self._app_secret:
            # Use API key directly as bearer token
            return self._api_key

        import base64
        credentials = base64.b64encode(
            f"{self._api_key}:{self._app_secret}".encode()
        ).decode()

        if self._client:
            response = self._client.post(
                "https://api.ebay.com/identity/v1/oauth2/token",
                headers={
                    "Authorization": f"Basic {credentials}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={
                    "grant_type": "client_credentials",
                    "scope": "https://api.ebay.com/oauth/api_scope",
                },
            )
            response.raise_for_status()
            data = response.json()
            self._oauth_token = data["access_token"]
            self._oauth_expires = time.monotonic() + data.get("expires_in", 7200) - 60
            return self._oauth_token

        return self._api_key

    def _do_search(self, params: SearchParams) -> SearchResult:
        """Search eBay Browse API."""
        token = self._get_oauth_token()
        region = params.region.upper() if params.region else "US"
        marketplace_id = self.MARKETPLACES.get(region, "EBAY_US")

        # Build query
        query_parts = [params.query]
        if params.brand:
            query_parts.insert(0, params.brand)
        q = " ".join(query_parts)

        api_params = {
            "q": q,
            "limit": min(params.limit, 200),
            "offset": (params.page - 1) * params.limit,
        }

        # Price filter
        filters = []
        if params.min_price > 0:
            filters.append(f"price:[{params.min_price}..{params.max_price or ''}],"
                          f"priceCurrency:{'USD' if region == 'US' else 'EUR'}")
        elif params.max_price > 0:
            filters.append(f"price:[..{params.max_price}],"
                          f"priceCurrency:{'USD' if region == 'US' else 'EUR'}")

        # Condition filter
        if params.condition:
            cond_map = {
                "new_with_tags": "NEW",
                "new_without_tags": "NEW",
                "like_new": "USED_EXCELLENT",
                "very_good": "USED_VERY_GOOD",
                "good": "USED_GOOD",
                "fair": "USED_ACCEPTABLE",
            }
            ebay_cond = cond_map.get(params.condition)
            if ebay_cond:
                filters.append(f"conditions:{{{ebay_cond}}}")

        if filters:
            api_params["filter"] = ",".join(filters)

        # Sort
        sort_map = {
            "relevance": "BEST_MATCH",
            "price_asc": "PRICE",
            "price_desc": "-PRICE",
            "newest": "NEWLY_LISTED",
        }
        api_params["sort"] = sort_map.get(params.sort, "BEST_MATCH")

        headers = {
            "Authorization": f"Bearer {token}",
            "X-EBAY-C-MARKETPLACE-ID": marketplace_id,
            "Accept": "application/json",
        }

        if self._client:
            response = self._client.get(
                f"{self.base_url}/buy/browse/v1/item_summary/search",
                params=api_params,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()
        else:
            import urllib.request
            import urllib.parse
            url = f"{self.base_url}/buy/browse/v1/item_summary/search?"
            url += urllib.parse.urlencode(api_params)
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())

        items = []
        for raw in data.get("itemSummaries", []):
            price_data = raw.get("price", {})
            price = float(price_data.get("value", "0"))

            image = raw.get("image", {})
            image_url = image.get("imageUrl", "")

            seller = raw.get("seller", {})

            items.append(MarketplaceItem(
                item_id=raw.get("itemId", ""),
                marketplace="ebay",
                title=raw.get("title", ""),
                url=raw.get("itemWebUrl", ""),
                price=price,
                currency=price_data.get("currency", "USD"),
                condition=raw.get("condition", ""),
                image_url=image_url,
                seller_name=seller.get("username", ""),
                seller_rating=float(seller.get("feedbackPercentage", "0")),
                location=raw.get("itemLocation", {}).get("country", ""),
            ))

        total = data.get("total", len(items))

        return SearchResult(
            items=items,
            total_found=total,
            marketplace="ebay",
            query=params.query,
            page=params.page,
        )

    def _do_get_item(self, item_id: str) -> ItemDetails | None:
        """Get detailed eBay item via Browse API."""
        token = self._get_oauth_token()

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

        if self._client:
            # eBay item IDs need URL encoding (they contain | characters)
            response = self._client.get(
                f"{self.base_url}/buy/browse/v1/item/{item_id}",
                headers=headers,
            )
            response.raise_for_status()
            raw = response.json()
        else:
            return None

        price_data = raw.get("price", {})
        price = float(price_data.get("value", "0"))

        images = []
        main_image = raw.get("image")
        if isinstance(main_image, dict) and main_image.get("imageUrl"):
            images.append(main_image["imageUrl"])

        # Additional images
        for img in raw.get("additionalImages", []):
            url = img.get("imageUrl", "")
            if url and url not in images:
                images.append(url)

        seller = raw.get("seller", {})

        item = MarketplaceItem(
            item_id=item_id,
            marketplace="ebay",
            title=raw.get("title", ""),
            url=raw.get("itemWebUrl", ""),
            price=price,
            currency=price_data.get("currency", "USD"),
            condition=raw.get("condition", ""),
            description=raw.get("shortDescription", ""),
            image_url=images[0] if images else "",
            image_urls=images,
            seller_name=seller.get("username", ""),
            seller_rating=float(seller.get("feedbackPercentage", "0")),
        )

        return ItemDetails(
            item=item,
            description=raw.get("description", ""),
            all_photos=images,
            seller_verified=seller.get("feedbackScore", 0) > 100,
            raw_data=raw,
        )

    def get_item_url(self, item_id: str) -> str:
        return f"https://www.ebay.com/itm/{item_id}"


# =============================================================================
# GRAILED PROVIDER
# =============================================================================

class GrailedProvider(BaseMarketplaceProvider):
    """Grailed marketplace — Algolia-powered search.

    Uses Grailed's Algolia search backend. No official API.
    Auth: Set GRAILED_ALGOLIA_KEY env var, or leave empty to try
    fetching the public Algolia credentials from the site.

    Focused on: menswear, streetwear, designer, archive fashion.
    """
    name = "grailed"
    display_name = "Grailed"
    base_url = "https://www.grailed.com"
    api_key_env = "GRAILED_ALGOLIA_KEY"

    min_request_interval = 2.0

    # Known Algolia config (may change)
    ALGOLIA_APP_ID = "MNRWEFSS2Q"
    ALGOLIA_INDEX = "Listing_production"

    def _do_search(self, params: SearchParams) -> SearchResult:
        """Search Grailed via Algolia."""
        algolia_key = self._api_key or self._fetch_algolia_key()
        if not algolia_key:
            raise RuntimeError(
                "Grailed Algolia key not available. "
                "Set GRAILED_ALGOLIA_KEY env var."
            )

        url = f"https://{self.ALGOLIA_APP_ID}-dsn.algolia.net/1/indexes/{self.ALGOLIA_INDEX}/query"
        headers = {
            "X-Algolia-Application-Id": self.ALGOLIA_APP_ID,
            "X-Algolia-API-Key": algolia_key,
            "Content-Type": "application/json",
        }

        # Build Algolia query
        algolia_params = {
            "query": f"{params.brand} {params.query}".strip() if params.brand else params.query,
            "hitsPerPage": min(params.limit, 40),
            "page": params.page - 1,  # Algolia is 0-indexed
        }

        # Filters
        filters = ["strata:grailed OR strata:hype OR strata:sartorial OR strata:core"]
        if params.min_price > 0 or params.max_price > 0:
            price_filter = ""
            if params.min_price > 0 and params.max_price > 0:
                price_filter = f"price_i >= {int(params.min_price)} AND price_i <= {int(params.max_price)}"
            elif params.min_price > 0:
                price_filter = f"price_i >= {int(params.min_price)}"
            else:
                price_filter = f"price_i <= {int(params.max_price)}"
            filters.append(price_filter)

        algolia_params["filters"] = " AND ".join(f"({f})" for f in filters)

        body = json.dumps(algolia_params).encode()

        if self._client:
            response = self._client.post(url, headers=headers, content=body)
            response.raise_for_status()
            data = response.json()
        else:
            import urllib.request
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())

        items = []
        for hit in data.get("hits", []):
            photos = hit.get("photos", [])
            image_url = ""
            if photos:
                image_url = photos[0].get("url", "") if isinstance(photos[0], dict) else str(photos[0])

            items.append(MarketplaceItem(
                item_id=str(hit.get("id", "")),
                marketplace="grailed",
                title=hit.get("title", ""),
                url=f"https://www.grailed.com/listings/{hit.get('id', '')}",
                price=float(hit.get("price_i", 0)),
                currency="USD",
                brand=hit.get("designer_names", [""])[0] if hit.get("designer_names") else "",
                size=hit.get("size", ""),
                condition=hit.get("condition", ""),
                category=hit.get("category_path", ""),
                image_url=image_url,
                seller_name=hit.get("user", {}).get("username", "") if isinstance(hit.get("user"), dict) else "",
            ))

        total = data.get("nbHits", len(items))
        pages = data.get("nbPages", 1)

        return SearchResult(
            items=items,
            total_found=total,
            marketplace="grailed",
            query=params.query,
            page=params.page,
            pages_total=pages,
        )

    def _fetch_algolia_key(self) -> str:
        """Try to fetch Algolia key from Grailed's frontend."""
        try:
            if self._client:
                resp = self._client.get("https://www.grailed.com")
                # Look for Algolia key in page source
                text = resp.text
                import re
                match = re.search(r'algoliaApiKey["\s:]+(["\'])([a-f0-9]+)\1', text)
                if match:
                    return match.group(2)
        except Exception as e:
            logger.warning(f"Failed to fetch Grailed Algolia key: {e}")
        return ""

    def _do_get_item(self, item_id: str) -> ItemDetails | None:
        """Get Grailed listing details."""
        # Grailed doesn't have a clean API for individual items
        # Use Algolia to fetch by ID
        return None

    def get_item_url(self, item_id: str) -> str:
        return f"https://www.grailed.com/listings/{item_id}"


# =============================================================================
# VESTIAIRE PROVIDER
# =============================================================================

class VestiaireProvider(BaseMarketplaceProvider):
    """Vestiaire Collective — luxury resale marketplace.

    No official API. Uses their internal search endpoints.
    Auth: Set VESTIAIRE_COOKIE env var with valid session cookie.

    Focused on: luxury bags, designer clothing, authenticated items.
    """
    name = "vestiaire"
    display_name = "Vestiaire Collective"
    base_url = "https://www.vestiairecollective.com"
    api_key_env = "VESTIAIRE_COOKIE"

    min_request_interval = 3.0

    def _do_search(self, params: SearchParams) -> SearchResult:
        """Search Vestiaire Collective."""
        url = f"{self.base_url}/search/"
        api_params = {
            "q": f"{params.brand} {params.query}".strip() if params.brand else params.query,
            "page": params.page,
        }

        if params.min_price > 0:
            api_params["priceMin"] = int(params.min_price)
        if params.max_price > 0:
            api_params["priceMax"] = int(params.max_price)

        headers = {
            "User-Agent": self._get_user_agent(),
            "Accept": "application/json",
        }
        if self._api_key:
            headers["Cookie"] = self._api_key

        if self._client:
            response = self._client.get(url, params=api_params, headers=headers)
            response.raise_for_status()

            # Vestiaire may return HTML or JSON depending on endpoint
            content_type = response.headers.get("content-type", "")
            if "json" in content_type:
                data = response.json()
            else:
                # Parse HTML results
                return SearchResult(
                    items=[],
                    total_found=0,
                    marketplace="vestiaire",
                    query=params.query,
                    page=params.page,
                )
        else:
            return SearchResult(
                items=[], total_found=0,
                marketplace="vestiaire", query=params.query,
            )

        items = []
        for raw in data.get("items", data.get("products", [])):
            items.append(MarketplaceItem(
                item_id=str(raw.get("id", "")),
                marketplace="vestiaire",
                title=raw.get("name", raw.get("title", "")),
                url=f"{self.base_url}{raw.get('link', '')}",
                price=float(raw.get("price", {}).get("amount", 0)),
                currency=raw.get("price", {}).get("currency", "EUR"),
                brand=raw.get("brand", {}).get("name", ""),
                condition=raw.get("condition", {}).get("label", ""),
                image_url=raw.get("pictures", [{}])[0].get("url", ""),
                seller_name=raw.get("seller", {}).get("username", ""),
                location=raw.get("seller", {}).get("country", ""),
            ))

        total = data.get("pagination", {}).get("totalItems", len(items))

        return SearchResult(
            items=items,
            total_found=total,
            marketplace="vestiaire",
            query=params.query,
            page=params.page,
        )

    def _do_get_item(self, item_id: str) -> ItemDetails | None:
        return None

    def get_item_url(self, item_id: str) -> str:
        return f"{self.base_url}/product/{item_id}"


# =============================================================================
# DEPOP PROVIDER
# =============================================================================

class DepopProvider(BaseMarketplaceProvider):
    """Depop marketplace — Gen-Z vintage/streetwear.

    No official API. Uses their search endpoints.
    Auth: Set DEPOP_COOKIE env var with valid session cookie.

    Focused on: vintage, Y2K, unique finds, creative fashion.
    """
    name = "depop"
    display_name = "Depop"
    base_url = "https://webapi.depop.com"
    api_key_env = "DEPOP_COOKIE"

    min_request_interval = 2.0

    def _do_search(self, params: SearchParams) -> SearchResult:
        """Search Depop."""
        api_params = {
            "what": f"{params.brand} {params.query}".strip() if params.brand else params.query,
            "itemsPerPage": min(params.limit, 24),
            "page": params.page - 1,  # 0-indexed
        }

        if params.min_price > 0:
            api_params["priceMin"] = int(params.min_price)
        if params.max_price > 0:
            api_params["priceMax"] = int(params.max_price)

        sort_map = {
            "relevance": "relevance",
            "price_asc": "priceAscending",
            "price_desc": "priceDescending",
            "newest": "newlyListed",
        }
        api_params["sort"] = sort_map.get(params.sort, "relevance")

        headers = {
            "User-Agent": self._get_user_agent(),
            "Accept": "application/json",
        }
        if self._api_key:
            headers["Cookie"] = self._api_key

        url = f"{self.base_url}/api/v2/search/products/"

        if self._client:
            response = self._client.get(url, params=api_params, headers=headers)
            response.raise_for_status()
            data = response.json()
        else:
            import urllib.request
            import urllib.parse
            full_url = url + "?" + urllib.parse.urlencode(api_params)
            req = urllib.request.Request(full_url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())

        items = []
        for raw in data.get("products", data.get("objects", [])):
            price = float(raw.get("price", {}).get("amount", 0)) if isinstance(raw.get("price"), dict) else float(raw.get("price", 0))

            images = raw.get("pictures", raw.get("images", []))
            image_url = ""
            if images:
                if isinstance(images[0], dict):
                    image_url = images[0].get("url", images[0].get("path", ""))
                else:
                    image_url = str(images[0])

            items.append(MarketplaceItem(
                item_id=str(raw.get("id", raw.get("slug", ""))),
                marketplace="depop",
                title=raw.get("description", raw.get("title", ""))[:100],
                url=f"https://www.depop.com/products/{raw.get('slug', raw.get('id', ''))}",
                price=price,
                currency=raw.get("price", {}).get("currency_code", "USD") if isinstance(raw.get("price"), dict) else "USD",
                brand=raw.get("brand", ""),
                size=raw.get("size", ""),
                condition=raw.get("condition", ""),
                image_url=image_url,
                seller_name=raw.get("seller", {}).get("username", "") if isinstance(raw.get("seller"), dict) else "",
                favorites=raw.get("likes", 0),
            ))

        total = data.get("meta", {}).get("end", len(items))

        return SearchResult(
            items=items,
            total_found=total,
            marketplace="depop",
            query=params.query,
            page=params.page,
        )

    def _do_get_item(self, item_id: str) -> ItemDetails | None:
        return None

    def get_item_url(self, item_id: str) -> str:
        return f"https://www.depop.com/products/{item_id}"


# =============================================================================
# APIFY PROVIDER (meta-provider — uses Apify Actors for any marketplace)
# =============================================================================

class ApifyProvider(BaseMarketplaceProvider):
    """Meta-provider that uses Apify Actors to scrape marketplaces.

    Instead of directly scraping, delegates to Apify cloud scrapers.
    Supports multiple marketplaces via configurable Actor mapping.
    Requires APIFY_API_TOKEN env var.
    Pricing: depends on Apify plan ($29/mo = ~30 Actor runs/day typical).
    """

    name = "apify"
    display_name = "Apify (Cloud Scraping)"
    base_url = "https://api.apify.com/v2"
    api_key_env = "APIFY_API_TOKEN"
    min_request_interval = 1.0  # Apify handles rate limiting

    # Map marketplace → Apify Actor ID
    # Format: "username/actor-name"
    # Selected based on: user count, rating, output richness, cost efficiency
    ACTOR_MAP: dict[str, str] = {
        "vinted": "bebity/vinted-premium-actor",           # 451 users, parameter-based
        "grailed": "vmscrapers/grailed",                   # 43 users, rich output (price_drops, seller_score)
        "ebay": "dtrungtin/ebay-items-scraper",            # 1700 users, 5.0★, 18 countries
        "vestiaire": "parseforge/vestiairecollective-scraper",  # 5.0★, luxury items
        "depop": "consummate_mandala/depop-listing-scraper",    # $0.75/1K, budget-friendly
        "allegro": "tri_angle/allegro-fast-product-scraper",    # 376 users, PL/CZ/SK
        "olx": "ecomscrape/olx-product-search-scraper",        # 5.0★, multi-country classifieds
        "stockx": "ecomscrape/stockx-product-search-scraper",  # 85 users, sneakers/collectibles
    }

    # Max wait time for Actor run (seconds)
    ACTOR_TIMEOUT = 120
    POLL_INTERVAL = 3

    def __init__(self):
        super().__init__()
        self._token = self._api_key

    def is_available(self) -> bool:
        """Available if APIFY_API_TOKEN is set."""
        return bool(self._token)

    def get_supported_marketplaces(self) -> list[str]:
        """Return list of marketplaces this provider can scrape via Apify."""
        return list(self.ACTOR_MAP.keys())

    def _build_actor_input(
        self, marketplace: str, params: SearchParams
    ) -> dict:
        """Build Actor-specific input from SearchParams."""
        if marketplace == "vinted":
            inp: dict = {
                "search": params.query,
                "maxItems": params.limit,
            }
            if params.min_price > 0:
                inp["priceFrom"] = params.min_price
            if params.max_price > 0:
                inp["priceTo"] = params.max_price
            if params.brand:
                inp["brand"] = params.brand
            # Vinted actor uses domain to set country
            domain = os.environ.get("VINTED_DOMAIN", "fr")
            inp["url"] = f"https://www.vinted.{domain}/catalog"
            return inp

        elif marketplace == "grailed":
            # vmscrapers/grailed uses URL-based input (search/category/collection pages)
            import urllib.parse
            query_encoded = urllib.parse.quote_plus(
                f"{params.brand} {params.query}".strip() if params.brand else params.query
            )
            search_url = f"https://www.grailed.com/shop?query={query_encoded}"
            return {
                "startUrls": [{"url": search_url}],
            }

        elif marketplace == "ebay":
            # dtrungtin/ebay-items-scraper uses URL-based input (search pages)
            import urllib.parse
            query_parts = [params.brand, params.query] if params.brand else [params.query]
            query_encoded = urllib.parse.quote_plus(" ".join(p for p in query_parts if p))
            domain_map = {
                "US": "com", "UK": "co.uk", "DE": "de", "FR": "fr",
                "IT": "it", "ES": "es", "AU": "com.au",
            }
            region = params.region.upper() if params.region else "US"
            domain = domain_map.get(region, "com")
            search_url = f"https://www.ebay.{domain}/sch/i.html?_nkw={query_encoded}"
            if params.min_price > 0:
                search_url += f"&_udlo={int(params.min_price)}"
            if params.max_price > 0:
                search_url += f"&_udhi={int(params.max_price)}"
            return {
                "startUrls": [{"url": search_url}],
                "maxItems": params.limit,
            }

        elif marketplace == "vestiaire":
            # parseforge/vestiairecollective-scraper uses URL-based input
            import urllib.parse
            query_parts = [params.brand, params.query] if params.brand else [params.query]
            query_encoded = urllib.parse.quote_plus(" ".join(p for p in query_parts if p))
            search_url = f"https://www.vestiairecollective.com/search/?q={query_encoded}"
            return {
                "startUrls": [search_url],
                "maxItems": params.limit,
            }

        elif marketplace == "depop":
            # consummate_mandala/depop-listing-scraper uses parameter-based input
            search_query = f"{params.brand} {params.query}".strip() if params.brand else params.query
            return {
                "searchQueries": [search_query],
                "maxResults": params.limit,
            }

        elif marketplace == "allegro":
            # tri_angle/allegro-fast-product-scraper — param-based, PL/CZ/SK
            search_query = f"{params.brand} {params.query}".strip() if params.brand else params.query
            domain = "allegro.pl"  # Default to Polish Allegro
            if params.region:
                domain_map = {"PL": "allegro.pl", "CZ": "allegro.cz", "SK": "allegro.sk"}
                domain = domain_map.get(params.region.upper(), "allegro.pl")
            return {
                "search": search_query,
                "searchDomain": domain,
                "maxProducts": params.limit,
            }

        elif marketplace == "olx":
            # ecomscrape/olx-product-search-scraper — URL-based, multi-country
            import urllib.parse
            query_slug = params.query.replace(" ", "-")
            domain_map = {
                "PL": "olx.pl", "UA": "olx.ua", "RO": "olx.ro",
                "PT": "olx.pt", "BG": "olx.bg",
            }
            region = params.region.upper() if params.region else "PL"
            domain = domain_map.get(region, "olx.pl")
            search_url = f"https://www.{domain}/oferty/q-{urllib.parse.quote(query_slug)}/"
            inp: dict = {
                "startUrls": [search_url],
                "maxItems": params.limit,
            }
            if params.min_price > 0:
                inp["priceMin"] = int(params.min_price)
            if params.max_price > 0:
                inp["priceMax"] = int(params.max_price)
            return inp

        elif marketplace == "stockx":
            # ecomscrape/stockx-product-search-scraper — param-based
            search_query = f"{params.brand} {params.query}".strip() if params.brand else params.query
            return {
                "keyword": search_query,
                "maxItems": params.limit,
            }

        else:
            # Generic fallback — most actors accept "search" + "maxItems"
            return {
                "search": params.query,
                "maxItems": params.limit,
            }

    def _parse_vinted_result(self, item: dict) -> MarketplaceItem:
        """Parse Apify Vinted actor output into MarketplaceItem."""
        return MarketplaceItem(
            item_id=str(item.get("id", item.get("item_id", ""))),
            marketplace="vinted",
            title=item.get("title", ""),
            url=item.get("url", item.get("path", "")),
            price=float(item.get("price", item.get("total_item_price", 0))),
            currency=item.get("currency", "EUR"),
            brand=item.get("brand_title", item.get("brand", "")),
            size=item.get("size_title", item.get("size", "")),
            image_url=item.get("photo", item.get("image_url", "")),
            condition=item.get("status", ""),
            location=item.get("city", ""),
            seller_name=item.get("user", {}).get("login", "")
            if isinstance(item.get("user"), dict)
            else str(item.get("user", "")),
        )

    def _parse_grailed_result(self, item: dict) -> MarketplaceItem:
        """Parse Apify Grailed actor output into MarketplaceItem."""
        return MarketplaceItem(
            item_id=str(item.get("id", item.get("listing_id", ""))),
            marketplace="grailed",
            title=item.get("title", item.get("name", "")),
            url=item.get("url", ""),
            price=float(item.get("price", 0)),
            currency=item.get("currency", "USD"),
            brand=item.get("designer", item.get("brand", "")),
            size=item.get("size", ""),
            image_url=item.get("image", item.get("cover_photo", "")),
            condition=item.get("condition", ""),
            seller_name=item.get("seller", {}).get("username", "")
            if isinstance(item.get("seller"), dict)
            else str(item.get("seller", "")),
        )

    def _parse_ebay_result(self, item: dict) -> MarketplaceItem:
        """Parse dtrungtin/ebay-items-scraper output."""
        try:
            price = float(item.get("price", 0))
        except (ValueError, TypeError):
            price = 0.0
        return MarketplaceItem(
            item_id=str(item.get("itemNumber", item.get("id", ""))),
            marketplace="ebay",
            title=item.get("title", ""),
            url=item.get("url", item.get("link", "")),
            price=price,
            currency=item.get("currency", "USD"),
            brand=item.get("brand", ""),
            condition=item.get("condition", item.get("type", "")),
            image_url=item.get("image", item.get("thumbnailUrl", "")),
            seller_name=item.get("seller", ""),
            location=item.get("itemLocation", ""),
        )

    def _parse_vestiaire_result(self, item: dict) -> MarketplaceItem:
        """Parse parseforge/vestiairecollective-scraper output."""
        try:
            price_raw = item.get("price", item.get("salePrice", 0))
            if isinstance(price_raw, dict):
                price = float(price_raw.get("amount", price_raw.get("value", 0)))
            else:
                price = float(price_raw)
        except (ValueError, TypeError):
            price = 0.0
        brand_raw = item.get("brand", item.get("designer", ""))
        if isinstance(brand_raw, dict):
            brand_raw = brand_raw.get("name", "")
        images = item.get("pictures", item.get("images", []))
        image_url = ""
        if images:
            if isinstance(images[0], dict):
                image_url = images[0].get("url", images[0].get("path", ""))
            else:
                image_url = str(images[0])
        return MarketplaceItem(
            item_id=str(item.get("id", item.get("productId", ""))),
            marketplace="vestiaire",
            title=item.get("name", item.get("title", "")),
            url=item.get("url", item.get("link", "")),
            price=price,
            currency=item.get("currency", "EUR"),
            brand=str(brand_raw),
            condition=item.get("condition", ""),
            image_url=image_url,
            seller_name=item.get("seller", {}).get("username", "")
            if isinstance(item.get("seller"), dict) else "",
            location=item.get("seller", {}).get("country", "")
            if isinstance(item.get("seller"), dict) else "",
        )

    def _parse_depop_result(self, item: dict) -> MarketplaceItem:
        """Parse consummate_mandala/depop-listing-scraper output."""
        try:
            price_raw = item.get("price", 0)
            if isinstance(price_raw, dict):
                price = float(price_raw.get("amount", price_raw.get("value", 0)))
            else:
                price = float(price_raw)
        except (ValueError, TypeError):
            price = 0.0
        images = item.get("images", item.get("pictures", []))
        image_url = ""
        if images:
            if isinstance(images[0], dict):
                image_url = images[0].get("url", images[0].get("path", ""))
            else:
                image_url = str(images[0])
        return MarketplaceItem(
            item_id=str(item.get("id", item.get("slug", ""))),
            marketplace="depop",
            title=item.get("description", item.get("title", ""))[:100],
            url=item.get("url", item.get("link", "")),
            price=price,
            currency=item.get("currency", "USD"),
            brand=item.get("brand", ""),
            size=item.get("size", ""),
            condition=item.get("condition", ""),
            image_url=image_url,
            seller_name=item.get("seller", {}).get("username", "")
            if isinstance(item.get("seller"), dict) else "",
            favorites=item.get("likes", 0),
        )

    def _parse_allegro_result(self, item: dict) -> MarketplaceItem:
        """Parse tri_angle/allegro-fast-product-scraper output."""
        try:
            price_raw = item.get("price", item.get("sellingMode", {}).get("price", {}))
            if isinstance(price_raw, dict):
                price = float(price_raw.get("amount", price_raw.get("value", 0)))
            else:
                price = float(price_raw)
        except (ValueError, TypeError):
            price = 0.0
        currency = "PLN"
        if isinstance(item.get("price", None), dict):
            currency = item["price"].get("currency", "PLN")
        images = item.get("images", item.get("photos", []))
        image_url = ""
        if images:
            if isinstance(images[0], dict):
                image_url = images[0].get("url", images[0].get("original", ""))
            else:
                image_url = str(images[0])
        return MarketplaceItem(
            item_id=str(item.get("id", item.get("itemId", ""))),
            marketplace="allegro",
            title=item.get("name", item.get("title", "")),
            url=item.get("url", item.get("link", "")),
            price=price,
            currency=currency,
            brand=item.get("brand", ""),
            condition=item.get("condition", ""),
            image_url=image_url,
            location=item.get("location", item.get("city", "")),
            seller_name=item.get("seller", {}).get("login", "")
            if isinstance(item.get("seller"), dict)
            else str(item.get("seller", "")),
        )

    def _parse_olx_result(self, item: dict) -> MarketplaceItem:
        """Parse ecomscrape/olx-product-search-scraper output."""
        try:
            price_raw = item.get("price", 0)
            if isinstance(price_raw, dict):
                price = float(price_raw.get("amount", price_raw.get("value", 0)))
            elif isinstance(price_raw, str):
                import re
                numbers = re.findall(r'[\d.,]+', price_raw.replace(",", "."))
                price = float(numbers[0]) if numbers else 0.0
            else:
                price = float(price_raw)
        except (ValueError, TypeError):
            price = 0.0
        images = item.get("images", item.get("photos", []))
        image_url = ""
        if images:
            if isinstance(images[0], dict):
                image_url = images[0].get("url", images[0].get("link", ""))
            else:
                image_url = str(images[0])
        return MarketplaceItem(
            item_id=str(item.get("id", item.get("adId", ""))),
            marketplace="olx",
            title=item.get("name", item.get("title", "")),
            url=item.get("url", item.get("link", "")),
            price=price,
            currency=item.get("currency", "PLN"),
            image_url=image_url,
            location=item.get("location", item.get("city", "")),
            seller_name=item.get("seller", {}).get("name", "")
            if isinstance(item.get("seller"), dict) else "",
        )

    def _parse_stockx_result(self, item: dict) -> MarketplaceItem:
        """Parse ecomscrape/stockx-product-search-scraper output."""
        try:
            # StockX has complex pricing — try multiple paths
            price_raw = (
                item.get("retailPrice")
                or item.get("lastSale")
                or item.get("price")
                or item.get("market", {}).get("lastSale", 0)
            )
            if isinstance(price_raw, dict):
                price = float(price_raw.get("amount", 0))
            else:
                price = float(price_raw)
        except (ValueError, TypeError):
            price = 0.0
        images = item.get("images", item.get("media", {}).get("imageUrl", ""))
        if isinstance(images, list):
            image_url = str(images[0]) if images else ""
        elif isinstance(images, str):
            image_url = images
        else:
            image_url = ""
        return MarketplaceItem(
            item_id=str(item.get("id", item.get("urlKey", item.get("styleId", "")))),
            marketplace="stockx",
            title=item.get("name", item.get("title", "")),
            url=item.get("url", item.get("link", "")),
            price=price,
            currency=item.get("currency", "USD"),
            brand=item.get("brand", ""),
            condition=item.get("condition", "New"),
            image_url=image_url,
            category=item.get("category", item.get("productCategory", "")),
        )

    def _parse_generic_result(
        self, item: dict, marketplace: str
    ) -> MarketplaceItem:
        """Generic parser — tries common field names. Handles malformed data."""
        try:
            price = float(item.get("price", 0))
        except (ValueError, TypeError):
            price = 0.0

        return MarketplaceItem(
            item_id=str(
                item.get("id", item.get("item_id", item.get("listing_id", "")))
            ),
            marketplace=marketplace,
            title=item.get("title", item.get("name", "")),
            url=item.get("url", item.get("link", "")),
            price=price,
            currency=item.get("currency", "USD"),
            brand=item.get("brand", item.get("designer", "")),
            size=item.get("size", ""),
            image_url=item.get("image", item.get("photo", item.get("image_url", ""))),
            condition=item.get("condition", ""),
        )

    def _parse_result(self, item: dict, marketplace: str) -> MarketplaceItem:
        """Route to marketplace-specific parser."""
        parsers = {
            "vinted": self._parse_vinted_result,
            "grailed": self._parse_grailed_result,
            "ebay": self._parse_ebay_result,
            "vestiaire": self._parse_vestiaire_result,
            "depop": self._parse_depop_result,
            "allegro": self._parse_allegro_result,
            "olx": self._parse_olx_result,
            "stockx": self._parse_stockx_result,
        }
        parser = parsers.get(marketplace, lambda i: self._parse_generic_result(i, marketplace))
        try:
            return parser(item)
        except Exception as e:
            logger.warning(f"Apify parse error for {marketplace}: {e}")
            return self._parse_generic_result(item, marketplace)

    def _do_search(self, params: SearchParams) -> SearchResult:
        """Run Apify Actor and collect results.

        Uses params.category to determine which marketplace Actor to run.
        E.g. category="vinted" → runs bebity/vinted-premium-actor.
        Defaults to "vinted" if category is empty.
        """
        # Determine which marketplace to search via category field
        marketplace = params.category if params.category else "vinted"

        actor_id = self.ACTOR_MAP.get(marketplace)
        if not actor_id:
            supported = ", ".join(self.ACTOR_MAP.keys())
            raise RuntimeError(
                f"Apify: no Actor configured for '{marketplace}'. "
                f"Supported: {supported}"
            )

        # 1. Start Actor run
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }
        actor_input = self._build_actor_input(marketplace, params)

        start_url = f"{self.base_url}/acts/{actor_id}/runs"
        logger.info(f"Apify: starting {actor_id} for '{params.query}'")

        resp = self._client.post(
            start_url,
            json=actor_input,
            headers=headers,
            timeout=30.0,
        )
        resp.raise_for_status()
        run_data = resp.json().get("data", {})
        run_id = run_data.get("id")
        dataset_id = run_data.get("defaultDatasetId")

        if not run_id:
            raise RuntimeError("Apify: failed to start Actor run")

        # 2. Poll for completion
        status_url = f"{self.base_url}/actor-runs/{run_id}"
        elapsed = 0
        while elapsed < self.ACTOR_TIMEOUT:
            time.sleep(self.POLL_INTERVAL)
            elapsed += self.POLL_INTERVAL

            status_resp = self._client.get(status_url, headers=headers)
            status_resp.raise_for_status()
            status = status_resp.json().get("data", {}).get("status")

            if status == "SUCCEEDED":
                break
            elif status in ("FAILED", "ABORTED", "TIMED-OUT"):
                error_msg = status_resp.json().get("data", {}).get("statusMessage", status)
                raise RuntimeError(f"Apify Actor {status}: {error_msg}")

        if elapsed >= self.ACTOR_TIMEOUT:
            raise RuntimeError(
                f"Apify: Actor timed out after {self.ACTOR_TIMEOUT}s"
            )

        # 3. Fetch results from dataset
        if not dataset_id:
            dataset_id = run_data.get("defaultDatasetId", "")

        items_url = f"{self.base_url}/datasets/{dataset_id}/items"
        items_resp = self._client.get(
            items_url,
            headers=headers,
            params={"limit": params.limit, "format": "json"},
        )
        items_resp.raise_for_status()
        raw_items = items_resp.json()

        # 4. Parse into MarketplaceItems
        items = []
        for raw in raw_items:
            try:
                item = self._parse_result(raw, marketplace)
                if item.title:  # Skip empty items
                    items.append(item)
            except Exception as e:
                logger.warning(f"Apify: skip item parse error: {e}")

        return SearchResult(
            marketplace=f"apify:{marketplace}",
            query=params.query,
            total_found=len(items),
            items=items,
            page=1,
            pages_total=1,
        )

    def _do_get_item(self, item_id: str) -> ItemDetails | None:
        """Apify doesn't support individual item fetch by default."""
        return None

    def get_item_url(self, item_id: str) -> str:
        """Can't construct URL without knowing marketplace."""
        return ""


# =============================================================================
# PROVIDER REGISTRY
# =============================================================================

PROVIDER_CLASSES = [
    VintedProvider,
    EbayProvider,
    GrailedProvider,
    VestiaireProvider,
    DepopProvider,
    ApifyProvider,
]

_providers: dict[str, BaseMarketplaceProvider] | None = None


def get_providers() -> dict[str, BaseMarketplaceProvider]:
    """Get all provider instances (lazy init)."""
    global _providers
    if _providers is None:
        _providers = {}
        for cls in PROVIDER_CLASSES:
            try:
                instance = cls()
                _providers[instance.name] = instance
            except Exception as e:
                logger.error(f"Failed to init {cls.name}: {e}")
    return _providers


def get_provider(name: str) -> BaseMarketplaceProvider:
    """Get a specific provider by name."""
    providers = get_providers()
    if name not in providers:
        available = ", ".join(providers.keys())
        raise ValueError(f"Unknown marketplace '{name}'. Available: {available}")
    return providers[name]


def get_available_providers() -> list[str]:
    """Get names of providers that have credentials configured."""
    return [name for name, p in get_providers().items() if p.is_available()]


def get_best_marketplace_for_category(category: str) -> tuple[str, str] | None:
    """Get best available marketplace for an item category."""
    routes = CATEGORY_ROUTING.get(category, CATEGORY_ROUTING["general"])
    providers = get_providers()
    for marketplace_name, region in routes:
        p = providers.get(marketplace_name)
        if p and p.is_available() and get_health(marketplace_name).is_healthy():
            return (marketplace_name, region)
    return None


VALID_MARKETPLACES = ["vinted", "ebay", "grailed", "vestiaire", "depop", "apify", "allegro", "olx", "stockx"]
