# Checkpoint — Air-Writing Language Game

Living state-of-the-project doc for Claude sessions working on this repo. `CLAUDE.md` has
the original spec; this file tracks what's actually been decided and built since, so a
fresh session doesn't have to re-derive it from conversation history.

## Scope decisions (superseding parts of CLAUDE.md)

- **Single-player, not 2-player.** Hackathon only has one ESP32 + IMU wand available.
  Game is: server picks a target letter (via spaced repetition, see below), player draws
  it, gets scored, cumulative score builds up across letters — no HP/versus mechanic.
- **Networking**: WiFi, real hardware, tested end-to-end (see "Real firmware contract"
  below). ESP32 can't join eduroam (enterprise auth); a phone hotspot works around venue
  WiFi client isolation (devices on the same shared network often can't reach each other).
- **Scoring**: switched from DTW-vs-templates to an **image classifier**. Reconstructed
  path (`trajectory.py`) gets rasterized to a 28x28 image and classified by a small CNN
  trained on EMNIST letters. Score = softmax probability of the target letter × 100.
  DTW/fastdtw and the old `templates/` directory are gone.
- **Path reconstruction uses gyro + accel (laser-pointer model).** Real wand recordings
  show players draw by _rotating_ the wand — total acceleration stays within ~1 m/s² of
  gravity during a stroke — so accel-only double-integration was mostly measuring gravity
  shifting between axes as the wand tilted: fine for straight strokes, badly distorted
  curvy ones (S, M). `trajectory.reconstruct_pointer_path` tracks orientation (gyro
  integration corrected toward the accelerometer's gravity reading, Mahony-style) and
  draws where the wand points; it runs over the whole letter, pen-up gaps included, so
  strokes keep their real relative positions. Replaying 18 real recordings through
  `/stroke`: mean score 34.5 → 54.6 (e.g. S 0 → 91.7, M 43.7 → 99.5, a 4-stroke M drawn
  with pen lifts between each stroke 0 → 99.0). Mounting matters: `POINTING_AXIS` in
  `trajectory.py` was measured with horizontal/vertical calibration strokes on the current
  wand (chip flat, wand along +y) — a differently-mounted chip (e.g. a second wand) needs
  it re-measured. Accel-only `reconstruct_path` remains the fallback for packets without
  gyro (`trajectory.has_gyro`) — exercise it with `scripts/simulate_stroke.py --no-gyro`.
- **Implemented: stroke-by-stroke recognition (Latin only)** with strict stroke
  order/direction enforcement (e.g. T = vertical stem top-to-bottom, then horizontal bar
  left→right), plus a **two-button wand design**: pen button (hold-to-draw/release-to-pause
  between strokes) and submit button (finalize) — see "Real firmware contract" below for
  the exact wire format.
  - Canonical per-letter stroke definitions (order, direction, control points for
    rendering) live in `strokes.py`'s `MULTI_STROKE_LETTERS` — single source of truth for
    both validation and the reference-hint images, so they can never drift out of sync.
    Covers all 26 Latin letters. **Not hiragana** — see below, this was tried and reverted
    this session.
  - Multi-stroke letters get strict validation: each submitted stroke is checked against
    its expected slot's direction (net displacement vector, 8-way compass, or rotation
    direction via signed area for circular strokes like O/G's bowl) — this also enforces
    _order_, since a stroke drawn out of sequence usually fails its slot's check.
  - Single-stroke letters (M, S — drawn as one continuous motion) skip this and fall back
    to the whole-path CNN.
  - If a multi-stroke letter's submitted stroke count doesn't match its expected count,
    also falls back to the whole-path CNN on the concatenated strokes.
  - Letter **S**'s reference/synthetic shape was a jagged 6-point zigzag that visually
    read poorly and, on a first fix attempt, an incorrectly-signed cosine parametrization
    produced a shape the CNN didn't recognize at all (scored 0). Fixed to a proper
    sine-based two-lobe curve (`strokes._s_curve_points`) — verify any future stroke-curve
    formula the same way (via `scripts/simulate_stroke.py`) before trusting it.
- **Hiragana per-stroke validation: tried, then reverted, this session.** Added
  `HIRAGANA_STROKES` (all 46 characters) to `strokes.py` mirroring the Latin approach, plus
  wider tolerances/score floors (`DIRECTION_MATCH_THRESHOLD_LENIENT` etc.) since the data
  was hand-approximated without a visual reference. Then compared our self-generated hint
  images against real stroke-order references (Wikimedia Commons) and found ours read as
  abstract disconnected arrows, nothing like the real calligraphic shapes. Decision: rather
  than hand-tracing 46 characters' curves to match, **use the real reference images
  directly** (see below) and **drop hiragana's per-stroke validation entirely** — enforcing
  order against unvalidated approximate data that might not even match what the player is
  now shown would be worse than not enforcing it. The live wand-cursor overlay (see
  "Languages, modes..." section) plus an accurate reference image now carry the
  self-correction job instead of backend order enforcement. `strokes.py` is Latin-only
  again; all the lenient-scoring plumbing it grew for hiragana was removed with it.
  Hiragana still gets the CNN-fallback leniency curve (`scoring.HIRAGANA_SCORE_BOOST_GAMMA`,
  a `raw**0.6` boost) since that's now its *only* scoring path, and the 49-way K49
  classifier (87.93% test accuracy) genuinely does spread softmax thinner than Latin's
  26-way/92.6% one for an equally "correct" drawing.
- **Stroke reference images**:
  - Latin: self-generated by `generate_reference_images.py` straight from `strokes.py`'s
    canonical definitions into `web/frontend/reference/<letter>.png`, so the hint always
    matches exactly what's validated.
  - Hiragana: **real stroke-order animations downloaded from Wikimedia Commons'
    [Stroke Order Project](https://commons.wikimedia.org/wiki/Commons:Stroke_Order_Project/Hiragana)**
    (CC0/public domain), saved as `web/frontend/reference/<char>.gif` — one-time download,
    not regenerated by any script here (there's no `strokes.py` data to regenerate them
    from anymore). `app.js`'s hint-loading picks `.gif` for Japanese vs `.png` for Latin
    based on `activeLanguage`. If a character's file is ever missing/needs
    re-fetching: `https://commons.wikimedia.org/w/api.php?action=query&titles=File:Hiragana_<char>_stroke_order_animation.gif&prop=imageinfo&iiprop=url&format=json`
    (mind the Wikimedia API's rate limit — space out requests, ~1.5s+ between downloads,
    or it 429s).
  - The hint image (both languages) is now docked to the **bottom-right corner** of the
    canvas at a small fixed size (`style.css`'s `.hint-image`), not overlaid full-size on
    top of the drawing area — it was covering the whole canvas before and getting in the
    way of actually drawing.
- **Languages, modes, spaced repetition, TTS — implemented by the teammate on top of the
  above** (see the new section below).

## Real firmware contract (esp32/, `main` branch — real hardware, tested)

One `POST /stroke` per **letter**, not per stroke: the pen button (GPIO 4) and submit
button (GPIO 18) are both handled device-side — the ESP32 buffers every sample from first
pen-down until submit is pressed (pen-up gaps between strokes included, each sample tagged
`pen: 0/1`), then sends one packet with everything. There is no `/submit` endpoint.
`GET /round/current` gives the target letter to submit against.

- `models.StrokeSample.t` is **milliseconds since the letter started** (firmware:
  `uint32_t`). `sample_rate_hz` is 50 (`SAMPLE_INTERVAL_MS=20` in
  `esp32/include/config.example.h`).
- `main.py`'s `split_by_pen()` splits one incoming packet into per-stroke sample runs
  (contiguous `pen=True` stretches); `pen=False` samples are dropped for stroke
  validation but kept for the gyro pointer reconstruction (see above — they're needed to
  track where the wand moved between strokes).
- **Real hardware confirmed working end-to-end**, including on-device testing: IMU init
  (auto-detects MPU-6050/6500/9250/9255 via WHO_AM_I — `esp32/src/imu_driver.cpp` — the
  current wand reports 0x70, an MPU-6500 sold as a "9250"), WiFi connect, two-button
  capture, `/stroke` POST, and the browser UI updating live over the `/ws` broadcast.
  A phone hotspot is the reliable way to get the wand and the laptop running the server on
  the same network without WiFi client isolation blocking device-to-device traffic.
- `esp32/include/config.h` is gitignored (real WiFi credentials + server IP); copy
  `config.example.h` to `config.h` and fill in real values, per-wand.
- **Debugging real recordings**: start the server with `RECORD_DIR=recordings` and every
  `/stroke` packet gets saved as JSON (gitignored) — used to find and fix the ay-sign bug
  and to build/verify the gyro pointer reconstruction above, against real motion instead
  of only synthetic data.
- `scripts/simulate_stroke.py` synthesizes IMU data for a wand that _aims_ at a letter's
  shape (gyro rates + gravity tilt) rather than translates through it — matches how real
  hardware draws. `--single-shot` tests a multi-stroke letter drawn without lifting the
  pen; `--no-gyro` tests the accel-only fallback.

## Languages, modes, spaced repetition, TTS (teammate's work, merged into this session)

- **`config.LANGUAGES`**: Latin (26 letters) and Japanese hiragana (46
  characters, gojuon set) are both fully playable (`enabled=True`). Japanese uses a
  dedicated 49-class CNN trained on Kuzushiji-49 (`model/hiragana_cnn.pt`), with
  reference glyph images rendered from Noto Sans CJK into `web/frontend/reference/`.
  `GET /languages`, `POST /language/{code}` switch the active deck.
- **Modes**: `learn` (shows the stroke reference hint) and `blind` (audio-only — plays the
  letter's sound via ElevenLabs TTS instead of a visual hint, `tts.py`). Blind mode is
  locked in the UI until `ELEVENLABS_API_KEY` is configured (`GET /modes` reports
  `enabled`), same pattern as an unconfirmed language. `POST /mode/{code}`,
  `GET /tts/{language}/{letter}` (cached per language+letter on disk).
- **Spaced repetition (`srs.py`)**: Anki-style SM-2 variant, but the "clock" is review
  count, not wall time (an interval of 3 means "due again after 3 more reviews") — day-
  scale intervals would make spacing invisible in a demo. `game_state.py` picks the next
  target letter from the SRS scheduler instead of a fixed cycle; Latin and Japanese have
  independent decks/clocks.
- **Persistence (`db.py`, Tiger Data / TimescaleDB)**: every attempt + SRS card state,
  keyed by (player_id, language, letter). Fully optional — unset or unreachable
  `DATABASE_URL` and the game runs in-memory only, same as before (`GameState` is always
  the source of truth mid-session; the DB is persistence + analytics, written
  best-effort off the request path via a background task so a slow/down DB never delays
  the ESP32's response). `web/server/.env.example` has the env vars; copy to `.env` and
  run with `uvicorn main:app --env-file .env`.
- **`GET /stats`**: per-letter attempt history + a timeline, from Tiger Data if connected
  else computed from the in-memory attempt log (same response shape either way).
- **`POST /progress/reset`**: wipes SRS cards + attempt history for one language, leaves
  others untouched.

## Current implementation state (web/server/, web/frontend/)

- `main.py` — FastAPI app; `/stroke` picks reconstruction (gyro pointer vs accel
  fallback) and scoring method (strict per-stroke vs whole-path CNN), `game_state.submit`
  grades the SRS card and returns the round result, then a background task persists to
  Tiger Data and broadcasts over `/ws`.
- `trajectory.py` — `reconstruct_pointer_path` (primary) and `reconstruct_path`
  (accel-only fallback); `place_in_bbox` repositions each independently-reconstructed
  multi-stroke submission into its canonical slot for display (true relative position
  across _separate_ button-press recordings isn't recoverable from accel alone — this
  doesn't apply to the gyro pointer path, which tracks position continuously through
  pen-up gaps).
- `strokes.py` — canonical per-letter/character stroke definitions (26 Latin + 46
  hiragana) + direction/rotation validation, with looser tolerances for hiragana.
- `game_state.py`, `srs.py`, `db.py`, `tts.py`, `config.py`, `models.py` — as described
  above.
- `generate_reference_images.py` — renders `web/frontend/reference/*.png` from
  `strokes.py`.
- `rasterize.py` / `scoring.py` — path → 28x28 image → CNN classification.
- `model/cnn.py`, `model/train_model.py`, `model/emnist_cnn.pt` — CNN trained on
  `tanganke/emnist_letters` (HF dataset), 92.6% test accuracy. **Note**: that dataset's
  images are transposed (inherited the classic EMNIST byte-format bug) —
  `train_model.py`'s `fix_orientation()` corrects this; if retraining against a different
  EMNIST source, re-verify orientation before trusting accuracy numbers.
- `esp32/` — firmware, real hardware tested (see above).
- `scripts/simulate_stroke.py` — dev tool, POSTs a synthesized letter to a running server
  without needing real hardware.

## Open questions / not yet decided

- Stroke-order choices in `strokes.py` are a best-guess standard order for most
  letters/characters (Latin block-letter order; hiragana standard modern teaching order)
  — worth a sanity check against how this is meant to be taught, since they're easy to
  tweak (just data) but do need real-hand testing per letter/character. This applies
  doubly to hiragana's stroke geometry (`HIRAGANA_STROKES`): schematic approximations
  authored without a visual reference, not calligraphic tracing — direction/order should
  be reasonably faithful to standard teaching, but hooks/curls on characters like む, ゆ,
  ん are the most likely to need adjustment after real-hand testing.
- Second wand: mounting-dependent constants (`POINTING_AXIS` in `trajectory.py`) are a
  single global right now, measured on one wand. A second wand with a differently-mounted
  chip needs its own calibration; if two wands are ever live at once this becomes
  per-player, not global.
- **ElevenLabs: tested against real credentials this session, found two bugs.** (1)
  `.env`'s `ELEVENLABS_VOICE_ID=` was present-but-empty, and `os.environ.get(key, default)`
  only falls back to `default` when the key is _absent_, not empty — every TTS request hit
  a URL with no voice ID and 404'd. Fixed by removing the blank line so the default
  ("Rachel") applies. (2) Separately, ElevenLabs changed policy (~March 2026): free-tier
  API keys can no longer use Voice Library voices (any `premade`/`professional` category,
  including all default/library voices like Rachel) — only genuinely cloned/generated
  voices, a 402 `paid_plan_required` otherwise. `.env`'s `ELEVENLABS_VOICE_ID` is now set
  to a real custom voice ID on the account owner's ElevenLabs account, confirmed working
  end-to-end (audio plays, `tts_cache/` populates). If TTS goes silent again on a fresh
  account/key, check both of these first.
- **Blind mode was showing the target letter next to the speaker icon** before the player
  attempted it, defeating the audio-recall point of the mode — `app.js`'s `round_start`/
  `stroke_result` handlers set `targetLetterEl.textContent` unconditionally. Fixed via a
  `showTargetLetter()` helper that masks it to `?` in blind mode (Learn mode unaffected);
  the post-attempt feedback line still reveals the letter after grading, as before.
- **Merged in from upstream this session**: a live wand-cursor overlay on the canvas
  (`app.js`'s `onCursor`/`drawCursor`, driven by a new `cursor` WebSocket message type from
  `main.py`) showing where the wand currently points plus a dim trail of the in-progress
  letter's strokes, with `+`/`-` keys to adjust sensitivity (persisted to `localStorage`).
  Also brought in `esp32`'s network-manager cleanup and `scripts/serial_bridge.py`.
- Tiger Data is optional (unset/unreachable `DATABASE_URL` → in-memory mode) and hasn't
  been exercised against real credentials in this environment yet.
