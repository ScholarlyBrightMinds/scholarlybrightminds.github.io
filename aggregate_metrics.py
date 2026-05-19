#!/usr/bin/env python3
"""Aggregate live metrics + recent publications from every member site and
bake them into index.html.

Runs in the hub repo's weekly workflow (Mondays at 06:00 UTC — one hour after
every member workflow finishes refreshing their own serpapi.json).

Output is purely additive on the page:
  • A "live stats" strip in the hero, between the tagline and the existing
    "Currently · 4 active members" pill.
  • A small metric pill on every member card: "N pubs · M cites · h-index K".
  • A "Latest across the hub" section at the bottom listing the most recent
    publication per member (sorted by year, newest first).

All values are baked into static HTML at workflow time so Googlebot sees the
final numbers on its first crawl — no client-side fetch in the critical path.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parent
INDEX_HTML = REPO_ROOT / "index.html"

# Each entry maps a member repo on GitHub to the URL slug we use under
# scholarlybrightminds.github.io. They happen to be identical today; the
# split is here so a future custom slug doesn't break the fetcher.
MEMBERS: list[dict[str, str]] = [
    {"repo": "abdallahabouhajal",  "slug": "abdallahabouhajal",  "name": "Abdallah Abou Hajal"},
    {"repo": "molhamsakkal",       "slug": "molhamsakkal",       "name": "Molham Sakkal"},
    {"repo": "Rahafalzeer",        "slug": "Rahafalzeer",        "name": "Rahaf Al Zeer"},
    {"repo": "ahmadalmeslamani",   "slug": "ahmadalmeslamani",   "name": "Ahmad Z. Al Meslamani"},
]

RAW_BASE = "https://raw.githubusercontent.com/ScholarlyBrightMinds"


# ─────────────────────────────────────────────────────────────────────────
# Fetch helpers — small wrapper around urllib so the workflow doesn't need
# extra dependencies. Times out after 15s per request; never raises (caller
# decides what to do with a None).
# ─────────────────────────────────────────────────────────────────────────
def _fetch_json(url: str) -> Any | None:
    try:
        req = Request(url, headers={"User-Agent": "sbm-aggregate/1.0"})
        with urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"  fetch failed: {url} ({e})", file=sys.stderr)
        return None


def fetch_member(member: dict[str, str]) -> dict[str, Any]:
    """Pull a member's metrics.json + serpapi.json from raw.githubusercontent.

    Returns a normalized dict — fields default to safe zeros if a fetch
    fails so the build never crashes on a single broken member."""
    repo = member["repo"]
    metrics_url = f"{RAW_BASE}/{repo}/main/data/serpapi/metrics.json"
    pubs_url    = f"{RAW_BASE}/{repo}/main/data/serpapi/serpapi.json"

    print(f"  fetching {repo}…")
    metrics = _fetch_json(metrics_url) or {}
    pubs    = _fetch_json(pubs_url) or []

    # Sort newest first so member["latest"] is always the most recent paper.
    pubs_sorted = sorted(
        (p for p in pubs if isinstance(p, dict)),
        key=lambda p: (int(p.get("year") or 0), p.get("title") or ""),
        reverse=True,
    )

    return {
        **member,
        "total_documents": int(metrics.get("total_documents") or 0),
        "total_citations": int(metrics.get("total_citations") or 0),
        "h_index":         int(metrics.get("h_index") or 0),
        "latest":          pubs_sorted[0] if pubs_sorted else None,
        "pubs":            pubs_sorted,
    }


# ─────────────────────────────────────────────────────────────────────────
# HTML rendering — every fragment is wrapped in clearly-named comment
# markers so re-running the script idempotently replaces only the block it
# owns, never the surrounding hand-written sections.
# ─────────────────────────────────────────────────────────────────────────
def _format_int(n: int) -> str:
    return f"{n:,}"


def render_org_stats(members: list[dict[str, Any]]) -> str:
    total_pubs   = sum(m["total_documents"] for m in members)
    total_cites  = sum(m["total_citations"] for m in members)
    max_h        = max((m["h_index"] for m in members), default=0)
    return (
        '<div class="org-stats" data-aggregated="true">'
        f'<span class="org-stat"><strong>{len(members)}</strong> researchers</span>'
        f'<span class="org-stat"><strong>{_format_int(total_pubs)}</strong> publications</span>'
        f'<span class="org-stat"><strong>{_format_int(total_cites)}</strong> citations</span>'
        f'<span class="org-stat"><strong>h-index {max_h}</strong> (top)</span>'
        f'</div>'
    )


def render_member_pill(member: dict[str, Any]) -> str:
    if member["total_documents"] == 0:
        return ""
    pubs_word  = "pub"  if member["total_documents"] == 1 else "pubs"
    cites_word = "cite" if member["total_citations"] == 1 else "cites"
    return (
        '<div class="member-stats">'
        f'<span class="ms"><strong>{member["total_documents"]}</strong> {pubs_word}</span>'
        f'<span class="ms-dot">·</span>'
        f'<span class="ms"><strong>{_format_int(member["total_citations"])}</strong> {cites_word}</span>'
        f'<span class="ms-dot">·</span>'
        f'<span class="ms">h-index <strong>{member["h_index"]}</strong></span>'
        f'</div>'
    )


def render_latest_section(members: list[dict[str, Any]]) -> str:
    """Show one newest paper per member, sorted year-desc across the group."""
    items: list[tuple[dict[str, Any], dict[str, Any]]] = [
        (m, m["latest"]) for m in members if m["latest"]
    ]
    items.sort(
        key=lambda pair: (int(pair[1].get("year") or 0), pair[1].get("title") or ""),
        reverse=True,
    )
    if not items:
        return ""

    rows = []
    for m, pub in items:
        title  = (pub.get("title") or "").strip()
        venue  = (pub.get("venue") or "").strip()
        link   = pub.get("link") or f"https://scholarlybrightminds.github.io/{m['slug']}/publications.html"
        # venue from SerpApi already includes the year at the end
        # (e.g. "Journal of X 12 (3), 45-67, 2024"), so we don't append year
        # separately — that produced "..., 2024, 2024" on the first pass.
        rows.append(
            '<li class="latest-row">'
            f'<a class="latest-title" href="{link}" target="_blank" rel="noopener">{title}</a>'
            '<span class="latest-meta">'
            f'<a class="latest-author" href="https://scholarlybrightminds.github.io/{m["slug"]}/">{m["name"]}</a>'
            f' &middot; {venue}'
            '</span>'
            '</li>'
        )
    return (
        '<section class="section latest-section" data-aggregated="true">'
        '<p class="kicker">Latest work</p>'
        '<h2 class="section-title">Recent across <em>the hub</em>.</h2>'
        '<p class="section-lede">One newest publication per member, refreshed every Monday.</p>'
        '<ul class="latest-list">' + "\n".join(rows) + '</ul>'
        '</section>'
    )


# ─────────────────────────────────────────────────────────────────────────
# Patch: index.html
# ─────────────────────────────────────────────────────────────────────────
ORG_STATS_RE = re.compile(
    r"<!--\s*ORG-STATS-START\s*-->.*?<!--\s*ORG-STATS-END\s*-->",
    re.DOTALL,
)
LATEST_RE = re.compile(
    r"<!--\s*LATEST-START\s*-->.*?<!--\s*LATEST-END\s*-->",
    re.DOTALL,
)


def _member_pill_re(slug: str) -> re.Pattern[str]:
    return re.compile(
        rf"<!--\s*MEMBER-STATS-{re.escape(slug)}-START\s*-->.*?<!--\s*MEMBER-STATS-{re.escape(slug)}-END\s*-->",
        re.DOTALL,
    )


def patch_index(members: list[dict[str, Any]]) -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")
    orig = html

    # 1. Org stats strip in hero
    org_block = (
        "<!-- ORG-STATS-START -->"
        + render_org_stats(members)
        + "<!-- ORG-STATS-END -->"
    )
    if ORG_STATS_RE.search(html):
        html = ORG_STATS_RE.sub(org_block, html)
    else:
        # First run — inject right before the existing meta pill so the
        # strip sits between tagline and pill.
        marker = '<span class="meta">Currently'
        html = html.replace(marker, org_block + "\n        " + marker, 1)

    # 2. Per-member pill inside every card
    for m in members:
        pill = render_member_pill(m)
        block = (
            f"<!-- MEMBER-STATS-{m['slug']}-START -->"
            + pill
            + f"<!-- MEMBER-STATS-{m['slug']}-END -->"
        )
        rx = _member_pill_re(m["slug"])
        if rx.search(html):
            html = rx.sub(block, html)
        else:
            # First run — inject just before <span class="visit"> within the
            # card pointing at this slug.
            anchor = f'href="https://scholarlybrightminds.github.io/{m["slug"]}/"'
            visit_marker = '<span class="visit">'
            # Find the card's visit span and inject pill just before it.
            idx = html.find(anchor)
            if idx == -1:
                continue
            visit_idx = html.find(visit_marker, idx)
            if visit_idx == -1:
                continue
            html = (
                html[:visit_idx]
                + block
                + "\n                "
                + html[visit_idx:]
            )

    # 3. Latest publications section (appended once, before footer)
    latest_block = (
        "<!-- LATEST-START -->"
        + render_latest_section(members)
        + "<!-- LATEST-END -->"
    )
    if LATEST_RE.search(html):
        html = LATEST_RE.sub(latest_block, html)
    else:
        html = html.replace("</main>", "    " + latest_block + "\n\n</main>", 1)

    if html != orig:
        INDEX_HTML.write_text(html, encoding="utf-8")
        print(f"  patched {INDEX_HTML.name}")
    else:
        print(f"  no change to {INDEX_HTML.name}")


# ─────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────
def main() -> int:
    print(f"aggregate_metrics: {datetime.now(timezone.utc).isoformat()}")
    enriched = [fetch_member(m) for m in MEMBERS]

    total_pubs  = sum(m["total_documents"] for m in enriched)
    total_cites = sum(m["total_citations"] for m in enriched)
    print(f"  org totals: {len(enriched)} researchers · {total_pubs} pubs · {total_cites} cites")

    patch_index(enriched)
    return 0


if __name__ == "__main__":
    sys.exit(main())
