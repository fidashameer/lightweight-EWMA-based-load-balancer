#!/usr/bin/env python3
"""
Capacity-aware per-client assignment SDN load balancer (Ryu, OpenFlow 1.3).

This policy comes directly from our own finding. Round-robin wins because it pins each
client to one server for the whole burst, which bounds how many requests can be in flight
at a single-threaded server at once. The other policies broke that bound by routing per
request and could not react fast enough to restore it. So here we KEEP the per-client
pinning (the concurrency bound is therefore structural and needs no runtime signal) and
only make the pinning smarter: each new client is assigned to the server that minimises its
projected tail, using the known per-server service times.

Projected tail if we add this client to server i:  (clients_already_on_i + 1) * work_i.
We assign the client to the server with the smallest projected tail, then pin it there.

For a 20/40/80 ms pool and four clients this greedy lands on roughly 3 clients on the fast
server, 1 on the medium, 0 on the slow one, which bounds the worst tail well below what
round-robin gets by spreading a client onto the 80 ms server. On a homogeneous pool it
reduces to an even 2:1:1 split, i.e. it matches round-robin when there is nothing to exploit.

Service times are read from SERVER_WORK_MS (the same calibration the weighted baseline uses);
if unset, all servers are treated as equal and the policy reduces to least-assigned-client.

Run:  ryu-manager src/lb_capacity.py
"""

import os
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ether_types, arp, ipv4

VIRTUAL_IP = "10.0.0.100"
VIRTUAL_MAC = "00:00:00:00:00:fe"

SERVERS = [
    {"ip": "10.0.0.1", "mac": "00:00:00:00:00:01", "port": 1},
    {"ip": "10.0.0.2", "mac": "00:00:00:00:00:02", "port": 2},
    {"ip": "10.0.0.3", "mac": "00:00:00:00:00:03", "port": 3},
]
PORT_TO_IDX = {s["port"]: i for i, s in enumerate(SERVERS)}


def server_work_times(n):
    raw = os.environ.get("SERVER_WORK_MS", "30")
    vals = []
    for v in raw.split(","):
        v = v.strip()
        if v:
            try:
                vals.append(float(v))
            except ValueError:
                pass
    if not vals:
        vals = [30.0]
    while len(vals) < n:
        vals.append(vals[-1])
    return vals[:n]


