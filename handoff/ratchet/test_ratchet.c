/*
 * Tests for the ratchet module. Run: make test   (or: cc -std=c99 -Wall -o test_ratchet test_ratchet.c ratchet.c)
 *
 * 1. Scenario tests: the rules in ../SPEC.md, one by one.
 * 2. Replay: the real NM2 recording (logs/nm2-usb-2026-10-23-timed.txt) through this module,
 *    compared line by line with what the validated Python box sent (the files in ../vectors).
 *    Replay rules are in ../make_vectors.py.
 */
#include "ratchet.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int failures;

#define CHECK(name, cond) do { \
        printf("%s  %s\n", (cond) ? "ok  " : "FAIL", name); \
        if (!(cond)) failures++; \
    } while (0)

/* --- Collecting what the module sends --- */

typedef struct { uint32_t t; uint8_t ch, cc, v; } sent_cc;
typedef struct { sent_cc *msgs; int n, cap; uint32_t now; } outbox;

static void collect(void *ctx, uint8_t ch, uint8_t cc, uint8_t v)
{
    outbox *o = ctx;
    if (o->n == o->cap) {
        o->cap = o->cap ? 2 * o->cap : 256;
        o->msgs = realloc(o->msgs, (size_t)o->cap * sizeof *o->msgs);
        if (!o->msgs) { perror("realloc"); exit(2); }
    }
    o->msgs[o->n++] = (sent_cc){ o->now, ch, cc, v };
}

/* --- Scenario helpers: time moves in 10 ms ticks, like the firmware's timer --- */

typedef struct { ratchet r; outbox out; uint32_t now; } rig;

static void rig_start(rig *g, const ratchet_config *cfg)
{
    memset(g, 0, sizeof *g);
    ratchet_init(&g->r, cfg, 0);
}

/* Advance time by ms, ticking every 10 ms. */
static void wait_ms(rig *g, uint32_t ms)
{
    for (uint32_t done = 0; done < ms; done += RATCHET_TICK_MS) {
        g->now += RATCHET_TICK_MS;
        g->out.now = g->now;
        ratchet_tick(&g->r, g->now, collect, &g->out);
    }
}

/* Tilt readings every 20 ms (the NM2's ~50 Hz), from `from` to `to` in steps of 1, then hold `to`. */
static void tilt(rig *g, uint8_t axis, int from, int to)
{
    int step = to > from ? 1 : -1;
    for (int v = from;; v += step) {
        ratchet_tilt(&g->r, axis, (uint8_t)v, g->now);
        wait_ms(g, 20);
        if (v == to) break;
    }
    for (int i = 0; i < 10; i++) {
        ratchet_tilt(&g->r, axis, (uint8_t)to, g->now);
        wait_ms(g, 20);
    }
    wait_ms(g, 300);  /* let the slew limit finish */
}

static void press(rig *g, int button) { ratchet_button(&g->r, (uint8_t)button, 1, g->now); }
static void release(rig *g, int button) { ratchet_button(&g->r, (uint8_t)button, 0, g->now); }

/* All messages for `cc` move one way in steps of at most max_step and end at `end`. */
static int gradual(const outbox *o, int from_msg, uint8_t cc, int start, int end, int max_step)
{
    int prev = start, seen = 0;
    for (int i = from_msg; i < o->n; i++) {
        if (o->msgs[i].cc != cc) continue;
        int d = o->msgs[i].v - prev;
        if (d == 0 || abs(d) > max_step || (end > start) != (d > 0)) return 0;
        prev = o->msgs[i].v;
        seen++;
    }
    return seen > 0 && prev == end;
}

