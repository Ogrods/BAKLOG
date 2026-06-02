/** Load index.html into happy-dom for axe scans. */
import fs from 'node:fs';
import path from 'node:path';

const ROOT = path.resolve(import.meta.dirname, '../..');
const INDEX_PATH = path.join(ROOT, 'index.html');

/** Strip the inline boot script — it schedules timers we don't need in tests. */
function stripBootScript(html) {
  return html.replace(
    /<script>\s*\n\s*\/\/ Synchronously hydrate[\s\S]*?<\/script>/,
    '',
  );
}

/** Parse index.html and replace the current document body/head content. */
export function hydrateIndexDocument() {
  let html = fs.readFileSync(INDEX_PATH, 'utf8');
  html = stripBootScript(html);

  const parser = new DOMParser();
  const parsed = parser.parseFromString(html, 'text/html');

  document.documentElement.lang = parsed.documentElement.lang || 'en';
  // Drop stylesheet/script tags — happy-dom tries to fetch/load them.
  document.head.innerHTML = [...parsed.head.children]
    .filter((el) => !['LINK', 'SCRIPT', 'STYLE'].includes(el.tagName))
    .map((el) => el.outerHTML)
    .join('\n');
  const bodyHtml = [...parsed.body.children]
    .filter((el) => el.tagName !== 'SCRIPT')
    .map((el) => el.outerHTML)
    .join('\n');
  document.body.innerHTML = bodyHtml;
  document.body.className = parsed.body.className;

  injectSyntheticRuntimeDom();
}

/** Representative post-render DOM so axe sees runtime widgets, not just templates. */
function injectSyntheticRuntimeDom() {
  const tbody = document.getElementById('tbody');
  if (tbody) {
    tbody.innerHTML = `
      <tr data-game-key="steam:570">
        <td><img src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7" alt="" aria-hidden="true" class="cover-thumb" width="40" height="60" /></td>
        <td>Dota 2</td>
        <td>Action</td>
        <td><button type="button" aria-label="Set status for Dota 2">Backlog</button></td>
      </tr>`;
  }

  const rail = document.getElementById('connRail');
  if (rail) {
    rail.innerHTML = `
      <div class="conn-rail-item" data-provider="steam" role="option" tabindex="0" aria-selected="true">Steam</div>
      <div class="conn-rail-item" data-provider="gog" role="option" tabindex="-1" aria-selected="false">GOG</div>`;
  }

  const fetcherRow = document.getElementById('fetcherHealthRow');
  if (fetcherRow) {
    fetcherRow.innerHTML =
      '<button type="button" class="fh-chip" aria-label="Refresh Steam library">Steam</button>';
  }

  const alphaNav = document.getElementById('alphaNav');
  if (alphaNav) {
    alphaNav.innerHTML =
      '<button type="button" aria-label="Jump to letter A">A</button>';
  }

  document.querySelectorAll('.view-tab').forEach((btn, i) => {
    btn.setAttribute('aria-current', i === 0 ? 'page' : 'false');
  });
}
