"""MCP Marketplace Search Server — Entry Point.

Provides Claude Code with tools to search 9 marketplace platforms
(Vinted, eBay, Grailed, Vestiaire, Depop + Allegro, OLX, StockX via Apify)
with persistent search history stored in SQLite.
Category-based smart routing, parallel search, price comparison.

CRITICAL: This is a STDIO MCP server. NEVER use print() — it corrupts the
JSON-RPC protocol. All logging MUST go to sys.stderr.

Architecture mirrors mcp-multi-ai:
- BaseMarketplaceProvider (abstract) with health tracking + circuit breaker
- 5 direct providers: Vinted, eBay, Grailed, Vestiaire, Depop
- ApifyProvider with 8 cloud actors (primary scraping engine)
- 3 Apify-only marketplaces: Allegro, OLX, StockX
- 16 MCP tools: 9 search + 3 orchestrator + 2 item + 2 utility
- SQLite persistence for search history
- Category-based smart routing (like task routing in multi-ai)

Adding a new marketplace (Apify-only, recommended):
1. Add actor to ApifyProvider.ACTOR_MAP in providers.py
2. Add _build_actor_input + _parse_result case
3. Add to MARKETPLACE_REGISTRY, CATEGORY_ROUTING, VALID_MARKETPLACES
4. Add search tool in tools.py using _search_via_apify helper
"""

import os
import sys

# CRITICAL: Force UTF-8 on Windows
os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["PYTHONUTF8"] = "1"
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import logging

# Configure logging to stderr BEFORE any other imports
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("marketplace")

from mcp.server.fastmcp import FastMCP
from server.tools import register_tools

# Create the MCP server
mcp = FastMCP(
    "marketplace-search",
    instructions=(
        "Marketplace search server for finding deals across 9 platforms. "
        "Direct search: search_vinted, search_ebay, search_grailed, search_vestiaire, search_depop. "
        "Apify-only: search_allegro (CEE), search_olx (classifieds), search_stockx (sneakers). "
        "Meta: search_apify (any of 8 marketplaces via Apify cloud actors). "
        "Orchestrator: search_all (parallel), search_smart (auto-route by category). "
        "Utils: compare_prices, marketplace_health, get_item_details, search_history, list_marketplaces. "
        "All searches are persisted with full history in SQLite."
    ),
)

# Register all 16 tools
register_tools(mcp)

logger.info("Marketplace Search MCP server initialized with 16 tools")


def main():
    """Run the MCP server via STDIO transport."""
    logger.info("Starting Marketplace Search MCP server...")
    mcp.run()


if __name__ == "__main__":
    main()
