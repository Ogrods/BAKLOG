/**
 * Wire the claimable-now module + claim dialogs (detail + hidden-claims).
 *
 * Extracted from bind-events.js to keep that file a thin orchestrator. The
 * claimable module is dynamically imported so its UI stays off the boot
 * critical path — the listeners attach as soon as the chunk resolves.
 * Called once from bindEvents().
 */
export function bindClaimableEvents() {
  void import('./claimable.js').then((claimable) => {
    document.getElementById('claimableNowModule')?.addEventListener('click', (e) => {
      claimable.handleClaimableClick(e);
    });
    document.getElementById('claimableBanner')?.addEventListener('click', (e) => {
      claimable.handleClaimableBannerClick(e);
    });
    document.getElementById('claimDetailDialog')?.addEventListener('click', (e) => {
      const dlg = e.currentTarget;
      if (e.target === dlg) {
        claimable.closeClaimDetail();
        return;
      }
      if (e.target.closest('[data-claim-clear]')) claimable.handleClaimableClick(e);
    });
    document.getElementById('claimHiddenDialog')?.addEventListener('click', (e) => {
      const dlg = e.currentTarget;
      if (e.target === dlg) {
        claimable.closeHiddenClaimsModal();
        return;
      }
      const restoreBtn = e.target.closest('[data-claim-restore]');
      if (restoreBtn) {
        claimable.restoreClaim(restoreBtn.dataset.claimRestore);
        return;
      }
      if (e.target.closest('[data-claim-purge-all]')) {
        claimable.openClaimPurgeConfirm();
      }
    });
    document.getElementById('claimPurgeConfirmDialog')?.addEventListener('click', (e) => {
      const dlg = e.currentTarget;
      if (e.target === dlg) {
        claimable.closeClaimPurgeConfirm();
        return;
      }
      if (e.target.closest('[data-claim-purge-confirm]')) {
        claimable.purgeAllHiddenClaims();
      }
    });
  });
}
