# MCP Marketplace Search Server

## Overview
MCP сервер для поиска товаров на 9 маркетплейсах (5 direct + 3 Apify-only + Apify meta-provider) через Claude Code.
Архитектура 1:1 с mcp-multi-ai — тот же паттерн FastMCP + STDIO + BaseProvider.
ApifyProvider поддерживает 8 marketplace actors — primary cloud scraping engine.

## Architecture

```
mcp-marketplace-search/
├── server/
│   ├── __init__.py          # Package init
│   ├── __main__.py          # python -m server entrypoint
│   ├── main.py              # FastMCP entry point (78 lines)
│   ├── types.py             # Shared types: SearchParams, MarketplaceItem, SearchResult (~199 lines)
│   ├── providers.py         # BaseMarketplaceProvider + 6 implementations (~1950 lines)
│   ├── tools.py             # 16 MCP tools registration (~870 lines)
│   └── db.py                # Thread-safe SQLite persistence (~310 lines)
├── tests/
│   ├── conftest.py          # Fixtures: temp_db, reset_providers, sample_items
│   ├── test_types.py        # 20 tests — enums, dataclasses, defaults
│   ├── test_db.py           # 19 tests — CRUD, thread safety, singleton
│   ├── test_providers.py    # 87 tests — health, registry, routing, per-provider, ApifyProvider (8 actors)
│   └── test_tools.py        # 9 tests — formatting, registration, search logic
├── data/                    # SQLite DB (auto-created)
├── pyproject.toml           # Dependencies + test config
├── .gitignore               # Excludes __pycache__, data/*.db, .venv, uv.lock
├── .mcp.json                # Claude Code MCP config
└── instructions.md          # This file
```

## Tests

```bash
# Run all 154 tests
uv run --with pytest --with pytest-cov pytest tests/ -v

# With coverage
uv run --with pytest --with pytest-cov pytest tests/ -v --cov=server --cov-report=term-missing
```

| File | Tests | Coverage |
|:-----|------:|:---------|
| test_types.py | 23 | Enums, dataclasses, defaults, mutable safety, SearchResult.error |
| test_db.py | 19 | CRUD, history, stats, cleanup, threads, singleton |
| test_providers.py | 92 | Health, registry, routing, instantiation, behavior, ApifyProvider (8 actors), graceful errors, real API parsers |
| test_tools.py | 9 | Formatting, registration, search mocking |
| **Total** | **162** | **All passing** |

## Marketplaces

| Marketplace | Auth | API | Strengths |
|:------------|:-----|:----|:----------|
| Vinted | Cookie/Playwright | Scraping | Fashion, EU, largest |
| eBay | API Key + Secret | Official | Global, everything |
| Grailed | Algolia Key | Scraping | Menswear, streetwear |
| Vestiaire | Cookie | Scraping | Luxury, authenticated |
| Depop | Cookie | Scraping | Vintage, Gen-Z |
| **Allegro** | via Apify | Cloud Actor | CEE, PL/CZ/SK, electronics |
| **OLX** | via Apify | Cloud Actor | Classifieds, PL/UA/RO/PT/BG |
| **StockX** | via Apify | Cloud Actor | Sneakers, authenticated, market data |
| **Apify** | API Token ($29/mo) | 8 Cloud Actors | **Multi-marketplace**, no cookies needed |

## Tools (16)

### Search (9)
- `search_vinted` — Search Vinted (EU fashion)
- `search_ebay` — Search eBay (global, everything)
- `search_grailed` — Search Grailed (streetwear/designer)
- `search_vestiaire` — Search Vestiaire (luxury)
- `search_depop` — Search Depop (vintage/unique)
- `search_allegro` — Search Allegro (PL/CZ/SK, via Apify)
- `search_olx` — Search OLX classifieds (PL/UA/RO/PT/BG, via Apify)
- `search_stockx` — Search StockX (sneakers/streetwear, via Apify)
- `search_apify` — Cloud scraping via 8 Apify actors (vinted, grailed, ebay, vestiaire, depop, allegro, olx, stockx)

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

