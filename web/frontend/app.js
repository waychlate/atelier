const targetLetterEl = document.getElementById("target-letter");
const accuracyEl = document.getElementById("accuracy");
const cumulativeScoreEl = document.getElementById("cumulative-score");
const nextRoundBtn = document.getElementById("next-round-btn");
const canvas = document.getElementById("canvas");
const ctx = canvas.getContext("2d");

function clearCanvas() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
}

// `strokes` is a list of strokes, each a list of [x, y] points (pen-up gaps
// between strokes are already dropped server-side — see trajectory.py).
function drawPath(strokes) {
  clearCanvas();
  if (!strokes || strokes.length === 0) return;

  const allPoints = strokes.flat();
  if (allPoints.length === 0) return;

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

  // Separate beginPath()/stroke() per stroke so the pen-up jump between
  // strokes never draws a connecting line.
  strokes.forEach((stroke) => {
    if (stroke.length === 0) return;
    ctx.beginPath();
    stroke.forEach((point, i) => {
      const [cx, cy] = toCanvas(point);
      if (i === 0) ctx.moveTo(cx, cy);
      else ctx.lineTo(cx, cy);
    });
    ctx.stroke();
  });
}

function connect() {
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${protocol}://${location.host}/ws`);

  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);

    if (msg.type === "round_start") {
      targetLetterEl.textContent = msg.target_letter;
      clearCanvas();
    } else if (msg.type === "stroke_result") {
      accuracyEl.textContent = msg.accuracy.toFixed(1);
      cumulativeScoreEl.textContent = msg.cumulative_score;
      targetLetterEl.textContent = msg.next_letter;
      drawPath(msg.path);
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
