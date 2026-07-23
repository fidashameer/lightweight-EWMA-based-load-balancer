# Project Brief

**Title:** Predictive vs. Reactive Load Balancing in Software-Defined Networks
under Flash-Crowd Traffic

**Student:** Fida M S (24BAI0180)
**Course:** BCSE308L / BCSE308P — Research-Oriented Project

## Research question

Can an SDN controller reduce tail latency during flash-crowd traffic by predicting
short-term server load, rather than reacting after overload occurs — using a
predictor lightweight enough to run in real time on the controller?

## Deliverables (mapped to rubric)

| Rubric line | Marks | Where it comes from |
|---|---|---|
| Problem Identification | 5 | This brief + paper Section I |
| Novelty | 8 | `docs/references.md` — stated contribution |
| Architecture | 5 | `docs/02-architecture.md` |
| Prototype | 12 | `src/` + `topology/` |
| Simulation | 8 | `experiments/` |
| Validation | 5 | Comparison vs. two baselines, `experiments/results/` |
| Patent | 5 | Patent canvas (secondary artifact) |
| Paper | 5 | IEEE-format paper |
| Presentation | 5 | Review decks |
| Documentation | 2 | This repository |

## Timeline

| Weeks | Phase | Output |
|---|---|---|
| 1–2 | Survey + environment | `docs/references.md`, working toolchain |
| 3–5 | Design | `docs/02-architecture.md`, EWMA policy spec |
| 6–10 | Prototype | Baselines + EWMA balancer in `src/` |
| 11–13 | Simulation | Experiment runs, results |
| 14–15 | Write-up | Paper, patent canvas, demo |

## Working principles

- Commit small and often — the history is part of the deliverable.
- Cite every close neighbour found; never claim first-of-its-kind.
- A negative result (EWMA doesn't beat the baselines) is reported honestly.
