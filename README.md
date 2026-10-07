# Predictive vs. Reactive Load Balancing in SDN under Flash-Crowd Traffic

**Course:** BCSE308L / BCSE308P — Computer Networks (Research-Oriented Project)
**Student:** Fida M S (24BAI0180)

An empirical study of a lightweight EWMA-based predictive load balancer implemented
in an SDN (OpenFlow) controller, benchmarked against round-robin, weighted
round-robin, and reactive least-load baselines. The headline metric is tail latency
(P95/P99) during flash-crowd onset, evaluated across homogeneous and heterogeneous
server pools.

> **Headline finding (negative result):** Across every condition tested, the
> lightweight EWMA predictor does **not** reduce tail latency relative to plain
> round-robin. Round-robin is the most stable and consistently best-performing
> policy. The load-aware policies are not only no better on average but an order of
> magnitude less stable (EWMA P99 standard deviation up to ~88 ms versus ~2–4 ms for
> round-robin). We report this honestly and explain the mechanism. See `paper/`.

## Problem

Most SDN load-balancing comparisons evaluate under steady or uniformly increasing
traffic. Real services face bursty, flash-crowd load, and users experience the
worst-case request, not the average.

**Research question:** Can a lightweight, non-ML EWMA predictor running inside an SDN
controller reduce tail latency during flash-crowd traffic, compared with standard
baselines?

**Answer (this study):** No — under the tested conditions. Round-robin's blind, even
distribution is hard to beat when servers are identical, and EWMA's smoothing is
counterproductive when server slowness is persistent rather than transient. This is a
rigorous empirical comparison rather than a new winning algorithm; its value is in the
honesty and reproducibility of the result.

## Approach

| | |
|---|---|
| **Proposed method** | EWMA over an SDN-native per-server load signal (OpenFlow port-stats byte-rate), with Power-of-Two-Choices (P2C) selection. No machine learning. |
| **Baselines** | Round-robin, weighted round-robin (smooth WRR), reactive least-load |
| **Traffic** | Flash-crowd burst (main case) and steady (control) |
| **Server pools** | Homogeneous (equal speeds) and heterogeneous (fast/medium/slow, 1:2:4) |
| **Metrics** | P95/P99 tail latency (primary), mean latency, throughput, success rate |
| **Rigor** | Each configuration run 7+ times; mean ± standard deviation reported |

**Important honesty note on the load signal:** an SDN controller observes the network
layer, not application-layer response times. The proposed method therefore smooths an
OpenFlow-derived *load* signal, not measured *latency*, and we test empirically whether
that load signal translates into latency improvement (it does not clearly do so). This
distinguishes the work from application-layer Peak-EWMA balancers (e.g. Envoy, Linkerd,
and the academic L3 system) and is discussed in `docs/02-architecture.md` and the paper.

## Key results (P99 tail latency, ms, mean ± SD over 7+ runs)

**Homogeneous servers**

| Policy | Burst | Steady |
|---|---|---|
| Round-robin | **91.3 ± 4.0** | **90.1 ± 2.2** |
| Weighted RR | 91.1 ± 2.8 | 89.0 ± 2.3 |
| Reactive least-load | 132.0 ± 19.5 | 148.9 ± 19.5 |
| EWMA (proposed) | 131.5 ± 56.4 | 128.4 ± 88.1 |

**Heterogeneous servers (1:2:4)**

| Policy | Burst | Steady |
|---|---|---|
| Round-robin | **98.2 ± 2.6** | 95.4 ± 3.3 |
| Weighted RR | 97.7 ± 1.9 | **95.8 ± 1.2** |
| Reactive least-load | 114.4 ± 55.8 | 109.0 ± 57.7 |
| EWMA (proposed) | 111.2 ± 39.5 | 111.3 ± 24.1 |

**Real event-driven trace (1998 World Cup flash crowd)**

