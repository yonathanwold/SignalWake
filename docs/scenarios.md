# Scenario Lab

Scenario Lab is SIGNALWAKE's second-order graph comparison surface. It answers
a narrow question: **what changes in this modeled infrastructure relationship
network if selected nodes or relationships are unavailable for the scenario?**
It does not answer whether a real asset is out, whether a service is disrupted,
or what a business, logistics, or economy outcome would be.

## Inputs and persistence

Creating a scenario writes a `Scenario` definition, ordered
`ScenarioTarget` rows, and a baseline graph snapshot. The snapshot is made
from the persisted `REFERENCE` infrastructure assets and persisted
`DERIVED`/`SOURCE_OBSERVED` relationships available at creation time. It
contains sorted node and edge IDs plus names/types and endpoint metadata, and
its canonical SHA-256 hash is stored with the scenario. The target rows retain
the selected node or edge snapshot used for the input.

The supported types are:

- `ASSET_UNAVAILABLE`: exactly one graph node.
- `EDGE_UNAVAILABLE`: exactly one graph relationship.
- `MULTIPLE_ASSETS_UNAVAILABLE`: two to 50 graph nodes.

Target existence and kind are checked before persistence. Duplicate targets,
empty selections, mixed node/edge selections, unsupported types, and selections
over the safe bound are rejected. An optional duration is retained as an
assumption for reproducibility; it does not change the static topology.

## Execution

`POST /scenarios/{id}/runs` is the explicit execution boundary. It rebuilds an
in-memory `GraphEngine` from the stored baseline snapshot, removes only the
selected nodes and/or edges, and computes the modified snapshot. No database
asset or relationship row is updated. A deterministic run key combines the
scenario input hash, baseline hash, scenario ID, and methodology version.
Repeating the run returns the same persisted `ScenarioRun` and `ScenarioResult`
instead of creating a duplicate.

The graph is currently undirected. Traversal uses sorted adjacency and bounded
unweighted breadth-first search. Results include:

- baseline and modified node/edge counts, component counts, and largest
  component sizes;
- explicitly removed node IDs and edge IDs (including edges incident to a
  removed node), plus surviving nodes whose baseline reachability changed;
- bounded all-surviving-node-pair shortest-path comparisons (up to 2,000 pairs
  and 200 changed paths), including unreachable transitions and hop deltas;
- alternate-route preservation, calculated by ignoring each candidate edge and
  checking whether its endpoints remain connected;
- baseline and modified Tarjan articulation-point sets and their differences;
- baseline and modified graph snapshots and hashes, methodology, assumptions,
  deterministic algorithm description, and limits.

## Structural resilience formula

The optional bounded score is a comparison aid, not a reliability probability.
The intact baseline is 100. The run stores every component and fixed weight:

```text
score = clamp(0, 100,
  100 × (
    0.45 × surviving_reachability_ratio
  + 0.35 × largest_component_ratio
  + 0.20 × alternate_route_preservation_ratio
  - 0.10 × path_inflation_penalty
  ))
```

`surviving_reachability_ratio` is scenario reachable pairs divided by baseline
reachable pairs. `largest_component_ratio` compares the largest surviving
component with the baseline largest component. `alternate_route_preservation`
compares the count of baseline alternate-route edges that remain alternate
routes. `path_inflation_penalty` is a bounded (0–1) normalized average of
positive hop increases. A denominator with no baseline pairs, components, or
alternate routes is treated as 1.0 (no evidence of degradation for that
component) and is recorded in the result. This score describes only the
modeled relationship graph.

## API and UI limits

The Scenario Lab uses real `/graph/nodes`, `/graph/edges`, and scenario API
responses. It does not substitute demo scenario results when the API is down.
The graph result endpoint accepts `state=baseline|modified` and caps returned
nodes at 200 (and edges at four times that cap). GET requests are side-effect
free; only the POST create and POST run operations write scenario projections.

Current relationship facts are source-backed or deterministic derivations from
the Phase 2 fixtures/imports. They are not operational dependency semantics,
and Scenario Lab does not invent `DEPENDS_ON`, upstream/downstream, alternate
suppliers, outage, service, economic, logistical, or causal claims.
