/** js/pro-capabilities.js settings mirror shared/pro_settings.py keys. */
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import {
  getProSettings,
  setProSettings,
  setProSettingsFromConfig,
} from '../js/pro-capabilities.js';

describe('pro settings mirror', () => {
  it('defaults every opt-in off', () => {
    setProSettingsFromConfig({});
    expect(getProSettings()).toEqual({ cloudMirrorEnabled: false, dealAlertsEnabled: false });
  });

  it('round-trips dealAlertsEnabled from config and PUT responses', () => {
    setProSettingsFromConfig({ cloudMirrorEnabled: true, dealAlertsEnabled: true, extra: 1 });
    expect(getProSettings()).toEqual({ cloudMirrorEnabled: true, dealAlertsEnabled: true });
    expect(setProSettings({ dealAlertsEnabled: false })).toEqual({
      cloudMirrorEnabled: true,
      dealAlertsEnabled: false,
    });
    expect(setProSettings({ dealAlertsEnabled: 'yes' }).dealAlertsEnabled).toBe(false);
  });

  it('keys match DEFAULT_PRO_SETTINGS in shared/pro_settings.py', () => {
    const py = readFileSync('shared/pro_settings.py', 'utf8');
    const m = py.match(/DEFAULT_PRO_SETTINGS = \{([^}]*)\}/);
    const pyKeys = [...m[1].matchAll(/"(\w+)"/g)].map((x) => x[1]).sort();
    setProSettingsFromConfig({});
    expect(Object.keys(getProSettings()).sort()).toEqual(pyKeys);
  });
});