| Policy | Homogeneous | Heterogeneous |
|---|---|---|
| Round-robin | **90.2 ± 3.2** | **99.1 ± 2.1** |
| Weighted RR | 92.6 ± 3.9 | 99.0 ± 1.8 |
| Reactive least-load | 144.9 ± 20.2 | 116.2 ± 57.9 |
| EWMA (proposed) | 100.7 ± 21.0 | 111.9 ± 25.9 |

Replaying the busiest 120 s of the World Cup trace (inverse-CDF sampling of the
recorded arrival timings) reproduces the synthetic result and exposes the
load-aware policies' instability directly: least-load's P99 ranges from 82 ms to
240 ms across identical heterogeneous runs, while round-robin holds ~99 ms with
SD under 2 ms. See `traces/` and paper §V.F.

An α-sweep (smoothing factor 0.1–0.9) shows a usable band at α ≈ 0.1–0.7 and a
pathological collapse at α = 0.9. Full data in `experiments/results/`.

## Tech stack

- **Emulation:** Mininet 2.3.1 · **Data plane:** Open vSwitch 2.17 (OpenFlow 1.3)
- **Controller:** Ryu 4.34 (Python) — see `docs/01-week1-setup-log.md` for the
  Ryu/eventlet compatibility fix required on Python 3.10
- **Traffic/analysis:** custom HTTP flash-crowd generator + percentile analyzer
- **Host:** MacBook Air M4 → UTM (QEMU) + ARM64 Ubuntu 22.04 VM

## Repository layout

```
docs/          Design notes, week-1 setup log, architecture/policy spec, references
topology/      Mininet topology (single-subnet VIP setup)
src/           Four controllers: lb_roundrobin, lb_weighted, lb_leastload, lb_ewma
experiments/   loadgen, analyzer, orchestrator, slow backend, and raw result CSVs
scripts/       Environment smoke test
paper/         IEEE-format paper (empirical study, honest negative result)
```

## Reproducing the experiments

```bash
# environment: Ubuntu 22.04, Mininet + OVS + Ryu (see docs/01-week1-setup-log.md)
sudo mn -c

# homogeneous, 7 runs, all four policies, burst + steady
SERVER_WORK_MS=40 sudo -E python3 run_experiment.py \
    --policies rr wrr least ewma --patterns burst steady \
    --runs 7 --clients 4 --n 120 \
    --out experiments/results/results_homogeneous_7.csv

# heterogeneous (fast/medium/slow)
SERVER_WORK_MS=20,40,80 sudo -E python3 run_experiment.py \
    --policies rr wrr least ewma --patterns burst steady \
    --runs 7 --clients 4 --n 120 \
    --out experiments/results/results_heterogeneous_7.csv
```

**Real event-driven trace (1998 World Cup).** The arrival profile ships in
`traces/worldcup_profile.json` (regenerate from the raw log with
`traces/parse_wc.py`). Replay it by swapping the pattern:

```bash
SERVER_WORK_MS=40 sudo -E python3 run_experiment.py \
    --policies rr wrr least ewma --patterns trace \
    --runs 7 --clients 4 --n 120 \
    --out experiments/results/results_homogeneous_7.csv

SERVER_WORK_MS=20,40,80 sudo -E python3 run_experiment.py \
    --policies rr wrr least ewma --patterns trace \
    --runs 7 --clients 4 --n 120 \
    --out experiments/results/results_heterogeneous_7.csv
```

## Related work

Tracked in `docs/references.md`. This project is positioned as an incremental,
reproducible empirical study; the closest prior art (the L3 / Peak-EWMA family of
application-layer balancers) is cited explicitly and the differences are stated, not
omitted.

## Status

Complete. All four controllers implemented and verified; full experiment matrix run
across two server scenarios with statistical reporting; IEEE-format paper written.
Submitted for course Review 0 (ranked #5 of the cohort, "Proceed with Refinement");
subsequent refinements — refined title, explicit differentiation, and statistical
significance via 7-run mean ± SD — are reflected here and in `paper/`. The
flash-crowd model is additionally validated against a real event-driven trace
(1998 World Cup), which reproduces the negative result; see paper §V.F and
`traces/`.
