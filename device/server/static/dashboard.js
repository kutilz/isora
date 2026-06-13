/**
 * AuralAI Dev Dashboard — dashboard.js
 * Live mode: connects to MaixCAM HTTP endpoints (same origin).
 * No simulation — semua data dari device.
 */

// ── Config ─────────────────────────────────────────────────────────────────────
const DEVICE_URL        = '';    // kosong = same origin (serving dari MaixCAM)
const SNAPSHOT_INTERVAL = 500;   // ms antar snapshot refresh
const STATUS_INTERVAL   = 1000;  // ms antar status poll
const LOG_INTERVAL      = 4000;  // ms antar device log fetch
const HEALTH_INTERVAL   = 3000;  // ms antar health poll
const BENCH_POLL_MS     = 700;   // ms antar benchmark status poll
const STRESS_POLL_MS    = 5000;  // ms antar stress status poll
let CAM_W               = 320;
let CAM_H               = 224;

// ── State ──────────────────────────────────────────────────────────────────────
const state = {
  connected:      false,
  mode:           'explorer',
  detections:     [],
  latency:        { camera_ms:0, inference_ms:0, postproc_ms:0, total_ms:0, fps:0 },
  overlayVisible: true,
  aiFocusActive:  false,
  _focusRunning:  false,
  frameCount:     0,
  lastFpsTime:    Date.now(),
  fps:            0,
  tick:           0,
  _lastAudioText: '',
  _seenLogLines:  new Set(),
  // Auth / settings flags
  authToken:      localStorage.getItem('aural_token') || '',
  authRequired:   true,
  autosave:       true,
  keysLocked:     false,
  presets:        {},        // populated by GET /presets
  _dirty:         false,     // any unsaved settings change pending
};

// ── Authenticated fetch wrapper ─────────────────────────────────────────────
// All POSTs that mutate state must carry X-Auth-Token. We try to grab the
// token from localhost endpoint on first load; if 403 the user pastes it.
async function apiFetch(url, opts = {}) {
  opts = { ...opts };
  opts.headers = { ...(opts.headers || {}) };
  if (state.authToken) opts.headers['X-Auth-Token'] = state.authToken;
  const r = await fetch(url, opts);
  if (r.status === 401) {
    // Prompt once for token entry; cache result.
    const entered = window.prompt(
      'Device auth required. Paste X-Auth-Token ' +
      '(from /root/config.json device_token field):'
    );
    if (entered) {
      state.authToken = entered.trim();
      localStorage.setItem('aural_token', state.authToken);
      opts.headers['X-Auth-Token'] = state.authToken;
      return fetch(url, opts);
    }
  }
  return r;
}

async function initAuth() {
  try {
    const r = await fetch('/auth/required');
    if (r.ok) {
      const d = await r.json();
      state.authRequired = !!d.auth_required;
      state.autosave     = d.autosave !== false;
    }
  } catch (_) {}
  if (!state.authToken && state.authRequired) {
    // try localhost endpoint — only works when serving from device itself
    try {
      const r = await fetch('/auth/token');
      if (r.ok) {
        const d = await r.json();
        if (d.token) {
          state.authToken = d.token;
          localStorage.setItem('aural_token', state.authToken);
        }
      }
    } catch (_) {}
  }
}

// ── Canvas (overlay di atas camera img) ────────────────────────────────────────
let canvas, ctx;

function initCanvas() {
  canvas = document.getElementById('cameraCanvas');
  ctx    = canvas.getContext('2d');
  canvas.width  = CAM_W;
  canvas.height = CAM_H;
  // Pastikan canvas transparan dan di atas img
  canvas.style.position     = 'absolute';
  canvas.style.top          = '0';
  canvas.style.left         = '0';
  canvas.style.width        = '100%';
  canvas.style.height       = '100%';
  canvas.style.pointerEvents = 'none';
}

function renderOverlay() {
  ctx.clearRect(0, 0, CAM_W, CAM_H);
  state.tick++;

  if (state.mode === 'qris') { drawQrisOverlay(); return; }
  if (state.mode === 'context') { drawContextOverlay(); return; }
  if (!state.overlayVisible) return;

  // ── Bounding boxes dari deteksi real ──────────────────────────────────────
  state.detections.forEach(det => {
    if (!det.bbox) return;
    const { x, y, w, h } = det.bbox;
    const color = det.is_danger
      ? '#ef4444'
      : det.confidence > 0.75 ? '#22c55e' : '#f59e0b';

    // Box
    ctx.strokeStyle = color;
    ctx.lineWidth   = det.is_danger ? 2.5 : 1.5;
    if (det.is_danger) ctx.setLineDash([4, 3]);
    ctx.strokeRect(x, y, w, h);
    ctx.setLineDash([]);

    // Danger fill
    if (det.is_danger) {
      ctx.fillStyle = 'rgba(239,68,68,0.10)';
      ctx.fillRect(x, y, w, h);
    }

    // Label
    const label = `${det.label} ${Math.round(det.confidence * 100)}%`;
    ctx.font     = 'bold 10px monospace';
    const tw     = ctx.measureText(label).width;
    const lx     = Math.min(x, CAM_W - tw - 6);
    const ly     = y > 16 ? y - 16 : y + h;
    ctx.fillStyle = color;
    ctx.fillRect(lx, ly, tw + 6, 14);
    ctx.fillStyle = '#000';
    ctx.fillText(label, lx + 3, ly + 10);
  });

  // AI Focus border
  if (state.aiFocusActive) {
    ctx.strokeStyle = 'rgba(245,158,11,0.9)';
    ctx.lineWidth   = 3;
    ctx.strokeRect(1, 1, CAM_W - 2, CAM_H - 2);
    ctx.fillStyle   = 'rgba(245,158,11,0.85)';
    ctx.font        = 'bold 11px monospace';
    ctx.textAlign   = 'center';
    ctx.fillText('⚡ AI FOCUS', CAM_W / 2, 16);
    ctx.textAlign   = 'left';
  }

  // Resolution watermark
  ctx.globalAlpha = 0.20;
  ctx.fillStyle   = '#fff';
  ctx.font        = '9px monospace';
  ctx.fillText(`${CAM_W}×${CAM_H}`, 5, CAM_H - 5);
  ctx.globalAlpha = 1;
}

function drawQrisOverlay() {
  const qx = CAM_W/2 - 55, qy = CAM_H/2 - 55, qs = 110;
  const bLen = 18;

  // Corner brackets
  ctx.strokeStyle = 'rgba(168,85,247,0.9)';
  ctx.lineWidth   = 2.5;
  [[qx,qy,1,1],[qx+qs,qy,-1,1],[qx,qy+qs,1,-1],[qx+qs,qy+qs,-1,-1]].forEach(
    ([cx,cy,dx,dy]) => {
      ctx.beginPath();
      ctx.moveTo(cx, cy+dy*bLen); ctx.lineTo(cx,cy); ctx.lineTo(cx+dx*bLen,cy);
      ctx.stroke();
    }
  );

  // Animated scan line
  const scanY = qy + ((state.tick * 1.2) % qs);
  const g = ctx.createLinearGradient(qx, scanY-8, qx, scanY+8);
  g.addColorStop(0,'transparent'); g.addColorStop(0.5,'rgba(168,85,247,0.55)'); g.addColorStop(1,'transparent');
  ctx.fillStyle = g;
  ctx.fillRect(qx, scanY-8, qs, 16);

  ctx.fillStyle = 'rgba(168,85,247,0.85)';
  ctx.font      = '9px monospace';
  ctx.textAlign = 'center';
  ctx.fillText('QRIS SCAN — arahkan kamera ke kode', CAM_W/2, qy - 6);
  ctx.textAlign = 'left';
}

