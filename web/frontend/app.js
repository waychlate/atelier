const targetLetterEl = document.getElementById("target-letter");
const accuracyEl = document.getElementById("accuracy");
const cumulativeScoreEl = document.getElementById("cumulative-score");
const nextRoundBtn = document.getElementById("next-round-btn");
const canvas = document.getElementById("canvas");
const canvasWrap = document.querySelector(".canvas-wrap");
const ctx = canvas.getContext("2d");
const hintImage = document.getElementById("hint-image");
const cursorCanvas = document.getElementById("cursor-canvas");
const cursorCtx = cursorCanvas.getContext("2d");
const perStrokeScoresEl = document.getElementById("per-stroke-scores");
const gradeEl = document.getElementById("grade");
const lettersBody = document.getElementById("letters-body");
const sourceEl = document.getElementById("source");
const totalReviewsEl = document.getElementById("total-reviews");
const timelineCanvas = document.getElementById("timeline");
const timelineEmpty = document.getElementById("timeline-empty");
const resetProgressBtn = document.getElementById("reset-progress-btn");
const languageTabsEl = document.getElementById("language-tabs");
const languageOptionsEl = document.getElementById("language-options");
const modeOptionsEl = document.getElementById("mode-options");
const weakestCalloutEl = document.getElementById("weakest-callout");
const weakestListEl = document.getElementById("weakest-list");
const settingsOverlay = document.getElementById("settings-overlay");
const audioSlider = document.getElementById("audio-slider");
const playAudioSlider = document.getElementById("play-audio-slider");
const replayAudioBtn = document.getElementById("replay-audio-btn");

const GRADE_LABELS = {
  again: "Again",
  hard: "Hard",
  good: "Good",
  easy: "Easy",
};
const HINT_TIMEOUT_MS = 5000;
// How long the just-submitted drawing + pass/fail state stays up before the
// canvas clears and the next letter's prompt begins. Was previously instant
// (target letter and hint switched the moment the result arrived), which
// meant the old drawing sat on screen, unexplained, through the whole next
// attempt - looked like a stuck/mismatched image.
const RESULT_DISPLAY_MS = 2200;

let hintTimer = null;
let resultTimer = null;
let currentLetter = null;
let activeLanguage = "latin"; // what's actually being played (from round_start/languages)
let activeMode = "learn"; // "learn" (stroke hints) or "blind" (audio prompt only)
let statsTabLanguage = "latin"; // which tab the stats screen is showing (independent of the above)
let languages = []; // cached GET /languages response
let modes = []; // cached GET /modes response
let promptAudio = null; // the Audio object for the current Blind-mode prompt

// ---------- screen navigation ----------

function showScreen(name) {
  document.querySelectorAll(".screen").forEach((el) => {
    el.classList.toggle("active", el.id === `screen-${name}`);
  });
  if (name === "stats") refreshStats();
}

document
  .getElementById("play-btn")
  .addEventListener("click", () => showScreen("play"));
document
  .getElementById("stats-nav-btn")
  .addEventListener("click", () => showScreen("stats"));
document.querySelectorAll(".back-btn").forEach((btn) => {
  btn.addEventListener("click", () => showScreen(btn.dataset.back));
});

// ---------- settings modal ----------

document.getElementById("settings-btn").addEventListener("click", () => {
  settingsOverlay.classList.remove("hidden");
});
document.getElementById("settings-close-btn").addEventListener("click", () => {
  settingsOverlay.classList.add("hidden");
});
settingsOverlay.addEventListener("click", (e) => {
  if (e.target === settingsOverlay) settingsOverlay.classList.add("hidden");
});

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  document.querySelectorAll(".theme-option").forEach((btn) => {
    btn.classList.toggle("selected", btn.dataset.theme === theme);
  });
  try {
    localStorage.setItem("theme", theme);
  } catch (e) {
    /* private-browsing or blocked storage: theme just won't persist */
  }
}

