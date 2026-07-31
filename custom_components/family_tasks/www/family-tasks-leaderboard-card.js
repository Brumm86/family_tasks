/**
 * Family Tasks Leaderboard Lovelace card.
 *
 * Framework-free custom element (no lit/build step) that ranks family
 * members by points earned, with switchable "Woche" (week) / "Monat" (month)
 * views. Reads member names/icons/participation from the family_tasks member
 * storage collection (family_tasks/member/subscribe, same API the main
 * family-tasks-card uses) and points from the integration's per-member
 * points sensor, whose extra_state_attributes carry points_today,
 * points_week, points_month, points_available alongside the sensor's
 * all-time total state (see FamilyTasksMemberPointsSensor in sensor.py).
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
 *
 * Only family members participating in the reward system show up on the
 * ranking (v0.9) - see the "Nimmt am Belohnungssystem teil" checkbox in the
 * main card's Familienmitglieder section (CONF_MEMBER_REWARDS_OPT_IN in
 * const.py); a household can e.g. keep the parents off the board entirely.
 * Each ranked row also shows that member's current reward-point balance
 * (points_available) by name, independent of which Woche/Monat tab is
 * selected - that balance, not the weekly/monthly ranking figure, is the
 * actual currency the reward system below spends.
 *
 * Rewards (v0.9): this card now owns the whole reward system - it used to
 * live in the main family-tasks-card, see that file's history. Parents
 * maintain a catalog of rewards, each with a name and a price in points
 * (admin-only CRUD, family_tasks/reward/*, same storage-collection pattern
 * as the main card's task/member management). Every catalog item is always
 * visible to everyone, including children, together with its price - so a
 * child can always see what's available and how many points it costs, even
 * if they can't currently afford it. A participating member (see above) can
 * select a reward they can afford ("Auswählen") and confirm the purchase
 * ("Bestätigen"); confirming calls the non-admin family_tasks/reward_redemption/redeem
 * command, which re-checks server-side that the caller participates in the
 * reward system and can actually afford it before creating the redemption -
 * creating that redemption entry *is* the point deduction, there is no
 * separate balance to update (see ws_redeem_reward in storage.py). Parents
 * can mark a redemption "erledigt" once they've handed the reward over; a
 * child cannot, even with an HA admin account (mirrors every other
 * parent-only action in this integration).
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

  // "1 Punkt" vs. "2 Punkte" (v0.10) - every place a reward's point cost or
  // a member's point balance is rendered as the word "Punkte" (not the
  // "Pkt." abbreviation used elsewhere) goes through this so the singular
  // case reads correctly.
  function pointsLabel(value) {
    const n = Number(value) || 0;
    return `${esc(n)} ${n === 1 ? "Punkt" : "Punkte"}`;
  }

  function emptyRewardForm() {
    return { name: "", icon: "", points_cost: 0 };
  }

  function rewardToForm(reward) {
    return {
      name: reward?.name ?? "",
      icon: reward?.icon ?? "",
      points_cost: reward?.points_cost ?? 0,
    };
  }

  class FamilyTasksLeaderboardCard extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: "open" });
      this._members = {};
      this._rewards = {};
      this._redemptions = {};
      this._hass = null;
      this._subscribed = false;
      this._listenersAttached = false;
      this._lastSignature = null;
      this._view = undefined;
      this._rewardFormOpen = false;
      this._editingRewardId = null;
      this._rewardForm = emptyRewardForm();
      // Which catalog reward is currently showing its "wirklich einlösen?"
      // confirm step for the current user - only one at a time.
      this._pendingRedeemId = null;
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
      return (
        3 +
        Object.keys(this._members).length +
        Object.keys(this._rewards).length +
        Object.keys(this._redemptions).length
      );
    }

    _isAdmin() {
      return this._hass?.user ? !!this._hass.user.is_admin : true;
    }

    // Mirrors the main card's _currentMemberId/_isChildUser: the family
    // member linked (via the "person" integration) to the logged-in HA user.
    _currentMemberId() {
      if (!this._hass?.user) return null;
      const userId = this._hass.user.id;
      const person = Object.values(this._hass.states).find(
        (s) => s.entity_id.startsWith("person.") && s.attributes.user_id === userId
      );
      if (!person) return null;
      const entry = Object.entries(this._members).find(
        ([, member]) => member.person_entity_id === person.entity_id
      );
      return entry ? entry[0] : null;
    }

    _currentMember() {
      const id = this._currentMemberId();
      return id ? this._members[id] : null;
    }

    _isChildUser() {
      return this._currentMember()?.role === "child";
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
      if (this._unsubRewards) this._unsubRewards();
      if (this._unsubRedemptions) this._unsubRedemptions();
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
      const handle = (store, idKey) => (changes) => {
        for (const change of changes) {
          const id = change[idKey];
          if (change.change_type === "removed") delete store[id];
          else store[id] = change.item;
        }
        this._render();
      };
      this._unsubMembers = await this._hass.connection.subscribeMessage(
        handle(this._members, "member_id"),
        { type: "family_tasks/member/subscribe" }
      );
      this._unsubRewards = await this._hass.connection.subscribeMessage(
        handle(this._rewards, "reward_id"),
        { type: "family_tasks/reward/subscribe" }
      );
      this._unsubRedemptions = await this._hass.connection.subscribeMessage(
        handle(this._redemptions, "reward_redemption_id"),
        { type: "family_tasks/reward_redemption/subscribe" }
      );
    }

    _pointsSensorForMember(memberId) {
      if (!this._hass) return null;
      return Object.values(this._hass.states).find(
        (s) => s.entity_id.startsWith("sensor.") && s.attributes.member_id === memberId
      );
    }

    // Current spendable balance (v0.9): all-time points minus everything
    // already redeemed - see MemberSummaryData.points_available in
    // coordinator.py. Always shown regardless of the Woche/Monat tab, since
    // it's the actual currency the reward catalog below spends, not a
    // per-period ranking figure.
    _availablePointsFor(memberId) {
      return Number(this._pointsSensorForMember(memberId)?.attributes?.points_available ?? 0);
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
        // Only members who take part in the reward system show up here at
        // all (v0.9) - a household may only want its children competing for
        // points, not the parents themselves.
        .filter((entry) => entry.member.participates_in_rewards !== false)
        .sort((a, b) => b.points - a.points);
    }

    // --- rewards actions ---------------------------------------------------

    _openRewardForm(rewardId) {
      this._editingRewardId = rewardId;
      this._rewardForm = rewardToForm(rewardId ? this._rewards[rewardId] : null);
      this._rewardFormOpen = true;
      this._render();
    }

    _closeRewardForm() {
      this._rewardFormOpen = false;
      this._editingRewardId = null;
      this._render();
    }

    async _saveReward() {
      const f = this._rewardForm;
      if (!f.name.trim()) return;
      const payload = {
        name: f.name.trim(),
        points_cost: Math.max(0, Number(f.points_cost) || 0),
      };
      if (f.icon) payload.icon = f.icon.trim();
      if (this._editingRewardId) {
        await this._hass.callWS({
          type: "family_tasks/reward/update",
          reward_id: this._editingRewardId,
          ...payload,
        });
      } else {
        await this._hass.callWS({ type: "family_tasks/reward/create", ...payload });
      }
      this._closeRewardForm();
    }

    async _deleteReward(rewardId) {
      const name = this._rewards[rewardId]?.name ?? rewardId;
      if (!confirm(`Belohnung "${name}" wirklich löschen?`)) return;
      await this._hass.callWS({ type: "family_tasks/reward/delete", reward_id: rewardId });
    }

    _selectReward(rewardId) {
      this._pendingRedeemId = rewardId;
      this._render();
    }

    _cancelRedeem() {
      this._pendingRedeemId = null;
      this._render();
    }

    // Non-admin redeem: the backend independently re-checks that the caller
    // participates in the reward system and can actually afford the reward
    // (see ws_redeem_reward in storage.py) - the client-side "disabled"
    // state on the "Auswählen" button is just there to not offer it in the
    // first place, not the actual guard.
    async _confirmRedeem(rewardId) {
      await this._hass.callWS({ type: "family_tasks/reward_redemption/redeem", reward_id: rewardId });
      this._pendingRedeemId = null;
      this._render();
    }

    async _fulfillRedemption(redemptionId) {
      await this._hass.callWS({
        type: "family_tasks/reward_redemption/update",
        reward_redemption_id: redemptionId,
        fulfilled: true,
      });
    }

    // --- rendering ---------------------------------------------------------

    _render() {
      if (!this._hass) return;
      const title = esc(this._config.title ?? "Bestenliste");
      const ranked = this._rankedMembers();
      const maxPoints = ranked.length ? Math.max(...ranked.map((r) => r.points), 1) : 1;
      const isAdmin = this._isAdmin();
      const isChildUser = this._isChildUser();
      // Same rule as the main card's canManageMembers - a "child"-linked
      // user never gets catalog/redemption management, regardless of their
      // HA admin flag (enforced server-side too, see
      // RewardRedemptionStorageCollectionWebsocket in storage.py).
      const canManageRewards = isAdmin && !isChildUser;
      const currentMemberId = this._currentMemberId();

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
                      const available = this._availablePointsFor(entry.id);
                      return `
                <div class="row">
                  <div class="rank">${index + 1}</div>
                  <div class="row-main">
                    <div class="row-top">
                      <span class="name">${entry.member.icon ? `<ha-icon icon="${esc(entry.member.icon)}"></ha-icon> ` : ""}${esc(entry.member.name)}</span>
                      <span class="points">${esc(entry.points)} Pkt.</span>
                    </div>
                    <div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div>
                    <div class="balance">${esc(entry.member.name)}: ${pointsLabel(available)} verfügbar</div>
                  </div>
                </div>`;
                    })
                    .join("")}</div>`
                : `<p class="muted">Noch keine teilnehmenden Familienmitglieder.</p>`
            }

            ${this._renderRewardsSection(canManageRewards, currentMemberId)}
          </div>
        </ha-card>
      `;
      this._attachListenersOnce();
    }

    _renderRewardsSection(canManageRewards, currentMemberId) {
      const currentMember = currentMemberId ? this._members[currentMemberId] : null;
      const currentParticipates = !!currentMember && currentMember.participates_in_rewards !== false;
      const availablePoints = currentMemberId ? this._availablePointsFor(currentMemberId) : 0;

      const rewardIds = Object.keys(this._rewards).sort(
        (a, b) => (this._rewards[a].points_cost ?? 0) - (this._rewards[b].points_cost ?? 0)
      );
      // Every catalog reward and its price is always visible to everyone
      // (v0.9) - a child should always be able to see what's available and
      // how many points it costs, even if they can't afford it yet. Only the
      // "Auswählen" action is gated by participation + affordability, and
      // "Bearbeiten"/"Löschen" by canManageRewards.
      const catalogList = rewardIds.length
        ? `<div class="list">${rewardIds
            .map((id) => {
              const r = this._rewards[id];
              const cost = r.points_cost ?? 0;
              const affordable = currentParticipates && availablePoints >= cost;
              const isPending = this._pendingRedeemId === id;
              return `
                <div class="row-wrap">
                  <div class="row">
                    <div class="row-main">
                      <span class="name">${r.icon ? `<ha-icon icon="${esc(r.icon)}"></ha-icon> ` : ""}${esc(r.name)}</span>
                      <span class="muted">${pointsLabel(cost)}</span>
                    </div>
                    <div class="row-actions">
                      ${currentMemberId && currentParticipates ? `<button data-action="select-reward" data-reward-id="${id}" ${affordable ? "" : "disabled"}>Auswählen</button>` : ""}
                      ${canManageRewards ? `
                      <button data-action="edit-reward" data-reward-id="${id}">Bearbeiten</button>
                      <button data-action="delete-reward" data-reward-id="${id}" class="danger">Löschen</button>` : ""}
                    </div>
                  </div>
                  ${isPending ? `
                  <div class="confirm-row">
                    <span>„${esc(r.name)}" für ${pointsLabel(cost)} einlösen?</span>
                    <button data-action="confirm-redeem" data-reward-id="${id}">Bestätigen</button>
                    <button type="button" class="link" data-action="cancel-redeem">Abbrechen</button>
                  </div>` : ""}
                </div>`;
            })
            .join("")}</div>`
        : `<p class="muted">Noch keine Belohnungen angelegt.</p>`;

      const redemptionIds = Object.keys(this._redemptions).sort((a, b) =>
        (this._redemptions[b].redeemed_at ?? "").localeCompare(this._redemptions[a].redeemed_at ?? "")
      );
      const historyList = redemptionIds.length
        ? `<div class="list">${redemptionIds
            .map((id) => {
              const r = this._redemptions[id];
              return `
                <div class="row">
                  <div class="row-main">
                    <span class="name">${esc(r.member_name)} · ${esc(r.reward_name)}</span>
                    <span class="muted">${pointsLabel(r.points_cost ?? 0)}${r.fulfilled ? " · erledigt" : ""}</span>
                  </div>
                  ${!r.fulfilled && canManageRewards ? `
                  <div class="row-actions">
                    <button data-action="fulfill-redemption" data-redemption-id="${id}">Als erledigt markieren</button>
                  </div>` : ""}
                </div>`;
            })
            .join("")}</div>`
        : `<p class="muted">Noch keine Belohnungen eingelöst.</p>`;

      return `
        <div class="section-header">
          <h3>Belohnungen</h3>
        </div>
        ${currentMemberId ? `<p class="muted">Dein Guthaben: ${pointsLabel(availablePoints)}${currentParticipates ? "" : " (nimmt nicht am Belohnungssystem teil)"}</p>` : ""}
        ${catalogList}
        ${canManageRewards ? `
          ${this._rewardFormOpen ? this._renderRewardForm() : `<button class="add" data-action="new-reward">+ Belohnung hinzufügen</button>`}
        ` : ""}
        <h4>Bisherige Einlösungen</h4>
        ${historyList}
      `;
    }

    _renderRewardForm() {
      const f = this._rewardForm;
      return `
        <form class="form" data-form="reward">
          <label>Name<input type="text" data-reward-field="name" placeholder="z. B. Filmabend aussuchen" value="${esc(f.name)}" required></label>
          <label>Icon (optional)<input type="text" data-reward-field="icon" placeholder="mdi:gift" value="${esc(f.icon)}"></label>
          <label>Preis (Punkte)<input type="number" min="0" data-reward-field="points_cost" value="${esc(f.points_cost)}"></label>
          <div class="form-actions">
            <button type="submit" data-action="save-reward">Speichern</button>
            <button type="button" data-action="cancel-reward-form">Abbrechen</button>
          </div>
        </form>`;
    }

    _attachListenersOnce() {
      if (this._listenersAttached) return;
      this._listenersAttached = true;

      this.shadowRoot.addEventListener("submit", (ev) => {
        ev.preventDefault();
        const form = ev.target.closest('[data-form="reward"]');
        if (form) this._saveReward();
      });

      this.shadowRoot.addEventListener("change", (ev) => {
        const el = ev.target.closest("[data-reward-field]");
        if (!el) return;
        this._rewardForm[el.dataset.rewardField] = el.value;
        this._render();
      });

      this.shadowRoot.addEventListener("click", (ev) => {
        const el = ev.target.closest("[data-action]");
        if (!el) return;
        const action = el.dataset.action;
        if (action === "select-view") {
          this._view = el.dataset.view;
          this._saveUiState();
          this._render();
        } else if (action === "select-reward") {
          this._selectReward(el.dataset.rewardId);
        } else if (action === "cancel-redeem") {
          this._cancelRedeem();
        } else if (action === "confirm-redeem") {
          this._confirmRedeem(el.dataset.rewardId);
        } else if (action === "new-reward") {
          // Defense-in-depth, same reasoning as the main card's edit/delete
          // gating - the backend enforces this too regardless (see
          // RewardRedemptionStorageCollectionWebsocket in storage.py).
          if (this._isAdmin() && !this._isChildUser()) this._openRewardForm(null);
        } else if (action === "edit-reward") {
          if (this._isAdmin() && !this._isChildUser()) this._openRewardForm(el.dataset.rewardId);
        } else if (action === "cancel-reward-form") {
          this._closeRewardForm();
        } else if (action === "delete-reward") {
          if (this._isAdmin() && !this._isChildUser()) this._deleteReward(el.dataset.rewardId);
        } else if (action === "fulfill-redemption") {
          if (this._isAdmin() && !this._isChildUser()) this._fulfillRedemption(el.dataset.redemptionId);
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
        .row-wrap { display: flex; flex-direction: column; gap: 4px; }
        .row { display: flex; align-items: center; gap: 10px; }
        .rank { width: 22px; text-align: center; font-weight: 500; color: var(--secondary-text-color); flex-shrink: 0; }
        .row-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
        .row-top { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
        .name { font-weight: 500; display: flex; align-items: center; gap: 4px; }
        .points { font-size: 0.85em; color: var(--secondary-text-color); flex-shrink: 0; }
        .balance { font-size: 0.8em; color: var(--secondary-text-color); }
        .bar-track { height: 6px; border-radius: 3px; background: var(--secondary-background-color, #f2f2f2); overflow: hidden; }
        .bar-fill { height: 100%; border-radius: 3px; background: var(--primary-color); }
        .section-header { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
        .section-header h3 { margin: 20px 0 8px; }
        h4 { margin: 16px 0 8px; font-size: 0.95em; color: var(--secondary-text-color); }
        .row-actions { display: flex; gap: 4px; flex-wrap: wrap; justify-content: flex-end; }
        button { border: none; border-radius: 6px; padding: 6px 10px; font-size: 0.85em;
                 background: var(--primary-color); color: var(--text-primary-color, #fff); cursor: pointer; }
        button:disabled { opacity: 0.5; cursor: default; }
        button.danger { background: var(--error-color, #db4437); }
        button.add { background: none; color: var(--primary-color); padding: 8px 0; text-align: left; }
        button.link { background: none; color: var(--primary-color); padding: 6px 10px; }
        .confirm-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding: 8px;
                       border-radius: 8px; background: var(--secondary-background-color, #f2f2f2); font-size: 0.9em; }
        .form { display: flex; flex-direction: column; gap: 10px; margin: 8px 0 16px;
                padding: 12px; border-radius: 8px; border: 1px solid var(--divider-color, #e0e0e0); }
        .form label { display: flex; flex-direction: column; gap: 4px; font-size: 0.9em; }
        .form input { padding: 6px; border-radius: 4px; border: 1px solid var(--divider-color, #ccc);
                      background: var(--card-background-color, #fff); color: inherit; }
        .form-actions { display: flex; gap: 8px; justify-content: flex-end; }
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
    description: "Punkte-Bestenliste und Belohnungen (Punkte-Shop) der Familie.",
  });
})();
