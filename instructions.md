# MCP Marketplace Search Server

## Overview
MCP сервер для поиска товаров на 5 маркетплейсах через Claude Code.
Архитектура 1:1 с mcp-multi-ai — тот же паттерн FastMCP + STDIO + BaseProvider.

## Architecture

```
mcp-marketplace-search/
├── server/
│   ├── __init__.py          # Package init
│   ├── __main__.py          # python -m server entrypoint
│   ├── main.py              # FastMCP entry point (78 lines)
│   ├── types.py             # Shared types: SearchParams, MarketplaceItem, SearchResult (~199 lines)
│   ├── providers.py         # BaseMarketplaceProvider + 5 implementations (~1296 lines)
│   ├── tools.py             # 12 MCP tools registration (~674 lines)
│   └── db.py                # Thread-safe SQLite persistence (~310 lines)
├── tests/
│   ├── conftest.py          # Fixtures: temp_db, reset_providers, sample_items
│   ├── test_types.py        # 20 tests — enums, dataclasses, defaults
│   ├── test_db.py           # 19 tests — CRUD, thread safety, singleton
│   ├── test_providers.py    # 33 tests — health, registry, routing, per-provider
│   └── test_tools.py        # 9 tests — formatting, registration, search logic
├── data/                    # SQLite DB (auto-created)
├── pyproject.toml           # Dependencies + test config
├── .gitignore               # Excludes __pycache__, data/*.db, .venv, uv.lock
├── .mcp.json                # Claude Code MCP config
└── instructions.md          # This file
```

## Tests

```bash
# Run all 108 tests
uv run --with pytest --with pytest-cov pytest tests/ -v

# With coverage
uv run --with pytest --with pytest-cov pytest tests/ -v --cov=server --cov-report=term-missing
```

| File | Tests | Coverage |
|:-----|------:|:---------|
| test_types.py | 20 | Enums, dataclasses, defaults, mutable safety |
| test_db.py | 19 | CRUD, history, stats, cleanup, threads, singleton |
| test_providers.py | 33 | Health, registry, routing, instantiation, behavior |
| test_tools.py | 9 | Formatting, registration, search mocking |
| **Total** | **108** | **All passing** |

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

## Roadmap

### v1.0 — Core (DONE ✅)
- [x] 5 marketplace providers (Vinted, eBay, Grailed, Vestiaire, Depop)
- [x] 12 MCP tools (search, orchestrator, item, utility)
- [x] Circuit breaker + health tracking
- [x] Category routing (13 categories)
- [x] Thread-safe SQLite persistence
- [x] 108 tests, all passing
- [x] Private GitHub repo

### v1.1 — Real API Validation
- [ ] Test Vinted search with real cookies (Playwright auto-cookie)
- [ ] Test eBay with real API key (OAuth flow)
- [ ] Test Grailed with real Algolia key
- [ ] Test Vestiaire + Depop with real cookies
- [ ] Fix any API response parsing issues found
- [ ] Integration tests with real endpoints

### v1.2 — New Marketplaces
- [ ] Apify integration as fallback provider (user has $29/mo plan)
- [ ] Mercari (US resale)
- [ ] Poshmark (US fashion)
- [ ] Wallapop (Spain/EU)
- [ ] Template: `docs/adding-marketplace.md` with step-by-step

### v1.3 — Deploy & Production
- [ ] Docker container + compose
- [ ] Deploy to user's server (root access available)
- [ ] Health monitoring endpoint
- [ ] Data retention / cleanup job
- [ ] Structured logging (JSON)

### v2.0 — Intelligence
- [ ] Price trend analysis (historical data from SQLite)
- [ ] Deal scoring (cross-marketplace price comparison)
- [ ] Notification system (price drops, new listings)
- [ ] AI-powered item categorization
- [ ] Photo-based search (Claude Vision integration)

## Git

- **Repo:** `pavelraiden/mcp-marketplace-search` (private)
- **Branch:** `master`
- **Initial commit:** `2e4483a` — v1.0.0 (16 files, 4017 lines)

## Created

- **Date:** 2026-02-27
- **Based on:** mcp-multi-ai architecture pattern
- **Session:** VintedFlip session 9 (deep self-learning + MCP marketplace server)
- **Deep audit:** Session 10 (108 tests, bug fixes, git init)
