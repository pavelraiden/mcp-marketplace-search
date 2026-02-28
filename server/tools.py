"""MCP tools for marketplace search.

16 tools total:
- 9 search_* tools (6 direct + 3 Apify-only: allegro, olx, stockx)
- 3 orchestrator tools (search_all, search_smart, marketplace_health)
- 2 item tools (get_item, compare_prices)
- 2 utility tools (search_history, list_marketplaces)
"""

import time
import logging
import concurrent.futures
from mcp.server.fastmcp import FastMCP

from server.db import get_db
from server.types import SearchParams
from server.providers import (
    get_provider, get_providers, get_available_providers,
    get_best_marketplace_for_category, get_health, get_all_health,
    VALID_MARKETPLACES, CATEGORY_ROUTING, MARKETPLACE_REGISTRY,
)

logger = logging.getLogger("marketplace.tools")

MAX_OUTPUT_CHARS = 24000


def _format_items(items, max_items: int = 20) -> str:
    """Format marketplace items as a readable table."""
    if not items:
        return "No items found."

    lines = [
        "| # | Title | Price | Brand | Size | Marketplace | Link |",
        "|--:|:------|------:|:------|:-----|:------------|:-----|",
    ]

    for i, item in enumerate(items[:max_items], 1):
        title = item.title[:50] + ("..." if len(item.title) > 50 else "")
        price_str = f"{item.price:.0f} {item.currency}"
        brand = item.brand[:20] if item.brand else "-"
        size = item.size[:10] if item.size else "-"
        link = f"[View]({item.url})" if item.url else "-"
        lines.append(
            f"| {i} | {title} | {price_str} | {brand} | {size} | "
            f"{item.marketplace} | {link} |"
        )

    if len(items) > max_items:
        lines.append(f"\n*...and {len(items) - max_items} more items*")

    return "\n".join(lines)


def _search_marketplace(
    marketplace_name: str,
    query: str,
    brand: str = "",
    min_price: float = 0,
    max_price: float = 0,
    condition: str = "",
    size: str = "",
    sort: str = "relevance",
    limit: int = 20,
    region: str = "",
) -> str:
    """Core search logic shared by all search_* tools."""
    db = get_db()
    provider = get_provider(marketplace_name)

    if not provider.is_available():
        return (
            f"ERROR: {marketplace_name} is not configured.\n"
            f"Set {provider.api_key_env} environment variable."
        )

    params = SearchParams(
        query=query,
        brand=brand,
        min_price=min_price,
        max_price=max_price,
        condition=condition,
        size=size,
        sort=sort,
        limit=limit,
        region=region,
    )

    try:
        result = provider.search(params)
    except Exception as e:
        error_msg = f"ERROR searching {marketplace_name}: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return error_msg

    # Handle graceful errors (e.g. actor-is-not-rented, timeout)
    if result.error:
        return (
            f"## {provider.display_name} Search Error\n\n"
            f"**Query:** {query}\n"
            f"**Error:** {result.error}\n"
        )

    # Save to DB
    search_id = db.save_search(
        query=query,
        marketplace=marketplace_name,
        brand=brand or None,
        min_price=min_price if min_price > 0 else None,
        max_price=max_price if max_price > 0 else None,
        condition=condition or None,
        region=region or None,
        total_results=result.total_found,
        items_returned=len(result.items),
        duration_ms=result.duration_ms,
    )
    if result.items:
        db.save_search_items(search_id, [item.to_dict() for item in result.items])

    # Format output
    output = f"## {provider.display_name} Search Results\n\n"
    output += f"**Query:** {query}"
    if brand:
        output += f" | **Brand:** {brand}"
    if min_price > 0 or max_price > 0:
        output += f" | **Price:** {min_price or '?'}-{max_price or '?'}"
    output += f"\n**Found:** {result.total_found} items | "
    output += f"**Showing:** {len(result.items)} | "
    output += f"**Time:** {result.duration_ms}ms\n"
    output += f"**Search ID:** `{search_id}`\n\n"

    output += _format_items(result.items, max_items=limit)

    if len(output) > MAX_OUTPUT_CHARS:
        output = output[:MAX_OUTPUT_CHARS]
        output += "\n\n[TRUNCATED]"

    return output


# =============================================================================
# TOOL REGISTRATION
# =============================================================================

