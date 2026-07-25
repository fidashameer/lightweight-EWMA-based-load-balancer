# Experiments

## Design principle

Controlled comparison: **same topology, same traffic, only the balancing policy
changes.** Every result is averaged over multiple runs with variance reported —
never a single run.

## Policies compared (baselines + our method)

| Policy | Role | Notes |
|---|---|---|
| Round-robin | Baseline 1 (naive static) | Distributes in fixed rotation |
| Weighted round-robin | Baseline 2 (reasonable static) | Weights by server capacity — harder to beat, more convincing comparison |
| Reactive least-load | Baseline 3 (reactive) | Responds only after load is observed |
| **EWMA predictive (ours)** | Proposed | Lightweight moving-average latency prediction |

Beating *weighted* round-robin (not just plain RR) is what makes the comparison
credible to a reviewer.

## Test conditions (traffic)

| Condition | Purpose |
|---|---|
| Steady traffic | Control case — establishes baseline behaviour |
| Flash-crowd: sudden spike | Main case — sharp onset |
| Flash-crowd: gradual ramp | Robustness — shows the result isn't specific to one burst shape |

## Metrics

| Metric | Priority | Backs which claim |
|---|---|---|
| **P95 / P99 latency** | Primary (headline) | Tail-latency improvement under bursts |
| Controller decision latency / CPU | **Primary — proves "lightweight"** | The central claim; without this, "lightweight" is unsupported |
| Mean response time | Secondary | General performance |
| Throughput | Secondary | No regression under load |
| Packet loss | Secondary | Stability |
| Server load variance | Secondary | Even distribution |

**Note:** the overhead metric (controller decision latency / CPU) is not optional
polish — it is the evidence for the word "lightweight" in the project title. It maps
directly to a dedicated results subsection in the paper.

## Parameter sensitivity (EWMA smoothing factor alpha)

Run the EWMA policy across a sweep of alpha values (e.g. 0.1, 0.3, 0.5, 0.7, 0.9)
under the main flash-crowd condition. Report how P95/P99 latency varies with alpha
and justify the chosen operating value. This converts "we picked alpha=X" into a
studied trade-off.

## Mapping to paper sections

| Experiment | Paper section it supports |
|---|---|
| Policy comparison (all 4) under all conditions | Results — main comparison table |
| Overhead measurement | Results — "lightweight" substantiation |
| alpha sensitivity sweep | Results — method characterisation |
| Steady vs. burst shapes | Results — robustness / generalisability |

## Results storage

Raw output goes in `results/<date>_<policy>_<condition>_<run>/`.
Bulky `.pcap` captures are gitignored; commit the derived CSV/summary only.
Each result set must record: policy, condition, alpha (if applicable), run number,
and the environment (so it's reproducible).
