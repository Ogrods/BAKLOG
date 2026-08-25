/** Boot FOUC script must read activeView from sessionStorage (prefs no longer store it). */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const INDEX = readFileSync(resolve(process.cwd(), 'index.html'), 'utf8');

describe('index.html FOUC boot view', () => {
  it('reads sessionStorage activeView key, not localStorage prefs.activeView', () => {
    expect(INDEX).toContain('sessionStorage.getItem(viewKey)');
    expect(INDEX).toContain('steam-backlog-ui-prefs:activeView');
    expect(INDEX).not.toMatch(/JSON\.parse\(raw\).*activeView/s);
    expect(INDEX).not.toMatch(/localStorage\.getItem\(prefsKey\)/);
  });
});