def register_tools(mcp: FastMCP):
    """Register all 16 tools with the MCP server."""

    # =========================================================================
    # 9 MARKETPLACE SEARCH TOOLS (6 direct + 3 Apify-only)
    # =========================================================================

    @mcp.tool()
    def search_vinted(
        query: str,
        brand: str = "",
        min_price: float = 0,
        max_price: float = 0,
        condition: str = "",
        size: str = "",
        sort: str = "relevance",
        limit: int = 20,
        region: str = "EU",
    ) -> str:
        """Search Vinted marketplace for secondhand items.
        Largest EU secondhand platform. Fashion, shoes, accessories, home, electronics.
        Conditions: new_with_tags, new_without_tags, very_good, good, fair.
        Sort: relevance, price_asc, price_desc, newest.
        Region: EU (default), or specific domain: fr, de, it, es, nl, be, uk, pl."""
        return _search_marketplace(
            "vinted", query, brand, min_price, max_price,
            condition, size, sort, limit, region,
        )

    @mcp.tool()
    def search_ebay(
        query: str,
        brand: str = "",
        min_price: float = 0,
        max_price: float = 0,
        condition: str = "",
        sort: str = "relevance",
        limit: int = 20,
        region: str = "US",
    ) -> str:
        """Search eBay marketplace. Global marketplace for everything.
        Official API with sold item data. Great for electronics, collectibles, general items.
        Conditions: new_with_tags, like_new, very_good, good, fair.
        Sort: relevance, price_asc, price_desc, newest.
        Region: US, UK, DE, FR, IT, ES, AU."""
        return _search_marketplace(
            "ebay", query, brand, min_price, max_price,
            condition, "", sort, limit, region,
        )

    @mcp.tool()
    def search_grailed(
        query: str,
        brand: str = "",
        min_price: float = 0,
        max_price: float = 0,
        sort: str = "relevance",
        limit: int = 20,
    ) -> str:
        """Search Grailed marketplace. Premium menswear and streetwear.
        Designer, archive, streetwear, vintage fashion. US-focused but global shipping.
        Best for: Supreme, Rick Owens, Comme des Garcons, archive fashion.
        Sort: relevance, price_asc, price_desc, newest."""
        return _search_marketplace(
            "grailed", query, brand, min_price, max_price,
            "", "", sort, limit, "US",
        )

    @mcp.tool()
    def search_vestiaire(
        query: str,
        brand: str = "",
        min_price: float = 0,
        max_price: float = 0,
        sort: str = "relevance",
        limit: int = 20,
    ) -> str:
        """Search Vestiaire Collective. Luxury resale with authentication.
        Pre-owned luxury bags, clothing, shoes, accessories.
        Items are authenticated by Vestiaire team.
        Best for: Hermes, Chanel, Louis Vuitton, Dior, Gucci."""
        return _search_marketplace(
            "vestiaire", query, brand, min_price, max_price,
            "", "", sort, limit, "EU",
        )

    @mcp.tool()
    def search_depop(
        query: str,
        brand: str = "",
        min_price: float = 0,
        max_price: float = 0,
        sort: str = "relevance",
        limit: int = 20,
    ) -> str:
        """Search Depop marketplace. Gen-Z vintage and streetwear.
        Unique finds, Y2K fashion, vintage, creative sellers.
        Mobile-first community marketplace.
        Best for: vintage, unique pieces, Y2K, indie brands."""
        return _search_marketplace(
            "depop", query, brand, min_price, max_price,
            "", "", sort, limit, "US",
        )

    @mcp.tool()
    def search_apify(
        query: str,
        target_marketplace: str = "vinted",
        brand: str = "",
        min_price: float = 0,
        max_price: float = 0,
        limit: int = 20,
    ) -> str:
        """Search via Apify cloud scraping (meta-provider for 8 marketplaces).
        Uses Apify Actors to scrape marketplaces in the cloud.
        No cookies/auth needed for target marketplace — only APIFY_API_TOKEN.

        target_marketplace: which marketplace to scrape via Apify.
            Supported: vinted (default), grailed, ebay, vestiaire, depop,
            allegro, olx, stockx.
        limit: max items to return (default 20).

        Primary method for all marketplace scraping. Also serves as fallback
        when direct API access fails (cookies expired, rate limited).
        Requires APIFY_API_TOKEN env var."""
        db = get_db()
        provider = get_provider("apify")

        if not provider.is_available():
            return (
                "ERROR: Apify is not configured.\n"
                "Set APIFY_API_TOKEN environment variable.\n"
                "Get a token at https://console.apify.com/account/integrations"
            )

        # Validate target marketplace
        supported = provider.get_supported_marketplaces()
        if target_marketplace not in supported:
            return (
                f"ERROR: Apify doesn't support '{target_marketplace}' yet.\n"
                f"Supported marketplaces: {', '.join(supported)}"
            )

        # Pass target_marketplace via category field
        params = SearchParams(
            query=query,
            category=target_marketplace,
            brand=brand,
            min_price=min_price,
            max_price=max_price,
            limit=limit,
        )

        try:
            result = provider.search(params)
        except Exception as e:
            error_msg = f"ERROR: Apify search failed for {target_marketplace}: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return error_msg

        # Handle graceful errors (actor-is-not-rented, timeout, etc.)
        if result.error:
            return (
                f"## Apify → {target_marketplace.upper()} Search Error\n\n"
                f"**Query:** {query}\n"
                f"**Error:** {result.error}\n"
            )

        # Save to DB
        search_id = db.save_search(
            query=query,
            marketplace=f"apify:{target_marketplace}",
            brand=brand or None,
            min_price=min_price if min_price > 0 else None,
            max_price=max_price if max_price > 0 else None,
            total_results=result.total_found,
            items_returned=len(result.items),
            duration_ms=result.duration_ms,
        )
        if result.items:
            db.save_search_items(search_id, [item.to_dict() for item in result.items])

        # Format output
        output = f"## Apify → {target_marketplace.upper()} Search Results\n\n"
        output += f"**Query:** {query}"
        if brand:
            output += f" | **Brand:** {brand}"
        if min_price > 0 or max_price > 0:
            output += f" | **Price:** {min_price or '?'}-{max_price or '?'}"
        output += f"\n**Found:** {result.total_found} items | "
        output += f"**Showing:** {len(result.items)} | "
        output += f"**Time:** {result.duration_ms}ms\n"
        output += f"**Provider:** Apify (cloud scraping) | **Search ID:** `{search_id}`\n\n"

        output += _format_items(result.items, max_items=limit)

        if len(output) > MAX_OUTPUT_CHARS:
            output = output[:MAX_OUTPUT_CHARS]
            output += "\n\n[TRUNCATED]"

        return output

    # =========================================================================
    # 3 APIFY-ONLY MARKETPLACE SEARCH TOOLS (Allegro, OLX, StockX)
    # =========================================================================

    def _search_via_apify(
        target_marketplace: str,
        display_name: str,
        query: str,
        brand: str = "",
        min_price: float = 0,
        max_price: float = 0,
        limit: int = 20,
        region: str = "",
    ) -> str:
        """Helper: search a marketplace through Apify meta-provider."""
        db = get_db()
        provider = get_provider("apify")

        if not provider.is_available():
            return (
                "ERROR: Apify is not configured.\n"
                "Set APIFY_API_TOKEN environment variable.\n"
                "Get a token at https://console.apify.com/account/integrations"
            )

        params = SearchParams(
            query=query,
            category=target_marketplace,
            brand=brand,
            min_price=min_price,
            max_price=max_price,
            limit=limit,
            region=region,
        )

        try:
            result = provider.search(params)
        except Exception as e:
            error_msg = f"ERROR: {display_name} search failed: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return error_msg

        # Handle graceful errors (actor-is-not-rented, timeout, etc.)
        if result.error:
            return (
                f"## {display_name} Search Error (via Apify)\n\n"
                f"**Query:** {query}\n"
                f"**Error:** {result.error}\n"
            )

        # Save to DB
        search_id = db.save_search(
            query=query,
            marketplace=f"apify:{target_marketplace}",
            brand=brand or None,
            min_price=min_price if min_price > 0 else None,
            max_price=max_price if max_price > 0 else None,
            total_results=result.total_found,
            items_returned=len(result.items),
            duration_ms=result.duration_ms,
        )
        if result.items:
            db.save_search_items(search_id, [item.to_dict() for item in result.items])

        # Format output
        output = f"## {display_name} Search Results (via Apify)\n\n"
        output += f"**Query:** {query}"
        if brand:
            output += f" | **Brand:** {brand}"
        if min_price > 0 or max_price > 0:
            output += f" | **Price:** {min_price or '?'}-{max_price or '?'}"
        output += f"\n**Found:** {result.total_found} items | "
        output += f"**Showing:** {len(result.items)} | "
        output += f"**Time:** {result.duration_ms}ms\n"
        output += f"**Search ID:** `{search_id}`\n\n"

        output += _format_items(result.items, max_items=limit)

        if len(output) > MAX_OUTPUT_CHARS:
            output = output[:MAX_OUTPUT_CHARS]
            output += "\n\n[TRUNCATED]"

        return output

    @mcp.tool()
    def search_allegro(
        query: str,
        brand: str = "",
        min_price: float = 0,
        max_price: float = 0,
        limit: int = 20,
        region: str = "PL",
    ) -> str:
        """Search Allegro — largest e-commerce in Poland/CEE.
        Millions of listings: fashion, electronics, home, kids, sports.
        Powered by Apify cloud scraping. Requires APIFY_API_TOKEN.
        Region: PL (default), CZ, SK, HU."""
        return _search_via_apify(
            "allegro", "Allegro", query, brand,
            min_price, max_price, limit, region,
        )

    @mcp.tool()
    def search_olx(
        query: str,
        brand: str = "",
        min_price: float = 0,
        max_price: float = 0,
        limit: int = 20,
        region: str = "PL",
    ) -> str:
        """Search OLX classifieds — local deals in CEE/Europe.
        Multi-country classifieds: electronics, furniture, clothing, everything.
        Powered by Apify cloud scraping. Requires APIFY_API_TOKEN.
        Region: PL (default), UA, RO, PT, BG."""
        return _search_via_apify(
            "olx", "OLX", query, brand,
            min_price, max_price, limit, region,
        )

    @mcp.tool()
    def search_stockx(
        query: str,
        brand: str = "",
        min_price: float = 0,
        max_price: float = 0,
        limit: int = 20,
    ) -> str:
        """Search StockX — stock exchange for sneakers and collectibles.
        Bid/Ask system with physical authentication guarantee.
        Categories: sneakers, shoes, apparel, accessories, collectibles, electronics.
        Powered by Apify cloud scraping. Requires APIFY_API_TOKEN.
        Best for: Jordan, Yeezy, Nike Dunk, Supreme, trading cards."""
        return _search_via_apify(
            "stockx", "StockX", query, brand,
            min_price, max_price, limit,
        )

    # =========================================================================
    # 3 ORCHESTRATOR TOOLS
    # =========================================================================

    @mcp.tool()
    def search_all(
        query: str,
        brand: str = "",
        min_price: float = 0,
        max_price: float = 0,
        marketplaces: str = "",
        limit: int = 10,
    ) -> str:
        """Search MULTIPLE marketplaces in parallel and compare results.
        Returns combined results from all available marketplaces.
        Use for price comparison or finding best deals across platforms.

        marketplaces: comma-separated (e.g. "ebay,grailed,vestiaire").
                      Leave empty to search all available.
                      Supports both direct providers and Apify cloud actors.
        limit: items per marketplace (default 10)."""
        all_providers = get_providers()
        available = get_available_providers()

        if not available:
            return "ERROR: No marketplaces configured. Set at least one API key."

        # Apify provider for fallback cloud scraping
        apify_provider = all_providers.get("apify")
        apify_available = apify_provider and apify_provider.is_available()
        apify_marketplaces = apify_provider.get_supported_marketplaces() if apify_available else []

        # Parse marketplace list
        if marketplaces:
            requested = [m.strip() for m in marketplaces.split(",") if m.strip()]
            invalid = [m for m in requested if m not in VALID_MARKETPLACES]
            if invalid:
                return f"ERROR: Unknown marketplace(s): {', '.join(invalid)}"
            # Accept marketplaces that have direct provider OR can be reached via Apify
            target = [
                m for m in requested
                if m in available or (m in apify_marketplaces and apify_available)
            ]
            if not target:
                return f"ERROR: None of requested marketplaces configured. Available: {', '.join(available)}"
        else:
            # Default: all available direct + all Apify-supported marketplaces
            target = list(set(available) | (set(apify_marketplaces) if apify_available else set()))
            # Remove 'apify' meta-provider itself from target list
            target = [m for m in target if m != "apify"]

        # Build search params (category is set per-marketplace for Apify routing)
        base_params = SearchParams(
            query=query, brand=brand,
            min_price=min_price, max_price=max_price,
            limit=limit,
        )

        # Search all in parallel
        # Timeout 120s because Apify actors can take 30-60s each
        TIMEOUT = 120
        results = {}
        start_all = time.monotonic()

        def _call_one(mname):
            """Search a marketplace via direct provider or Apify fallback."""
            try:
                provider = all_providers.get(mname)
                if provider and provider.is_available():
                    # Direct provider available — use it
                    result = provider.search(base_params)
                    return (mname, result, None)
                elif apify_available and mname in apify_marketplaces:
                    # Fallback to Apify cloud actor
                    apify_params = SearchParams(
                        query=query, category=mname, brand=brand,
                        min_price=min_price, max_price=max_price,
                        limit=limit,
                    )
                    result = apify_provider.search(apify_params)
                    return (mname, result, None)
                else:
                    return (mname, None, f"Not configured")
            except Exception as e:
                return (mname, None, str(e))

        with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(target), 5)) as executor:
            futures = {
                executor.submit(_call_one, m): m
                for m in target
            }
            done, not_done = concurrent.futures.wait(futures.keys(), timeout=TIMEOUT)
            for future in done:
                mname, result, error = future.result()
                results[mname] = {"result": result, "error": error}
            for future in not_done:
                future.cancel()
                mname = futures[future]
                results[mname] = {"result": None, "error": f"Timed out ({TIMEOUT}s)"}

        total_ms = int((time.monotonic() - start_all) * 1000)

        # Save to DB
        db = get_db()
        all_items_count = sum(
            len(r["result"].items) for r in results.values() if r["result"]
        )
        search_id = db.save_search(
            query=query, marketplace="ALL",
            brand=brand or None,
            min_price=min_price if min_price > 0 else None,
            max_price=max_price if max_price > 0 else None,
            total_results=all_items_count,
            items_returned=all_items_count,
            duration_ms=total_ms,
        )

        # Format output
        output = f"# Cross-Marketplace Search ({total_ms}ms)\n\n"
        output += f"**Query:** {query}"
        if brand:
            output += f" | **Brand:** {brand}"
        output += f"\n\n"

        # Summary table
        output += "| Marketplace | Items | Total | Time | Status |\n"
        output += "|:------------|------:|------:|-----:|:-------|\n"
        total_items = 0
        for mname in target:
            r = results.get(mname, {})
            if r.get("error"):
                output += f"| {mname} | — | — | — | ❌ {r['error'][:40]} |\n"
            elif r.get("result"):
                res = r["result"]
                total_items += len(res.items)
                output += (
                    f"| {mname} | {len(res.items)} | {res.total_found} | "
                    f"{res.duration_ms}ms | ✅ |\n"
                )

        output += f"\n**Total items:** {total_items}\n\n"

        # Results per marketplace
        for mname in target:
            r = results.get(mname, {})
            if r.get("error") or not r.get("result"):
                continue
            res = r["result"]
            if res.items:
                output += f"---\n\n### {mname.upper()} ({len(res.items)} items)\n\n"
                output += _format_items(res.items, max_items=limit)
                output += "\n\n"

        if len(output) > MAX_OUTPUT_CHARS:
            output = output[:MAX_OUTPUT_CHARS]
            output += "\n\n[TRUNCATED]"

        return output

    @mcp.tool()
    def search_smart(
        query: str,
        category: str = "general",
        brand: str = "",
        min_price: float = 0,
        max_price: float = 0,
        limit: int = 20,
    ) -> str:
        """Smart-route search to the BEST marketplace for an item category.
        Automatically selects optimal marketplace based on category routing.
        Falls back to Apify cloud actors when direct providers are unavailable.

        Categories: clothing, shoes, accessories, bags, luxury, streetwear,
        vintage, electronics, furniture, sports, kids, home, general.

        Example: search_smart("Jordan 4", category="shoes")
        → Routes to best available marketplace for shoes."""
        valid_cats = list(CATEGORY_ROUTING.keys())
        if category not in valid_cats:
            return f"ERROR: Unknown category '{category}'. Available: {', '.join(valid_cats)}"

        all_providers = get_providers()
        route_chain = CATEGORY_ROUTING.get(category, CATEGORY_ROUTING["general"])
        chain_str = " → ".join(f"{m}({r})" for m, r in route_chain)

        # Try direct provider first, then Apify fallback for each marketplace
        apify_provider = all_providers.get("apify")
        apify_available = apify_provider and apify_provider.is_available()
        apify_marketplaces = (
            apify_provider.get_supported_marketplaces() if apify_available else []
        )

        # Find the best available marketplace (direct or via Apify)
        chosen_marketplace = None
        chosen_region = ""
        use_apify = False

        for mp_name, region in route_chain:
            if mp_name == "apify":
                # Skip generic "apify" entry — we handle Apify per-marketplace
                continue
            # Check direct provider
            direct = all_providers.get(mp_name)
            if direct and direct.is_available() and get_health(mp_name).is_healthy():
                chosen_marketplace = mp_name
                chosen_region = region
                use_apify = False
                break
            # Check Apify fallback for this marketplace
            if apify_available and mp_name in apify_marketplaces:
                chosen_marketplace = mp_name
                chosen_region = region
                use_apify = True
                break

        if not chosen_marketplace:
            return f"ERROR: No marketplaces available for '{category}'."

        if use_apify:
            # Search via Apify with correct target marketplace
            result = _search_via_apify(
                target_marketplace=chosen_marketplace,
                display_name=chosen_marketplace.capitalize(),
                query=query, brand=brand,
                min_price=min_price, max_price=max_price,
                limit=limit, region=chosen_region,
            )
            header = (
                f"🎯 **Smart Routing** → `{category}` → **{chosen_marketplace}** "
                f"(via Apify, {chosen_region})\n"
                f"Route chain: {chain_str}\n\n"
            )
        else:
            result = _search_marketplace(
                chosen_marketplace, query, brand, min_price, max_price,
                "", "", "relevance", limit, chosen_region,
            )
            header = (
                f"🎯 **Smart Routing** → `{category}` → **{chosen_marketplace}** "
                f"({chosen_region})\n"
                f"Route chain: {chain_str}\n\n"
            )
        return header + result

    @mcp.tool()
    def marketplace_health() -> str:
        """Show health status of all marketplace providers.
        Displays: availability, success rate, avg latency, circuit breaker state.
        Use to check which marketplaces are working."""
        all_providers = get_providers()
        available = get_available_providers()
        health_data = get_all_health()

        output = "# Marketplace Health Dashboard\n\n"
        output += f"**Available:** {len(available)}/{len(all_providers)} configured\n\n"

        output += "| Marketplace | Status | Calls | Success | Avg Latency | Circuit | Auth |\n"
        output += "|:------------|:-------|------:|--------:|------------:|:--------|:-----|\n"

        for name, p in all_providers.items():
            cap = MARKETPLACE_REGISTRY.get(name)
            auth_type = cap.requires_auth if cap else "?"

            if not p.is_available():
                output += (
                    f"| {name} | ❌ No auth | — | — | — | — | "
                    f"`{p.api_key_env}` ({auth_type}) |\n"
                )
                continue

            h = health_data.get(name)
            if not h or h.total_calls == 0:
                output += f"| {name} | ✅ Ready | 0 | — | — | Closed | {auth_type} |\n"
                continue

            success_pct = f"{h.success_rate * 100:.0f}%"
            circuit = "🔴 OPEN" if h.circuit_open else "🟢 Closed"
            output += (
                f"| {name} | ✅ Active | {h.total_calls} | {success_pct} | "
                f"{h.avg_latency_ms}ms | {circuit} | {auth_type} |\n"
            )

        # Category routing table
        output += "\n## Category Routing\n\n"
        output += "| Category | Route (best → fallback) |\n"
        output += "|:---------|:------------------------|\n"
        for cat, chain in CATEGORY_ROUTING.items():
            route_str = " → ".join(
                f"**{m}**({r})" if m in available else f"~~{m}~~({r})"
                for m, r in chain
            )
            output += f"| {cat} | {route_str} |\n"

        # Marketplace capabilities
        output += "\n## Marketplace Capabilities\n\n"
        output += "| Marketplace | Categories | Regions | API | Rate Limit | Strengths |\n"
        output += "|:------------|:-----------|:--------|:----|:-----------|:----------|\n"
        for name, cap in MARKETPLACE_REGISTRY.items():
            cats = ", ".join(cap.categories[:4])
            if len(cap.categories) > 4:
                cats += f" +{len(cap.categories) - 4}"
            regions = ", ".join(cap.regions)
            api = "✅ Official" if cap.has_api else "🔧 Scraping"
            rate = f"{cap.rate_limit_rpm} rpm"
            strengths = ", ".join(cap.strengths[:3])
            output += f"| {name} | {cats} | {regions} | {api} | {rate} | {strengths} |\n"

        return output

    # =========================================================================
    # 2 ITEM TOOLS
    # =========================================================================

    @mcp.tool()
    def get_item_details(
        marketplace: str,
        item_id: str,
    ) -> str:
        """Get detailed information about a specific item.
        marketplace: vinted, ebay, grailed, vestiaire, depop, apify, allegro, olx, stockx
        item_id: the item's ID on that marketplace."""
        if marketplace not in VALID_MARKETPLACES:
            return f"ERROR: Unknown marketplace '{marketplace}'. Use: {', '.join(VALID_MARKETPLACES)}"

        provider = get_provider(marketplace)
        if not provider.is_available():
            return f"ERROR: {marketplace} not configured."

        try:
            details = provider.get_item(item_id)
        except Exception as e:
            return f"ERROR fetching item: {e}"

        if not details:
            return f"Item {item_id} not found on {marketplace}."

        item = details.item
        output = f"## {item.title}\n\n"
        output += f"**Marketplace:** {marketplace} | **ID:** {item_id}\n"
        output += f"**Price:** {item.price} {item.currency}\n"
        output += f"**Brand:** {item.brand or 'N/A'} | **Size:** {item.size or 'N/A'}\n"
        output += f"**Condition:** {item.condition or 'N/A'}\n"
        output += f"**URL:** {item.url}\n\n"

        if details.description:
            desc = details.description[:500]
            output += f"**Description:**\n{desc}\n\n"

        if item.seller_name:
            output += f"**Seller:** {item.seller_name}"
            if item.seller_rating:
                output += f" (Rating: {item.seller_rating})"
            output += "\n"

        if details.all_photos:
            output += f"\n**Photos:** {len(details.all_photos)}\n"
            for i, photo in enumerate(details.all_photos[:5], 1):
                output += f"  {i}. {photo}\n"

        return output

    @mcp.tool()
    def compare_prices(
        query: str,
        brand: str = "",
        marketplaces: str = "",
    ) -> str:
        """Compare prices for the same item across multiple marketplaces.
        Returns average, min, max prices per marketplace for quick comparison.
        Supports both direct providers and Apify cloud actors.

        marketplaces: comma-separated list (e.g. "ebay,grailed,vestiaire"),
                      or empty for all available (direct + Apify)."""
        all_providers = get_providers()
        available = get_available_providers()

        # Apify fallback for cloud scraping
        apify_provider = all_providers.get("apify")
        apify_available = apify_provider and apify_provider.is_available()
        apify_marketplaces = (
            apify_provider.get_supported_marketplaces() if apify_available else []
        )

        if marketplaces:
            requested = [m.strip() for m in marketplaces.split(",") if m.strip()]
            # Accept marketplaces reachable via direct OR Apify
            target = [
                m for m in requested
                if m in available or (m in apify_marketplaces and apify_available)
            ]
        else:
            # All reachable marketplaces (direct + Apify)
            target = list(
                set(available)
                | (set(apify_marketplaces) if apify_available else set())
            )
            target = [m for m in target if m != "apify"]

        if len(target) < 2:
            return (
                "ERROR: Need at least 2 marketplaces to compare.\n"
                f"Available: {', '.join(sorted(set(available) | set(apify_marketplaces)))}"
            )

        # Search all in parallel with Apify fallback
        TIMEOUT = 120
        results = {}

        def _compare_one(mname):
            try:
                provider = all_providers.get(mname)
                if provider and provider.is_available():
                    params = SearchParams(query=query, brand=brand, limit=10)
                    return (mname, provider.search(params))
                elif apify_available and mname in apify_marketplaces:
                    params = SearchParams(
                        query=query, category=mname, brand=brand, limit=10,
                    )
                    return (mname, apify_provider.search(params))
                else:
                    return (mname, None)
            except Exception as e:
                logger.warning(f"Price compare failed for {mname}: {e}")
                return (mname, None)

        with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(target), 5)) as executor:
            futures = {
                executor.submit(_compare_one, m): m for m in target
            }
            done, not_done = concurrent.futures.wait(futures.keys(), timeout=TIMEOUT)
            for future in done:
                mname, result = future.result()
                results[mname] = result
            for future in not_done:
                future.cancel()
                mname = futures[future]
                results[mname] = None

        # Build comparison
        output = f"# Price Comparison: {query}\n\n"
        if brand:
            output += f"**Brand:** {brand}\n\n"

        output += "| Marketplace | Min | Max | Avg | Items | Currency |\n"
        output += "|:------------|----:|----:|----:|------:|:--------:|\n"

        best_marketplace = None
        best_avg = float("inf")

        for mname in sorted(target):
            result = results.get(mname)
            if not result or result.error or not result.items:
                status = result.error[:30] if result and result.error else "No data"
                output += f"| {mname} | — | — | — | 0 | {status} |\n"
                continue

            prices = [item.price for item in result.items if item.price > 0]
            if not prices:
                output += f"| {mname} | — | — | — | {len(result.items)} | — |\n"
                continue

            min_p = min(prices)
            max_p = max(prices)
            avg_p = sum(prices) / len(prices)
            currency = result.items[0].currency

            if avg_p < best_avg:
                best_avg = avg_p
                best_marketplace = mname

            output += (
                f"| {mname} | {min_p:.0f} | {max_p:.0f} | {avg_p:.0f} | "
                f"{len(prices)} | {currency} |\n"
            )

        if best_marketplace:
            output += f"\n**Best average price:** {best_marketplace} ({best_avg:.0f})\n"

        output += "\n*Note: Prices may be in different currencies. Check marketplace for exact rates.*"

        return output

    # =========================================================================
    # 2 UTILITY TOOLS
    # =========================================================================

    @mcp.tool()
    def search_history(
        marketplace: str = "",
        limit: int = 20,
    ) -> str:
        """View recent search history.
        Optionally filter by marketplace name.
        Shows query, results count, and timing."""
        db = get_db()
        searches = db.get_search_history(
            marketplace=marketplace or None,
            limit=limit,
        )
        if not searches:
            return "No search history found."

        lines = [
            "| # | Query | Marketplace | Results | Time | Date |",
            "|--:|:------|:------------|--------:|-----:|:-----|",
        ]
        for i, s in enumerate(searches, 1):
            query = (s["query"] or "")[:40]
            marketplace = s["marketplace"] or "?"
            results = s["items_returned"]
            duration = f"{s['duration_ms']}ms"
            date = (s["created_at"] or "")[:16]
            lines.append(
                f"| {i} | {query} | {marketplace} | {results} | {duration} | {date} |"
            )

        return "\n".join(lines)

    @mcp.tool()
    def list_marketplaces() -> str:
        """List all available marketplaces with configuration status.
        Shows which marketplaces have direct providers, which are available
        via Apify cloud actors, and their capabilities."""
        providers = get_providers()
        available = get_available_providers()

        # Check Apify availability
        apify_provider = providers.get("apify")
        apify_available = apify_provider and apify_provider.is_available()
        apify_marketplaces = (
            apify_provider.get_supported_marketplaces() if apify_available else []
        )

        # Count all searchable marketplaces (direct + Apify)
        all_searchable = set(available)
        if apify_available:
            all_searchable |= set(apify_marketplaces)
        all_searchable.discard("apify")  # Don't count meta-provider

        output = "# Available Marketplaces\n\n"
        output += f"**Searchable:** {len(all_searchable)} marketplaces\n"
        output += f"**Direct providers:** {len(available)}/{len(providers)} configured\n"
        if apify_available:
            output += f"**Apify cloud:** {len(apify_marketplaces)} actors available\n"
        output += "\n"

        # Show each marketplace with its access method
        shown = set()
        for name, p in providers.items():
            if name == "apify":
                continue  # Show Apify section separately
            shown.add(name)

            direct_ok = p.is_available()
            apify_ok = name in apify_marketplaces and apify_available

            if direct_ok:
                status = "✅ Direct"
            elif apify_ok:
                status = "☁️ Apify"
            else:
                status = "❌ Offline"

            cap = MARKETPLACE_REGISTRY.get(name)
            output += f"### {status} — {p.display_name} (`{name}`)\n"

            if cap:
                output += f"- **Categories:** {', '.join(cap.categories)}\n"
                output += f"- **Regions:** {', '.join(cap.regions)}\n"
                output += f"- **Strengths:** {', '.join(cap.strengths)}\n"
            output += "\n"

        # Show Apify-only marketplaces
        for mp_name in apify_marketplaces:
            if mp_name not in shown:
                cap = MARKETPLACE_REGISTRY.get(mp_name)
                display = cap.notes if cap else mp_name.capitalize()
                output += f"### ☁️ Apify — {mp_name.capitalize()} (`{mp_name}`)\n"
                if cap:
                    output += f"- **Categories:** {', '.join(cap.categories)}\n"
                    output += f"- **Regions:** {', '.join(cap.regions)}\n"
                    output += f"- **Strengths:** {', '.join(cap.strengths)}\n"
                output += "\n"

        # Apify section
        if apify_available:
            output += "## Apify Cloud Scraping\n\n"
            output += f"**Status:** ✅ Configured (APIFY_API_TOKEN set)\n"
            output += f"**Actors:** {len(apify_marketplaces)} ({', '.join(apify_marketplaces)})\n"
            output += f"**Usage:** `search_apify(query, target_marketplace)` or `search_all(query)`\n"
        else:
            output += "## Apify Cloud Scraping\n\n"
            output += "**Status:** ❌ Not configured\n"
            output += "Set `APIFY_API_TOKEN` to enable cloud scraping for all marketplaces.\n"
            output += "Get token: https://console.apify.com/account/integrations\n"

        return output
