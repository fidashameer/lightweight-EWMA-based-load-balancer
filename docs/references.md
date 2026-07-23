# Related Work

This project is **incremental and positioned honestly**. Prior work in this space is
substantial; the contribution is a specific combination, not a first-of-its-kind claim.
Every close neighbour found during the survey is recorded here and will be cited in
the paper's related-work section.

> **Rule for this file:** if a paper is close to what we're doing, it goes in here.
> Omitting a close neighbour is what gets a paper rejected — citing it is what makes
> an incremental contribution legitimate.

## Categories to survey (Weeks 1–2)

### A. SDN load balancing — classic policies
Round-robin, weighted round-robin, least-connection comparisons in Mininet/OpenFlow.
_Typical gap:_ evaluated under steady or uniformly increasing traffic.

| # | Ref | Venue / Year | What it does | How we differ |
|---|-----|--------------|--------------|---------------|
| A1 |  |  |  |  |
| A2 |  |  |  |  |

### B. Predictive / ML-based SDN load balancing
LSTM, ARIMA, RL-based forecasting of load in SDN controllers.
_Typical gap:_ heavy models; throughput-focused reporting rather than tail latency.

| # | Ref | Venue / Year | What it does | How we differ |
|---|-----|--------------|--------------|---------------|
| B1 |  |  |  |  |
| B2 |  |  |  |  |

### C. EWMA / moving-average latency balancing
"Peak EWMA" style balancers in service meshes (Envoy, Linkerd, Finagle, brpc).
**Important:** this is the closest prior art to our predictor. Must be cited.
_How we differ:_ implemented inside an SDN/OpenFlow controller installing flow
rules, rather than in an application-layer proxy.

| # | Ref | Venue / Year | What it does | How we differ |
|---|-----|--------------|--------------|---------------|
| C1 |  |  |  |  |

### D. Bursty / flash-crowd traffic handling
Surveys and papers that specifically address burst traffic in SDN.

| # | Ref | Venue / Year | What it does | How we differ |
|---|-----|--------------|--------------|---------------|
| D1 |  |  |  |  |

## Our stated contribution

1. **Setting** — EWMA latency prediction moved from service-mesh proxies into an
   SDN/OpenFlow controller.
2. **Simplicity** — a lightweight, explainable moving-average predictor instead of
   LSTM/ARIMA, viable in real time on the controller.
3. **Evaluation angle** — benchmarked specifically on **P95/P99 latency at
   flash-crowd onset**, a condition most SDN load-balancing comparisons don't isolate.

**Not claimed:** first-ever, or novel in concept. Claimed: a specific, reproducible
combination with honest baselines.

## Search log

Record searches so the survey is reproducible and defensible in the viva.

| Date | Database | Query | Useful hits |
|------|----------|-------|-------------|
|  | IEEE Xplore |  |  |
|  | Google Scholar |  |  |
|  | ACM DL |  |  |