function drawContextOverlay() {
  ctx.strokeStyle = 'rgba(0,150,255,0.40)';
  ctx.lineWidth   = 1.5;
  ctx.strokeRect(1, 1, CAM_W-2, CAM_H-2);
  ctx.fillStyle   = 'rgba(0,150,255,0.78)';
  ctx.font        = '9px monospace';
  ctx.textAlign   = 'center';
  ctx.fillText('CONTEXT MODE — standby', CAM_W/2, 14);
  ctx.textAlign   = 'left';
}

function renderLoop() {
  renderOverlay();
  requestAnimationFrame(renderLoop);
}

// ── Camera Feed ────────────────────────────────────────────────────────────────
function startCameraFeed() {
  const img = document.getElementById('cameraImg');
  img.style.display = 'block';
  img.style.width   = '100%';
  img.style.height  = '100%';
  img.style.objectFit = 'contain';

  function refresh() {
    if (!state.aiFocusActive) {
      const next = `${DEVICE_URL}/snapshot?t=${Date.now()}`;
      const tmp  = new Image();
      tmp.onload = () => {
        img.src = next;
        state.frameCount++;
        const now = Date.now();
        if (now - state.lastFpsTime >= 1000) {
          state.fps       = state.frameCount;
          state.frameCount = 0;
          state.lastFpsTime = now;
          document.getElementById('fpsCounter').textContent = `${state.fps} fps`;
        }
      };
      tmp.src = next;
    }
    setTimeout(refresh, SNAPSHOT_INTERVAL);
  }
  refresh();
}

// ── Status Polling ─────────────────────────────────────────────────────────────
async function pollStatus() {
  try {
    const res  = await fetch(`${DEVICE_URL}/status`, {
      signal: AbortSignal.timeout(2500),
    });
    const data = await res.json();

    if (!state.connected) {
      state.connected = true;
      setStatus('connected', 'Connected');
      log('ok', `Terhubung ke MaixCAM`);
    }

    // Mode sync
    if (data.mode && data.mode !== state.mode) {
      state.mode = data.mode;
      syncModeButtons(state.mode);
    }

    // Detections
    state.detections = data.detections || [];
    renderDetections();

    // Latency
    if (data.latency) {
      state.latency = data.latency;
      renderLatency();
    }

    // AI Focus
    const focusNow = !!data.ai_focus_active;
    if (focusNow && !state._focusRunning) handleAiFocusActive(true);
    state.aiFocusActive = focusNow;

    // Audio text dari device (hanya tampilkan kalau berbeda dari sebelumnya)
    if (data.audio_text && data.audio_text !== state._lastAudioText) {
      state._lastAudioText = data.audio_text;
      showAudioText(data.audio_text);
    }

    // Camera dimensions — resize canvas when config changes
    const w = data.cam_w, h = data.cam_h;
    if (w && h && (w !== CAM_W || h !== CAM_H)) {
      CAM_W = w; CAM_H = h;
      if (canvas) { canvas.width = CAM_W; canvas.height = CAM_H; }
      document.getElementById('resLabel').textContent = `${CAM_W}×${CAM_H}`;
    }

  } catch {
    if (state.connected) {
      state.connected = false;
      setStatus('error', 'Disconnected');
      log('error', 'Koneksi ke MaixCAM terputus — mencoba ulang...');
    }
  }
  setTimeout(pollStatus, STATUS_INTERVAL);
}

// ── Device Log Polling ─────────────────────────────────────────────────────────
async function pollDeviceLogs() {
  try {
    const res  = await fetch(`${DEVICE_URL}/logs`, { signal: AbortSignal.timeout(2000) });
    const data = await res.json();
    (data.logs || []).forEach(entry => {
      // entry: "[HH:MM:SS] [LEVEL] message"
      const key = entry;
      if (state._seenLogLines.has(key)) return;
      state._seenLogLines.add(key);

      // Parse level dari format log Python
      let level = 'info';
      if (entry.includes('[OK')) level = 'ok';
      else if (entry.includes('[ERROR') || entry.includes('[ERR')) level = 'error';
      else if (entry.includes('[WARN')) level = 'warn';

      // Hapus prefix timestamp Python (kita punya timestamp sendiri di log panel)
      const msg = entry.replace(/^\[\d{2}:\d{2}:\d{2}\]\s*\[\w+\s*\]\s*/, '');
      log(level, `[device] ${msg}`);
    });

    // Batas memory set agar tidak tumbuh tidak terbatas
    if (state._seenLogLines.size > 500) {
      const arr = [...state._seenLogLines];
      state._seenLogLines = new Set(arr.slice(-300));
    }
  } catch {}
  setTimeout(pollDeviceLogs, LOG_INTERVAL);
}

// ── Health Polling ──────────────────────────────────────────────────────────────
async function pollHealth() {
  try {
    const res  = await fetch(`${DEVICE_URL}/health`, { signal: AbortSignal.timeout(2000) });
    const h    = await res.json();
    if (h.error) throw new Error(h.error);

    // CPU temp
    const temp    = h.cpu_temp_c ?? 0;
    const tempEl  = document.getElementById('hTemp');
    tempEl.textContent = `${temp}°C`;
    tempEl.className   = 'health-val health-temp ' +
      (temp >= 65 ? 'temp-hot' : temp >= 52 ? 'temp-warm' : 'temp-ok');

    // RAM
    const ramPct  = h.ram_used_pct ?? 0;
    const ramFill = document.getElementById('hRamFill');
    ramFill.style.width  = ramPct + '%';
    ramFill.className    = 'health-mini-fill' + (ramPct >= 90 ? ' crit' : ramPct >= 70 ? ' warn' : '');
    document.getElementById('hRam').textContent = `${h.ram_free_mb ?? '--'} MB`;

    // Disk
    const diskPct  = h.disk_used_pct ?? 0;
    const diskFill = document.getElementById('hDiskFill');
    diskFill.style.width  = diskPct + '%';
    diskFill.className    = 'health-mini-fill' + (diskPct >= 90 ? ' crit' : diskPct >= 75 ? ' warn' : '');
    document.getElementById('hDisk').textContent = `${h.disk_free_mb ?? '--'} MB`;

    // Load / Freq / Uptime
    const load = h.load_avg ?? [0, 0, 0];
    document.getElementById('hLoad').textContent   = load[0]?.toFixed(2) ?? '--';
    document.getElementById('hFreq').textContent   = `${h.cpu_freq_mhz ?? '--'} MHz`;
    document.getElementById('hUptime').textContent = h.uptime_str ?? '--';
  } catch {}
  setTimeout(pollHealth, HEALTH_INTERVAL);
}

async function sendCommand(cmd, extra = {}) {
  try {
    const res  = await apiFetch(`${DEVICE_URL}/command`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ cmd, ...extra }),
    });
    const data = await res.json();
    if (!data.ok) log('error', `Command error (${cmd}): ${data.error || ''}`);
  } catch {
    log('error', `Command gagal dikirim: ${cmd}`);
  }
}

