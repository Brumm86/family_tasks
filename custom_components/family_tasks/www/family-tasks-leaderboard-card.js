/**
 * Family Tasks Leaderboard Lovelace card.
 *
 * Framework-free custom element (no lit/build step) that ranks family
 * members by points earned, with separate "Woche" (week) and "Monat"
 * (month) views. Reads member names/icons from the family_tasks member
 * storage collection (family_tasks/member/subscribe, same API the main
 * family-tasks-card uses) and points from the integration's per-member
 * points sensor, whose extra_state_attributes carry points_today,
 * points_week, points_month alongside the sensor's all-time total state
 * (see FamilyTasksMemberPointsSensor in sensor.py).
 *
 * Registered automatically by the backend (see __init__.py, add_extra_js_url)
 * - no manual Lovelace resource needs to be added. Add the card via
 * "type: custom:family-tasks-leaderboard-card" or pick "Family Tasks
 * Leaderboard" in the card picker.
 *
 * Card config options (all optional):
 *   title: "..."       - card title, defaults to "Bestenliste"
 *   default_view: "week" | "month" - which tab is selected the very first
 *                         time the card runs on a device (only used once -
 *                         after that the card's own persisted choice, saved
 *                         to localStorage per browser/device keyed by the
 *                         card's title, wins so a dashboard reload doesn't
 *                         undo a manual tab switch). Defaults to "week".
 */
