const targetLetterEl = document.getElementById("target-letter");
const accuracyEl = document.getElementById("accuracy");
const cumulativeScoreEl = document.getElementById("cumulative-score");
const nextRoundBtn = document.getElementById("next-round-btn");
const canvas = document.getElementById("canvas");
const ctx = canvas.getContext("2d");
const hintImage = document.getElementById("hint-image");
const cursorCanvas = document.getElementById("cursor-canvas");
const cursorCtx = cursorCanvas.getContext("2d");
const perStrokeScoresEl = document.getElementById("per-stroke-scores");

const HINT_TIMEOUT_MS = 5000;
let hintTimer = null;
let currentLetter = null;

// Pixels per radian of wand rotation. Fixed, not auto-fit: re-fitting on
// every sample blew tiny movements up to full size. Adjustable live with the
// + / - keys (remembered per browser) so it can be tuned to how someone
// actually holds the wand.
const DEFAULT_PX_PER_RAD = 90;
let cursorPxPerRad = DEFAULT_PX_PER_RAD;
try {
  cursorPxPerRad = Number(localStorage.getItem("cursorPxPerRad")) || DEFAULT_PX_PER_RAD;
} catch {}
// Fraction of the way the displayed cursor moves toward each new reading
// (50 Hz), smoothing out hand tremor and sensor noise at a small lag.
const CURSOR_SMOOTHING = 0.3;
// While no letter is in progress, the view slowly re-centers on the wand
// (this fraction of the remaining distance per 50 Hz sample, ~1 s to
// settle), so wherever you point becomes the middle and slow gyro heading
// drift never walks the cursor off screen. Frozen during a letter so
// strokes keep their positions relative to each other.
const RECENTER_RATE = 0.04;

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
      hintImage.src = `reference/${currentLetter}.png`;
      hintImage.classList.remove("hidden");
    }
  }, HINT_TIMEOUT_MS);
}

function pathTransform(points, padding = 40) {
  const xs = points.map((p) => p[0]);
  const ys = points.map((p) => p[1]);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const span = Math.max(maxX - minX, maxY - minY, 1e-6);
  const scale = (canvas.width - padding * 2) / span;

  return ([x, y]) => [
    canvas.width / 2 + (x - (minX + maxX) / 2) * scale,
    // Flip y: screen y grows downward, our path y grows "up".
    canvas.height / 2 - (y - (minY + maxY) / 2) * scale,
  ];
}

function drawPaths(paths) {
  clearCanvas();
  if (!paths || paths.length === 0) return;
  const toCanvas = pathTransform(paths.flat());

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

function connect() {
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${protocol}://${location.host}/ws`);

  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);

    if (msg.type === "round_start") {
      currentLetter = msg.target_letter;
      targetLetterEl.textContent = msg.target_letter;
      endLetter();
      clearCanvas();
      perStrokeScoresEl.innerHTML = "";
      scheduleHint();
    } else if (msg.type === "stroke_result") {
      if (hintTimer) clearTimeout(hintTimer);
      hideHint();
      endLetter();
      accuracyEl.textContent = msg.accuracy.toFixed(1);
      cumulativeScoreEl.textContent = msg.cumulative_score;
      currentLetter = msg.next_letter;
      targetLetterEl.textContent = msg.next_letter;
      updatePerStrokeScores(msg.per_stroke_scores);
      drawPaths(msg.paths);
      scheduleHint();
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

connect();