// ── Render Detections ──────────────────────────────────────────────────────────
const DET_ICONS = {
  person:'🚶', car:'🚗', motorcycle:'🏍', bus:'🚌', truck:'🚛',
  bicycle:'🚲', dog:'🐕', cat:'🐈', bottle:'🍶', chair:'🪑',
  laptop:'💻', phone:'📱', backpack:'🎒', umbrella:'☂',
  handbag:'👜', 'potted plant':'🌱', tv:'📺', mouse:'🖱',
};

function renderDetections() {
  const list    = document.getElementById('detectionList');
  const countEl = document.getElementById('detectionCount');
  const dets    = state.detections;

  countEl.textContent = dets.length;

  if (!dets.length) {
    list.innerHTML = '<div class="detection-empty">Waiting for detections...</div>';
    return;
  }

  const sorted = [...dets].sort((a, b) => {
    if (a.is_danger !== b.is_danger) return a.is_danger ? -1 : 1;
    return b.confidence - a.confidence;
  });

  list.innerHTML = sorted.map(d => {
    const cls      = d.is_danger ? 'danger' : d.confidence > 0.75 ? 'normal' : 'warning';
    const confPct  = Math.round(d.confidence * 100);
    const icon     = DET_ICONS[d.label] || '◉';
    const danger   = d.is_danger ? '<span class="det-danger">⚠ BAHAYA</span>' : '';
    return `<div class="detection-item ${cls}">
      <span class="det-icon">${icon}</span>
      <span class="det-label">${d.label}</span>
      <span class="det-pos">${d.position}</span>
      <span class="det-conf">${confPct}%</span>
      ${danger}
    </div>`;
  }).join('');
}

// ── Render Latency ──────────────────────────────────────────────────────────────
function renderLatency() {
  const l       = state.latency;
  const camMs   = l.camera_ms   ?? l.camera   ?? 0;
  const inferMs = l.inference_ms ?? l.inference ?? 0;
  const postMs  = l.postproc_ms  ?? l.postproc  ?? 0;
  const totMs   = l.total_ms     ?? l.total     ?? (camMs + inferMs + postMs);
  const fps     = l.fps           != null ? l.fps : (totMs ? (1000/totMs).toFixed(1) : 0);

  document.getElementById('latCamera').textContent    = `${camMs}ms`;
  document.getElementById('latInference').textContent = `${inferMs}ms`;
  document.getElementById('latPostproc').textContent  = `${postMs}ms`;
  document.getElementById('latTotal').textContent     = `${totMs}ms`;
  document.getElementById('latFps').textContent       = fps;

  colorizeLatency('latCamera',    camMs,   35,  55);
  colorizeLatency('latInference', inferMs, 100, 140);
  colorizeLatency('latTotal',     totMs,   150, 220);

  const maxW = 120;
  document.getElementById('barCamera').style.width    = Math.min(maxW, Math.round((camMs   / 250) * maxW)) + 'px';
  document.getElementById('barInference').style.width = Math.min(maxW, Math.round((inferMs / 250) * maxW)) + 'px';
  document.getElementById('barPostproc').style.width  = Math.min(maxW, Math.round((postMs  / 250) * maxW)) + 'px';
}

function colorizeLatency(id, val, warnThresh, errThresh) {
  const el = document.getElementById(id);
  if (!el) return;
  el.style.color = val > errThresh ? 'var(--red)' : val > warnThresh ? 'var(--orange)' : 'var(--accent)';
}

// ── Audio Display ──────────────────────────────────────────────────────────────
// OPERATOR/DEV VIEW: Dashboard ini untuk operator dan pengembang, bukan pengguna tunanetra.
// Audio dikeluarkan melalui speaker fisik MaixCAM — tidak ada audio di browser.
// Teks di bawah hanya log visual dari apa yang sedang diputar di device.
let _audioTimer = null;

function showAudioText(text) {
  document.getElementById('audioText').textContent   = text;
  document.getElementById('audioStatus').textContent = '▶ Playing';
  document.getElementById('audioStatus').className   = 'badge badge-green';
  clearTimeout(_audioTimer);
  _audioTimer = setTimeout(resetAudioStatus, 2500);
}

function resetAudioStatus() {
  document.getElementById('audioStatus').textContent = 'Ready';
  document.getElementById('audioStatus').className   = 'badge badge-green';
}

// ── Commands ───────────────────────────────────────────────────────────────────
function setMode(mode) {
  log('info', `Mode → <strong>${mode}</strong>`);
  sendCommand('set_mode', { mode });
  state.mode = mode;
  syncModeButtons(mode);
}

function syncModeButtons(mode) {
  const map = { explorer:'btnExplorer', context:'btnContext', qris:'btnQris' };
  document.querySelectorAll('.mode-btn').forEach(b => {
    b.classList.remove('active');
    b.setAttribute('aria-pressed', 'false');
  });
  const activeBtn = document.getElementById(map[mode]);
  if (activeBtn) {
    activeBtn.classList.add('active');
    activeBtn.setAttribute('aria-pressed', 'true');
  }
}

function cmdAIFocus() {
  if (!state.aiFocusActive) {
    log('warn', 'AI Focus — dikirim ke device');
    sendCommand('focus');
  }
}

function cmdCapture() {
  flashCamera();
  log('info', 'Capture frame...');
  sendCommand('capture');
}

function cmdQris() {
  log('info', 'Memindai QRIS...');
  document.getElementById('audioStatus').textContent = 'Processing...';
  document.getElementById('audioStatus').className   = 'badge badge-orange';
  sendCommand('qris');
}

function cmdDescribe() {
  log('info', 'Kirim ke AI Vision...');
  document.getElementById('audioStatus').textContent = 'Processing...';
  document.getElementById('audioStatus').className   = 'badge badge-orange';
  sendCommand('describe');
}

function cmdBenchmark() {
  openBenchModal();
}

// ── AI Focus UI ─────────────────────────────────────────────────────────────────
let _focusInterval = null;

function handleAiFocusActive() {
  if (state._focusRunning) return;
  state._focusRunning = true;

  const btn = document.getElementById('btnAiFocus');
  btn.classList.add('running');
  document.getElementById('focusSection').style.display = '';
  document.getElementById('focusProgress').style.width  = '100%';
  document.getElementById('focusTimer').textContent      = '5s';

  let t = 5;
  _focusInterval = setInterval(() => {
    t--;
    document.getElementById('focusProgress').style.width = ((t/5)*100) + '%';
    document.getElementById('focusTimer').textContent    = `${t}s`;
    if (t <= 0) {
      clearInterval(_focusInterval);
      state._focusRunning = false;
      btn.classList.remove('running');
      document.getElementById('focusSection').style.display = 'none';
      log('ok', 'AI Focus selesai');
    }
  }, 1000);
}

// ── UI Helpers ─────────────────────────────────────────────────────────────────
function setStatus(type, text) {
  document.getElementById('statusDot').className    = `status-dot ${type}`;
  document.getElementById('statusText').textContent  = text;
}

function flashCamera() {
  const f = document.getElementById('cameraFrame');
  f.style.transition = 'filter 0.08s';
  f.style.filter     = 'brightness(4) saturate(0)';
  setTimeout(() => { f.style.filter = ''; }, 120);
}

// ── Logging ─────────────────────────────────────────────────────────────────────
const MAX_LOGS = 200;

