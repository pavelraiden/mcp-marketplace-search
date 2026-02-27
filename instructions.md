# MCP Marketplace Search Server

## Overview
MCP сервер для поиска товаров на 5 маркетплейсах через Claude Code.
Архитектура 1:1 с mcp-multi-ai — тот же паттерн FastMCP + STDIO + BaseProvider.

## Architecture

```
mcp-marketplace-search/
├── server/
│   ├── __init__.py          # Package init
│   ├── main.py              # FastMCP entry point (66 lines)
│   ├── types.py             # Shared types: SearchParams, MarketplaceItem, SearchResult
│   ├── providers.py         # BaseMarketplaceProvider + 5 implementations
│   ├── tools.py             # 12 MCP tools registration
│   └── db.py                # SQLite persistence (search history)
├── data/                    # SQLite DB (auto-created)
├── pyproject.toml           # Dependencies: mcp[cli], httpx
├── .mcp.json                # Claude Code MCP config
└── instructions.md          # This file
```

## Marketplaces

| Marketplace | Auth | API | Strengths |
|:------------|:-----|:----|:----------|
| Vinted | Cookie/Playwright | Scraping | Fashion, EU, largest |
| eBay | API Key + Secret | Official | Global, everything |
| Grailed | Algolia Key | Scraping | Menswear, streetwear |
| Vestiaire | Cookie | Scraping | Luxury, authenticated |
| Depop | Cookie | Scraping | Vintage, Gen-Z |

## Tools (12)

### Search (5)
- `search_vinted` — Search Vinted (EU fashion)
- `search_ebay` — Search eBay (global, everything)
- `search_grailed` — Search Grailed (streetwear/designer)
- `search_vestiaire` — Search Vestiaire (luxury)
- `search_depop` — Search Depop (vintage/unique)

### Orchestrator (3)
- `search_all` — Parallel search across multiple marketplaces
- `search_smart` — Auto-route to best marketplace by category
- `marketplace_health` — Health dashboard with circuit breaker status

### Item (2)
- `get_item_details` — Detailed item info from specific marketplace
- `compare_prices` — Price comparison across platforms

### Utility (2)
- `search_history` — Recent search history from SQLite
- `list_marketplaces` — Configured marketplaces and capabilities

## Adding a New Marketplace

1. Create class in `server/providers.py` extending `BaseMarketplaceProvider`
2. Set: `name`, `display_name`, `base_url`, `api_key_env`
3. Implement `_do_search(params: SearchParams) -> SearchResult`
4. Implement `_do_get_item(item_id: str) -> ItemDetails | None`
5. Add class to `PROVIDER_CLASSES` list
6. Add entry to `MARKETPLACE_REGISTRY`
7. Add to `CATEGORY_ROUTING` for relevant categories
8. Set API key in .mcp.json env vars
9. Done — tools auto-discover new providers

## Key Patterns (from multi-ai)

- **Health Tracking:** ProviderHealth tracks calls/failures/latency per marketplace
- **Circuit Breaker:** Opens after 3 consecutive failures, 2-minute cooldown
- **Retry:** Exponential backoff for transient errors (429, 503, timeout)
- **Rate Limiting:** Per-provider min_request_interval prevents abuse
- **Smart Routing:** CATEGORY_ROUTING maps item type → best marketplace chain
- **SQLite Persistence:** All searches saved for history/analytics
- **Parallel Search:** search_all uses ThreadPoolExecutor with timeout

## Setup

```bash
# Install
uv run --with "mcp[cli]" --with httpx --python 3.12 python -m server.main

# For Vinted auto-cookies (optional):
pip install playwright && playwright install chromium

# Environment variables:
VINTED_COOKIE=<session_cookie_or_empty_for_auto>
VINTED_DOMAIN=fr
EBAY_API_KEY=<ebay_client_id>
EBAY_APP_SECRET=<ebay_client_secret>
GRAILED_ALGOLIA_KEY=<algolia_key_or_auto>
VESTIAIRE_COOKIE=<session_cookie>
DEPOP_COOKIE=<session_cookie>
```

## Relation to VintedFlip

This MCP server is the **search infrastructure** for VintedFlip project.
- VintedFlip's scraper package = single-marketplace (Vinted only)
- This MCP server = multi-marketplace, pluggable, Claude Code integrated
- Future: VintedFlip can consume this server's search results

## Created

- **Date:** 2026-02-27
- **Based on:** mcp-multi-ai architecture pattern
- **Session:** VintedFlip session 9 (deep self-learning + MCP marketplace server)
