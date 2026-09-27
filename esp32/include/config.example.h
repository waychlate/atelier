#pragma once

// Copy this file to config.h and fill in real values. config.h is
// gitignored so per-wand settings never get committed.

// Everything - live cursor samples and the final letter submission - goes
// over USB serial to scripts/serial_bridge.py, not Wi-Fi. See that script's
// docstring. Give each wand its own PLAYER_ID.
#define PLAYER_ID      "player_1"

// ---------------------------------------------------------------------------
// Hardware pins
// ---------------------------------------------------------------------------
#define PIN_PEN             4    // hold LOW to draw a stroke (INPUT_PULLUP)
#define PIN_SUBMIT          18   // press LOW to submit the letter (INPUT_PULLUP)
#define PIN_I2C_SDA         21
#define PIN_I2C_SCL         22

#define MPU9250_I2C_ADDR    0x68
#define I2C_CLOCK_HZ        400000

// ---------------------------------------------------------------------------
// Sampling
// ---------------------------------------------------------------------------
#define SAMPLE_INTERVAL_MS  20    // 50 Hz
#define DEBOUNCE_MS         15
// Hard cap on samples per letter, pen-up gaps included (30 s at 50 Hz), to
// bound RAM usage. Sampling stops when full; submit to send what was captured.
#define MAX_LETTER_SAMPLES  1500
// Letters with fewer pen-down samples than this are treated as accidental
// taps and not sent.
#define MIN_PEN_SAMPLES     3
