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
let serverSide = 'near';   // which physical side the serving team is on
let isRunning = false;
let _serverLogCount = 0;  // tracks how many server-side log entries we've shown

// --- Setup state (read from UI before Start) ---
let gameMode = 'doubles';
let setupServerSide = 'near';
let setupServerNum = 1;

// --- Bounce overlay ---
let lastBounce = null;          // { result: 'IN'|'OUT', time: ms }
const BOUNCE_DISPLAY_MS = 2500; // how long to show the badge

function updateScoreboard() {
    document.getElementById('servingScore').textContent = String(servingScore).padStart(2, '0');
    document.getElementById('receivingScore').textContent = String(receivingScore).padStart(2, '0');
    document.getElementById('serverNumber').textContent = serverNumber;
    document.getElementById('serverSide').textContent = serverSide;
    // Dynamic team name labels
    const nearName = (document.getElementById('teamNear') || {}).value || 'Team A';
    const farName  = (document.getElementById('teamFar')  || {}).value || 'Team B';
    const servingName  = serverSide === 'near' ? nearName : farName;
    const receivingName = serverSide === 'near' ? farName  : nearName;
    document.getElementById('servingLabel').textContent = servingName + ' (Serving)';
    document.getElementById('receivingLabel').textContent = receivingName + ' (Receiving)';
}

function updateModeUI() {
    var isSingles = gameMode === 'singles';
    document.getElementById('modeBadge').textContent = isSingles ? 'Singles' : 'Doubles';
    document.getElementById('serverNumLabel').style.display = isSingles ? 'none' : '';
    document.getElementById('serverMinus').style.display = isSingles ? 'none' : '';
    document.getElementById('serverPlus').style.display = isSingles ? 'none' : '';
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

// --- Setup toggles ---
function initToggles() {
    document.querySelectorAll('[data-mode]').forEach(function (btn) {
        btn.addEventListener('click', function () {
            document.querySelectorAll('[data-mode]').forEach(function (b) { b.classList.remove('active'); });
            btn.classList.add('active');
            gameMode = btn.dataset.mode;
            updateModeUI();
        });
    });
    document.querySelectorAll('[data-side]').forEach(function (btn) {
        btn.addEventListener('click', function () {
            document.querySelectorAll('[data-side]').forEach(function (b) { b.classList.remove('active'); });
            btn.classList.add('active');
            setupServerSide = btn.dataset.side;
            serverSide = setupServerSide;
            updateScoreboard();
        });
    });
}
initToggles();

// --- Settings modal ---
document.getElementById('settingsBtn').addEventListener('click', function () {
    document.getElementById('settingsModal').classList.add('active');
});
document.getElementById('closeSettings').addEventListener('click', function () {
    document.getElementById('settingsModal').classList.remove('active');
});
document.getElementById('settingsModal').addEventListener('click', function (e) {
    if (e.target === this) this.classList.remove('active');
});

// Update labels when team name inputs change
document.getElementById('teamNear').addEventListener('input', updateScoreboard);
document.getElementById('teamFar').addEventListener('input', updateScoreboard);

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
            body: JSON.stringify({
                source: source,
                server_side: setupServerSide,
                server: setupServerNum,
                mode: gameMode,
                team_near: (document.getElementById('teamNear').value.trim()) || 'Team A',
                team_far:  (document.getElementById('teamFar').value.trim())  || 'Team B',
                serving:   0,
                receiving: 0
            })
        })
        .then(r => r.json())
        .then(data => {
            if (data.status === 'started') {
                isRunning = true;
                _serverLogCount = 0;
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

document.getElementById('matchHistoryBtn').addEventListener('click', function () {
    if (isRunning) {
        fetch('/pause', { method: 'POST' })
            .then(() => { window.location.href = '/matches'; })
            .catch(() => { window.location.href = '/matches'; });
    } else {
        window.location.href = '/matches';
    }
});

document.getElementById('rewindBtn').addEventListener('click', function () {
    if (!isRunning) return;

    fetch('/rewind', { method: 'POST' })
        .then(r => r.json())
        .then(() => {
            addLog('Camera paused for rewind.');
            const pollClip = setInterval(function () {
                fetch('/rewind_status')
                    .then(r => r.json())
                    .then(data => {
                        if (!data.ready) return;
                        clearInterval(pollClip);

                        const live = document.getElementById('liveFeed');
                        // Break the old MJPEG stream by clearing src first
                        live.src = '';
                        // Start fresh rewind stream (timestamp forces new request)
                        live.src = '/rewind_feed?t=' + Date.now();
                        addLog('Rewind: playing last 15 seconds...');
                    });
            }, 300);
        })
        .catch(err => addLog('Rewind failed: ' + err));
});

function switchToLiveFeed() {
    const live = document.getElementById('liveFeed');
    live.src = '/video_feed';
}

// --- Keyboard shortcuts for testing scores ---
// Press 's' to add point to serving team, 'r' for receiving, 'n' to switch server
function postScore(log) {
    fetch('/update_score', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ serving: servingScore, receiving: receivingScore, server: serverNumber, log })
    }).catch(() => {});
}

