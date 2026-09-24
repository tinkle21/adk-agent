"""Markdown and JSON output for a scan."""

from __future__ import annotations

import json
from pathlib import Path

from .config import Criteria
from .finance import breakeven_weekly_rent
from .models import Evaluation


def _row(e: Evaluation) -> str:
    l, v = e.listing, e.valuation
    return (
        f"| [{l.address}]({l.url}) | {l.property_type or '-'} | {l.bedrooms or '-'} | "
        f"{l.price_text} | ${v.estimated_value:,.0f} ({v.confidence}) | {e.price_gap:+.1%} | "
        f"${v.weekly_rent_estimate or 0:,.0f}/wk | ${e.monthly_repayment:,.0f} | "
        f"{(e.rent_coverage or 0):.0%} | {(e.gross_yield or 0):.2%} |"
    )


_HEADER = (
    "| Property | Type | Beds | Asking | property.com.au estimate | Price vs est. | Rent est. "
    "| Repayment /mo | Rent covers | Gross yield |\n"
    "|---|---|---|---|---|---|---|---|---|---|"
)


def render_markdown(
    evaluations: list[Evaluation], criteria: Criteria, scanned_at: str, errors: list[str], new_ids: set[str]
) -> str:
    passed = [e for e in evaluations if e.passed]
    near = [e for e in evaluations if e.near_miss]
    lines = [
        f"# Investment property scan - {scanned_at}",
        "",
        f"Criteria: asking price within ±{criteria.price_tolerance:.0%} of the property.com.au estimate, "
        f"estimate confidence {'/'.join(criteria.accepted_confidence)}, and estimated rent at least "
        f"{criteria.min_rent_coverage:.0%} of the repayment on a {1 - criteria.deposit_pct:.0%} loan at "
        f"{criteria.interest_rate:.2%} over {criteria.loan_term_years} years.",
        "",
        f"Listings checked: {len(evaluations)} · Matches: {len(passed)} · Near misses: {len(near)}",
        "",
        "## Matches",
        "",
    ]
    if passed:
        lines += [_HEADER] + [_row(e) + (" 🆕" if e.listing.listing_id in new_ids else "") for e in passed]
    else:
        lines.append("None this scan.")
    lines += ["", "## Near misses (fail one rule by a small margin)", ""]
    if near:
        lines += [_HEADER] + [_row(e) for e in near]
        lines += ["", *[f"- {e.listing.address}: {'; '.join(e.reasons)}" for e in near]]
    else:
        lines.append("None.")
    if evaluations:
        sample = evaluations[0].asking_price or 500_000
        lines += [
            "",
            "## Rule of thumb",
            "",
            f"At these settings a ${sample:,.0f} property needs about "
            f"${breakeven_weekly_rent(sample, criteria.deposit_pct, criteria.interest_rate, criteria.loan_term_years):,.0f}"
            f"/week rent to cover the repayment (a {52 * breakeven_weekly_rent(1, criteria.deposit_pct, criteria.interest_rate, criteria.loan_term_years):.2%} gross yield).",
        ]
    if errors:
        lines += ["", "## Problems during the scan", "", *[f"- {err}" for err in errors]]
    lines += [
        "",
        "_Estimates are automated (PropTrack via property.com.au) and exclude strata, rates, "
        "insurance, management fees and vacancy. Not financial advice - verify before acting._",
    ]
    return "\n".join(lines) + "\n"


def write_reports(out_dir: Path, stamp: str, markdown: str, evaluations: list[Evaluation]) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / f"{stamp}.md"
    json_path = out_dir / f"{stamp}.json"
    md_path.write_text(markdown)
    json_path.write_text(json.dumps([e.to_dict() for e in evaluations], indent=2))
    (out_dir / "latest.md").write_text(markdown)
    return md_path, json_path
