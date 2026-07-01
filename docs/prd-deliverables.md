# PRD: Deliverables (Phase 4)

**Worktree:** `deliverables` · **Status:** ready after `integration` merges · **Depends on:** the full working system · **Blocks:** nothing (final)
**Runs:** solo · **Read first:** `docs/system-design.md`, the assignment brief (submission requirements, evaluation criteria, integrity note)

---

## Problem statement

A working backend is not a submission. The assignment is graded on a README (run instructions, schemas, design decisions, tradeoffs, limitations, AI-tools writeup), 3 to 5 example runs with actual JSON outputs, and an optional demo. This worktree produces those artifacts against the finished system. It consumes the system; it does not modify application code.

## Goals
1. A README that satisfies every required submission section and reads as evidence of deliberate engineering, not a feature list.
2. 3 to 5 example runs captured as real JSON, spanning the operation taxonomy, reproducible offline in replay.
3. An optional single-file demo that renders both a chart spec and the network spec, with zero build chain.
4. A clean final repo whose structure maps obviously onto the evaluation criteria.

## Non-goals
1. **No application code changes.** If something is broken, flag it for the relevant worktree; do not patch it here.
2. **No new features.** Documentation and capture only.
3. **No deployment requirement.** A deployed endpoint is an optional bonus, not in scope unless time allows.

## User stories
- As a **grader**, I can clone the repo, follow the README, and run the examples in replay without obtaining a key.
- As a **grader scoring system design**, I can read the design-decisions section and see the rationale and tradeoffs behind the pipeline, the IR, and the spec format.
- As a **frontend engineer**, I can read the schema section plus `docs/schemas/` and render the output without guessing.

---

## Scope and specification

### Module layout (owns `README.md`, `examples/**`, `demo/**`, `scripts/capture_examples.py`)
Does not own anything under `app/`.

### README structure (map directly to the assignment's required sections)
1. **Overview:** one paragraph on what the service does and the two-problem framing (NL-to-query, NL-to-viz).
2. **How to run:** prerequisites (Python 3.12, uv); install (`uv sync`); configure (`.env` from `.env.example`, `OPENAI_API_KEY` for live, replay needs neither key nor network); start (`uv run uvicorn app.api.main:app`); the live-vs-replay distinction stated plainly. Include the example `curl`.
3. **Request and response schema:** describe the request fields, the response envelope, the `VizSpec` discriminated union (chart vs graph), the semantic-encoding-plus-embedded-spec design, and the per-datum citations. Point to the generated `docs/schemas/*.json` as the authoritative contract.
4. **Key design decisions and tradeoffs:** pull from `system-design.md` section 6, in the author's words. Lead with the model-plans-code-executes wall (and why: hallucination prevention in a clinical domain, testability, the reliability-over-autonomy tradeoff). Then: Vega-Lite subset plus semantic layer; the closed-world `AnalysisPlan` IR and how it yields breadth without one-off hacks; client-side aggregation forced by the stats-endpoint limitation, with projection pushdown and caching; provenance threaded from the transform layer; planner-executor over a ReAct loop.
5. **Query and visualization coverage:** the operation-to-viz matrix, with one example query per row.
6. **Limitations and what I would improve with more time:** geo country-name to ISO mapping edge cases and the ranked-bar fallback; pushing date and country filters server-side; the `/stats` fast path for unfiltered distributions; results-section analytics (adverse events, outcomes); per-datum citation caps for large payloads; multi-turn and follow-up refinement; more viz types; a fuller planner eval.
7. **AI tools used (the integrity note):** which tools were used, how correctness was validated (the planner eval, the test suite, the live API spike, replay determinism), and which parts were designed deliberately versus generated and adapted. Be specific and honest.
8. **Testing and eval:** how to run the suite and the planner eval, and what replay vs live covers.

Keep it scannable: a busy grader should get the gist from headers and bold.

### Example runs (`examples/**`, `scripts/capture_examples.py`)
- Pick 3 to 5 queries spanning operations: at minimum a time trend, a categorical distribution, a comparison, and a co-occurrence network (a geographic example if geo landed).
- `scripts/capture_examples.py` runs each request through the running service (or `run_pipeline` directly) and writes `examples/<name>/request.json` and `examples/<name>/response.json`.
- **Reproducibility workflow:** the author runs capture once live (with the key and network), which populates the retrieval cache and the planner's recorded outputs; commit those alongside the examples. Graders then re-run in replay and get byte-identical outputs with no key. Document this in the README.
- Each example folder gets a one-line note stating the operation and what the visualization answers.

