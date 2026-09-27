# Checkpoint — Air-Writing Language Game

Living state-of-the-project doc for Claude sessions working on this repo. `CLAUDE.md` has
the original spec; this file tracks what's actually been decided and built since, so a
fresh session doesn't have to re-derive it from conversation history.

## Accounts, Menu Tabs & Practice Configuration

- **No-password player accounts.** `players` dict lives in `GameState` (source of truth,
  same relationship as cards/attempts to `db.py`), seeded with a reserved admin id `444`
  (placeholder, no special privileges). `POST /signup {name}` assigns a sequential id
  (starting 1000) and logs in; `POST /login {id}` switches; `GET /players` lists everyone
  (login-screen namecard grid). Since there's one physical wand, this is about
  *attribution*, not concurrency — `GameState.switch_player()` changes whose attempts get
  recorded.
  - **Single active player session rule**: `cards_by_language`/`clock_by_language`/`attempts`
    are not keyed by player in memory — they hold whichever single player is active.
    Every login/signup reloads them (`main.py`'s `_load_player_cards`) so progress does
    not leak between players. Tiger Data persistence (`db.create_player`/`list_players`)
    is best-effort.
- **Menu navigation**: Four horizontal tabs: Versus (placeholder — static namecards/HP
  bars), Practice, Shop (placeholder), and Settings.
- **Practice tab**:
  - Full deck character grid (`GameState.practice_letters`, `None` = full deck).
  - Selection mode toggle: `"srs"` (SM-2 scheduler) vs. `"accuracy"` (`srs.pick_by_accuracy`,
    weighting weaker letters higher). `POST /practice/config {letters, selection_mode}`.
  - Prompt mode toggle: Learn (shows stroke reference hint) vs. Blind (audio prompt only,
    masks letter to `?` until submit).
  - **No inner scrolling**: Removed `.letters-grid` max-height scrollbar so all characters
    are visible simultaneously on the card.
  - **Collapsible sections**: Sections (*Groupings*, *Characters to practice*, *Selection
    mode*, *Show letter*) use native `<details open class="collapsible-group">` with
    rotating chevrons (`▾`/`▸`) and slide animations, allowing users to collapse sections.
  - **Additive multi-group selection (Hiragana)**: Gojuon row buttons (`a`, `ka`, `sa`, etc.)
    toggle additively with `.selected` and `.partial` states. Added a "Clear all" button
    next to "Select all" for focused drill setups.
- **Titular branding & logo font**:
  - Implemented **Makcasa** (`web/frontend/makcasa/Makcasa-Regular.otf/.ttf`) as the
    primary titular font for `.game-title` ("Atelier!").
- **UI/UX fluid transitions**:
  - Pure CSS, GPU-accelerated transitions:
    - Screen transitions: smooth cross-fade with 6px upward float (`screen-fade-in`).
    - Tab panels: smooth entrance animation (`panel-fade-in`).
    - Buttons & chips: springy tactile physics (`translateY(-1px)` on hover, `scale(0.96)`
      on active click, accent shadow on selected).
    - Canvas result feedback: cyan pulse glow on pass (`result-pass`), tactile shake on fail
      (`result-fail`), and elastic grade badge entrance (`grade-pop`).
    - Overlays & modals: backdrop blur (`blur(3px)`) and scale-in pop.

## Languages, Recognition & Scoring Models

The game supports three playable languages/decks in `config.LANGUAGES`:

1. **Latin Alphabet (`latin`)**:
   - 26 letters (`A`-`Z`).
   - Multi-stroke letters use strict per-stroke order + direction validation (`strokes.py`).
     Single-stroke letters (M, S, C, J, U) and stroke-count mismatches fall through to the
     EMNIST CNN (`model/emnist_cnn.pt`, 26 classes, 92.6% test accuracy).
   - "S" reference curve uses a smooth sine-based two-lobe parameterization (`_s_curve_points`).
   - Hints: self-generated PNG arrow diagrams (`generate_reference_images.py`).
2. **Japanese Hiragana (`japanese`)**:
   - 46 gojuon characters (`あ` through `ん`).
   - Scored via whole-path 49-class CNN trained on Kuzushiji-49 (`model/hiragana_cnn.pt`,
     87.93% test accuracy).
   - Strict stroke validation was tested and intentionally reverted: schematic stroke rules
     often conflicted with natural calligraphic handwriting. Instead, hiragana uses the
     CNN path with a gamma boost curve (`scoring.HIRAGANA_SCORE_BOOST_GAMMA = 0.6`) to
     compensate for 49-class softmax dispersion.
   - Hints: animated stroke-order GIFs from Wikimedia Commons (`reference/<char>.gif`).
3. **Japanese Kanji (`kanji`)**:
   - 10 foundational, pictographic characters: `日` (sun), `月` (moon), `火` (fire),
     `水` (water), `木` (tree), `山` (mountain), `川` (river), `人` (person),
     `口` (mouth), `土` (earth).
   - Scored via a dedicated 10-class CNN (`model/kanji_cnn.pt`, 812 KB, **99.90% test
     accuracy**) trained via `model/train_kanji_model.py` using 30,000 augmented samples
     derived from 14 system CJK font weights + inverted Wikimedia reference glyphs.
   - Hints: animated stroke-order GIFs from Wikimedia Commons (`reference/<char>.gif`).
   - `activeLanguage === "latin" ? "png" : "gif"` dynamically routes hint formats.

## Path Reconstruction (Laser-Pointer Model)

- Players draw by *rotating* the wand, not moving the hand (centripetal acceleration
  remains within ~1 m/s² of gravity).
- `trajectory.reconstruct_pointer_path`: tracks orientation using Mahony-style complementary
  filtering (gyro integration corrected against accelerometer gravity vector). Runs across
  the entire letter, including pen-up intervals, preserving true relative stroke positions.
- Accel-only double-integration (`trajectory.reconstruct_path`) remains as fallback for
  packets without gyro data.
- Live wand-cursor: streamed at 50 Hz (`POST /stroke/live`), tracked by
  `LiveOrientationTracker`, and broadcast over `/ws` as `cursor` messages to render a live
  pointer dot and trail on the canvas.

## Hardware & Firmware Contract (Wired USB Serial)

The wand operates purely over a **wired USB-UART serial connection at 921600 baud**
(no Wi-Fi stack in firmware):

- **Pinout**:
  - Pen Button: **GPIO 4** (active-low, `INPUT_PULLUP`). Hold to draw.
  - Submit Button: **GPIO 18** (active-low, `INPUT_PULLUP`). Press to submit letter.
  - Status LED: **GPIO 19** (`PIN_LED`). Flashes on valid letter submit for `LED_FLASH_MS` (2200 ms).
  - IMU I2C: **SDA = GPIO 21**, **SCL = GPIO 22** (`0x68`, 400 kHz).
  - Chip support: auto-detects MPU-6050, MPU-6500, and MPU-9250 via `WHO_AM_I` with
    per-chip axis-sign correction.
- **Serial Protocol**:
  - `L:{...}`: emitted at 50 Hz throughout (idle and active). Relayed by
    `scripts/serial_bridge.py` to `POST /stroke/live` for the live cursor.
  - `S:{...}`: emitted on submit button press. Full buffered letter packet relayed by
    `scripts/serial_bridge.py` to `POST /stroke` for grading and broadcast.
- **Building & Flashing**:
  - Firmware builds with PlatformIO:
    ```bash
    ~/.platformio/penv/bin/pio run --project-dir esp32 -t upload
    ```
  - Serial bridge runs via:
    ```bash
    web/server/.venv/bin/python scripts/serial_bridge.py
    ```
  - `esp32/include/config.h` is gitignored; keeps local wand settings and pin definitions.

## External Services & Graceful Degradation

- **ElevenLabs TTS**: Reads target prompt in Blind mode. Audio clips are cached locally in
  `web/server/tts_cache/`. Requires `ELEVENLABS_API_KEY` and a custom voice ID in
  `ELEVENLABS_VOICE_ID` (free-tier accounts require user-cloned voices rather than library
  defaults). Unset key &rarr; Blind mode stays locked in UI.
- **Tiger Data (TimescaleDB)**: Optional persistence for `attempts` and SRS cards across
  restarts. Unset or unreachable `DATABASE_URL` &rarr; server runs purely in-memory via
  `GameState`.

## Open Questions & Future Milestones

- **Versus Mode**: Currently a static mock; requires HP bar logic, relative scoring deltas,
  and turn/speed timers when a second wand is available.
- **Second Wand Mounting**: Pointing axis coordinates (`POINTING_AXIS` in `trajectory.py`)
  are currently calibrated for wand #1; a second device requires wand-specific axis config.
- **Kanji Expansion**: Can expand beyond the initial 10 foundational characters to full
  elementary Grade 1 kanji (80 characters) by extending `train_kanji_model.py`.
