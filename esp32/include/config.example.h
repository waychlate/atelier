#pragma once

// Copy this file to config.h and fill in real values. config.h is
// gitignored so your Wi-Fi credentials and server IP never get committed.

// ---------------------------------------------------------------------------
// Wi-Fi / server
// ---------------------------------------------------------------------------
#define WIFI_SSID      "YOUR_HOTSPOT_SSID"
#define WIFI_PASSWORD  "YOUR_HOTSPOT_PASSWORD"

// Base URL of the server (no trailing slash). The wand POSTs to /stroke and
// GETs /round/current under it.
#define SERVER_BASE_URL "http://192.168.1.100:8000"

#define PLAYER_ID      "player_1"

// Fallback letter if /round/current can't be reached at submit time.
#define FALLBACK_LETTER  "A"

// How long to wait for Wi-Fi on boot / reconnect before giving up (ms).
#define WIFI_CONNECT_TIMEOUT_MS  15000
// HTTP request timeout (ms).
#define HTTP_TIMEOUT_MS          5000

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
// Hard cap on samples per letter, pen-up gaps included (10 s at 50 Hz), to
// bound RAM usage. Sampling stops when full; submit to send what was captured.
#define MAX_LETTER_SAMPLES  500
// Letters with fewer pen-down samples than this are treated as accidental
// taps and not sent.
#define MIN_PEN_SAMPLES     3