document.querySelectorAll(".theme-option").forEach((btn) => {
  btn.addEventListener("click", () => applyTheme(btn.dataset.theme));
});

(function initTheme() {
  let saved = "dark";
  try {
    saved = localStorage.getItem("theme") || "dark";
  } catch (e) {
    /* default to dark */
  }
  applyTheme(saved);
})();

function currentVolume() {
  return Number(audioSlider.value) / 100;
}

function setVolume(value) {
  audioSlider.value = value;
  playAudioSlider.value = value;
  if (promptAudio) promptAudio.volume = currentVolume();
  try {
    localStorage.setItem("audioVolume", value);
  } catch (e) {
    /* not persisted this session */
  }
}

(function initAudioSliders() {
  let saved = 70;
  try {
    const stored = localStorage.getItem("audioVolume");
    if (stored !== null) saved = stored;
  } catch (e) {
    /* use the default */
  }
  setVolume(saved);
  // Two sliders (settings modal + play screen) control the same volume —
  // keep them mirrored so changing either one updates both.
  audioSlider.addEventListener("input", () => setVolume(audioSlider.value));
  playAudioSlider.addEventListener("input", () =>
    setVolume(playAudioSlider.value),
  );
})();

async function loadLanguages() {
  try {
    const res = await fetch("/languages");
    const data = await res.json();
    languages = data.languages;
    activeLanguage = data.active;
    statsTabLanguage = data.active;
    renderLanguageOptions();
    renderLanguageTabs();
  } catch (e) {
    languageOptionsEl.textContent = "unavailable";
  }
}

function renderLanguageOptions() {
  languageOptionsEl.replaceChildren();
  for (const lang of languages) {
    const btn = document.createElement("button");
    btn.className =
      "lang-option" + (lang.code === activeLanguage ? " selected" : "");
    btn.textContent = lang.label;
    if (!lang.enabled) {
      btn.classList.add("locked");
      btn.disabled = true;
      btn.title = "Coming soon";
    } else {
      btn.addEventListener("click", async () => {
        if (lang.code === activeLanguage) return;
        await fetch(`/language/${lang.code}`, { method: "POST" });
        activeLanguage = lang.code;
        renderLanguageOptions();
      });
    }
    languageOptionsEl.appendChild(btn);
  }
}

function renderLanguageTabs() {
  languageTabsEl.replaceChildren();
  for (const lang of languages) {
    const btn = document.createElement("button");
    btn.className = "tab" + (lang.code === statsTabLanguage ? " selected" : "");
    btn.textContent = lang.label;
    btn.addEventListener("click", () => {
      statsTabLanguage = lang.code;
      renderLanguageTabs();
      refreshStats();
    });
    languageTabsEl.appendChild(btn);
  }
}

async function loadModes() {
  try {
    const res = await fetch("/modes");
    const data = await res.json();
    modes = data.modes;
    activeMode = data.active;
    renderModeOptions();
  } catch (e) {
    modeOptionsEl.textContent = "unavailable";
  }
}

function renderModeOptions() {
  modeOptionsEl.replaceChildren();
  for (const mode of modes) {
    const btn = document.createElement("button");
    btn.className =
      "mode-option" + (mode.code === activeMode ? " selected" : "");
    btn.innerHTML = `${mode.label}<small>${mode.description}</small>`;
    if (!mode.enabled) {
      btn.classList.add("locked");
      btn.disabled = true;
      btn.title = "Needs ELEVENLABS_API_KEY configured server-side";
    } else {
      btn.addEventListener("click", async () => {
        if (mode.code === activeMode) return;
        await fetch(`/mode/${mode.code}`, { method: "POST" });
        activeMode = mode.code;
        renderModeOptions();
      });
    }
    modeOptionsEl.appendChild(btn);
  }
}

// ---------- play screen ----------

