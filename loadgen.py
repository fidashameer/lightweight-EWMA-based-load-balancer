#!/usr/bin/env python3
"""
Flash-crowd load generator + per-request latency recorder.

Runs from a Mininet client host. Fires HTTP GET requests at the virtual IP, each on
a FRESH connection (so every request is independently load-balanced, and so it models
a flash crowd of many short-lived requests). Records per-request latency to a CSV.

Patterns:
  burst  : all requests fired as fast as possible (sudden flash-crowd onset)
  ramp   : request rate increases linearly over the duration (gradual onset)
  steady : fixed inter-request gap (control case)

Usage (run on a client, e.g. c1):
  python3 loadgen.py --vip 10.0.0.100 --port 8000 --n 200 --pattern burst \
                     --out /tmp/lat_c1.csv --label ewma_burst_run1_c1

Output CSV columns: label,seq,start_epoch,latency_ms,status
  status: 'ok' or an error string (timeouts/refusals recorded, not silently dropped)
"""

import argparse
import socket
import time
import csv
import sys

def do_request(vip, port, timeout):
    """Open a fresh TCP connection, send a minimal HTTP GET, read the response.
    Returns (latency_seconds, status_string)."""
    start = time.time()
    try:
        s = socket.create_connection((vip, port), timeout=timeout)
        req = "GET / HTTP/1.0\r\nHost: %s\r\n\r\n" % vip
        s.sendall(req.encode())
        # read until close or timeout
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
        s.close()
        return (time.time() - start, "ok")
    except socket.timeout:
        return (time.time() - start, "timeout")
    except (ConnectionRefusedError, OSError) as e:
        return (time.time() - start, "err:%s" % type(e).__name__)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vip", default="10.0.0.100")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--n", type=int, default=200, help="number of requests")
    ap.add_argument("--pattern", choices=["burst", "ramp", "steady", "trace"], default="burst")
    ap.add_argument("--trace-file", default="traces/worldcup_profile.json")
    ap.add_argument("--duration", type=float, default=10.0,
                    help="seconds over which to spread requests (ramp/steady)")
    ap.add_argument("--timeout", type=float, default=5.0)
    ap.add_argument("--out", required=True)
    ap.add_argument("--label", default="run")
    args = ap.parse_args()

    rows = []
    _trace_offsets = None
    if args.pattern == "trace":
        import json as _json, os as _os
        _tf = args.trace_file
        if not _os.path.exists(_tf):
            _tf = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                "traces", "worldcup_profile.json")
        _prof = _json.load(open(_tf))["requests_per_second"]
        _tot = float(sum(_prof)) or 1.0
        _cum, _run = [], 0.0
        for _c in _prof:
            _run += _c
            _cum.append(_run / _tot)
        _nsec = len(_prof)
        _trace_offsets = []
        for _k in range(args.n):
            _f = (_k + 0.5) / args.n
            _lo = 0
            while _lo < _nsec and _cum[_lo] < _f:
                _lo += 1
            if _lo >= _nsec:
                _lo = _nsec - 1
            _prev = _cum[_lo - 1] if _lo > 0 else 0.0
            _w = _cum[_lo] - _prev
            _fin = (_f - _prev) / _w if _w > 0 else 0.0
            _trace_offsets.append(args.duration * (_lo + _fin) / _nsec)
    t0 = time.time()
    for seq in range(args.n):
        # schedule: when should this request fire?
        if args.pattern == "burst":
            target = t0  # all at once, as fast as the loop allows
        elif args.pattern == "trace":
            target = t0 + _trace_offsets[seq]
        elif args.pattern == "steady":
            target = t0 + (args.duration * seq / max(args.n - 1, 1))
        else:  # ramp: quadratic spacing -> rate increases over time
            frac = seq / float(max(args.n - 1, 1))
            target = t0 + args.duration * (frac ** 2)
        now = time.time()
        if target > now:
            time.sleep(target - now)

        start_epoch = time.time()
        lat, status = do_request(args.vip, args.port, args.timeout)
        rows.append((args.label, seq, "%.6f" % start_epoch, "%.3f" % (lat * 1000.0), status))

    with open(args.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["label", "seq", "start_epoch", "latency_ms", "status"])
        w.writerows(rows)

    ok = sum(1 for r in rows if r[4] == "ok")
    sys.stderr.write("loadgen done: %d/%d ok, wrote %s\n" % (ok, args.n, args.out))

if __name__ == "__main__":
    main()
