"""HTTP API wrapper for marketplace search engine.

This is the server-side deployment version (FastAPI).
The MCP STDIO server (main.py) stays for Claude Desktop.
Both share the same providers and search engine.

Endpoints:
- GET  /health              — health check
- GET  /search/{marketplace} — search a single marketplace
- GET  /search-all          — parallel multi-marketplace search
- GET  /search-smart        — auto-route by category
- GET  /compare             — cross-marketplace price comparison
- GET  /marketplaces        — list available marketplaces
- GET  /history             — search history
"""

import os
import sys
import time
import logging
import concurrent.futures

# UTF-8
os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["PYTHONUTF8"] = "1"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("marketplace.api")

from fastapi import FastAPI, Query, HTTPException, Depends, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader

from server.db import get_db
from server.types import SearchParams
from server.providers import (
    get_provider, get_providers, get_available_providers,
    get_health, get_all_health,
    VALID_MARKETPLACES, CATEGORY_ROUTING, MARKETPLACE_REGISTRY,
)

# ==========================================================================
# API KEY AUTHENTICATION
# ==========================================================================
API_KEY = os.environ.get("MARKETPLACE_API_KEY", "")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str = Security(api_key_header)):
    """Verify API key for all protected endpoints."""
    if not API_KEY:
        # No key configured = open access (dev mode)
        return None
    if not api_key or api_key != API_KEY:
        raise HTTPException(
            status_code=403,
            detail="Invalid or missing API key. Set X-API-Key header.",
        )
    return api_key


app = FastAPI(
    title="Marketplace Search API",
    description="Multi-marketplace search engine. Searches eBay, Grailed, Vestiaire, and more via Apify cloud actors.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================================================================
# HELPERS
# =========================================================================

def _items_to_dicts(items):
    """Convert MarketplaceItem list to serializable dicts."""
    return [item.to_dict() for item in items]


def _get_apify_info():
    """Get Apify provider info for fallback routing."""
    providers = get_providers()
    apify = providers.get("apify")
    if apify and apify.is_available():
        return apify, apify.get_supported_marketplaces()
    return None, []


# =========================================================================
# ENDPOINTS
# =========================================================================

@app.get("/health")
def health():
    """Health check."""
    providers = get_providers()
    available = get_available_providers()
    apify, apify_mps = _get_apify_info()
    return {
        "status": "ok",
        "providers_total": len(providers),
        "providers_available": len(available),
        "apify_configured": apify is not None,
        "apify_marketplaces": apify_mps,
        "marketplaces_searchable": list(
            set(available) | (set(apify_mps) if apify else set()) - {"apify"}
        ),
    }


@app.get("/search/{marketplace}")
def search_marketplace(
    marketplace: str,
    query: str = Query(..., min_length=1),
    brand: str = "",
    min_price: float = 0,
    max_price: float = 0,
    condition: str = "",
    size: str = "",
    sort: str = "relevance",
    limit: int = Query(20, ge=1, le=100),
    _key: str = Depends(verify_api_key),
):
    """Search a specific marketplace."""
    providers = get_providers()
    apify, apify_mps = _get_apify_info()

    # Try direct provider first
    provider = providers.get(marketplace)
    use_apify = False

    if provider and provider.is_available():
        params = SearchParams(
            query=query, brand=brand, min_price=min_price,
            max_price=max_price, condition=condition, size=size,
            sort=sort, limit=limit,
        )
    elif apify and marketplace in apify_mps:
        provider = apify
        use_apify = True
        params = SearchParams(
            query=query, category=marketplace, brand=brand,
            min_price=min_price, max_price=max_price, limit=limit,
        )
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Marketplace '{marketplace}' not available. "
                   f"Valid: {', '.join(VALID_MARKETPLACES)}",
        )

    try:
        result = provider.search(params)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

    if result.error:
        return {
            "marketplace": marketplace,
            "query": query,
            "error": result.error,
            "items": [],
            "total_found": 0,
        }

    # Save to DB
    db = get_db()
    mp_label = f"apify:{marketplace}" if use_apify else marketplace
    search_id = db.save_search(
        query=query, marketplace=mp_label, brand=brand or None,
        min_price=min_price if min_price > 0 else None,
        max_price=max_price if max_price > 0 else None,
        condition=condition or None,
        total_results=result.total_found,
        items_returned=len(result.items),
        duration_ms=result.duration_ms,
    )
    if result.items:
        db.save_search_items(search_id, _items_to_dicts(result.items))

    return {
        "marketplace": marketplace,
        "query": query,
        "via_apify": use_apify,
        "total_found": result.total_found,
        "items_returned": len(result.items),
        "duration_ms": result.duration_ms,
        "search_id": search_id,
        "items": _items_to_dicts(result.items),
    }


