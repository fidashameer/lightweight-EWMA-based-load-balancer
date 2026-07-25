# Architecture & EWMA Policy Specification

Design phase (Weeks 3-5). This is the spec that the Week 6-10 prototype implements.
Every design choice below is justified so it can be defended in the viva/paper.

## System overview

One OpenFlow switch, a small client pool, and 3-4 backend servers. The controller
runs the EWMA balancing logic and installs flow rules that steer each new client
flow to a chosen server.

Topology: clients (c1..cN) and servers (h1..hM) all connect to switch s1 (OVS),
which is controlled by the Ryu controller running the EWMA load-balancing app.

## 1. What the controller measures (load signal)

Decision: per-server load derived from OpenFlow port/flow statistics — active
flow count and recent byte/packet rate per server-facing port, polled at a fixed
interval (e.g. every 1 s).

Why not response latency (true Peak-EWMA)?
True Peak-EWMA tracks application-layer response time. An SDN controller sits at the
network layer and observes flows, not HTTP round-trips. Measuring true response time
would require active probing that (a) adds complexity, (b) introduces overhead that
undercuts the "lightweight" claim, and (c) is hard to get right in the timeline.

Framing (state honestly in the paper): we adapt the EWMA technique to an SDN-native,
controller-observable load signal. We do NOT claim to replicate Peak-EWMA exactly.

Known assumption / risk: the control signal is flow-based load, but the headline
metric is tail latency. We assume load correlates with latency (overloaded servers
are slow). This is treated as an empirical result to VERIFY, not an assumption to
rely on — we measure actual P95/P99 latency to confirm the load signal translates
into latency improvement.

## 2. The EWMA computation

Per server, updated every polling interval:

    score_new = alpha * current_sample + (1 - alpha) * score_old

- current_sample = normalised load reading for that server this interval
  (active-flow count, optionally combined with byte-rate).
- alpha = smoothing factor in (0, 1). High alpha reacts fast to spikes but is noisy;
  low alpha is smooth but sluggish.
- score_old = previous EWMA score (initialised to 0 or a neutral baseline).

Pure arithmetic — no ML, no training. This IS the "lightweight" property and must be
measured (controller CPU / per-decision time) to substantiate the claim.

alpha is swept, not fixed. The sensitivity experiment tries alpha in
{0.1, 0.3, 0.5, 0.7, 0.9}, reports how P95/P99 varies, then justifies the chosen
value. There is no single correct alpha; characterising the trade-off is part of the
contribution.

## 3. Score to server selection

Decision: Power-of-Two-Choices (P2C). On each new flow, sample two servers at random,
compare their EWMA scores, pick the lower (better) one.

Why not greedy (always pick the global lowest)?
Greedy has a documented failure mode — herding: every new flow sees the same "best"
server, they pile on, it overloads, then all stampede to the next, causing
oscillation. P2C breaks the herd because not every flow chooses from the same full
ranking. It is what real Peak-EWMA implementations (Envoy, Linkerd, Finagle) use, so
choosing it aligns our method with established practice.

Honest caveat: with a small pool (3-4), herding is milder and P2C's advantage over
greedy is modest. But P2C costs almost nothing extra and is the correct, defensible
choice. We note the scale caveat in the paper.

## 4. Flow-rule installation

- Trigger: on PacketIn for a new client flow, the controller runs selection and
  installs an OpenFlow rule directing that flow to the chosen server.
- Scope: new flows only. Existing flows are NOT re-routed when scores change.
  Re-routing mid-flow is complex and can break live connections; new-flows-only is
  standard and sufficient here.
- Flow rules carry an idle/hard timeout so stale entries clear.

## 5. Baselines (must share this exact framework)

All baselines use the same topology, traffic, and flow-installation path — only the
selection step differs:

| Policy | Selection rule |
|---|---|
| Round-robin | Next server in fixed rotation |
| Weighted round-robin | Rotation weighted by server capacity |
| Reactive least-load | Pick current least-loaded server (no smoothing/prediction) |
| EWMA predictive (ours) | P2C over EWMA scores |

The key comparison is EWMA (smoothed/predictive) vs. reactive least-load
(instantaneous, no smoothing) — this isolates the effect of the EWMA prediction
itself, not just "load-aware vs. round-robin".

## 6. Parameters (record every value used, for reproducibility)

| Parameter | Meaning | Default / sweep |
|---|---|---|
| alpha | EWMA smoothing factor | sweep {0.1,0.3,0.5,0.7,0.9} |
| poll_interval | Stats polling period | 1 s (tune if noisy) |
| n_servers | Backend pool size | 3-4 |
| flow_idle_timeout | OpenFlow rule idle timeout | e.g. 10 s |
| load signal weights | flow-count vs byte-rate mix | decide during build; record it |

## Open questions to resolve during the build (Weeks 6-10)

- Exact composition of current_sample (flow count only, or flow count + byte rate?).
  Start with active-flow count; add byte-rate only if flow count alone is too coarse.
- Normalisation of the load sample so alpha behaves consistently across servers.
- Whether poll_interval and alpha interact (fast polling + high alpha = noise).

## Design decisions summary (for the paper's Method section)

1. Load signal: SDN-native flow stats (honest to platform; "lightweight" preserved).
2. Predictor: EWMA smoothing, alpha swept.
3. Selection: Power-of-Two-Choices (avoids herding; matches real Peak-EWMA).
4. Flow handling: new-flows-only, timeout-based cleanup.
5. Fair comparison: all policies share topology/traffic/flow-path; only selection differs.
