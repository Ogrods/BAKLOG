/**
 * Shared Playwright tab click for UI/responsive audits.
 * Itch with no catalog jumps to the dashboard card (itch-tab-jump) - callers
 * must not wait for data-init-view=itch in that case.
 */

/**
 * @param {import('playwright').Page} page
 * @param {string} view
 * @returns {Promise<{ jumped: boolean, hasTab: boolean }>}
 */
export async function clickViewTab(page, view) {
  if (view === 'itch') {
    await page
      .waitForFunction(
        () =>
          window.__baklogBootPerf?.dashboardDataReady
          || document.getElementById('summary')?.children?.length > 0,
        null,
        { timeout: 15000 },
      )
      .catch(() => {});
  }
  return page.evaluate((v) => {
    const tab =
      document.querySelector(`.view-tab[data-view="${v}"]`) ||
      document.querySelector(`#headerNavSheet .view-tab[data-view="${v}"]`);
    const jumped = v === 'itch' && !!tab?.classList.contains('itch-tab-jump');
    tab?.click();
    return { jumped, hasTab: !!tab };
  }, view);
}

/**
 * @param {import('playwright').Page} page
 * @param {string} view
 * @param {number} [timeoutMs]
 */
export async function waitViewSettled(page, view, timeoutMs = 12000) {
  await page.waitForFunction(
    (v) => {
      const overlay = !!document
        .getElementById('viewLoadingOverlay')
        ?.classList.contains('show');
      const active = document.documentElement.getAttribute('data-init-view');
      return !overlay && active === v;
    },
    view,
    { timeout: timeoutMs },
  );
}
