"""Runs one full market scan. This is what the every-2-days job executes.

    python -m property_agent.scan                      # live scan
    python -m property_agent.scan --offline sample.json  # no network, for testing
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import ROOT, Settings, load_settings
from .models import Evaluation, Listing, Valuation
from .report import render_markdown, write_reports
from .screener import evaluate, rank

log = logging.getLogger("property_agent")

REPORTS_DIR = ROOT / "reports"
STATE_DIR = ROOT / "data"
VALUATION_CACHE_DAYS = 14  # PropTrack estimates refresh roughly monthly


@dataclass
class ScanResult:
    evaluations: list[Evaluation]
    new_ids: set[str]
    errors: list[str] = field(default_factory=list)
    report_path: Path | None = None
    markdown: str = ""

    @property
    def matches(self) -> list[Evaluation]:
        return [e for e in self.evaluations if e.passed]

    @property
    def near_misses(self) -> list[Evaluation]:
        return [e for e in self.evaluations if e.near_miss]


class _JsonStore:
    def __init__(self, path: Path):
        self.path = path
        self.data = json.loads(path.read_text()) if path.exists() else {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2, sort_keys=True))


class OfflineSource:
    """Listings and valuations from a JSON file (tests, demos, manual data)."""

    def __init__(self, path: str | Path):
        raw = json.loads(Path(path).read_text())
        self._listings = [Listing(**item) for item in raw["listings"]]
        self._valuations = {k: Valuation(**v) for k, v in raw.get("valuations", {}).items()}

    def listings_for(self, location: str) -> list[Listing]:
        return self._listings

    def valuation(self, listing: Listing) -> Valuation | None:
        return self._valuations.get(listing.listing_id)


def _gather_live(settings: Settings, errors: list[str]):
    from .sources.http import BlockedError, Fetcher
    from .sources.property_com_au import PropertyComAuSource
    from .sources.realestate import RealestateSource

    fetcher = Fetcher(settings.fetch)
    listing_source = RealestateSource(fetcher, settings.search)
    valuation_source = PropertyComAuSource(fetcher)
    listings: dict[str, Listing] = {}
    for location in settings.search.locations:
        try:
            found = listing_source.listings_for(location)
            log.info("%s: %d listings", location, len(found))
            listings.update((l.listing_id, l) for l in found)
        except BlockedError as exc:
            errors.append(str(exc))
            log.error("%s", exc)
            break  # every further request would be blocked too
        except Exception as exc:  # keep scanning other locations
            errors.append(f"{location}: {exc}")
            log.exception("search failed for %s", location)
    return list(listings.values()), valuation_source, fetcher


def run_scan(settings: Settings | None = None, offline: str | Path | None = None, write: bool = True) -> ScanResult:
    settings = settings or load_settings()
    errors: list[str] = []
    fetcher = None
    if offline:
        source = OfflineSource(offline)
        listings = source.listings_for("")
        valuation_source = source
    else:
        listings, valuation_source, fetcher = _gather_live(settings, errors)

    seen = _JsonStore(STATE_DIR / "seen_listings.json")
    cache = _JsonStore(STATE_DIR / "valuation_cache.json")
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=VALUATION_CACHE_DAYS)).isoformat()

    evaluations = []
    try:
        for listing in listings:
            cached = cache.data.get(listing.listing_id)
            valuation = None
            if cached and cached["fetched_at"] >= cutoff and not offline:
                valuation = Valuation(**cached["valuation"]) if cached["valuation"] else None
            else:
                try:
                    valuation = valuation_source.valuation(listing)
                    if not offline:
                        cache.data[listing.listing_id] = {
                            "fetched_at": now.isoformat(),
                            "valuation": asdict(valuation) if valuation else None,
                        }
                except Exception as exc:
                    errors.append(f"Valuation for {listing.address}: {exc}")
                    log.warning("valuation failed for %s: %s", listing.address, exc)
                    if type(exc).__name__ == "BlockedError":
                        break
            evaluations.append(evaluate(listing, valuation, settings.criteria))
    finally:
        if fetcher:
            fetcher.close()

    evaluations = rank(evaluations)
    new_ids = {e.listing.listing_id for e in evaluations if e.listing.listing_id not in seen.data}
    result = ScanResult(evaluations, new_ids, errors)

    stamp = now.strftime("%Y-%m-%d")
    result.markdown = render_markdown(evaluations, settings.criteria, now.strftime("%Y-%m-%d %H:%M UTC"), errors, new_ids)
    if write:
        result.report_path, _ = write_reports(REPORTS_DIR, stamp, result.markdown, evaluations)
        for listing_id in new_ids:
            seen.data[listing_id] = now.isoformat()
        seen.save()
        if not offline:
            cache.save()
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan for Australian investment properties.")
    parser.add_argument("--config", help="Path to config.toml")
    parser.add_argument("--offline", help="JSON file of listings/valuations instead of scraping")
    parser.add_argument("--no-write", action="store_true", help="Print the report without saving it")
    parser.add_argument("--fail-on-errors", action="store_true", help="Exit 1 if any fetch failed")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    result = run_scan(load_settings(args.config), offline=args.offline, write=not args.no_write)
    print(result.markdown)
    if result.report_path:
        log.info("Report written to %s", result.report_path)
    return 1 if (args.fail_on_errors and result.errors) else 0


if __name__ == "__main__":
    sys.exit(main())