### Optional demo (`demo/index.html`)
- A single static HTML file using `vega-embed` from a CDN. A text input posts the query to `POST /visualize`; on a chart response it embeds `visualization.vega_spec`; on a graph response it reads `visualization.data` (nodes/edges) and renders with a small d3-force or cytoscape block (also CDN). No bundler, no build step.
- Show citations on hover/click for at least one viz type to demonstrate the deep-citation payload.
- Document how to use it: start the API, open `demo/index.html` (or serve it statically), with permissive CORS already set by integration.
- Clearly mark the demo as an optional bonus.

### Final packaging
The repo is the submission. Note in the README that producing the zip is a final manual step (or provide a small `scripts/package.sh` that zips the repo excluding `.venv`, `.cache`, and `.git`). Confirm `.env` is gitignored and only `.env.example` is committed.

---

## Requirements

### Must-have (P0)
- [ ] README covers all eight sections above, including the AI-tools integrity writeup.
- [ ] 3 to 5 example runs committed with real `request.json` / `response.json`, reproducible in replay.
- [ ] `scripts/capture_examples.py` regenerates the example outputs.
- [ ] README documents the live-vs-replay workflow and confirms replay needs no key or network.

### Nice-to-have (P1)
- [ ] The optional `demo/index.html` rendering at least one chart and the network spec, with citations surfaced.
- [ ] A geographic example among the captured runs.
- [ ] `scripts/package.sh` producing a clean submission zip.

### Future considerations (P2)
- [ ] A deployed endpoint and a short demo video.

### Acceptance criteria
- Given a fresh clone with no `OPENAI_API_KEY` and no network, When a grader follows the README replay instructions and runs `scripts/capture_examples.py` (or inspects `examples/`), Then they see real outputs for every committed example.
- Given the README design-decisions section, When read alongside `system-design.md`, Then every major architectural choice has a stated rationale and tradeoff.
- Given the demo is built, When the API is running and a grader submits a bar-chart query and a network query, Then both render and citations are visible for at least one.
- Given the repo, When inspected, Then `.env` is absent and gitignored and `.env.example` is present.

---

## Verification commands
```
# replay reproduction (no key, no network):
uv run python scripts/capture_examples.py --mode replay
ls examples/*/response.json
# demo (optional): start API, then open demo/index.html
uv run uvicorn app.api.main:app --port 8000 &
python -m http.server -d demo 8080   # then visit localhost:8080
```

## File ownership and boundaries
Owns `README.md`, `examples/**`, `demo/**`, and `scripts/capture_examples.py` (plus optional `scripts/package.sh`). Does not modify anything under `app/`, `docs/schemas/` (generated by contracts), or other worktrees. If the system misbehaves during capture, file it against the responsible worktree rather than patching here.

## Dependencies and chaining
Upstream: merged `integration` (a working end-to-end `POST /visualize`), the planner's recorded outputs, and a populated retrieval cache. Final worktree; blocks nothing.

## Open questions
| Question | Owner | Blocking? |
|---|---|---|
| Which 3 to 5 queries best showcase coverage | Taylor | non-blocking (recommend time trend, distribution, comparison, network, +geo) |
| Build the optional demo, or stay backend-only | Taylor | non-blocking (recommend the demo; it is cheap and shows citations) |
| Deploy an endpoint | Taylor | non-blocking (P2) |

## Conductor handoff prompt
```
You are building the "deliverables" worktree for a ClinicalTrials.gov query-to-visualization backend. You
produce the submission artifacts against the finished system; do not modify any application code. Read
docs/system-design.md and the assignment brief (submission requirements, evaluation criteria, integrity
note), then build exactly what docs/prd-deliverables.md specifies.

You own README.md, examples/**, demo/**, and scripts/capture_examples.py only.

Write a README covering: overview; how to run (uv, .env, uvicorn, live-vs-replay); request/response schema
(the VizSpec chart-vs-graph union, semantic-encoding-plus-embedded-spec, citations, pointing to
docs/schemas/); key design decisions and tradeoffs (in the author's words, drawn from system-design.md
section 6, leading with model-plans-code-executes); the operation-to-viz coverage matrix; limitations and
future work; the AI-tools-used integrity writeup (tools used, how validated, deliberate vs generated); and
how to run the tests and planner eval. Keep it scannable.

Write scripts/capture_examples.py to run 3 to 5 queries (time trend, distribution, comparison, network,
optionally geo) through the service and write examples/<name>/request.json and response.json. Capture once
live to populate the cache and recorded planner outputs, commit them, and document that graders reproduce
in replay with no key or network. Optionally build demo/index.html: a single static file using vega-embed
(CDN) for chart specs and a small d3-force/cytoscape block for the network spec, surfacing citations on
hover for at least one viz; mark it as a bonus. Ensure .env is gitignored and only .env.example is
committed.

Acceptance: every command in the PRD "Verification commands" block works; examples reproduce in replay
without a key; the README satisfies all eight sections; .env is absent from the repo.
```
