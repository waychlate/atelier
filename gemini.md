# Add Japanese (hiragana) as a playable language

## Context

Japanese hiragana currently exists only as plumbing: `config.LANGUAGES["japanese"]` has
`enabled=False`, and `POST /language/japanese` is rejected server-side. Investigation
confirmed everything _except scoring_ is already language-agnostic and works today with no
changes: `game_state.py`/`srs.py` (independent per-language decks/clocks, non-ASCII-safe
`letter.upper()` guard already in place), `trajectory.py` (pure IMU math, no letter
assumptions), `tts.py` (already hex-encodes cache keys specifically to survive kana, per its
own comment), and the frontend's language-switch UI (`app.js`'s `renderLanguageOptions`/
`POST /language/{code}` flow is fully generic).

The two real gaps, and the decisions made to scope this for a hackathon timeline:

1. **Stroke-order validation** (`strokes.py`'s per-stroke direction/rotation checks) only
   understands straight-line and full-circle shapes — hiragana's curves/hooks don't fit
   either primitive, and building a new shape/validation model is out of scope. **Decision:
   skip strict per-stroke validation for Japanese entirely** — hiragana letters simply won't
   appear in `strokes.MULTI_STROKE_LETTERS`, so `main.py`'s existing dispatch in
   `post_stroke()` already falls through to the whole-path CNN branch automatically
   (`strokes.expected_stroke_count()` defaults unmapped letters to 1 — confirmed at
   `strokes.py:227-231`, no code change needed there).

2. **Scoring** — the CNN is architecturally locked to 26 Latin classes
   (`model/cnn.py:9,28`: `LETTERS = string.ascii_uppercase`, baked into the output layer
   size), so today any hiragana attempt scores a hard 0 (`scoring.py:30-32`). Gemini vision
   was named as "the path to Japanese" in `CLAUDE.md` but has zero implementation anywhere.
   **Decision: no Gemini** (the team is moving to a wired ESP32 connection with an existing
   low-latency demo, and wants to avoid adding an external API dependency). **Instead: train
   a second CNN specifically for hiragana**, mirroring the existing
   `model/train_model.py` pattern, and make `scoring.py`/`main.py` pick the right
   (model, letter-set) pair based on the active language.

Also decided: reference hint images will be **pre-made, not derived from stroke data**
(`generate_reference_images.py` only draws straight-line segments and can't render curves) —
rendered from a font instead, and the character set will cover the **full ~46-character
hiragana gojuon table**, not just the current 5.

## Changes

1. **`config.py`** — expand `LANGUAGES["japanese"].letters` to the full 46-character
   hiragana gojuon set (あいうえお かきくけこ さしすせそ たちつてと なにぬねの
   はひふへほ まみむめも やゆよ らりるれろ わをん). Leave `enabled=False` until steps
   2-4 are done, then flip to `True` as the last step.

2. **`model/cnn.py`** — generalize `EmnistCNN` to take a `num_classes` constructor param
   (default `len(LETTERS)` to keep the existing Latin model/weights loading unchanged).
   This lets one architecture class serve both the Latin and hiragana models.

3. **New `model/train_hiragana_model.py`** — mirror `model/train_model.py`'s structure
   (same `EmnistTorchDataset`-style wrapper, `evaluate()`, training loop, CPU-only,
   `datasets.load_dataset`) but trained on a Kuzushiji-49-style hiragana dataset (49
   MNIST-format classes covering the hiragana set, analogous to how `tanganke/emnist_letters`
   serves Latin). Saves `model/hiragana_cnn.pt`.
   - **Correctness-critical**: the label-index-to-character order used here must be recorded
     and reused verbatim in `scoring.py` — get this from the dataset's own class-label
     mapping (e.g. its `classmap`/`ClassLabel` names), not from `config.py`'s list order,
     the same way `model/cnn.py`'s `LETTERS = string.ascii_uppercase` directly matches the
     EMNIST dataset's label indices today.
   - **Flag before committing to a dataset**: Kuzushiji datasets (K49/KMNIST) use classical
     _kuzushiji_ cursive glyph forms, which can look meaningfully different from the modern
     printed hiragana shown to learners. Confirm the dataset's visual style is close enough
     to what the reference images show before training — if it's too different, the model
     will learn to grade against the wrong target shape. Note this exact caveat in
     `model/train_hiragana_model.py`'s docstring either way (matching the existing
     `fix_orientation()` orientation-bug precedent in `train_model.py`).

4. **`scoring.py`** — generalize `load_model`/`score_stroke`/`LETTER_TO_INDEX` away from
   the Latin-only module-level constants so both languages' (model, letter-index-map) pairs
   can coexist — e.g. `score_stroke(path, target_letter, model, letter_to_index)` taking the
   index map explicitly, with a small helper to build it from a given ordered letter list.

5. **`main.py`** — at startup, load a second model the same optional/graceful way
   `ELEVENLABS_API_KEY`/`DATABASE_URL` already degrade (missing `hiragana_cnn.pt` -> log a
   warning, leave Japanese unplayable, don't crash). In `post_stroke()`, the two branches
   that currently call `scoring.score_stroke(path, letter, model)` (~`main.py:372,375`)
   need to select the Latin or hiragana `(model, letter_to_index)` pair based on
   `game_state.language`.

6. **New `generate_hiragana_reference_images.py`** — renders each hiragana character as a
   plain glyph image into `web/frontend/reference/<char>.png`, using PIL + the system's
   already-installed Noto Sans CJK font (`/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc`,
   confirmed present) — no external image sourcing or network fetch needed. This is a
   simpler "what the character looks like" hint rather than Latin's arrow-annotated
   stroke-order diagrams, consistent with skipping stroke-order enforcement for Japanese.

7. **Small fix while touching this path**: `web/frontend/app.js:221`
   (`` hintImage.src = `reference/${currentLetter}.png` ``) isn't URL-encoded, unlike the
   TTS call two lines below it (`app.js:229`, which does use `encodeURIComponent`). Apply
   the same `encodeURIComponent(currentLetter)` here for consistency/safety with non-ASCII
   filenames.

8. **`config.py`** — flip `LANGUAGES["japanese"].enabled = True` once the model file and
   reference images exist and steps 4-5 are wired up.

## Verification

- Run `python -m model.train_hiragana_model` (mirroring how `train_model.py` is invoked)
  and confirm test-set accuracy is in a reasonable range (compare to Latin's documented
  92.6%) before trusting it — check for a label-order mismatch first if accuracy looks
  near-random.
- Start the server and confirm the startup log shows the hiragana model loaded (or a clear
  warning if the weights file is missing), mirroring the existing Tiger Data/ElevenLabs
  optional-dependency log pattern.
- `POST /language/japanese` should now succeed (200, not the current 400).
- Use a quick FastAPI `TestClient` smoke test (same technique used to debug the earlier
  WS issue) or extend `scripts/simulate_stroke.py` to accept a hiragana character, POST a
  synthesized stroke for e.g. "あ", and confirm a non-zero, plausible score comes back
  (rather than the current hard 0).
- Load the frontend, switch language to Japanese via the settings modal, confirm: the
  target-letter display shows a hiragana character, the reference hint image loads (check
  the `encodeURIComponent` fix didn't break the existing Latin path), and Blind-mode TTS
  audio plays for a hiragana prompt (already-working `tts.py` path — just confirm it
  sounds reasonable for kana, since checkpoint.md notes ElevenLabs hasn't been exercised
  against real credentials for this yet).
- Confirm Latin play-through still works unaffected after all changes (regression check on
  `scoring.py`'s generalization).
