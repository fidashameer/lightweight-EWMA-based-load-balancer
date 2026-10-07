#!/usr/bin/env python3
"""
Parse a 1998 World Cup trace shard into a per-second request-arrival profile.

World Cup binary record = 20 bytes, big-endian. First 4 bytes = Unix timestamp.
We stream-decompress and count requests per second, then save the busiest
contiguous window as a flash-crowd arrival profile (requests per second).
"""
import gzip, struct, json, sys
from collections import Counter

INFILE  = sys.argv[1] if len(sys.argv) > 1 else "wc_day25.gz"
OUTFILE = sys.argv[2] if len(sys.argv) > 2 else "worldcup_profile.json"
REC = 20  # bytes per record

per_sec = Counter()
n = 0
with gzip.open(INFILE, "rb") as f:
    while True:
        buf = f.read(REC * 50000)          # read in chunks
        if not buf:
            break
        # process whole records only
        usable = len(buf) - (len(buf) % REC)
        for off in range(0, usable, REC):
            ts = struct.unpack(">I", buf[off:off+4])[0]  # timestamp (big-endian uint32)
            per_sec[ts] += 1
            n += 1

if not per_sec:
    print("No records parsed - format mismatch?"); sys.exit(1)

t0, t1 = min(per_sec), max(per_sec)
span = t1 - t0 + 1
print(f"Parsed {n:,} requests over {span:,} seconds "
      f"({span/3600:.1f} h). Peak = {max(per_sec.values())} req/s, "
      f"mean = {n/span:.1f} req/s.")

# find the busiest 120-second window (the flash-crowd surge)
WIN = 120
secs = list(range(t0, t1+1))
best_start, best_sum = t0, 0
run = 0
from collections import deque
window = deque()
cur = 0
for s in secs:
    window.append(per_sec.get(s, 0)); cur += per_sec.get(s, 0)
    if len(window) > WIN:
        cur -= window.popleft()
    if len(window) == WIN and cur > best_sum:
        best_sum, best_start = cur, s - WIN + 1

profile = [per_sec.get(best_start + i, 0) for i in range(WIN)]
json.dump({"source": "1998 World Cup trace (wc_day25 / TR1), ITA, verified MD5",
           "window_seconds": WIN,
           "requests_per_second": profile,
           "peak_rps": max(profile), "total_in_window": sum(profile)},
          open(OUTFILE, "w"), indent=2)
print(f"\nBusiest {WIN}s window: {best_sum:,} requests, "
      f"peak {max(profile)} req/s, min {min(profile)} req/s.")
print(f"Shape (every 10s): {profile[::10]}")
print(f"Saved -> {OUTFILE}")
