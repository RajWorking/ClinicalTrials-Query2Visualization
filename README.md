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
cp .env.example .env   # add your OPENROUTER_API_KEY
./run.sh               # serves http://localhost:8000
```

`run.sh` looks for (in order) the conda env named `cheiron`, then a local
`.venv`, then falls back to system python. Override the conda env name
with `CONDA_ENV=other ./run.sh`.

The planner routes through **OpenRouter** using the OpenAI-compatible SDK.
Set `OPENROUTER_API_KEY` in `.env`. The default model is
`openai/gpt-4o-mini`; override with `OPENROUTER_MODEL`. Any model that
supports OpenAI structured outputs (`response_format={"type":"json_schema",...}`)
will work.

Open `http://localhost:8000/` in a browser, or POST to `/analyze`:

```bash
curl -sS -X POST http://localhost:8000/analyze \
  -H 'content-type: application/json' \
  -d '{"query":"How has the number of trials for this drug changed each year?","drug_name":"Pembrolizumab"}' \
  | python3 -m json.tool
```

### Tests

```bash
pytest -q                       # unit + integration (mocked CT.gov + mocked OpenAI)
python -m scripts.smoke_ctgov   # live transport check against /version + /studies
python -m scripts.smoke_analyze # live end-to-end /analyze on all 7 example queries
python -m scripts.smoke_analyze --write # refresh examples/*.response.json
```

The test suite covers every aggregation builder, deterministic planner
validation helpers, schema validation
(phase/status/sponsor-class/study-type/sex/intervention-type synonyms,
year bounds, discriminated visualization spec, typed per-viz datum rows),
end-to-end `/analyze` integration via a mocked CT.gov client, the OpenAI
planner path with a fake SDK (happy path / malformed-output repair retry /
provider-error propagation), small-enum exact fan-out across
`sponsor_class` / `study_type` / `sex` / `intervention_type`
(parametrized), candidate-discovery exact fan-out for sponsor / condition /
intervention top-N, salt-form canonicalization and MeSH artifact filtering
for the network builder, top-N clipping (bar and network),
default-time-range surfacing, network-truncation warnings, and a recorded
CT.gov payload played through the real httpx client. The
`smoke_ctgov` script diagnoses transport issues (e.g. CDN-side `403`s);
the `smoke_analyze` script runs each canonical example against the
live API and prints actual vs. expected viz types. Pass `--write` to
recapture the checked responses in `examples/*.response.json`.

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

| Stage      | Module                  | What it does                                                                 |
|------------|-------------------------|------------------------------------------------------------------------------|
| Route      | `app/main.py`           | FastAPI setup, error mapping, `/analyze` orchestration                        |
| Plan       | `app/planner.py`        | OpenRouter planner call, malformed-output repair, provider-error propagation |
| Validate   | `app/plan_verifier.py`  | Hook for deterministic post-plan checks (pass-through until logic is added)  |
| Schema     | `app/planner_schema.py` | OpenAI structured-output prompt + strict JSON schema                         |
| Fetch      | `app/ctgov.py`          | Translates `Filters` → v2 API params, paginates, normalizes to flat dicts    |
| Execute    | `app/paths.py`          | Selects exact/sampled execution path and returns `PathOutcome`                |
| Exact      | `app/exact_counts.py`   | Shared countTotal fan-out helpers for small enums, countries, years, cells   |
| Aggregate  | `app/aggregate.py`      | Pure builders for sampled bar/time/histogram/scatter/network outputs         |
| Cite       | `app/citations.py`      | Picks NCT ID + brief-title excerpt per bucket / edge                         |
| Respond    | `app/responses.py`      | Top-N clipping, warnings, and `AnalyzeResponse` assembly                     |

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
| `sponsor_class` | string? | no      | One of `INDUSTRY`, `NIH`, `FED`, `OTHER_GOV`, `INDIV`, `NETWORK`, `AMBIG`, `OTHER`, `UNKNOWN`; common phrases like `industry-sponsored` normalize to enum values |
| `study_type`  | string?  | no       | One of `INTERVENTIONAL`, `OBSERVATIONAL`, `EXPANDED_ACCESS`; synonyms like `observational` are accepted |
| `sex`         | string?  | no       | One of `ALL`, `FEMALE`, `MALE`; synonyms like `women` / `men` are accepted |
| `intervention_type` | string? | no  | One of CT.gov's intervention-type enums such as `DRUG`, `BIOLOGICAL`, `DEVICE`, `PROCEDURE`, `DIAGNOSTIC_TEST` |
| `start_year`  | int?     | no       | Lower bound for trial start date                       |
| `end_year`    | int?     | no       | Upper bound for trial start date                       |
| `max_studies` | int      | no       | Default 500, max 2000                                  |
| `top_n`       | int?     | no       | If set (1–200), bar / grouped_bar / histogram / network output is clipped to the top-N highest-weight buckets / edges. Time series is unaffected. |

