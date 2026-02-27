"""MCP Marketplace Search Server — Entry Point.

Provides Claude Code with tools to search 5 marketplace platforms
(Vinted, eBay, Grailed, Vestiaire, Depop) with persistent search history
stored in SQLite. Category-based smart routing, parallel search, price comparison.

CRITICAL: This is a STDIO MCP server. NEVER use print() — it corrupts the
JSON-RPC protocol. All logging MUST go to sys.stderr.

Architecture mirrors mcp-multi-ai:
- BaseMarketplaceProvider (abstract) with health tracking + circuit breaker
- 5 concrete providers: Vinted, eBay, Grailed, Vestiaire, Depop
- 12 MCP tools: 5 search + 3 orchestrator + 2 item + 2 utility
- SQLite persistence for search history
- Category-based smart routing (like task routing in multi-ai)

Adding a new marketplace:
1. Create provider class in providers.py extending BaseMarketplaceProvider
2. Add to PROVIDER_CLASSES, MARKETPLACE_REGISTRY, CATEGORY_ROUTING
3. Set API key in environment variables
4. Done — tools auto-discover new providers
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
        "Marketplace search server for finding deals across 5 platforms. "
        "Use search_vinted, search_ebay, search_grailed, search_vestiaire, search_depop "
        "to search specific marketplaces. "
        "Use search_all to search multiple marketplaces in parallel. "
        "Use search_smart for auto-routing to the best marketplace by item category. "
        "Use compare_prices to compare prices across platforms. "
        "Use marketplace_health to check provider status. "
        "All searches are persisted with full history."
    ),
)

# Register all 12 tools
register_tools(mcp)

logger.info("Marketplace Search MCP server initialized with 12 tools")


def main():
    """Run the MCP server via STDIO transport."""
    logger.info("Starting Marketplace Search MCP server...")
    mcp.run()


if __name__ == "__main__":
    main()
