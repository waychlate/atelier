# Checkpoint — Air-Writing Language Game

Living state-of-the-project doc for Claude sessions working on this repo. `CLAUDE.md` has
the original spec; this file tracks what's actually been decided and built since, so a
fresh session doesn't have to re-derive it from conversation history.

## Small UX fixes: theme-aware clouds, Practice-tab language switch, button centering

- **`.cloud`'s color is now a `--cloud-color` theme token** instead of a hardcoded gold
  rgba — the original value was a light gold, nearly invisible against light theme's pale
  parchment background. Light theme now uses a darker warm brown (`rgba(110, 80, 30,
  0.22)`) so clouds actually show up in both themes. Same pattern as every other
  theme-dependent color in this file — if something needs to look different per theme, it
  goes in `:root`/`:root[data-theme="light"]` as a variable, never hardcoded in the rule
  that uses it.
- **Language can now be switched from the Practice tab**, not just Settings —
  `renderLanguageOptions()` (`app.js`) was generalized to render into *both*
  `#language-options` (Settings) and the new `#practice-language-options` (Practice, added
  above "Groupings") from a single loop over `[languageOptionsEl,
  practiceLanguageOptionsEl]`, so both stay in sync automatically on every call — no
  duplicated logic, no separate state to keep consistent.
- **"Start practicing" button is centered** — wrapped in a `.practice-start-row` div
  (`text-align: center`) since `.menu-panel`'s own `text-align: left` was left-aligning it.

## Background: floating multi-script glyphs + drifting clouds

Went through two iterations this session before landing here — worth knowing if either
approach comes up again:
1. Sparkle particle field (dots) from the original magic-theme pass.
2. Replaced with dense horizontal marquee rows of characters (one row per script, scrolling
   sideways) — tuned through several rounds (size, spacing, speed, row density) into a
   deliberately dense, "mysterious wall of ancient text" look, tiled to cover the full
   viewport height.
3. **Replaced again** (teammate's request via the user): rows felt too rigid/mechanical —
   wanted it to "float around and look magical, with clouds" instead. Current
   implementation:

- `app.js`'s `initMagicBackground()` (container: `#magic-background`, was
  `#alphabet-marquee`) builds two independent layers:
  - **`.cloud`** — 6 large soft-blurred radial-gradient ellipses (`filter: blur(30px)`),
    randomized size/vertical position/duration, drifting left-to-right via `@keyframes
    cloud-drift`.
  - **`.floating-glyph`** — 45 individual characters, each randomly drawn from a pooled set
    of all 10 scripts (not one-script-per-row anymore — `MARQUEE_SCRIPTS` is now just a
    flat character pool, the per-script row structure is gone), each with randomized
    starting x-position, font-size, and a per-element `--drift` CSS custom property (random
    horizontal sway amount) consumed by `@keyframes glyph-float` (rises + sways + rotates +
    fades in/out over its lifetime).
  - Both use **negative `animation-delay`** (`-Math.random() * N`) so elements are already
    mid-animation on page load instead of all synchronously fading in from zero — avoids an
    obviously-just-loaded look.
- All motion is still pure CSS — JS only scatters initial randomized values once at load,
  no per-frame work, consistent with every background-effect iteration this session.
- Font-family stack (Noto Sans CJK/Arabic/Thai/Khmer/Devanagari, confirmed installed via
  `fc-list`) carried over unchanged from the marquee version — same caveat: a machine
  without these fonts shows tofu boxes for the non-Latin glyphs, purely cosmetic.
- Still hidden on the Play screen via the same `body.play-active` toggle in `showScreen()`
  (now targets `.magic-background` instead of `.alphabet-marquee`) — that decision (keep
  the drawing screen visually quiet) has survived all three background iterations.

## Stats charts were blurry — canvas DPR/sizing fix

