const MATCH_ID = parseInt(document.querySelector('meta[name="match-id"]').content, 10);

// Clock
function updateClock() {
    const now = new Date();
    let h = now.getHours(), m = String(now.getMinutes()).padStart(2,'0');
    const ap = h >= 12 ? 'pm' : 'am';
    h = h % 12 || 12;
    document.getElementById('clock').textContent = h + ':' + m + ap;
}
updateClock(); setInterval(updateClock, 1000);

document.getElementById('matchId').textContent = MATCH_ID;

function fmtDuration(seconds) {
    if (!seconds || seconds <= 0) return '—';
    return Math.floor(seconds / 60) + 'm ' + Math.floor(seconds % 60) + 's';
}

// --- Court bounce map (top-down, same as live dashboard) ---
// Court dimensions in cm
const CW = 609.6, CL = 1341.12, NET_Y = 670.56;
const KITCHEN_NEAR = 457.2, KITCHEN_FAR = 883.92, CENTER_X = 304.8;

function drawCourtMap(courtPoly, bounces) {
    const canvas = document.getElementById('courtCanvas');
    const ctx = canvas.getContext('2d');
    const W = canvas.offsetWidth || 500;
    const maxH = 500;
    canvas.width = W;
    // Maintain court aspect ratio, capped at maxH
    const H = Math.min(Math.round(W * CL / CW), maxH);
    canvas.height = H;

    // Scale court to fit canvas with margin
    const margin = 10;
    const scaleX = (W - margin * 2) / CW;
    const scaleY = (H - margin * 2) / CL;
    const sc = Math.min(scaleX, scaleY);
    const ox = (W - CW * sc) / 2;
    const oy = (H - CL * sc) / 2;

    function c2c(cx, cy) { return [ox + cx * sc, oy + cy * sc]; }

    // Background
    ctx.fillStyle = '#2e7d32';
    ctx.fillRect(0, 0, W, H);

    // Court surface
    var tl = c2c(0, 0);
    ctx.fillStyle = '#388e3c';
    ctx.fillRect(tl[0], tl[1], CW * sc, CL * sc);

    // Draw lines helper
    function drawLine(x1, y1, x2, y2, color, width) {
        var a = c2c(x1, y1), b = c2c(x2, y2);
        ctx.strokeStyle = color || '#fff';
        ctx.lineWidth = width || 2;
        ctx.beginPath();
        ctx.moveTo(a[0], a[1]);
        ctx.lineTo(b[0], b[1]);
        ctx.stroke();
    }

    // Court boundary
    drawLine(0, 0, CW, 0);
    drawLine(0, CL, CW, CL);
    drawLine(0, 0, 0, CL);
    drawLine(CW, 0, CW, CL);

    // Kitchen lines
    drawLine(0, KITCHEN_NEAR, CW, KITCHEN_NEAR);
    drawLine(0, KITCHEN_FAR, CW, KITCHEN_FAR);

    // Net
    drawLine(0, NET_Y, CW, NET_Y, '#ddd', 3);

    // Center service lines
    drawLine(CENTER_X, 0, CENTER_X, KITCHEN_NEAR);
    drawLine(CENTER_X, KITCHEN_FAR, CENTER_X, CL);

    // Zone labels
    ctx.fillStyle = 'rgba(255,255,255,0.5)';
    ctx.font = 'bold ' + Math.max(10, 14 * sc) + 'px sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
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
        ctx.fillText(labels[i][0], p[0], p[1]);
    }

    if (!bounces.length) {
        ctx.fillStyle = 'rgba(255,255,255,0.6)';
        ctx.font = '14px Arial';
        ctx.textAlign = 'center';
        ctx.fillText('No bounces recorded', W / 2, H / 2);
        return;
    }

    // Bounce and serve markers
    bounces.forEach(function(b) {
        if (b.court_x == null || b.court_y == null) return;
        var bp = c2c(b.court_x, b.court_y);
        if (b.result === 'SERVE') {
            // Serve marker: triangle
            ctx.beginPath();
            ctx.moveTo(bp[0], bp[1] - 7);
            ctx.lineTo(bp[0] - 6, bp[1] + 5);
            ctx.lineTo(bp[0] + 6, bp[1] + 5);
            ctx.closePath();
            ctx.fillStyle = '#42a5f5';
            ctx.fill();
            ctx.strokeStyle = '#fff';
            ctx.lineWidth = 1;
            ctx.stroke();
        } else {
            ctx.beginPath();
            ctx.arc(bp[0], bp[1], 5, 0, Math.PI * 2);
            ctx.fillStyle = b.result === 'IN' ? '#66bb6a' : '#ef5350';
            ctx.fill();
            ctx.strokeStyle = '#fff';
            ctx.lineWidth = 1;
            ctx.stroke();
        }
    });
}

// --- Score timeline chart ---
function buildScoreChart(scores, matchStart) {
    const startMs = new Date(matchStart).getTime();

    const serverPts = scores.map(s => ({
        x: (new Date(s.timestamp).getTime() - startMs) / 1000,
        y: s.server_score
    }));
    const receiverPts = scores.map(s => ({
        x: (new Date(s.timestamp).getTime() - startMs) / 1000,
        y: s.receiver_score
    }));

    new Chart(document.getElementById('scoreChart'), {
        type: 'line',
        data: {
            datasets: [
                {
                    label: 'Server',
                    data: serverPts,
                    borderColor: '#1565c0',
                    backgroundColor: 'rgba(21,101,192,0.08)',
                    stepped: true,
                    pointRadius: 4,
                    tension: 0
                },
                {
                    label: 'Receiver',
                    data: receiverPts,
                    borderColor: '#c62828',
                    backgroundColor: 'rgba(198,40,40,0.08)',
                    stepped: true,
                    pointRadius: 4,
                    tension: 0
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: {
                    type: 'linear',
                    title: { display: true, text: 'Elapsed (seconds)' }
                },
                y: {
                    beginAtZero: true,
                    ticks: { stepSize: 1 },
                    title: { display: true, text: 'Score' }
                }
            },
            plugins: {
                legend: { position: 'top' }
            }
        }
    });
}

// --- Fetch & render ---
fetch('/api/analysis/' + MATCH_ID)
    .then(r => r.json())
    .then(data => {
        const { match, stats, bounces, scores, court_poly } = data;

        // Header date
        if (match.started_at)
            document.getElementById('matchDate').textContent = match.started_at.slice(0, 16).replace('T', '  ');

        // Stats
        let duration = null;
        if (match.started_at && match.ended_at)
            duration = (new Date(match.ended_at) - new Date(match.started_at)) / 1000;
        document.getElementById('statDuration').textContent  = fmtDuration(duration);
        document.getElementById('statPoints').textContent    = stats.total_points   ?? 0;
        document.getElementById('statBounces').textContent   = stats.total_bounces  ?? 0;
        document.getElementById('statSideOuts').textContent  = stats.total_side_outs ?? 0;

        // Court map
        if (court_poly && court_poly.length >= 3)
            drawCourtMap(court_poly, bounces);

        // Score timeline
        if (scores.length)
            buildScoreChart(scores, match.started_at);
        else {
            document.querySelector('.chart-wrap').innerHTML =
                '<p class="empty-msg">No score events recorded yet.</p>';
        }
    })
    .catch(() => {
        document.querySelector('.main-grid').innerHTML =
            '<p class="empty-msg" style="grid-column:1/-1">Failed to load analysis data.</p>';
    });
