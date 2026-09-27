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
    next to "Select all" for focused drill setups. Groupings section is strictly hidden
    (both via `.hidden:not(.hint-image) { display: none !important; }` and HTML `hidden` attribute)
    and cleared when non-Japanese decks (Latin, Kanji) are active.
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
   - 10 foundational, pictographic characters: `日` (Sun / Day), `月` (Moon / Month), `火` (Fire),
     `水` (Water), `木` (Tree / Wood), `山` (Mountain), `川` (River), `人` (Person),
     `口` (Mouth), `土` (Earth / Soil).
   - Definitions are surfaced across the entire UI: play banner prompt (in Learn mode as
     `火 · Fire` and in Blind mode as `? · Fire`), practice selection character buttons with
     dedicated subtitle tags (`.kanji-toggle`), grading feedback banners (`火 (Fire)`), and
     the stats screen character review table.
   - Scored via a dedicated 10-class CNN (`model/kanji_cnn.pt`, 812 KB, **99.90% test
     accuracy**) trained via `model/train_kanji_model.py`.
   - **Multi-stroke rasterization**: `rasterize.path_to_image` accepts multiple distinct
     stroke paths and renders them without drawing artificial connector lines across pen-up
     gaps. This fixed an issue where multi-stroke characters (especially `火`) had artificial
     connector lines that turned the glyph into `木` (scoring 0.05% instead of 99.99%). Added
     `KANJI_SCORE_BOOST_GAMMA = 0.7` in `scoring.py` to gracefully accommodate natural hand-drawn
     variations.
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
- **Forgiving Deadzone Auto-Centering**:
  - Replaced the aggressive center-pull spring with a wide central deadzone (`DEADZONE_PX = 140px`,
    creating a 280x280 px free area). Inside this zone, center pull is 0 so the wand moves
    completely naturally with zero rubber-banding.
  - Soft-boundary easing only engages if gyro heading drift nudges the cursor toward the canvas
    perimeter, gently keeping it on-screen.
  - Removed all snapping on `letter_start` and `endLetter`: the cursor never teleports to
    the center when beginning a stroke, drawing smoothly from the exact point of aim. View
    remains locked during drawing.

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

## Multiplayer Versus Mode (Backend Integrated)

- **Engine (`web/server/versus.py`)**:
  - Two wands race to draw the same random letter in the active language.
  - Initial HP: 101 (`START_HP`), Damage: 20 (`DAMAGE`), Passing accuracy: 80.0% (`PASS_ACCURACY`),
    Failed retry cooldown: 1.0s (`RETRY_COOLDOWN_S`), Intermission between rounds: 2.2s (`INTERMISSION_S`).
  - First player to submit a drawing with $\ge 80\%$ accuracy wins the round; the opponent loses 20 HP.
  - Submissions $< 80\%$ lock out only that player for 1 second without losing HP.
  - First player to reach 0 HP loses the match.
  - State messages (`VersusStateMessage`) broadcast on start, join, round win, and match over.
  - Submissions broadcast `VersusAttemptMessage` with live paths and status (`won`, `failed`, `locked`, `stale`).
- **Unified Grading Architecture**:
  - `grade_packet(packet, letter, language)` in `main.py` serves both Solo SRS (`post_stroke`) and
    Versus (`post_versus_stroke`).
  - Multi-stroke path separation (preserving separate strokes without connector lines in `rasterize.py`)
    powers both modes.
- **Multi-Player Live Cursors**:
  - `esp32/src/main.cpp` tags each live sample with `player_id`.
  - `main.py` maintains per-player `live_trackers: dict[str, LiveOrientationTracker]`, broadcasting
    `CursorMessage(player_id=...)` so the frontend can display independent live cursors for each wand.

## Open Questions & Future Milestones

- **Versus Frontend UI**: Wire the mock elements in `#menu-panel-versus` (or a dedicated versus view)
  to `/versus/start`, `/versus/stop`, and the `versus_state` / `versus_attempt` WebSocket messages.
- **Second Wand Mounting**: Pointing axis coordinates (`POINTING_AXIS` in `trajectory.py`)
  are currently calibrated for wand #1; a second device requires wand-specific axis config.
- **Kanji Expansion**: Can expand beyond the initial 10 foundational characters to full
  elementary Grade 1 kanji (80 characters) by extending `train_kanji_model.py`.
