# Week 1 — Environment Setup & Toolchain Smoke Test

**Goal of this week:** prove the toolchain works end-to-end *before* writing any
balancing logic. The single biggest execution risk in this project is the
environment, not the algorithm.

## Known risks going in

| Risk | Why it matters | Mitigation |
|---|---|---|
| Mininet VM is x86-only | The prepackaged VM will not boot on Apple Silicon (M4) | Use UTM + ARM64 Ubuntu, install Mininet from source inside it |
| Ryu depends on `eventlet` | Known import failures on Python 3.10+; Ryu is barely maintained | Pin Python 3.8 + compatible eventlet, **or** switch controller (POX / ONOS) |
| QEMU emulation overhead | Large topologies will be slow | Keep topology small (1 client pool + 3–4 servers) — sufficient for this study |
| Wireshark GUI over X11 | Fiddly on macOS | Capture with `tcpdump`/`tshark`, analyse `.pcap` afterwards |

## Smoke test — definition of done

The environment is considered working when **all five** pass:

- [ ] Ubuntu ARM64 VM boots in UTM
- [ ] `sudo mn --test pingall` succeeds
- [ ] Controller process starts without import errors
- [ ] Mininet connects to the controller (switch shows as connected)
- [ ] A flow rule installed by the controller visibly changes traffic path

Run `scripts/smoke_test.sh` inside the VM and paste the output below.

## Log

### Attempt 1 — <date>

- **VM:** Ubuntu <version> ARM64 on UTM
- **Python:** <version>
- **Controller tried:** <Ryu / POX / ONOS>
- **Result:**
- **Errors hit:**
- **Fix applied:**

### Decision

> **Controller chosen:** _TBD_
> **Reason:** _TBD_

_Record the decision here once the smoke test passes. This decision goes into the
paper's methodology section and the Review 1 slides._

## Notes

Anything that cost more than 30 minutes to solve should be written down here —
it becomes the "implementation challenges" content for the report and viva.