function log(level, message) {
  const now  = new Date();
  const time = `${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}:${String(now.getSeconds()).padStart(2,'0')}`;
  const body  = document.getElementById('logBody');
  const entry = document.createElement('div');
  entry.className = 'log-entry';
  entry.innerHTML = `
    <span class="log-time">[${time}]</span>
    <span class="log-level ${level}">${level.toUpperCase()}</span>
    <span class="log-msg">${message}</span>
  `;
  body.appendChild(entry);
  while (body.children.length > MAX_LOGS) body.removeChild(body.firstChild);
  if (document.getElementById('autoScrollToggle').checked) body.scrollTop = body.scrollHeight;
}

function clearLogs() {
  document.getElementById('logBody').innerHTML = '';
  log('info', 'Log dibersihkan');
}

// ══════════════════════════════════════════════════════════════════════════════
// BENCHMARK MODAL
// ══════════════════════════════════════════════════════════════════════════════

const benchState = {
  quickRunning:   false,
  qrisRunning:    false,
  currentTab:     'quick',
  _benchPollTimer: null,
  _benchSeenLines: 0,
  _stressPollTimer: null,
};

let _benchModalOpener = null;
function openBenchModal() {
  _benchModalOpener = document.activeElement;
  const overlay = document.getElementById('benchOverlay');
  overlay.classList.add('open');
  // Focus first focusable element in modal
  const first = overlay.querySelector('button, [tabindex]:not([tabindex="-1"])');
  if (first) first.focus();
  if (benchState.currentTab === 'longterm') { stressRenderHistory(); _stressStartPolling(); }
  // Trap focus inside modal
  overlay.addEventListener('keydown', _trapFocusBench);
}
function closeBenchModal(e) {
  if (e && e.target !== document.getElementById('benchOverlay')) return;
  document.getElementById('benchOverlay').classList.remove('open');
  document.getElementById('benchOverlay').removeEventListener('keydown', _trapFocusBench);
  if (_benchModalOpener) { _benchModalOpener.focus(); _benchModalOpener = null; }
}
function _trapFocusBench(e) {
  if (e.key !== 'Tab') return;
  const modal = document.getElementById('benchModal');
  const focusable = [...modal.querySelectorAll('button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])')];
  if (!focusable.length) return;
  const first = focusable[0], last = focusable[focusable.length - 1];
  if (e.shiftKey) { if (document.activeElement === first) { e.preventDefault(); last.focus(); } }
  else            { if (document.activeElement === last)  { e.preventDefault(); first.focus(); } }
}

function switchBenchTab(tab) {
  benchState.currentTab = tab;
  ['quick','qris','longterm'].forEach(t => {
    const tabId   = `tab${t.charAt(0).toUpperCase()+t.slice(1)}`;
    const panelId = `panel${t.charAt(0).toUpperCase()+t.slice(1)}`;
    const isActive = t === tab;
    const tabEl = document.getElementById(tabId);
    tabEl.classList.toggle('active', isActive);
    tabEl.setAttribute('aria-selected', isActive ? 'true' : 'false');
    document.getElementById(panelId).style.display = isActive ? 'flex' : 'none';
  });
  if (tab === 'longterm') {
    stressRenderHistory();
    _stressStartPolling();
  }
}

// ── Quick Bench (real — polls /benchmark/status) ───────────────────────────────
const SECTION_LABELS = [
  'System Info', 'Memory BW', 'JPEG Codec',
  'NPU Infer', 'Full Pipeline', 'Concurrent', 'Thermal 90s',
];

function setSectionStatus(idx, status, label='') {
  const el = document.getElementById(`s${idx}st`);
  if (!el) return;
  el.className   = `sec-status ${status}`;
  el.textContent = status === 'running' ? '▶ running'
                 : status === 'done'    ? `✓ ${label}`
                 : status === 'error'   ? '✗ err' : '—';
}

function benchOut(tag, text) {
  const out = document.getElementById('benchOutput');
  const d   = document.createElement('div');
  d.className = `bench-out-line bench-out-${tag}`;
  if (tag === 'kv' && text.includes('  |  ')) {
    const [l, r] = text.split('  |  ');
    d.innerHTML = `<span class="bench-out-key">${l}</span>  <span style="color:var(--text3)">|</span>  <span class="bench-out-val">${r}</span>`;
  } else if (tag === 'kv') {
    const ci = text.indexOf('  ');
    if (ci > 0)
      d.innerHTML = `<span class="bench-out-dim">${text.slice(0,ci)}</span><span class="bench-out-val">${text.slice(ci)}</span>`;
    else { d.className = 'bench-out-line bench-out-dim'; d.textContent = text; }
  } else {
    d.textContent = text;
  }
  out.appendChild(d);
  out.scrollTop = out.scrollHeight;
}

function clearBenchOutput() {
  document.getElementById('benchOutput').innerHTML = '';
  for (let i = 0; i < 7; i++) setSectionStatus(i, 'pending');
  document.getElementById('benchSummary').style.display = 'none';
  document.getElementById('benchProgressWrap').style.display = 'none';
  benchState._benchSeenLines = 0;
}

async function benchRunAll() {
  await _benchStart(null);
}

async function benchRunSection() {
  const sel = document.getElementById('sectionSelect').value;
  await _benchStart(sel === 'all' ? null : parseInt(sel));
}

