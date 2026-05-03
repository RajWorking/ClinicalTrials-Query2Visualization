# Clinical Trials Query → Visualization Backend

A backend service that converts natural-language clinical-trial questions into
structured visualization specifications, backed by live data from the
[ClinicalTrials.gov v2 API](https://clinicaltrials.gov/data-api/api).

The output is a JSON document a frontend can render directly: chart `type`,
`title`, `encoding`, and `data` (with deep citations — every datum carries
the `nct_id`s and excerpts that produced it). A small demo UI is included
that renders bar / line / scatter / histogram via Vega-Lite and network
graphs via vis-network.

---

## Quick start

The project runs on **Python 3.13**. `run.sh` will activate the right
environment automatically; pick whichever path is convenient:

```bash
# Option A — conda (recommended)
conda create -n cheiron python=3.13 -y
conda activate cheiron
pip install -r requirements.txt

# Option B — stdlib venv
python3.13 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt

# Then in either case:
cp .env.example .env   # add OPENAI_API_KEY, or set STUB_LLM=1 to skip
./run.sh               # serves http://localhost:8000
```

`run.sh` looks for (in order) the conda env named `cheiron`, then a local
`.venv`, then falls back to system python. Override the conda env name
with `CONDA_ENV=other ./run.sh`.

Open `http://localhost:8000/` in a browser, or POST to `/analyze`:

```bash
curl -sS -X POST http://localhost:8000/analyze \
  -H 'content-type: application/json' \
  -d '{"query":"How has the number of trials for this drug changed each year?","drug_name":"Pembrolizumab"}' \
  | python3 -m json.tool
```

### Stub mode

Set `STUB_LLM=1` to bypass OpenAI entirely. The planner uses hand-crafted
plans for the five example query categories (time trends, distributions,
comparisons, geography, networks). This lets graders run the full pipeline
end-to-end without an OpenAI key.

```bash
STUB_LLM=1 ./run.sh
```

### Tests

```bash
pytest -q                       # unit + integration (mocked CT.gov + mocked OpenAI)
python -m scripts.smoke_ctgov   # live transport check against /version + /studies
python -m scripts.smoke_analyze # live end-to-end /analyze on all 5 example queries
```

77 tests cover every aggregation builder, the stub planner's classification,
schema validation (phase/status synonyms, year bounds), end-to-end
`/analyze` integration via a mocked CT.gov client, the OpenAI planner
path with a fake SDK (happy path / repair retry / fallback), and a
recorded CT.gov payload played through the real httpx client. The
`smoke_ctgov` script diagnoses transport issues (e.g. CDN-side `403`s);
the `smoke_analyze` script runs each canonical example against the
live API and prints actual vs. expected viz types.

---

## Architecture

```
NL query  ──►  planner.py  ──►  QueryPlan
                │                  │
                │                  ▼
                │             ctgov.py  ──►  ClinicalTrials.gov v2 API
                │                  │
                │                  ▼
                │            normalized studies
                │                  │
                │                  ▼
                │           aggregate.py  ──►  data/nodes/edges + citations
                │                  │
                ▼                  ▼
          query_interpretation  + VisualizationSpec  ──►  AnalyzeResponse
```

The pipeline is **LLM-as-planner, code-as-executor**. The LLM only chooses
the *shape* of the question — filters, aggregation dimension, viz type. All
data fetching, counting, binning, and citation building is deterministic
Python. Numbers are never hallucinated.

| Stage      | Module             | What it does                                                                 |
|------------|--------------------|------------------------------------------------------------------------------|
| Plan       | `app/planner.py`   | OpenAI structured outputs (or `STUB_LLM=1` heuristic) → `QueryPlan` Pydantic |
| Fetch      | `app/ctgov.py`     | Translates `Filters` → v2 API params, paginates, normalizes to flat dicts    |
| Aggregate  | `app/aggregate.py` | One pure function per visualization type (`build_bar`, `build_network`, …)   |
| Cite       | `app/citations.py` | Picks NCT ID + brief-title excerpt per bucket / edge                          |
| Respond    | `app/main.py`      | Assembles `AnalyzeResponse` and serves it                                    |

---

## Request schema

`POST /analyze`

| Field         | Type     | Required | Notes                                                  |
|---------------|----------|----------|--------------------------------------------------------|
| `query`       | string   | yes      | The natural-language question                          |
| `drug_name`   | string?  | no       | Maps to `query.intr` on ClinicalTrials.gov             |
| `condition`   | string?  | no       | Maps to `query.cond`                                   |
| `sponsor`     | string?  | no       | Maps to `query.spons`                                  |
| `country`     | string?  | no       | Maps to `query.locn`                                   |
| `phase`       | string?  | no       | One of `PHASE1`, `PHASE2`, `PHASE3`, `PHASE4`, `EARLY_PHASE1`, `NA` |
| `status`      | string?  | no       | e.g. `RECRUITING`, `COMPLETED`, `TERMINATED`           |
| `start_year`  | int?     | no       | Lower bound for trial start date                       |
| `end_year`    | int?     | no       | Upper bound for trial start date                       |
| `max_studies` | int      | no       | Default 500, max 2000                                  |

Any structured field provided overrides anything the LLM picks for that
filter.

## Response schema

```jsonc
{
  "visualization": {
    "type": "bar_chart | grouped_bar_chart | time_series | scatter_plot | histogram | network_graph",
    "title": "Human-readable title",
    "encoding": {
      "x": {"field": "phase", "type": "nominal"},
      "y": {"field": "trial_count", "type": "quantitative"}
      // for grouped_bar: + "series": {...}
      // for network_graph: "nodes" + "edges" descriptors instead of x/y
    },
    "data": [
      {
        "phase": "Phase 2",
        "trial_count": 947,
        "sampled": false,
        "citations": [
          {
            "nct_id": "NCT00016991",
            "excerpt": "PURPOSE: Phase II trial to study the effectiveness of ZD 1839 in treating patients who have glioblastoma…",
            "source_field": "protocolSection.descriptionModule.briefSummary",
            "url": "https://clinicaltrials.gov/study/NCT00016991"
          }
        ]
      }
    ]
    // network_graph replaces "data" with "nodes" + "edges"; each edge has its own "citations".
  },
  "meta": {
    "filters_applied": {"condition": "Glioblastoma"},
    "query_interpretation": "Distribute matching trials by phase.",
    "source": "clinicaltrials.gov",
    "total_studies_matched": 2204,    // distinct trials matching the filters
    "bucket_memberships": 2285,       // sum of bucket counts (≥ total when
                                      // the dim is multi-valued, e.g. phase)
    "studies_used": 2204,
    "truncated": false,
    "warnings": [],
    "per_series_totals": null,        // populated for grouped_bar
    "nodes_returned": null,           // populated for network_graph
    "nodes_total": null,
    "edges_returned": null,
    "edges_total": null,
    "min_edge_weight": null
  }
}
```

---

## Supported visualization types

| `type`              | When picked                                            | `data` shape                                                          |
|---------------------|--------------------------------------------------------|-----------------------------------------------------------------------|
| `bar_chart`         | Distribution across a categorical dimension            | `[{<dim>, trial_count, citations}]`                                   |
| `grouped_bar_chart` | Comparing two or more named items across a dimension   | `[{<dim>, <series>, trial_count, citations}]`                         |
| `time_series`       | Trend by year/quarter/month of trial start             | `[{year, trial_count, citations}]`                                    |
| `histogram`         | Distribution of a numeric field (enrollment, duration) | `[{bin, bin_start, bin_end, trial_count, citations}]`                 |
| `scatter_plot`      | Two numeric fields per trial                           | `[{<x>, <y>, nct_id, citations}]`                                     |
| `network_graph`     | Relationships (sponsor↔drug, drug↔condition, drug↔drug)| `nodes: [{id,label,type}]`, `edges: [{source,target,weight,citations}]` |

Supported dimensions for grouping: `phase`, `overall_status`, `study_type`,
`sex`, `lead_sponsor`, `sponsor_class`, `country`, `intervention_type`,
`intervention_name`, `condition`, `year`, `quarter`, `month`.

## Example queries

The five canonical queries, with captured input/output JSON pairs, live in
[`examples/`](./examples). They cover every supported visualization type:

| File prefix          | Query category    | Viz type            |
|----------------------|-------------------|---------------------|
| `01_time_trend`      | Time trends       | `time_series`       |
| `02_phases`          | Distributions     | `bar_chart`         |
| `03_compare`         | Comparisons       | `grouped_bar_chart` |
| `04_geography`       | Geographic        | `bar_chart` (country dim) |
| `05_network`         | Relationships     | `network_graph`     |
| `06_histogram`       | Numeric distribution | `histogram`     |
| `07_scatter`         | Numeric vs numeric | `scatter_plot`     |

Reproduce them with:

```bash
STUB_LLM=1 ./run.sh &
for f in examples/*.request.json; do
  curl -sS -X POST http://localhost:8000/analyze \
    -H 'content-type: application/json' --data-binary @"$f"
done
```

---

## Design decisions and tradeoffs

**LLM as a planner, not a calculator.** The model emits a `QueryPlan`
constrained by an OpenAI JSON schema — nothing more. Every count comes
from real ClinicalTrials.gov data. This makes the system debuggable,
testable, and cheap (one LLM call per request, no token-heavy
data summarization).

**One coherent contract for every viz type.** A single `VisualizationSpec`
object holds bar / time-series / scatter / histogram / grouped-bar (using
`data`) and network graphs (using `nodes`/`edges`). The encoding object is
intentionally small and Vega-Lite-compatible, so the demo UI can render
five chart types from one rendering function plus a network branch.

**Citations on every datum.** `cite()` is called per bucket (per bar, per
year, per edge), capped at 3 entries each. Excerpts come from
`briefTitle` (with `briefSummary` fallback). This keeps the response
under 100 KB even for high-cardinality queries while still being
auditable — the assignment's bonus criterion.

**Override semantics.** Any structured field the user supplies wins over
the LLM's guess. If the user says `condition=Glioblastoma`, that's the
filter — even if the model tried to set something else.

**Stub mode.** A heuristic planner ships with the code so the pipeline
can be evaluated without an OpenAI key. It also guards the test suite
against LLM nondeterminism.

**Exact counts where possible, sampled-and-labelled otherwise.** For
`bar_chart` queries grouped by `phase` or `overall_status`, for
`time_series` (per-year), and for `grouped_bar_chart` comparisons (one
fan-out cell per series-value × bucket-value), the backend fans out tiny
`countTotal=true` queries in parallel — giving exact counts with no
sampling. For high-cardinality dimensions (country, sponsor, condition)
we fall back to fetching up to `max_studies` (default 500); each datum
carries `sampled: true`, the title gets a `(sampled)` suffix, and `meta`
records `truncated: true` with a warning. We deliberately do **not**
extrapolate to an estimated total — pagination is not a random sample, so
scaling would produce biased numbers; sampled counts are lower bounds.

For grouped comparisons, `meta.per_series_totals` reports each compared
item's independent total. Trials that combine both compared items will
contribute to both totals — that's by design: it answers "how many
Pembro Phase-3 trials" and "how many Nivolumab Phase-3 trials" as
independent questions.

For network graphs, `meta.{nodes,edges}_{returned,total}` reports the
cap (200 highest-weight edges) versus the actual sizes, and `warnings`
flags truncation when it occurs.

**Deep citations.** Each citation carries:

  - `nct_id` — the trial identifier
  - `excerpt` — exact text from the study payload that supports the
    datum (preferring sentences from `briefSummary` that mention the
    bucket value verbatim; falling back to the structured field's value)
  - `source_field` — the JSON path on the v2 API record where the
    excerpt was sourced (e.g. `protocolSection.designModule.phases` or
    `protocolSection.descriptionModule.briefSummary`)
  - `url` — the canonical CT.gov study page

So a reviewer can confirm not just *which* trial supports a datum but
*which field on that trial*, and click through to the source.

**Network entity normalization.** Drug nodes are deduped via a canonical
form: lowercased, with parentheticals, dosage values (`200 mg`,
`5 mg/kg`), and dosage forms (`injection`, `tablet`, `oral`) stripped.
So `Pembrolizumab`, `pembrolizumab`, and `Pembrolizumab 200 mg
injection` all collapse to one node. When the API supplies a MeSH term
that matches the canonical form, that term wins as the display label.

---

## Error handling & resilience

- `phase` and `status` are validated against the API enum (with friendly
  synonyms — "Phase 3" / "3" / "III" all normalize to `PHASE3`).
  Invalid values return `422`.
- Empty queries, out-of-range years, and `max_studies` outside `[1, 2000]`
  return `422`.
- Upstream ClinicalTrials.gov errors are caught by a custom `CTGovError`
  and surfaced as `502 Bad Gateway` (transient / 5xx) or `400` (4xx
  upstream). The HTTP client uses curl-equivalent headers, follows
  redirects, and retries `429/502/503/504` with exponential backoff.
- **Transport fallback.** Some CDN edges have been observed returning
  `403` to httpx but not to stdlib `urllib`. On `403`, the client
  automatically retries the same request via `urllib.request` in a
  thread, so the service stays usable.
- **Planner repair.** If OpenAI fails or returns malformed output, the
  request retries once; if it still fails, the planner falls back to a
  safe default plan (year trend if a year filter is set, else phase
  distribution) and surfaces the reason in `meta.warnings`. The
  endpoint never `500`s on planning failures.

## Tuning knobs (env vars)

- `CTGOV_PAGINATE_CAP` (default `2000`) — generic-path pagination cap;
  raise for more exact counts on high-cardinality dims at the cost of
  latency.
- `CTGOV_CACHE_TTL` (default `300` seconds), `CTGOV_CACHE_MAX` (default
  `256`) — in-process TTL cache for repeat queries.
- `CTGOV_CONCURRENCY` (default `8`) — semaphore on in-flight CT.gov
  requests, prevents fan-out paths from saturating upstream.
- `OPENAI_MODEL` (default `gpt-4o-mini`), `STUB_LLM=1` to bypass OpenAI.

## Limitations and future work

- **Exact counts only for `phase` / `overall_status` / `year`.** Could
  be extended to `study_type`, `sex`, and `sponsor_class` with the same
  fan-out pattern; left as future work to keep latency predictable.
- **High-cardinality accuracy is bounded.** For country / sponsor /
  condition distributions, exact counts hold up to `CTGOV_PAGINATE_CAP`
  matched trials; above that the result is honestly labeled
  `truncated: true` with `sampled: true` per datum and no biased
  extrapolation.
- **Free-text drug/condition matching.** We pass user-provided
  drug/condition strings (after a small alias normalization step,
  `app/aliases.py`) straight through to `query.intr` / `query.cond`. A
  full MeSH lookup would tighten precision further.
- **English-only planner prompts.** The system prompt, few-shot
  examples, and stub heuristics are English.
- **No auth.** Intended for local evaluation; add an API key middleware
  before deploying. The CT.gov client *does* enforce a per-process
  concurrency limit and an in-process TTL cache.
- **Single-call OpenAI integration.** One repair retry on validation
  failure, then a deterministic safe-default plan. No streaming.

---

## Repo layout

```
app/
  __init__.py
  main.py             FastAPI app + routes
  schemas.py          Pydantic request/response/plan models
  planner.py          OpenAI structured-output planner + stub mode
  ctgov.py            ClinicalTrials.gov v2 client + study normalizer
  aggregate.py        build_bar / build_grouped_bar / build_time_series / build_histogram / build_scatter / build_network
  citations.py        excerpt selection + cite() helper
  static/
    index.html        single-page demo UI
    app.js            Vega-Lite + vis-network rendering
    style.css
examples/             5 captured request/response JSON pairs
tests/
  test_aggregate.py   unit tests for every builder
  test_planner.py     stub-mode classification tests
requirements.txt
run.sh                convenience launcher (loads .env, starts uvicorn)
.env.example
```
