"""Shared types for marketplace search MCP server.

All marketplace providers return these standardized types,
regardless of the underlying API format.
"""

from dataclasses import dataclass, field
from enum import Enum


# =============================================================================
# ENUMS
# =============================================================================

class ItemCondition(str, Enum):
    """Standardized condition across marketplaces."""
    NEW_WITH_TAGS = "new_with_tags"
    NEW_WITHOUT_TAGS = "new_without_tags"
    LIKE_NEW = "like_new"
    VERY_GOOD = "very_good"
    GOOD = "good"
    FAIR = "fair"
    POOR = "poor"
    UNKNOWN = "unknown"


class SortOrder(str, Enum):
    """Standardized sort options."""
    RELEVANCE = "relevance"
    PRICE_ASC = "price_asc"
    PRICE_DESC = "price_desc"
    NEWEST = "newest"
    POPULAR = "popular"


class ItemCategory(str, Enum):
    """Item categories for smart routing."""
    CLOTHING = "clothing"
    SHOES = "shoes"
    ACCESSORIES = "accessories"
    BAGS = "bags"
    LUXURY = "luxury"
    STREETWEAR = "streetwear"
    VINTAGE = "vintage"
    ELECTRONICS = "electronics"
    FURNITURE = "furniture"
    SPORTS = "sports"
    KIDS = "kids"
    HOME = "home"
    GENERAL = "general"


# =============================================================================
# SEARCH PARAMS (marketplace-agnostic)
# =============================================================================

@dataclass
class SearchParams:
    """Universal search parameters for any marketplace.

    Marketplace providers map these to their API-specific formats.
    """
    query: str
    category: str = ""
    brand: str = ""
    min_price: float = 0.0
    max_price: float = 0.0
    condition: str = ""       # ItemCondition value or raw string
    size: str = ""
    color: str = ""
    sort: str = "relevance"   # SortOrder value
    limit: int = 20
    page: int = 1
    region: str = ""          # "EU", "US", "UK", or specific country code
    currency: str = ""        # ISO 4217 code: "EUR", "USD", "GBP"


# =============================================================================
# SEARCH RESULTS
# =============================================================================

@dataclass
class MarketplaceItem:
    """A single item from any marketplace.

    Standardized format — all marketplace providers return this.
    """
    # Identity
    item_id: str              # Marketplace-specific ID
    marketplace: str          # "vinted", "ebay", "grailed", etc.
    title: str
    url: str

    # Pricing
    price: float
    currency: str

    # Details
    brand: str = ""
    size: str = ""
    condition: str = ""
    color: str = ""
    description: str = ""
    category: str = ""

    # Media
    image_url: str = ""
    image_urls: list[str] = field(default_factory=list)

    # Seller
    seller_name: str = ""
    seller_rating: float = 0.0
    seller_id: str = ""

    # Engagement
    favorites: int = 0
    views: int = 0

    # Metadata
    listed_at: str = ""
    location: str = ""
    shipping_price: float = 0.0
    promoted: bool = False

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "item_id": self.item_id,
            "marketplace": self.marketplace,
            "title": self.title,
            "url": self.url,
            "price": self.price,
            "currency": self.currency,
            "brand": self.brand,
            "size": self.size,
            "condition": self.condition,
            "color": self.color,
            "image_url": self.image_url,
            "seller_name": self.seller_name,
            "seller_rating": self.seller_rating,
            "favorites": self.favorites,
            "views": self.views,
            "listed_at": self.listed_at,
            "location": self.location,
        }


@dataclass
class SearchResult:
    """Result of a marketplace search."""
    items: list[MarketplaceItem]
    total_found: int
    marketplace: str
    query: str
    page: int = 1
    pages_total: int = 1
    duration_ms: int = 0

    def to_summary(self) -> str:
        """One-line summary for logs."""
        return (
            f"{self.marketplace}: {len(self.items)} items "
            f"({self.total_found} total) in {self.duration_ms}ms"
        )


@dataclass
class ItemDetails:
    """Detailed item info (from get_item API call)."""
    item: MarketplaceItem
    description: str = ""
    all_photos: list[str] = field(default_factory=list)
    seller_total_items: int = 0
    seller_total_sales: int = 0
    seller_joined: str = ""
    seller_verified: bool = False
    shipping_options: list[dict] = field(default_factory=list)
    raw_data: dict = field(default_factory=dict)


# =============================================================================
# MARKETPLACE CAPABILITY REGISTRY
# =============================================================================

@dataclass
class MarketplaceCapability:
    """Metadata about a marketplace's capabilities."""
    categories: list[str] = field(default_factory=list)
    regions: list[str] = field(default_factory=list)
    has_api: bool = False
    requires_auth: str = "api_key"   # "api_key", "cookies", "oauth", "none"
    max_results_per_page: int = 50
    supports_filters: list[str] = field(default_factory=lambda: [
        "query", "price", "brand", "condition", "sort"
    ])
    rate_limit_rpm: int = 60
    strengths: list[str] = field(default_factory=list)
    notes: str = ""