static void scenarios(void)
{
    ratchet_config cfg;
    ratchet_default_config(&cfg);
    rig g;

    /* Button 9 (index 8) -> CC 110 with the default config. */
    rig_start(&g, &cfg);
    tilt(&g, RATCHET_PITCH, 40, 40);
    press(&g, 8);
    wait_ms(&g, 100);
    CHECK("press sends nothing", g.out.n == 0);

    tilt(&g, RATCHET_PITCH, 40, 60);
    CHECK("hold + tilt +20: 64 -> 84, at most 3 per 10 ms", gradual(&g.out, 0, 110, 64, 84, 3));
    CHECK("output on channel 1 (B0)", g.out.n > 0 && g.out.msgs[0].ch == 0);

    int n = g.out.n;
    release(&g, 8);
    wait_ms(&g, 100);
    CHECK("release sends nothing", g.out.n == n);

    tilt(&g, RATCHET_PITCH, 60, 20);
    CHECK("tilt with no button held sends nothing", g.out.n == n);

    /* Next press while the hand is already tilted (20): continues from 84, no jump to the angle. */
    press(&g, 8);
    wait_ms(&g, 100);
    CHECK("press while tilted: no jump", g.out.n == n);
    tilt(&g, RATCHET_PITCH, 20, 10);
    CHECK("next press continues from 84: -10 -> 74", gradual(&g.out, n, 110, 84, 74, 3));
    release(&g, 8);

    /* Each button keeps its own value. */
    n = g.out.n;
    press(&g, 0);
    wait_ms(&g, 100);
    tilt(&g, RATCHET_PITCH, 10, 15);
    CHECK("button 1 starts at its own 64: +5 -> 69", gradual(&g.out, n, 102, 64, 69, 3));
    CHECK("button 9's CC untouched by button 1", g.r.value[8][RATCHET_PITCH] == 74);
    release(&g, 0);

    /* Press jolt: a spike right after the press must not become the reference. */
    rig_start(&g, &cfg);
    tilt(&g, RATCHET_PITCH, 60, 60);
    press(&g, 3);
    ratchet_tilt(&g.r, RATCHET_PITCH, 100, g.now);   /* jolt */
    wait_ms(&g, 20);
    for (int i = 0; i < 20; i++) {
        ratchet_tilt(&g.r, RATCHET_PITCH, 60, g.now);
        wait_ms(&g, 20);
    }
    CHECK("press jolt (one spike) sends nothing", g.out.n == 0);

    /* Clamp at 127, and coming back down works at once. */
    rig_start(&g, &cfg);
    tilt(&g, RATCHET_PITCH, 0, 0);
    press(&g, 0);
    wait_ms(&g, 100);
    tilt(&g, RATCHET_PITCH, 0, 120);
    CHECK("clamped at 127", g.r.value[0][RATCHET_PITCH] == 127);

    /* A second button pressed while the first is held takes over; the first one's release is ignored. */
    rig_start(&g, &cfg);
    tilt(&g, RATCHET_PITCH, 60, 60);
    press(&g, 0);
    wait_ms(&g, 100);
    press(&g, 1);
    release(&g, 0);
    wait_ms(&g, 100);
    tilt(&g, RATCHET_PITCH, 60, 70);
    CHECK("second press takes over", gradual(&g.out, 0, 103, 64, 74, 3) && g.r.value[0][RATCHET_PITCH] == 64);

    /* Roll is inverted: tilting right lowers the raw value and raises the CC. Pitch ignores roll. */
    ratchet_config roll = cfg;
    for (int b = 0; b < RATCHET_BUTTONS; b++) {
        roll.cc[b][RATCHET_ROLL] = (uint8_t)(102 + b);
        roll.cc[b][RATCHET_PITCH] = RATCHET_NO_CC;
    }
    rig_start(&g, &roll);
    tilt(&g, RATCHET_PITCH, 60, 60);
    tilt(&g, RATCHET_ROLL, 60, 60);
    press(&g, 0);
    wait_ms(&g, 100);
    tilt(&g, RATCHET_PITCH, 60, 90);
    CHECK("roll config ignores pitch", g.out.n == 0);
    tilt(&g, RATCHET_ROLL, 60, 40);
    CHECK("roll: raw -20 -> CC +20 (64 -> 84)", gradual(&g.out, 0, 102, 64, 84, 3));

    /* Both axes on one button: two CCs at once. */
    ratchet_config both = cfg;
    both.cc[0][RATCHET_ROLL] = 20;
    rig_start(&g, &both);
    tilt(&g, RATCHET_PITCH, 60, 60);
    tilt(&g, RATCHET_ROLL, 60, 60);
    press(&g, 0);
    wait_ms(&g, 100);
    tilt(&g, RATCHET_PITCH, 60, 70);
    tilt(&g, RATCHET_ROLL, 60, 55);
    CHECK("both axes: pitch +10 -> 74, roll right 5 -> 69",
          g.r.value[0][RATCHET_PITCH] == 74 && g.r.value[0][RATCHET_ROLL] == 69);

    /* Gain 2 and no slew limit. */
    ratchet_config fast = cfg;
    fast.gain_pct = 200;
    fast.slew = 0;
    rig_start(&g, &fast);
    tilt(&g, RATCHET_PITCH, 60, 60);
    press(&g, 0);
    wait_ms(&g, 100);
    tilt(&g, RATCHET_PITCH, 60, 70);
    CHECK("gain 2: +10 -> 84", g.r.value[0][RATCHET_PITCH] == 84);

    /* Reset: values back to start, nothing sent. */
    n = g.out.n;
    ratchet_reset_values(&g.r);
    wait_ms(&g, 100);
    CHECK("reset: back to 64, nothing sent", g.r.value[0][RATCHET_PITCH] == 64 && g.out.n == n);

    /* Millisecond counter wrapping around (uint32 overflow after ~49 days). */
    rig_start(&g, &cfg);
    g.now = 0xFFFFFF00u;
    ratchet_init(&g.r, &cfg, g.now);
    tilt(&g, RATCHET_PITCH, 60, 60);
    press(&g, 0);
    wait_ms(&g, 100);
    tilt(&g, RATCHET_PITCH, 60, 70);
    CHECK("works across the ms counter wrap", gradual(&g.out, 0, 102, 64, 74, 3));

    free(g.out.msgs);
}

