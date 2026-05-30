import { state } from './state.js';
import { escapeAttr, escapeHtml, formatNum } from './dom-util.js';

const FRESH_THRESHOLDS = { fresh: 7 * 86400000, recent: 30 * 86400000 };

const COUNT_FNS = {
  itad: m => Object.keys(m?.by_key || {}).length,
  hltb: m => Object.keys(m || {}).filter(k => k !== 'fetched_at').length,
};

let fetcherSources = [];
let reloadGamesFn = async () => {};

export function configureFetcherHealth({ reloadGames }) {
  reloadGamesFn = reloadGames;
}

export async function loadFetcherSources() {
  if (fetcherSources.length) return fetcherSources;
  try {
    const res = await fetch('/api/fetchers');
    if (res.ok) {
      const data = await res.json();
      fetcherSources = (data.fetchers || []).map(entry => ({
        key: entry.key,
        label: entry.label,
        group: entry.group || 'library',
        color: entry.color || '#94a3b8',
        metaKey: entry.metaKey || entry.key,
        cmd: entry.cmd ? `python ${entry.cmd}` : '',
        countFn: COUNT_FNS[entry.key] || null,
      }));
      return fetcherSources;
    }
  } catch (_) {}
  try {
    const res = await fetch('fetchers/manifest.json');
    if (res.ok) {
      const data = await res.json();
      fetcherSources = (data.fetchers || []).map(entry => ({
        key: entry.key,
        label: entry.label,
        group: entry.group || 'library',
        color: entry.color || '#94a3b8',
        metaKey: entry.metaKey || entry.key,
        cmd: `python ${entry.script}`,
        countFn: COUNT_FNS[entry.key] || null,
      }));
    }
  } catch (_) {}
  return fetcherSources;
}

function humanizeAge(ms) {
  if (!Number.isFinite(ms)) return '—';
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 48) return `${h}h`;
  const d = Math.floor(h / 24);
  if (d < 14) return `${d}d`;
  const w = Math.floor(d / 7);
  if (w < 8) return `${w}w`;
  return `${Math.floor(d / 30)}mo`;
}

export function fetcherFreshness(source) {
  const meta = state.libraryMeta[source.metaKey];
  const count = meta
    ? (source.countFn ? source.countFn(meta) : (meta.game_count ?? null))
    : null;
  if (!meta || !meta.fetched_at) {
    return { status: 'missing', ageMs: Infinity, count, ageLabel: meta ? '?' : '—', iso: null };
  }
  const ts = Date.parse(meta.fetched_at);
  const ageMs = Number.isFinite(ts) ? Date.now() - ts : Infinity;
  let status = 'stale';
  if (ageMs < FRESH_THRESHOLDS.fresh) status = 'fresh';
  else if (ageMs < FRESH_THRESHOLDS.recent) status = 'recent';
  return { status, ageMs, count, ageLabel: humanizeAge(ageMs), iso: meta.fetched_at };
}