class CapacityAwareLB(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(CapacityAwareLB, self).__init__(*args, **kwargs)
        self.mac_to_port = {}
        self.datapaths = {}
        self.work = server_work_times(len(SERVERS))        # per-server service time (ms)
        self.clients_on = [0] * len(SERVERS)               # clients pinned to each server
        self.client_map = {}                               # client IP -> server index
        self.logger.info("capacity-aware LB; service times (ms): %s", self.work)

    # ---- capacity-aware per-client assignment ----
    def select_server(self, client_ip):
        if client_ip in self.client_map:
            return SERVERS[self.client_map[client_ip]]
        best, best_proj = 0, None
        for i in range(len(SERVERS)):
            proj = (self.clients_on[i] + 1) * self.work[i]   # projected tail on server i
            if best_proj is None or proj < best_proj:
                best_proj, best = proj, i
        self.clients_on[best] += 1
        self.client_map[client_ip] = best
        return SERVERS[best]

    # ---- switch/flow boilerplate (same framework as the other policies) ----
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        dp = ev.msg.datapath
        self.datapaths[dp.id] = dp
        ofp, psr = dp.ofproto, dp.ofproto_parser
        match = psr.OFPMatch()
        actions = [psr.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER)]
        self.add_flow(dp, 0, match, actions)
        self.logger.info("switch %s connected, table-miss installed", dp.id)

    def add_flow(self, dp, priority, match, actions, idle=0, hard=0):
        ofp, psr = dp.ofproto, dp.ofproto_parser
        inst = [psr.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]
        mod = psr.OFPFlowMod(datapath=dp, priority=priority, match=match,
                             instructions=inst, idle_timeout=idle, hard_timeout=hard)
        dp.send_msg(mod)

    def _flood(self, msg, dp, in_port, data):
        ofp, psr = dp.ofproto, dp.ofproto_parser
        out = psr.OFPPacketOut(datapath=dp, buffer_id=ofp.OFP_NO_BUFFER,
                               in_port=in_port,
                               actions=[psr.OFPActionOutput(ofp.OFPP_FLOOD)],
                               data=data)
        dp.send_msg(out)

    def _send_actions(self, dp, in_port, actions, data):
        psr = dp.ofproto_parser
        out = psr.OFPPacketOut(datapath=dp, buffer_id=dp.ofproto.OFP_NO_BUFFER,
                               in_port=in_port, actions=actions, data=data)
        dp.send_msg(out)

    def _send_out(self, dp, in_port, out_port, data):
        psr = dp.ofproto_parser
        out = psr.OFPPacketOut(datapath=dp, buffer_id=dp.ofproto.OFP_NO_BUFFER,
                               in_port=in_port,
                               actions=[psr.OFPActionOutput(out_port)], data=data)
        dp.send_msg(out)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg = ev.msg
        dp = msg.datapath
        ofp, psr = dp.ofproto, dp.ofproto_parser
        in_port = msg.match["in_port"]

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)
        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return

        self.mac_to_port.setdefault(dp.id, {})
        self.mac_to_port[dp.id][eth.src] = in_port

        arp_pkt = pkt.get_protocol(arp.arp)
        ip_pkt = pkt.get_protocol(ipv4.ipv4)

        if arp_pkt and arp_pkt.dst_ip == VIRTUAL_IP and arp_pkt.opcode == arp.ARP_REQUEST:
            self.reply_arp(dp, arp_pkt, eth, in_port)
            return

        if ip_pkt and ip_pkt.dst == VIRTUAL_IP:
            server, fwd_actions = self.install_lb_flows(dp, in_port, eth, ip_pkt)
            self._send_actions(dp, in_port, fwd_actions, msg.data)
            return

        out_port = self.mac_to_port[dp.id].get(eth.dst, ofp.OFPP_FLOOD)
        if out_port != ofp.OFPP_FLOOD:
            match = psr.OFPMatch(eth_dst=eth.dst, eth_src=eth.src)
            self.add_flow(dp, 1, match, [psr.OFPActionOutput(out_port)], idle=20)
            self._send_out(dp, in_port, out_port, msg.data)
        else:
            self._flood(msg, dp, in_port, msg.data)

    def reply_arp(self, dp, arp_pkt, eth, in_port):
        reply = packet.Packet()
        reply.add_protocol(ethernet.ethernet(
            ethertype=ether_types.ETH_TYPE_ARP, src=VIRTUAL_MAC, dst=eth.src))
        reply.add_protocol(arp.arp(
            opcode=arp.ARP_REPLY, src_mac=VIRTUAL_MAC, src_ip=VIRTUAL_IP,
            dst_mac=arp_pkt.src_mac, dst_ip=arp_pkt.src_ip))
        reply.serialize()
        self._send_out(dp, dp.ofproto.OFPP_CONTROLLER, in_port, reply.data)
        self.logger.info("ARP reply for VIP -> %s", arp_pkt.src_ip)

    def install_lb_flows(self, dp, in_port, eth, ip_pkt):
        ofp, psr = dp.ofproto, dp.ofproto_parser
        server = self.select_server(ip_pkt.src)
        idx = PORT_TO_IDX[server["port"]]
        self.logger.info("flow %s -> VIP assigned to server %s (cap, clients_on=%s)",
                         ip_pkt.src, server["ip"], self.clients_on)
        client_port = in_port

        fwd_match = psr.OFPMatch(eth_type=ether_types.ETH_TYPE_IP,
                                 ipv4_src=ip_pkt.src, ipv4_dst=VIRTUAL_IP)
        fwd_actions = [psr.OFPActionSetField(eth_dst=server["mac"]),
                       psr.OFPActionSetField(ipv4_dst=server["ip"]),
                       psr.OFPActionOutput(server["port"])]
        self.add_flow(dp, 10, fwd_match, fwd_actions, idle=10)

        rev_match = psr.OFPMatch(eth_type=ether_types.ETH_TYPE_IP,
                                 ipv4_src=server["ip"], ipv4_dst=ip_pkt.src)
        rev_actions = [psr.OFPActionSetField(eth_src=VIRTUAL_MAC),
                       psr.OFPActionSetField(ipv4_src=VIRTUAL_IP),
                       psr.OFPActionOutput(client_port)]
        self.add_flow(dp, 10, rev_match, rev_actions, idle=10)
        return server, fwd_actions