// --- Score adjustment buttons ---
document.getElementById('servingPlus').addEventListener('click', function () {
    servingScore++;
    updateScoreboard();
    const msg = 'Manual +1 Server. Score ' + servingScore + '-' + receivingScore + '-' + serverNumber;
    addLog(msg);
    postScore(msg);
});
document.getElementById('servingMinus').addEventListener('click', function () {
    if (servingScore <= 0) return;
    servingScore--;
    updateScoreboard();
    const msg = 'Manual -1 Server. Score ' + servingScore + '-' + receivingScore + '-' + serverNumber;
    addLog(msg);
    postScore(msg);
});
document.getElementById('receivingPlus').addEventListener('click', function () {
    receivingScore++;
    updateScoreboard();
    const msg = 'Manual +1 Receiver. Score ' + servingScore + '-' + receivingScore + '-' + serverNumber;
    addLog(msg);
    postScore(msg);
});
document.getElementById('receivingMinus').addEventListener('click', function () {
    if (receivingScore <= 0) return;
    receivingScore--;
    updateScoreboard();
    const msg = 'Manual -1 Receiver. Score ' + servingScore + '-' + receivingScore + '-' + serverNumber;
    addLog(msg);
    postScore(msg);
});

// --- Server number adjustment buttons ---
document.getElementById('serverPlus').addEventListener('click', function () {
    serverNumber = serverNumber === 1 ? 2 : 1;
    updateScoreboard();
    const msg = 'Manual switch Server #' + serverNumber;
    addLog(msg);
    postScore(msg);
});
document.getElementById('serverMinus').addEventListener('click', function () {
    serverNumber = serverNumber === 1 ? 2 : 1;
    updateScoreboard();
    const msg = 'Manual switch Server #' + serverNumber;
    addLog(msg);
    postScore(msg);
});

document.addEventListener('keydown', function (e) {
    if (!isRunning) return;

    if (e.key === 's') {
        servingScore++;
        updateScoreboard();
        const msg = 'Point Server. Score ' + servingScore + '-' + receivingScore + '-' + serverNumber;
        addLog(msg);
        postScore(msg);
    }
    if (e.key === 'r') {
        receivingScore++;
        updateScoreboard();
        const msg = 'Point Receiver. Score ' + servingScore + '-' + receivingScore + '-' + serverNumber;
        addLog(msg);
        postScore(msg);
    }
    if (e.key === 'n') {
        serverNumber = serverNumber === 1 ? 2 : 1;
        updateScoreboard();
        const msg = 'Switch Server #' + serverNumber;
        addLog(msg);
        postScore(msg);
    }
    if (e.key === 'x') {
        fetch('/swap_side', { method: 'POST' })
            .then(r => r.json())
            .then(data => {
                serverSide = data.server_side;
                updateScoreboard();
                addLog('Swapped server side to ' + serverSide);
            })
            .catch(() => {});
    }
});