The "Accuracy over time" timeline and per-letter sparklines (`app.js`) drew at a fixed
low-res pixel buffer (canvas `width`/`height` attributes, e.g. 480x160) while CSS stretched
the timeline to `width:100%` — the browser upscales/blurs a canvas whenever its CSS display
size exceeds its actual pixel buffer, and a canvas whose buffer matches its CSS size 1:1
still looks soft on any high-DPI/retina display. Fixed with `setupCanvasDPR(canvas,
cssWidth, cssHeight)`: sizes the pixel buffer to `cssSize * devicePixelRatio` and scales the
context via `setTransform`, while callers keep doing all layout math in CSS pixels.
**Non-obvious gotcha hit while building this**: the first version also set
`canvas.style.width/height` inline to pin the CSS display size — this broke the timeline,
because when `renderTimeline()` first runs while `#screen-stats` is still hidden (e.g. from
`onLoggedIn()`'s eager `refreshStats()` call), `clientWidth` reads `0`, falls back to 480,
and that inline style then **permanently locks the canvas at 480px** on every later call
too (inline style overrides the responsive `width:100%` CSS rule, and `clientWidth` just
reports back whatever was last inline-styled). Fix: `setupCanvasDPR` never touches
`style.width/height` — the timeline's CSS `width:100%;height:auto` stays in full control
(the width/height *attributes* still define its aspect ratio even after DPR-scaling, so
`height:auto` keeps computing correctly), and the sparklines instead get an explicit
`width: 80px; height: 22px` in `style.css` (`.letters td canvas`) since nothing else was
constraining their display size. Lesson for next time: if a canvas needs a fixed CSS
display size, put it in a stylesheet rule, not `element.style.*` set from inside a function
that might run before the element is actually visible/measurable.

## Magic-themed UI/UX overhaul

Dark mystical/gothic-academy reskin, decided via several rounds of clarifying questions
(mood, layout scope, component depth, background, colors) rather than assumed — see plan
history if the reasoning behind a choice is unclear later.

- **Palette swap** (`:root` in `style.css`): background moved from flat `#111` to deep
  indigo/purple (`--bg: #14091f`) with a subtle radial purple glow (`--bg-glow`) behind the
  header. **Cyan (`#4fc3f7`) is fully retired as the interactive accent** — gold
  (`--accent: #d9b34d`) replaces it everywhere: selected states, buttons, scores, chart
  lines. Panels get a translucent gold border (`--panel-border`) instead of flat grey, for
  a gilded-edge look. Light theme got its own coherent parchment/gold variant, not just an
  inverted dark palette. Any component already using `var(--accent)`/`var(--chip-bg)`
  tokens needed zero changes — only genuinely hardcoded hex (`#4fc3f7`, and its rgb form
  `rgba(79,195,247,...)`) needed hunting down, in both `style.css` and `app.js` (cursor dot
  fill, canvas stroke color, `scoreColor()`'s "good" threshold).
- **Shared full-width header** (`.app-header` in `index.html`/`style.css`): one header
  block, hoisted **outside** the `.screen` sections entirely (not duplicated per screen) —
  centered "Atelier" title (still Makcasa-only; body text stays system-ui per the
  readability decision, especially for the Stats table), `#current-player` pinned top-right
  via CSS grid (`grid-template-columns: 1fr auto 1fr`). `#menu-tabs` also hoisted out of
  `#screen-menu` into its own persistent full-width strip directly under the header, shown
  only while the menu screen is active (`showScreen()` now toggles a `.hidden` class on it)
  — this was necessary to avoid duplicate-id / per-screen-header duplication problems.
  Actual screen content (letter grid, stats table, settings groups) still lives in a
  `.screen-content` wrapper that keeps the old ~900px centered width — only the
  header/background go edge-to-edge, per the "content shouldn't get harder to read" call.
- **CSS-only particle field** (`.particle-field`/`.spark` in `style.css`, generated once in
  `app.js`'s `initParticleField()`): ~28 small gold/white radial-gradient dots with
  randomized `left`/`animation-delay`/`animation-duration`, animated purely via one
  `@keyframes spark-drift` (drift upward + twinkle). No canvas, no per-frame JS — chosen
  specifically so it doesn't compete with the app's existing drawing/cursor canvases.
  Deliberately subtle (visible but not distracting) at 28 sparks; bump `COUNT` in
  `initParticleField()` if it should read as more "alive."
- **Play screen stays visually quiet on purpose** — canvas/cursor/hint-image styling
  barely changed (just inherits the new neutral-dark `--canvas-bg`/`--canvas-border`), no
  ornate frame, no particle-field interference — this was an explicit decision to protect
  drawing-accuracy legibility over thematic consistency.
- **Gemini's transition/animation mechanics were kept as-is** (`screen-fade-in`,
  `panel-fade-in`, button hover/press transforms, `result-pass`/`result-fail` glow,
  `grade-pop`) — only their colors were repointed to the new palette, no new animation
  logic was added on top.
- One gotcha hit during this pass: the tab-bar's background band was first hardcoded to a
  dark-purple rgba (`rgba(30, 16, 48, 0.4)`), which looked muddy/wrong once Light theme was
  actually screenshotted — fixed to `var(--chip-bg)` so it adapts per theme. Lesson: always
  visually check a themed rgba against *both* themes, not just the one being actively
  designed in.

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
- **Menu navigation**: Four horizontal tabs: Versus (live — see "Multiplayer Versus
  Mode" below), Practice, Shop (placeholder), and Settings. Subtitle dynamically updates per tab
  (`showMenuTab`): Versus ("Test your skills against equal opponents"), Practice ("Hone your
  skills in isolation"), Shop ("Reap your rewards"), and Settings (empty/hidden).
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

- **ElevenLabs TTS**: Reads the target prompt in both modes (Learn: alongside the shown
  letter + stroke hint; Blind: the only cue). Speaker button replays it. Audio clips are
  cached locally in `web/server/tts_cache/`. Requires `ELEVENLABS_API_KEY` (the `sk_...`
  secret, not the key ID shown in the dashboard list; paid plan needed for library voices)
  and voice IDs:
  - English/Latin: `ELEVENLABS_VOICE_ID` (`qWRrMoaOJUg6mVvRBiwM`).
  - Japanese (Hiragana & Kanji): `ELEVENLABS_JA_VOICE_ID` (`OrIijq7uyVaGDbu9tqly`).
  - The old defaults (`vTdzvS51...`, `v36jhKEf...`) returned `voice_not_found` on our account.
  - Routed dynamically via [`config.voice_id_for_language(language)`](file:///home/doa/projects/atelier/web/server/config.py#L29-L33).
  - Clips generate on first request and are cached to disk after that (the cache is
    gitignored, so each laptop builds its own). Warm it before a demo so venue Wi-Fi can't
    break audio.
  - `config.py` loads `.env` via `python-dotenv`.
  - Unset API key &rarr; Blind mode stays locked in UI.
- **Tiger Data (TimescaleDB)**: Optional persistence for `attempts` and SRS cards across
  restarts. Unset or unreachable `DATABASE_URL` &rarr; server runs purely in-memory via
  `GameState`.

## Multiplayer Versus Mode (Backend + Frontend Integrated)

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
- **Frontend (`web/frontend/index.html` / `app.js` / `style.css`)**:
  - `#menu-panel-versus` (Versus tab) shows a compact HP/namecard preview and a "Start match"
    button (`POST /versus/start`), then navigates to `#screen-versus`.
  - `#screen-versus` is the live match view: shared target letter, an intermission banner between
    rounds, and two side-by-side player panels (namecard, HP bar, a small canvas for that wand's
    live cursor/trail, and a status line).
  - Each player panel gets its own cursor renderer (`makeVersusRenderer`, mirrors the solo
    cursor/trail logic but as a reusable instance — two independent copies, one per wand).
    `player_id`s are assigned to slots 0/1 in join order (`versusSlotOf`) and stay fixed for the match.
  - `renderVersusState` updates HP bars (color shifts green→orange→red as HP drops) and the
    winner banner from `versus_state` messages; `renderVersusAttempt` flashes each panel's canvas
    border and sets status text (e.g. "Won the round!", "Missed — try again in a moment") from
    `versus_attempt` messages.
  - `versusActive` gates the WS `"cursor"` handler so live samples route to the right renderer
    (versus panels vs. the solo play canvas) — the two never cross-talk.
  - **Known gap**: no session-resume. If the browser reloads mid-match, the WS reconnects and the
    next `versus_state` broadcast catches the UI up, but there's no immediate poll of current state
    on load — clicking "Start match" again would restart the match rather than rejoin it. Low
    priority for a table demo where the tab stays open; flagged rather than guessed at.

## Open Questions & Future Milestones

- **Second Wand Mounting**: Pointing axis coordinates (`POINTING_AXIS` in `trajectory.py`)
  are currently calibrated for wand #1; a second device requires wand-specific axis config.
- **Kanji Expansion**: Can expand beyond the initial 10 foundational characters to full
  elementary Grade 1 kanji (80 characters) by extending `train_kanji_model.py`.
