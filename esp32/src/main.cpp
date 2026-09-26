#include <Arduino.h>
#include <ArduinoJson.h>

#include <vector>

#include "config.h"
#include "imu_driver.h"
#include "network_manager.h"

namespace {

// Active-low button on an INPUT_PULLUP pin with a simple time-based debounce.
struct Button {
    uint8_t pin;
    bool pressed = false;       // debounced state
    bool last_raw = false;
    uint32_t last_change_ms = 0;

    explicit Button(uint8_t p) : pin(p) {}

    // Updates and returns the debounced state.
    bool update() {
        bool raw = digitalRead(pin) == LOW;
        uint32_t now = millis();
        if (raw != last_raw) {
            last_raw = raw;
            last_change_ms = now;
        }
        if (now - last_change_ms >= DEBOUNCE_MS) pressed = raw;
        return pressed;
    }
};

struct LetterSample {
    ImuSample imu;
    bool pen;                   // true while the pen button was held
};

Button pen_button(PIN_PEN);
Button submit_button(PIN_SUBMIT);

// A letter runs from its first pen-down until submit. Samples are taken the
// whole time, pen-up gaps included, so the server can see how the wand moved
// between strokes.
std::vector<LetterSample> letter_buffer;
bool letter_active = false;
bool buffer_full_logged = false;
int stroke_count = 0;
uint32_t letter_start_ms = 0;
uint32_t next_sample_ms = 0;

void reset_letter() {
    letter_buffer.clear();
    letter_active = false;
    buffer_full_logged = false;
    stroke_count = 0;
}

void start_letter() {
    reset_letter();
    letter_active = true;
    letter_start_ms = millis();
    next_sample_ms = letter_start_ms;
    Serial.println("[MAIN] Letter started");
}

void sample_if_due(bool pen) {
    uint32_t now = millis();
    if ((int32_t)(now - next_sample_ms) < 0) return;

    // Advance on a fixed grid to avoid drift; resync if we fell far behind.
    next_sample_ms += SAMPLE_INTERVAL_MS;
    if ((int32_t)(now - next_sample_ms) >= 0) next_sample_ms = now + SAMPLE_INTERVAL_MS;

    if (letter_buffer.size() >= MAX_LETTER_SAMPLES) {
        if (!buffer_full_logged) {
            Serial.println("[MAIN] Letter buffer full - press submit (GPIO 18)");
            buffer_full_logged = true;
        }
        return;
    }

    LetterSample s;
    if (!imu_read(s.imu)) {
        Serial.println("[MAIN] IMU read failed, sample skipped");
        return;
    }
    s.imu.t = now - letter_start_ms;
    s.pen = pen;
    letter_buffer.push_back(s);
}

void submit_letter() {
    if (!letter_active) {
        Serial.println("[MAIN] Nothing to submit - hold GPIO 4 to draw first");
        return;
    }

    // Drop the pen-up tail (moving the hand to press submit isn't part of the letter).
    while (!letter_buffer.empty() && !letter_buffer.back().pen) letter_buffer.pop_back();

    size_t pen_samples = 0;
    for (const LetterSample &s : letter_buffer) pen_samples += s.pen;

    if (pen_samples < MIN_PEN_SAMPLES) {
        Serial.println("[MAIN] Letter too short, discarded");
        reset_letter();
        return;
    }

    String letter = FALLBACK_LETTER;
    if (!fetch_target_letter(letter)) {
        Serial.printf("[MAIN] Couldn't fetch target letter, using fallback \"%s\"\n", letter.c_str());
    }

    Serial.printf("[MAIN] Submitting \"%s\": %d strokes, %u samples (%u pen-down) over %lu ms\n",
                  letter.c_str(), stroke_count, letter_buffer.size(), pen_samples,
                  letter_buffer.back().imu.t);

    JsonDocument doc;
    doc["player_id"] = PLAYER_ID;
    doc["letter"] = letter;
    doc["sample_rate_hz"] = 1000 / SAMPLE_INTERVAL_MS;
    JsonArray samples = doc["samples"].to<JsonArray>();
    for (const LetterSample &s : letter_buffer) {
        JsonObject o = samples.add<JsonObject>();
        o["t"] = s.imu.t;
        o["ax"] = s.imu.ax;
        o["ay"] = s.imu.ay;
        o["az"] = s.imu.az;
        o["gx"] = s.imu.gx;
        o["gy"] = s.imu.gy;
        o["gz"] = s.imu.gz;
        o["pen"] = s.pen ? 1 : 0;
    }
    reset_letter();

    if (doc.overflowed()) {
        Serial.printf("[MAIN] Out of memory building JSON (free heap %u), letter dropped\n",
                      ESP.getFreeHeap());
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

    pinMode(PIN_PEN, INPUT_PULLUP);
    pinMode(PIN_SUBMIT, INPUT_PULLUP);
    letter_buffer.reserve(MAX_LETTER_SAMPLES);

    while (!imu_init()) {
        Serial.println("[MAIN] Retrying IMU init in 1 s");
        delay(1000);
    }

    // Keep going even without Wi-Fi; send_stroke_to_server() retries later.
    network_init();

    Serial.println("[MAIN] Ready - hold GPIO 4 LOW to draw, press GPIO 18 LOW to submit");
}

void loop() {
    bool pen_was = pen_button.pressed;
    bool pen_now = pen_button.update();
    bool submit_was = submit_button.pressed;
    bool submit_now = submit_button.update();

    if (pen_now && !pen_was) {
        if (!letter_active) start_letter();
        stroke_count++;
        Serial.printf("[MAIN] Stroke %d started\n", stroke_count);
    } else if (!pen_now && pen_was && letter_active) {
        Serial.printf("[MAIN] Stroke %d ended\n", stroke_count);
    }

    if (letter_active) sample_if_due(pen_now);

    if (submit_now && !submit_was) submit_letter();
}
