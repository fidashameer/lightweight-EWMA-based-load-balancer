# Related Work

This project is **incremental and positioned honestly**. Prior work in this space is
substantial; the contribution is a specific combination (lightweight EWMA prediction,
in an SDN/OpenFlow controller, evaluated on tail latency at flash-crowd onset), not a
first-of-its-kind claim.

> **Rule for this file:** every close neighbour found during the survey is recorded
> here and will be cited in the paper's related-work section.

> **Access note:** [IEEE] = on IEEE Xplore (check VIT access). [OA] = open-access free
> PDF. [SURVEY] = literature review; mine its reference list for more papers.

---

## A. SDN load balancing: classic policies (round-robin, weighted RR, least-conn)
Gap: evaluated under steady/increasing traffic, not bursts. Establishes the standard Mininet+Ryu+iperf methodology and our baselines.

| # | Reference | Venue/Year | What it does | How we differ |
|---|-----------|------------|--------------|---------------|
| A1 | Traffic LB in SDN Using Round-Robin and Dijkstra | IEEE | RR+Dijkstra, fat-tree, Mininet+Ryu+iperf | We add prediction; tail latency under bursts |
| A2 | Application for load balancing in SDN | IEEE | FIFO/RR/Deficit-RR on Ryu | Our policy is predictive, not queue-based |
| A3 | Server LB Techniques Using SDN | IEEE | Bandwidth vs round-robin, Mininet | Predictive vs reactive under flash-crowd |
| A4 | Performance Analysis of RR LB in SDN | IEEE | RR, Mininet+Floodlight | We focus on tail latency |
| A5 | Server LB with Round Robin in SDN | IEEE | RR benchmark, POX | Establishes RR baseline |
| A6 | Applying LB Strategies on Different SDN Environments | OA | Weighted RR, Mininet+RPi+Ryu | Relevant to our weighted-RR baseline |
| A7 | A Comparative Study on LB Algorithms in SDN | OA | Comparative study, Ryu+Mininet | Closest in format to ours |

## B. Predictive / ML-based SDN load balancing
Gap: heavy ML models (LSTM/DNN/RL); throughput-focused, rarely tail latency. Our differentiator vs this category is SIMPLICITY.

| # | Reference | Venue/Year | What it does | How we differ |
|---|-----------|------------|--------------|---------------|
| B1 | Yang et al., predictive LB technique for SDN cloud services | Computing 2019 | Predictive LB for SDN cloud | Close neighbour; ours is lighter, tail-latency focused |
| B2 | Babayigit & Ulu, deep learning for SDN DCN load balancing | IJCS 2021 | DL-based SDN DCN LB | We avoid heavy DL; explainable EWMA |
| B3 | Filali et al., Preemptive SDN LB with ML for delay-sensitive apps | IEEE TVT | ML preemptive LB | Simpler predictor, tail latency |
| B4 | AI-based load balancing in SDN: a comprehensive survey | arXiv 2308.02149 [SURVEY][OA] | Survey of AI/ML SDN LB | Mine its references for more papers |
| B5 | Predictive Load Balancing in Cloud Computing: A Comparative Study | ACM 2024 [OA] | Compares predictive LB (LR, trees, LSTM) | Confirms simple predictors under-explored vs LSTM |

## C. EWMA / Peak-EWMA latency-aware balancing (CLOSEST prior art)
This is the nearest existing work to our mechanism. MUST be cited prominently.

| # | Reference | Venue/Year | What it does | How we differ |
|---|-----------|------------|--------------|---------------|
| C1 | L3: Latency-aware Load Balancing in Multi-Cluster Service Mesh | Middleware 2024 [OA] | EWMA+PeakEWMA, 26%/22% tail-latency cut vs RR & C3 | CLOSEST neighbour. They: service mesh/K8s/AWS. Us: SDN/OpenFlow in Mininet |
| C2 | Linkerd, Beyond Round Robin: Load Balancing for Latency (2016) | Industry [OA] | Original Peak-EWMA: RR vs least-loaded vs peak-EWMA | Foundational; industry, not SDN |
| C3 | Envoy Peak EWMA Load Balancer (docs) | Industry [OA] | Production Peak-EWMA (P2C + RTT) | We study it in SDN |
| C4 | Alibaba ASM peak EWMA (docs) | Industry [OA] | Peak-EWMA for burst traffic, P90/P95/P99 | Confirms EWMA used for bursts; sets our bar |

## D. Bursty / flash-crowd traffic handling (OUR EVALUATION ANGLE)
Thinner at the SDN-LB-policy intersection; most work is CDN/auto-scaling. This thinness is where our contribution sits.

| # | Reference | Venue/Year | What it does | How we differ |
|---|-----------|------------|--------------|---------------|
| D1 | A Novel Dynamic SDN Approach to Neutralize Traffic Burst | Computers MDPI 2023 [OA] | SDN for burst; finds standard SDN bottlenecks | Motivates our problem; no EWMA LB policy |
| D2 | Ari et al., Managing Flash Crowds on the Internet | MASCOTS 2003 [OA] | Classic flash-crowd characterisation | Defines flash-crowd; not SDN LB |
| D3 | Optimizing and LB for Flash Crowd in CDN | ResearchGate [OA] | Flash-crowd LB in CDN | CDN not SDN; motivates burst focus |
| D4 | Behal et al., Characterizing DDoS Attacks and Flash Events | Comp Sci Review 2017 | Flash-event vs DDoS characterisation | Useful for modelling realistic bursts |

## Our stated contribution (for the paper's Introduction)

1. Setting: EWMA/Peak-EWMA latency prediction, established in service-mesh proxies
   (C1-C4), moved into an SDN/OpenFlow controller that installs flow rules.
2. Simplicity: a lightweight moving-average predictor instead of the LSTM/DNN/RL
   approaches dominant in SDN predictive LB (B1-B5). Explainable, low-overhead.
3. Evaluation angle: benchmarked on P95/P99 latency at flash-crowd onset (D1-D4),
   a condition the SDN LB comparisons in category A do not isolate.

Not claimed: first-ever, or novel in concept. The mechanism exists (C1-C4). Claimed:
a specific, reproducible study of it in the SDN setting with honest baselines.

## Honest assessment (read before writing the paper)

- Closest neighbour is C1 (L3, Middleware 2024): EWMA/PeakEWMA + tail latency.
  Our defensible distinction is the setting (SDN/OpenFlow/Mininet, not service mesh)
  and the lightweight framing. This distinction is real but narrow; do not oversell.
- The bursty-traffic + SDN-LB-policy intersection (D applied to A) is genuinely thin.
  That is the strongest part of the contribution.
- A sharp reviewer will ask: "how is this different from Peak-EWMA / L3?" Answer:
  different platform, lightweight non-ML, tail-latency-at-burst-onset evaluation.

## Papers to read in FULL (not just cite): C1, B1, D1

## Search log (for reproducibility / viva defence)

| Date | Source | Query | Hits |
|------|--------|-------|------|
| 2026-07-25 | Web/IEEE | Peak EWMA load balancing tail latency | C1-C4 |
| 2026-07-25 | Web/IEEE | SDN load balancing Mininet Ryu round robin | A1-A7 |
| 2026-07-25 | Web/IEEE | predictive ML load balancing SDN LSTM | B1-B5 |
| 2026-07-25 | Web/IEEE | flash crowd bursty traffic load balancing SDN | D1-D4 |
