#!/usr/bin/env python3
"""
Reactive least-load SDN load balancer (Ryu, OpenFlow 1.3) with port-stats polling.

Baseline #3 AND the shared polling machinery for EWMA.

New vs the round-robin/weighted controllers: a background thread polls the switch
for per-port byte counters every POLL_INTERVAL seconds, converts them to a per-server
BYTE RATE (delta / interval), and select_server() picks the server with the lowest
current rate. "Reactive" = it responds to observed load, with NO smoothing/prediction
(that smoothing is what EWMA will add next).

This implements the "SDN-native flow-stats load signal" from docs/02-architecture.md.

Run:  ryu-manager src/lb_leastload.py
"""

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ether_types, arp, ipv4
from ryu.lib import hub

VIRTUAL_IP = "10.0.0.100"
VIRTUAL_MAC = "00:00:00:00:00:fe"
POLL_INTERVAL = 2  # seconds between port-stats polls

SERVERS = [
    {"ip": "10.0.0.1", "mac": "00:00:00:00:00:01", "port": 1},
    {"ip": "10.0.0.2", "mac": "00:00:00:00:00:02", "port": 2},
    {"ip": "10.0.0.3", "mac": "00:00:00:00:00:03", "port": 3},
]
# quick lookup: switch port -> index into SERVERS
PORT_TO_IDX = {s["port"]: i for i, s in enumerate(SERVERS)}


class LeastLoadLB(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(LeastLoadLB, self).__init__(*args, **kwargs)
        self.mac_to_port = {}
        self.datapaths = {}
        # per-server load bookkeeping
        self.prev_bytes = [0] * len(SERVERS)   # last cumulative byte count
        self.rate = [0.0] * len(SERVERS)       # current byte rate (bytes/sec)
        self.have_baseline = False             # skip the first delta (no prev)
        # start the background polling thread
        self.monitor_thread = hub.spawn(self._monitor)

    # ---- background port-stats polling ----
    def _monitor(self):
        while True:
            for dp in list(self.datapaths.values()):
                self._request_port_stats(dp)
            hub.sleep(POLL_INTERVAL)

    def _request_port_stats(self, dp):
        ofp, psr = dp.ofproto, dp.ofproto_parser
        req = psr.OFPPortStatsRequest(dp, 0, ofp.OFPP_ANY)
        dp.send_msg(req)

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def _port_stats_reply(self, ev):
        # sum tx+rx bytes per server port, convert cumulative -> rate
        new_bytes = [0] * len(SERVERS)
        for stat in ev.msg.body:
            idx = PORT_TO_IDX.get(stat.port_no)
            if idx is not None:
                new_bytes[idx] = stat.tx_bytes + stat.rx_bytes

        if self.have_baseline:
            for i in range(len(SERVERS)):
                delta = new_bytes[i] - self.prev_bytes[i]
                if delta < 0:
                    delta = 0  # counter reset guard
                self.rate[i] = delta / float(POLL_INTERVAL)
            self.logger.info("load(bytes/s): %s",
                             ", ".join("%s=%.0f" % (SERVERS[i]["ip"], self.rate[i])
                                       for i in range(len(SERVERS))))
        self.prev_bytes = new_bytes
        self.have_baseline = True

    def select_server(self):
        """Reactive least-load: pick the server with the lowest current byte rate.
        Before the first poll completes, all rates are 0 -> falls back to first server.
        """
        best = 0
        for i in range(1, len(SERVERS)):
            if self.rate[i] < self.rate[best]:
                best = i
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
        self.logger.info("flow %s -> VIP assigned to server %s (least-load, rate=%.0f B/s)",
                         ip_pkt.src, server["ip"], self.rate[PORT_TO_IDX[server["port"]]])
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