// --- Live Stats ---
function updateLiveStats(data) {
    document.getElementById('statTotalPts').textContent = servingScore + receivingScore;

    // Count side outs from log entries
    var sideOuts = 0;
    data.log.forEach(function (msg) {
        if (msg.toLowerCase().indexOf('side') !== -1 && msg.toLowerCase().indexOf('out') !== -1) sideOuts++;
    });
    document.getElementById('statSideOuts').textContent = sideOuts;

    // Count bounces by result
    var inCount = 0, outCount = 0, serveCount = 0;
    courtBounces.forEach(function (b) {
        if (b.result === 'IN') inCount++;
        else if (b.result === 'OUT') outCount++;
        else if (b.result === 'SERVE') serveCount++;
    });
    document.getElementById('statIn').textContent = inCount;
    document.getElementById('statOut').textContent = outCount;
    document.getElementById('statServe').textContent = serveCount;
}

// --- Poll Flask /score every second ---
function pollScore() {
    fetch('/score')
        .then(r => r.json())
        .then(data => {
            servingScore   = data.serving;
            receivingScore = data.receiving;
            serverNumber   = data.server;
            serverSide     = data.server_side || serverSide;
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
            } else if (data.status === 'shutdown') {
                window.close();
            }

            // Append new server-side log entries
            // If server trimmed the log (length shrank), reset our pointer
            if (data.log.length < _serverLogCount) {
                _serverLogCount = data.log.length;
            }
            data.log.slice(_serverLogCount).forEach(msg => {
                addLog(msg);
                _serverLogCount++;
            });

            // Sync bounce markers for court view
            courtBounces = data.bounces || [];
            drawCourtView();
            updateLiveStats(data);
        })
        .catch(() => {}); // silently ignore if server not running
}
setInterval(pollScore, 1000);

// --- Top-Down Court View ---
const courtCanvas = document.getElementById('courtViewCanvas');
const courtCtx = courtCanvas.getContext('2d');
let courtBounces = [];       // synced from score_state.bounces
let currentBallCourt = null; // {x, y} in cm, from SSE detections

// Court dimensions in cm
const CW = 609.6, CL = 1341.12, NET_Y = 670.56;
const KITCHEN_NEAR = 457.2, KITCHEN_FAR = 883.92, CENTER_X = 304.8;

