#pragma once

#include <Arduino.h>

// Connects to the configured Wi-Fi network, printing progress. Returns true
// once connected, false on timeout.
bool network_init();

// Reconnects if the link has dropped. Returns true if connected.
bool network_ensure_connected();

// GETs /round/current and writes the server's target letter into `letter`.
// Returns false (leaving `letter` untouched) if the server can't be reached.
bool fetch_target_letter(String &letter);

// POSTs `json_payload` to /stroke as application/json and logs the
// response code. Returns true on a 2xx response.
bool send_stroke_to_server(const String &json_payload);
