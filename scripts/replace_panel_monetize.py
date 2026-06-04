"""Replace panelMonetize() in tracker.html with thesis IA version."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
TRACKER = ROOT / "tracker.html"

text = TRACKER.read_text(encoding="utf-8")

# Extract SVG blocks from existing howitworks branch
m_run = re.search(r'const runSvg = `\s*(<svg[\s\S]*?</svg>)`', text)
m_ep = re.search(r'const endpointSvg = `\s*(<svg[\s\S]*?</svg>)`', text)
if not m_run or not m_ep:
    raise SystemExit("Could not extract SVG blocks")
run_svg = m_run.group(1)
endpoint_svg = m_ep.group(1)

# Escape for JS template literal (backticks in SVG are unlikely)
def js_tpl(s: str) -> str:
    return s.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")

run_js = js_tpl(run_svg)
ep_js = js_tpl(endpoint_svg)

NEW = r'''  function monetizeStatusPill(status) {
    const tones = { locked: "pill-locked", open: "pill-open", believe: "pill-believe", validate: "pill-validate" };
    return el("span", { class: "pill " + (tones[status] || "pill-neutral") }, status);
  }

  function renderMarketingFeatureCards() {
    const out = [];
    for (const block of MARKETING_FEATURES) {
      out.push(el("div", { class: "card" },
        el("h3", {}, block.category),
        el("p", {}, el("strong", {}, "Pitch: "), block.pitch),
        el("ul", {}, ...block.bullets.map((b) => {
          const li = el("li", {});
          const codeMatch = b.match(/(find_[a-z0-9_]+|bs_[a-z0-9_]+)/g);
          if (!codeMatch) { li.textContent = b; return li; }
          const parts = b.split(/(find_[a-z0-9_]+|bs_[a-z0-9_]+)/);
          for (const part of parts) {
            if (/^(find_|bs_)/.test(part)) li.appendChild(el("code", {}, part));
            else if (part) li.appendChild(document.createTextNode(part));
          }
          return li;
        })),
      ));
    }
    return out;
  }

  function panelMonetize() {
    const ta = el("textarea", { class: "freenotes", placeholder: "Free notes — pricing thoughts, channel ideas, counsel questions…" });
    ta.value = getPageNote("monetize");
    ta.addEventListener("input", () => setPageNote("monetize", ta.value));
    const section = state.monetizeSection || "thesis";
    const cards = [];

    if (section === "thesis") {
      cards.push(el("div", { class: "card thesis-lane" },
        el("h2", {}, "Thesis statement"),
        el("p", { class: "thesis-statement" }, MONETIZE_THESIS.statement),
        el("h3", {}, "The bet"),
        el("ul", { class: "thesis-bet" }, ...MONETIZE_THESIS.bet.map((b) => el("li", {}, b))),
        el("p", { class: "muted" }, MONETIZE_THESIS.horizon),
        el("p", { style: "margin-top:0.5rem" }, MONETIZE_THESIS.productTruth),
        el("p", { class: "xref" }, "Lead monetization model (canonical): Model & unit econ tab."),
      ));
      cards.push(el("div", { class: "card thesis-lane" },
        el("h2", {}, "Founder truths (evidence, not personas)"),
        el("p", { class: "muted" }, "The actual library the founder lives in — grounds the accidental-library thesis."),
        el("ul", {}, ...MONETIZE_TRUTHS.map((t) => el("li", {}, t))),
        el("p", {}, el("strong", {}, "Reframed pitch: "), "Modern game libraries are accidental. BAKLOG is built for people who own more games than they remember claiming."),
      ));
      cards.push(ownerPref("vision", "Define your personal north-star and hard limits.", "Success looks like...\nI will not do..."));
    } else if (section === "problem") {
      cards.push(el("div", { class: "card thesis-lane" },
        el("h2", {}, "Pain stories"),
        el("p", { class: "muted" }, "Court users with simple truths: free to start, Steam works first, cross-store clarity, privacy-first defaults."),
        el("ul", {},
          el("li", {}, el("strong", {}, "Free Thursday has consequences: "), "Epic weekly, Prime monthly, GOG giveaways, Steam free weekends — years of claims with no native audit tool on any storefront."),
          el("li", {}, el("strong", {}, "The accidental library: "), "You did not buy a 600-game library — it accumulated while you were not looking."),
          el("li", {}, el("strong", {}, "The itch.io blackout: "), "1,400-item bundles mix games, assets, and zines — no storefront sorts playable vs junk."),
          el("li", {}, el("strong", {}, "The five-launcher tax: "), "Steam, Epic, GOG, PSN, Xbox — 'what should I play tonight?' requires five places."),
          el("li", {}, el("strong", {}, "The duplicate buy: "), "Wishlist alerts are ownership-blind; you rebuy on Epic what you already own on Steam."),
        ),
        el("p", { class: "muted" }, "Counter-positioning: storefronts profit when you cannot see across stores. BAKLOG runs on your machine."),
      ));
      cards.push(el("div", { class: "card thesis-lane" },
        el("h2", {}, "Non-obvious insight"),
        el("p", {}, el("strong", {}, "Revealed preference = $0 payers. "), "The core audience acquired games through free claim flows (Epic, Prime, keys, bundles). Pricing the core above $0 fights how they actually spend."),
        el("p", {}, el("strong", {}, "Accidental libraries are the category. "), "No incumbent treats cross-store owned-library truth + ownership-aware deals + backlog decisioning as one local-first package."),
        el("p", { class: "xref" }, "Magic-moment demo + 12 library / 8 wishlist stack: Product & moat tab."),
      ));
      cards.push(el("div", { class: "card thesis-lane" },
        el("h2", {}, "Why now"),
        el("table", { class: "data-table ledger-table" },
          el("thead", {}, el("tr", {}, el("th", {}, "Signal"), el("th", {}, "Value"), el("th", {}, "Implication"))),
          el("tbody", {},
            ...MONETIZE_MARKET.filter((m) => /Epic|Prime|claim|free|accidental|ITAD|Backloggd/i.test(m.metric + m.implication)).slice(0, 6).map((m) =>
              el("tr", {}, el("td", {}, m.metric), el("td", {}, m.value), el("td", {}, m.implication)),
            ),
          ),
        ),
        el("p", { class: "xref" }, "Full TAM table: Market & audience tab."),
      ));
      cards.push(ownerPref("hooks", "Capture your preferred product pitch voice.", "My one-sentence pitch...\nMy 30-second demo script..."));
    } else if (section === "product") {
      cards.push(el("div", { class: "card thesis-lane" },
        el("h2", {}, "Canonical product facts"),
        el("p", {}, el("strong", {}, "12 library + 8 wishlist fetchers "), "— largest accidental-hoarder ingestion stack in category; cross-store dedupe + combined playtime."),
        el("h3", {}, "Magic-moment demo (canonical)"),
        el("p", {}, "Connect once, Refresh — fetcher chips light store-by-store, library counter climbs (often 0→1,000+ in ~60s) on the user's PC. Real account → real library; 30s screen recording is onboarding + marketing."),
        el("p", { class: "muted" }, "Every competitor shows populated mocks. BAKLOG can show retrieval happening locally."),
        el("h3", {}, "Ownership-aware deals (canonical)"),
        el("p", {}, "ITAD pricing fused with real libraries — deals surface only when actionable (on sale, unowned everywhere). Kills duplicate buys; wishlist radar retires itself when owned."),
        el("p", { class: "xref" }, "Privacy + fetcher-health bullets below; lead model in Model tab."),
      ));
      cards.push(...renderMarketingFeatureCards());
      cards.push(el("div", { class: "card thesis-lane" },
        el("h3", {}, "Marketing pillars"),
        ...MARKETING_PILLARS.map((p) => el("div", { class: "pillar-card" },
          el("p", {}, el("strong", {}, p.headline)),
          el("p", { class: "muted", style: "margin:0" }, p.proof),
          el("p", { class: "faint", style: "margin:0.25rem 0 0" },
            ...(p.relatedFindings || []).map((id) => el("code", { style: "margin-right:0.35rem" }, id)),
          ),
        )),
      ));
      cards.push(el("div", { class: "card thesis-lane" },
        el("h3", {}, "Quick comparison"),
        el("table", { class: "data-table", style: "margin-top:0.5rem" },
          el("thead", {}, el("tr", {}, el("th", {}, "They"), el("th", {}, "BAKLOG"))),
          el("tbody", {},
            el("tr", {}, el("td", {}, "Deal sites (ITAD, GG.deals)"), el("td", {}, "Deals + ownership context + backlog status")),
            el("tr", {}, el("td", {}, "Launchers (Playnite, Galaxy)"), el("td", {}, "Decision layer: what to play, what to buy, what's on sale")),
            el("tr", {}, el("td", {}, "Backloggd / manual trackers"), el("td", {}, "Auto-import from 12 library + 8 wishlist sources; no manual logging")),
            el("tr", {}, el("td", {}, "Hosted trackers"), el("td", {}, "No server — credentials never uploaded")),
          ),
        ),
      ));
      cards.push(ownerPref("features", "Note which bullets to lead with per channel.", "Reddit lead with...\nLanding hero should emphasize...\nScreenshots to capture next..."));
    } else if (section === "market") {
      cards.push(el("div", { class: "card thesis-lane" },
        el("h2", {}, "Personas (condensed)"),
        el("p", { class: "muted" }, "Primary: backlog hoarders, deal hunters, cross-store collectors. Secondary: privacy-first power users, creators."),
        ...MONETIZE_PERSONAS.map((p) => el("div", { class: "finding" },
          el("div", { class: "finding-title" }, p.name),
          el("p", { class: "finding-body" }, p.description),
          el("p", { style: "margin:0" }, el("strong", {}, "Pain: "), p.pain),
          el("p", { style: "margin:0.2rem 0 0" }, el("strong", {}, "Wins with: "), p.winsWith),
        )),
      ));
      cards.push(el("div", { class: "card thesis-lane" },
        el("h2", {}, "Market + TAM logic"),
        el("table", { class: "data-table ledger-table" },
          el("thead", {}, el("tr", {}, el("th", {}, "Metric"), el("th", {}, "Value"), el("th", {}, "Source"), el("th", {}, "Implication"))),
          el("tbody", {}, ...MONETIZE_MARKET.map((m) => el("tr", {}, el("td", {}, m.metric), el("td", {}, m.value), el("td", {}, m.source), el("td", {}, m.implication)))),
        ),
      ));
      cards.push(ownerPref("market", "Write down assumptions you trust versus assumptions to validate.", "Assumptions I trust...\nAssumptions to validate..."));
    } else if (section === "competition") {
      cards.push(el("div", { class: "card thesis-lane" },
        el("h2", {}, "Category position"),
        el("p", {}, "Only local-first tool fusing ", el("strong", {}, "automatic cross-store owned-library ingestion"), " + ", el("strong", {}, "deal intelligence"), " + ", el("strong", {}, "backlog decisioning"), " in one no-account package."),
        el("h3", {}, "Market segments"),
        ...MONETIZE_LANDSCAPE.map((s) => el("div", { class: "finding" },
          el("div", { class: "finding-title" }, s.segment),
          el("p", { class: "muted", style: "margin:0 0 0.25rem" }, s.players),
          el("p", { class: "finding-body" }, s.whatTheyDo),
          el("p", { style: "margin:0" }, el("strong", {}, "Gap: "), s.gap),
          el("p", { style: "margin:0.2rem 0 0" }, el("strong", {}, "Room for BAKLOG: "), s.roomFor),
        )),
      ));
      cards.push(el("div", { class: "card thesis-lane" },
        el("h2", {}, "Competitor deep dives"),
        ...MONETIZE_COMPETITORS.map((c) => el("div", { class: "finding" },
          el("div", { class: "finding-title" }, c.name),
          el("p", { class: "muted", style: "margin:0 0 0.25rem" }, `${c.segment} · ${c.platform} · ${c.model}`),
          el("p", { class: "finding-body" }, c.strength),
          el("p", { style: "margin:0" }, el("strong", {}, "Gap: "), c.gap),
          el("p", { style: "margin:0.2rem 0 0" }, el("strong", {}, "BAKLOG edge: "), c.edge),
        )),
      ));
      cards.push(el("div", { class: "card thesis-lane" },
        el("h2", {}, "Honest weaknesses"),
        el("ul", {},
          el("li", {}, el("strong", {}, "No native mobile app: "), "GG wins mobile; BAKLOG desktop-local for now."),
          el("li", {}, el("strong", {}, "Install friction: "), "Python + local server today — privacy moat, real friction."),
          el("li", {}, el("strong", {}, "No social layer: "), "Backloggd/GG feeds — solo workflow by design."),
          el("li", {}, el("strong", {}, "Pre-launch scale: "), "Founder library as proof; smaller than Backloggd's 650k."),
          el("li", {}, el("strong", {}, "Per-store Connect: "), "No one-click cloud OAuth like hosted competitors."),
        ),
      ));
      cards.push(el("div", { class: "card thesis-lane" },
        el("h2", {}, "Metadata: Steam + Wikidata, not IGDB"),
        el("p", {}, el("strong", {}, "IGDB rejected. "), "Commercial terms + attribution for monetized product. Authority stays Steam (+ Wikidata gap-fill for console-only rows)."),
      ));
      cards.push(ownerPref("compete", "Draft positioning against launchers, trackers, and deal sites.", "We win because..."));
    } else if (section === "model") {
      cards.push(el("div", { class: "card thesis-lane" },
        el("h2", {}, "Lead model (canonical): free + ads"),
        el("p", {}, el("strong", {}, "$0 free with contextual ads "), "on deal intent · optional ", el("strong", {}, "$2–$4/mo No ads"), " removes ad code paths (not DOM hide) + optional cloud sync later."),
        el("p", { class: "muted" }, "Audience revealed preference is $0 on games. House/affiliate on deal cards first; third-party networks only after MAU ≥ 5k, context-only targeting."),
      ));
      cards.push(el("div", { class: "card thesis-lane" },
        el("h2", {}, "Model iterations (ranked)"),
        ...MONETIZE_MODELS.map((m) => el("div", { class: "finding" },
          el("div", { class: "finding-title" }, m.name),
          el("p", { class: "finding-body" }, m.pitch),
          el("p", { style: "margin:0" }, el("strong", {}, "Price: "), m.priceBand, " — ", el("strong", {}, "Math: "), m.math),
          el("p", { style: "margin:0.2rem 0 0" }, el("strong", {}, "Agency says: "), m.agencySays),
          el("p", { style: "margin:0.2rem 0 0" }, el("strong", {}, "You'd ship: "), m.actuallyShip),
        )),
      ));
      cards.push(ownerPref("model_pick", "Pick your current model and deal-breakers.", "Model I'm leaning toward...\nDeal-breakers..."));
      cards.push(ownerPref("pricing", "Lock your first pricing hypothesis.", "Free tier ad slots...\nUpgrade price...\nFloor...\nCeiling...\nWhat triggers ad-network onboarding..."));
    } else if (section === "architecture") {
      const runSvg = `''' + run_js + r'''`;
      const endpointSvg = `''' + ep_js + r'''`;
      const PACKAGING_TIERS = [
        ["Clone and run (today)", "Yes", "User installs Python 3.11+, pip install -e \".[dev]\", Chrome for Connect. Runs python server.py."],
        ["pipx / pip install", "Yes (Python must exist)", "Console entry point (baklog) — cleaner, still needs Python on the machine."],
        ["PyInstaller / Briefcase frozen binary", "No", "Bundles interpreter + deps into BAKLOG.exe / .app. Build per OS. Gotcha: ROOT path must use sys._MEIPASS when frozen. Chrome still required (BAKLOG_CHROME_PATH)."],
        ["Docker", "No (needs Docker)", "Wrong fit for non-technical users; self-hosters only."],
      ];
      cards.push(el("div", { class: "card" },
        el("h2", {}, "How it runs (today)"),
        el("p", { class: "muted" }, "Local engine on your PC; two browser windows. Privacy moat = architecture, not marketing copy."),
        el("div", { class: "card", html: runSvg }),
        el("p", { class: "muted", style: "margin-top:0.5rem" }, "Stores → fetchers → local JSON → dashboard. No BAKLOG cloud in the middle."),
        el("h3", {}, "First run"),
        el("ol", {},
          el("li", {}, "Run ", el("code", {}, "python server.py"), " → ", el("code", {}, "http://127.0.0.1:8765"), "."),
          el("li", {}, "Connections → Connect each store (sign-in popup)."),
          el("li", {}, "Refresh — ", el("code", {}, "games_*.json"), " fills; dashboard paints live."),
        ),
      ));
      cards.push(el("div", { class: "card" },
        el("h2", {}, "Distribution endpoint: B (locked)"),
        el("p", { class: "muted" }, "Local-first core + optional derived-catalog sync + hosted read-only demo. Full hosted fetch (C) rejected."),
        el("div", { class: "card", html: endpointSvg }),
        el("p", { class: "muted", style: "margin-top:0.5rem" }, codeText("p4_packaging"), " · ", codeText("p4_hosted_demo"), " · ", codeText("bs_multiuser_app_login"), " when hosting decided."),
      ));
      cards.push(el("div", { class: "card" },
        el("h2", {}, "Engine vs frontend · Python requirement"),
        el("ul", {},
          el("li", {}, el("strong", {}, "UI: "), el("code", {}, "index.html"), " + ", el("code", {}, "js/"), " — static files served by ", el("code", {}, "server.py"), "."),
          el("li", {}, el("strong", {}, "Workers: "), "fetch_*.py write ", el("code", {}, "games_*.json"), "; secrets in OS keyring + ", el("code", {}, "auth/secrets.bin"), "."),
          el("li", {}, el("strong", {}, "Today: Python required. "), "Frozen binary removes Python; Chrome still required for Connect."),
        ),
        tableEl(["Approach", "Python required?", "Notes"], PACKAGING_TIERS.map((r) => r)),
      ));
      cards.push(el("div", { class: "card" },
        el("h2", {}, "B vs full-hosted C"),
        el("p", {}, el("strong", {}, "Endpoint locked: B. "), "Optional sync = derived catalog only; never credentials; never server-side fetch."),
        el("ul", {},
          el("li", {}, el("strong", {}, "C temptation: "), "zero-install URL, mobile-anywhere, native sync."),
          el("li", {}, el("strong", {}, "C rejected: "), "breaks privacy thesis, ", codeText("bs_tos"), " guardrails, breach target + infra cost."),
          el("li", {}, el("strong", {}, "Sanctioned slivers: "), "read-only demo, opt-in catalog sync, later hosted login after counsel."),
        ),
      ));
      cards.push(ownerPref("howitworks", "Notes on how you explain the model to a new user.", "The one-liner I use...\nWhat confuses people...\nThe analogy that clicks..."));
    } else if (section === "gtm") {
      cards.push(el("div", { class: "card thesis-lane" },
        el("h2", {}, "Launch sequencing (one channel at a time)"),
        el("p", { class: "muted" }, "Optional checklist — expand only if retention signal holds (", codeText("p5_pick_channel"), ")."),
        el("ol", {},
          el("li", {}, el("strong", {}, "Week 0: "), "Magic-moment recording (", codeText("video_magic_moment"), ") + README above-fold (", codeText("readme_above_fold"), ")."),
          el("li", {}, el("strong", {}, "Week 1: "), "10–20 friends — time-to-first-fetch + day-1 status edits."),
          el("li", {}, el("strong", {}, "Week 2: "), "Single Reddit — ", codeText("Watch your library appear"), " GIF."),
          el("li", {}, el("strong", {}, "Week 3: "), "r/selfhosted privacy variant."),
          el("li", {}, el("strong", {}, "Week 4: "), "Thursday claim-day post."),
          el("li", {}, el("strong", {}, "Week 5+: "), "Next channel only if day-7 return holds."),
        ),
        el("p", { class: "xref" }, "Full campaign storyboards: Execution library tab."),
      ));
      cards.push(el("div", { class: "card thesis-lane" },
        el("h2", {}, "Persona × channel (condensed)"),
        el("div", { class: "messaging-grid" },
          tableEl(
            ["Persona", "Reddit", "GitHub", "Landing", "Video", "Email"],
            MARKETING_CHANNEL_MATRIX.map((row) => [
              row.persona,
              ...["reddit", "github_readme", "landing", "short_video", "email_waitlist"].map((ch) => {
                const cell = row.channels[ch];
                if (!cell) return "—";
                return el("div", {},
                  el("div", {}, el("strong", {}, cell.campaign)),
                  el("div", { class: "faint" }, cell.hook),
                );
              }),
            ]),
          ),
        ),
      ));
      cards.push(ownerPref("playbook", "Your launch sequencing.", "Week 1 channel...\nSuccess metric...\nKill criteria..."));
      cards.push(ownerPref("gtm", "Pick first channel and success metric.", "First channel...\nSuccess metric..."));
    } else if (section === "risk") {
      cards.push(el("div", { class: "card thesis-lane" },
        el("h2", {}, "Risk + ethics"),
        el("p", { class: "muted" }, "Big risks: affiliate incentives, cloud defaults breaking trust, solo bandwidth, ads in a privacy-first brand."),
        el("p", { class: "xref" }, "Lead monetization model (canonical): Model & unit econ tab."),
        el("h3", {}, "Ads in a privacy-first tool"),
        el("ul", {},
          el("li", {}, el("strong", {}, "House/affiliate first "), "on deal cards — no third-party network until MAU ≥ 5k."),
          el("li", {}, el("strong", {}, "Context, not behavior: "), "target view (wishlist, store badge) — library never leaves device."),
          el("li", {}, el("strong", {}, "Disclosure "), "on every slot; upgrade removes ad modules at runtime."),
          el("li", {}, el("strong", {}, "Never sell data "), "— even aggregate ownership datasets off limits."),
        ),
        el("h3", {}, "Storefront ToS guardrails"),
        el("ul", {},
          el("li", {}, el("strong", {}, "Never centralize credentials or proxy fetches."), ""),
          el("li", {}, el("strong", {}, "Don't host/redistribute scraped catalog."), ""),
          el("li", {}, el("strong", {}, "User-initiated, reasonable rate, own account only."), ""),
          el("li", {}, el("strong", {}, "Copy precision: "), "automates what you could do in your browser on your machine — not 'we aggregate store data.'"),
        ),
        el("p", { class: "muted" }, "Per-store posture: SECURITY.md. EA uses web-session replay only."),
      ));
      cards.push(ownerPref("risk", "Document legal/trust constraints before monetization buildout.", "Disclosure language...\nRed lines...\nAd-network gating rules...\nQuestions for counsel..."));
    } else if (section === "decisions") {
      cards.push(el("div", { class: "card thesis-lane" },
        el("h2", {}, "Assumptions ledger"),
        el("table", { class: "data-table ledger-table" },
          el("thead", {}, el("tr", {}, el("th", {}, "Claim"), el("th", {}, "Status"), el("th", {}, "Evidence"))),
          el("tbody", {}, ...MONETIZE_ASSUMPTIONS.map((a) => el("tr", {},
            el("td", {}, a.claim),
            el("td", {}, monetizeStatusPill(a.status)),
            el("td", {}, a.evidence),
          ))),
        ),
      ));
      cards.push(el("div", { class: "card thesis-lane" },
        el("h2", {}, "Decision log"),
        el("table", { class: "data-table ledger-table" },
          el("thead", {}, el("tr", {}, el("th", {}, "Decision"), el("th", {}, "Status"), el("th", {}, "Rationale"))),
          el("tbody", {}, ...MONETIZE_DECISIONS.map((d) => el("tr", {},
            el("td", {}, d.decision),
            el("td", {}, monetizeStatusPill(d.status)),
            el("td", {}, d.rationale),
          ))),
        ),
      ));
      cards.push(el("div", { class: "card thesis-lane" },
        el("h2", {}, "North-star metrics"),
        el("ul", {}, ...MONETIZE_METRICS.northStar.map((m) => el("li", {}, el("strong", {}, m.metric + ": "), m.note))),
        el("h3", {}, "Guardrails"),
        el("ul", {}, ...MONETIZE_METRICS.guardrails.map((m) => el("li", {}, el("strong", {}, m.metric + ": "), m.note))),
        el("h3", {}, "Kill criteria"),
        el("ul", {}, ...MONETIZE_METRICS.kill.map((k) => el("li", {}, k))),
      ));
      cards.push(el("div", { class: "card" },
        el("h3", {}, "Owner lanes (strategic notes)"),
        el("p", { class: "muted" }, "Saved notes persist under legacy ids — edit in place."),
      ));
      cards.push(ownerPref("market", "Assumptions I trust vs validate.", "Assumptions I trust...\nAssumptions to validate..."));
      cards.push(ownerPref("model_pick", "Model pick + deal-breakers.", "Model I'm leaning toward...\nDeal-breakers..."));
      cards.push(ownerPref("pricing", "Pricing hypothesis.", "Free tier ad slots...\nUpgrade price..."));
      cards.push(ownerPref("gtm", "First channel + metric.", "First channel...\nSuccess metric..."));
      cards.push(ownerPref("risk", "Legal/trust red lines.", "Disclosure language...\nRed lines..."));
    } else if (section === "execution") {
      const execBody = el("div", { class: "execution-body" },
        el("p", { class: "muted" }, "Demoted reference — public deck is canonical for external audiences."),
        el("p", {},
          el("a", { href: "marketing/index.html", target: "_blank", rel: "noopener" }, "marketing/index.html"),
          " · ",
          el("a", { href: "marketing/one-pager.html", target: "_blank", rel: "noopener" }, "one-pager"),
          " · ",
          el("a", { href: "marketing/content-kit.md", target: "_blank", rel: "noopener" }, "content-kit.md"),
        ),
        el("h3", {}, "Creative asset briefs"),
      );
      for (const asset of MARKETING_ASSETS) {
        const statusTone = asset.status === "ready" ? "success" : asset.status === "shipped" ? "info" : "neutral";
        const card = el("div", { class: "asset-card" },
          el("div", { class: "asset-card-head" },
            el("span", { class: "asset-card-title" }, asset.title),
            el("span", { class: "pill pill-" + statusTone }, asset.status),
            el("span", { class: "pill pill-neutral" }, asset.format),
          ),
          el("p", { class: "muted", style: "margin:0 0 0.35rem" }, asset.goal),
        );
        for (const [key, lines] of Object.entries(asset.copyBlocks || {})) {
          const txt = Array.isArray(lines) ? lines.join("\n") : String(lines);
          card.appendChild(el("div", { style: "margin-top:0.35rem" },
            el("strong", {}, key + ": "),
            copyBtn(key, txt),
            el("pre", { class: "copy-snippet" }, txt),
          ));
        }
        execBody.appendChild(card);
      }
      execBody.appendChild(el("h3", { style: "margin-top:1rem" }, "Persona × channel matrix (full)"));
      execBody.appendChild(el("div", { class: "messaging-grid" },
        tableEl(
          ["Persona", "Reddit", "GitHub README", "Landing", "Short video", "Email waitlist"],
          MARKETING_CHANNEL_MATRIX.map((row) => [
            row.persona,
            ...["reddit", "github_readme", "landing", "short_video", "email_waitlist"].map((ch) => {
              const cell = row.channels[ch];
              if (!cell) return "—";
              return el("div", {},
                el("div", {}, el("strong", {}, cell.campaign)),
                el("div", { class: "faint" }, cell.hook),
                el("code", { style: "font-size:0.7rem" }, cell.pillar),
              );
            }),
          ]),
        ),
      ));
      execBody.appendChild(el("h3", { style: "margin-top:1rem" }, "Campaign suite"));
      for (const c of MONETIZE_CAMPAIGNS) execBody.appendChild(renderCampaignCard(c));
      execBody.appendChild(el("h3", { style: "margin-top:1rem" }, "Copy snippet bank"));
      execBody.appendChild(el("pre", { class: "copy-snippet" }, MONETIZE_COPY_SNIPPETS.taglines.join("\n")));
      execBody.appendChild(copyBtn("taglines", MONETIZE_COPY_SNIPPETS.taglines.join("\n")));
      execBody.appendChild(el("pre", { class: "copy-snippet", style: "margin-top:0.5rem" }, MONETIZE_COPY_SNIPPETS.elevator30));
      execBody.appendChild(copyBtn("30s", MONETIZE_COPY_SNIPPETS.elevator30));
      cards.push(el("details", { class: "card execution-appendix", open: false },
        el("summary", {}, "Execution library (collapsed) — briefs, campaigns, snippets"),
        execBody,
      ));
      cards.push(ownerPref("creative", "Asset production notes.", "Ship first...\nBlocked on..."));
      cards.push(ownerPref("messaging", "Channel testing notes.", "Primary channel...\nHook to A/B..."));
      cards.push(ownerPref("campaign", "Tone and forbidden angles.", "Tone I like...\nNever do..."));
    }

    return el("section", { id: "panel-monetize", class: "panel" + (state.activeTab === "monetize" ? " active" : "") },
      el("h1", {}, "Launch thesis (internal)"),
      el("div", { class: "callout success", style: "margin-bottom:1rem" },
        el("div", { class: "callout-title" }, "Public-facing deck"),
        el("div", { class: "callout-body" },
          "Investor/audience showpiece: ",
          el("a", { href: "marketing/index.html", target: "_blank", rel: "noopener" }, "marketing/index.html"),
          " · ",
          el("a", { href: "marketing/one-pager.html", target: "_blank", rel: "noopener" }, "one-pager"),
          " · ",
          el("a", { href: "marketing/content-kit.md", target: "_blank", rel: "noopener" }, "content-kit.md"),
          ". This panel is the internal investment thesis — execution collateral lives in the appendix.",
        ),
      ),
      el("p", { class: "muted" }, "Thesis sections first; assumptions and kill criteria in Decisions. Your preference lanes persist under legacy note ids."),
      monetizeSubnav(),
      ...cards,
      el("div", { class: "card-row", style: "margin-top:1rem" },
        el("button", { type: "button", class: "btn btn-primary btn-sm", onClick: () => exportMarketingBrief() }, "Export marketing brief"),
        el("span", { class: "muted", style: "font-size:0.85rem" }, "Copies MARKETING_FEATURES + campaigns + snippets to clipboard as Markdown"),
      ),
      el("h2", {}, "Free notes"),
      ta,
    );
  }
'''

# Fix architecture section - the template broke because I used broken string concat
# Rebuild architecture block with proper SVG injection
arch_block = f'''    }} else if (section === "architecture") {{
      const runSvg = `{run_js}`;
      const endpointSvg = `{ep_js}`;
      const PACKAGING_TIERS = [
        ["Clone and run (today)", "Yes", "User installs Python 3.11+, pip install -e \\".\\[dev\\]", Chrome for Connect. Runs python server.py."],
        ["pipx / pip install", "Yes (Python must exist)", "Console entry point (baklog) — cleaner, still needs Python on the machine."],
        ["PyInstaller / Briefcase frozen binary", "No", "Bundles interpreter + deps into BAKLOG.exe / .app. Build per OS. Gotcha: ROOT path must use sys._MEIPASS when frozen. Chrome still required (BAKLOG_CHROME_PATH)."],
        ["Docker", "No (needs Docker)", "Wrong fit for non-technical users; self-hosters only."],
      ];
      cards.push(el("div", {{ class: "card" }},
        el("h2", {{}}, "How it runs (today)"),
        el("p", {{ class: "muted" }}, "Local engine on your PC; two browser windows. Privacy moat = architecture, not marketing copy."),
        el("div", {{ class: "card", html: runSvg }}),
        el("p", {{ class: "muted", style: "margin-top:0.5rem" }}, "Stores → fetchers → local JSON → dashboard. No BAKLOG cloud in the middle."),
        el("h3", {{}}, "First run"),
        el("ol", {{}},
          el("li", {{}}, "Run ", el("code", {{}}, "python server.py"), " → ", el("code", {{}}, "http://127.0.0.1:8765"), "."),
          el("li", {{}}, "Connections → Connect each store (sign-in popup)."),
          el("li", {{}}, "Refresh — ", el("code", {{}}, "games_*.json"), " fills; dashboard paints live."),
        ),
      ));
      cards.push(el("div", {{ class: "card" }},
        el("h2", {{}}, "Distribution endpoint: B (locked)"),
        el("p", {{ class: "muted" }}, "Local-first core + optional derived-catalog sync + hosted read-only demo. Full hosted fetch (C) rejected."),
        el("div", {{ class: "card", html: endpointSvg }}),
        el("p", {{ class: "muted", style: "margin-top:0.5rem" }}, codeText("p4_packaging"), " · ", codeText("p4_hosted_demo"), " · ", codeText("bs_multiuser_app_login"), " when hosting decided."),
      ));
      cards.push(el("div", {{ class: "card" }},
        el("h2", {{}}, "Engine vs frontend · Python requirement"),
        el("ul", {{}},
          el("li", {{}}, el("strong", {{}}, "UI: "), el("code", {{}}, "index.html"), " + ", el("code", {{}}, "js/"), " — static files served by ", el("code", {{}}, "server.py"), "."),
          el("li", {{}}, el("strong", {{}}, "Workers: "), "fetch_*.py write ", el("code", {{}}, "games_*.json"), "; secrets in OS keyring + ", el("code", {{}}, "auth/secrets.bin"), "."),
          el("li", {{}}, el("strong", {{}}, "Today: Python required. "), "Frozen binary removes Python; Chrome still required for Connect."),
        ),
        tableEl(["Approach", "Python required?", "Notes"], PACKAGING_TIERS.map((r) => r)),
      ));
      cards.push(el("div", {{ class: "card" }},
        el("h2", {{}}, "B vs full-hosted C"),
        el("p", {{}}, el("strong", {{}}, "Endpoint locked: B. "), "Optional sync = derived catalog only; never credentials; never server-side fetch."),
        el("ul", {{}},
          el("li", {{}}, el("strong", {{}}, "C temptation: "), "zero-install URL, mobile-anywhere, native sync."),
          el("li", {{}}, el("strong", {{}}, "C rejected: "), "breaks privacy thesis, ", codeText("bs_tos"), " guardrails, breach target + infra cost."),
          el("li", {{}}, el("strong", {{}}, "Sanctioned slivers: "), "read-only demo, opt-in catalog sync, later hosted login after counsel."),
        ),
      ));
      cards.push(ownerPref("howitworks", "Notes on how you explain the model to a new user.", "The one-liner I use...\\nWhat confuses people...\\nThe analogy that clicks..."));
'''

# Split NEW at architecture placeholder and splice
parts = NEW.split('    } else if (section === "architecture") {')
if len(parts) != 2:
    raise SystemExit("architecture split failed")
before_arch = parts[0]
after_arch = parts[1]
# drop broken architecture through gtm start
after_arch = re.sub(
    r'^[\s\S]*?    \} else if \(section === "gtm"\)',
    '    } else if (section === "gtm")',
    after_arch,
    count=1,
)
NEW = before_arch + arch_block + after_arch

start = text.index("  function panelMonetize() {")
end = text.index("\n  // ---------- Render: all panels ----------", start)
old = text[start:end]
text = text[:start] + NEW + text[end:]

TRACKER.write_text(text, encoding="utf-8")
print("Replaced panelMonetize:", len(old), "->", len(NEW))