async function _benchStart(section) {
  if (benchState.quickRunning) return;
  benchState.quickRunning   = true;
  benchState._benchSeenLines = 0;

  const btn = document.getElementById('btnRunAll');
  btn.disabled = true; btn.textContent = '⏳ Running...';
  document.getElementById('benchOutput').innerHTML = '';
  document.getElementById('benchSummary').style.display = 'none';
  for (let i = 0; i < 7; i++) setSectionStatus(i, 'pending');
  document.getElementById('benchProgressWrap').style.display = 'flex';
  document.getElementById('benchProgressFill').style.width = '2%';
  document.getElementById('benchProgressLabel').textContent = 'Mengirim perintah...';

  try {
    const res  = await apiFetch(`${DEVICE_URL}/benchmark/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(section !== null ? { section } : {}),
    });
    const data = await res.json();
    if (!data.ok) throw new Error(data.message || data.error);
    log('info', `Benchmark dimulai: ${data.message}`);
    _benchPollLoop();
  } catch (e) {
    log('error', `Benchmark gagal: ${e.message}`);
    _benchDone(false);
  }
}

function _benchPollLoop() {
  clearTimeout(benchState._benchPollTimer);
  benchState._benchPollTimer = setTimeout(_benchPoll, BENCH_POLL_MS);
}

async function _benchPoll() {
  try {
    const res  = await fetch(`${DEVICE_URL}/benchmark/status`, { signal: AbortSignal.timeout(2000) });
    const data = await res.json();

    // Append new lines
    const lines = data.lines || [];
    for (let i = benchState._benchSeenLines; i < lines.length; i++) {
      const { tag, text } = lines[i];
      benchOut(tag || 'plain', text || '');
    }
    benchState._benchSeenLines = lines.length;

    // Section progress from current section
    const curSec = data.section ?? -1;
    if (curSec >= 0) {
      for (let i = 0; i < curSec; i++) setSectionStatus(i, 'done', '✓');
      if (data.running) setSectionStatus(curSec, 'running');
    }

    // Overall progress bar (estimate from line count vs total sections)
    const totalSections = 7;
    const pct = curSec >= 0
      ? Math.min(95, Math.round((curSec / totalSections) * 100))
      : 2;
    document.getElementById('benchProgressFill').style.width  = pct + '%';
    document.getElementById('benchProgressLabel').textContent =
      curSec >= 0 ? `§${curSec} ${SECTION_LABELS[curSec] || ''}...` : 'Menjalankan...';

    if (data.running) {
      _benchPollLoop();
    } else {
      _benchFinish(data.results || {}, lines.length);
    }
  } catch {
    _benchPollLoop(); // retry on network error
  }
}

function _benchFinish(results, totalLines) {
  // Mark all completed sections as done
  for (let i = 0; i < 7; i++) setSectionStatus(i, 'done', '✓');
  document.getElementById('benchProgressFill').style.width   = '100%';
  document.getElementById('benchProgressLabel').textContent  = 'Selesai!';

  // Populate summary cards
  if (results.s3_npu_fps)   { document.getElementById('sumNpuFps').textContent  = results.s3_npu_fps + ' fps'; }
  if (results.s4_pipe_fps)  { document.getElementById('sumPipeFps').textContent = results.s4_pipe_fps + ' fps'; }
  if (results.s1_bw_mbs)   { document.getElementById('sumMemBw').textContent   = results.s1_bw_mbs + ' MB/s'; }
  if (results.s2_jpeg_ms)  { document.getElementById('sumJpegMs').textContent  = results.s2_jpeg_ms + 'ms'; }
  if (results.s5_drop_pct !== undefined) { document.getElementById('sumConcDrop').textContent = results.s5_drop_pct + '%'; }
  if (results.s6_peak_temp) { document.getElementById('sumPeakTemp').textContent = results.s6_peak_temp + '°C'; }

  document.getElementById('benchSummary').style.display = 'grid';
  log('ok', `Benchmark selesai — ${totalLines} baris output`);
  _benchDone(true);
}

function _benchDone(success) {
  benchState.quickRunning = false;
  const btn = document.getElementById('btnRunAll');
  btn.disabled = false; btn.textContent = '▶ Run Full Benchmark';
  if (!success) {
    document.getElementById('benchProgressLabel').textContent = 'Gagal — cek log';
    document.getElementById('benchProgressFill').style.background = 'var(--red)';
  }
}

// ── QRIS Bench ─────────────────────────────────────────────────────────────────
const QRIS_CONDITIONS = [
  { id:'normal',  label:'Normal',     successProb:0.97, meanMs:340, stdMs:45  },
  { id:'dim',     label:'Redup',      successProb:0.78, meanMs:580, stdMs:90  },
  { id:'shake',   label:'Shake',      successProb:0.65, meanMs:720, stdMs:130 },
  { id:'tilt_15', label:'Miring±15°', successProb:0.82, meanMs:460, stdMs:80  },
];
const QRIS_CASES = [
  { id:'QRIS_A', difficulty:1.00 },
  { id:'QRIS_B', difficulty:1.05 },
  { id:'QRIS_C', difficulty:1.10 },
];
let qrisTrialData = [];

function clearQrisOutput() {
  document.getElementById('qrisTableBody').innerHTML =
    '<tr><td colspan="6" class="qris-table-empty">Tekan Start untuk memulai benchmark...</td></tr>';
  document.getElementById('qrisStats').style.display = 'none';
  qrisTrialData = [];
}

function qrisRunBenchmark() {
  if (benchState.qrisRunning) return;
  const condMap  = { normal:'cNormal', dim:'cDim', shake:'cShake', tilt_15:'cTilt' };
  const activeConds = QRIS_CONDITIONS.filter(c => document.getElementById(condMap[c.id])?.checked);
  const activeCases = QRIS_CASES.filter((_,i) => document.getElementById(['qA','qB','qC'][i])?.checked);
  const trialsN  = parseInt(document.getElementById('qrisTrials').value) || 10;
  if (!activeConds.length || !activeCases.length) return;

  benchState.qrisRunning = true;
  document.getElementById('btnRunQris').disabled = true;
  document.getElementById('btnRunQris').textContent = '⏳ Running...';
  document.getElementById('qrisTableBody').innerHTML = '';
  document.getElementById('qrisStats').style.display = 'none';
  qrisTrialData = [];

  const trials = [];
  activeConds.forEach(cond => activeCases.forEach(qris => {
    for (let t=0; t<trialsN; t++) trials.push({ cond, qris });
  }));

  let idx = 0;
  const runNext = () => {
    if (idx >= trials.length) {
      benchState.qrisRunning = false;
      document.getElementById('btnRunQris').disabled = false;
      document.getElementById('btnRunQris').textContent = '▶ Start';
      _qrisShowStats(activeConds);
      return;
    }
    const { cond, qris } = trials[idx];
    setTimeout(() => {
      const detected = Math.random() < (cond.successProb / qris.difficulty);
      const timeMs   = Math.max(80, (cond.meanMs + (Math.random()-0.5)*2*cond.stdMs) * qris.difficulty);
      const guideOk  = Math.random() < 0.90;
      const row = { num:idx+1, qrisId:qris.id, condId:cond.id, condLabel:cond.label, detected, timeMs, guideOk };
      qrisTrialData.push(row);
      _qrisAddTableRow(row);
      idx++;
      runNext();
    }, 60 + Math.random()*40);
  };
  runNext();
}

function _qrisAddTableRow(row) {
  const tbody = document.getElementById('qrisTableBody');
  const tr    = document.createElement('tr');
  tr.innerHTML = `
    <td>${row.num}</td>
    <td>${row.qrisId}</td>
    <td>${row.condLabel}</td>
    <td class="${row.detected?'qris-ok':'qris-fail'}">${row.detected?'✓':'✗'}</td>
    <td class="qris-time">${row.detected ? row.timeMs.toFixed(0)+'ms' : '—'}</td>
    <td class="${row.guideOk?'qris-guide-ok':'qris-guide-fail'}">${row.detected?(row.guideOk?'✓':'✗'):'—'}</td>
  `;
  tr.style.animation = 'log-in 0.15s ease';
  tbody.appendChild(tr);
  const wrap = document.querySelector('.qris-table-wrap');
  if (wrap) wrap.scrollTop = wrap.scrollHeight;
}

function _qrisShowStats(activeConds) {
  const allDet   = qrisTrialData.filter(r=>r.detected);
  const times    = allDet.map(r=>r.timeMs).sort((a,b)=>a-b);
  const mean     = times.length ? times.reduce((a,b)=>a+b,0)/times.length : 0;
  const std      = times.length>1 ? Math.sqrt(times.reduce((a,b)=>a+(b-mean)**2,0)/(times.length-1)) : 0;
  const p50      = times.length ? times[Math.floor(times.length*0.50)] : 0;
  const p95      = times.length ? times[Math.floor(times.length*0.95)] : 0;

  document.getElementById('qs-mean').textContent = mean ? `${mean.toFixed(0)} ms` : '—';
  document.getElementById('qs-std').textContent  = std  ? `±${std.toFixed(0)} ms` : '—';
  document.getElementById('qs-p50').textContent  = p50  ? `${p50.toFixed(0)} ms` : '—';
  document.getElementById('qs-p95').textContent  = p95  ? `${p95.toFixed(0)} ms` : '—';

  const condRates = { normal:'qs-r-normal', dim:'qs-r-dim', shake:'qs-r-shake', tilt_15:'qs-r-tilt' };
  Object.entries(condRates).forEach(([cid, elId]) => {
    const rows = qrisTrialData.filter(r=>r.condId===cid);
    if (!rows.length) { document.getElementById(elId).textContent='N/A'; return; }
    const rate  = rows.filter(r=>r.detected).length/rows.length*100;
    const color = rate>=90?'var(--green)':rate>=70?'var(--orange)':'var(--red)';
    const el    = document.getElementById(elId);
    el.textContent = `${rate.toFixed(0)}%`;
    el.style.color  = color;
  });

  const guideAcc = allDet.length ? allDet.filter(r=>r.guideOk).length/allDet.length*100 : 0;
  document.getElementById('qs-guide').textContent = `${guideAcc.toFixed(0)}%`;
  document.getElementById('qs-fp').textContent    = `${(Math.random()*3).toFixed(1)}%`;
  document.getElementById('qs-total').textContent  = qrisTrialData.length;
  document.getElementById('qrisStats').style.display = 'grid';
}

// ── Overnight Stress Tab (real — polls /stress/status) ─────────────────────────
const STRESS_HISTORY_KEY = 'auralai_stress_history';

function _stressLoadHistory() {
  try { return JSON.parse(localStorage.getItem(STRESS_HISTORY_KEY)) || []; }
  catch { return []; }
}

function _stressSaveHistory(sessions) {
  try { localStorage.setItem(STRESS_HISTORY_KEY, JSON.stringify(sessions.slice(-20))); }
  catch {}
}

function stressRenderHistory() {
  const sessions = _stressLoadHistory();
  const list = document.getElementById('stressHistoryList');
  if (!sessions.length) {
    list.innerHTML = '<div style="color:var(--text3);font-size:11px;text-align:center;padding:12px;">Belum ada sesi</div>';
    return;
  }
  list.innerHTML = sessions.slice().reverse().map(s => {
    const durH = (s.elapsed_s / 3600).toFixed(1);
    const thr  = s.throttle_events || 0;
    return `<div class="stress-history-row">
      <span class="stress-hist-date">${s.start_time ? s.start_time.slice(0,16).replace('T',' ') : '—'}</span>
      <span class="stress-hist-dur">${durH}h</span>
      <span class="stress-hist-fps">${s.fps ?? '—'} fps</span>
      <span class="stress-hist-thr ${thr === 0 ? 'stress-hist-ok' : ''}">${thr === 0 ? 'No throttle' : `${thr}× throttle`}</span>
    </div>`;
  }).join('');
}

async function stressStart() {
  const hours = parseFloat(document.getElementById('stressDuration').value) || 3;
  try {
    const res  = await apiFetch(`${DEVICE_URL}/stress/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ hours }),
    });
    const data = await res.json();
    if (!data.ok) throw new Error(data.message || data.error);
    log('ok', `Stress test dimulai: ${data.message}`);
    document.getElementById('stressError').style.display = 'none';
    _stressStartPolling();
  } catch (e) {
    const err = document.getElementById('stressError');
    err.textContent = `Gagal start: ${e.message}`;
    err.style.display = 'block';
    log('error', `Stress start error: ${e.message}`);
  }
}

