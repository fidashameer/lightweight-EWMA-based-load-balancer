# Controller applications

| File | Purpose |
|---|---|
| `baseline_roundrobin.py` | Static round-robin balancer (baseline 1) |
| `baseline_leastload.py`  | Reactive least-load balancer (baseline 2) |
| `ewma_balancer.py`       | EWMA predictive balancer (our approach) |

All three expose the same interface so experiments can swap the policy while
keeping topology and traffic identical — this is what makes the comparison
controlled.

Controller framework (Ryu / POX / ONOS) is decided in Week 1; see
`docs/01-week1-setup-log.md`.
