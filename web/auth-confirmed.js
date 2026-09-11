import { parseConfirmRedirectState, stripAuthHashFromUrl } from './auth-url-state.js';

function showSuccess() {
  document.getElementById('lead').textContent = 'Email confirmed';
  document.getElementById('bodySuccess').classList.remove('hidden');
  document.getElementById('bodyLocal').classList.remove('hidden');
  document.getElementById('actionsSuccess').hidden = false;
  stripAuthHashFromUrl();
}

function showError(message) {
  document.getElementById('lead').textContent = 'Confirmation link problem';
  const err = document.getElementById('bodyError');
  err.textContent = message || 'This confirmation link is invalid or has expired.';
  err.classList.remove('hidden');
  document.getElementById('actionsError').classList.remove('hidden');
  stripAuthHashFromUrl();
}

function showUnknown() {
  document.getElementById('lead').textContent = 'BAKLOG account';
  document.getElementById('bodyUnknown').classList.remove('hidden');
  document.getElementById('actionsSuccess').hidden = false;
  stripAuthHashFromUrl();
}

const state = parseConfirmRedirectState(location.search, location.hash);
if (state.status === 'success') showSuccess();
else if (state.status === 'error') showError(state.message);
else showUnknown();
if (location.hash) stripAuthHashFromUrl();
