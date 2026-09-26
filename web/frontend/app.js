const targetLetterEl = document.getElementById("target-letter");
const accuracyEl = document.getElementById("accuracy");
const cumulativeScoreEl = document.getElementById("cumulative-score");
const nextRoundBtn = document.getElementById("next-round-btn");
const canvas = document.getElementById("canvas");
const ctx = canvas.getContext("2d");
const hintImage = document.getElementById("hint-image");
const perStrokeScoresEl = document.getElementById("per-stroke-scores");

const HINT_TIMEOUT_MS = 5000;
let hintTimer = null;
let currentLetter = null;

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
      clearCanvas();
      perStrokeScoresEl.innerHTML = "";
      scheduleHint();
    } else if (msg.type === "stroke_result") {
      if (hintTimer) clearTimeout(hintTimer);
      hideHint();
      accuracyEl.textContent = msg.accuracy.toFixed(1);
      cumulativeScoreEl.textContent = msg.cumulative_score;
      currentLetter = msg.next_letter;
      targetLetterEl.textContent = msg.next_letter;
      updatePerStrokeScores(msg.per_stroke_scores);
      drawPaths(msg.paths);
      scheduleHint();
    }
  };

  ws.onclose = () => {
    setTimeout(connect, 1000);
  };
}

nextRoundBtn.addEventListener("click", () => {
  fetch("/round/next", { method: "POST" });
});

connect();
