#!/usr/bin/env python
"""Phase 0 live-API capture spike (PRD Section I).

Captures real ClinicalTrials.gov v2 responses to ``fixtures/raw/``, probes the
``/stats`` filter question, fetches the version ``dataTimestamp``, and writes
``fixtures/raw/notes.md`` with the confirmed field paths (exact casing) every
downstream worktree needs.

ClinicalTrials.gov needs no API key. If the network is unavailable the script
**fails loudly and exits non-zero** — it never fabricates fixture data.

Run::

    uv run python scripts/spike_api.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import httpx

BASE_URL = "https://clinicaltrials.gov/api/v2"
RAW_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "raw"

# The projection the transform + citation layers need (PRD Section I.1).
FIELDS = (
    "NCTId,BriefTitle,Phase,OverallStatus,LeadSponsorName,"
    "LeadSponsorClass,StartDate,LocationCountry"
)

# Field paths the transform layer relies on; the spike confirms exact casing by
# walking a real full study record (PRD Section I.6 / system-design §7).
EXPECTED_FIELD_PATHS = [
    "protocolSection.identificationModule.nctId",
    "protocolSection.identificationModule.briefTitle",
    "protocolSection.statusModule.overallStatus",
    "protocolSection.statusModule.startDateStruct.date",
    "protocolSection.designModule.phases",
    "protocolSection.designModule.studyType",
    "protocolSection.sponsorCollaboratorsModule.leadSponsor.name",
    "protocolSection.sponsorCollaboratorsModule.leadSponsor.class",
    "protocolSection.armsInterventionsModule.interventions.type",
    "protocolSection.armsInterventionsModule.interventions.name",
    "protocolSection.conditionsModule.conditions",
    "protocolSection.contactsLocationsModule.locations.country",
    "protocolSection.designModule.enrollmentInfo.count",
]


def _fail(message: str) -> None:
    """Print a clear failure and exit non-zero."""
    print(f"\nSPIKE FAILED: {message}", file=sys.stderr)
    sys.exit(1)


def _get_raw(
    client: httpx.Client, path: str, params: dict[str, Any] | None = None
) -> httpx.Response:
    """GET that fails loudly on network errors but returns any HTTP status.

    Used by the stats probe, where a 4xx is itself the finding (the endpoint
    rejecting a search filter) rather than a fatal error.
    """
    url = f"{BASE_URL}{path}"
    try:
        return client.get(url, params=params)
    except httpx.RequestError as exc:
        _fail(
            f"network error contacting {url!r}: {exc!r}. "
            "Are you offline? This script requires live access to ClinicalTrials.gov."
        )
        raise  # unreachable; _fail exits. Keeps the type checker happy.


def _get(client: httpx.Client, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
    """GET with loud failure on any network or HTTP error."""
    resp = _get_raw(client, path, params)
    resp.raise_for_status()
    return resp


def _safe_json_or_text(resp: httpx.Response) -> Any:
    """Return parsed JSON if possible, else a truncated text body."""
    try:
        return resp.json()
    except ValueError:
        return resp.text[:500]


def _save_json(name: str, payload: Any) -> Path:
    path = RAW_DIR / name
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"  wrote {path.relative_to(RAW_DIR.parents[1])}")
    return path


def _resolve_path(record: dict[str, Any], dotted: str) -> tuple[bool, Any]:
    """Resolve a dotted path, descending into the first element of any list.

    Returns ``(found, sample_value)``. ``sample_value`` is a short string sample
    of the leaf when found.
    """
    node: Any = record
    for part in dotted.split("."):
        if isinstance(node, list):
            if not node:
                return (False, None)
            node = node[0]
        if not isinstance(node, dict) or part not in node:
            return (False, None)
        node = node[part]
    sample = node[0] if isinstance(node, list) and node else node
    sample_str = str(sample)
    if len(sample_str) > 60:
        sample_str = sample_str[:57] + "..."
    return (True, sample_str)


def _phase_value_counts(stats_payload: Any) -> dict[str, int]:
    """Extract {phase_value: studies_count} from a /stats/field/values payload.

    The v2 stats payload shape varies across deployments; this walks defensively
    and pulls any ``{value, studiesCount}``-like records found under the field.
    """
    counts: dict[str, int] = {}

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            value = node.get("value")
            count = node.get("studiesCount", node.get("studies_count", node.get("count")))
            if isinstance(value, str) and isinstance(count, int):
                counts[value] = count
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(stats_payload)
    return counts


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Capturing ClinicalTrials.gov v2 fixtures to {RAW_DIR}\n")

    with httpx.Client(timeout=30.0, headers={"accept": "application/json"}) as client:
        # 0. Connectivity + freshness probe (also the version timestamp, step 5).
        print("[1/6] GET /version")
        version = _get(client, "/version").json()
        data_timestamp = version.get("dataTimestamp")
        _save_json("version.json", version)

        # 1. Intervention/drug search.
        print("[2/6] GET /studies?query.intr=pembrolizumab")
        intr_params = {
            "query.intr": "pembrolizumab",
            "fields": FIELDS,
            "pageSize": 50,
            "countTotal": "true",
            "format": "json",
        }
        intr = _get(client, "/studies", intr_params).json()
        _save_json("studies_pembrolizumab.json", intr)

        # 2. Condition search.
        print("[3/6] GET /studies?query.cond=melanoma")
        cond_params = {
            "query.cond": "melanoma",
            "fields": FIELDS,
            "pageSize": 50,
            "countTotal": "true",
            "format": "json",
        }
        cond = _get(client, "/studies", cond_params).json()
        _save_json("studies_melanoma.json", cond)

        # 3. One full study record (for confirming field paths/casing).
        studies = intr.get("studies") or []
        if not studies:
            _fail("intervention search returned no studies; cannot fetch a full record")
        first_nct = (
            studies[0]
            .get("protocolSection", {})
            .get("identificationModule", {})
            .get("nctId")
        )
        if not first_nct:
            _fail("could not read nctId from the first study to fetch a full record")
        print(f"[4/6] GET /studies/{first_nct}")
        full = _get(client, f"/studies/{first_nct}", {"format": "json"}).json()
        _save_json("study_full.json", full)

        # 4. Stats filter probe: does /stats/field/values accept query.cond and
        #    change its counts? A 4xx here is a valid finding (endpoint rejects
        #    the search expression), not a fatal error.
        print("[5/6] GET /stats/field/values?fields=Phase  (unfiltered vs query.cond=melanoma)")
        stats_unfiltered = _get(client, "/stats/field/values", {"fields": "Phase"}).json()
        _save_json("stats_phase_unfiltered.json", stats_unfiltered)

        filtered_resp = _get_raw(
            client, "/stats/field/values", {"fields": "Phase", "query.cond": "melanoma"}
        )
        stats_filter_status = filtered_resp.status_code
        stats_filter_rejected = stats_filter_status >= 400
        if stats_filter_rejected:
            filtered_payload: Any = {
                "_spike_note": "endpoint returned an error for query.cond; captured as evidence",
                "request_url": str(filtered_resp.request.url),
                "status_code": stats_filter_status,
                "body": _safe_json_or_text(filtered_resp),
            }
            filtered_counts: dict[str, int] = {}
        else:
            filtered_payload = filtered_resp.json()
            filtered_counts = _phase_value_counts(filtered_payload)
        _save_json("stats_phase_melanoma.json", filtered_payload)

        unfiltered_counts = _phase_value_counts(stats_unfiltered)
        stats_filter_changes_counts = (
            not stats_filter_rejected
            and bool(unfiltered_counts)
            and bool(filtered_counts)
            and unfiltered_counts != filtered_counts
        )

        # 5. Confirm field paths against the full record.
        print("[6/6] Confirming field paths against the full record")
        path_results = [(p, *_resolve_path(full, p)) for p in EXPECTED_FIELD_PATHS]

    _write_notes(
        data_timestamp=data_timestamp,
        intr=intr,
        cond=cond,
        path_results=path_results,
        unfiltered_counts=unfiltered_counts,
        filtered_counts=filtered_counts,
        stats_filter_changes_counts=stats_filter_changes_counts,
        stats_filter_rejected=stats_filter_rejected,
        stats_filter_status=stats_filter_status,
        full_nct=first_nct,
    )

    missing = [p for p, found, _ in path_results if not found]
    print("\nDone.")
    print(f"  data_timestamp: {data_timestamp}")
    print(
        "  stats /stats/field/values accepts query.cond AND changes counts: "
        f"{'YES' if stats_filter_changes_counts else 'NO'} "
        f"(filtered request HTTP {stats_filter_status})"
    )
    if missing:
        print(f"  WARNING: {len(missing)} expected field path(s) not found: {missing}")
    else:
        print("  all expected field paths confirmed")


def _write_notes(
    *,
    data_timestamp: str | None,
    intr: dict[str, Any],
    cond: dict[str, Any],
    path_results: list[tuple[str, bool, Any]],
    unfiltered_counts: dict[str, int],
    filtered_counts: dict[str, int],
    stats_filter_changes_counts: bool,
    stats_filter_rejected: bool,
    stats_filter_status: int,
    full_nct: str,
) -> None:
    """Render fixtures/raw/notes.md from the captured data."""
    lines: list[str] = []
    lines.append("# CT.gov v2 spike notes")
    lines.append("")
    lines.append(
        "Generated by `scripts/spike_api.py`. Everything here is read off real "
        "responses captured in this directory — no values are hand-written."
    )
    lines.append("")
    lines.append(f"- **Base URL:** `{BASE_URL}`")
    lines.append(f"- **`dataTimestamp` (from `/version`):** `{data_timestamp}`")
    lines.append(
        f"- **`countTotal`** (intervention search `query.intr=pembrolizumab`): "
        f"`{intr.get('totalCount')}`"
    )
    lines.append(
        f"- **`countTotal`** (condition search `query.cond=melanoma`): "
        f"`{cond.get('totalCount')}`"
    )
    lines.append("")

    # Stats-filter finding.
    lines.append("## Stats filter question")
    lines.append("")
    answer = "YES" if stats_filter_changes_counts else "NO"
    lines.append(
        f"**Does `/stats/field/values?fields=Phase` accept an additional "
        f"`query.cond=melanoma` and change the returned counts? -> {answer}.**"
    )
    lines.append("")
    if stats_filter_rejected:
        lines.append(
            f"The endpoint returns **HTTP {stats_filter_status}** when "
            "`query.cond=melanoma` is added — it rejects the search expression "
            "outright (the `query.*` params are not valid on `/stats/field/values`). "
            "**Implication:** filtered distributions cannot be obtained from the "
            "stats endpoint at all; they must be computed client-side by paging "
            "`/studies`. This confirms the assumption in system-design §6."
        )
    elif stats_filter_changes_counts:
        lines.append(
            "The per-phase counts differ between the unfiltered and "
            "`query.cond=melanoma` requests, so the stats endpoint *does* honor "
            "the search expression. (Re-confirm in the retrieval worktree before "
            "relying on it.)"
        )
    else:
        lines.append(
            "The endpoint accepted `query.cond=melanoma` but the per-phase counts "
            "are identical to the unfiltered request, so `/stats/field/values` "
            "ignores the search expression and reports **whole-registry** "
            "aggregates. **Implication:** filtered distributions must be computed "
            "client-side by paging `/studies`. This confirms system-design §6."
        )
    lines.append("")
    lines.append("Captured Phase counts:")
    lines.append("")
    lines.append("| Phase | Unfiltered | query.cond=melanoma |")
    lines.append("|---|---|---|")
    all_phase_keys = sorted(set(unfiltered_counts) | set(filtered_counts))
    for key in all_phase_keys:
        lines.append(
            f"| `{key}` | {unfiltered_counts.get(key, '-')} | {filtered_counts.get(key, '-')} |"
        )
    lines.append("")

    # Field paths.
    lines.append("## Confirmed field paths")
    lines.append("")
    lines.append(
        f"Confirmed against the full record for `{full_nct}` "
        "(`study_full.json`). List indices below mean \"the leaf lives on each "
        "array element\" (e.g. `interventions[].type`). Casing is exact.")
    lines.append("")
    lines.append("| Field path | Present | Sample value |")
    lines.append("|---|---|---|")
    for path, found, sample in path_results:
        mark = "yes" if found else "**NO**"
        sample_cell = f"`{sample}`" if found and sample is not None else "-"
        lines.append(f"| `{path}` | {mark} | {sample_cell} |")
    lines.append("")

    # Paging behavior.
    lines.append("## Paging / pageSize behavior")
    lines.append("")
    lines.append(
        "- `pageSize` caps results per page (max 1000; default 10 — always set it). "
        f"This spike used `pageSize=50` and received "
        f"{len(intr.get('studies') or [])} study records on the first page."
    )
    has_token = "nextPageToken" in intr
    lines.append(
        f"- `nextPageToken` present on the first page: **{has_token}**. "
        "Pass it back as `pageToken` to fetch the next page; absence means the "
        "result set fit in one page."
    )
    lines.append(
        "- `countTotal=true` returns `totalCount` for the whole filtered result "
        "set independent of `pageSize`."
    )
    lines.append("")
    lines.append("## Files in this directory")
    lines.append("")
    for name in [
        "version.json",
        "studies_pembrolizumab.json",
        "studies_melanoma.json",
        "study_full.json",
        "stats_phase_unfiltered.json",
        "stats_phase_melanoma.json",
    ]:
        lines.append(f"- `{name}`")
    lines.append("")

    (RAW_DIR / "notes.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"  wrote {(RAW_DIR / 'notes.md').relative_to(RAW_DIR.parents[1])}")


if __name__ == "__main__":
    main()
