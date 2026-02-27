# PROJECT ROADMAP: MCP Marketplace Search Server

> **Version:** 1.3.0
> **Last Updated:** 2026-02-28
> **Status:** Development
> **Language:** Ukrainian (UA)

---

## VISION

### Final Goal
Multi-marketplace search engine integrated into Claude Code/Desktop, that allows the user to **search 9+ marketplaces simultaneously** through natural language.

**Use cases:**
1. **Reselling (profit):** Find underpriced items on one marketplace, sell higher on another
2. **Personal shopping:** Find top clothing/shoes/accessories across all platforms
3. **Price comparison:** Compare prices for the same item across marketplaces
4. **Deal hunting:** Discover deals, price drops, rare items

### Key Success Metrics
- [ ] **KSM-1:** Real search works on 5+ marketplaces via Apify (end-to-end verified)
- [ ] **KSM-2:** User can ask Claude "find me Nike Air Max under $100" and get real results
- [ ] **KSM-3:** Response time < 30 seconds for single marketplace, < 60s for multi
- [ ] **KSM-4:** Results include price, photos, links, seller info
- [ ] **KSM-5:** Server runs reliably 24/7 (Docker or MCP auto-start)

---

## FEATURES (MoSCoW)

### Must-Have (without these — product is useless)
- [x] Multi-marketplace search (9 marketplaces)
- [x] Apify cloud scraping (8 actors, no cookies needed)
- [x] Smart routing by category
- [ ] **Real API integration (Apify token configured and tested)**
- [ ] **End-to-end search working (real results returned)**
- [ ] **MCP server starts and registers tools in Claude**

### Should-Have (important, but can launch without)
- [ ] Error handling for real API failures (timeouts, rate limits, empty results)
- [ ] Structured logging (JSON, errors traceable)
- [ ] Price normalization across currencies (EUR, USD, PLN, UAH)
- [ ] Result deduplication (same item on multiple platforms)

### Could-Have (nice to have, Phase 4+)
- [ ] Price trend analysis (historical data)
- [ ] Deal scoring algorithm
- [ ] Notification system (price drops)
- [ ] Photo-based search (Claude Vision)
- [ ] Docker deployment

### Won't-Have (explicitly out of scope for now)
- Web UI / Dashboard
- Mobile app
- Payment processing
- Automated buying/bidding
- User accounts / multi-tenant

---

## PHASES

### Phase 1: Foundation (DONE ✅)
**Period:** 2026-02-27
**Summary:** Core architecture, 5 direct providers, 12 tools, 108 tests

| Task | Status | Details |
|:-----|:------:|:--------|
| BaseMarketplaceProvider architecture | ✅ Done | Template Method + health tracking |
| 5 marketplace providers (Vinted, eBay, Grailed, Vestiaire, Depop) | ✅ Done | Each with search + item details |
| 12 MCP tools (search, orchestrator, item, utility) | ✅ Done | FastMCP + STDIO |
| Circuit breaker + retry + rate limiting | ✅ Done | 3 failures → open, 2min cooldown |
| Category routing (13 categories) | ✅ Done | Maps category → best marketplace chain |
| Thread-safe SQLite persistence | ✅ Done | Singleton + Lock |
| 108 tests, all passing | ✅ Done | types, db, providers, tools |
| Private GitHub repo | ✅ Done | pavelraiden/mcp-marketplace-search |

### Phase 2: Apify Expansion (DONE ✅)
**Period:** 2026-02-27 — 2026-02-28
**Summary:** ApifyProvider 2→8 actors, 3 new marketplaces, 154 tests

| Task | Status | Details |
|:-----|:------:|:--------|
| ApifyProvider with 2 actors (v1.2) | ✅ Done | Vinted + Grailed, 5 bugs fixed |
| Expand to 8 actors (v1.3) | ✅ Done | +eBay, Vestiaire, Depop, Allegro, OLX, StockX |
| Upgrade grailed actor | ✅ Done | vmscrapers/grailed (43 users, richer data) |
| 6 new marketplace parsers | ✅ Done | Each handles specific JSON format |
| 3 new Apify-only marketplaces | ✅ Done | Allegro (CEE), OLX (classifieds), StockX (sneakers) |
| 3 new search tools | ✅ Done | search_allegro, search_olx, search_stockx |
| Registry updates (6→9 marketplaces) | ✅ Done | MARKETPLACE_REGISTRY, ROUTING, VALID |
| 154 tests, all passing | ✅ Done | +30 new tests |
| Knowledge K110 created | ✅ Done | Apify patterns for future reference |
| Config files updated | ✅ Done | .mcp.json + claude_desktop_config.json |

