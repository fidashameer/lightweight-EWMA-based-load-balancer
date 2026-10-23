#!/usr/bin/env python3
"""
Response-time SDN load balancer (Ryu, OpenFlow 1.3), signal derived from flow lifetime.

Second non-inverting signal in our signal study. Instead of counting connections, this
controller estimates each backend's recent SERVICE TIME without any application-layer
instrumentation: because the workload opens a fresh TCP connection per request, a flow's
lifetime (install -> FlowRemoved) is essentially that request's duration. The controller
reads the duration reported on FlowRemoved, subtracts the idle-timeout tail, and keeps a
smoothed per-server estimate. A slow server produces longer-lived flows, so its estimate
rises -- the signal moves the right way, unlike byte rate.

Same two changes vs lb_leastload.py as lb_conn.py: a different (non-inverting) signal and
per-connection (5-tuple) matching. select_server() picks the lowest estimated response
time; until a server has produced a completed flow it is sampled in round-robin order.

Run:  ryu-manager src/lb_rt.py
"""

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ether_types, arp, ipv4, tcp

VIRTUAL_IP = "10.0.0.100"
VIRTUAL_MAC = "00:00:00:00:00:fe"
CONN_IDLE = 2            # idle timeout (s) for a per-connection flow
RT_ALPHA = 0.3           # smoothing for the per-server response-time estimate
COOKIE_BASE = 0x5B0000   # forward LB flows carry COOKIE_BASE + server_index

SERVERS = [
    {"ip": "10.0.0.1", "mac": "00:00:00:00:00:01", "port": 1},
    {"ip": "10.0.0.2", "mac": "00:00:00:00:00:02", "port": 2},
    {"ip": "10.0.0.3", "mac": "00:00:00:00:00:03", "port": 3},
]
PORT_TO_IDX = {s["port"]: i for i, s in enumerate(SERVERS)}


class ResponseTimeLB(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(ResponseTimeLB, self).__init__(*args, **kwargs)
        self.mac_to_port = {}
        self.datapaths = {}
        self.est = [None] * len(SERVERS)   # smoothed response-time estimate (ms) or None
        self.rr = 0                        # round-robin pointer (sampling / tie-break)

    # ---- signal: pick the backend with the lowest estimated response time ----
    def select_server(self):
        if any(e is None for e in self.est):
            # still sampling: rotate so every server gets at least one completed flow
            self.rr = (self.rr + 1) % len(SERVERS)
            return SERVERS[self.rr]
        m = min(self.est)
        minima = [i for i in range(len(SERVERS)) if self.est[i] == m]
        self.rr = (self.rr + 1) % len(minima)
        return SERVERS[minima[self.rr]]

    @set_ev_cls(ofp_event.EventOFPFlowRemoved, MAIN_DISPATCHER)
    def _flow_removed(self, ev):
        msg = ev.msg
        ck = msg.cookie
        if not (COOKIE_BASE <= ck < COOKIE_BASE + len(SERVERS)):
            return
        idx = ck - COOKIE_BASE
        lifetime = msg.duration_sec + msg.duration_nsec / 1e9
        active_ms = (lifetime - CONN_IDLE) * 1000.0   # strip the idle-timeout tail
        if active_ms < 1.0:
            active_ms = 1.0
        if self.est[idx] is None:
            self.est[idx] = active_ms
        else:
            self.est[idx] = RT_ALPHA * active_ms + (1 - RT_ALPHA) * self.est[idx]

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
        est = self.est[idx]
        self.logger.info("flow %s:%d -> VIP assigned to server %s (rt, est=%s ms)",
                         ip_pkt.src, tcp_pkt.src_port, server["ip"],
                         ("%.1f" % est) if est is not None else "n/a")
        client_port = in_port
        sport, dport = tcp_pkt.src_port, tcp_pkt.dst_port
        cookie = COOKIE_BASE + idx

        fwd_match = psr.OFPMatch(eth_type=ether_types.ETH_TYPE_IP, ip_proto=6,
                                 ipv4_src=ip_pkt.src, ipv4_dst=VIRTUAL_IP,
                                 tcp_src=sport, tcp_dst=dport)
        fwd_actions = [psr.OFPActionSetField(eth_dst=server["mac"]),
                       psr.OFPActionSetField(ipv4_dst=server["ip"]),
                       psr.OFPActionOutput(server["port"])]
        self.add_flow(dp, 10, fwd_match, fwd_actions, idle=CONN_IDLE,
                      cookie=cookie, flags=ofp.OFPFF_SEND_FLOW_REM)

        rev_match = psr.OFPMatch(eth_type=ether_types.ETH_TYPE_IP, ip_proto=6,
                                 ipv4_src=server["ip"], ipv4_dst=ip_pkt.src,
                                 tcp_src=dport, tcp_dst=sport)
        rev_actions = [psr.OFPActionSetField(eth_src=VIRTUAL_MAC),
                       psr.OFPActionSetField(ipv4_src=VIRTUAL_IP),
                       psr.OFPActionOutput(client_port)]
        self.add_flow(dp, 10, rev_match, rev_actions, idle=CONN_IDLE)
        return server, fwd_actions