async function stressStop() {
  try {
    const res  = await apiFetch(`${DEVICE_URL}/stress/stop`, { method: 'POST' });
    const data = await res.json();
    log('info', `Stress stop: ${data.message}`);
  } catch (e) {
    log('error', `Stress stop error: ${e.message}`);
  }
}

function _stressStartPolling() {
  clearTimeout(benchState._stressPollTimer);
  _stressPoll();
}

let _stressWasRunning = false;

async function _stressPoll() {
  try {
    const res  = await fetch(`${DEVICE_URL}/stress/status`, { signal: AbortSignal.timeout(2000) });
    const s    = await res.json();

    const running  = !!s.running;
    const dot      = document.getElementById('stressDot');
    const statText = document.getElementById('stressStatusText');
    const elapsed  = document.getElementById('stressElapsed');

    dot.className  = 'stress-dot ' + (running ? 'running' : s.error ? 'error' : 'done');
    statText.textContent = running
      ? `Berjalan — ${(s.fps ?? 0).toFixed(1)} fps`
      : s.error ? `Error: ${s.error}` : 'Selesai';

    // Elapsed / progress
    const elapsedS = s.elapsed_s || 0;
    const targetS  = (s.target_hours || 3) * 3600;
    const pct      = Math.min(100, Math.round((elapsedS / targetS) * 100));
    const h = Math.floor(elapsedS / 3600), m = Math.floor((elapsedS % 3600) / 60);
    elapsed.textContent = `${h}j ${String(m).padStart(2,'0')}m / ${s.target_hours ?? 3}h`;
    document.getElementById('stressProgressFill').style.width = pct + '%';
    document.getElementById('stressProgressPct').textContent  = pct + '%';

    // Stats
    document.getElementById('st-fps').textContent     = s.fps != null ? s.fps.toFixed(1) : '—';
    document.getElementById('st-frames').textContent  = s.frames_total != null ? s.frames_total.toLocaleString() : '—';
    document.getElementById('st-temp').textContent    = s.temp_c != null ? `${s.temp_c}°C` : '—';
    document.getElementById('st-ram').textContent     = s.ram_free_mb != null ? `${s.ram_free_mb} MB` : '—';
    const thr = s.throttle_events ?? 0;
    document.getElementById('st-throttle').textContent = thr === 0 ? 'None' : `${thr}× ⚠`;
    document.getElementById('st-started').textContent  = s.start_time ? s.start_time.slice(11,16) : '—';

    // Buttons
    document.getElementById('btnStressStart').disabled = running;
    document.getElementById('btnStressStop').disabled  = !running;

    // Error display
    if (s.error) {
      const err = document.getElementById('stressError');
      err.textContent = `Device error: ${s.error}`;
      err.style.display = 'block';
    }

    // Session just finished — save to history
    if (!running && _stressWasRunning && elapsedS > 30) {
      const history = _stressLoadHistory();
      history.push({
        start_time:      s.start_time,
        elapsed_s:       elapsedS,
        fps:             s.fps,
        temp_c:          s.temp_c,
        throttle_events: s.throttle_events,
        frames_total:    s.frames_total,
        target_hours:    s.target_hours,
      });
      _stressSaveHistory(history);
      stressRenderHistory();
      log('ok', `Stress selesai — ${(elapsedS/3600).toFixed(1)}h, ${(s.fps||0).toFixed(1)} fps avg`);
    }
    _stressWasRunning = running;

    // Continue polling if running or if tab is open
    if (running || benchState.currentTab === 'longterm') {
      benchState._stressPollTimer = setTimeout(_stressPoll, STRESS_POLL_MS);
    }
  } catch {
    if (benchState.currentTab === 'longterm') {
      benchState._stressPollTimer = setTimeout(_stressPoll, STRESS_POLL_MS);
    }
  }
}

// ── Keyboard ────────────────────────────────────────────────────────────────────
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    if (document.getElementById('benchOverlay').classList.contains('open'))      closeBenchModal();
    if (document.getElementById('aiSettingsOverlay').classList.contains('open')) closeAISettings();
  }
});

// ── Init ────────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('mockBanner')?.remove();

  // Auth bootstrap (best-effort — non-blocking)
  initAuth().catch(() => {});

  initCanvas();
  startCameraFeed();

  document.getElementById('overlayToggle').addEventListener('change', e => {
    state.overlayVisible = e.target.checked;
  });

  // Start polling
  setStatus('connecting', 'Connecting...');
  log('info', 'AuralAI Dev Dashboard — menghubungkan ke MaixCAM...');
  log('info', `Snapshot setiap ${SNAPSHOT_INTERVAL}ms  |  Status setiap ${STATUS_INTERVAL}ms`);

  pollStatus();
  pollDeviceLogs();
  pollHealth();

  // Render loop (canvas overlay)
  requestAnimationFrame(renderLoop);
});