### Phase 3: Real API Integration (CURRENT 🔄)
**Period:** 2026-02-28 — ...
**Goal:** Make the server actually WORK with real Apify API

| Task | Status | Details |
|:-----|:------:|:--------|
| Configure APIFY_API_TOKEN in claude_desktop_config.json | 🔄 Pending | Need user's token from console.apify.com |
| Verify MCP server starts without errors | 🔄 In Progress | Test startup, tool registration |
| Test real Apify search (Vinted) | ⬜ Planned | First real end-to-end test |
| Test real Apify search (eBay) | ⬜ Planned | Verify parser handles real JSON |
| Test real Apify search (Grailed) | ⬜ Planned | URL-based actor input |
| Test real Apify search (Allegro) | ⬜ Planned | CEE marketplace |
| Test real Apify search (StockX) | ⬜ Planned | Sneaker marketplace |
| Fix parser bugs from real data | ⬜ Planned | Inevitable — real JSON ≠ mock JSON |
| Test search_all (multi-marketplace) | ⬜ Planned | Parallel search across 3+ marketplaces |
| Test search_smart (auto-routing) | ⬜ Planned | Category → marketplace chain |
| Integration tests with real endpoints | ⬜ Planned | Separate test file, skippable |
| Update parsers based on real data | ⬜ Planned | Fix field names, handle edge cases |

### Phase 4: Production Hardening
**Period:** After Phase 3
**Goal:** Make it reliable and pleasant to use

| Task | Status | Details |
|:-----|:------:|:--------|
| Error messages for user (not tracebacks) | ⬜ Planned | Friendly error formatting |
| Price normalization (EUR/USD/PLN/UAH) | ⬜ Planned | Unified currency display |
| Result deduplication | ⬜ Planned | Same item on Vinted + Vestiaire |
| Structured logging (JSON) | ⬜ Planned | Debug without print() |
| Rate limiting per Apify actor | ⬜ Planned | Respect Apify plan limits |
| Data retention / cleanup | ⬜ Planned | SQLite DB grows forever → auto-cleanup |
| Search result caching (5-min TTL) | ⬜ Planned | Don't re-query for same search |

### Phase 5: Intelligence (Future)
**Period:** After Phase 4
**Goal:** Make the tool SMART — not just search, but analyze

| Task | Status | Details |
|:-----|:------:|:--------|
| Price trend analysis | ⬜ Planned | Historical price data from SQLite |
| Deal scoring (cross-marketplace comparison) | ⬜ Planned | "This item is 30% cheaper on Vinted vs eBay" |
| More marketplaces (Mercari, Poshmark, Wallapop) | ⬜ Planned | Expand to US + Spain |
| Photo-based search | ⬜ Planned | Upload photo → find similar items |
| Notification system | ⬜ Planned | "New Nike Air Max under $50 found!" |

---

## ARCHITECTURE

### System Architecture
```
User → Claude Code/Desktop → MCP Server (STDIO) → Providers → Marketplaces
                                  ↓
                              SQLite DB (search history)
```

### Provider Architecture
```
BaseMarketplaceProvider (abstract)
├── VintedProvider      (Cookie/Playwright)
├── EbayProvider        (OAuth API)
├── GrailedProvider     (Algolia API)
├── VestiaireProvider   (Cookie)
├── DepopProvider       (Cookie)
└── ApifyProvider       (8 cloud actors)
    ├── vinted    → bebity/vinted-premium-actor
    ├── grailed   → vmscrapers/grailed
    ├── ebay      → dtrungtin/ebay-items-scraper
    ├── vestiaire → parseforge/vestiairecollective-scraper
    ├── depop     → consummate_mandala/depop-listing-scraper
    ├── allegro   → tri_angle/allegro-fast-product-scraper
    ├── olx       → ecomscrape/olx-product-search-scraper
    └── stockx    → ecomscrape/stockx-product-search-scraper
```

