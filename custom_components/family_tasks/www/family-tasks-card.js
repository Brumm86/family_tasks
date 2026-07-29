/**
 * Family Tasks Lovelace card.
 *
 * Framework-free custom element (no lit/build step) that manages tasks and
 * family members through the family_tasks storage-collection websocket API
 * (family_tasks/task/*, family_tasks/member/*) and shows their live,
 * coordinator-computed status via the integration's sensor entities.
 *
 * Registered automatically by the backend (see __init__.py, add_extra_js_url)
 * - no manual Lovelace resource needs to be added. Add the card via
 * "type: custom:family-tasks-card" or pick "Family Tasks" in the card picker.
 *
 * Card config options (all optional):
 *   hide_add_member: true    - hide the "+ Mitglied hinzufügen" button/form
 *                               (existing members can still be edited/deleted)
 *   hide_not_due_tasks: true - start with only currently-due tasks shown
 *                               (idle/done hidden; can still be toggled from
 *                               the card itself)
 *   hide_members_list: true  - start with the family members list collapsed
 *                               (can still be toggled from the card itself)
 *
 * Child tasks: a task assigned to a member with role "child" isn't finished
 * the moment the child taps "Erledigt" - the task shows "Wartet auf
 * Bestätigung" and an auto-generated task appears for the household's
 * parents. A parent completing *that* task finalizes the child's completion
 * (points + rotation); skipping it rejects the claim. These auto-generated
 * tasks are read-only (no edit/delete) since the coordinator manages them.
 */