// Pixels per radian of wand rotation. Fixed, not auto-fit: re-fitting on
// every sample blew tiny movements up to full size. Adjustable live with the
// + / - keys (remembered per browser) so it can be tuned to how someone
// actually holds the wand.
const DEFAULT_PX_PER_RAD = 220;
let cursorPxPerRad = DEFAULT_PX_PER_RAD;
try {
  cursorPxPerRad = Number(localStorage.getItem("cursorPxPerRad")) || DEFAULT_PX_PER_RAD;
} catch {}
// Fraction of the way the displayed cursor moves toward each new reading
// (50 Hz), smoothing out hand tremor and sensor noise at a small lag.
const CURSOR_SMOOTHING = 0.6;
// Disabled: view no longer auto-drifts back to the wand while idle.
// Once you point somewhere, it stays there until you start the next letter.
const RECENTER_RATE = 0;

const cursor = { x: 0, y: 0, pen: false, seen: false }; // smoothed position
const view = { x: 0, y: 0 };
let letterActive = false;
let liveStrokes = []; // one [x, y] list per pen-down run of the current letter

function clearCanvas() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
}

function hideHint() {
  hintImage.classList.add("hidden");
}

function scheduleHint() {
  if (hintTimer) clearTimeout(hintTimer);
  hideHint();
  hintTimer = setTimeout(() => {
    if (currentLetter) {
      hintImage.src = `reference/${encodeURIComponent(currentLetter)}.png`;
      hintImage.classList.remove("hidden");
    }
  }, HINT_TIMEOUT_MS);
}

function playPrompt() {
  if (!currentLetter) return;
  promptAudio = new Audio(
    `/tts/${activeLanguage}/${encodeURIComponent(currentLetter)}`,
  );
  promptAudio.volume = currentVolume();
  promptAudio.play().catch(() => {
    // Autoplay can be blocked before any user gesture on the page — the
    // replay button still works once the player has clicked anything.
  });
}

// Learn mode: delayed stroke-hint image (existing behavior). Blind mode:
// no hint image at all — the audio prompt itself is the only cue, played
// immediately and replayable via the speaker button.
function startPrompt() {
  if (hintTimer) clearTimeout(hintTimer);
  hideHint();
  if (activeMode === "blind") {
    replayAudioBtn.classList.remove("hidden");
    playPrompt();
  } else {
    replayAudioBtn.classList.add("hidden");
    scheduleHint();
  }
}

replayAudioBtn.addEventListener("click", () => {
  if (promptAudio) {
    promptAudio.currentTime = 0;
    promptAudio.play();
  } else {
    playPrompt();
  }
});

function drawPaths(paths) {
  clearCanvas();
  if (!paths || paths.length === 0) return;

  const allPoints = paths.flat();
  const xs = allPoints.map((p) => p[0]);
  const ys = allPoints.map((p) => p[1]);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const spanX = Math.max(maxX - minX, 1e-6);
  const spanY = Math.max(maxY - minY, 1e-6);
  const span = Math.max(spanX, spanY);
  const padding = 40;
  const scale = (canvas.width - padding * 2) / span;

  const toCanvas = ([x, y]) => {
    const cx = canvas.width / 2 + (x - (minX + maxX) / 2) * scale;
    // Flip y: screen y grows downward, our path y grows "up".
    const cy = canvas.height / 2 - (y - (minY + maxY) / 2) * scale;
    return [cx, cy];
  };

  ctx.strokeStyle = "#4fc3f7";
  ctx.lineWidth = 3;
  ctx.lineJoin = "round";
  ctx.lineCap = "round";

  for (const path of paths) {
    ctx.beginPath();
    path.forEach((point, i) => {
      const [cx, cy] = toCanvas(point);
      if (i === 0) ctx.moveTo(cx, cy);
      else ctx.lineTo(cx, cy);
    });
    ctx.stroke();
  }
}

function toCursorCanvas(x, y) {
  return [
    cursorCanvas.width / 2 + (x - view.x) * cursorPxPerRad,
    // Flip y: screen y grows downward, elevation grows up.
    cursorCanvas.height / 2 - (y - view.y) * cursorPxPerRad,
  ];
}