@app.get("/search-all")
def search_all(
    query: str = Query(..., min_length=1),
    brand: str = "",
    min_price: float = 0,
    max_price: float = 0,
    marketplaces: str = "",
    limit: int = Query(10, ge=1, le=50),
    _key: str = Depends(verify_api_key),
):
    """Search multiple marketplaces in parallel."""
    providers = get_providers()
    available = get_available_providers()
    apify, apify_mps = _get_apify_info()

    if marketplaces:
        target = [m.strip() for m in marketplaces.split(",") if m.strip()]
        target = [
            m for m in target
            if m in available or (m in apify_mps and apify)
        ]
    else:
        target = list(set(available) | (set(apify_mps) if apify else set()))
        target = [m for m in target if m != "apify"]

    if not target:
        raise HTTPException(status_code=400, detail="No marketplaces available")

    TIMEOUT = 120
    results = {}
    start_all = time.monotonic()

    def _call_one(mname):
        try:
            provider = providers.get(mname)
            if provider and provider.is_available():
                params = SearchParams(
                    query=query, brand=brand,
                    min_price=min_price, max_price=max_price, limit=limit,
                )
                return (mname, provider.search(params), False)
            elif apify and mname in apify_mps:
                params = SearchParams(
                    query=query, category=mname, brand=brand,
                    min_price=min_price, max_price=max_price, limit=limit,
                )
                return (mname, apify.search(params), True)
            return (mname, None, False)
        except Exception as e:
            logger.warning(f"search_all failed for {mname}: {e}")
            return (mname, None, False)

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(target), 5)) as ex:
        futures = {ex.submit(_call_one, m): m for m in target}
        done, not_done = concurrent.futures.wait(futures.keys(), timeout=TIMEOUT)
        for f in done:
            mname, result, via_apify = f.result()
            results[mname] = {"result": result, "via_apify": via_apify}
        for f in not_done:
            f.cancel()
            results[futures[f]] = {"result": None, "via_apify": False, "error": "timeout"}

    total_ms = int((time.monotonic() - start_all) * 1000)

    marketplace_results = {}
    total_items = 0
    for mname in sorted(target):
        r = results.get(mname, {})
        res = r.get("result")
        if res and not res.error and res.items:
            marketplace_results[mname] = {
                "items": _items_to_dicts(res.items),
                "total_found": res.total_found,
                "duration_ms": res.duration_ms,
                "via_apify": r.get("via_apify", False),
            }
            total_items += len(res.items)
        else:
            error = res.error if res and res.error else r.get("error", "no data")
            marketplace_results[mname] = {"items": [], "error": error}

    return {
        "query": query,
        "total_items": total_items,
        "total_ms": total_ms,
        "marketplaces": marketplace_results,
    }


@app.get("/search-smart")
def search_smart(
    query: str = Query(..., min_length=1),
    category: str = "general",
    brand: str = "",
    min_price: float = 0,
    max_price: float = 0,
    limit: int = Query(20, ge=1, le=100),
    _key: str = Depends(verify_api_key),
):
    """Smart-route search to best marketplace for category."""
    if category not in CATEGORY_ROUTING:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown category '{category}'. "
                   f"Available: {', '.join(CATEGORY_ROUTING.keys())}",
        )

    providers = get_providers()
    apify, apify_mps = _get_apify_info()
    route_chain = CATEGORY_ROUTING[category]

    chosen = None
    use_apify = False
    for mp_name, region in route_chain:
        if mp_name == "apify":
            continue
        direct = providers.get(mp_name)
        if direct and direct.is_available():
            chosen = (mp_name, region)
            break
        if apify and mp_name in apify_mps:
            chosen = (mp_name, region)
            use_apify = True
            break

    if not chosen:
        raise HTTPException(status_code=503, detail=f"No marketplace available for '{category}'")

    mp_name, region = chosen
    if use_apify:
        params = SearchParams(
            query=query, category=mp_name, brand=brand,
            min_price=min_price, max_price=max_price, limit=limit,
        )
        result = apify.search(params)
    else:
        provider = providers[mp_name]
        params = SearchParams(
            query=query, brand=brand, min_price=min_price,
            max_price=max_price, limit=limit, region=region,
        )
        result = provider.search(params)

    return {
        "category": category,
        "routed_to": mp_name,
        "via_apify": use_apify,
        "query": query,
        "total_found": result.total_found,
        "duration_ms": result.duration_ms,
        "error": result.error or None,
        "items": _items_to_dicts(result.items) if not result.error else [],
    }


