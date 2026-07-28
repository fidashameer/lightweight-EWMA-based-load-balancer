#!/usr/bin/env python3
"""
Congesting backend server for the load-balancing experiments.

Plain http.server returns in ~8ms no matter the load, so no policy can improve on
another -- there is no congestion to avoid. This server instead:

  1. does REAL CPU work per request (busy-loop for ~WORK_MS milliseconds), so a
     server handling many concurrent requests actually gets backed up; and
  2. is SINGLE-THREADED (one request at a time), so concurrent requests QUEUE --
     this is what turns "many requests to one server" into rising latency.

Together these make server response time depend on how many requests a policy piles
onto each backend -- which is exactly the condition under which a smarter balancer
(least-load / EWMA) can help, and under which round-robin can hurt by ignoring load.

WORK_MS is read from the SLOW_WORK_MS env var (default 30). Tune it to control how
easily servers congest.

Run (on a backend host):  SLOW_WORK_MS=30 python3 slowserver.py 8000
"""

import os
import sys
import time
import socketserver
import http.server

WORK_MS = float(os.environ.get("SLOW_WORK_MS", "30"))


class SlowHandler(http.server.BaseHTTPRequestHandler):
    # silence logging (writing to stderr would skew timing)
    def log_message(self, *args):
        pass

    def do_GET(self):
        # busy-loop for WORK_MS of real CPU work (not sleep -- sleep wouldn't
        # create CPU contention between queued requests)
        deadline = time.perf_counter() + (WORK_MS / 1000.0)
        x = 0
        while time.perf_counter() < deadline:
            x += 1  # burn CPU
        body = b"ok\n"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    # single-threaded server: one request served at a time -> requests queue
    httpd = socketserver.TCPServer(("0.0.0.0", port), SlowHandler)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
