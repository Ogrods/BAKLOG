import { escapeAttr, escapeHtml, isSafeHttpUrl } from "./dom-util.js";
import { lastRunErrorForProvider } from "./fetcher-health-shared.js";
import {
  providerForFetcher,
} from "./connections-status.js";
import {
  STATUS_CLASS,
  STATUS_LABEL,
  STATUS_NOTE,
  connStoreKey,
  contentFacetLabel,
  displayStatus,
  sourceFacet,
} from "./connections-rail.js";
import { formatPlatformList } from "./platform-labels.js";
import { state } from "./state.js";
import { storeLogoHtml } from "./store-logos.js";

const LOCAL_PROVIDER_FOOTER = {
  amazon: {
    connected:
      "Auto-detected from Amazon Games launcher. Open the app and sync, then run the Amazon fetcher for new games.",
    disconnected:
      "Disconnected - cached library stays visible. Connect to refresh, or use Prime web",
  },
  gog_galaxy: {
    connected: "Auto-detected from GOG Galaxy on this PC",
    disconnected:
      "Disconnected - cached library stays visible. Connect to refresh, or use GOG (web)",
  },
  itch_local: {
    connected: "Auto-detected from the itch desktop app",
    disconnected:
      "Disconnected - cached library stays visible. Connect to refresh, or use an API key",
  },
};

/** Footer copy for local provider cards (exported for tests). */
export function localProviderFooterCopy(providerKey, connected) {
  const copy = LOCAL_PROVIDER_FOOTER[providerKey];
  if (!copy) {
    return connected
      ? "Auto-detected locally on this PC"
      : "Local source hidden - Connect to use it again";
  }
  return connected ? copy.connected : copy.disconnected;
}

const CONN_HELP_LINKS = {
  steam: {
    url: "https://steamcommunity.com/dev/apikey",
    before: "Register for a Steam Web API key ",
    linkText: "here",
    after: " first, then sign in to connect.",
  },
};

function primaryLabel(st) {
  if (st === "connected" || st === "expired") return "Reconnect";

  if (st === "unverified") return "Verify";

  return "Connect";
}

function buildFormFields(p) {
  return (p.form_fields || [])
    .map(
      (f) => `

    <label>${escapeHtml(f.label)}

      <input type="${f.secret ? "password" : "text"}" data-field="${escapeAttr(f.key)}" placeholder="${escapeAttr(f.placeholder || "")}" autocomplete="off" />

    </label>`,
    )
    .join("");
}

function buildFormPanel(p) {
  return `

    <div class="conn-paste-panel">

      ${buildFormFields(p)}

      <div class="conn-paste-actions">

        <button type="button" class="conn-paste-clip" data-paste-clipboard>Paste</button>

        <button type="button" class="conn-save-btn conn-save" data-provider="${escapeAttr(p.key)}">Save key</button>

      </div>

    </div>`;
}

/**
 * Browser providers connect via the primary button; their form field is only a
 * manual fallback. Fold it into a collapsed drawer so it doesn't look like a
 * required step.
 */
function buildFallbackPanel(p) {
  const epicBrowser =
    p.key === "epic"
      ? `<button type="button" class="conn-open-url" data-epic-oauth data-provider="epic" title="Epic library OAuth in browser">Sign in with your browser instead</button>`
      : "";
  return `
    <details class="conn-fallback">
      <summary class="conn-fallback-summary">
        <span class="conn-fallback-chevron" aria-hidden="true">&rsaquo;</span>
        <span>Trouble connecting? Enter a code manually</span>
      </summary>
      <div class="conn-fallback-body">
        ${epicBrowser}
        ${buildFormPanel(p)}
      </div>
    </details>`;
}

function disconnectBtnHtml(p, st) {
  const show =
    st !== "disconnected" && st !== "unverified" && p.kind !== "local";
  return show
    ? `<button type="button" class="conn-disconnect" data-disconnect-quick data-provider="${escapeAttr(p.key)}" title="Disconnect ${escapeAttr(p.label)} (credentials removed locally)">Disconnect</button>`
    : "";
}

