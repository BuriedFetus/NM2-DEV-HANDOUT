/*
 * NM2 hold + tilt ratchet: reference implementation (C99, no floats, no malloc, no platform code).
 *
 * While a button is held, tilting changes that button's CC relative to its value at press.
 * On release the value stays; the next press continues from it. Behavior spec: ../SPEC.md
 *
 * The firmware feeds it three things and sends what comes back:
 *   ratchet_button()  on every button press / release
 *   ratchet_tilt()    on every tilt reading (0-127 per axis, ideally at a fixed ~50 Hz)
 *   ratchet_tick()    every 10 ms; calls send() for each CC to transmit
 * Times are milliseconds from any free-running counter; wrap-around is handled.
 */
#ifndef RATCHET_H
#define RATCHET_H

#include <stdint.h>

#define RATCHET_BUTTONS 18
#define RATCHET_AXES 2
#define RATCHET_ROLL 0        /* left/right; the NM2 sends it as CC 74 today */
#define RATCHET_PITCH 1       /* back/forward; CC 75 today */
#define RATCHET_NO_CC 0xFF    /* this button does not use this axis */
#define RATCHET_MAX_SMOOTH 16
#define RATCHET_TICK_MS 10

typedef struct {
    uint8_t cc[RATCHET_BUTTONS][RATCHET_AXES]; /* CC sent per button and axis, or RATCHET_NO_CC */
    uint8_t invert[RATCHET_AXES]; /* 1: use 127 - tilt (roll: tilting right lowers CC 74, so right should add) */
    uint8_t channel;              /* 0-15 (0 = MIDI channel 1) */
    uint8_t start_value;          /* every CC's value at power-on, as far as the ratchet knows */
    uint8_t spike_filter;         /* 1: median of the last 3 readings */
    uint8_t smooth;               /* moving average length, 1..RATCHET_MAX_SMOOTH */
    uint16_t settle_ms;           /* wait after press before taking the reference (press jolt) */
    uint16_t slew;                /* max change in CC values per second, 0 = no limit */
    uint16_t gain_pct;            /* 100 = 1 CC value per tilt value */
} ratchet_config;

typedef struct {
    uint8_t hist[3], hist_n;               /* last 3 raw readings, for the median */
    uint8_t avg[RATCHET_MAX_SMOOTH], avg_n, avg_pos;
    uint16_t sum;                          /* filtered tilt = sum / avg_n */
} ratchet_filter;

typedef struct {
    ratchet_config cfg;
    ratchet_filter filt[RATCHET_AXES];
    uint8_t value[RATCHET_BUTTONS][RATCHET_AXES];   /* last value sent (what the synth should have) */
    uint8_t target[RATCHET_BUTTONS][RATCHET_AXES];  /* where value is heading, under the slew limit */
    uint8_t start[RATCHET_AXES];                    /* held button's value when the reference was taken */
    uint16_t ref_sum[RATCHET_AXES];                 /* reference tilt = ref_sum / ref_n */
    uint8_t ref_n[RATCHET_AXES];
    int8_t selected;                                /* held button, -1 = none */
    uint8_t have_ref;
    uint32_t press_ms, last_tick_ms;
} ratchet;

/* send() is called once per CC to transmit (3-byte message B0|channel, cc, value). */
typedef void (*ratchet_send_fn)(void *ctx, uint8_t channel, uint8_t cc, uint8_t value);

/* Defaults validated on the NM2: pitch axis only, buttons 1-18 -> CC 102-119 (undefined in MIDI 1.0),
 * channel 1, start 64,
 * median of 3 + average of 7, settle 40 ms, slew 300/s, gain 1. */
void ratchet_default_config(ratchet_config *cfg);
void ratchet_init(ratchet *r, const ratchet_config *cfg, uint32_t now_ms);
void ratchet_button(ratchet *r, uint8_t button, uint8_t pressed, uint32_t now_ms);
void ratchet_tilt(ratchet *r, uint8_t axis, uint8_t value, uint32_t now_ms);
void ratchet_tick(ratchet *r, uint32_t now_ms, ratchet_send_fn send, void *ctx);
/* Forget all values: back to start_value. Sends nothing. */
void ratchet_reset_values(ratchet *r);

#endif
