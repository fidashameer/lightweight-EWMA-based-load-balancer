#!/usr/bin/env python3
"""
In-flight connection-count SDN load balancer (Ryu, OpenFlow 1.3).

Motivation (from our own result): the byte-rate signal used by lb_leastload.py
INVERTS for compute-bound servers -- a saturating server completes fewer requests,
emits fewer bytes, and so looks idle and attracts even more traffic. This controller
uses a signal that moves the RIGHT way: the number of connections currently in flight
to each backend. A slow server holds its connections open longer, so it accumulates
MORE concurrent connections, which correctly marks it as busy.

Two changes vs lb_leastload.py, and ONLY two:
  1. Signal:     per-server in-flight connection count instead of byte rate.
                 Count is incremented when a connection's forward flow is installed
                 and decremented when that flow is removed (OFPFF_SEND_FLOW_REM +
                 a per-server cookie read back in the FlowRemoved handler).
  2. Granularity: flows match the full TCP 5-tuple (per connection), not just the
                 source IP, so the controller makes a routing decision for every
                 request instead of once per client per burst.

select_server() picks the server with the fewest in-flight connections, breaking ties
in round-robin order so load is not pinned to server 0 early on.

Run:  ryu-manager src/lb_conn.py
"""

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ether_types, arp, ipv4, tcp

VIRTUAL_IP = "10.0.0.100"
VIRTUAL_MAC = "00:00:00:00:00:fe"
CONN_IDLE = 2          # idle timeout (s) for a per-connection flow
COOKIE_BASE = 0x5B0000  # forward LB flows carry COOKIE_BASE + server_index

SERVERS = [
    {"ip": "10.0.0.1", "mac": "00:00:00:00:00:01", "port": 1},
    {"ip": "10.0.0.2", "mac": "00:00:00:00:00:02", "port": 2},
    {"ip": "10.0.0.3", "mac": "00:00:00:00:00:03", "port": 3},
]
PORT_TO_IDX = {s["port"]: i for i, s in enumerate(SERVERS)}


class ConnCountLB(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(ConnCountLB, self).__init__(*args, **kwargs)
        self.mac_to_port = {}
        self.datapaths = {}
        self.inflight = [0] * len(SERVERS)   # current in-flight connections per server
        self.rr = 0                          # round-robin pointer for tie-breaking

    # ---- signal: pick the backend with the fewest in-flight connections ----
    def select_server(self):
        m = min(self.inflight)
        minima = [i for i in range(len(SERVERS)) if self.inflight[i] == m]
        self.rr = (self.rr + 1) % len(minima)
        return SERVERS[minima[self.rr]]

    @set_ev_cls(ofp_event.EventOFPFlowRemoved, MAIN_DISPATCHER)
    def _flow_removed(self, ev):
        ck = ev.msg.cookie
        if COOKIE_BASE <= ck < COOKIE_BASE + len(SERVERS):
            idx = ck - COOKIE_BASE
            if self.inflight[idx] > 0:
                self.inflight[idx] -= 1

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

    def add_flow(self, dp, priority, match, actions, idle=0, hard=0, cookie=0, flags=0):
        ofp, psr = dp.ofproto, dp.ofproto_parser
        inst = [psr.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]
        mod = psr.OFPFlowMod(datapath=dp, priority=priority, match=match,
                             instructions=inst, idle_timeout=idle, hard_timeout=hard,
                             cookie=cookie, flags=flags)
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

    def _send_actions(self, dp, in_port, actions, data):
        psr = dp.ofproto_parser
        out = psr.OFPPacketOut(datapath=dp, buffer_id=dp.ofproto.OFP_NO_BUFFER,
                               in_port=in_port, actions=actions, data=data)
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
        tcp_pkt = pkt.get_protocol(tcp.tcp)

        if arp_pkt and arp_pkt.dst_ip == VIRTUAL_IP and arp_pkt.opcode == arp.ARP_REQUEST:
            self.reply_arp(dp, arp_pkt, eth, in_port)
            return

        if ip_pkt and ip_pkt.dst == VIRTUAL_IP and tcp_pkt:
            server, fwd_actions = self.install_lb_flows(dp, in_port, eth, ip_pkt, tcp_pkt)
            # send this first packet through the SAME rewrite the flow will apply,
            # otherwise the server receives a packet addressed to the VIP and drops it,
            # costing a ~1s TCP retransmit on every new connection.
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

    def install_lb_flows(self, dp, in_port, eth, ip_pkt, tcp_pkt):
        ofp, psr = dp.ofproto, dp.ofproto_parser
        server = self.select_server()
        idx = PORT_TO_IDX[server["port"]]
        self.inflight[idx] += 1
        self.logger.info("flow %s:%d -> VIP assigned to server %s (conn, inflight=%d)",
                         ip_pkt.src, tcp_pkt.src_port, server["ip"], self.inflight[idx])
        client_port = in_port
        sport, dport = tcp_pkt.src_port, tcp_pkt.dst_port
        cookie = COOKIE_BASE + idx

        # forward: client -> VIP  rewritten to the chosen server (per-connection match)
        fwd_match = psr.OFPMatch(eth_type=ether_types.ETH_TYPE_IP, ip_proto=6,
                                 ipv4_src=ip_pkt.src, ipv4_dst=VIRTUAL_IP,
                                 tcp_src=sport, tcp_dst=dport)
        fwd_actions = [psr.OFPActionSetField(eth_dst=server["mac"]),
                       psr.OFPActionSetField(ipv4_dst=server["ip"]),
                       psr.OFPActionOutput(server["port"])]
        self.add_flow(dp, 10, fwd_match, fwd_actions, idle=CONN_IDLE,
                      cookie=cookie, flags=ofp.OFPFF_SEND_FLOW_REM)

        # reverse: server -> client  rewritten back to the VIP
        rev_match = psr.OFPMatch(eth_type=ether_types.ETH_TYPE_IP, ip_proto=6,
                                 ipv4_src=server["ip"], ipv4_dst=ip_pkt.src,
                                 tcp_src=dport, tcp_dst=sport)
        rev_actions = [psr.OFPActionSetField(eth_src=VIRTUAL_MAC),
                       psr.OFPActionSetField(ipv4_src=VIRTUAL_IP),
                       psr.OFPActionOutput(client_port)]
        self.add_flow(dp, 10, rev_match, rev_actions, idle=CONN_IDLE)
        return server, fwd_actions
