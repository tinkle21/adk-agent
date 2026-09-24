"""Buy listings from realestate.com.au search result pages.

The search page embeds its results as JSON (window.ArgonautExchange). Rather
than depending on one exact path inside that blob, we look for any object that
has the shape of a listing (an id, an address and a price display), which
survives most front-end refactors.
"""

from __future__ import annotations

import re
import urllib.parse

from ..config import SearchSettings
from ..models import Listing
from .http import Fetcher, dig, embedded_json, walk

BASE = "https://www.realestate.com.au"


def search_url(location: str, search: SearchSettings, page: int = 1) -> str:
    parts = ["property", "-".join(search.property_types or ["house"])]
    if search.min_bedrooms:
        parts.append(f"with-{search.min_bedrooms}-bedrooms")
    if search.min_price and search.max_price:
        parts.append(f"between-{search.min_price}-{search.max_price}")
    elif search.max_price:
        parts.append(f"between-0-{search.max_price}")
    elif search.min_price:
        parts.append(f"between-{search.min_price}-any")
    slug = "-".join(parts)
    where = urllib.parse.quote(location.strip().lower().replace(" ", "+"), safe="+,")
    return f"{BASE}/buy/{slug}-in-{where}/list-{page}?activeSort=list-date&includeSurrounding=false"


def _int(value) -> int | None:
    if isinstance(value, dict):
        value = value.get("value")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _find_profile_link(obj) -> str | None:
    stack = [obj]
    while stack:
        item = stack.pop()
        if isinstance(item, str) and "property.com.au/" in item and "-pid-" in item:
            return item
        if isinstance(item, dict):
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    return None


def _to_listing(node: dict) -> Listing | None:
    price_text = dig(node, "price", "display")
    address = node.get("address")
    listing_id = node.get("id") or node.get("listingId")
    if not (isinstance(price_text, str) and isinstance(address, dict) and listing_id):
        return None
    full = dig(address, "display", "fullAddress") or dig(address, "display", "shortAddress")
    suburb = address.get("suburb") or ""
    state = (address.get("state") or "").upper()
    postcode = address.get("postcode") or ""
    if not full:
        street = address.get("streetAddress") or ""
        full = ", ".join(p for p in (street, f"{suburb} {state} {postcode}".strip()) if p)
    elif suburb and suburb.lower() not in full.lower():
        full = f"{full}, {suburb} {state} {postcode}".strip()
    url = dig(node, "_links", "canonical", "href") or f"{BASE}/{listing_id}"
    if url.startswith("/"):
        url = BASE + url
    features = node.get("generalFeatures") or {}
    return Listing(
        listing_id=str(listing_id),
        address=full,
        url=url,
        price_text=price_text,
        suburb=suburb,
        state=state,
        postcode=str(postcode),
        property_type=dig(node, "propertyType", "display") or dig(node, "propertyType", "id") or "",
        bedrooms=_int(features.get("bedrooms")),
        bathrooms=_int(features.get("bathrooms")),
        parking=_int(features.get("parkingSpaces")),
        property_profile_url=_find_profile_link(node),
    )


def parse_search_page(html: str) -> list[Listing]:
    found: dict[str, Listing] = {}
    for blob in embedded_json(html):
        for node in walk(blob):
            listing = _to_listing(node)
            if listing and listing.listing_id not in found:
                found[listing.listing_id] = listing
    return list(found.values())


class RealestateSource:
    def __init__(self, fetcher: Fetcher, search: SearchSettings):
        self.fetcher = fetcher
        self.search = search

    def listings_for(self, location: str) -> list[Listing]:
        results: dict[str, Listing] = {}
        for page in range(1, self.search.max_pages + 1):
            page_listings = parse_search_page(self.fetcher.get(search_url(location, self.search, page)))
            new = [l for l in page_listings if l.listing_id not in results]
            if not new:
                break
            results.update((l.listing_id, l) for l in new)
        return list(results.values())

    def listing(self, url: str) -> Listing | None:
        """A single listing from its page (which also embeds 'similar' listings)."""
        listings = parse_search_page(self.fetcher.get(url))
        wanted = re.search(r"(\d{6,})/?(?:[?#].*)?$", url)
        for listing in listings:
            if wanted and listing.listing_id == wanted.group(1):
                return listing
        return listings[0] if listings else None