### Key Files
| File | Lines | Purpose |
|:-----|------:|:--------|
| providers.py | ~1950 | All provider implementations |
| tools.py | ~870 | 16 MCP tools |
| types.py | ~199 | Shared dataclasses |
| db.py | ~310 | SQLite persistence |
| main.py | ~78 | FastMCP entry point |

---

## RISKS & BLOCKERS

### Active Risks

| Risk | Probability | Impact | Mitigation |
|:-----|:----------:|:------:|:-----------|
| Apify actors change output format | Medium | High | Version-pin actors, defensive parsing with try/except |
| Apify $29/mo plan rate limits | Medium | Medium | Cache results, respect rate limits, queue requests |
| Real JSON structure differs from mock | High | High | **Phase 3 primary task** — fix parsers from real data |
| MCP server crash on malformed data | Medium | High | Global exception handler, graceful error messages |
| Actor deprecation (removed from Apify Store) | Low | High | Monitor actor health, have alternatives documented |

### Dependencies

| Dependency | Type | Status |
|:-----------|:-----|:------:|
| Apify API Token ($29/mo) | External | ⚠️ Not configured |
| Apify Actor availability | External | ✅ All 8 verified on Store |
| Claude Code MCP protocol | External | ✅ Working |
| Python 3.12 + uv | Internal | ✅ Installed |
| httpx library | Internal | ✅ In pyproject.toml |

### Unknowns
- How will real Apify response times affect UX? (currently 0ms in mocks)
- Will Apify actors handle Ukrainian/Polish queries correctly?
- How many parallel actor runs does $29/mo allow?

---

## DECISIONS LOG

### 2026-02-27 — Architecture: FastMCP + STDIO
**Context:** Needed MCP server for Claude Code integration.
**Options:** (1) HTTP server, (2) FastMCP + STDIO (same as mcp-multi-ai)
**Decision:** Option 2 — proven pattern from mcp-multi-ai project.
**Impact:** Reuse of architecture, faster development.

### 2026-02-27 — Apify as primary scraping engine
**Context:** Direct API keys are hard to get (cookies expire, OAuth complex).
**Options:** (1) Direct APIs only, (2) Apify as fallback, (3) Apify as primary
**Decision:** Option 3 — all 8 marketplaces through Apify actors.
**Impact:** One API token covers everything. $29/mo cost.

### 2026-02-28 — Grailed actor upgrade
**Context:** Original actor (benthepythondev) had 2 users and poor data.
**Decision:** Upgraded to vmscrapers/grailed (43 users, richer output).
**Impact:** Better data quality for grailed searches.

### 2026-02-28 — URL-based vs Parameter-based actors
**Context:** Apify actors accept different input formats.
**Decision:** Marketplace-specific input builders in _build_actor_input().
**Impact:** Each marketplace has correct input format, extensible pattern.

---

## PROGRESS TRACKER

```
Phase 1 (Foundation):      ████████████████████ 100%  ✅
Phase 2 (Apify Expansion): ████████████████████ 100%  ✅
Phase 3 (Real API):        ██░░░░░░░░░░░░░░░░░░  10%  🔄
Phase 4 (Hardening):       ░░░░░░░░░░░░░░░░░░░░   0%  ⬜
Phase 5 (Intelligence):    ░░░░░░░░░░░░░░░░░░░░   0%  ⬜

Total Progress:            ████████░░░░░░░░░░░░  42%
```

---

## IDEAS (Parking Lot)

- [ ] Telegram bot integration (search from Telegram, not just Claude)
- [ ] Price alerts via email/Telegram
- [ ] Browser extension for one-click price comparison
- [ ] AI-powered style recommendations
- [ ] Integration with VintedFlip bot scorer
- [ ] Marketplace health dashboard (web UI)
- [ ] Export results to CSV/Excel
- [ ] Saved searches with auto-refresh