function drawCourtView() {
    const parent = courtCanvas.parentElement;
    const W = courtCanvas.width = parent.clientWidth || 200;
    const H = courtCanvas.height = parent.clientHeight || 200;

    // Scale court to fit canvas with margin
    const margin = 10;
    const scaleX = (W - margin * 2) / CW;
    const scaleY = (H - margin * 2) / CL;
    const sc = Math.min(scaleX, scaleY);
    const ox = (W - CW * sc) / 2;
    const oy = (H - CL * sc) / 2;

    function c2c(cx, cy) { return [ox + cx * sc, oy + cy * sc]; }

    // Background
    courtCtx.fillStyle = '#2e7d32';
    courtCtx.fillRect(0, 0, W, H);

    // Court surface
    var tl = c2c(0, 0);
    courtCtx.fillStyle = '#388e3c';
    courtCtx.fillRect(tl[0], tl[1], CW * sc, CL * sc);

    // Draw lines helper
    function drawLine(x1, y1, x2, y2, color, width) {
        var a = c2c(x1, y1), b = c2c(x2, y2);
        courtCtx.strokeStyle = color || '#fff';
        courtCtx.lineWidth = width || 2;
        courtCtx.beginPath();
        courtCtx.moveTo(a[0], a[1]);
        courtCtx.lineTo(b[0], b[1]);
        courtCtx.stroke();
    }

    // Court boundary
    drawLine(0, 0, CW, 0);       // top baseline
    drawLine(0, CL, CW, CL);     // bottom baseline
    drawLine(0, 0, 0, CL);       // left sideline
    drawLine(CW, 0, CW, CL);     // right sideline

    // Kitchen lines
    drawLine(0, KITCHEN_NEAR, CW, KITCHEN_NEAR);
    drawLine(0, KITCHEN_FAR, CW, KITCHEN_FAR);

    // Net (thicker)
    drawLine(0, NET_Y, CW, NET_Y, '#ddd', 3);

    // Center service lines
    drawLine(CENTER_X, 0, CENTER_X, KITCHEN_NEAR);
    drawLine(CENTER_X, KITCHEN_FAR, CENTER_X, CL);

    // Zone labels
    courtCtx.fillStyle = 'rgba(255,255,255,0.5)';
    courtCtx.font = 'bold ' + Math.max(10, 14 * sc) + 'px sans-serif';
    courtCtx.textAlign = 'center';
    courtCtx.textBaseline = 'middle';
    var labels = [
        ['L Service', CENTER_X / 2, KITCHEN_NEAR / 2],
        ['R Service', CENTER_X + CENTER_X / 2, KITCHEN_NEAR / 2],
        ['Kitchen', CENTER_X, (KITCHEN_NEAR + NET_Y) / 2],
        ['Kitchen', CENTER_X, (NET_Y + KITCHEN_FAR) / 2],
        ['L Service', CENTER_X / 2, (KITCHEN_FAR + CL) / 2],
        ['R Service', CENTER_X + CENTER_X / 2, (KITCHEN_FAR + CL) / 2],
    ];
    for (var i = 0; i < labels.length; i++) {
        var p = c2c(labels[i][1], labels[i][2]);
        courtCtx.fillText(labels[i][0], p[0], p[1]);
    }

    // Bounce and serve markers
    for (var j = 0; j < courtBounces.length; j++) {
        var b = courtBounces[j];
        var bp = c2c(b.court_x, b.court_y);
        if (b.result === 'SERVE') {
            // Serve marker: triangle
            courtCtx.beginPath();
            courtCtx.moveTo(bp[0], bp[1] - 7);
            courtCtx.lineTo(bp[0] - 6, bp[1] + 5);
            courtCtx.lineTo(bp[0] + 6, bp[1] + 5);
            courtCtx.closePath();
            courtCtx.fillStyle = '#42a5f5';
            courtCtx.fill();
            courtCtx.strokeStyle = '#fff';
            courtCtx.lineWidth = 1;
            courtCtx.stroke();
        } else {
            courtCtx.beginPath();
            courtCtx.arc(bp[0], bp[1], 5, 0, Math.PI * 2);
            courtCtx.fillStyle = b.result === 'IN' ? '#66bb6a' : '#ef5350';
            courtCtx.fill();
            courtCtx.strokeStyle = '#fff';
            courtCtx.lineWidth = 1;
            courtCtx.stroke();
        }
    }

    // Current ball position
    if (currentBallCourt) {
        var bp2 = c2c(currentBallCourt.x, currentBallCourt.y);
        courtCtx.beginPath();
        courtCtx.arc(bp2[0], bp2[1], 7, 0, Math.PI * 2);
        courtCtx.fillStyle = '#ffeb3b';
        courtCtx.fill();
        courtCtx.strokeStyle = '#333';
        courtCtx.lineWidth = 2;
        courtCtx.stroke();
    }
}

// Initial draw
drawCourtView();

// --- Detection overlay via Server-Sent Events (SSE) ---
const canvas = document.getElementById('overlayCanvas');
const ctx = canvas.getContext('2d');

