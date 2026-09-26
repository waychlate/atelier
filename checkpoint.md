# Checkpoint — Air-Writing Language Game

Living state-of-the-project doc for Claude sessions working on this repo. `CLAUDE.md` has
the original spec; this file tracks what's actually been decided and built since, so a
fresh session doesn't have to re-derive it from conversation history.

## Scope decisions (superseding parts of CLAUDE.md)

- **Single-player, not 2-player.** Hackathon only has one ESP32 + accelerometer available.
  Game is: server shows a target letter, player draws it, gets scored, cumulative score
  builds up across letters (progression system), no HP/versus mechanic.
- **Networking**: WiFi stays as originally specced (no Bluetooth pivot). ESP32 can't join
  eduroam (enterprise auth), so the plan is a phone hotspot at the venue — no code impact,
  current HTTP POST contract is unchanged.
- **Scoring**: switched from DTW-vs-templates to an **image classifier**. Reconstructed
  path (`trajectory.py`, double-integration + drift correction — unchanged from spec) gets
  rasterized to a 28x28 image and classified by a small CNN trained on EMNIST letters.
  Score = softmax probability of the target letter × 100. DTW/fastdtw and the old
  `templates/` directory are gone.
- **Gyro is unused.** Trajectory reconstruction uses raw `ax/ay` only, no orientation
  compensation. Deliberate tradeoff (see `trajectory.py`'s docstring) — fine as long as
  reconstructed paths look recognizable; revisit only if real hardware data looks warped.
- **Implemented: stroke-by-stroke recognition** with strict stroke order/direction
  enforcement (e.g. T = vertical stem top-to-bottom, then horizontal bar left→right), plus
  a **two-button design**: pen button (hold-to-draw/release-to-pause between strokes) and
  submit button (finalize). **The teammate independently built this on a `firmware`
  branch** (`origin/firmware`, esp32/ dir merged into this working tree) — see the next
  section for the real contract, which differs from what was first assumed here.
  - Canonical per-letter stroke definitions (order, direction, control points for
    rendering) live in `strokes.py` — single source of truth for both validation and the
    reference-hint images, so they can never drift out of sync.
  - Multi-stroke letters (T: 2, A: 3, H: 3, E: 4) get strict validation: each submitted
    stroke is checked against its expected slot's direction (net displacement vector,
    8-way compass, must be within 60° or it's a hard 0 for that slot) — this also enforces
    *order*, since a stroke drawn out of sequence usually fails its slot's direction check.
  - Single-stroke letters (M, S — naturally drawn as one continuous motion) skip this
    entirely and fall back to the whole-path CNN, same as before.
  - If a multi-stroke letter's submitted stroke count doesn't match its expected count,
    also falls back to the whole-path CNN on the concatenated strokes.
  - Verified: correct order/direction scores ~97-100; deliberately wrong order (tested by
    swapping T's two strokes) correctly scores 0.
- **Stroke reference images — implemented, self-generated, not sourced externally.**
  `generate_reference_images.py` renders each letter's canonical stroke definition
  (numbered arrows) straight from `strokes.py` into `web/frontend/reference/<letter>.png`
  — guarantees the hint always matches exactly what's validated. Frontend flashes it after
  5s of no stroke activity (`app.js`'s `scheduleHint`, reset on every `stroke_received` WS
  event, not just round start).

## Real firmware contract (discovered from `origin/firmware`, esp32/ now merged in)

This superseded the two-button design's original assumption of one `POST /stroke` per
stroke plus a separate `POST /submit`. **The actual firmware sends the whole letter in
one HTTP POST**: the pen button (GPIO 4) and submit button (GPIO 18) are both handled
device-side — the ESP32 buffers every sample from first pen-down until submit is pressed
(pen-up gaps between strokes included, each sample tagged `pen: 0/1`), and only then does
one `POST /stroke` with everything. There is no `/submit` endpoint. `GET /round/current`
matches what was already built. Adjusted to match:

- `models.StrokeSample` gained a `pen: bool` field. `t` is **milliseconds since the letter
  started** (firmware: `uint32_t`), not seconds — `trajectory._dt_array` now converts
  (`np.diff(t) / 1000.0`); this was a real bug (1000x integration error) caught before any
  real hardware data hit it. Sample rate is 50 Hz (`SAMPLE_INTERVAL_MS=20` in
  `esp32/include/config.example.h`), not the 100 Hz originally assumed — doesn't matter
  much since reconstruction prefers real `t` diffs when available, but `t` really does need
  to be trusted now that it's not synthetic.
- `main.py`'s `split_by_pen()` splits one incoming packet into per-stroke sample runs
  (contiguous `pen=True` stretches); `pen=False` samples are dropped. `game_state.py` no
  longer buffers anything cross-request — the whole letter arrives atomically, so scoring
  and round-advance both happen inside the single `/stroke` handler now.
- Lost capability: the frontend's live "stroke N of M drawn" progress + per-stroke
  hint-timer-reset don't make sense anymore — the server has zero visibility until the
  whole letter arrives in one shot. Removed that UI; the hint timer now only resets on
  `round_start`.
- `scripts/simulate_stroke.py` rewritten to build one whole-letter packet (strokes + short
  pen=False gap segments in between, 50 Hz, millisecond `t`) and POST it once — matches
  the real firmware shape. Re-verified end-to-end: all 7 demo letters score well; wrong
  order/rotation still correctly reject; reconstruction scale confirmed sane (unit-square
  range, not 1000x blown up) after the ms fix.
- **Not yet done**: no physical ESP32/platformio available in this environment to actually
  flash and test — everything above is verified via the updated simulator standing in for
  real hardware. First real on-device test should double check the `pen` semantics
  (esp32/src/main.cpp drops the trailing pen-up tail before sending, but a leading tail
  before the first pen-down shouldn't exist since buffering starts exactly at first
  pen-down) and confirm real accelerometer noise doesn't break `split_by_pen`'s run
  detection (e.g. debounce chatter producing spurious 1-sample runs).

## Current implementation state (web/server/, web/frontend/)

- `models.py`, `game_state.py`, `main.py`, `trajectory.py` — as described above, working.
  `trajectory.place_in_bbox` repositions each independently-reconstructed multi-stroke
  submission into its canonical slot for display (true relative position isn't recoverable
  from separate accel recordings anyway).
- `strokes.py` — canonical per-letter stroke definitions + direction validation.
- `generate_reference_images.py` — one-time script, renders `web/frontend/reference/*.png`.
- `rasterize.py` — path → 28x28 image for the CNN.
- `model/cnn.py`, `model/train_model.py`, `model/emnist_cnn.pt` — CNN trained on
  `tanganke/emnist_letters` (HF dataset), 92.6% test accuracy. **Note**: that dataset's
  images are transposed (inherited the classic EMNIST byte-format bug) —
  `train_model.py`'s `fix_orientation()` corrects this; if retraining against a different
  EMNIST source, re-verify orientation before trusting accuracy numbers.
- `scoring.py` — rasterize + classify, no DTW.
- `scripts/simulate_stroke.py` — dev tool, synthesizes a fake accelerometer stroke from
  hand-authored per-letter control points and POSTs it to a running server, for
  smoke-testing without real hardware. Verified end-to-end (HTTP + WebSocket broadcast).
- Demo letter set: `config.DEMO_LETTERS` = M, A, T, H, S, E.
- None of the DTW→CNN pivot changes are committed yet (still working tree changes as of
  this checkpoint) — check `git status` before assuming what's on `main`.

## Open questions / not yet decided

- Stroke-order choices for A/H/E (T's order was given directly by the user: vertical stem
  top-to-bottom, then horizontal bar) are my best-guess standard block-letter order — worth
  a quick sanity check against how the user actually wants to teach them, since they're
  easy to tweak in `strokes.py` (just data) but do need real-hand testing.
- First real on-device test is still pending (no hardware in this environment) — see the
  "Not yet done" note above.
- S's whole-path CNN score is the weakest of the demo set (~61-67 for a clean synthetic
  draw) — worth testing with a real ESP32 draw specifically.
- **G added** (circle bowl + straight descender, counterclockwise) as the first
  circular-stroke example — `strokes.py`'s `classify_circular_stroke` validates rotation
  direction via signed area (shoelace formula) instead of net displacement, since a closed
  loop's start/end points are near-identical. Verified: correct rotation ~100, wrong
  rotation (clockwise instead of CCW) correctly scores 0 for that stroke.
  `scripts/simulate_stroke.py --single-shot` tests "drew it in one go" for any
  multi-stroke letter, but my hand-authored synthetic loop+tail shapes for G don't closely
  match real cursive-G topology (the CNN doesn't recognize my synthetic version well) —
  this is a synthetic-test-data limitation, not a system bug, since the same whole-path
  CNN fallback already scores well for M and S. Worth testing G's one-go fallback with a
  real ESP32 draw rather than more synthetic tuning.