(() => {
  const VIEWS = {
    week: { label: "Woche", attr: "points_week" },
    month: { label: "Monat", attr: "points_month" },
  };

  function esc(value) {
    return String(value ?? "").replace(
      /[&<>"']/g,
      (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );
  }

  class FamilyTasksLeaderboardCard extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: "open" });
      this._members = {};
      this._hass = null;
      this._subscribed = false;
      this._lastSignature = null;
      this._view = undefined;
    }

    setConfig(config) {
      this._config = config || {};
      if (this._view === undefined) {
        const saved = this._loadUiState();
        const initial = saved?.view ?? this._config.default_view ?? "week";
        this._view = VIEWS[initial] ? initial : "week";
      }
    }

    _storageKey() {
      return `family-tasks-leaderboard-card-ui-state:${this._config?.title ?? "default"}`;
    }

    _loadUiState() {
      try {
        const raw = window.localStorage.getItem(this._storageKey());
        return raw ? JSON.parse(raw) : null;
      } catch (err) {
        return null;
      }
    }

    _saveUiState() {
      try {
        window.localStorage.setItem(this._storageKey(), JSON.stringify({ view: this._view }));
      } catch (err) {
        // Storage unavailable/full - the tab still works for this session,
        // it just won't be remembered next time.
      }
    }

    static getStubConfig() {
      return { type: "custom:family-tasks-leaderboard-card", title: "Bestenliste" };
    }

    getCardSize() {
      return 2 + Object.keys(this._members).length;
    }

    set hass(hass) {
      const first = !this._hass;
      this._hass = hass;
      if (!this._subscribed) {
        this._subscribed = true;
        this._subscribe();
      }
      const signature = this._relevantStatesSignature();
      if (first || signature !== this._lastSignature) {
        this._lastSignature = signature;
        this._render();
      }
    }

    disconnectedCallback() {
      if (this._unsubMembers) this._unsubMembers();
    }

    // Only the per-member points sensors should trigger a re-render.
    _relevantStatesSignature() {
      if (!this._hass) return "";
      const parts = [];
      for (const state of Object.values(this._hass.states)) {
        if (state.entity_id.startsWith("sensor.") && state.attributes.member_id) {
          parts.push(`${state.entity_id}:${state.state}:${state.last_changed}`);
        }
      }
      parts.sort();
      return parts.join("|");
    }

    async _subscribe() {
      this._unsubMembers = await this._hass.connection.subscribeMessage(
        (changes) => {
          for (const change of changes) {
            if (change.change_type === "removed") delete this._members[change.member_id];
            else this._members[change.member_id] = change.item;
          }
          this._render();
        },
        { type: "family_tasks/member/subscribe" }
      );
    }

    _pointsSensorForMember(memberId) {
      if (!this._hass) return null;
      return Object.values(this._hass.states).find(
        (s) => s.entity_id.startsWith("sensor.") && s.attributes.member_id === memberId
      );
    }

    _rankedMembers() {
      const attr = VIEWS[this._view].attr;
      return Object.keys(this._members)
        .map((id) => {
          const member = this._members[id];
          const sensor = this._pointsSensorForMember(id);
          const points = Number(sensor?.attributes?.[attr] ?? 0);
          return { id, member, points };
        })
        .filter((entry) => entry.member.active !== false)
        .sort((a, b) => b.points - a.points);
    }

    _render() {
      if (!this._hass) return;
      const title = esc(this._config.title ?? "Bestenliste");
      const ranked = this._rankedMembers();
      const maxPoints = ranked.length ? Math.max(...ranked.map((r) => r.points), 1) : 1;

      this.shadowRoot.innerHTML = `
        <style>${this._styles()}</style>
        <ha-card>
          <div class="card-header">
            <div class="name">${title}</div>
          </div>
          <div class="card-content">
            <div class="tabs">
              ${Object.entries(VIEWS)
                .map(
                  ([value, view]) => `
                <button
                  class="tab ${this._view === value ? "active" : ""}"
                  data-action="select-view"
                  data-view="${value}"
                >${esc(view.label)}</button>`
                )
                .join("")}
            </div>
            ${
              ranked.length
                ? `<div class="list">${ranked
                    .map((entry, index) => {
                      const pct = Math.round((entry.points / maxPoints) * 100);
                      return `
                <div class="row">
                  <div class="rank">${index + 1}</div>
                  <div class="row-main">
                    <div class="row-top">
                      <span class="name">${entry.member.icon ? `<ha-icon icon="${esc(entry.member.icon)}"></ha-icon> ` : ""}${esc(entry.member.name)}</span>
                      <span class="points">${esc(entry.points)} Pkt.</span>
                    </div>
                    <div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div>
                  </div>
                </div>`;
                    })
                    .join("")}</div>`
                : `<p class="muted">Noch keine Familienmitglieder angelegt.</p>`
            }
          </div>
        </ha-card>
      `;
      this._attachListeners();
    }

    _attachListeners() {
      this.shadowRoot.addEventListener("click", (ev) => {
        const el = ev.target.closest("[data-action]");
        if (!el) return;
        if (el.dataset.action === "select-view") {
          this._view = el.dataset.view;
          this._saveUiState();
          this._render();
        }
      });
    }

    _styles() {
      return `
        .card-header { display: flex; align-items: center; justify-content: space-between; gap: 8px;
                       padding: 16px 16px 0; }
        .card-header .name { font-size: 1.2em; font-weight: 400; letter-spacing: -0.012em;
                              line-height: 1.2; color: var(--ha-card-header-color, var(--primary-text-color)); }
        .card-content { padding: 8px 16px 16px; }
        .tabs { display: flex; gap: 4px; margin: 8px 0 12px; }
        .tab { border: none; border-radius: 6px; padding: 6px 14px; font-size: 0.85em;
               background: var(--secondary-background-color, #f2f2f2); color: var(--secondary-text-color);
               cursor: pointer; }
        .tab.active { background: var(--primary-color); color: var(--text-primary-color, #fff); }
        .muted { color: var(--secondary-text-color); font-size: 0.9em; }
        .list { display: flex; flex-direction: column; gap: 8px; }
        .row { display: flex; align-items: center; gap: 10px; }
        .rank { width: 22px; text-align: center; font-weight: 500; color: var(--secondary-text-color); flex-shrink: 0; }
        .row-main { flex: 1; min-width: 0; }
        .row-top { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; margin-bottom: 4px; }
        .name { font-weight: 500; display: flex; align-items: center; gap: 4px; }
        .points { font-size: 0.85em; color: var(--secondary-text-color); flex-shrink: 0; }
        .bar-track { height: 6px; border-radius: 3px; background: var(--secondary-background-color, #f2f2f2); overflow: hidden; }
        .bar-fill { height: 100%; border-radius: 3px; background: var(--primary-color); }
      `;
    }
  }

  if (!customElements.get("family-tasks-leaderboard-card")) {
    customElements.define("family-tasks-leaderboard-card", FamilyTasksLeaderboardCard);
  }

  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "family-tasks-leaderboard-card",
    name: "Family Tasks Leaderboard",
    description: "Punkte-Bestenliste der Familie - Wochen- und Monatsansicht.",
  });
})();
