# Experiments

## Design

Same topology, same traffic, **only the balancing policy changes.**

| Variable | Values |
|---|---|
| Policy | round-robin, reactive least-load, EWMA predictive |
| Traffic | steady (control), flash-crowd onset (main case) |
| Runs | repeat each combination; report mean + variance |

## Metrics

- **P95 / P99 latency** — primary
- Mean response time
- Throughput
- Packet loss
- Server load variance

## Results

Raw output goes in `results/<date>_<policy>_<condition>/`.
Bulky `.pcap` captures are gitignored; keep the derived CSV/summary committed.
