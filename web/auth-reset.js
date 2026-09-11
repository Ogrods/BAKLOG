import { createClient } from './vendor/supabase-js.mjs';
import { hasRecoveryTokens, stripAuthHashFromUrl } from './auth-url-state.js';

const lead = document.getElementById('lead');
const hint = document.getElementById('hint');
const status = document.getElementById('status');
const form = document.getElementById('resetForm');
const submitBtn = document.getElementById('resetSubmit');
const actionsDone = document.getElementById('actionsDone');
const actionsExpired = document.getElementById('actionsExpired');

function showStatus(msg, { error = false, success = false } = {}) {
  status.textContent = msg;
  status.classList.remove('hidden', 'error', 'success');
  if (error) status.classList.add('error');
  if (success) status.classList.add('success');
}

async function clearRecoverySession(supabase) {
  if (!supabase) return;
  try {
    await supabase.auth.signOut();
  } catch {
    /* best-effort */
  }
}

async function showExpired(message, supabase = null) {
  await clearRecoverySession(supabase);
  lead.textContent = 'Reset link expired';
  hint.textContent = message;
  hint.classList.remove('hidden');
  actionsExpired.classList.remove('hidden');
  stripAuthHashFromUrl();
}

function showForm() {
  lead.textContent = 'Choose a new password';
  hint.textContent = 'Pick a new password for your BAKLOG account.';
  hint.classList.remove('hidden');
  form.hidden = false;
  form.classList.remove('hidden');
}

function showDone() {
  lead.textContent = 'Password updated';
  hint.textContent = 'Open BAKLOG on your PC and sign in with your new password.';
  hint.classList.remove('hidden');
  form.hidden = true;
  form.classList.add('hidden');
  actionsDone.classList.remove('hidden');
  stripAuthHashFromUrl();
}

async function loadConfig() {
  const res = await fetch('/api/auth-config');
  if (!res.ok) throw new Error('Auth not configured');
  return res.json();
}

function waitForRecovery(supabase, ms = 1200) {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (ok) => {
      if (settled) return;
      settled = true;
      resolve(ok);
    };
    const { data: { subscription } } = supabase.auth.onAuthStateChange((event) => {
      if (event === 'PASSWORD_RECOVERY') finish(true);
    });
    setTimeout(async () => {
      subscription.unsubscribe();
      const { data: { session } } = await supabase.auth.getSession();
      finish(!!session && hasRecoveryTokens(location.hash));
    }, ms);
  });
}

async function main() {
  let supabase;
  try {
    const cfg = await loadConfig();
    supabase = createClient(cfg.supabaseUrl, cfg.supabaseAnonKey, {
      auth: {
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: true,
      },
    });
  } catch {
    await showExpired(
      'Password reset is not available right now. Open BAKLOG on your PC, use Forgot password on the sign-in screen, and request a new link.',
    );
    return;
  }

  if (!hasRecoveryTokens(location.hash)) {
    await showExpired(
      'Open the reset link from your email, or request a new one from BAKLOG (Forgot password on the sign-in screen).',
      supabase,
    );
    return;
  }

  const ready = await waitForRecovery(supabase);
  if (!ready) {
    await showExpired(
      'This reset link is invalid or has expired. Open BAKLOG on your PC and use Forgot password to request a new one.',
      supabase,
    );
    return;
  }

  showForm();

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const password = document.getElementById('newPassword').value;
    const confirm = document.getElementById('confirmPassword').value;
    if (password.length < 8) {
      showStatus('Password must be at least 8 characters.', { error: true });
      return;
    }
    if (password !== confirm) {
      showStatus('Passwords do not match.', { error: true });
      return;
    }
    submitBtn.disabled = true;
    showStatus('');
    try {
      const { error: updateError } = await supabase.auth.updateUser({ password });
      if (updateError) {
        showStatus(updateError.message || 'Could not update password.', { error: true });
        return;
      }
      await supabase.auth.signOut();
      showDone();
    } finally {
      submitBtn.disabled = false;
    }
  });
}

main();