### Option A: Apify-only (RECOMMENDED — no API keys needed)
1. Find Apify actor for the marketplace on https://apify.com/store
2. Add entry to `ApifyProvider.ACTOR_MAP` dict
3. Add `_build_actor_input_{name}()` case in `_build_actor_input()`
4. Add `_parse_{name}_result()` parser method
5. Add routing in `_parse_result()`
6. Add entry to `MARKETPLACE_REGISTRY`
7. Add to `CATEGORY_ROUTING` for relevant categories
8. Add to `VALID_MARKETPLACES`
9. Add `search_{name}` tool in `tools.py` (use `_search_via_apify` helper)
10. Write tests for input builder + parser + registry

### Option B: Direct Provider (with API key)
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
APIFY_API_TOKEN=<apify_api_token>  # $29/mo plan, https://console.apify.com/account/integrations
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

### v1.2 — Apify Fallback (DONE ✅)
- [x] ApifyProvider as cloud scraping fallback
- [x] Vinted + Grailed Apify Actors configured
- [x] search_apify tool with target_marketplace parameter
- [x] CATEGORY_ROUTING updated with apify as last fallback
- [x] 22 new tests (130 total, all passing)
- [x] 5 bugs fixed in initial implementation

### v1.3 — Apify Multi-Marketplace Expansion (DONE ✅)
- [x] ApifyProvider ACTOR_MAP: 2 → 8 actors (vinted, grailed, ebay, vestiaire, depop, allegro, olx, stockx)
- [x] Upgraded grailed actor: benthepythondev → vmscrapers/grailed (43 users, richer data)
- [x] 6 new parsers: ebay, vestiaire, depop, allegro, olx, stockx
- [x] 7 new input builders with marketplace-specific logic (URL-based vs param-based)
- [x] 3 new Apify-only marketplaces: Allegro (CEE), OLX (classifieds), StockX (sneakers)
- [x] 3 new search tools: search_allegro, search_olx, search_stockx
- [x] MARKETPLACE_REGISTRY: 6 → 9 entries
- [x] CATEGORY_ROUTING updated with new marketplaces
- [x] ~30 new tests (154 total, all passing)
- [x] 830 insertions across 5 files

### v1.4 — More Marketplaces
- [ ] Mercari (US resale)
- [ ] Poshmark (US fashion)
- [ ] Wallapop (Spain/EU)
- [ ] Template: `docs/adding-marketplace.md` with step-by-step

### v1.5 — Deploy & Production
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
- **Commits:**
  - `2e4483a` — v1.0.0 (16 files, 4017 lines)
  - `4b08c3a` — docs: roadmap, session log, test documentation
  - `99289d4` — feat: ApifyProvider as cloud scraping fallback (v1.2)
  - `b9ff83b` — feat: expand ApifyProvider to 8 actors, add Allegro/OLX/StockX (v1.3)
  - `7aaf866` — fix: update stale test counts, add APIFY_API_TOKEN to configs
  - `0f2e19e` — feat: add global ROADMAP.md, fix main.py docstring and tool count
  - `c50f985` — fix: real API validation — graceful errors, Vestiaire parser (v1.4-dev)

## Created

- **Date:** 2026-02-27
- **Based on:** mcp-multi-ai architecture pattern
- **Session:** VintedFlip session 9 (deep self-learning + MCP marketplace server)
- **Deep audit:** Session 10 (108 tests, bug fixes, git init)
- **Apify provider:** Session 11 (ApifyProvider + 22 tests, 130 total)
- **Apify expansion:** Session 12 (8 actors, 3 new marketplaces, 154 total tests)
- **Real API validation:** Session 13 (5 bugs fixed, Vestiaire verified, 161 tests)
