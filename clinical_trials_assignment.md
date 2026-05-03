# Take-Home Assignment: ClinicalTrials.gov Query-to-Visualization Agent (Backend)

**Primary goal:** Build a backend service that converts clinical-trial
questions into structured visualization outputs backed by
ClinicalTrials.gov API data.

------------------------------------------------------------------------

## 1) Problem Overview

You will build an AI-enabled backend that answers questions about
clinical trials using the ClinicalTrials.gov API. The user will provide
a natural-language query, along with optional structured fields (which
you may define). Your system must:

1.  Interpret the user's question.
2.  Retrieve relevant data from ClinicalTrials.gov.
3.  Identify if a visualization is needed and what type is suitable.
4.  Produce a visualization specification that answers the question.

A frontend is not required, but your output must be clear and structured
so that a frontend can render the visualization reliably.

------------------------------------------------------------------------

## 2) Data Source

Use the ClinicalTrials.gov Data API as the authoritative data source.

-   API documentation: https://clinicaltrials.gov/data-api/api
-   You may use any endpoints/fields needed.

------------------------------------------------------------------------

## 3) Functional Requirements

### 3.1 Inputs

Your service must accept a request containing:

**Required** - `query` (string): a natural language question about
clinical trials.

**Optional structured fields (candidate-defined)**\
Examples (not required): - `drug_name` - `condition/disease` -
`trial_phase` - `sponsor` - `country/location` - `start_year`,
`end_year` - any other useful fields

You must document your request schema (field names, types,
optional/required, validation).

**Example request:**

``` json
{
  "query": "How has the number of trials for this drug changed over time?",
  "drug_name": "Pembrolizumab"
}
```

------------------------------------------------------------------------

### 3.2 Outputs

Your service must return a structured response describing a
visualization.

**Required output components**

1.  **Visualization specification**
    -   `type`: visualization type (e.g., bar_chart, time_series,
        network_graph)
    -   `title`: human-readable title
    -   `encoding`: mapping from fields to visual channels (x, y,
        series, nodes/edges)
    -   `data`: data points required to render the visualization
2.  **Response metadata**
    -   additional fields needed for rendering (units, sorting, time
        granularity, etc.)
    -   optional notes (assumptions, filters applied, query
        interpretation)

You must document your response schema.

**Example response:**

``` json
{
  "visualization": {
    "type": "bar_chart",
    "title": "Trials by Phase for Pembrolizumab",
    "encoding": {
      "x": {"field": "phase"},
      "y": {"field": "trial_count"}
    },
    "data": [
      {"phase": "Phase 1", "trial_count": 32},
      {"phase": "Phase 2", "trial_count": 78}
    ]
  },
  "meta": {
    "filters": {"drug_name": "Pembrolizumab"},
    "source": "clinicaltrials.gov"
  }
}
```

------------------------------------------------------------------------

## 4) Visualization Requirements

-   The answer must be a visualization (via structured specification).
-   Support multiple visualization types:
    -   bar chart / grouped bar chart
    -   timeline / time series
    -   scatter plot
    -   histogram
    -   network graph (drugs, sponsors, conditions, investigators,
        sites)

**Design goal:** Cover as many query types as possible with a single
coherent approach.

------------------------------------------------------------------------

## 5) Bonus: Deep Citations (Source Traceability)

Include deep citations from ClinicalTrials.gov:

-   Each datum includes references to underlying trial records.
-   Each reference includes:
    -   `nct_id`
    -   exact text excerpt supporting the datum

**Example:**

``` json
{
  "phase": "Phase 3",
  "trial_count": 41,
  "citations": [
    {
      "nct_id": "NCT01234567",
      "excerpt": "Phase 3 randomized study evaluating pembrolizumab..."
    }
  ]
}
```

------------------------------------------------------------------------

## 6) Submission Requirements

Submit a zip file containing:

1.  **Code**: All source code.
2.  **README**:
    -   how to run
    -   request/response schema
    -   design decisions and tradeoffs
    -   limitations and future work
3.  **Example Runs**: 3--5 queries with actual JSON outputs.
4.  **Optional Demo**:
    -   small UI
    -   deployed endpoint
    -   short demo video

------------------------------------------------------------------------

## Appendix: Example Query Types

### Time trends

-   "How has the number of trials for \[drug\] changed per year since
    2015?"
-   "How many trials started each year for \[condition\]?"

### Distributions

-   "How are \[condition\] trials distributed across phases?"
-   "What are the most common intervention types?"

### Comparisons

-   "Compare phases for Drug A vs Drug B."
-   "Compare sponsor categories across conditions."

### Geographic patterns

-   "Which countries have the most recruiting trials?"

### Relationships / networks

-   "Show a network of sponsors ↔ drugs."
-   "Which drugs co-occur in combination studies?"