// Overlay above the drawing and the hint image: the current letter's
// pen-down strokes as a dim trail (nothing drawn while the pen is up), plus
// a dot that always follows the wand - faint when idle, bright while drawing.
function drawCursor() {
  const c = cursorCtx;
  c.clearRect(0, 0, cursorCanvas.width, cursorCanvas.height);
  if (!cursor.seen) return;

  c.strokeStyle = "#4fc3f7";
  c.globalAlpha = 0.5;
  c.lineWidth = 3;
  c.lineJoin = "round";
  c.lineCap = "round";
  for (const stroke of liveStrokes) {
    c.beginPath();
    stroke.forEach(([x, y], i) => {
      const [cx, cy] = toCursorCanvas(x, y);
      if (i === 0) c.moveTo(cx, cy);
      else c.lineTo(cx, cy);
    });
    c.stroke();
  }

  // Pin the dot to the edge rather than lose it when pointing off-canvas.
  let [cx, cy] = toCursorCanvas(cursor.x, cursor.y);
  cx = Math.min(Math.max(cx, 6), cursorCanvas.width - 6);
  cy = Math.min(Math.max(cy, 6), cursorCanvas.height - 6);
  c.globalAlpha = cursor.pen ? 0.9 : 0.35;
  c.fillStyle = "#4fc3f7";
  c.beginPath();
  c.arc(cx, cy, cursor.pen ? 6 : 5, 0, Math.PI * 2);
  c.fill();
  c.globalAlpha = 1;
}

function onCursor(msg) {
  if (!cursor.seen) {
    cursor.x = view.x = msg.x;
    cursor.y = view.y = msg.y;
    cursor.seen = true;
  }
  cursor.x += (msg.x - cursor.x) * CURSOR_SMOOTHING;
  cursor.y += (msg.y - cursor.y) * CURSOR_SMOOTHING;
  if (msg.letter_start) {
    letterActive = true;
    liveStrokes = [];
    if (hintTimer) clearTimeout(hintTimer); // don't pop the hint in mid-letter
  }
  if (letterActive && msg.pen) {
    if (!cursor.pen || liveStrokes.length === 0) liveStrokes.push([]);
    liveStrokes[liveStrokes.length - 1].push([cursor.x, cursor.y]);
  }
  if (!letterActive) {
    view.x += (cursor.x - view.x) * RECENTER_RATE;
    view.y += (cursor.y - view.y) * RECENTER_RATE;
  }
  cursor.pen = msg.pen;
  drawCursor();
}

function endLetter() {
  letterActive = false;
  liveStrokes = [];
  drawCursor();
}

function updatePerStrokeScores(scores) {
  perStrokeScoresEl.innerHTML = "";
  if (!scores) return;
  scores.forEach((score, i) => {
    const span = document.createElement("span");
    span.textContent = `#${i + 1}: ${score.toFixed(0)}`;
    span.className = score > 0 ? "pass" : "fail";
    perStrokeScoresEl.appendChild(span);
  });
}

// ---------- stats screen ----------

function scoreColor(score) {
  if (score >= 75) return "#4fc3f7";
  if (score >= 40) return "#ffb74d";
  return "#ef5350";
}

function drawSparkline(cvs, scores) {
  const c = cvs.getContext("2d");
  const w = cvs.width;
  const h = cvs.height;
  c.clearRect(0, 0, w, h);
  if (scores.length === 0) return;
  const barW = w / 10;
  scores.forEach((score, i) => {
    const barH = Math.max(2, (score / 100) * h);
    c.fillStyle = scoreColor(score);
    c.fillRect(i * barW + 1, h - barH, barW - 2, barH);
  });
}

function dueText(l) {
  if (l.status === "new") return "new";
  if (l.due_in <= 0) return "due now";
  return `in ${l.due_in}`;
}