@app.get("/compare")
def compare_prices(
    query: str = Query(..., min_length=1),
    brand: str = "",
    marketplaces: str = "",
    _key: str = Depends(verify_api_key),
):
    """Compare prices across multiple marketplaces."""
    providers = get_providers()
    available = get_available_providers()
    apify, apify_mps = _get_apify_info()

    if marketplaces:
        target = [
            m.strip() for m in marketplaces.split(",")
            if m.strip() in available or (m.strip() in apify_mps and apify)
        ]
    else:
        target = list(set(available) | (set(apify_mps) if apify else set()))
        target = [m for m in target if m != "apify"]

    if len(target) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 marketplaces")

    results = {}
    TIMEOUT = 120

    def _one(mname):
        try:
            p = providers.get(mname)
            if p and p.is_available():
                return (mname, p.search(SearchParams(query=query, brand=brand, limit=10)))
            elif apify and mname in apify_mps:
                return (mname, apify.search(SearchParams(query=query, category=mname, brand=brand, limit=10)))
            return (mname, None)
        except Exception:
            return (mname, None)

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(target), 5)) as ex:
        futures = {ex.submit(_one, m): m for m in target}
        done, _ = concurrent.futures.wait(futures.keys(), timeout=TIMEOUT)
        for f in done:
            mname, result = f.result()
            results[mname] = result

    comparison = {}
    for mname in sorted(target):
        r = results.get(mname)
        if not r or r.error or not r.items:
            comparison[mname] = {"error": r.error if r and r.error else "no data"}
            continue
        prices = [i.price for i in r.items if i.price > 0]
        if not prices:
            comparison[mname] = {"items": len(r.items), "prices": 0}
            continue
        comparison[mname] = {
            "min": round(min(prices), 2),
            "max": round(max(prices), 2),
            "avg": round(sum(prices) / len(prices), 2),
            "items": len(prices),
            "currency": r.items[0].currency,
        }

    return {"query": query, "brand": brand, "comparison": comparison}


@app.get("/marketplaces")
def list_marketplaces(_key: str = Depends(verify_api_key)):
    """List all available marketplaces with status."""
    providers = get_providers()
    available = get_available_providers()
    apify, apify_mps = _get_apify_info()

    result = {}
    shown = set()
    for name, p in providers.items():
        if name == "apify":
            continue
        shown.add(name)
        direct_ok = p.is_available()
        apify_ok = name in apify_mps and apify is not None
        cap = MARKETPLACE_REGISTRY.get(name)
        result[name] = {
            "status": "direct" if direct_ok else ("apify" if apify_ok else "offline"),
            "categories": cap.categories if cap else [],
            "regions": cap.regions if cap else [],
            "strengths": cap.strengths if cap else [],
        }

    for mp in apify_mps:
        if mp not in shown:
            cap = MARKETPLACE_REGISTRY.get(mp)
            result[mp] = {
                "status": "apify",
                "categories": cap.categories if cap else [],
                "regions": cap.regions if cap else [],
                "strengths": cap.strengths if cap else [],
            }

    return {
        "total_searchable": len([v for v in result.values() if v["status"] != "offline"]),
        "marketplaces": result,
    }


@app.get("/history")
def search_history(marketplace: str = "", limit: int = 20, _key: str = Depends(verify_api_key)):
    """View recent search history."""
    db = get_db()
    searches = db.get_search_history(marketplace=marketplace or None, limit=limit)
    return {"searches": searches}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
