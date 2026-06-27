/** Load landing/index.html into happy-dom for axe scans. */
import fs from 'node:fs';
import path from 'node:path';

const LANDING_PATH = path.resolve(import.meta.dirname, '../../landing/index.html');

export function hydrateLandingDocument() {
  const html = fs.readFileSync(LANDING_PATH, 'utf8');
  const parser = new DOMParser();
  const parsed = parser.parseFromString(html, 'text/html');

  document.documentElement.lang = parsed.documentElement.lang || 'en';
  document.head.innerHTML = [...parsed.head.children]
    .filter((el) => !['LINK', 'SCRIPT', 'STYLE'].includes(el.tagName))
    .map((el) => el.outerHTML)
    .join('\n');
  document.body.innerHTML = [...parsed.body.children]
    .filter((el) => el.tagName !== 'SCRIPT')
    .map((el) => el.outerHTML)
    .join('\n');
  document.body.className = parsed.body.className;
}