Any structured field provided overrides anything the LLM picks for that
filter.

## Response schema

`visualization` is a Pydantic [discriminated union](https://docs.pydantic.dev/latest/concepts/unions/#discriminated-unions)
keyed on `type` — the generated OpenAPI schema lists one variant per
visualization type, so consumers can dispatch on `type` without
defending against absent fields. Chart types (`bar_chart`,
`grouped_bar_chart`, `time_series`, `histogram`, `scatter_plot`) carry a
`data: list[…]` and never `nodes`/`edges`. `network_graph` carries
`nodes` and `edges` and never `data`.

Frontend consumers can inspect the live OpenAPI document at
`GET /openapi.json`. The `encoding` channels are typed in that schema
while preserving the compact Vega-Lite-style JSON shape, e.g.
`{"field":"phase","type":"nominal"}`.

Each datum row is also a typed model — `BarDatum`, `GroupedBarDatum`,
`TimeSeriesDatum`, `HistogramDatum`, `ScatterDatum`, `NetworkNode`,
`NetworkEdge`. They share a uniform "support envelope" (`trial_count`,
`sampled`, `supporting_nct_ids`, `supporting_nct_ids_complete`,
`citation_count`, `citations`) and add what's specific to that chart
shape (`bin_start`/`bin_end` for histograms, `nct_id` for scatter,
`source`/`target`/`weight` for network edges, …). The dynamic dim-key
field — `phase`, `country`, `sponsor`, `year`, … — is named after
`aggregation.group_by` and flows through `model_extra`, so it can vary
per request without weakening row-level validation.

Spec models reject unexpected top-level fields and validate required
rendering channels: chart specs require `encoding.x` + `encoding.y`,
grouped bars also require `encoding.series`, and network graphs require
`encoding.nodes` + `encoding.edges`.

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
| `network_graph`     | Relationships (sponsor↔drug, drug↔condition, drug↔drug, site↔drug)| `nodes: [{id,label,type}]`, `edges: [{source,target,weight,citations}]` |

Supported dimensions for grouping: `phase`, `overall_status`, `study_type`,
`sex`, `lead_sponsor`, `sponsor_class`, `country`, `intervention_type`,
`intervention_name`, `condition`, `year`, `quarter`, `month`.

## Example queries

Seven canonical queries, with captured input/output JSON pairs, live in
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
./run.sh &
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
year, per edge), capped at **3 entries each** for payload-size reasons —
the response stays under 100 KB even on high-cardinality queries while
remaining auditable (the assignment's bonus criterion). Excerpts come
from `briefTitle` with `briefSummary` fallback. The cited NCT IDs are a
**stable representative sample** of the trials supporting that datum,
not the full list. Two adjacent fields disambiguate that:

  - `supporting_nct_ids` — the IDs the response carries for this datum.
  - `supporting_nct_ids_complete` — `true` when the list is exhaustive
    for the studies actually scanned (aggregator paths: bar-from-sample,
    time series from per-year fan-out, scatter), `false` when the list
    is only a small citation sample (exact-count fan-out paths return
    the API's `totalCount` but only fetch a few studies for citations).
  - `citation_count` — the count the trial_count reflects (always exact
    on fan-out paths; equals `len(supporting_nct_ids)` on aggregator
    paths).

So a reviewer can tell whether "more IDs exist beyond what's shown".

**Override semantics.** Any structured field the user supplies wins over
the LLM's guess. If the user says `condition=Glioblastoma`, that's the
filter — even if the model tried to set something else. The same applies
to CT.gov enum filters (`phase`, `status`, `sponsor_class`, `study_type`,
`sex`, `intervention_type`), which are also inferred from clear phrases
such as "Phase 3", "industry-sponsored", "observational", "female-only",
and "biologic trials".

**Exact counts where possible, sampled-and-labelled otherwise.** Each
visualization request is dispatched to one of eight *path strategies*
(`_path_year_fanout`, `_path_exact_bar`, `_path_high_card_bar`,
`_path_grouped_bar_cross`, `_path_grouped_compare_exact`,
`_path_grouped_compare_sampled`, `_path_generic`) — each returns a
`PathOutcome`, then `responses.py` runs
the same post-processing on whatever the chosen path produced.

- `phase`, `overall_status`, `sponsor_class`, `study_type`, `sex`, and
  `intervention_type` bar_charts, `year` time_series, and X-vs-Y
  comparisons over `phase` / `overall_status` / `sponsor_class` /
  `study_type` / `sex` / `intervention_type` fan out **one tiny
  `countTotal=true` query per bucket** in parallel — exact counts with
  no sampling. The dims share a small enum, which is why we can
  enumerate buckets up-front. Exact year time-series responses include
  explicit zero-count rows for empty years, and exact grouped comparisons
  include zero-count cells for every compared series × enum bucket.
- For **country / sponsor / condition / intervention name** group_by we
  candidate-discover from a broader high-cardinality scan window, then fan out one
  `countTotal=true` per discovered candidate — so the trial counts on
  shown buckets are *exact* (no sampling), but a candidate that appears
  *only* in the unsampled portion of the result set is missing from the
  ranking. The response surfaces this in `warnings` whenever it applies.
- The remaining viz types (histogram, scatter, network, plus
  quarter/month time-series) use the generic sample-then-aggregate path.
  We bump the cap per viz type because each has different
  representativeness needs: `CTGOV_NUMERIC_SCAN_CAP` (default 10000) for
  histogram/scatter so the numeric distribution isn't skewed by
  pagination order, `CTGOV_NETWORK_SCAN_CAP` (default 5000) for network
  graphs so edge weights reflect more relationships. When the matched
  total still exceeds these caps, each datum carries `sampled: true`,
  the title gets a `(sampled)` suffix, and `meta` records `truncated:
  true` with a warning. We deliberately do **not** extrapolate to an
  estimated total — pagination is not a random sample, so scaling would
  produce biased numbers; sampled counts are lower bounds. Scatter plots
  also apply a display payload cap (`CTGOV_SCATTER_POINT_CAP`, default
  1000) after scanning; when it clips points, `warnings` says the display
  was capped while source scan metadata remains unchanged.

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
*which field on that trial*, and click through to the source. Network
edge citations combine the structured fields that form the relationship
(for example sponsor + intervention, site + intervention, or drug +
condition) instead of falling back to only a trial title.

**Network entity normalization.** Drug nodes are deduped via a canonical
form: lowercased, with parentheticals, dosage values (`200 mg`,
`5 mg/kg`), dosage forms (`injection`, `tablet`, `oral`), and salt /
ester / hydrate suffixes (`mesylate`, `phosphate`, `s-malate`,
`hydrochloride`, `monohydrate`, …) stripped. So `Pembrolizumab`,
`pembrolizumab`, and `Pembrolizumab 200 mg injection` all collapse to
one node, and `Dabrafenib` / `Dabrafenib Mesylate` /
`Cabozantinib S-malate` / `Fludarabine phosphate monohydrate` resolve to
their parent INNs. A blocklist also drops MeSH umbrella terms (e.g.
*Antineoplastic Agents*, *Cancer Vaccines*, *Immunoglobulin G*,
*CTLA-4 Antigen*, *Introns*) and procedure-like artifacts (e.g. *Blood
Specimen Collection*, *Gene Expression Profiling*, *Immunohistochemistry*)
so they never appear as drug nodes. When the API supplies a MeSH term
that matches a kept canonical form, that term wins as the display label.
The graph builder also supports site↔drug networks using CT.gov
location facility/city/country fields; site nodes use `type: "site"`.

Network output also honors the request-level `top_n`: when set, edges
are clipped to the top-N highest-weight pairs and any nodes whose only
edges were clipped are dropped from the response. `meta.edges_returned` /
`meta.nodes_returned` are updated accordingly.

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
  thread — *and* sets a process-wide flag so subsequent requests skip
  the httpx attempt entirely. This avoids paying the 403 RTT on every
  fan-out cell when the local CDN edge is unfriendly to httpx; the flag
  resets on process restart.
- **Planner repair.** If the model returns malformed JSON or a schema-invalid
  `QueryPlan`, the request retries once with an explicit repair prompt.
  Provider/API failures such as authentication errors are surfaced as
  planning errors; the service does not fabricate a default visualization.

## Tuning knobs (env vars)

- `CTGOV_PAGINATE_CAP` (default `2000`) — generic-path pagination cap;
  raise for more exact counts on generic sampled paths at the cost of
  latency.
- `CTGOV_HIGH_CARD_SCAN_CAP` (default `10000`) — candidate-discovery scan
  window for high-cardinality bar charts (`country`, `lead_sponsor`,
  `condition`, `intervention_name`) before per-candidate exact
  `countTotal` fan-out.
- `CTGOV_HIGH_CARD_CANDIDATE_CAP` (default `100`) — maximum discovered
  candidates to fan out exactly on high-cardinality bar charts.
- `CTGOV_NUMERIC_SCAN_CAP` (default `10000`) — applies to `histogram`
  and `scatter_plot` so numeric distributions cover a broad sample of
  matched trials.
- `CTGOV_SCATTER_POINT_CAP` (default `1000`) — display cap applied to
  scatter response points after the numeric scan; set to `0` to disable.
- `CTGOV_NETWORK_SCAN_CAP` (default `5000`) — applies to `network_graph`
  scans so edge weights reflect more relationships before the 200-edge
  display cap kicks in.
- `CTGOV_CACHE_TTL` (default `300` seconds), `CTGOV_CACHE_MAX` (default
  `256`) — in-process TTL cache for repeat queries.
- `CTGOV_CONCURRENCY` (default `8`) — semaphore on in-flight CT.gov
  requests, prevents fan-out paths from saturating upstream.
- `OPENROUTER_API_KEY` — required for live LLM calls (`OPENAI_API_KEY`
  is accepted as a fallback). `OPENROUTER_MODEL` (default
  `openai/gpt-4o-mini`), `OPENROUTER_BASE_URL` (default
  `https://openrouter.ai/api/v1`).

## Limitations and future work

- **Exact counts via fan-out for six small-enum dims** (`phase`,
  `overall_status`, `sponsor_class`, `study_type`, `sex`,
  `intervention_type`) plus `year` time-series and X-vs-Y comparisons
  over those dims. Each dim's bucket list is enumerated up front; one
  tiny `countTotal=true` request per bucket in parallel. Empty years and
  empty exact comparison cells are returned as explicit zero-count rows.
- **Country / sponsor / condition / intervention-name top-N rankings use
  candidate-discovery exact fan-out.** A sample window of up to
  `CTGOV_HIGH_CARD_SCAN_CAP` trials seeds the candidate set, then each
  discovered candidate gets its own `countTotal=true` request — so the
  *shown* trial counts are exact. The trade-off is that values that
  appear only outside the sample window (rare combinations) won't make
  the candidate list. A `candidate_set_sampled` warning is emitted in
  that case.
- **Free-text drug/condition matching.** We pass user-provided
  drug/condition strings straight through to `query.intr` / `query.cond`.
  A full MeSH lookup would tighten precision further.
- **English-only planner prompts.** The system prompt and few-shot examples
  are English.
- **No auth.** Intended for local evaluation; add an API key middleware
  before deploying. The CT.gov client *does* enforce a per-process
  concurrency limit and an in-process TTL cache.
- **Single-call OpenRouter integration.** One repair retry on
  schema-validation failure. Provider/API failures are returned as errors.
  No streaming.

---

## Repo layout

```
app/
  __init__.py
  main.py             FastAPI setup + routes
  paths.py            /analyze path selection and execution strategies
  exact_counts.py     countTotal fan-out helpers
  responses.py        response post-processing + AnalyzeResponse assembly
  constants.py        shared enum values and labels
  drugs.py            drug canonicalization + network drug extraction
  schemas.py          Pydantic request/response/plan models
  planner.py          OpenRouter planner call + repair retry
  planner_schema.py   planner system prompt + strict JSON schema
  plan_verifier.py    post-plan validation hook
  ctgov.py            ClinicalTrials.gov v2 client + study normalizer
  aggregate.py        build_bar / build_grouped_bar / build_time_series / build_histogram / build_scatter / build_network
  citations.py        excerpt selection + cite() helper
  static/
    index.html        single-page demo UI
    app.js            Vega-Lite + vis-network rendering
    style.css
examples/             7 captured request/response JSON pairs
tests/
  test_aggregate.py   unit tests for every builder
  test_openai_planner.py OpenRouter planner integration tests with fake SDK
requirements.txt
run.sh                convenience launcher (loads .env, starts uvicorn)
.env.example
```
