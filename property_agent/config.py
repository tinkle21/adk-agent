"""Loads config.toml into typed settings."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = ROOT / "config.toml"


@dataclass
class SearchSettings:
    locations: list[str] = field(default_factory=list)
    property_types: list[str] = field(default_factory=lambda: ["house"])
    min_price: int | None = None
    max_price: int | None = None
    min_bedrooms: int | None = None
    max_pages: int = 1


@dataclass
class Criteria:
    price_tolerance: float = 0.05
    accepted_confidence: list[str] = field(default_factory=lambda: ["high"])
    deposit_pct: float = 0.20
    interest_rate: float = 0.061
    loan_term_years: int = 30
    min_rent_coverage: float = 1.0
    range_price_basis: str = "high"
    near_miss_margin: float = 0.05


@dataclass
class FetchSettings:
    delay_seconds: float = 3.0
    timeout_seconds: float = 60
    url_template: str | None = None


@dataclass
class Settings:
    search: SearchSettings
    criteria: Criteria
    fetch: FetchSettings


def load_settings(path: str | Path | None = None) -> Settings:
    path = Path(path or os.environ.get("PROPERTY_AGENT_CONFIG") or DEFAULT_CONFIG_PATH)
    raw = tomllib.loads(path.read_text()) if path.exists() else {}
    fetch = FetchSettings(**raw.get("fetch", {}))
    fetch.url_template = os.environ.get("FETCH_URL_TEMPLATE") or fetch.url_template
    return Settings(
        search=SearchSettings(**raw.get("search", {})),
        criteria=Criteria(**raw.get("criteria", {})),
        fetch=fetch,
    )
