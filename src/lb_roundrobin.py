#!/usr/bin/env python3
"""
Round-robin SDN load balancer (Ryu, OpenFlow 1.3) + L2 learning fallback.

Baseline #1. Proves the flow-installation path:
  - client -> VIRTUAL_IP: controller picks a backend (round-robin) and installs
    rewrite rules both directions.
  - all other traffic (incl. server<->client ARP and replies): normal L2 learning
    switch behaviour, so hosts can resolve each other and replies get back.

Run:  ryu-manager src/lb_roundrobin.py
"""

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


class RoundRobinLB(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(RoundRobinLB, self).__init__(*args, **kwargs)
        self.rr_index = 0
        self.mac_to_port = {}

    def select_server(self):
        server = SERVERS[self.rr_index % len(SERVERS)]
        self.rr_index += 1
        return server

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

        # 1) ARP for the VIP -> controller answers with the virtual MAC
        if arp_pkt and arp_pkt.dst_ip == VIRTUAL_IP and arp_pkt.opcode == arp.ARP_REQUEST:
            self.reply_arp(dp, arp_pkt, eth, in_port)
            return

        # 2) IP traffic destined to the VIP -> load balance
        if ip_pkt and ip_pkt.dst == VIRTUAL_IP:
            self.install_lb_flows(dp, in_port, eth, ip_pkt)
            # also forward THIS first packet so the ping isn't dropped
            server = SERVERS[(self.rr_index - 1) % len(SERVERS)]
            self._send_out(dp, in_port, server["port"], msg.data)
            return

        # 3) everything else -> plain L2 learning switch
        #    (this carries server<->client ARP and the return replies)
        out_port = self.mac_to_port[dp.id].get(eth.dst, ofp.OFPP_FLOOD)
        if out_port != ofp.OFPP_FLOOD:
            match = psr.OFPMatch(eth_dst=eth.dst, eth_src=eth.src)
            self.add_flow(dp, 1, match,
                          [psr.OFPActionOutput(out_port)], idle=20)
            self._send_out(dp, in_port, out_port, msg.data)
        else:
            self._flood(msg, dp, in_port, msg.data)

    def reply_arp(self, dp, arp_pkt, eth, in_port):
        psr = dp.ofproto_parser
        reply = packet.Packet()
        reply.add_protocol(ethernet.ethernet(
            ethertype=ether_types.ETH_TYPE_ARP,
            src=VIRTUAL_MAC, dst=eth.src))
        reply.add_protocol(arp.arp(
            opcode=arp.ARP_REPLY,
            src_mac=VIRTUAL_MAC, src_ip=VIRTUAL_IP,
            dst_mac=arp_pkt.src_mac, dst_ip=arp_pkt.src_ip))
        reply.serialize()
        self._send_out(dp, dp.ofproto.OFPP_CONTROLLER, in_port, reply.data)
        self.logger.info("ARP reply for VIP -> %s", arp_pkt.src_ip)

    def install_lb_flows(self, dp, in_port, eth, ip_pkt):
        ofp, psr = dp.ofproto, dp.ofproto_parser
        server = self.select_server()
        self.logger.info("flow %s -> VIP assigned to server %s (rr)",
                         ip_pkt.src, server["ip"])
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
