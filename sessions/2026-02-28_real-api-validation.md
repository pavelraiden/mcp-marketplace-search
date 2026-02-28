# MCP Marketplace Search — SESSION LOG

**Last Updated:** 2026-02-28T04:00:00Z

---

## Session 4 — 2026-02-28 (Real API Validation — Phase 3)

### Context
- Continuation of Session 3 (8 Apify actors, 154 tests, v1.3 done)
- User requested: continue Ralph Loop, make project actually work end-to-end
- EXIT GATE: fully working project user can use RIGHT NOW
- Language: switched to Ukrainian (no Russian)

### Completed

#### TASK 1: Global ROADMAP.md
- Created comprehensive ROADMAP.md (~280 lines) using project-roadmap plugin
- Vision, MoSCoW features, 5 Phases, Architecture diagram, Risks, Decisions Log
- Committed: `0f2e19e`

#### TASK 2: Fix main.py Stale Counts
- Docstring said "5 marketplaces" → fixed to 9
- FastMCP instructions said "5 platforms" → fixed to 9 with all tools listed
- Logger said "12 tools" → fixed to 16
- Committed: `0f2e19e`

#### TASK 3: Apify API Bug Fixes (4 bugs found via real testing)
- **BUG 1: Actor ID URL format (404)** — Apify API requires tilde `~` not slash in actor IDs
  - Fix: `safe_actor_id = actor_id.replace("/", "~")`
- **BUG 2: Auth method** — Changed from Bearer header to query param `?token=TOKEN`
  - All 3 API calls (start, poll, dataset) use query param now
- **BUG 3: Vestiaire input format (400)** — Actor expects `startUrl` (singular) not `startUrls` (plural)
  - Fix: `"startUrl": search_url` instead of `"startUrls": [search_url]`
- **BUG 4: Error logging** — Added error body logging before raise_for_status()

#### TASK 4: Graceful Error Handling
- **ACTOR_TIMEOUT:** 120→300s (Vestiaire needs ~100s for scraping)
- **POLL_INTERVAL:** 3→5s (reduce unnecessary API calls)
- **SearchResult.error field:** Added to types.py — enables graceful error propagation
- **403 handling:** actor-is-not-rented returns SearchResult with readable error + rental URL
- **Timeout handling:** Returns SearchResult with error instead of crash
- **Network error handling:** Catches connection errors, returns readable message
- **tools.py:** Added error handling in all 3 search flows (direct, search_apify, _search_via_apify)
- **to_summary():** Shows "ERROR" prefix when error field is set

#### TASK 5: Vestiaire Parser Rewrite (Real API Response)
- Discovered real JSON keys differ from guessed ones:
  - `productId` (not `id`), `productName` (not `name`), `brandName` (not `brand.name`)
  - `price` as flat int (not `price.amount` dict), `priceCurrency` (not `currency`)
  - `productUrl` (not `url`), `imageUrl`/`imageUrls` (not `pictures[].url`)
  - `sellerName` (not `seller.username`), `country` (not `seller.country`)
  - `likes` (not `favorites`), `colors[]`, `description`, `modelName`
- Parser now handles both real and legacy formats (backward-compatible)

#### TASK 6: Grailed Parser Rewrite (Real API Response)
- User rented Grailed actor — tested with "nike dunk" → 5 real items returned
- Discovered real JSON keys differ:
  - `designer_names`/`designers[]` (not `designer`), `user.username` (not `seller.username`)
  - `user.seller_score.rating_average` (not `seller.rating`)
  - `image_url` (not `image`), `follower_count` (not `favorites`)
  - `category_path`, `shipping.us.amount`, `created_at`, `color`, `location`
- Parser rewritten with backward-compatible fallbacks
- Added `test_parse_grailed_result_designer_fallback` test

#### TASK 7: eBay Parser Update (Real API Response)
- User rented eBay actor — tested with "nike air max" → 5 real items in 10s!
- Real keys confirmed matching our parser: `itemNumber`, `title`, `price`, `brand`, `condition`
- Enhanced parser with new fields: `images[]`, `sold` (as favorites proxy), `priceWithCurrency` for currency
- eBay data is richest: up to 28 photos, sold count, wasPrice for discount analysis

