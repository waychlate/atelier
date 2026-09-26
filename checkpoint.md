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
  enforcement (e.g. T = horizontal bar left→right, then vertical stem top→bottom), plus a
  **two-button hardware design**: button 1 = hold-to-draw/release-to-send one stroke
  (`POST /stroke`, buffers only, no scoring), button 2 = submit once all strokes for the
  letter are drawn (`POST /submit`, scores + advances the round). **This is a data-contract
  change the teammate's firmware needs to implement** (second button/gesture) — not yet
  confirmed with them.
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

## Current implementation state (web/server/, web/frontend/)

- `models.py`, `game_state.py`, `main.py`, `trajectory.py` — as described above, working.
  `game_state.py` now buffers strokes (`pending_strokes`) across the round instead of
  scoring on every `/stroke` call; `trajectory.place_in_bbox` repositions each
  independently-reconstructed multi-stroke submission into its canonical slot for display
  (true relative position isn't recoverable from separate accel recordings anyway).
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

- **Two-button hardware change needs teammate firmware coordination — not yet confirmed.**
  Until then, `scripts/simulate_stroke.py` (updated for the new POST /stroke + POST
  /submit flow) is the only way to test this end-to-end.
- Stroke-order choices for A/H/E (T's order was given directly by the user: horizontal
  bar then vertical stem, top-to-bottom) are my best-guess standard block-letter order —
  worth a quick sanity check against how the user actually wants to teach them, since
  they're easy to tweak in `strokes.py` (just data) but do need real-hand testing.
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
