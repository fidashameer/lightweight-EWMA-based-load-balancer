# Week 1 — Environment Setup & Toolchain Smoke Test

**Date:** 2026-07-23
**Goal:** prove the toolchain works end-to-end before writing any balancing logic.

## Environment

| | |
|---|---|
| Host | MacBook Air M4 (Apple Silicon, ARM64) |
| Hypervisor | UTM (QEMU, "Virtualize" mode) |
| Guest OS | Ubuntu Server 22.04.5 LTS ARM64 |
| Kernel | 5.15.0-186-generic aarch64 |
| Python | 3.10.12 |
| VM spec | 4 GB RAM, 2 vCPU, 20 GB disk (no LVM) |
| Guest IP | 192.168.64.2 (SSH from host) |

**Why 22.04 and not 24.04/26.04:** newer releases ship Python 3.12+, which worsens
the Ryu/eventlet incompatibility documented below. 22.04 ships Python 3.10.

**Why no LVM:** Ubuntu's guided LVM layout allocates only ~half the disk to root.
Disabling it gave the full 19.07 GB on `/`.

## Installed

- Mininet 2.3.1b4 (from source, `util/install.sh -nfv`)
- Open vSwitch 2.17.9
- OpenFlow reference implementation (compiled from source)
- Ryu 4.34
- iperf3, tcpdump, git, python3-pip

Note: `apt` reports `openvswitch-controller` as unavailable on 22.04; the install
script falls back to `openvswitch-testcontroller`. This is expected, not an error.

## Smoke test result

`sudo bash scripts/smoke_test.sh` → **7 passed, 0 failed**

- mn, ovs-vsctl, ovs-ofctl, iperf3, tcpdump all present
- Open vSwitch service responding
- `mn --test pingall` → 0% dropped

Step 5 (controller ↔ switch) completed manually — see below.

## Implementation challenge: Ryu / eventlet dependency conflict

Ryu 4.34 could not start on Python 3.10. The cause is a genuine version conflict
with no valid pin:

| eventlet version | Failure |
|---|---|
| 0.30.2 | `TypeError: cannot set 'is_timeout' attribute of immutable type 'TimeoutError'` — old eventlet patches `socket.timeout`, which became an immutable alias of `TimeoutError` in Python 3.10 |
| 0.32.0 | same as above |
| 0.33.3 | `ImportError: cannot import name 'ALREADY_HANDLED' from 'eventlet.wsgi'` — removed in eventlet 0.33.0, but still imported by `ryu/app/wsgi.py` |
| 0.41.1 (latest) | same `ALREADY_HANDLED` ImportError |

**Every version below 0.33 fails on Python 3.10; every version from 0.33 onward
removed the symbol Ryu needs. No single version satisfies both constraints, so
pinning alone cannot resolve this.**

### Fix applied

```bash
pip3 install "eventlet==0.33.3"
sed -i "s/from eventlet.wsgi import ALREADY_HANDLED/ALREADY_HANDLED = None/" \
  ~/.local/lib/python3.10/site-packages/ryu/app/wsgi.py
```

`ALREADY_HANDLED` is used only as a sentinel value in Ryu's WSGI layer. Stubbing it
to `None` is safe for this project, which does not use Ryu's REST API.

### Reproducibility risk

Anyone rebuilding this environment will hit the same failure. The patch above is a
required setup step, not an optional workaround. It is recorded here and must be
included in the final report's methodology section.

## Verification (step 5)

Terminal 1:
```bash
ryu-manager ryu.app.simple_switch_13
```

Terminal 2:
```bash
sudo mn --controller=remote,ip=127.0.0.1,port=6653 \
        --switch ovsk,protocols=OpenFlow13 --test pingall
```

**Result:** `*** Results: 0% dropped (2/2 received)`, completed in 5.298 s.
The Ryu process logged `packet in` events with source/destination MACs, confirming
the controller is receiving PacketIn messages and installing flow rules.

## Decision

> **Controller chosen: Ryu 4.34** (with eventlet 0.33.3 + `wsgi.py` patch)
>
> **Reason:** works end-to-end after the patch; better documented and more widely
> used in SDN literature than POX, which matters for comparability with prior work.
> POX remains the fallback if Ryu causes further problems during development.

## Known issues / TODO

- `scripts/smoke_test.sh` prints a malformed OVS version string (`== -1 ==`);
  parsing bug in the script, cosmetic only.
- Pin the working dependency set in a `requirements.txt` so the environment is
  reproducible without repeating this debugging.