// SSE connection — stays open, auto-reconnects
const detSource = new EventSource('/detections');
detSource.onmessage = function (e) {
    if (!isRunning) {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        currentBallCourt = null;
        drawCourtView();
        return;
    }
    var data = JSON.parse(e.data);
    drawOverlay(data);

    // Update ball position on court view
    if (data.detections.length > 0 && data.detections[0].court_x !== undefined) {
        currentBallCourt = { x: data.detections[0].court_x, y: data.detections[0].court_y };
    } else {
        currentBallCourt = null;
    }
    drawCourtView();
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

        // Color: green for YOLO, orange for Kalman prediction
        const isKalman = det.source === 'Kalman';
        const color = isKalman ? '#ff8800' : '#00ff00';

        // Box
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        if (isKalman) {
            ctx.setLineDash([4, 4]);  // dashed box for predictions
        }
        ctx.strokeRect(x1, y1, bw, bh);
        ctx.setLineDash([]);

        // Center dot
        const cx = det.cx * scale + offsetX;
        const cy = det.cy * scale + offsetY;
        ctx.beginPath();
        ctx.arc(cx, cy, 4, 0, Math.PI * 2);
        ctx.fillStyle = color;
        ctx.fill();

        // Label: source + track ID + confidence
        const srcTag = isKalman ? 'KF ' : '';
        const idStr = det.id !== undefined ? '#' + det.id + ' ' : '';
        const label = srcTag + idStr + (det.conf * 100).toFixed(0) + '%';
        ctx.font = 'bold 13px monospace';
        const tw = ctx.measureText(label).width;
        ctx.fillStyle = 'rgba(0,0,0,0.6)';
        ctx.fillRect(x1, y1 - 18, tw + 8, 18);
        ctx.fillStyle = color;
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

    // --- Bounce IN / OUT badge ---
    if (lastBounce) {
        const age = Date.now() - lastBounce.time;
        if (age < BOUNCE_DISPLAY_MS) {
            // Fade out over the last 800 ms
            const alpha = age > BOUNCE_DISPLAY_MS - 800
                ? 1 - (age - (BOUNCE_DISPLAY_MS - 800)) / 800
                : 1;

            const text  = lastBounce.result;                          // 'IN', 'OUT', or 'SERVE'
            const color = lastBounce.result === 'IN' ? '#ffeb3b'
                        : lastBounce.result === 'SERVE' ? '#42a5f5' : '#ef5350';

            ctx.save();
            ctx.globalAlpha = alpha;
            ctx.font = 'bold 80px monospace';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';

            const tw = ctx.measureText(text).width;
            const bx = w / 2 - tw / 2 - 18;
            const by = h / 2 - 50;
            ctx.fillStyle = 'rgba(0,0,0,0.55)';
            ctx.fillRect(bx, by, tw + 36, 90);

            ctx.fillStyle = color;
            ctx.fillText(text, w / 2, h / 2);
            ctx.restore();
        } else {
            lastBounce = null;  // expired — clear so it stops drawing
        }
    }
}