function renderLetters(letters) {
  lettersBody.replaceChildren();
  for (const l of letters) {
    const tr = document.createElement("tr");
    if (l.letter === currentLetter && statsTabLanguage === activeLanguage) {
      tr.classList.add("current");
    }

    const letterTd = document.createElement("td");
    letterTd.className = "letter";
    letterTd.textContent = l.letter;

    const statusTd = document.createElement("td");
    const pill = document.createElement("span");
    pill.className = `pill ${l.status}`;
    pill.textContent = l.status;
    if (l.lapses > 0)
      pill.title = `${l.lapses} lapse${l.lapses > 1 ? "s" : ""}`;
    statusTd.appendChild(pill);

    const sparkTd = document.createElement("td");
    const spark = document.createElement("canvas");
    spark.width = 80;
    spark.height = 22;
    drawSparkline(spark, l.recent);
    sparkTd.appendChild(spark);

    const avgTd = document.createElement("td");
    avgTd.textContent = l.avg_score == null ? "-" : l.avg_score.toFixed(0);

    const dueTd = document.createElement("td");
    dueTd.className = l.status !== "new" && l.due_in <= 0 ? "due" : "";
    dueTd.textContent = dueText(l);

    tr.append(letterTd, statusTd, sparkTd, avgTd, dueTd);
    lettersBody.appendChild(tr);
  }
}

function renderWeakest(letters) {
  const attempted = letters.filter(
    (l) => l.attempts > 0 && l.avg_score != null,
  );
  const weakest = [...attempted]
    .sort((a, b) => a.avg_score - b.avg_score)
    .slice(0, 3);
  weakestCalloutEl.classList.toggle("hidden", weakest.length === 0);
  weakestListEl.textContent = weakest
    .map((l) => `${l.letter} (${l.avg_score.toFixed(0)}%)`)
    .join(", ");
}

function renderTimeline(points) {
  const c = timelineCanvas.getContext("2d");
  const w = timelineCanvas.width;
  const h = timelineCanvas.height;
  c.clearRect(0, 0, w, h);
  timelineEmpty.classList.toggle("hidden", points.length > 0);
  if (points.length === 0) return;

  const pad = { l: 28, r: 8, t: 8, b: 18 };
  const plotW = w - pad.l - pad.r;
  const plotH = h - pad.t - pad.b;
  const maxAttempts = Math.max(...points.map((p) => p.attempts));
  const step = points.length > 1 ? plotW / (points.length - 1) : 0;
  const xAt = (i) => pad.l + (points.length > 1 ? i * step : plotW / 2);
  const yAt = (score) => pad.t + plotH * (1 - score / 100);

  c.strokeStyle = "#333";
  c.fillStyle = "#777";
  c.font = "10px system-ui";
  c.lineWidth = 1;
  for (const v of [0, 50, 100]) {
    c.beginPath();
    c.moveTo(pad.l, yAt(v));
    c.lineTo(w - pad.r, yAt(v));
    c.stroke();
    c.fillText(String(v), 4, yAt(v) + 3);
  }

  // attempts per bucket as faint bars behind the line
  const barW = Math.max(4, Math.min(24, plotW / points.length / 2));
  c.fillStyle = "rgba(79, 195, 247, 0.15)";
  points.forEach((p, i) => {
    const barH = (p.attempts / maxAttempts) * plotH * 0.5;
    c.fillRect(xAt(i) - barW / 2, pad.t + plotH - barH, barW, barH);
  });

  c.strokeStyle = "#4fc3f7";
  c.lineWidth = 2;
  c.beginPath();
  points.forEach((p, i) => {
    if (i === 0) c.moveTo(xAt(i), yAt(p.avg_score));
    else c.lineTo(xAt(i), yAt(p.avg_score));
  });
  c.stroke();
  c.fillStyle = "#4fc3f7";
  points.forEach((p, i) => {
    c.beginPath();
    c.arc(xAt(i), yAt(p.avg_score), 3, 0, Math.PI * 2);
    c.fill();
  });

  const fmt = (iso) =>
    new Date(iso).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    });
  c.fillStyle = "#777";
  c.fillText(fmt(points[0].bucket), pad.l, h - 4);
  if (points.length > 1) {
    const last = fmt(points[points.length - 1].bucket);
    c.fillText(last, w - pad.r - c.measureText(last).width, h - 4);
  }
}

