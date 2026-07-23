#!/usr/bin/env bash
# Week-1 toolchain smoke test.
# Run INSIDE the Ubuntu ARM64 VM. Verifies the environment before any
# balancing logic is written. Paste the output into docs/01-week1-setup-log.md
#
# Usage:  sudo bash scripts/smoke_test.sh

set -u
PASS=0; FAIL=0
ok()   { echo "  [PASS] $1"; PASS=$((PASS+1)); }
bad()  { echo "  [FAIL] $1"; FAIL=$((FAIL+1)); }
head() { echo; echo "== $1 =="; }

head "0. Host / platform"
echo "  arch:   $(uname -m)"
echo "  kernel: $(uname -r)"
echo "  distro: $(. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME")"
echo "  python: $(python3 --version 2>&1)"

head "1. Required binaries present"
for b in mn ovs-vsctl ovs-ofctl iperf3 tcpdump; do
  if command -v "$b" >/dev/null 2>&1; then ok "$b found"; else bad "$b MISSING"; fi
done

head "2. Open vSwitch service running"
if ovs-vsctl show >/dev/null 2>&1; then
  ok "ovs-vsctl responds"
  echo "  ovs version: $(ovs-vsctl --version | head -1)"
else
  bad "ovs-vsctl not responding (is openvswitch-switch started?)"
fi

head "3. Mininet basic connectivity (mn --test pingall)"
if timeout 120 mn --test pingall >/tmp/_mn.log 2>&1; then
  if grep -q "0% dropped" /tmp/_mn.log; then ok "pingall 0% dropped"
  else bad "pingall ran but had drops"; grep -i dropped /tmp/_mn.log | sed 's/^/      /'; fi
else
  bad "mn --test pingall failed"; tail -5 /tmp/_mn.log | sed 's/^/      /'
fi
mn -c >/dev/null 2>&1

head "4. Controller import check"
CTRL="none"
if command -v ryu-manager >/dev/null 2>&1; then
  if python3 -c "import ryu" >/dev/null 2>&1; then ok "ryu imports cleanly"; CTRL="ryu"
  else bad "ryu present but FAILS to import (likely the eventlet issue)"
       python3 -c "import ryu" 2>&1 | tail -3 | sed 's/^/      /'; fi
else
  echo "  [skip] ryu-manager not installed"
fi
if python3 -c "import pox" >/dev/null 2>&1; then ok "pox imports cleanly"; [ "$CTRL" = none ] && CTRL="pox"; fi

head "5. Controller <-> switch connection"
echo "  Manual step — run in two terminals:"
echo "    T1:  ryu-manager ryu.app.simple_switch_13     (or: ./pox.py forwarding.l2_learning)"
echo "    T2:  sudo mn --controller=remote,ip=127.0.0.1,port=6653 --switch ovsk,protocols=OpenFlow13 --test pingall"
echo "  Then confirm flows were installed:"
echo "    sudo ovs-ofctl -O OpenFlow13 dump-flows s1"
echo "  Expect: non-empty flow table with packet counters > 0"

head "SUMMARY"
echo "  passed: $PASS   failed: $FAIL   controller candidate: $CTRL"
echo
if [ "$FAIL" -gt 0 ]; then
  echo "  Environment NOT ready. Fix the failures above before writing balancer code."
  echo "  If ryu fails to import, do not fight it — switch to POX or ONOS and record"
  echo "  that decision in docs/01-week1-setup-log.md."
  exit 1
fi
echo "  Automated checks passed. Complete step 5 manually, then log the result."
