#pragma once

// ---------------------------------------------------------------------------
// Wi-Fi / server
// ---------------------------------------------------------------------------
#define WIFI_SSID      "YOUR_HOTSPOT_SSID"
#define WIFI_PASSWORD  "YOUR_HOTSPOT_PASSWORD"

// Full URL of the stroke endpoint on the teammate's server.
#define SERVER_URL     "http://192.168.1.100:8000/stroke"

#define PLAYER_ID      "player_1"

// Which letter to attempt each stroke. TODO: replace with a GET to
// /round/current once the round-fetching flow is wired up; hardcoded for now
// so end-to-end scoring can be tested.
#define TARGET_LETTER  "A"

// How long to wait for Wi-Fi on boot / reconnect before giving up (ms).
#define WIFI_CONNECT_TIMEOUT_MS  15000
// HTTP request timeout (ms).
#define HTTP_TIMEOUT_MS          5000

// ---------------------------------------------------------------------------
// Hardware pins
// ---------------------------------------------------------------------------
#define PIN_STROKE_TRIGGER  4    // active-low, INPUT_PULLUP
#define PIN_I2C_SDA         21
#define PIN_I2C_SCL         22

#define MPU9250_I2C_ADDR    0x68
#define I2C_CLOCK_HZ        400000

// ---------------------------------------------------------------------------
// Sampling
// ---------------------------------------------------------------------------
#define SAMPLE_INTERVAL_MS  20    // 50 Hz
#define DEBOUNCE_MS         15
// Hard cap on samples per stroke (10 s at 50 Hz) to bound RAM usage.
#define MAX_STROKE_SAMPLES  500
// Strokes shorter than this are treated as accidental taps and discarded.
#define MIN_STROKE_SAMPLES  3