// --- Calibration Modal ---
(function () {
    const LABELS = ['TL', 'TR', 'BR', 'BL', 'Net-L', 'Net-R'];
    const COLORS = ['#00ff00', '#00ff00', '#00ff00', '#00ff00', '#ffeb3b', '#ffeb3b'];
    let calibPoints = [];
    let calibImg = null;

    const modal = document.getElementById('calibrateModal');
    const cvs = document.getElementById('calibrateCanvas');
    const cCtx = cvs.getContext('2d');
    const statusEl = document.getElementById('calibrateStatus');

    function updateStatus() {
        if (!calibImg) {
            statusEl.textContent = 'Click "Capture" to grab a frame';
        } else if (calibPoints.length < 6) {
            statusEl.textContent = 'Click point ' + (calibPoints.length + 1) + '/6: ' + LABELS[calibPoints.length];
        } else {
            statusEl.textContent = 'All 6 points set. Click "Save" to confirm.';
        }
        document.getElementById('calibrateSave').disabled = calibPoints.length < 6;
    }

    function drawCalibration() {
        if (!calibImg) return;
        cCtx.drawImage(calibImg, 0, 0, cvs.width, cvs.height);

        var scaleX = cvs.width / calibImg.naturalWidth;
        var scaleY = cvs.height / calibImg.naturalHeight;

        for (var i = 0; i < calibPoints.length; i++) {
            var px = calibPoints[i][0] * scaleX;
            var py = calibPoints[i][1] * scaleY;
            // dot
            cCtx.beginPath();
            cCtx.arc(px, py, 12, 0, Math.PI * 2);
            cCtx.fillStyle = COLORS[i];
            cCtx.fill();
            cCtx.strokeStyle = '#000';
            cCtx.lineWidth = 3;
            cCtx.stroke();
            // label
            cCtx.font = 'bold 22px monospace';
            cCtx.fillStyle = COLORS[i];
            cCtx.strokeStyle = '#000';
            cCtx.lineWidth = 3;
            cCtx.strokeText(LABELS[i], px + 16, py - 16);
            cCtx.fillText(LABELS[i], px + 16, py - 16);
        }
        // Court outline
        if (calibPoints.length >= 4) {
            cCtx.strokeStyle = '#00ff00';
            cCtx.lineWidth = 3;
            cCtx.beginPath();
            for (var j = 0; j < 4; j++) {
                var x = calibPoints[j][0] * scaleX;
                var y = calibPoints[j][1] * scaleY;
                if (j === 0) cCtx.moveTo(x, y);
                else cCtx.lineTo(x, y);
            }
            cCtx.closePath();
            cCtx.stroke();
        }
        // Net line
        if (calibPoints.length >= 6) {
            cCtx.strokeStyle = '#ffeb3b';
            cCtx.lineWidth = 3;
            cCtx.beginPath();
            cCtx.moveTo(calibPoints[4][0] * scaleX, calibPoints[4][1] * scaleY);
            cCtx.lineTo(calibPoints[5][0] * scaleX, calibPoints[5][1] * scaleY);
            cCtx.stroke();
        }
    }

    // Canvas click — record point in original image coordinates
    cvs.addEventListener('click', function (e) {
        if (!calibImg || calibPoints.length >= 6) return;
        var rect = cvs.getBoundingClientRect();
        var clickX = e.clientX - rect.left;
        var clickY = e.clientY - rect.top;
        // Convert from display size to canvas backing store
        var canvasX = clickX * (cvs.width / rect.width);
        var canvasY = clickY * (cvs.height / rect.height);
        // Convert to original image coordinates
        var origX = canvasX / cvs.width * calibImg.naturalWidth;
        var origY = canvasY / cvs.height * calibImg.naturalHeight;
        calibPoints.push([Math.round(origX), Math.round(origY)]);
        drawCalibration();
        updateStatus();
    });

    // Open modal
    document.getElementById('calibrateBtn').addEventListener('click', function () {
        modal.classList.add('active');
        calibPoints = [];
        calibImg = null;
        cCtx.clearRect(0, 0, cvs.width, cvs.height);
        updateStatus();
        // Auto-load existing calibration status
        fetch('/calibrate/load').then(function (r) { return r.json(); }).then(function (data) {
            if (data.exists) {
                statusEl.textContent = 'Existing calibration found. Capture a new frame to recalibrate.';
            }
        }).catch(function () {});
    });

    // Close modal
    document.getElementById('closeCalibrate').addEventListener('click', function () {
        modal.classList.remove('active');
    });
    modal.addEventListener('click', function (e) {
        if (e.target === modal) modal.classList.remove('active');
    });

    // Capture frame
    document.getElementById('calibrateCapture').addEventListener('click', function () {
        statusEl.textContent = 'Capturing frame...';
        var img = new Image();
        img.crossOrigin = 'anonymous';
        img.onload = function () {
            calibImg = img;
            calibPoints = [];
            cvs.width = img.naturalWidth;
            cvs.height = img.naturalHeight;
            drawCalibration();
            updateStatus();
        };
        img.onerror = function () {
            statusEl.textContent = 'Failed to capture frame. Is the feed running?';
        };
        img.src = '/calibrate/frame?t=' + Date.now();
    });

    // Reset points
    document.getElementById('calibrateReset').addEventListener('click', function () {
        calibPoints = [];
        drawCalibration();
        updateStatus();
    });

    // Save calibration
    document.getElementById('calibrateSave').addEventListener('click', function () {
        if (calibPoints.length < 6) return;
        var payload = {
            corners: calibPoints.slice(0, 4),
            net: calibPoints.slice(4, 6)
        };
        fetch('/calibrate/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            if (data.status === 'saved') {
                statusEl.textContent = 'Calibration saved!';
                addLog('Court calibration updated from browser.');
                setTimeout(function () { modal.classList.remove('active'); }, 1000);
            } else {
                statusEl.textContent = 'Error: ' + (data.error || 'Unknown');
            }
        })
        .catch(function (err) {
            statusEl.textContent = 'Save failed: ' + err;
        });
    });
})();

// Initialize
updateScoreboard();