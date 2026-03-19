// --- Clock ---
function updateClock() {
    const now = new Date();
    let hours = now.getHours();
    const minutes = String(now.getMinutes()).padStart(2, '0');
    const ampm = hours >= 12 ? 'pm' : 'am';
    hours = hours % 12 || 12;
    document.getElementById('clock').textContent = hours + ':' + minutes + ampm;
}
updateClock();
setInterval(updateClock, 1000);

// --- Scoreboard State ---
let servingScore = 0;
let receivingScore = 0;
let serverNumber = 1;
let isRunning = false;
let _serverLogCount = 0;  // tracks how many server-side log entries we've shown

function updateScoreboard() {
    document.getElementById('servingScore').textContent = String(servingScore).padStart(2, '0');
    document.getElementById('receivingScore').textContent = String(receivingScore).padStart(2, '0');
    document.getElementById('serverNumber').textContent = serverNumber;
}

// --- Log ---
function addLog(message) {
    const logBox = document.getElementById('logBox');
    const entry = document.createElement('div');
    entry.className = 'log-entry';
    entry.textContent = '> ' + message;
    logBox.appendChild(entry);
    logBox.scrollTop = logBox.scrollHeight;
}

// --- Controls ---
document.getElementById('startBtn').addEventListener('click', function () {
    if (isRunning) return;
    const statusText = document.getElementById('status').textContent;
    const isPaused = statusText.includes('Paused');

    if (isPaused) {
        // Resume paused pipeline
        fetch('/resume', { method: 'POST' })
            .then(r => r.json())
            .then(() => { switchToLiveFeed(); addLog('Resumed.'); })
            .catch(err => addLog('Resume failed: ' + err));
    } else {
        // Fresh start
        let source = document.getElementById('sourceInput').value.trim();
        if (source === '' || source === '0') source = 0;
        fetch('/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ source: source })
        })
        .then(r => r.json())
        .then(data => {
            if (data.status === 'started') {
                isRunning = true;
                switchToLiveFeed();
                addLog('System starting with source: ' + (source === 0 ? 'webcam' : source));
            } else {
                addLog('Start failed: ' + (data.error || 'Unknown error'));
            }
        })
        .catch(err => addLog('Start failed: ' + err));
    }
});

document.getElementById('stopBtn').addEventListener('click', function () {
    if (!isRunning) return;
    fetch('/pause', { method: 'POST' })
        .then(r => r.json())
        .then(() => addLog('Camera paused.'))
        .catch(err => addLog('Pause failed: ' + err));
});

document.getElementById('rewindBtn').addEventListener('click', function () {
    if (!isRunning) return;
    fetch('/pause', { method: 'POST' })
        .then(r => r.json())
        .then(() => addLog('Camera paused.'))
        .catch(err => addLog('Pause failed: ' + err));

    fetch('/score')
        .then(r => r.json())
        .then(data => {
            const src = data.source;
            if (!src) { addLog('Rewind: no file source (webcam mode).'); return; }

            const currentTimeSec = data.frame_pos / data.fps;
            const REWIND_SEC = 10;
            const seekTo = Math.max(0, currentTimeSec - REWIND_SEC);

            const live = document.getElementById('liveFeed');
            const rewind = document.getElementById('rewindFeed');
            rewind.src = '/' + src.replace(/\\/g, '/');
            live.style.display = 'none';
            rewind.style.display = 'block';

            rewind.onloadedmetadata = function () {
                rewind.currentTime = seekTo;
                rewind.play();
            };

            addLog('Rewind: seeking to ' + seekTo.toFixed(1) + 's (current: ' + currentTimeSec.toFixed(1) + 's)');
        });
});

function switchToLiveFeed() {
    const live = document.getElementById('liveFeed');
    const rewind = document.getElementById('rewindFeed');
    rewind.pause();
    rewind.style.display = 'none';
    live.style.display = 'block';
}

// --- Keyboard shortcuts for testing scores ---
// Press 's' to add point to serving team, 'r' for receiving, 'n' to switch server
document.addEventListener('keydown', function (e) {
    if (!isRunning) return;

    if (e.key === 's') {
        servingScore++;
        updateScoreboard();
        addLog('Point Server. Score ' + servingScore + '-' + receivingScore + '-' + serverNumber);
    }
    if (e.key === 'r') {
        receivingScore++;
        updateScoreboard();
        addLog('Point Receiver. Score ' + servingScore + '-' + receivingScore + '-' + serverNumber);
    }
    if (e.key === 'n') {
        serverNumber = serverNumber === 1 ? 2 : 1;
        updateScoreboard();
        addLog('Switch Sides (Left/Right)');
    }
});