function buildCardFooter(p, st) {
  if (p.available === false) {
    const plats = formatPlatformList(p.platforms);
    return `
      <div class="conn-card-footer">
        <span class="conn-local-label">${escapeHtml(`Available on ${plats} only`)}</span>
      </div>`;
  }

  if (p.kind === "local") {
    const connected = st === "connected";
    const label = localProviderFooterCopy(p.key, connected);
    return `
      <div class="conn-card-footer">
        ${
          connected
            ? `<span class="conn-local-label">${escapeHtml(label)}</span>
             <button type="button" class="conn-disconnect" data-disconnect-quick data-provider="${escapeAttr(p.key)}" title="Disconnect ${escapeAttr(p.label)} (credentials removed locally)">Disconnect</button>`
            : `<span class="conn-local-label">${escapeHtml(label)}</span>
             <button type="button" class="conn-primary" data-enable-local data-provider="${escapeAttr(p.key)}" title="Enable ${escapeAttr(p.label)} from local launcher data">Connect</button>`
        }
      </div>`;
  }

  if (p.kind === "manual") {
    return `

      <div class="conn-card-footer">

        <button type="button" class="conn-open-url" data-open-url data-provider="${escapeAttr(p.key)}" title="Open ${escapeAttr(p.label)} sign-in page in browser">Open sign-in page</button>

        ${disconnectBtnHtml(p, st)}

      </div>`;
  }

  const label = primaryLabel(st);

  return `

    <div class="conn-card-footer">

      <button type="button" class="conn-primary" data-primary="browser" data-provider="${escapeAttr(p.key)}">${label}</button>

      ${disconnectBtnHtml(p, st)}

    </div>`;
}

function buildConnHelpLink(key) {
  const help = CONN_HELP_LINKS[key];
  if (!help || !isSafeHttpUrl(help.url)) return "";
  return `<p class="conn-help">${escapeHtml(help.before)}<a class="conn-help-link" href="${escapeAttr(help.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(help.linkText)}</a>${escapeHtml(help.after)}</p>`;
}

export function buildCardHtml(p) {
  const st = p.status || "disconnected";

  const pillSt = displayStatus(st);

  const storeKey = connStoreKey(p);

  const expiry = p.expiry_days
    ? `<p class="conn-meta">Typical session ~${p.expiry_days}d</p>`
    : "";

  const note = STATUS_NOTE[st]
    ? `<p class="conn-note">${escapeHtml(STATUS_NOTE[st])}</p>`
    : "";

  const helpLink = buildConnHelpLink(p.key);

  const err = p.last_error
    ? `<p class="conn-error">${escapeHtml(p.last_error)}</p>`
    : "";

  // Sticky last-run failure from fetcher health (rate-limit / empty / network)
  // while Connections status may still read Connected.
  const lastFetch = lastRunErrorForProvider(p.key, providerForFetcher);
  const lastFetchErr = lastFetch?.message
    ? `<p class="conn-error conn-error--fetch" title="Last fetcher run failed while this connection stayed connected">Last fetch failed: ${escapeHtml(lastFetch.message)}</p>`
    : "";

  const tips = (p.tips || []).length
    ? `<ul class="conn-tips">${p.tips.map((t) => `<li>${escapeHtml(t)}</li>`).join("")}</ul>`
    : "";

  const hasFormFields = (p.form_fields || []).length > 0;

  const showFormPanel =
    hasFormFields &&
    (p.kind === "form" || p.kind === "manual" || p.kind === "browser");

  const facets = `
    <div class="conn-facets" aria-label="Pull type and credential source">
      <span class="conn-facet conn-facet--content" title="What this connection syncs (library, wishlist, prices)">${escapeHtml(contentFacetLabel(p.key))}</span>
      <span class="conn-facet conn-facet--source" title="Where credentials are stored">${escapeHtml(sourceFacet(p))}</span>
    </div>`;

  const noteVal = (state.prefs?.connectionNotes || {})[p.key] || "";
  const notesHtml = `
    <div class="conn-notes">
      <label class="conn-notes-label" for="conn-note-${escapeAttr(p.key)}">Notes</label>
      <textarea id="conn-note-${escapeAttr(p.key)}" class="conn-note-input"
        data-note-provider="${escapeAttr(p.key)}" rows="2"
        placeholder="Private notes for this connection (saved to this profile)">${escapeHtml(noteVal)}</textarea>
    </div>`;

  return `

    <article class="conn-card${p.kind === "manual" ? " conn-card--manual" : ""}" data-provider="${escapeAttr(p.key)}">

      <div class="conn-card-stripe"></div>

      <div class="conn-card-head">

        ${storeLogoHtml(storeKey, { size: "lg", title: p.label, className: "conn-card-badge" })}

        <div class="conn-head-actions">

          <span class="${STATUS_CLASS[pillSt] || STATUS_CLASS.disconnected}" title="Connection status">${STATUS_LABEL[pillSt] || pillSt}</span>

        </div>

      </div>

      <div class="conn-card-body">

        <div class="conn-card-body-main">

          <h3>${escapeHtml(p.label)}</h3>

          ${facets}

          <p class="conn-desc">${escapeHtml(p.description || "")}</p>

          ${helpLink}

          ${tips}

          ${note}

          ${err}

          ${lastFetchErr}

          ${expiry}

          <p class="conn-log hidden" aria-live="polite"></p>

        </div>

        ${notesHtml}

      </div>

      ${showFormPanel ? (p.kind === "browser" ? buildFallbackPanel(p) : buildFormPanel(p)) : ""}

      ${buildCardFooter(p, st)}

    </article>`;
}