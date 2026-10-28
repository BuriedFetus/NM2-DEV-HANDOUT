#!/usr/bin/env python3
"""Test the ratchet without any MIDI hardware: a fake NM2 plays a scripted press + tilt.

Run:  python3 tools/box/test_box.py      (takes about 10 s; prints PASS or what failed)
"""

import queue
import sys
import threading
import time

from nm2_box import Box, Settings, run


class FakeMidi:
    """Stands in for nm2_midi.AlsaMidi / RtMidi: feed() plays NM2 messages, sent collects the output."""

    where = "fake port"

    def __init__(self):
        self.incoming = queue.Queue()
        self.sent = []

    def ports(self):
        return {"NM2 fake": "USB"}

    def connect(self, port):
        return True

    def disconnect(self, port):
        pass

    def wait(self, timeout):
        try:
            msgs = [self.incoming.get(timeout=timeout)]
        except queue.Empty:
            return []
        while not self.incoming.empty():
            msgs.append(self.incoming.get_nowait())
        return msgs

    def send(self, msg):
        self.sent.append(list(msg))

    def close(self):
        pass

    def feed(self, msg):
        self.incoming.put(msg)


def scenario(fake, tilt_cc=75, frm=40, to=60):
    """Rest at `frm`, hold button 9, tilt to `to`, release, turn encoder 1, tilt with nothing held."""
    for _ in range(10):
        fake.feed([0xB0, tilt_cc, frm]); time.sleep(0.01)
    fake.feed([0x90, 83, 100])              # button 9 down
    time.sleep(0.1)                         # longer than the settle time
    step = 1 if to > frm else -1
    for v in range(frm, to + step, step):
        fake.feed([0xB0, tilt_cc, v]); time.sleep(0.01)
    for _ in range(10):
        fake.feed([0xB0, tilt_cc, to]); time.sleep(0.01)
    time.sleep(0.3)
    fake.feed([0x80, 83, 0])                # button 9 up
    fake.feed([0xB0, 1, 99])                # encoder: must pass through
    fake.feed([0xB0, tilt_cc, 10])          # tilt with nothing held: nothing out
    time.sleep(0.3)


def play(settings, **kw):
    """Run the box with a fake NM2 through the scenario; return (box, sent messages, events)."""
    fake, events, stop = FakeMidi(), [], threading.Event()
    box = Box(fake, settings, lambda *e: events.append(e))
    t = threading.Thread(target=run, args=(fake, box, "Bluetooth", stop))
    t.start()
    time.sleep(0.1)                         # let the port watcher connect
    scenario(fake, **kw)
    stop.set()
    t.join()
    return box, fake.sent, events


failures = []


def check(name, ok, detail=""):
    print(("ok    " if ok else "FAIL  ") + name + (f"   ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def gradual(values, end, max_step=3):
    """Moves only up, never faster than the speed limit allows per tick, and ends at `end`.
    (On a quiet computer it is exactly one step at a time; busy test machines can merge ticks.)"""
    steps = [b - a for a, b in zip([64] + values, values)]
    return bool(values) and values[-1] == end and all(0 < s <= max_step for s in steps)


def main():
    # 1. Defaults: same output as the recorded run of 2026-10-23 (64 → 84 one step at a time)
    box, sent, events = play(Settings())
    cc20 = [m[2] for m in sent if m[:2] == [0xB0, 20]]
    check("defaults: CC 20 goes 64 → 84 gradually", gradual(cc20, 84) and len(cc20) + 1 == len(sent), sent)
    check("defaults: encoder passes through, after the tilt", sent and sent[-1] == [0xB0, 1, 99], sent)
    check("defaults: no note forwarded", not any(m[0] & 0xF0 in (0x80, 0x90) for m in sent))
    check("defaults: press and release reported", ("press", 8, 64) in events and ("release", 8, 84) in events)
    check("defaults: connection reported", ("connected", "USB", "NM2 fake") in events)

    # 2. Reset values: back to start, nothing sent
    before = len(sent)
    box.reset_values()
    check("reset: values back to 64, nothing sent", box.box[8] == 64 and len(sent) == before)

    # 3. Gain 2: +20 tilt → +40
    _, sent, _ = play(Settings(gain=2))
    cc20 = [m[2] for m in sent if m[1] == 20]
    check("gain 2: ends at 104", gradual(cc20, 104, max_step=6), cc20)

    # 4. Roll axis: tilting right lowers CC 74 and raises the value
    _, sent, _ = play(Settings(axis="roll"), tilt_cc=74, frm=60, to=40)
    cc20 = [m[2] for m in sent if m[1] == 20]
    check("roll: CC 74 down by 20 → value 84", gradual(cc20, 84), cc20)

    # 5. Pitch axis ignores roll
    _, sent, _ = play(Settings(axis="pitch"), tilt_cc=74, frm=60, to=40)
    check("pitch: roll movement sends nothing", [m for m in sent if m[1] == 20] == [], sent)

    # 6. No filtering at all still lands on the same value
    _, sent, _ = play(Settings(spike=False, smooth=1))
    cc20 = [m[2] for m in sent if m[1] == 20]
    check("no filter: ends at 84", gradual(cc20, 84), cc20)

    # 7. MIDI channel 2 and a different CC for button 9
    s = Settings(channel=1)
    s.buttons[8] = [74, "Hydrasynth cutoff"]
    _, sent, _ = play(s)
    check("channel 2 + CC 74: sent as B1 4A", sent and all(m[:2] == [0xB1, 74] for m in sent[:-1]), sent[:3])

    print("PASS" if not failures else f"FAILED: {len(failures)}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