// --- Poll Flask /score every second ---
function pollScore() {
    fetch('/score')
        .then(r => r.json())
        .then(data => {
            servingScore   = data.serving;
            receivingScore = data.receiving;
            serverNumber   = data.server;
            updateScoreboard();

            // Sync status
            const statusEl = document.getElementById('status');
            if (data.status === 'live') {
                isRunning = true;
                statusEl.textContent = '(Status: Live)';
                statusEl.classList.add('live');
            } else if (data.status === 'paused') {
                isRunning = false;
                statusEl.textContent = '(Status: Paused)';
                statusEl.classList.remove('live');
            } else if (data.status === 'stopped') {
                isRunning = false;
                statusEl.textContent = '(Status: Stopped)';
                statusEl.classList.remove('live');
            }

            // Append new server-side log entries (tracked separately from JS-only addLog calls)
            data.log.slice(_serverLogCount).forEach(msg => {
                addLog(msg);
                _serverLogCount++;
            });
        })
        .catch(() => {}); // silently ignore if server not running
}
setInterval(pollScore, 1000);

// --- Detection overlay via Server-Sent Events (SSE) ---
const canvas = document.getElementById('overlayCanvas');
const ctx = canvas.getContext('2d');

// SSE connection — stays open, auto-reconnects
const detSource = new EventSource('/detections');
detSource.onmessage = function (e) {
    if (!isRunning) {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        return;
    }
    drawOverlay(JSON.parse(e.data));
};

function drawOverlay(data) {
    const img = document.getElementById('liveFeed');
    const rect = img.getBoundingClientRect();

    // Resize canvas backing store to match displayed size (only when changed)
    const w = Math.round(rect.width);
    const h = Math.round(rect.height);
    if (canvas.width !== w || canvas.height !== h) {
        canvas.width = w;
        canvas.height = h;
    }

    // Scale + offset for object-fit:contain letterboxing
    const scaleX = w / data.frame_w;
    const scaleY = h / data.frame_h;
    const scale = Math.min(scaleX, scaleY);
    const offsetX = (w - data.frame_w * scale) / 2;
    const offsetY = (h - data.frame_h * scale) / 2;

    ctx.clearRect(0, 0, w, h);

    // --- Draw bounding boxes ---
    for (const det of data.detections) {
        const x1 = det.x1 * scale + offsetX;
        const y1 = det.y1 * scale + offsetY;
        const bw = (det.x2 - det.x1) * scale;
        const bh = (det.y2 - det.y1) * scale;

        // Box
        ctx.strokeStyle = '#00ff00';
        ctx.lineWidth = 2;
        ctx.strokeRect(x1, y1, bw, bh);

        // Center dot
        const cx = det.cx * scale + offsetX;
        const cy = det.cy * scale + offsetY;
        ctx.beginPath();
        ctx.arc(cx, cy, 4, 0, Math.PI * 2);
        ctx.fillStyle = '#00ff00';
        ctx.fill();

        // Label: track ID + confidence
        const idStr = det.id !== undefined ? '#' + det.id + ' ' : '';
        const label = idStr + (det.conf * 100).toFixed(0) + '%';
        ctx.font = 'bold 13px monospace';
        const tw = ctx.measureText(label).width;
        ctx.fillStyle = 'rgba(0,0,0,0.6)';
        ctx.fillRect(x1, y1 - 18, tw + 8, 18);
        ctx.fillStyle = '#00ff00';
        ctx.fillText(label, x1 + 4, y1 - 4);
    }

    // --- Draw court polygon ---
    if (data.court && data.court.length > 0) {
        ctx.strokeStyle = '#00ff00';
        ctx.lineWidth = 2;
        ctx.setLineDash([6, 4]);
        ctx.beginPath();
        data.court.forEach(function (pt, i) {
            const x = pt[0] * scale + offsetX;
            const y = pt[1] * scale + offsetY;
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        });
        ctx.closePath();
        ctx.stroke();
        ctx.setLineDash([]);
    }

    // --- FPS badge ---
    if (data.fps) {
        const fpsText = 'YOLO: ' + data.fps.toFixed(1) + ' fps';
        ctx.font = 'bold 16px monospace';
        const ftw = ctx.measureText(fpsText).width;
        ctx.fillStyle = 'rgba(0,0,0,0.6)';
        ctx.fillRect(8, 8, ftw + 12, 24);
        ctx.fillStyle = '#00ff00';
        ctx.fillText(fpsText, 14, 26);
    }
}

// Initialize
updateScoreboard();