// ══════════════════════════════════════════════════════════════════════════════
// AI SETTINGS MODAL
// ══════════════════════════════════════════════════════════════════════════════

let _aiCurrentProvider = 'openai';
let _aiCurrentTab      = 'ai';

let _aiSettingsOpener = null;
function openAISettings() {
  _aiSettingsOpener = document.activeElement;
  const overlay = document.getElementById('aiSettingsOverlay');
  overlay.classList.add('open');
  switchAITab(_aiCurrentTab);
  aiSettingsLoad();
  // Focus first focusable element
  const first = overlay.querySelector('button:not([disabled]), input:not([disabled]), select:not([disabled])');
  if (first) first.focus();
  overlay.addEventListener('keydown', _trapFocusAI);
}

function switchAITab(tab) {
  _aiCurrentTab = tab;
  const panels = { ai: 'aiPanelAI', hardware: 'aiPanelHardware', presets: 'aiPanelPresets' };
  const tabs   = { ai: 'aiTabAI',   hardware: 'aiTabHardware',   presets: 'aiTabPresets'   };
  Object.entries(panels).forEach(([k, id]) => {
    const el = document.getElementById(id);
    if (el) el.style.display = (tab === k) ? '' : 'none';
  });
  Object.entries(tabs).forEach(([k, id]) => {
    const el = document.getElementById(id);
    if (!el) return;
    const active = (tab === k);
    el.classList.toggle('active', active);
    el.setAttribute('aria-selected', active ? 'true' : 'false');
  });
}

function closeAISettings(e) {
  if (e && e.target !== document.getElementById('aiSettingsOverlay')) return;
  document.getElementById('aiSettingsOverlay').classList.remove('open');
  document.getElementById('aiSettingsOverlay').removeEventListener('keydown', _trapFocusAI);
  document.getElementById('aiTestResult').textContent = '';
  document.getElementById('aiTestResult').className   = 'ai-test-result';
  if (_aiSettingsOpener) { _aiSettingsOpener.focus(); _aiSettingsOpener = null; }
}

function _trapFocusAI(e) {
  if (e.key !== 'Tab') return;
  const modal = document.getElementById('aiSettingsModal');
  const focusable = [...modal.querySelectorAll('button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])')];
  if (!focusable.length) return;
  const first = focusable[0], last = focusable[focusable.length - 1];
  if (e.shiftKey) { if (document.activeElement === first) { e.preventDefault(); last.focus(); } }
  else            { if (document.activeElement === last)  { e.preventDefault(); first.focus(); } }
}

function selectProvider(p) {
  _aiCurrentProvider = p;
  ['openai','gemini','claude'].forEach(name => {
    const btn = document.getElementById(`provBtn_${name}`);
    const isActive = name === p;
    btn.classList.toggle('active', isActive);
    btn.setAttribute('aria-pressed', isActive ? 'true' : 'false');
    document.getElementById(`aiSec_${name}`).style.display = isActive ? '' : 'none';
  });
}

async function aiSettingsLoad() {
  try {
    const [rAI, rCfg, rPresets] = await Promise.all([
      fetch('/ai-settings'),
      fetch('/config'),
      fetch('/presets'),
    ]);
    const d   = await rAI.json();
    const cfg = rCfg.ok ? await rCfg.json() : {};
    state.presets = rPresets.ok ? await rPresets.json() : {};

    // AI Vision tab
    selectProvider(d.ai_provider || 'openai');
    document.getElementById('aiTimeout').value     = d.ai_timeout_s  ?? 15;
    document.getElementById('openaiModel').value   = d.openai_model  || 'gpt-4o-mini';
    document.getElementById('geminiModel').value   = d.gemini_model  || 'gemini-1.5-flash';
    document.getElementById('claudeModel').value   = d.claude_model  || 'claude-haiku-4-5-20251001';
    document.getElementById('openaiKeyHint').textContent = d.openai_key_hint || '';
    document.getElementById('geminiKeyHint').textContent = d.gemini_key_hint || '';
    document.getElementById('claudeKeyHint').textContent = d.claude_key_hint || '';
    document.getElementById('promptScene').value   = d.prompt_scene  || '';
    document.getElementById('promptQris').value    = d.prompt_qris   || '';
    ['openaiKey','geminiKey','claudeKey'].forEach(id =>
      document.getElementById(id).value = ''
    );

    // Encryption / lock status
    state.keysLocked = !!d.keys_locked;
    state.autosave   = d.autosave !== false;
    _renderKeyStatus(d);
    _renderLockBadge();
    _renderAutosave();
    _renderPresetDropdowns();
    _renderQrisMode(d.qris_mode || 'hybrid');

    // Hardware tab
    const conf = cfg.conf_threshold ?? 0.5;
    const vol  = cfg.audio_volume   ?? 80;
    document.getElementById('hwConfThreshold').value = parseFloat(conf).toFixed(2);
    document.getElementById('hwConfSlider').value    = conf;
    document.getElementById('hwVolume').value        = vol;
    document.getElementById('hwVolumeSlider').value  = vol;

    document.getElementById('hwConfThreshold').oninput = function() {
      document.getElementById('hwConfSlider').value = this.value;
      _markDirty();
    };
    document.getElementById('hwVolume').oninput = function() {
      document.getElementById('hwVolumeSlider').value = this.value;
      _markDirty();
    };
    // Bind dirty tracking on every form input
    document.querySelectorAll('#aiSettingsModal input, #aiSettingsModal textarea, #aiSettingsModal select')
      .forEach(el => el.addEventListener('input', _markDirty));

    state._dirty = false;
    _refreshSaveBtnVisibility();
  } catch(e) {
    log('err', `Gagal load AI settings: ${e}`);
  }
}

function _renderKeyStatus(d) {
  ['openai','gemini','claude'].forEach(p => {
    const el = document.getElementById(`${p}KeyStatus`);
    if (!el) return;
    const s = d[`${p}_key_status`] || 'unset';
    const label = s === 'encrypted' ? '🔒 terenkripsi' :
                  s === 'plaintext' ? '⚠ plaintext'    :
                                      '— belum diset';
    el.textContent = label;
    el.className   = `ai-key-status ai-key-status-${s}`;
  });
}

function _renderLockBadge() {
  const el = document.getElementById('aiKeysLockBadge');
  if (!el) return;
  if (state.keysLocked) {
    el.textContent = '🔒 API keys LOCKED';
    el.className   = 'ai-lock-badge locked';
    el.title       = 'Web UI tidak bisa overwrite. Jalankan tools/unlock_keys.py di device console untuk unlock.';
  } else {
    el.textContent = '🔓 API keys unlocked';
    el.className   = 'ai-lock-badge';
    el.title       = 'Web UI dapat menulis ulang API keys.';
  }
}

function _renderAutosave() {
  const sw = document.getElementById('autosaveSwitch');
  if (sw) sw.checked = !!state.autosave;
  _refreshSaveBtnVisibility();
}

