/* NM2 hold + tilt ratchet: reference implementation. See ratchet.h and ../SPEC.md. */
#include "ratchet.h"

#include <string.h>

void ratchet_default_config(ratchet_config *cfg)
{
    memset(cfg, 0, sizeof *cfg);
    for (int b = 0; b < RATCHET_BUTTONS; b++) {
        cfg->cc[b][RATCHET_ROLL] = RATCHET_NO_CC;
        cfg->cc[b][RATCHET_PITCH] = (uint8_t)(102 + b);
    }
    cfg->invert[RATCHET_ROLL] = 1;
    cfg->channel = 0;
    cfg->start_value = 64;
    cfg->spike_filter = 1;
    cfg->smooth = 7;
    cfg->settle_ms = 40;
    cfg->slew = 300;
    cfg->gain_pct = 100;
}

void ratchet_init(ratchet *r, const ratchet_config *cfg, uint32_t now_ms)
{
    memset(r, 0, sizeof *r);
    r->cfg = *cfg;
    if (r->cfg.smooth < 1) r->cfg.smooth = 1;
    if (r->cfg.smooth > RATCHET_MAX_SMOOTH) r->cfg.smooth = RATCHET_MAX_SMOOTH;
    r->selected = -1;
    r->last_tick_ms = now_ms;
    ratchet_reset_values(r);
}

void ratchet_reset_values(ratchet *r)
{
    memset(r->value, r->cfg.start_value, sizeof r->value);
    memset(r->target, r->cfg.start_value, sizeof r->target);
    r->have_ref = 0;  /* if a button is held, re-reference from the new value: no jump */
}

void ratchet_button(ratchet *r, uint8_t button, uint8_t pressed, uint32_t now_ms)
{
    if (button >= RATCHET_BUTTONS) return;
    if (pressed) {
        /* A new press takes over even if another button is still held. */
        r->selected = (int8_t)button;
        r->press_ms = now_ms;
        r->have_ref = 0;
    } else if (r->selected == (int8_t)button) {
        r->selected = -1;
        r->have_ref = 0;
    }
    /* Nothing is ever sent on press or release. */
}

/* Integer division rounded to nearest, ties to even (same as the Python tools, so results match exactly). */
static int32_t div_round(int32_t num, int32_t den)
{
    int32_t q = num / den, rem = num % den;
    if (rem < 0) { q -= 1; rem += den; }  /* floor */
    if (2 * rem > den || (2 * rem == den && (q & 1))) q += 1;
    return q;
}

static uint8_t clamp127(int32_t v)
{
    return (uint8_t)(v < 0 ? 0 : v > 127 ? 127 : v);
}

/* Filtered tilt of one axis as a fraction sum / n (n = 0: no reading yet). */
static uint8_t tilt_of(const ratchet *r, int axis, uint16_t *sum)
{
    const ratchet_filter *f = &r->filt[axis];
    *sum = r->cfg.invert[axis] ? (uint16_t)(127u * f->avg_n - f->sum) : f->sum;
    return f->avg_n;
}

static void update(ratchet *r, uint32_t now_ms)
{
    int b = r->selected;
    if (b < 0 || (uint32_t)(now_ms - r->press_ms) < r->cfg.settle_ms) return;

    uint16_t sum[RATCHET_AXES];
    uint8_t n[RATCHET_AXES];
    for (int a = 0; a < RATCHET_AXES; a++) {
        n[a] = tilt_of(r, a, &sum[a]);
        if (r->cfg.cc[b][a] != RATCHET_NO_CC && n[a] == 0) return;
    }

    if (!r->have_ref) {
        /* First update after the press settles: remember where the hand is. No output yet. */
        for (int a = 0; a < RATCHET_AXES; a++) {
            r->ref_sum[a] = sum[a];
            r->ref_n[a] = n[a];
            r->start[a] = r->value[b][a];
        }
        r->have_ref = 1;
        return;
    }

    for (int a = 0; a < RATCHET_AXES; a++) {
        if (r->cfg.cc[b][a] == RATCHET_NO_CC) continue;
        /* target = start + (sum/n - ref_sum/ref_n) * gain_pct/100, in exact integer arithmetic */
        int32_t den = (int32_t)n[a] * r->ref_n[a] * 100;
        int32_t num = (int32_t)r->start[a] * den
                    + ((int32_t)sum[a] * r->ref_n[a] - (int32_t)r->ref_sum[a] * n[a]) * r->cfg.gain_pct;
        r->target[b][a] = clamp127(div_round(num, den));
    }
}

void ratchet_tilt(ratchet *r, uint8_t axis, uint8_t value, uint32_t now_ms)
{
    if (axis >= RATCHET_AXES) return;
    ratchet_filter *f = &r->filt[axis];
    if (value > 127) value = 127;

    /* Spike filter: median of the last 3 readings (one-reading spikes come from taps and button presses). */
    if (f->hist_n < 3) f->hist_n++;
    f->hist[0] = f->hist[1];
    f->hist[1] = f->hist[2];
    f->hist[2] = value;
    uint8_t m = value;
    if (r->cfg.spike_filter && f->hist_n == 3) {
        uint8_t x = f->hist[0], y = f->hist[1], z = f->hist[2];
        m = (x > y) ? ((y > z) ? y : (x > z) ? z : x) : ((x > z) ? x : (y > z) ? z : y);
    }

    /* Moving average of the last cfg.smooth medians (hand jiggle). */
    if (f->avg_n == r->cfg.smooth) {
        f->sum -= f->avg[f->avg_pos];
    } else {
        f->avg_n++;
    }
    f->avg[f->avg_pos] = m;
    f->sum += m;
    f->avg_pos = (uint8_t)((f->avg_pos + 1) % r->cfg.smooth);

    update(r, now_ms);
}

void ratchet_tick(ratchet *r, uint32_t now_ms, ratchet_send_fn send, void *ctx)
{
    update(r, now_ms);

    /* Slew limit: at most cfg.slew values per second, at least 1 per tick (exact: step = slew * dt / 1000). */
    uint32_t dt = now_ms - r->last_tick_ms;
    r->last_tick_ms = now_ms;
    if (dt > 1000) dt = 1000;  /* a late tick never needs more than 1 s of slew; keeps the math in range */
    int32_t step_x1000 = r->cfg.slew ? (int32_t)(r->cfg.slew * dt) : 127000;
    if (step_x1000 < 1000) step_x1000 = 1000;

    for (int b = 0; b < RATCHET_BUTTONS; b++) {
        for (int a = 0; a < RATCHET_AXES; a++) {
            uint8_t cc = r->cfg.cc[b][a];
            int32_t v = r->value[b][a], t = r->target[b][a];
            if (cc == RATCHET_NO_CC || v == t) continue;
            int32_t diff_x1000 = (t - v) * 1000;
            if (diff_x1000 > step_x1000) v = div_round(v * 1000 + step_x1000, 1000);
            else if (diff_x1000 < -step_x1000) v = div_round(v * 1000 - step_x1000, 1000);
            else v = t;
            r->value[b][a] = (uint8_t)v;
            send(ctx, r->cfg.channel, cc, (uint8_t)v);
        }
    }
}
