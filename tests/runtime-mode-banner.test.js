import { beforeEach, describe, expect, it } from 'vitest';
import { _runtimeBannerLabel, _resetRuntimeModeBannerForTests, syncRuntimeModeBanner } from '../js/runtime-mode-banner.js';

describe('runtime-mode-banner', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="runtimeModeBanner"></div>';
    _resetRuntimeModeBannerForTests();
  });

  it('labels dev server when frozen is false', () => {
    expect(_runtimeBannerLabel({ frozen: false })).toBe('Dev server');
    expect(_runtimeBannerLabel({ runtime_label: 'dev' })).toBe('Dev server');
  });

  it('shows dev chip in the header for dev config', () => {
    syncRuntimeModeBanner({ runtime_label: 'dev', data_dir_path: '~/repo/profiles' });
    const slot = document.getElementById('runtimeModeBanner');
    expect(slot.classList.contains('hidden')).toBe(false);
    expect(slot.textContent).toContain('Dev server');
  });

  it('hides for pure frozen sessions without mixed errors', () => {
    syncRuntimeModeBanner({ runtime_label: 'installed', data_dir_path: '~/AppData/Local/BAKLOG-Data' });
    const slot = document.getElementById('runtimeModeBanner');
    expect(slot.classList.contains('hidden')).toBe(true);
  });

  it('respects session dismiss', () => {
    syncRuntimeModeBanner({ frozen: false });
    document.querySelector('.runtime-mode-banner-dismiss')?.click();
    syncRuntimeModeBanner({ frozen: false });
    expect(document.getElementById('runtimeModeBanner').classList.contains('hidden')).toBe(true);
  });
});