/* --- Replay of the real recording --- */

/* Button notes as measured with the web app set to A minor, root A4 (docs/nm2-midi-map.md).
 * Only needed here because the recording is MIDI; firmware reads the buttons directly. */
static const uint8_t NOTES[RATCHET_BUTTONS] = { 69, 71, 72, 74, 76, 77, 79, 81, 83, 84, 86, 88, 89, 91, 93, 95, 96, 98 };

static int replay(const char *log_path, const char *vec_path, int axis)
{
    FILE *log = fopen(log_path, "r"), *vec = fopen(vec_path, "r");
    if (!log || !vec) {
        printf("FAIL  cannot open %s or %s\n", log_path, vec_path);
        return 0;
    }

    ratchet_config cfg;
    ratchet_default_config(&cfg);
    for (int b = 0; b < RATCHET_BUTTONS; b++) {
        cfg.cc[b][RATCHET_ROLL] = axis == RATCHET_ROLL ? (uint8_t)(102 + b) : RATCHET_NO_CC;
        cfg.cc[b][RATCHET_PITCH] = axis == RATCHET_PITCH ? (uint8_t)(102 + b) : RATCHET_NO_CC;
    }
    ratchet r;
    ratchet_init(&r, &cfg, 0);
    outbox out = { 0 };

    char line[256];
    long t0 = -1, t = 0;
    uint32_t next_tick = 10;
    while (fgets(line, sizeof line, log)) {
        int h, mi, s, ms, ch, a, b;
        char kind[16];
        if (sscanf(line, "%d:%d:%d.%d %*s %15[A-Za-z ]%d, %*s %d, %*s %d", &h, &mi, &s, &ms, kind, &ch, &a, &b) != 8)
            continue;
        t = ((h * 60L + mi) * 60 + s) * 1000 + ms;
        if (t0 < 0) t0 = t;
        uint32_t now = (uint32_t)(t - t0);
        for (; next_tick <= now; next_tick += 10) {
            out.now = next_tick;
            ratchet_tick(&r, next_tick, collect, &out);
        }
        if (!strncmp(kind, "Note o", 6)) {
            for (int k = 0; k < RATCHET_BUTTONS; k++)
                if (NOTES[k] == a) ratchet_button(&r, (uint8_t)k, !strncmp(kind, "Note on", 7) && b > 0, now);
        } else if (!strncmp(kind, "Control change", 14) && (a == 74 || a == 75)) {
            ratchet_tilt(&r, a == 74 ? RATCHET_ROLL : RATCHET_PITCH, (uint8_t)b, now);
        }
    }
    for (uint32_t end = (uint32_t)(t - t0) + 1000; next_tick <= end; next_tick += 10) {
        out.now = next_tick;
        ratchet_tick(&r, next_tick, collect, &out);
    }

    int i = 0, ok = 1, expected = 0;
    unsigned et, ecc, ev;
    while (fgets(line, sizeof line, vec)) {
        if (line[0] == '#' || sscanf(line, "%u %u %u", &et, &ecc, &ev) != 3) continue;
        expected++;
        if (ok && (i >= out.n || out.msgs[i].t != et || out.msgs[i].cc != ecc || out.msgs[i].v != ev)) {
            printf("      first difference at expected line %d: want %u %u %u, got ", expected, et, ecc, ev);
            if (i < out.n) printf("%u %u %u\n", (unsigned)out.msgs[i].t, out.msgs[i].cc, out.msgs[i].v);
            else printf("nothing\n");
            ok = 0;
        }
        i++;
    }
    if (ok && out.n != expected) {
        printf("      sent %d CCs, expected %d\n", out.n, expected);
        ok = 0;
    }
    printf("%s  replay %s (%d CCs)\n", ok ? "ok  " : "FAIL", vec_path, expected);
    if (!ok) failures++;
    fclose(log);
    fclose(vec);
    free(out.msgs);
    return ok;
}

int main(int argc, char **argv)
{
    const char *root = argc > 1 ? argv[1] : "../..";  /* repo root; default works from handoff/ratchet */
    char log_path[512], pitch[512], roll[512];
    snprintf(log_path, sizeof log_path, "%s/logs/nm2-usb-2026-10-23-timed.txt", root);
    snprintf(pitch, sizeof pitch, "%s/handoff/vectors/usb-2026-10-23-pitch.txt", root);
    snprintf(roll, sizeof roll, "%s/handoff/vectors/usb-2026-10-23-roll.txt", root);

    scenarios();
    replay(log_path, pitch, RATCHET_PITCH);
    replay(log_path, roll, RATCHET_ROLL);

    printf(failures ? "FAILED: %d\n" : "PASS\n", failures);
    return failures ? 1 : 0;
}
