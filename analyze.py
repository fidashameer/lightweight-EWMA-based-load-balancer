#!/usr/bin/env python3
"""
Latency analyzer: read one or more loadgen CSVs and compute summary stats.

Headline metric: P95 / P99 tail latency. Also reports mean, median, min, max,
success rate, and throughput (successful requests / wallclock span).

Usage:
  python3 analyze.py /tmp/lat_c1.csv /tmp/lat_c2.csv ...            # print summary
  python3 analyze.py --append results.csv --policy ewma --pattern burst --run 1 \
                     --alpha 0.3 /tmp/lat_c*.csv                    # append a result row

Percentiles use the nearest-rank method on successful requests only. Failed requests
(timeouts/refusals) are counted in success_rate but excluded from latency percentiles
(their "latency" is the timeout ceiling, which would distort the distribution) -- this
is stated so the methodology is honest and reproducible.
"""

import argparse
import csv
import math
import os
import sys

def percentile(sorted_vals, p):
    if not sorted_vals:
        return float("nan")
    # nearest-rank
    k = max(1, int(math.ceil(p / 100.0 * len(sorted_vals))))
    return sorted_vals[k - 1]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--append", help="append a summary row to this results CSV")
    ap.add_argument("--policy", default="")
    ap.add_argument("--pattern", default="")
    ap.add_argument("--run", default="")
    ap.add_argument("--alpha", default="")
    args = ap.parse_args()

    lats = []          # successful latencies (ms)
    total = 0
    ok = 0
    start_min = None
    start_max = None
    for path in args.files:
        with open(path) as f:
            r = csv.DictReader(f)
            for row in r:
                total += 1
                se = float(row["start_epoch"])
                start_min = se if start_min is None else min(start_min, se)
                start_max = se if start_max is None else max(start_max, se)
                if row["status"] == "ok":
                    ok += 1
                    lats.append(float(row["latency_ms"]))

    lats.sort()
    span = (start_max - start_min) if (start_min is not None and start_max) else 0.0
    thr = (ok / span) if span > 0 else float("nan")

    def stat(name, val, unit="ms"):
        print("  %-14s %.3f %s" % (name, val, unit))

    print("=== latency summary (%d files, %d requests) ===" % (len(args.files), total))
    print("  success_rate   %.1f%% (%d/%d)" % (100.0 * ok / total if total else 0, ok, total))
    if lats:
        stat("mean", sum(lats) / len(lats))
        stat("p50", percentile(lats, 50))
        stat("p95", percentile(lats, 95))
        stat("p99", percentile(lats, 99))
        stat("min", lats[0])
        stat("max", lats[-1])
    stat("throughput", thr, "req/s")

    if args.append and lats:
        newfile = not os.path.exists(args.append)
        with open(args.append, "a", newline="") as f:
            w = csv.writer(f)
            if newfile:
                w.writerow(["policy", "pattern", "alpha", "run", "n_total", "n_ok",
                            "success_pct", "mean_ms", "p50_ms", "p95_ms", "p99_ms",
                            "min_ms", "max_ms", "throughput_reqps"])
            w.writerow([args.policy, args.pattern, args.alpha, args.run, total, ok,
                        "%.1f" % (100.0 * ok / total if total else 0),
                        "%.3f" % (sum(lats) / len(lats)),
                        "%.3f" % percentile(lats, 50),
                        "%.3f" % percentile(lats, 95),
                        "%.3f" % percentile(lats, 99),
                        "%.3f" % lats[0], "%.3f" % lats[-1],
                        "%.3f" % thr])
        sys.stderr.write("appended result row to %s\n" % args.append)

if __name__ == "__main__":
    main()
