#include <Arduino.h>
#include <ArduinoJson.h>

#include <vector>

#include "config.h"
#include "imu_driver.h"
#include "network_manager.h"

namespace {

std::vector<ImuSample> stroke_buffer;

bool drawing = false;           // debounced trigger state
bool last_raw_low = false;
uint32_t last_raw_change_ms = 0;

uint32_t stroke_start_ms = 0;
uint32_t next_sample_ms = 0;

// Returns the debounced "trigger held" state (GPIO 4 LOW).
bool read_trigger_debounced() {
    bool raw_low = digitalRead(PIN_STROKE_TRIGGER) == LOW;
    uint32_t now = millis();
    if (raw_low != last_raw_low) {
        last_raw_low = raw_low;
        last_raw_change_ms = now;
    }
    if (now - last_raw_change_ms >= DEBOUNCE_MS) drawing = raw_low;
    return drawing;
}

void start_stroke() {
    stroke_buffer.clear();
    stroke_start_ms = millis();
    next_sample_ms = stroke_start_ms;
    Serial.println("[MAIN] Stroke started");
}

void sample_if_due() {
    uint32_t now = millis();
    if ((int32_t)(now - next_sample_ms) < 0) return;

    // Advance on a fixed grid to avoid drift; resync if we fell far behind.
    next_sample_ms += SAMPLE_INTERVAL_MS;
    if ((int32_t)(now - next_sample_ms) >= 0) next_sample_ms = now + SAMPLE_INTERVAL_MS;

    if (stroke_buffer.size() >= MAX_STROKE_SAMPLES) return;

    ImuSample s;
    if (!imu_read(s)) {
        Serial.println("[MAIN] IMU read failed, sample skipped");
        return;
    }
    s.t = now - stroke_start_ms;
    stroke_buffer.push_back(s);

    if (stroke_buffer.size() == MAX_STROKE_SAMPLES) {
        Serial.println("[MAIN] Stroke buffer full, further samples ignored");
    }
}

void finish_stroke() {
    Serial.printf("[MAIN] Stroke finished: %u samples over %lu ms\n",
                  stroke_buffer.size(), millis() - stroke_start_ms);

    if (stroke_buffer.size() < MIN_STROKE_SAMPLES) {
        Serial.println("[MAIN] Stroke too short, discarded");
        stroke_buffer.clear();
        return;
    }

    JsonDocument doc;
    doc["user_id"] = USER_ID;
    JsonArray samples = doc["samples"].to<JsonArray>();
    for (const ImuSample &s : stroke_buffer) {
        JsonObject o = samples.add<JsonObject>();
        o["t"] = s.t;
        o["ax"] = s.ax;
        o["ay"] = s.ay;
        o["az"] = s.az;
        o["gx"] = s.gx;
        o["gy"] = s.gy;
        o["gz"] = s.gz;
    }
    stroke_buffer.clear();

    if (doc.overflowed()) {
        Serial.println("[MAIN] Out of memory building JSON, stroke dropped");
        return;
    }

    String payload;
    serializeJson(doc, payload);
    doc.clear();  // free the document before the HTTP request allocates

    send_stroke_to_server(payload);
}

}  // namespace

void setup() {
    Serial.begin(115200);
    delay(200);
    Serial.println();
    Serial.println("[MAIN] Handwriting wand booting");

    pinMode(PIN_STROKE_TRIGGER, INPUT_PULLUP);
    stroke_buffer.reserve(MAX_STROKE_SAMPLES);

    while (!imu_init()) {
        Serial.println("[MAIN] Retrying IMU init in 1 s");
        delay(1000);
    }

    // Keep going even without Wi-Fi; send_stroke_to_server() retries later.
    network_init();

    Serial.println("[MAIN] Ready - hold GPIO 4 LOW to draw");
}

void loop() {
    bool was_drawing = drawing;
    bool is_drawing = read_trigger_debounced();

    if (is_drawing && !was_drawing) {
        start_stroke();
    } else if (!is_drawing && was_drawing) {
        finish_stroke();
    }

    if (is_drawing) sample_if_due();
}
