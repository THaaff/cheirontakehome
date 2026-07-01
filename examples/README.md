# Example runs

Six real `POST /visualize` runs spanning six of the seven operations. Each folder holds:

- **`request.json`** — the request (pinned to `mode:"replay"`, the reproducible path).
- **`response.json`** — the actual response, `request_id` normalized to `"<request-id>"`.
- **`plan.json`** — the recorded `AnalysisPlan` (what the planner produced live; injected in replay).
- **`note.md`** — one line: the operation and what the visualization answers.

`replay_cache/` holds the raw CT.gov pages these runs aggregate, so replay needs **no key and
no network**.

| Example | Operation → viz | What it answers |
|---|---|---|
| [`time_trend_pembrolizumab`](time_trend_pembrolizumab/) | `time_trend` → `time_series` | Annual count of pembrolizumab trials since 2018. |
| [`phase_distribution_melanoma`](phase_distribution_melanoma/) | `categorical_distribution` → `bar_chart` | How melanoma trials split across Phase 1–4. |
| [`sponsor_comparison_conditions`](sponsor_comparison_conditions/) | `comparison` → `grouped_bar_chart` | Sponsor-class mix for melanoma vs. lung cancer. |
| [`sponsor_drug_network_melanoma`](sponsor_drug_network_melanoma/) | `cooccurrence_network` → `network_graph` | Sponsors ↔ drugs that co-occur in melanoma trials, with per-node/edge citations. |
| [`geo_recruiting_melanoma`](geo_recruiting_melanoma/) | `geographic_distribution` → `choropleth_map` | Recruiting-melanoma-trial counts by country. |
| [`enrollment_distribution_melanoma`](enrollment_distribution_melanoma/) | `numeric_distribution` → `histogram` | How melanoma trials distribute across enrollment-size bins. |

## Reproduce (offline, no key, no network)

```bash
uv run python scripts/capture_examples.py --mode replay
```

Regenerates every `response.json` from the recorded plan + cached pages and asserts each is
**byte-for-byte** identical to what's committed (exits non-zero on any drift). `git diff`
after a run should show nothing.

## Re-capture (author only — needs a key + network)

```bash
uv run python scripts/capture_examples.py --mode live
```

Plans each query with one LLM call, records the plan, and repopulates `replay_cache/` from the
live CT.gov API. The script pins `PYTHONHASHSEED=0` so the network layout is deterministic.
