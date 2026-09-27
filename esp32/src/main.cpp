#include <Arduino.h>
#include <esp_system.h>

#include <vector>

#include "config.h"
#include "imu_driver.h"

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

// Lit for LED_FLASH_MS after a successful submit. Placeholder for future
// per-feat feedback (accuracy, streaks, ...) once there's game logic to
// drive it - for now it's just "a letter went out." Timed in loop(), not
// delay(), so it doesn't stall sampling.
uint32_t led_off_at_ms = 0;

void flash_led() {
    digitalWrite(PIN_LED, HIGH);
    led_off_at_ms = millis() + LED_FLASH_MS;
}

void update_led() {
    if (led_off_at_ms && (int32_t)(millis() - led_off_at_ms) >= 0) {
        digitalWrite(PIN_LED, LOW);
        led_off_at_ms = 0;
    }
}

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

// One compact line per sample, over the same USB serial link used for
// debug logging - scripts/serial_bridge.py picks out lines starting with
// "L:" and relays them to the server's live-cursor endpoint. Printed for
// every sample, idle included, so the on-screen cursor always follows the
// wand. `t` is millis() (not letter-relative) so the server's orientation
// tracker sees one continuous clock across letters. Hand-built (no JSON
// library) to stay well under the 20 ms sample budget - at 921600 baud
// this line takes under 2 ms.
void print_live_sample(const ImuSample &imu, uint32_t now, bool pen, bool letter_start) {
    char buf[256];
    snprintf(buf, sizeof(buf),
             "L:{\"player_id\":\"%s\",\"t\":%lu,\"ax\":%.4f,\"ay\":%.4f,\"az\":%.4f,"
             "\"gx\":%.4f,\"gy\":%.4f,\"gz\":%.4f,\"pen\":%d,\"letter_start\":%s}",
             PLAYER_ID, (unsigned long)now, imu.ax, imu.ay, imu.az, imu.gx, imu.gy, imu.gz,
             pen ? 1 : 0, letter_start ? "true" : "false");
    Serial.println(buf);
}

void sample_if_due(bool pen) {
    uint32_t now = millis();
    if ((int32_t)(now - next_sample_ms) < 0) return;

    // Advance on a fixed grid to avoid drift; resync if we fell far behind.
    next_sample_ms += SAMPLE_INTERVAL_MS;
    if ((int32_t)(now - next_sample_ms) >= 0) next_sample_ms = now + SAMPLE_INTERVAL_MS;

    LetterSample s;
    if (!imu_read(s.imu)) {
        Serial.println("[MAIN] IMU read failed, sample skipped");
        return;
    }
    s.pen = letter_active && pen;
    print_live_sample(s.imu, now, s.pen, letter_active && letter_buffer.empty());

    if (!letter_active) return;
    if (letter_buffer.size() >= MAX_LETTER_SAMPLES) {
        if (!buffer_full_logged) {
            Serial.println("[MAIN] Letter buffer full - press submit (GPIO 18)");
            buffer_full_logged = true;
        }
        return;
    }
    s.imu.t = now - letter_start_ms;
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

    Serial.printf("[MAIN] Submitting: %d strokes, %u samples (%u pen-down) over %lu ms\n",
                  stroke_count, letter_buffer.size(), pen_samples, letter_buffer.back().imu.t);

    // One "S:" line (same prefix scheme as the live "L:" samples), printed
    // sample by sample. Building the whole letter in memory first (it can
    // be ~100 KB) ran the ESP32 out of heap and crashed it on submit.
    // `letter` is empty: the server already knows its own active round and
    // grades against that.
    Serial.printf("S:{\"player_id\":\"%s\",\"letter\":\"\",\"sample_rate_hz\":%d,\"samples\":[",
                  PLAYER_ID, 1000 / SAMPLE_INTERVAL_MS);
    char buf[160];
    for (size_t i = 0; i < letter_buffer.size(); i++) {
        const LetterSample &s = letter_buffer[i];
        snprintf(buf, sizeof(buf),
                 "%s{\"t\":%lu,\"ax\":%.4f,\"ay\":%.4f,\"az\":%.4f,"
                 "\"gx\":%.4f,\"gy\":%.4f,\"gz\":%.4f,\"pen\":%d}",
                 i ? "," : "", (unsigned long)s.imu.t, s.imu.ax, s.imu.ay, s.imu.az,
                 s.imu.gx, s.imu.gy, s.imu.gz, s.pen ? 1 : 0);
        Serial.print(buf);
    }
    Serial.println("]}");
    flash_led();
    reset_letter();
}

const char *reset_reason() {
    switch (esp_reset_reason()) {
        case ESP_RST_POWERON: return "power-on";
        case ESP_RST_EXT: return "reset pin";
        case ESP_RST_SW: return "software restart";
        case ESP_RST_PANIC: return "CRASHED";
        case ESP_RST_INT_WDT:
        case ESP_RST_TASK_WDT:
        case ESP_RST_WDT: return "FROZE (watchdog)";
        case ESP_RST_BROWNOUT: return "POWER DIPPED (brownout) - check for a short or loose power wire";
        default: return "other";
    }
}

}  // namespace

void setup() {
    Serial.begin(921600);
    delay(200);
    Serial.println();
    Serial.printf("[MAIN] Handwriting wand booting (last reset: %s)\n", reset_reason());

    pinMode(PIN_PEN, INPUT_PULLUP);
    pinMode(PIN_SUBMIT, INPUT_PULLUP);
    pinMode(PIN_LED, OUTPUT);
    digitalWrite(PIN_LED, LOW);
    letter_buffer.reserve(MAX_LETTER_SAMPLES);

    while (!imu_init()) {
        Serial.println("[MAIN] Retrying IMU init in 1 s");
        delay(1000);
    }

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

    sample_if_due(pen_now);

    if (submit_now && !submit_was) submit_letter();

    update_led();
}
