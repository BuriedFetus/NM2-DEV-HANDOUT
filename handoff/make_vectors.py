#!/usr/bin/env python3
"""Make the test vectors: replay a recorded NM2 log through the Python box (tools/box/nm2_box.py).

The Python box is the version the owner validated by hand. This replays a recording through it
with a simulated clock and writes every CC it sends. ratchet/test_ratchet.c replays the same log
through the C module and must produce exactly the same lines.

Replay rules (the C test follows the same ones):
- Time 0 = the first MIDI event in the log. Ticks happen every 10 ms (10, 20, 30, ...).
- Before an event at time t, every tick at time <= t runs first.
- A tick = update the ratchet, then send. After the last event, ticks run for 1 more second.

Run:  python3 handoff/make_vectors.py      (rewrites handoff/vectors/*.txt)
"""

import re
import sys
import types
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools" / "box"))
import nm2_box  # noqa: E402

LOG = ROOT / "logs" / "nm2-usb-2026-10-23-timed.txt"
OUT = Path(__file__).resolve().parent / "vectors"
LINE = re.compile(r"^(\d\d):(\d\d):(\d\d)\.(\d\d\d)\s+\S+\s+"
                  r"(?:(Note on|Note off)\s+(\d+), note (\d+), velocity (\d+)"
                  r"|Control change\s+(\d+), controller (\d+), value (\d+))")


def read_log(path):
    """[(ms of day, [status, data1, data2])] for notes and CCs in an aseqdump -t log."""
    events = []
    for line in path.read_text().splitlines():
        m = LINE.match(line)
        if not m:
            continue
        h, mi, s, ms = (int(x) for x in m.group(1, 2, 3, 4))
        t = ((h * 60 + mi) * 60 + s) * 1000 + ms
        if m.group(5):
            status = (0x90 if m.group(5) == "Note on" else 0x80) | int(m.group(6))
            events.append((t, [status, int(m.group(7)), int(m.group(8))]))
        else:
            events.append((t, [0xB0 | int(m.group(9)), int(m.group(10)), int(m.group(11))]))
    return events


def replay(events, axis):
    clock = [Fraction(0)]
    nm2_box.time = types.SimpleNamespace(monotonic=lambda: clock[0])  # simulated clock

    sent, ticking = [], [False]

    class Midi:
        def send(self, msg):
            if ticking[0]:  # ratchet output only; encoder pass-through is not part of the module
                sent.append((int(clock[0] * 1000), msg[1], msg[2]))

    s = nm2_box.Settings(axis=axis, settle=Fraction(40, 1000))  # exact 40 ms, like the C module
    s.buttons = [[102 + b, f"button {b + 1}"] for b in range(18)]
    box = nm2_box.Box(Midi(), s, lambda *a: None)

    t0 = events[0][0]
    next_tick = 10

    def tick_until(t):
        nonlocal next_tick
        while next_tick <= t:
            clock[0] = Fraction(next_tick, 1000)
            ticking[0] = True
            box.update()
            box.tick()
            ticking[0] = False
            next_tick += 10

    for t, msg in events:
        tick_until(t - t0)
        clock[0] = Fraction(t - t0, 1000)
        box.on_message(msg)
        box.update()
    tick_until(events[-1][0] - t0 + 1000)
    return sent


def main():
    events = read_log(LOG)
    OUT.mkdir(exist_ok=True)
    for axis in ("pitch", "roll"):
        sent = replay(events, axis)
        path = OUT / f"usb-2026-10-23-{axis}.txt"
        with path.open("w") as f:
            f.write(f"# Expected ratchet output for logs/{LOG.name}, axis = {axis}.\n"
                    "# Made by handoff/make_vectors.py from the Python box (tools/box/nm2_box.py).\n"
                    "# Settings: buttons 1-18 -> CC 102-119, channel 1, start 64, median of 3 + average of 7,\n"
                    "# settle 40 ms, slew 300/s, gain 1. Roll is inverted (127 - CC 74).\n"
                    "# Columns: time in ms since the first event, CC, value.\n")
            for t, cc, v in sent:
                f.write(f"{t} {cc} {v}\n")
        print(f"{path.relative_to(ROOT)}: {len(sent)} CCs")


if __name__ == "__main__":
    main()