export const fetcherRunner = (() => {
  let apiAvailable = null;
  const runStateByKey = new Map();
  let activeRunId = null;
  let activeKey = null;
  let activeSource = null;
  let logEl = null;
  let logBodyEl = null;

  function logPanel() {
    if (!logEl) logEl = document.getElementById('fetcherRunLog');
    return logEl;
  }

  function logBody() {
    if (!logBodyEl || !document.body.contains(logBodyEl)) {
      logBodyEl = logPanel()?.querySelector('.fh-log-body') || null;
    }
    return logBodyEl;
  }

  async function probeApi() {
    if (apiAvailable !== null) return apiAvailable;
    try {
      await loadFetcherSources();
      const res = await fetch('/api/fetchers', { method: 'GET' });
      apiAvailable = res.ok;
    } catch {
      apiAvailable = false;
    }
    return apiAvailable;
  }

  function isApiAvailable() {
    return apiAvailable === true;
  }

  function stateFor(key) {
    return runStateByKey.get(key) || null;
  }

  function source(key) {
    return fetcherSources.find(s => s.key === key) || null;
  }

  function ensurePanel(src) {
    const panel = logPanel();
    if (!panel) return;
    if (!panel.dataset.built) {
      panel.innerHTML = `
        <div class="fh-log-head">
          <span class="fh-log-title" data-role="title">Fetcher log</span>
          <span class="fh-log-status" data-role="status">idle</span>
          <span class="fh-log-spacer"></span>
          <button type="button" class="fh-log-btn" data-role="clear">Clear</button>
          <button type="button" class="fh-log-btn" data-role="close">Close</button>
        </div>
        <div class="fh-log-body" data-role="body"></div>
      `;
      panel.dataset.built = '1';
      panel.addEventListener('click', e => {
        const btn = e.target.closest('[data-role]');
        if (!btn) return;
        if (btn.dataset.role === 'close') closePanel();
        else if (btn.dataset.role === 'clear') clearLog();
      });
    }
    panel.classList.add('open');
    panel.querySelector('[data-role="title"]').textContent = src ? `Running: ${src.label}` : 'Fetcher log';
    setStatus('queued');
    logBodyEl = panel.querySelector('[data-role="body"]');
  }

  function closePanel() {
    logPanel()?.classList.remove('open');
  }

  function clearLog() {
    const body = logBody();
    if (body) body.innerHTML = '';
  }

  function setStatus(status, extra) {
    const panel = logPanel();
    if (!panel) return;
    const el = panel.querySelector('[data-role="status"]');
    if (!el) return;
    el.className = `fh-log-status ${status}`;
    el.textContent = extra ? `${status} · ${extra}` : status;
  }

  function appendLine(text, kind = 'stdout') {
    const body = logBody();
    if (!body) return;
    const div = document.createElement('div');
    div.className = `fh-log-line ${kind}`;
    div.textContent = text;
    body.appendChild(div);
    while (body.children.length > 4000) body.removeChild(body.firstChild);
    body.scrollTop = body.scrollHeight;
  }

  function markChipState(key, runState) {
    if (runState) runStateByKey.set(key, runState);
    else runStateByKey.delete(key);
    renderDashboardFetcherHealth();
  }

  async function run(key) {
    if (!isApiAvailable()) return;
    const src = source(key);
    if (!src || runStateByKey.has(key)) return;

    ensurePanel(src);
    appendLine(`$ ${src.cmd}`, 'cmd');
    markChipState(key, 'queued');

    let res;
    try {
      res = await fetch(`/api/run/${encodeURIComponent(key)}`, { method: 'POST' });
    } catch (err) {
      appendLine(`[client] cannot reach server: ${err}`, 'stderr');
      setStatus('failed');
      markChipState(key, null);
      return;
    }
    if (!res.ok) {
      const txt = await res.text().catch(() => '');
      appendLine(`[server ${res.status}] ${txt || 'submit failed'}`, 'stderr');
      setStatus('failed');
      markChipState(key, null);
      return;
    }
    const { run_id: runId } = await res.json();
    if (activeKey && activeKey !== key) {
      appendLine(`(queued after ${source(activeKey)?.label || activeKey})`, 'meta');
    }
    activeRunId = runId;
    activeKey = key;
    subscribe(runId, key, src);
  }

  function subscribe(runId, key, src) {
    if (activeSource) {
      try { activeSource.close(); } catch (_) {}
      activeSource = null;
    }
    const es = new EventSource(`/api/stream/${encodeURIComponent(runId)}`);
    activeSource = es;

    es.addEventListener('status', evt => {
      try {
        const data = JSON.parse(evt.data);
        if (data.status === 'running') {
          markChipState(key, 'running');
          const panel = logPanel();
          if (panel) panel.querySelector('[data-role="title"]').textContent = `Running: ${src.label}`;
          setStatus('running');
        }
      } catch (_) {}
    });

    es.addEventListener('line', evt => {
      try {
        const data = JSON.parse(evt.data);
        appendLine(data.text || '', data.stream === 'stderr' ? 'stderr' : 'stdout');
      } catch (_) {}
    });

    es.addEventListener('done', async evt => {
      try {
        const data = JSON.parse(evt.data);
        const ok = data.status === 'done' && data.exit_code === 0;
        const duration = data.started_at && data.ended_at
          ? `${(data.ended_at - data.started_at).toFixed(1)}s`
          : '';
        appendLine(`[exit ${data.exit_code}] ${ok ? 'done' : 'failed'}${duration ? ` in ${duration}` : ''}`, 'meta');
        setStatus(ok ? 'done' : 'failed', duration);
        if (ok) {
          await refreshAfterFetch(key);
          markChipState(key, null);
        } else {
          markChipState(key, 'failed');
          setTimeout(() => {
            if (runStateByKey.get(key) === 'failed') {
              runStateByKey.delete(key);
              renderDashboardFetcherHealth();
            }
          }, 10000);
        }
      } catch (err) {
        appendLine(`[client] parse error on done: ${err}`, 'stderr');
      } finally {
        try { es.close(); } catch (_) {}
        if (activeSource === es) activeSource = null;
        if (activeRunId === runId) {
          activeRunId = null;
          activeKey = null;
        }
      }
    });

    es.onerror = async () => {
      if (es.readyState === EventSource.CONNECTING) return;
      try { es.close(); } catch (_) {}
      if (activeSource === es) activeSource = null;
      try {
        const snap = await fetch('/api/runs').then(r => r.json());
        const stillActive = snap.active?.id === runId;
        const inQueue = (snap.queue || []).some(r => r.id === runId);
        const finished = (snap.history || []).find(r => r.id === runId);
        if (stillActive || inQueue) {
          appendLine('[client] stream dropped — reconnecting', 'meta');
          setTimeout(() => subscribe(runId, key, src), 500);
          return;
        }
        if (finished) {
          const ok = finished.status === 'done' && finished.exit_code === 0;
          appendLine(`[client] stream dropped after exit ${finished.exit_code}`, 'meta');
          setStatus(ok ? 'done' : 'failed');
          if (ok) await refreshAfterFetch(key);
          markChipState(key, null);
          return;
        }
      } catch (_) {}
      appendLine('[client] stream error (server may have shut down)', 'stderr');
      setStatus('failed');
      markChipState(key, null);
    };
  }

  async function refreshAfterFetch(key) {
    try {
      await reloadGamesFn();
    } catch (err) {
      appendLine(`[client] reload failed: ${err}`, 'stderr');
    }
    const src = source(key);
    if (src) {
      const meta = state.libraryMeta[src.metaKey];
      if (meta && typeof meta === 'object' && !meta.fetched_at) {
        meta.fetched_at = new Date().toISOString();
      } else if (!meta) {
        state.libraryMeta[src.metaKey] = { fetched_at: new Date().toISOString() };
      }
    }
  }

  return { probeApi, isApiAvailable, stateFor, run };
})();