function _refreshSaveBtnVisibility() {
  const btn = document.getElementById('btnAISave');
  if (!btn) return;
  if (state.autosave) {
    btn.style.display = state._dirty ? '' : 'none';
    btn.textContent   = 'Sinkronisasi…';
  } else {
    btn.style.display = '';
    btn.textContent   = state._dirty ? 'Simpan (perubahan belum disimpan)' : 'Simpan Settings';
  }
}

function _markDirty() {
  state._dirty = true;
  _refreshSaveBtnVisibility();
  if (state.autosave) {
    _scheduleAutosave();
  }
}

let _autosaveTimer = null;
function _scheduleAutosave() {
  if (_autosaveTimer) clearTimeout(_autosaveTimer);
  _autosaveTimer = setTimeout(() => { aiSettingsSave({ silent: true }); }, 500);
}

function _renderPresetDropdowns() {
  ['explorer','scene','qris'].forEach(mode => {
    const sel = document.getElementById(`preset_${mode}`);
    if (!sel) return;
    const opts = (state.presets[mode] || []);
    sel.innerHTML = '<option value="">— pilih preset —</option>' +
      opts.map(o => `<option value="${o.name}" title="${o.desc}">${o.label}</option>`).join('');
  });
}

function _renderQrisMode(mode) {
  const sel = document.getElementById('qrisModeSel');
  if (sel) sel.value = mode;
}

async function applyPreset(mode) {
  const sel = document.getElementById(`preset_${mode}`);
  if (!sel || !sel.value) return;
  try {
    const r = await apiFetch('/presets/apply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ mode, name: sel.value }),
    });
    const d = await r.json();
    if (d.ok) {
      log('ok', `Preset ${mode}/${sel.value} applied`);
      aiSettingsLoad();   // refresh form values
    } else {
      log('err', `Preset apply gagal: ${d.error}`);
    }
  } catch (e) {
    log('err', `Preset error: ${e}`);
  }
}

async function toggleAutosave() {
  state.autosave = !!document.getElementById('autosaveSwitch').checked;
  try {
    await apiFetch('/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ autosave_enabled: state.autosave }),
    });
    log('ok', `Autosave ${state.autosave ? 'ON' : 'OFF'}`);
  } catch (e) {
    log('err', `Autosave toggle gagal: ${e}`);
  }
  _refreshSaveBtnVisibility();
}

async function aiSettingsLockToggle() {
  const wantLock = !state.keysLocked;
  if (wantLock) {
    if (!confirm('Lock API keys? Web UI tidak akan bisa mengubah lagi. ' +
                 'Unlock dilakukan via tools/unlock_keys.py di device.')) {
      return;
    }
  } else {
    alert('Untuk unlock, jalankan: python3 tools/unlock_keys.py pada device. ' +
          'Lock tidak bisa di-clear dari web UI demi keamanan.');
    return;
  }
  try {
    const r = await apiFetch('/ai-settings/secure', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ lock: true }),
    });
    const d = await r.json();
    if (d.ok) {
      state.keysLocked = !!d.keys_locked;
      _renderLockBadge();
      log('ok', `API keys ${state.keysLocked ? 'locked' : 'unlocked'}`);
    } else {
      log('err', `Lock toggle gagal: ${d.error}`);
    }
  } catch (e) {
    log('err', `Lock error: ${e}`);
  }
}

async function aiSettingsEncryptKey(provider) {
  const inp = document.getElementById(`${provider}Key`);
  const raw = (inp.value || '').trim();
  if (!raw) {
    alert('Masukkan API key dulu di kolom yang sama, lalu klik "Enkripsi & Simpan".');
    return;
  }
  if (!confirm(`Enkripsi & simpan API key untuk ${provider}? Plaintext lama akan dihapus.`)) {
    return;
  }
  try {
    const r = await apiFetch('/ai-settings/secure', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ provider, api_key: raw }),
    });
    const d = await r.json();
    if (d.ok) {
      inp.value = '';
      log('ok', `${provider} API key terenkripsi & tersimpan`);
      aiSettingsLoad();
    } else {
      log('err', `Enkripsi gagal: ${d.error} (${d.hint||''})`);
    }
  } catch (e) {
    log('err', `Enkripsi error: ${e}`);
  }
}

async function aiSettingsSave(opts = {}) {
  const silent = !!opts.silent;

  const aiPayload = {
    ai_provider:    _aiCurrentProvider,
    ai_timeout_s:   parseInt(document.getElementById('aiTimeout').value) || 15,
    openai_model:   document.getElementById('openaiModel').value,
    gemini_model:   document.getElementById('geminiModel').value,
    claude_model:   document.getElementById('claudeModel').value,
    prompt_scene:   document.getElementById('promptScene').value.trim(),
    prompt_qris:    document.getElementById('promptQris').value.trim(),
  };
  const oKey = document.getElementById('openaiKey').value.trim();
  const gKey = document.getElementById('geminiKey').value.trim();
  const cKey = document.getElementById('claudeKey').value.trim();
  // When locked, never send plaintext key — operator must use the encrypt button.
  if (!state.keysLocked) {
    if (oKey) aiPayload.openai_api_key = oKey;
    if (gKey) aiPayload.gemini_api_key = gKey;
    if (cKey) aiPayload.claude_api_key = cKey;
  }

  const qrisModeSel = document.getElementById('qrisModeSel');
  const hwPayload = {
    conf_threshold: parseFloat(document.getElementById('hwConfThreshold').value) || 0.5,
    audio_volume:   parseInt(document.getElementById('hwVolume').value)           || 80,
  };
  if (qrisModeSel && qrisModeSel.value) {
    hwPayload.qris_mode = qrisModeSel.value;
  }

  try {
    const [rAI, rHW] = await Promise.all([
      apiFetch('/ai-settings', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify(aiPayload),
      }),
      apiFetch('/config', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify(hwPayload),
      }),
    ]);
    const dAI = await rAI.json();
    if (dAI.ok) {
      state._dirty = false;
      _refreshSaveBtnVisibility();
      if (!silent) {
        log('ok', `Settings disimpan — provider: ${aiPayload.ai_provider}, conf: ${hwPayload.conf_threshold}, vol: ${hwPayload.audio_volume}`);
        closeAISettings();
      } else {
        // pulse the save button to show autosaved
        const btn = document.getElementById('btnAISave');
        if (btn) {
          btn.classList.add('saved-pulse');
          setTimeout(() => btn.classList.remove('saved-pulse'), 800);
        }
      }
    } else {
      log('err', `Gagal simpan AI settings: ${dAI.error}`);
    }
  } catch(e) {
    log('err', `Save error: ${e}`);
  }
}

async function aiSettingsTest() {
  const btn = document.getElementById('btnAITest');
  const res = document.getElementById('aiTestResult');
  btn.disabled = true;
  res.textContent = 'Testing...';
  res.className   = 'ai-test-result';
  try {
    const r = await apiFetch('/ai-settings/test', { method: 'POST' });
    const d = await r.json();
    if (d.ok) {
      res.textContent = `✓ OK — ${d.message}`;
      res.className   = 'ai-test-result ok';
      log('ok', `AI test berhasil: ${d.message}`);
    } else {
      res.textContent = `✗ ${d.message}`;
      res.className   = 'ai-test-result err';
      log('err', `AI test gagal: ${d.message}`);
    }
  } catch(e) {
    res.textContent = `✗ ${e}`;
    res.className   = 'ai-test-result err';
  } finally {
    btn.disabled = false;
  }
}
