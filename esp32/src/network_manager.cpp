#include "network_manager.h"

#include <HTTPClient.h>
#include <WiFi.h>

#include "config.h"

namespace {

bool wait_for_connection() {
    uint32_t start = millis();
    while (WiFi.status() != WL_CONNECTED) {
        if (millis() - start > WIFI_CONNECT_TIMEOUT_MS) {
            Serial.println();
            Serial.println("[NET] Wi-Fi connection timed out");
            return false;
        }
        delay(250);
        Serial.print('.');
    }
    Serial.println();
    Serial.printf("[NET] Connected, IP: %s, RSSI: %d dBm\n",
                  WiFi.localIP().toString().c_str(), WiFi.RSSI());
    return true;
}

}  // namespace

bool network_init() {
    WiFi.mode(WIFI_STA);
    WiFi.setSleep(false);  // lower latency for the POST after each stroke
    WiFi.setAutoReconnect(true);

    Serial.printf("[NET] Connecting to \"%s\"", WIFI_SSID);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    return wait_for_connection();
}

bool network_ensure_connected() {
    if (WiFi.status() == WL_CONNECTED) return true;

    Serial.print("[NET] Wi-Fi lost, reconnecting");
    WiFi.disconnect();
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    return wait_for_connection();
}

bool send_stroke_to_server(const String &json_payload) {
    if (!network_ensure_connected()) {
        Serial.println("[NET] Not connected, stroke dropped");
        return false;
    }

    HTTPClient http;
    http.setTimeout(HTTP_TIMEOUT_MS);
    if (!http.begin(SERVER_URL)) {
        Serial.println("[NET] HTTPClient.begin() failed - check SERVER_URL");
        return false;
    }
    http.addHeader("Content-Type", "application/json");

    Serial.printf("[NET] POST %s (%u bytes)\n", SERVER_URL, json_payload.length());
    int code = http.POST(json_payload);

    bool ok = false;
    if (code > 0) {
        Serial.printf("[NET] Server responded: %d\n", code);
        String body = http.getString();
        if (body.length()) Serial.printf("[NET] Response body: %s\n", body.c_str());
        ok = code >= 200 && code < 300;
    } else {
        Serial.printf("[NET] POST failed: %s\n", http.errorToString(code).c_str());
    }

    http.end();
    return ok;
}