export function renderDashboardFetcherHealth() {
  const slot = document.getElementById('dashboardFetcherHealth');
  if (!slot) return;
  const showOnlyStale = !!state.prefs.fetcherHealthStaleOnly;
  const rows = fetcherSources.map(src => ({ src, ...fetcherFreshness(src) }));
  const staleRows = rows.filter(r => r.status === 'stale');
  const missingRows = rows.filter(r => r.status === 'missing');
  const visible = showOnlyStale
    ? rows.filter(r => r.status === 'stale' || r.status === 'missing')
    : rows;
  const rank = { missing: 0, stale: 1, recent: 2, fresh: 3 };
  visible.sort((a, b) => rank[a.status] - rank[b.status] || a.src.label.localeCompare(b.src.label));

  const summaryParts = [];
  if (staleRows.length) summaryParts.push(`${staleRows.length} stale`);
  if (missingRows.length) summaryParts.push(`${missingRows.length} missing`);
  const summaryText = summaryParts.length ? summaryParts.join(' · ') : 'All fresh';
  const apiReady = fetcherRunner.isApiAvailable();
  const apiNotice = apiReady
    ? '<span class="fh-summary" title="Click a chip to run that fetcher">· click to fetch</span>'
    : '<span class="fh-summary" title="Launch with `python server.py` for click-to-fetch">· read-only (run server.py to enable)</span>';

  const chipsHtml = visible.length
    ? visible.map(({ src, status, count, ageLabel, iso }) => {
        const countStr = count != null && count > 0 ? formatNum(count) : '—';
        const fetchedLine = iso ? new Date(iso).toLocaleString() : 'not loaded';
        const runState = fetcherRunner.stateFor(src.key);
        const displayStatus = runState || status;
        const runLabel = runState ? ` · ${runState.toUpperCase()}` : '';
        const title = apiReady
          ? `${src.label} · ${countStr} entries · fetched ${fetchedLine}${runLabel} — click to run \`${src.cmd}\``
          : `${src.label} · ${countStr} entries · fetched ${fetchedLine} · ${src.cmd}`;
        const disabled = !apiReady || runState === 'running' || runState === 'queued';
        return `<button type="button" class="fh-chip fh-chip-${displayStatus}" data-fetcher-key="${escapeAttr(src.key)}" data-status="${escapeAttr(status)}" style="border-left: 3px solid ${escapeAttr(src.color)}" title="${escapeAttr(title)}"${disabled ? ' disabled' : ''}>
          <span class="fh-chip-dot"></span>
          <span class="fh-chip-label">${escapeHtml(src.label)}</span>
          <span class="fh-chip-count">${escapeHtml(countStr)}</span>
          <span class="fh-chip-age">${escapeHtml(runState ? runState : ageLabel)}</span>
        </button>`;
      }).join('')
    : '<span class="fh-empty">No stale or missing fetchers — nice.</span>';

  slot.innerHTML = `
    <div class="fh-head">
      <div class="fh-head-left">
        <span class="fh-title">Fetcher health</span>
        <span class="fh-summary">${escapeHtml(summaryText)}</span>
        ${apiNotice}
      </div>
      <label class="fh-toggle">
        <input id="fetcherHealthStaleOnly" type="checkbox" class="rounded" ${showOnlyStale ? 'checked' : ''} />
        Only stale / missing
      </label>
    </div>
    <div class="fh-chips">${chipsHtml}</div>
  `;
}
