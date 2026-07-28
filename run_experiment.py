#!/usr/bin/env python3
"""
Experiment orchestrator (v4): full policy x pattern x repeat matrix,
with HETEROGENEOUS backend servers.

Server speeds are set per-backend from the SERVER_WORK_MS env var: a comma-separated
list of per-request work-times in ms, one per server. Example:
    SERVER_WORK_MS=20,40,80   -> h1 fast (20ms), h2 medium (40ms), h3 slow (80ms)
If fewer values than servers are given, the last value repeats. Default: 30 for all.

This heterogeneity is the condition under which a load-aware policy (least-load / EWMA)
can beat round-robin: RR blindly sends 1/3 of traffic to the slow server, creating a
tail; a load-aware policy routes away from it.

Run as root from the repo root (use sudo -E to pass env through):
  SERVER_WORK_MS=20,40,80 sudo -E python3 run_experiment.py \
      --policies rr wrr least ewma --patterns burst steady \
      --runs 3 --clients 4 --n 150 --out experiments/results/results_het.csv
"""

import argparse
import os
import subprocess
import time
import signal

from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.link import TCLink
from mininet.log import setLogLevel, info

RYU = "/home/syraously/.local/bin/ryu-manager"
PYPATH = "/home/syraously/.local/lib/python3.10/site-packages"
POLICY_FILES = {
    "rr":    "src/lb_roundrobin.py",
    "wrr":   "src/lb_weighted.py",
    "least": "src/lb_leastload.py",
    "ewma":  "src/lb_ewma.py",
}
VIP = "10.0.0.100"
HTTP_PORT = 8000
REPO = os.getcwd()


def server_work_times(n_servers):
    raw = os.environ.get("SERVER_WORK_MS", "30")
    vals = [v.strip() for v in raw.split(",") if v.strip()]
    if not vals:
        vals = ["30"]
    while len(vals) < n_servers:
        vals.append(vals[-1])
    return vals[:n_servers]


def start_controller(policy, alpha=None, logpath="/tmp/ctrl.log"):
    env = dict(os.environ)
    env["PYTHONPATH"] = PYPATH + ":" + env.get("PYTHONPATH", "")
    if alpha is not None:
        env["EWMA_ALPHA"] = str(alpha)
    logf = open(logpath, "w")
    p = subprocess.Popen([RYU, POLICY_FILES[policy]],
                         stdout=logf, stderr=subprocess.STDOUT, env=env,
                         preexec_fn=os.setsid)
    return p, logf


def stop_controller(proc, logf):
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGINT)
        proc.wait(timeout=5)
    except Exception:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            pass
    logf.close()


def build_net(n_servers, n_clients):
    net = Mininet(controller=None, switch=OVSSwitch, link=TCLink,
                  autoSetMacs=True, cleanup=True)
    net.addController("c0", controller=RemoteController, ip="127.0.0.1", port=6653)
    s1 = net.addSwitch("s1", protocols="OpenFlow13")
    servers, clients = [], []
    for i in range(1, n_servers + 1):
        h = net.addHost("h%d" % i, ip="10.0.0.%d/24" % i)
        net.addLink(h, s1, bw=10, delay="1ms")
        servers.append(h)
    for i in range(1, n_clients + 1):
        c = net.addHost("c%d" % i, ip="10.0.0.%d/24" % (i + 10))
        net.addLink(c, s1, bw=10, delay="1ms")
        clients.append(c)
    net.start()
    return net, servers, clients


def loadgen_cmd(n, pattern, out, label):
    return ["python3", os.path.join(REPO, "loadgen.py"),
            "--vip", VIP, "--port", str(HTTP_PORT), "--n", str(n),
            "--pattern", pattern, "--duration", "10",
            "--out", out, "--label", label]


def one_run(policy, pattern, run_idx, n_servers, n_clients, n_req, alpha, out_csv):
    tag = "%s_%s_run%d" % (policy, pattern, run_idx)
    works = server_work_times(n_servers)
    info("\n*** RUN %s (alpha=%s, server_ms=%s)\n" % (tag, alpha, ",".join(works)))

    proc, logf = start_controller(policy, alpha)
    time.sleep(2)

    net, servers, clients = build_net(n_servers, n_clients)
    time.sleep(3)

    # start heterogeneous slow servers (each its own work-time)
    httpd = []
    for i, h in enumerate(servers):
        p = h.popen(["python3", os.path.join(REPO, "slowserver.py"), str(HTTP_PORT)],
                    env={"SLOW_WORK_MS": works[i]},
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        httpd.append(p)
    time.sleep(1.5)

    # connectivity warm-up
    warm = clients[0].popen(loadgen_cmd(3, "steady", "/tmp/warm.csv", "warm"),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        warm.wait(timeout=30)
    except Exception:
        warm.kill()
        info("*** WARNING: warm-up did not complete for %s\n" % tag)

    # flash crowd
    procs, outfiles = [], []
    for c in clients:
        of = "/tmp/lat_%s_%s.csv" % (tag, c.name)
        outfiles.append(of)
        procs.append(c.popen(loadgen_cmd(n_req, pattern, of, "%s_%s" % (tag, c.name)),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))

    deadline = time.time() + 180
    for p in procs:
        try:
            p.wait(timeout=max(1, int(deadline - time.time())))
        except Exception:
            p.kill()

    for p in httpd:
        try:
            p.kill()
        except Exception:
            pass

    time.sleep(1)
    net.stop()
    stop_controller(proc, logf)

    analyze_cmd = ["python3", os.path.join(REPO, "analyze.py"),
                   "--append", out_csv,
                   "--policy", policy, "--pattern", pattern,
                   "--run", str(run_idx), "--alpha", str(alpha if alpha else "")]
    analyze_cmd += outfiles
    subprocess.call(analyze_cmd)
    time.sleep(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--policies", nargs="+", default=["rr", "wrr", "least", "ewma"])
    ap.add_argument("--patterns", nargs="+", default=["burst", "steady"])
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--servers", type=int, default=3)
    ap.add_argument("--clients", type=int, default=4)
    ap.add_argument("--n", type=int, default=150)
    ap.add_argument("--alpha", default=None)
    ap.add_argument("--out", default="experiments/results/results.csv")
    args = ap.parse_args()

    setLogLevel("info")
    os.makedirs(os.path.dirname(args.out), exist_ok=True)

    for policy in args.policies:
        alpha = args.alpha if policy == "ewma" else None
        for pattern in args.patterns:
            for run_idx in range(1, args.runs + 1):
                one_run(policy, pattern, run_idx, args.servers, args.clients,
                        args.n, alpha, args.out)

    info("\n*** ALL RUNS DONE -> %s\n" % args.out)


if __name__ == "__main__":
    main()
