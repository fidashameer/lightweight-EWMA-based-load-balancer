#!/usr/bin/env python3
"""
Mininet topology for the SDN load-balancing experiments.

Layout:

    c1 ... cN  (clients)          h1 ... hM  (backend servers)
        \\        |                    |        /
         \\-------+---- s1 (OVS) ------+-------/
                        |
                  remote controller

One OpenFlow switch. Clients generate load; the controller decides which
backend server each new flow is sent to. Deliberately small — the study is
about the balancing policy, not topology scale, and large topologies are slow
under QEMU on Apple Silicon.

Usage:
    sudo python3 topology/lb_topo.py --servers 3 --clients 4
    sudo python3 topology/lb_topo.py --controller-ip 127.0.0.1 --cli
"""

import argparse

from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.link import TCLink
from mininet.cli import CLI
from mininet.log import setLogLevel, info


def build(servers=3, clients=4, ctrl_ip="127.0.0.1", ctrl_port=6653,
          link_bw=10, link_delay="1ms"):
    """Build and start the topology. Returns the Mininet object."""
    net = Mininet(controller=None, switch=OVSSwitch, link=TCLink,
                  autoSetMacs=True, cleanup=True)

    info("*** Adding remote controller\n")
    net.addController("c0", controller=RemoteController,
                      ip=ctrl_ip, port=ctrl_port)

    info("*** Adding switch\n")
    s1 = net.addSwitch("s1", protocols="OpenFlow13")

    info("*** Adding %d backend servers\n" % servers)
    server_hosts = []
    for i in range(1, servers + 1):
        h = net.addHost("h%d" % i, ip="10.0.0.%d/24" % i)
        net.addLink(h, s1, bw=link_bw, delay=link_delay)
        server_hosts.append(h)

    info("*** Adding %d clients\n" % clients)
    client_hosts = []
    for i in range(1, clients + 1):
        c = net.addHost("c%d" % i, ip="10.0.1.%d/24" % i)
        net.addLink(c, s1, bw=link_bw, delay=link_delay)
        client_hosts.append(c)

    net.start()
    return net, server_hosts, client_hosts


def start_servers(server_hosts, port=8000):
    """Start a trivial HTTP server on each backend so clients have something to hit."""
    for h in server_hosts:
        h.cmd("python3 -m http.server %d &> /tmp/%s_http.log &" % (port, h.name))
    info("*** HTTP servers listening on port %d\n" % port)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--servers", type=int, default=3)
    ap.add_argument("--clients", type=int, default=4)
    ap.add_argument("--controller-ip", default="127.0.0.1")
    ap.add_argument("--controller-port", type=int, default=6653)
    ap.add_argument("--bw", type=int, default=10, help="link bandwidth (Mbit/s)")
    ap.add_argument("--delay", default="1ms")
    ap.add_argument("--cli", action="store_true", help="drop into Mininet CLI")
    args = ap.parse_args()

    setLogLevel("info")
    net, servers, clients = build(
        servers=args.servers, clients=args.clients,
        ctrl_ip=args.controller_ip, ctrl_port=args.controller_port,
        link_bw=args.bw, link_delay=args.delay,
    )
    start_servers(servers)

    info("*** Servers: %s\n" % ", ".join(h.name for h in servers))
    info("*** Clients: %s\n" % ", ".join(h.name for h in clients))

    if args.cli:
        CLI(net)
    else:
        info("*** Running connectivity check\n")
        net.pingAll()

    net.stop()


if __name__ == "__main__":
    main()