#### TASK 8: Multi-Marketplace Search Test
- Tested all 3 working marketplaces sequentially with "nike dunk":
  - **eBay:** 3 items, 16.5s — Nike Dunk $99-$125
  - **Grailed:** 3 items, 21.0s — Nike Dunk $39-$119
  - **Vestiaire:** 3 items, 31.4s — Nike Dunk $170-$217
- **9 total items from 3 marketplaces — ALL WORKING**
- Price comparison reveals: Grailed cheapest → eBay mid → Vestiaire highest

#### TASK 9: Tests & Documentation
- Updated Grailed mock test with real API keys
- Updated eBay mock test with real API keys (itemNumber as int, images[], sold, categories[])
- **162/162 PASSED** (was 161)
- Updated ROADMAP.md: Phase 3 progress 40% → 70%

### Git Commits
- `0f2e19e` — feat: add global ROADMAP.md, fix main.py docstring and tool count
- `c50f985` — fix: real API validation — graceful errors, Vestiaire parser, timeout increase
- (pending) — feat: Grailed + eBay parser rewrite from real API data

### Current State
- **Phase 1 (Core):** DONE ✅
- **Phase 2 (Apify Expansion):** DONE ✅
- **Phase 3 (Real API):** 70% 🔄
  - Vestiaire ✅ — 3 items verified, parser rewritten
  - Grailed ✅ — 5 items verified, parser rewritten
  - eBay ✅ — 5 items verified, parser enhanced
  - Depop ❌ — both actors broken (fallback response)
  - Vinted ⬜ — actor not rented
  - Allegro/OLX/StockX ⬜ — actors not rented
- **Tests:** 162/162 passing
- **Working marketplaces:** 3/8 via Apify (Vestiaire, Grailed, eBay)

### Infrastructure

| Resource | Value |
|:---------|:------|
| Repo | pavelraiden/mcp-marketplace-search (private) |
| Branch | master |
| Marketplaces | 9 configured, 3 verified working |
| Tools | 16 (9 search + 3 orchestrator + 2 item + 2 utility) |
| Tests | 162/162 passing |
| Apify User | nippy_steak (STARTER plan) |
| Rented Actors | vestiaire ✅, grailed ✅, ebay ✅, depop ❌ (broken) |

### Error Journal

| Error ID | Date | Description | Prevention |
|:---------|:-----|:-----------|:-----------|
| ERR-011 | 2026-02-28 | Apify URL uses `/` as path separator in actor IDs | Always encode actor IDs with tilde: `id.replace("/", "~")` |
| ERR-012 | 2026-02-28 | Vestiaire actor expects `startUrl` (singular) not `startUrls` | Read actor documentation, test with real API before shipping |
| ERR-013 | 2026-02-28 | Bearer auth fails for some endpoints, query param works | Use `?token=` consistently for all Apify API calls |
| ERR-014 | 2026-02-28 | SearchResult had no `error` field — graceful errors impossible | Always add error propagation to result types from the start |
| ERR-015 | 2026-02-28 | Parser keys ALWAYS differ from API docs | ALWAYS test with real API data before writing parsers |
| ERR-016 | 2026-02-28 | Grailed: `designer_names` not `designer`, `user` not `seller` | Different actors use completely different JSON schemas |
| ERR-017 | 2026-02-28 | Depop actors broken (both return _fallback) | Have alternative actors documented, graceful error handling |

### Key Patterns
- **REAL API testing reveals everything** — 7 bugs found that unit tests couldn't catch
- **Parser keys ALWAYS differ from documentation** — test with real data, not assumptions
- **Each actor has unique JSON schema** — no standardization across Apify actors
- **Price comparison works** — same item varies 2-5x across marketplaces (profit opportunity!)
- **Response times:** eBay ~16s, Grailed ~21s, Vestiaire ~31s

### Recovery Protocol
1. Read this session log for context
2. `cd "C:/CLAUDE MAIN FOLDER/projects/mcp-marketplace-search"`
3. `uv run --with pytest --with pytest-cov pytest tests/ -v` — verify 162 tests pass
4. Real search: `APIFY_API_TOKEN=<token> uv run --with httpx python -c "..."`
5. Working actors: vestiaire, grailed, ebay. Broken: depop.
6. Next: commit changes, test search_all orchestrator, or proceed to Phase 4
