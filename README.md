# Atelier ⭑.ᐟ

> **Draw characters in the air. Master languages through spatial memory and spaced repetition.**

Atelier is an air-writing language-learning system powered by an **ESP32 motion-sensing wand**, real-time **IMU orientation tracking**, **stroke-order validation**, and **custom Convolutional Neural Networks (CNNs)**.

Instead of typing on a keyboard or tapping multiple-choice options, learners physically trace characters in three-dimensional space. The wand captures high-frequency 6-DOF inertial dynamics, reconstructs the 2D projected trajectory in real-time, grades both stroke order and structural accuracy, and schedules reviews using an Anki-style Spaced Repetition System (SRS).

---

## Table of Contents

- [Supported Scripts & Languages](#supported-scripts--languages)
- [System Architecture](#system-architecture)
- [How It Works](#how-it-works)
  - [1. Hardware & Firmware](#1-hardware--firmware)
  - [2. The Serial Bridge](#2-the-serial-bridge)
  - [3. Trajectory Reconstruction (Laser-Pointer Model)](#3-trajectory-reconstruction-laser-pointer-model)
  - [4. Scoring & Recognition Pipeline](#4-scoring--recognition-pipeline)
  - [5. Spaced Repetition & Learning Modes](#5-spaced-repetition--learning-modes)
- [Hardware Wiring & Setup](#hardware-wiring--setup)
- [How to Run](#how-to-run)
  - [Prerequisites](#prerequisites)
  - [1. Flash the ESP32 Firmware](#1-flash-the-esp32-firmware)
  - [2. Set Up the Server](#2-set-up-the-server)
  - [3. Start the Serial Bridge](#3-start-the-serial-bridge)
  - [4. Open the Web Application](#4-open-the-web-application)
  - [5. Testing Without Hardware (Simulation)](#5-testing-without-hardware-simulation)
- [Project Structure](#project-structure)
- [API & WebSocket Protocol](#api--websocket-protocol)

---

## Supported Scripts & Languages

| Script / Deck | Characters | Recognition & Scoring Method | Reference Hints |
| :--- | :--- | :--- | :--- |
| **Latin Alphabet** | 26 letters (`A`–`Z`) | Strict stroke-order & direction validation + EMNIST CNN fallback (92.6% accuracy) | Canonical vector stroke paths with direction indicators |
| **Japanese (Hiragana)** | 46 gojūon characters (`あ`–`ん`) | 49-class Kuzushiji CNN with gamma boost curve | Wikimedia Commons stroke-order animations (`.gif`) |
| **Japanese (Kanji)** | 10 foundational pictograms (`日`, `月`, `火`, `水`, `木`, `山`, `川`, `人`, `口`, `土`) | 10-class custom CNN trained on augmented CJK fonts (99.9% accuracy) | Wikimedia Commons stroke-order animations (`.gif`) |

---

## System Architecture

```
                    ┌────────────────────────────┐
                    │  ESP32 Motion-Sensing Wand │
                    │   - MPU-6050/6500/9250 IMU │
                    │   - Pen & Submit Buttons   │
                    │   - Feedback LED           │
                    └─────────────┬──────────────┘
                                  │ High-speed USB Serial (921,600 baud)
                                  │ "L:" Live 50Hz samples | "S:" Completed letter
                                  ▼
                    ┌────────────────────────────┐
                    │  scripts/serial_bridge.py  │
                    │   Auto-detects USB port &  │
                    │   relays to local REST API │
                    └───────┬────────────┬───────┘
          POST /stroke/live │            │ POST /stroke
                            ▼            ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   FastAPI Backend (web/server)                         │
│                                                                        │
│  ┌───────────────────────┐              ┌───────────────────────────┐  │
│  │ Trajectory Engine     │              │ Scoring Engine            │  │
│  │ - Mahony Filter       │              │ - Stroke-Order Validator  │  │
│  │ - Pointer Projection  │─────────────▶│ - 28x28 Rasterizer        │  │
│  │ - Drift Correction    │              │ - PyTorch CNN Classifiers │  │
│  └───────────────────────┘              └─────────────┬─────────────┘  │
│                                                       │                │
│  ┌───────────────────────┐              ┌─────────────▼─────────────┐  │
│  │ Spaced Repetition     │              │ Analytics & Persistence   │  │
│  │ - SM-2 Review Clock   │◀─────────────│ - Tiger Data/TimescaleDB  │  │
│  │ - Accuracy-Weighting  │              │   (in-memory fallback)    │  │
│  └───────────────────────┘              └───────────────────────────┘  │
│                                                       │                │
│  ┌───────────────────────┐              ┌─────────────▼─────────────┐  │
│  │ ElevenLabs TTS        │              │ WebSocket Broadcaster     │  │
│  │ (Blind audio-recall)  │              │ (/ws live cursor & score) │  │
│  └───────────────────────┘              └─────────────┬─────────────┘  │
└───────────────────────────────────────────────────────┼────────────────┘
                                                        │ JSON Events
                                                        ▼
┌────────────────────────────────────────────────────────────────────────┐
│                     Web Frontend (web/frontend)                        │
│  - Real-time wand cursor & smooth in-progress stroke trails            │
│  - Reconstructed letter preview & post-submission feedback             │
│  - Animated stroke order guides & practice deck selector               │
│  - Performance analytics (accuracy curves, SRS cards, round history)   │
└────────────────────────────────────────────────────────────────────────┘
```

---

## How It Works

### 1. Hardware & Firmware

The wand is built around an **ESP32 dev board** and a **6-DOF I2C Inertial Measurement Unit (IMU)**:
- **Automatic IMU Detection:** On boot, the firmware reads `REG_WHO_AM_I` (0x75) to differentiate between **MPU-6050** (`0x68`), **MPU-6500** (`0x70`), and **MPU-9250** (`0x71` or `0x73`), automatically applying the correct axis sign mapping so that $+Y$ consistently points out the wand tip.
- **50 Hz Sampling Loop:** The IMU is sampled every 20 ms (`SAMPLE_INTERVAL_MS = 20`).
- **Two-Button Control Flow:**
  - **Pen Button (GPIO 4):** Active-low, held down while drawing a stroke. When released, drawing pauses (allowing pen lifts between strokes).
  - **Submit Button (GPIO 18):** Active-low, pressed once the entire letter or character is finished.
- **Serial Protocol:** To eliminate venue Wi-Fi isolation and connection latency, all communication runs over a USB-UART connection at **921,600 baud**:
  - `L:{...}`: Streamed 50 times per second during both idle and active states for real-time cursor tracking.
  - `S:{...}`: Printed on letter submission. Contains all buffered samples from the first pen-down through the final pen-up, tagged with individual `pen` flags (0 or 1).
- **Physical Feedback:** GPIO 19 drives an onboard LED that illuminates for 2.2 seconds upon a successful submission.

### 2. The Serial Bridge

[`scripts/serial_bridge.py`](file:///home/doa/projects/atelier/scripts/serial_bridge.py) bridges the USB hardware and the server:
- Scans host serial ports for known ESP32 USB-UART bridge chips (CP210x, CH340, CH9102).
- Parses lines beginning with `L:` and forwards them to `POST /stroke/live` with minimal overhead.
- Parses lines beginning with `S:` and forwards the complete letter payload to `POST /stroke`.

### 3. Trajectory Reconstruction (Laser-Pointer Model)

Physical testing showed that users write in the air primarily by **rotating their wrist and forearm**, rather than translating their entire arm through space (total linear acceleration remains within $\sim 1\text{ m/s}^2$ of gravity). 

Conventional double-integration of raw accelerometer data fails because gravity shifts between axes as the wand tilts. Atelier solves this using a **laser-pointer model** ([`web/server/trajectory.py`](file:///home/doa/projects/atelier/web/server/trajectory.py)):
1. **Orientation Filter:** Integrates high-frequency gyroscope angular rates ($\omega_x, \omega_y, \omega_z$) and corrects orientation against the accelerometer's static gravity vector using a **Mahony-style complementary filter**.
2. **Pointing Projection:** Projects the tip of the wand's pointing axis onto a virtual 2D projection plane (azimuth and elevation angles).
3. **Continuous Tracking Across Pen-Lifts:** Gyro orientation is tracked continuously through pen-up gaps, preserving the correct relative spatial offsets between multi-stroke letters (e.g. crossing the `T`, or writing the three strokes of `A`).
4. **Fallback:** If gyroscope data is omitted, an accelerometer double-integration model with endpoint zero-velocity drift correction is used.

### 4. Scoring & Recognition Pipeline

Submissions are evaluated through a hybrid scoring pipeline ([`web/server/scoring.py`](file:///home/doa/projects/atelier/web/server/scoring.py) and [`web/server/strokes.py`](file:///home/doa/projects/atelier/web/server/strokes.py)):

#### A. Strict Stroke-Order Validation (Latin Multi-Stroke Letters)
For letters with defined canonical multi-stroke paths where the user lifts the pen between strokes:
- Each stroke's net displacement vector is evaluated against an 8-way compass direction.
- Circular strokes (such as `O` or the bowl of `G`) are validated using signed geometric polygon area to enforce clockwise vs. counter-clockwise rotation.
- Stroke ordering is inherently enforced, as drawing out of sequence causes slot-by-slot direction checks to fail.

#### B. CNN Vision Grader (Single-Stroke Letters, Fallbacks, Hiragana & Kanji)
If a letter is single-stroke, has mismatched stroke counts, or is Japanese kana/kanji:
1. **Rasterization:** [`web/server/rasterize.py`](file:///home/doa/projects/atelier/web/server/rasterize.py) normalizes the 2D trajectory with an aspect-ratio-preserving bounding box, centers it with padding, and draws antialiased lines onto a $28 \times 28$ grayscale pixel grid.
2. **CNN Inference:**
   - **Latin:** PyTorch CNN trained on the EMNIST Letters dataset (26 classes, 92.6% test accuracy).
   - **Hiragana:** 49-class CNN trained on Kuzushiji-49 with gamma scaling (`score = (prob ** 0.6) * 100`).
   - **Kanji:** 10-class CNN (`model/kanji_cnn.pt`) trained on augmented multi-weight CJK typography and template contours (99.9% test accuracy).
3. **Accuracy Score:** Derived from the target class softmax confidence score ($0$–$100$).

### 5. Spaced Repetition & Learning Modes

- **SM-2 Algorithm Adapted for Sessions:** [`web/server/srs.py`](file:///home/doa/projects/atelier/web/server/srs.py) implements the SuperMemo SM-2 algorithm. Instead of using calendar days (which are ineffective for hackathons or live demos), the review clock advances with each review attempt (`clock_by_language`). Cards track ease factors, intervals, and lapses.
- **Selection Modes:**
  - `srs`: Prioritizes due reviews, then introduces new characters.
  - `accuracy`: Prioritizes characters with lower average historical accuracy.
- **Prompt Modes:**
  - **Learn Mode:** Shows the character prompt and an animated stroke-order reference hint.
  - **Blind Mode:** Masks the character prompt to `?` and speaks the pronunciation aloud via **ElevenLabs TTS** ([`web/server/tts.py`](file:///home/doa/projects/atelier/web/server/tts.py)). Audio clips are cached locally in `tts_cache/`.
- **Persistence:** High-resolution time-series attempts and SRS cards are persisted asynchronously to **TimescaleDB / Tiger Data** via [`web/server/db.py`](file:///home/doa/projects/atelier/web/server/db.py), with automatic fallback to in-memory storage if no database is configured.

---

## Hardware Wiring & Setup

### Bill of Materials
- 1× ESP32 Development Board (NodeMCU / ESP32-WROOM-32)
- 1× 6-DOF IMU module (MPU-6050, MPU-6500, or MPU-9250)
- 2× Momentary pushbuttons (Tactile switches)
- 1× LED (optional external LED, or use onboard)
- Breadboard or perfboard wand enclosure & connecting wires

### Wiring Diagram

| Component Pin | ESP32 GPIO | Description / Mode |
| :--- | :--- | :--- |
| **IMU VCC** | `3.3V` | Power supply |
| **IMU GND** | `GND` | Common ground |
| **IMU SDA** | `GPIO 21` | I2C Data |
| **IMU SCL** | `GPIO 22` | I2C Clock (400 kHz) |
| **Pen Button** | `GPIO 4` | Active LOW (`INPUT_PULLUP`). Connect between GPIO 4 and GND. |
| **Submit Button** | `GPIO 18` | Active LOW (`INPUT_PULLUP`). Connect between GPIO 18 and GND. |
| **Feedback LED** | `GPIO 19` | Connect anode via current-limiting resistor to GPIO 19, cathode to GND. |

---

## How to Run

### Prerequisites

- **Python 3.10+**
- **PlatformIO CLI** or VS Code PlatformIO extension (for flashing ESP32)
- USB-to-MicroUSB or USB-C cable for ESP32

---

### 1. Flash the ESP32 Firmware

1. Navigate to the `esp32` directory:
   ```bash
   cd esp32
   ```

2. Configure your wand settings (optional, defaults are pre-configured):
   ```bash
   cp include/config.example.h include/config.h
   ```

3. Build and upload to your connected ESP32 board:
   ```bash
   pio run -t upload
   ```

4. Verify output using the serial monitor (optional):
   ```bash
   pio device monitor -b 921600
   ```
   *You should see `[MAIN] Handwriting wand booting` followed by `[MAIN] Ready`.*

---

### 2. Set Up the Server

1. Navigate to the server directory:
   ```bash
   cd web/server
   ```

2. Create a virtual environment and install dependencies:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

3. Configure environment variables (optional):
   ```bash
   cp .env.example .env
   ```
   *Edit `.env` if you want to enable:*
   - `DATABASE_URL`: TimescaleDB / Tiger Data connection string. *(If left unset, the server runs fully in-memory).*
   - `ELEVENLABS_API_KEY`: API key for audio speech synthesis in Blind mode.
   - `ELEVENLABS_VOICE_ID`: Custom or cloned ElevenLabs voice ID.

4. Start the server:
   ```bash
   uvicorn main:app --host 0.0.0.0 --port 8000
   ```

---

### 3. Start the Serial Bridge

In a separate terminal, with your virtual environment activated:

```bash
python scripts/serial_bridge.py
```

*The script will automatically detect your ESP32's COM port and begin forwarding 50 Hz live cursor samples and submissions.*

> **Manual Port Selection:** If auto-detection finds multiple devices, specify your port:
> ```bash
> python scripts/serial_bridge.py --port /dev/ttyUSB0
> ```

---

### 4. Open the Web Application

Open your browser and navigate to:
```
http://localhost:8000
```

1. **Log in or Sign up:** Enter a name or select an existing player card.
2. **Select Practice Settings:**
   - Choose your target language: **Latin Alphabet**, **Japanese (Hiragana)**, or **Japanese (Kanji)**.
   - Select your mode (**Learn** with visual animation guides, or **Blind** with audio prompts).
   - Filter specific character groups or practice the entire deck.
3. **Pick up the wand and draw:**
   - Hold down the **Pen Button** (`GPIO 4`) while moving the wand.
   - Release the button between strokes.
   - Press the **Submit Button** (`GPIO 18`) to grade the character!

---

### 5. Testing Without Hardware (Simulation)

You can test the entire backend, scoring models, and frontend without physical hardware using [`scripts/simulate_stroke.py`](file:///home/doa/projects/atelier/scripts/simulate_stroke.py):

```bash
# Simulate drawing the letter 'T' (multi-stroke, with pen lifts)
python scripts/simulate_stroke.py T

# Simulate drawing 'G' in a single continuous stroke
python scripts/simulate_stroke.py G --single-shot

# Test the accelerometer-only fallback (no gyroscope)
python scripts/simulate_stroke.py S --no-gyro
```

---

## Project Structure

```
atelier/
├── README.md                      # This guide
├── checkpoint.md                  # Development history & technical decisions
├── scripts/
│   ├── serial_bridge.py           # USB-UART serial relay to local HTTP API
│   └── simulate_stroke.py         # Synthetic IMU motion generator for testing
├── esp32/
│   ├── platformio.ini             # PlatformIO build configuration
│   ├── include/
│   │   ├── config.example.h       # Pinouts, baud rates, and buffer limits
│   │   └── imu_driver.h           # IMU abstraction header
│   └── src/
│       ├── main.cpp               # Button debouncing, sampling, & serial formatting
│       └── imu_driver.cpp         # MPU-6050/6500/9250 I2C driver & axis calibration
└── web/
    ├── frontend/
    │   ├── index.html             # Single-page web app interface
    │   ├── app.js                 # WebSocket client, canvas drawing & UI state
    │   ├── style.css              # Custom styling & responsive layouts
    │   ├── makcasa/               # Logo typography
    │   └── reference/             # Stroke diagrams (.png) & animated hints (.gif)
    └── server/
        ├── main.py                # FastAPI web server, REST & WebSocket endpoints
        ├── models.py              # Pydantic data schemas
        ├── config.py              # Deck configurations, language definitions & ports
        ├── trajectory.py          # Mahony filter, laser pointer projection & drift removal
        ├── scoring.py             # Accuracy calculation & model dispatch
        ├── strokes.py             # Canonical Latin stroke definitions & geometry checks
        ├── rasterize.py           # Path-to-28x28 grayscale image rendering
        ├── srs.py                 # SM-2 Spaced Repetition engine
        ├── game_state.py          # Session management & review queues
        ├── db.py                  # TimescaleDB / Tiger Data persistence
        ├── tts.py                 # ElevenLabs speech generation & disk cache
        ├── requirements.txt       # Python dependencies
        └── model/
            ├── cnn.py             # PyTorch CNN architecture
            ├── train_model.py     # Training script for EMNIST Latin CNN
            ├── emnist_cnn.pt      # Pre-trained Latin CNN weights (92.6% acc)
            ├── hiragana_cnn.pt    # Pre-trained Hiragana CNN weights
            ├── kanji_cnn.pt       # Pre-trained Kanji CNN weights (99.9% acc)
            └── train_kanji_model.py # Kanji dataset augmentation & training script
```

---

## API & WebSocket Protocol

### Key REST Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/stroke/live` | Ingests a single 50 Hz motion sample for live canvas cursor tracking |
| `POST` | `/stroke` | Submits a completed character for reconstruction, grading, and SRS update |
| `GET` | `/round/current` | Returns the current active target character and round ID |
| `POST` | `/round/next` | Advances to the next character in the review queue |
| `GET` | `/languages` | Lists available languages and playable status |
| `POST` | `/language/{code}` | Changes the active language deck (`latin`, `japanese`, `kanji`) |
| `GET` | `/modes` | Returns available modes (`learn`, `blind`) |
| `POST` | `/mode/{code}` | Sets mode (`learn` or `blind`) |
| `GET` | `/players` | Lists all local player profiles |
| `POST` | `/signup` | Registers a new player account |
| `POST` | `/login` | Switches active player |
| `POST` | `/practice/config`| Restricts deck letters and chooses selection mode (`srs` vs `accuracy`) |
| `GET` | `/stats` | Returns accuracy timeline and per-character review statistics |
| `GET` | `/tts/{lang}/{char}` | Fetches or generates MP3 audio pronunciation |

### WebSocket Protocol (`/ws`)

Clients connect to `/ws` for bi-directional live events:
- **`round_start`**: Broadcast when a new character round begins.
- **`cursor`**: Real-time $(x, y)$ pointer coordinates with pen state for on-screen cursor tracking.
- **`stroke_result`**: Broadcast upon grading with accuracy percentage, reconstructed 2D paths, and updated cumulative score.
