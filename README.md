# Predictive vs. Reactive Load Balancing in SDN under Flash-Crowd Traffic

**Course:** BCSE308L / BCSE308P — Research-Oriented Project
**Student:** Fida M S (24BAI0180)

A lightweight EWMA-based predictive load balancer implemented in an SDN controller,
benchmarked against round-robin and reactive least-load baselines. The headline
metric is **tail latency (P95/P99) during flash-crowd onset**.

---

## Problem

Most SDN load-balancing comparisons evaluate under steady or uniformly increasing
traffic. Real services face bursty, flash-crowd load, and users experience the
*worst-case* request, not the average. Reactive balancers respond only after
servers are already overloaded.

**Research question:** Can an SDN controller reduce tail latency during flash-crowd
traffic by predicting short-term server load, using a predictor lightweight enough
to run in real time on the controller?

## Approach

| | |
|---|---|
| Predictor | EWMA over recent per-server response latency (no ML) |
| Baselines | Round-robin (static), reactive least-load |
| Conditions | Steady traffic (control), flash-crowd onset (main case) |
| Metrics | **P95/P99 latency (primary)**, mean latency, throughput, packet loss, load variance |

**Success criterion (defined in advance):** the predictive balancer measurably
lowers P95/P99 latency during burst onset versus both baselines. If it does not,
that negative result is reported and explained — it is still a valid finding.

## Scope

**In scope:** SDN emulation (Mininet + OpenFlow), EWMA prediction, comparison
against two baselines, the metrics above.

**Out of scope:** physical hardware, heavy ML models, multi-controller distributed
control, security/encrypted-traffic aspects.

## Tech stack

- **Emulation:** Mininet · **Data plane:** Open vSwitch (OpenFlow)
- **Controller:** TBD week 1 — see `docs/01-week1-setup-log.md`
- **Logic:** Python · **Traffic:** iperf / custom generator
- **Analysis:** tcpdump / tshark · **Host:** MacBook Air M4 → UTM + ARM64 Ubuntu VM

## Repository layout

```
docs/          Design notes, weekly logs, references, decisions
topology/      Mininet topology definitions
src/           Controller apps: baselines + EWMA balancer
experiments/   Run scripts, configs, and raw results
scripts/       Environment setup and smoke tests
```

## Status

See `docs/01-week1-setup-log.md` for the current environment state and the
controller decision. Weekly progress notes live in `docs/`.

## Related work

Tracked in `docs/references.md`. This project is positioned as an incremental,
reproducible study — prior work in predictive SDN load balancing and EWMA-based
balancing is cited explicitly, not omitted.
