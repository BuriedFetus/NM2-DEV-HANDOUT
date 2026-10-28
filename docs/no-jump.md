# Why the value never jumps on press

> When you let go, the value stays where you left it. The next press picks up from that value,
> whatever angle the NM2 is at.

This page explains why that matters and how the code does it.

## The problem it solves

Out of the box, the NM2's tilt is **absolute**: the angle of the NM2 *is* the value.
Hold it at a 30° angle and the CC is about 90, whatever it was before.

Now picture the hold + tilt mode working the same way:

1. You hold button 9, tilt forward, and set the filter to 84. You let go.
2. Later, with the NM2 resting tilted backward, you press button 9 again to adjust it a little.
3. An absolute mapping would send the filter straight to about 20, the hand's angle, before you've even moved.

That sudden jump is loud and unmusical. Playing live, it's also an ear-safety problem.

## The behavior

The mode is **relative** instead: tilting changes the value by *how much you've tilted since the press*,
not by the angle itself. Like a ratchet wrench, you can release, level the NM2, press again and keep going
in the same direction.

Worked example (the same numbers as the C test, see below):

| Step | Hand angle | Value sent |
|---|---|---|
| Press button 9 | 40 | nothing (value is 64) |
| Tilt forward by 20 | 40 → 60 | 64 → 84 |
| Release | 60 | nothing (value stays 84) |
| Tilt back with no button held | 60 → 20 | nothing |
| Press button 9 again | 20 | **nothing: no jump** |
| Tilt back by 10 | 20 → 10 | 84 → 74 |

## How the code does it

Three steps, the same in the C module and in the Python box.

**1. Press and release send nothing.** A press only notes which button is held and forgets the old
reference angle. A release only ends the hold. The button's value is left alone, so it "stays where you left it".

**2. Take a reference after the press settles.** Pressing a button shakes the NM2 a little
(measured: single-reading spikes like 59 → 37 → 59). So the code waits 40 ms, then remembers two things:
- the *reference*: the hand's angle right now
- the *start*: the button's value right now

Nothing is sent on this step either.

**3. While held, follow the difference.**

```
new value = start + (angle now − reference) × gain      (kept within 0–127)
```

Only the *difference* between the angle now and the angle at press counts. The angle the NM2 happened
to be at when you pressed cancels out. That is why it never jumps.

On top of that, the value sent moves toward the new value at most 300 steps per second
(3 every 10 ms), so even a fast tilt ramps smoothly.

The same "take a fresh reference" trick is used in two other places, so they don't jump either:
switching the tilt axis while a button is held, and resetting all values to the start value.

## Where to find it

**C module (what goes into the NM2):** [`handoff/ratchet/ratchet.c`](../handoff/ratchet/ratchet.c)

| Step | Code |
|---|---|
| 1. Press / release, nothing sent | [`ratchet_button()`, lines 41–54](../handoff/ratchet/ratchet.c#L41-L54) |
| 2. Wait 40 ms, take reference + start | [`update()`, lines 81 and 90–99](../handoff/ratchet/ratchet.c#L78-L99) |
| 3. Follow the difference | [lines 101–108](../handoff/ratchet/ratchet.c#L101-L108) |

**Python box (the version the owner tested by hand):** [`tools/box/nm2_box.py`](../tools/box/nm2_box.py)

| Step | Code |
|---|---|
| 1. Press / release | [lines 112–117](../tools/box/nm2_box.py#L112-L117) |
| 2. and 3. Reference, then follow the difference | [`update()`, lines 122–133](../tools/box/nm2_box.py#L122-L133) |

**The test that proves it:** [`handoff/ratchet/test_ratchet.c`, lines 97–121](../handoff/ratchet/test_ratchet.c#L97-L121)
plays the worked example above and checks that the second press sends nothing.
Run it with `cd handoff/ratchet && make test`.

The exact rules (2, 3 and 4) are in [`handoff/SPEC.md`](../handoff/SPEC.md).

## A different jump that is still open

There is one case this does not cover: the very first time a button is used, the box doesn't know the
synth's real value, so it assumes 64. If the synth is at 0, the first tilt jumps from 0 to about 64.
That's a separate issue, with options, in [`first-tilt-jump.md`](first-tilt-jump.md).
