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
            .then(() => addLog('Resumed.'))
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
    addLog('Rewind requested.');
});

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

            // Append new log entries
            const logBox = document.getElementById('logBox');
            const currentCount = logBox.children.length;
            data.log.slice(currentCount).forEach(msg => addLog(msg));
        })
        .catch(() => {}); // silently ignore if server not running
}
setInterval(pollScore, 1000);

// Initialize
updateScoreboard();