async function refreshStats() {
  try {
    const res = await fetch(`/stats?language=${statsTabLanguage}`);
    const stats = await res.json();
    sourceEl.textContent =
      stats.source === "tiger" ? "Tiger Data" : "offline (local)";
    sourceEl.className = `source ${stats.source}`;
    totalReviewsEl.textContent = stats.total_reviews;
    renderLetters(stats.letters);
    renderWeakest(stats.letters);
    renderTimeline(stats.timeline);
  } catch (e) {
    sourceEl.textContent = "stats unavailable";
  }
}

// ---------- websocket ----------

function connect() {
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${protocol}://${location.host}/ws`);

  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);

    if (msg.type === "round_start") {
      if (resultTimer) clearTimeout(resultTimer);
      canvasWrap.classList.remove("result-pass", "result-fail");
      activeLanguage = msg.language;
      activeMode = msg.mode;
      currentLetter = msg.target_letter;
      targetLetterEl.textContent = msg.target_letter;
      endLetter();
      clearCanvas();
      perStrokeScoresEl.innerHTML = "";
      startPrompt();
    } else if (msg.type === "stroke_result") {
      if (hintTimer) clearTimeout(hintTimer);
      if (resultTimer) clearTimeout(resultTimer);
      hideHint();
      endLetter();
      activeMode = msg.mode;
      accuracyEl.textContent = msg.accuracy.toFixed(1);
      cumulativeScoreEl.textContent = msg.cumulative_score;
      gradeEl.textContent = `${GRADE_LABELS[msg.grade]} · ${msg.letter} back in ${msg.next_review_in}`;
      gradeEl.className = `grade ${msg.grade}`;
      updatePerStrokeScores(msg.per_stroke_scores);
      drawPaths(msg.paths);
      // Hold this result on screen (drawing + pass/fail flag) before moving
      // on - canvasWrap gets "result-pass"/"result-fail" for styling; the
      // banner/hint/canvas only switch to the next letter once this timer
      // fires, so the old drawing is never up during the next attempt.
      canvasWrap.classList.toggle("result-fail", msg.grade === "again");
      canvasWrap.classList.toggle("result-pass", msg.grade !== "again");
      resultTimer = setTimeout(() => {
        canvasWrap.classList.remove("result-pass", "result-fail");
        clearCanvas();
        currentLetter = msg.next_letter;
        targetLetterEl.textContent = msg.next_letter;
        startPrompt();
      }, RESULT_DISPLAY_MS);
    } else if (msg.type === "cursor") {
      onCursor(msg);
    }
  };

  ws.onclose = () => {
    setTimeout(connect, 1000);
  };
}

document.addEventListener("keydown", (e) => {
  if (e.key !== "+" && e.key !== "=" && e.key !== "-") return;
  cursorPxPerRad *= e.key === "-" ? 1 / 1.25 : 1.25;
  cursorPxPerRad = Math.min(Math.max(cursorPxPerRad, 20), 1000);
  try {
    localStorage.setItem("cursorPxPerRad", String(cursorPxPerRad));
  } catch {}
  console.log(`cursor sensitivity: ${Math.round(cursorPxPerRad)} px/rad`);
  drawCursor();
});

nextRoundBtn.addEventListener("click", () => {
  fetch("/round/next", { method: "POST" });
});

resetProgressBtn.addEventListener("click", async () => {
  const label =
    languages.find((l) => l.code === statsTabLanguage)?.label ||
    statsTabLanguage;
  if (!confirm(`Erase all "${label}" learning progress and history?`)) return;
  await fetch(`/progress/reset?language=${statsTabLanguage}`, {
    method: "POST",
  });
  gradeEl.textContent = "";
  accuracyEl.textContent = "-";
  cumulativeScoreEl.textContent = "0";
  refreshStats();
});

loadLanguages();
loadModes();
connect();
