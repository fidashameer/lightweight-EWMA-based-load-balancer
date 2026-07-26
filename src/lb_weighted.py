#!/usr/bin/env python3
"""
Weighted round-robin SDN load balancer (Ryu, OpenFlow 1.3).

Baseline #2. Identical framework to lb_roundrobin.py (VIP rewriting, bidirectional
flows, L2 fallback). The ONLY difference is select_server(): servers carry a weight,
and higher-weight (higher-capacity) servers are chosen proportionally more often.

Uses the standard smooth weighted round-robin algorithm (as in nginx): avoids
bursty "give server A all its slots at once" behaviour and instead interleaves them.

Run:  ryu-manager src/lb_weighted.py
"""

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ether_types, arp, ipv4

VIRTUAL_IP = "10.0.0.100"
VIRTUAL_MAC = "00:00:00:00:00:fe"

# Each server now has a weight. Higher weight = chosen more often.
# Example: server 1 is twice as capable as servers 2 and 3.
SERVERS = [
    {"ip": "10.0.0.1", "mac": "00:00:00:00:00:01", "port": 1, "weight": 2},
    {"ip": "10.0.0.2", "mac": "00:00:00:00:00:02", "port": 2, "weight": 1},
    {"ip": "10.0.0.3", "mac": "00:00:00:00:00:03", "port": 3, "weight": 1},
]


class WeightedRoundRobinLB(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(WeightedRoundRobinLB, self).__init__(*args, **kwargs)
        self.mac_to_port = {}
        # smooth weighted round-robin state: one "current weight" per server
        self.current_weights = [0] * len(SERVERS)
        self.total_weight = sum(s["weight"] for s in SERVERS)
        self.last_choice = None

    def select_server(self):
        """Smooth weighted round-robin (nginx algorithm).

        Each call: add each server's static weight to its current weight, pick the
        server with the highest current weight, then subtract total_weight from the
        chosen one. This interleaves picks proportionally to weight.
        """
        best = -1
        for i, s in enumerate(SERVERS):
            self.current_weights[i] += s["weight"]
            if best == -1 or self.current_weights[i] > self.current_weights[best]:
                best = i
        self.current_weights[best] -= self.total_weight
        self.last_choice = best
        return SERVERS[best]

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        dp = ev.msg.datapath
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
            server = self.install_lb_flows(dp, in_port, eth, ip_pkt)
            self._send_out(dp, in_port, server["port"], msg.data)
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
        server = self.select_server()
        self.logger.info("flow %s -> VIP assigned to server %s (wrr w=%d)",
                         ip_pkt.src, server["ip"], server["weight"])
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
        return server