(() => {
  const WEEKDAY_LABELS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];
  const STATUS_LABELS = {
    idle: "Wartet auf Sensor",
    pending: "Offen",
    overdue: "Überfällig",
    awaiting_confirmation: "Wartet auf Bestätigung",
    done: "Erledigt",
  };
  const STATUS_COLORS = {
    idle: "var(--disabled-text-color, #9e9e9e)",
    pending: "var(--warning-color, #ff9800)",
    overdue: "var(--error-color, #db4437)",
    awaiting_confirmation: "var(--info-color, #039be5)",
    done: "var(--success-color, #43a047)",
  };
  // Statuses considered "currently due" by the hide-not-due toggle: an
  // occurrence that needs someone to act on it right now.
  const DUE_STATUSES = ["pending", "overdue", "awaiting_confirmation"];
  const STRATEGY_LABELS = { round_robin: "Reihum", random: "Zufällig", fixed: "Fest zugewiesen" };
  const RECURRENCE_LABELS = {
    daily: "Täglich",
    weekly: "Wöchentlich (Wochentage)",
    interval_days: "Alle N Tage",
    trigger: "Sensor-Ereignis",
  };
  const TRIGGER_KIND_LABELS = {
    state: "Status (z. B. Binärsensor)",
    numeric_state: "Schwellenwert (Zahl)",
  };
  const THRESHOLD_DIRECTION_LABELS = {
    above: "Überschreitet",
    below: "Unterschreitet",
  };
  const MEMBER_ROLE_LABELS = {
    parent: "Elternteil",
    child: "Kind (Aufgaben brauchen Eltern-Bestätigung)",
  };

  function esc(value) {
    return String(value ?? "").replace(
      /[&<>"']/g,
      (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );
  }

  function emptyTriggerForm() {
    // "direction"/"value" drive the numeric_state UI: a single threshold to
    // cross (above OR below), not a from-x-to-y range - see storage.py's
    // _require_single_threshold. Mapped to/from the backend's above/below
    // fields in taskToForm() / _saveTask().
    return { kind: "state", entity_id: "", to_state: "on", direction: "above", value: "" };
  }

  function emptyTaskForm() {
    return {
      name: "",
      points: 0,
      icon: "",
      enabled: true,
      due_time: "",
      overdue_after_minutes: 60,
      recurrence: {
        type: "daily",
        interval: 1,
        weekdays: [0],
        anchor_date: "",
        trigger: emptyTriggerForm(),
      },
      rotation: { member_ids: [], strategy: "round_robin" },
    };
  }

  function emptyMemberForm() {
    return { name: "", person_entity_id: "", icon: "", active: true, role: "parent" };
  }

  function taskToForm(task) {
    return {
      name: task.name ?? "",
      points: task.points ?? 0,
      icon: task.icon ?? "",
      enabled: task.enabled !== false,
      due_time: task.due_time ?? "",
      overdue_after_minutes: task.overdue_after_minutes ?? 60,
      recurrence: {
        type: task.recurrence?.type ?? "daily",
        interval: task.recurrence?.interval ?? 1,
        weekdays: task.recurrence?.weekdays ?? [0],
        anchor_date: task.recurrence?.anchor_date ?? "",
        trigger: (() => {
          const t = task.recurrence?.trigger;
          const hasBelow = t?.below !== undefined && t?.below !== null;
          return {
            kind: t?.kind ?? "state",
            entity_id: t?.entity_id ?? "",
            to_state: t?.to_state ?? "on",
            direction: hasBelow ? "below" : "above",
            value: hasBelow ? t.below : t?.above ?? "",
          };
        })(),
      },
      rotation: {
        member_ids: [...(task.rotation?.member_ids ?? [])],
        strategy: task.rotation?.strategy ?? "round_robin",
      },
    };
  }

  function memberToForm(member) {
    return {
      name: member.name ?? "",
      person_entity_id: member.person_entity_id ?? "",
      icon: member.icon ?? "",
      active: member.active !== false,
      role: member.role ?? "parent",
    };
  }

  class FamilyTasksCard extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: "open" });
      this._tasks = {};
      this._members = {};
      this._hass = null;
      this._subscribed = false;
      this._listenersAttached = false;
      this._lastSignature = null;
      this._taskFormOpen = false;
      this._memberFormOpen = false;
      this._editingTaskId = null;
      this._editingMemberId = null;
      this._taskForm = emptyTaskForm();
      this._memberForm = emptyMemberForm();
      this._hideNotDue = undefined;
      this._hideMembers = undefined;
    }

    setConfig(config) {
      this._config = config || {};
      // Only seed from config once; afterwards the in-card toggle buttons own
      // it, so re-applying the same config (e.g. dashboard reload) doesn't
      // undo a manual toggle.
      if (this._hideNotDue === undefined) {
        this._hideNotDue = !!this._config.hide_not_due_tasks;
      }
      if (this._hideMembers === undefined) {
        this._hideMembers = !!this._config.hide_members_list;
      }
    }

    static getStubConfig() {
      return { type: "custom:family-tasks-card", title: "Family Tasks" };
    }

    getCardSize() {
      return 4 + Object.keys(this._tasks).length + Object.keys(this._members).length;
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
      if (this._unsubTasks) this._unsubTasks();
      if (this._unsubMembers) this._unsubMembers();
    }

    // Only entities belonging to this integration should trigger a re-render;
    // otherwise unrelated state churn elsewhere in the house would rebuild the
    // whole card (and any open form) every few seconds.
    _relevantStatesSignature() {
      if (!this._hass) return "";
      const parts = [];
      for (const state of Object.values(this._hass.states)) {
        if (
          state.entity_id.startsWith("sensor.") &&
          (state.attributes.task_id || state.attributes.member_id)
        ) {
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
      this._unsubTasks = await this._hass.connection.subscribeMessage(
        handle(this._tasks, "task_id"),
        { type: "family_tasks/task/subscribe" }
      );
      this._unsubMembers = await this._hass.connection.subscribeMessage(
        handle(this._members, "member_id"),
        { type: "family_tasks/member/subscribe" }
      );
    }

    _statusStateForTask(taskId) {
      if (!this._hass) return null;
      return Object.values(this._hass.states).find(
        (s) => s.entity_id.startsWith("sensor.") && s.attributes.task_id === taskId
      );
    }

    _memberName(memberId) {
      return this._members[memberId]?.name ?? "–";
    }

    _personOptions() {
      if (!this._hass) return [];
      return Object.values(this._hass.states)
        .filter((s) => s.entity_id.startsWith("person."))
        .map((s) => ({ id: s.entity_id, name: s.attributes.friendly_name || s.entity_id }));
    }

    // Suggestions for the trigger entity_id field. Sensors/binary_sensors cover
    // the documented use cases (thresholds, binary state changes); the field
    // itself stays a free-text input so any other entity can be typed in too.
    _entityOptions() {
      if (!this._hass) return [];
      return Object.values(this._hass.states)
        .filter((s) => s.entity_id.startsWith("sensor.") || s.entity_id.startsWith("binary_sensor."))
        .map((s) => ({ id: s.entity_id, name: s.attributes.friendly_name || s.entity_id }))
        .sort((a, b) => a.name.localeCompare(b.name));
    }

    // --- actions -------------------------------------------------------

    _openTaskForm(taskId) {
      this._editingTaskId = taskId;
      this._taskForm = taskId ? taskToForm(this._tasks[taskId]) : emptyTaskForm();
      this._taskFormOpen = true;
      this._render();
    }

    _closeTaskForm() {
      this._taskFormOpen = false;
      this._editingTaskId = null;
      this._render();
    }

    _openMemberForm(memberId) {
      this._editingMemberId = memberId;
      this._memberForm = memberId ? memberToForm(this._members[memberId]) : emptyMemberForm();
      this._memberFormOpen = true;
      this._render();
    }

    _closeMemberForm() {
      this._memberFormOpen = false;
      this._editingMemberId = null;
      this._render();
    }

    async _saveTask() {
      const form = this._taskForm;
      if (!form.name.trim()) return;

      const recurrence = { type: form.recurrence.type };
      if (form.recurrence.type === "weekly") {
        recurrence.weekdays = form.recurrence.weekdays.length ? form.recurrence.weekdays : [0];
      } else if (form.recurrence.type === "interval_days") {
        recurrence.interval = Math.max(1, Number(form.recurrence.interval) || 1);
        recurrence.anchor_date = form.recurrence.anchor_date || new Date().toISOString().slice(0, 10);
      } else if (form.recurrence.type === "trigger") {
        const t = form.recurrence.trigger;
        if (!t.entity_id.trim()) {
          alert("Bitte eine Entity ID für den Sensor-Trigger angeben.");
          return;
        }
        if (t.kind === "state") {
          recurrence.trigger = {
            kind: "state",
            entity_id: t.entity_id.trim(),
            to_state: (t.to_state || "on").trim(),
          };
        } else {
          const value = t.value === "" ? undefined : Number(t.value);
          if (value === undefined || Number.isNaN(value)) {
            alert("Bitte einen Schwellenwert angeben.");
            return;
          }
          recurrence.trigger = { kind: "numeric_state", entity_id: t.entity_id.trim() };
          // Single-direction crossing, not a range: exactly one of above/below.
          recurrence.trigger[t.direction === "below" ? "below" : "above"] = value;
        }
      }

      const payload = {
        name: form.name.trim(),
        points: Number(form.points) || 0,
        enabled: form.enabled,
        recurrence,
        rotation: {
          member_ids: form.rotation.member_ids,
          strategy: form.rotation.strategy,
        },
      };
      if (form.icon) payload.icon = form.icon.trim();
      if (form.due_time) payload.due_time = form.due_time;
      if (form.overdue_after_minutes !== "") {
        payload.overdue_after_minutes = Math.max(0, Number(form.overdue_after_minutes) || 0);
      }

      if (this._editingTaskId) {
        await this._hass.callWS({ type: "family_tasks/task/update", task_id: this._editingTaskId, ...payload });
      } else {
        await this._hass.callWS({ type: "family_tasks/task/create", ...payload });
      }
      this._closeTaskForm();
    }

    async _deleteTask(taskId) {
      const name = this._tasks[taskId]?.name ?? taskId;
      if (!confirm(`Aufgabe "${name}" wirklich löschen?`)) return;
      await this._hass.callWS({ type: "family_tasks/task/delete", task_id: taskId });
    }

    async _saveMember() {
      const form = this._memberForm;
      if (!form.name.trim()) return;

      const payload = { name: form.name.trim(), active: form.active, role: form.role || "parent" };
      if (form.person_entity_id) payload.person_entity_id = form.person_entity_id;
      if (form.icon) payload.icon = form.icon.trim();

      if (this._editingMemberId) {
        await this._hass.callWS({ type: "family_tasks/member/update", member_id: this._editingMemberId, ...payload });
      } else {
        await this._hass.callWS({ type: "family_tasks/member/create", ...payload });
      }
      this._closeMemberForm();
    }

    async _deleteMember(memberId) {
      const name = this._members[memberId]?.name ?? memberId;
      if (!confirm(`Mitglied "${name}" wirklich löschen?`)) return;
      await this._hass.callWS({ type: "family_tasks/member/delete", member_id: memberId });
    }

    // --- rendering -------------------------------------------------------

    _render() {
      if (!this._hass) return;
      const title = esc(this._config.title ?? "Family Tasks");

      const hideAddMember = !!this._config.hide_add_member;

      this.shadowRoot.innerHTML = `
        <style>${this._styles()}</style>
        <ha-card header="${title}">
          <div class="card-content">
            <div class="section-header">
              <h3>Aufgaben</h3>
              <button class="link" data-action="toggle-hide-not-due">${this._hideNotDue ? "Alle anzeigen" : "Nicht fällige ausblenden"}</button>
            </div>
            ${this._renderTaskList()}
            ${this._taskFormOpen ? this._renderTaskForm() : `<button class="add" data-action="new-task">+ Aufgabe hinzufügen</button>`}

            <div class="section-header">
              <h3>Familienmitglieder</h3>
              <button class="link" data-action="toggle-hide-members">${this._hideMembers ? "Anzeigen" : "Ausblenden"}</button>
            </div>
            ${this._hideMembers ? "" : this._renderMemberList()}
            ${hideAddMember ? "" : this._memberFormOpen ? this._renderMemberForm() : `<button class="add" data-action="new-member">+ Mitglied hinzufügen</button>`}
          </div>
        </ha-card>
      `;
      this._attachListenersOnce();
    }

    _renderTaskList() {
      let ids = Object.keys(this._tasks);
      const totalCount = ids.length;
      if (this._hideNotDue) {
        ids = ids.filter((id) => DUE_STATUSES.includes(this._statusStateForTask(id)?.state ?? "pending"));
      }
      if (!ids.length) {
        return `<p class="muted">${totalCount ? "Keine fälligen Aufgaben." : "Noch keine Aufgaben angelegt."}</p>`;
      }

      return `<div class="list">${ids
        .map((id) => {
          const task = this._tasks[id];
          const statusState = this._statusStateForTask(id);
          const status = statusState?.state ?? "pending";
          const assignedId = statusState?.attributes?.assigned_member_id;
          const label = STATUS_LABELS[status] ?? status;
          const color = STATUS_COLORS[status] ?? "var(--secondary-text-color)";
          const isTrigger = task.recurrence?.type === "trigger";
          // Auto-generated by the coordinator when a child's task needs
          // parental sign-off (see async_complete_task in coordinator.py) -
          // read-only row, and "Erledigt"/"Überspringen" mean confirm/reject.
          const isConfirmation = !!task.confirms;
          const detail = isConfirmation
            ? `Bestätigung für ${esc(this._memberName(task.confirms.member_id))}`
            : isTrigger
            ? `Sensor: ${esc(task.recurrence.trigger?.entity_id ?? "–")}`
            : `${assignedId ? esc(this._memberName(assignedId)) : "–"} · ${esc(task.points ?? 0)} Pkt.`;
          const disableActions = status === "done" || status === "idle" || status === "awaiting_confirmation";
          return `
            <div class="row">
              <div class="row-main">
                <span class="badge" style="background:${color}">${esc(label)}</span>
                <span class="name">${task.icon ? `<ha-icon icon="${esc(task.icon)}"></ha-icon> ` : ""}${esc(task.name)}</span>
                <span class="muted">${detail}</span>
              </div>
              <div class="row-actions">
                <button data-action="complete-task" data-task-id="${id}" ${disableActions ? "disabled" : ""}>${isConfirmation ? "Bestätigen" : "Erledigt"}</button>
                <button data-action="skip-task" data-task-id="${id}" ${disableActions ? "disabled" : ""}>${isConfirmation ? "Ablehnen" : "Überspringen"}</button>
                ${isConfirmation ? "" : `
                <button data-action="edit-task" data-task-id="${id}">Bearbeiten</button>
                <button data-action="delete-task" data-task-id="${id}" class="danger">Löschen</button>`}
              </div>
            </div>`;
        })
        .join("")}</div>`;
    }

    _renderMemberList() {
      const ids = Object.keys(this._members);
      if (!ids.length) return `<p class="muted">Noch keine Familienmitglieder angelegt.</p>`;

      return `<div class="list">${ids
        .map((id) => {
          const member = this._members[id];
          const roleSuffix = member.role === "child" ? " · Kind" : "";
          return `
            <div class="row">
              <div class="row-main">
                <span class="name">${esc(member.name)}</span>
                <span class="muted">${member.person_entity_id ? esc(member.person_entity_id) : "keine Verknüpfung"}${member.active === false ? " · inaktiv" : ""}${roleSuffix}</span>
              </div>
              <div class="row-actions">
                <button data-action="edit-member" data-member-id="${id}">Bearbeiten</button>
                <button data-action="delete-member" data-member-id="${id}" class="danger">Löschen</button>
              </div>
            </div>`;
        })
        .join("")}</div>`;
    }

    _renderTaskForm() {
      const f = this._taskForm;
      const memberCheckboxes = Object.keys(this._members)
        .map((id) => {
          const checked = f.rotation.member_ids.includes(id) ? "checked" : "";
          return `<label class="chip"><input type="checkbox" data-field="rotation.member_ids" value="${id}" ${checked}> ${esc(this._members[id].name)}</label>`;
        })
        .join("") || `<p class="muted">Erst Familienmitglieder anlegen.</p>`;

      const weekdayCheckboxes = WEEKDAY_LABELS.map((label, idx) => {
        const checked = f.recurrence.weekdays.includes(idx) ? "checked" : "";
        return `<label class="chip"><input type="checkbox" data-field="recurrence.weekdays" value="${idx}" ${checked}> ${label}</label>`;
      }).join("");

      return `
        <form class="form" data-form="task">
          <label>Name<input type="text" data-field="name" value="${esc(f.name)}" required></label>
          <div class="grid2">
            <label>Punkte<input type="number" min="0" data-field="points" value="${esc(f.points)}"></label>
            <label>Icon (optional)<input type="text" data-field="icon" placeholder="mdi:trash-can" value="${esc(f.icon)}"></label>
          </div>

          <label>Wiederholung
            <select data-field="recurrence.type">
              ${Object.entries(RECURRENCE_LABELS).map(([value, label]) => `<option value="${value}" ${f.recurrence.type === value ? "selected" : ""}>${label}</option>`).join("")}
            </select>
          </label>
          ${f.recurrence.type === "weekly" ? `<div class="chips">${weekdayCheckboxes}</div>` : ""}
          ${f.recurrence.type === "interval_days" ? `
            <div class="grid2">
              <label>Intervall (Tage)<input type="number" min="1" data-field="recurrence.interval" value="${esc(f.recurrence.interval)}"></label>
              <label>Ankerdatum<input type="date" data-field="recurrence.anchor_date" value="${esc(f.recurrence.anchor_date)}"></label>
            </div>` : ""}
          ${f.recurrence.type === "trigger" ? this._renderTriggerFields(f.recurrence.trigger) : ""}

          ${f.recurrence.type !== "trigger" ? `
          <div class="grid2">
            <label>Fällig um (optional)<input type="time" data-field="due_time" value="${esc(f.due_time)}"></label>
            <label>Karenz bis überfällig (Min.)<input type="number" min="0" data-field="overdue_after_minutes" value="${esc(f.overdue_after_minutes)}"></label>
          </div>` : `
          <label>Karenz bis überfällig, nachdem der Sensor ausgelöst hat (Min.)<input type="number" min="0" data-field="overdue_after_minutes" value="${esc(f.overdue_after_minutes)}"></label>`}

          <label>Rotation
            <select data-field="rotation.strategy">
              ${Object.entries(STRATEGY_LABELS).map(([value, label]) => `<option value="${value}" ${f.rotation.strategy === value ? "selected" : ""}>${label}</option>`).join("")}
            </select>
          </label>
          <div class="chips">${memberCheckboxes}</div>

          <label class="inline"><input type="checkbox" data-field="enabled" ${f.enabled ? "checked" : ""}> Aktiv</label>

          <div class="form-actions">
            <button type="submit" data-action="save-task">Speichern</button>
            <button type="button" data-action="cancel-task-form">Abbrechen</button>
          </div>
        </form>`;
    }

    _renderTriggerFields(t) {
      const entityList = this._entityOptions()
        .map((e) => `<option value="${esc(e.id)}">${esc(e.name)}</option>`)
        .join("");

      return `
        <div class="trigger-fields">
          <label>Auslöser-Art
            <select data-field="recurrence.trigger.kind">
              ${Object.entries(TRIGGER_KIND_LABELS).map(([value, label]) => `<option value="${value}" ${t.kind === value ? "selected" : ""}>${label}</option>`).join("")}
            </select>
          </label>
          <label>Sensor (Entity ID)
            <input type="text" list="family-tasks-entity-list" data-field="recurrence.trigger.entity_id"
                   placeholder="binary_sensor.muelleimer_voll" value="${esc(t.entity_id)}">
          </label>
          ${t.kind === "state" ? `
            <label>Ziel-Zustand<input type="text" data-field="recurrence.trigger.to_state" placeholder="on" value="${esc(t.to_state)}"></label>
          ` : `
            <div class="grid2">
              <label>Richtung
                <select data-field="recurrence.trigger.direction">
                  ${Object.entries(THRESHOLD_DIRECTION_LABELS).map(([value, label]) => `<option value="${value}" ${t.direction === value ? "selected" : ""}>${label}</option>`).join("")}
                </select>
              </label>
              <label>Schwellenwert<input type="number" step="any" data-field="recurrence.trigger.value" value="${esc(t.value)}"></label>
            </div>
          `}
          <p class="muted">Die Aufgabe wird fällig, sobald der Sensor die Bedingung erfüllt – statt nach einem festen Zeitplan.</p>
          <datalist id="family-tasks-entity-list">${entityList}</datalist>
        </div>`;
    }

    _renderMemberForm() {
      const f = this._memberForm;
      const personOptions = this._personOptions()
        .map((p) => `<option value="${esc(p.id)}" ${f.person_entity_id === p.id ? "selected" : ""}>${esc(p.name)}</option>`)
        .join("");

      return `
        <form class="form" data-form="member">
          <label>Name<input type="text" data-field="name" value="${esc(f.name)}" required></label>
          <label>Verknüpfte Person (optional)
            <select data-field="person_entity_id">
              <option value="">– keine Verknüpfung –</option>
              ${personOptions}
            </select>
          </label>
          <label>Icon (optional)<input type="text" data-field="icon" placeholder="mdi:account" value="${esc(f.icon)}"></label>
          <label>Rolle
            <select data-field="role">
              ${Object.entries(MEMBER_ROLE_LABELS).map(([value, label]) => `<option value="${value}" ${f.role === value ? "selected" : ""}>${label}</option>`).join("")}
            </select>
          </label>
          <label class="inline"><input type="checkbox" data-field="active" ${f.active ? "checked" : ""}> Aktiv (nimmt an der Rotation teil)</label>
          <div class="form-actions">
            <button type="submit" data-action="save-member">Speichern</button>
            <button type="button" data-action="cancel-member-form">Abbrechen</button>
          </div>
        </form>`;
    }

    _styles() {
      return `
        .card-content { padding: 0 16px 16px; }
        h3 { margin: 16px 0 8px; font-size: 1.05em; }
        .section-header { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
        .section-header h3 { margin: 16px 0 8px; }
        .muted { color: var(--secondary-text-color); font-size: 0.9em; }
        .list { display: flex; flex-direction: column; gap: 4px; }
        .row { display: flex; align-items: center; justify-content: space-between; gap: 8px;
               padding: 8px; border-radius: 8px; background: var(--secondary-background-color, #f2f2f2); }
        .row-main { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
        .row-actions { display: flex; gap: 4px; flex-wrap: wrap; justify-content: flex-end; }
        .name { font-weight: 500; display: flex; align-items: center; gap: 4px; }
        .badge { display: inline-block; color: #fff; border-radius: 10px; padding: 1px 8px;
                 font-size: 0.75em; width: fit-content; }
        button { border: none; border-radius: 6px; padding: 6px 10px; font-size: 0.85em;
                 background: var(--primary-color); color: var(--text-primary-color, #fff); cursor: pointer; }
        button:disabled { opacity: 0.5; cursor: default; }
        button.danger { background: var(--error-color, #db4437); }
        button.add { background: none; color: var(--primary-color); padding: 8px 0; text-align: left; }
        button.link { background: none; color: var(--primary-color); padding: 4px 0; font-size: 0.8em; }
        .trigger-fields { display: flex; flex-direction: column; gap: 10px; padding: 8px 10px;
                           border-radius: 8px; background: var(--secondary-background-color, #f2f2f2); }
        .trigger-fields label { display: flex; flex-direction: column; gap: 4px; font-size: 0.9em; }
        .form { display: flex; flex-direction: column; gap: 10px; margin: 8px 0 16px;
                padding: 12px; border-radius: 8px; border: 1px solid var(--divider-color, #e0e0e0); }
        .form label { display: flex; flex-direction: column; gap: 4px; font-size: 0.9em; }
        .form label.inline { flex-direction: row; align-items: center; }
        .form input, .form select { padding: 6px; border-radius: 4px; border: 1px solid var(--divider-color, #ccc);
                                     background: var(--card-background-color, #fff); color: inherit; }
        .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
        .chips { display: flex; flex-wrap: wrap; gap: 6px; }
        .chip { flex-direction: row !important; align-items: center; gap: 4px !important; background: var(--secondary-background-color, #f2f2f2);
                border-radius: 12px; padding: 4px 8px; }
        .form-actions { display: flex; gap: 8px; justify-content: flex-end; }
      `;
    }

    // --- event delegation -------------------------------------------------

    _attachListenersOnce() {
      if (this._listenersAttached) return;
      this._listenersAttached = true;

      this.shadowRoot.addEventListener("submit", (ev) => {
        ev.preventDefault();
        const form = ev.target.closest("[data-form]");
        if (!form) return;
        if (form.dataset.form === "task") this._saveTask();
        if (form.dataset.form === "member") this._saveMember();
      });

      this.shadowRoot.addEventListener("click", (ev) => {
        const el = ev.target.closest("[data-action]");
        if (!el) return;
        const action = el.dataset.action;
        if (action === "new-task") this._openTaskForm(null);
        else if (action === "cancel-task-form") this._closeTaskForm();
        else if (action === "edit-task") this._openTaskForm(el.dataset.taskId);
        else if (action === "delete-task") this._deleteTask(el.dataset.taskId);
        else if (action === "complete-task")
          this._hass.callService("family_tasks", "complete_task", { task_id: el.dataset.taskId });
        else if (action === "skip-task")
          this._hass.callService("family_tasks", "skip_task", { task_id: el.dataset.taskId });
        else if (action === "new-member") this._openMemberForm(null);
        else if (action === "cancel-member-form") this._closeMemberForm();
        else if (action === "edit-member") this._openMemberForm(el.dataset.memberId);
        else if (action === "delete-member") this._deleteMember(el.dataset.memberId);
        else if (action === "toggle-hide-not-due") {
          this._hideNotDue = !this._hideNotDue;
          this._render();
        } else if (action === "toggle-hide-members") {
          this._hideMembers = !this._hideMembers;
          this._render();
        }
      });

      this.shadowRoot.addEventListener("change", (ev) => {
        const el = ev.target.closest("[data-field]");
        if (!el) return;
        const form = ev.target.closest("[data-form]");
        if (!form) return;
        const target = form.dataset.form === "task" ? this._taskForm : this._memberForm;
        this._applyFieldChange(target, el);
        // Re-render only the form itself in place so unrelated typing isn't lost,
        // but recurrence-type / rotation changes need the sub-fields to redraw.
        if (form.dataset.form === "task") {
          form.outerHTML = this._renderTaskForm();
        } else {
          form.outerHTML = this._renderMemberForm();
        }
      });
    }

    _applyFieldChange(target, el) {
      const path = el.dataset.field.split(".");
      const leaf = path[path.length - 1];

      if (leaf === "weekdays") {
        const idx = Number(el.value);
        const list = target.recurrence.weekdays;
        const pos = list.indexOf(idx);
        if (el.checked && pos === -1) list.push(idx);
        if (!el.checked && pos !== -1) list.splice(pos, 1);
        return;
      }
      if (leaf === "member_ids") {
        const list = target.rotation.member_ids;
        const pos = list.indexOf(el.value);
        if (el.checked && pos === -1) list.push(el.value);
        if (!el.checked && pos !== -1) list.splice(pos, 1);
        return;
      }

      // Generic path assignment, e.g. "name" (len 1), "recurrence.type" (len
      // 2), or "recurrence.trigger.entity_id" (len 3).
      const value = el.type === "checkbox" ? el.checked : el.value;
      let obj = target;
      for (let i = 0; i < path.length - 1; i++) obj = obj[path[i]];
      obj[leaf] = value;
    }
  }

  if (!customElements.get("family-tasks-card")) {
    customElements.define("family-tasks-card", FamilyTasksCard);
  }

  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "family-tasks-card",
    name: "Family Tasks",
    description: "Aufgaben, Rotation und Punkte für die Familie verwalten.",
  });
})();
