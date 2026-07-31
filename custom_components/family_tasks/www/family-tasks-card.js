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
 *                               (existing members can still be edited/deleted,
 *                               subject to the admin restriction below)
 *   hide_not_due_tasks: true - initial value for the "nicht fällige
 *                               ausblenden" toggle (only used the very first
 *                               time the card runs on a device - after that
 *                               the card's own persisted state, see below,
 *                               wins so a dashboard reload doesn't undo a
 *                               manual toggle)
 *   hide_members_list: true  - initial value for the "Familienmitglieder"
 *                               visibility toggle (same first-run-only rule
 *                               as above). When active, the entire members
 *                               section - heading, list, and the "+
 *                               Mitglied hinzufügen" button - is hidden, not
 *                               just the list.
 *   only_own_tasks: true     - initial value for the "Nur eigene Aufgaben"
 *                               toggle (same first-run-only rule as above).
 *                               Filters the task list down to occurrences
 *                               assigned to whichever family member is
 *                               linked (via the "person" integration) to the
 *                               logged-in HA user - plus, for a task whose
 *                               rotation is "fest zugewiesen" (fixed) with
 *                               more than one member selected, every one of
 *                               those members (a fixed multi-assignee task
 *                               never rotates, so it's shared rather than
 *                               "currently belonging" to just one of them).
 *                               Any other rotation option only ever shows
 *                               the task to whoever is currently responsible.
 *   hide_battery_section: true - initial value for the "Batterien"
 *                               visibility toggle (same first-run-only rule
 *                               as above). That section is configuration-only
 *                               (see "Battery monitoring" below) so hiding it
 *                               has no effect on monitoring itself.
 *
 * Task types: a task defaults to a single "Erledigt" action. Setting
 * "Aufgabentyp" to "Checkliste" instead gives it an open-ended list of named
 * sub-items (e.g. "Kofferpacken" with one sub-item per thing to pack) that
 * get checked off individually - checked items render struck-through - and
 * the task itself only becomes "Erledigt" once every sub-item is checked for
 * the current period; the manual "Erledigt" button is disabled for these
 * (see FamilyTasksCoordinator.async_toggle_subtask in coordinator.py).
 *
 * A "trigger" (sensor-based) task shows the bound sensor's current value next
 * to its trigger definition, and can optionally name a button entity
 * (family_tasks/task/*'s "completion_button_entity_id") that gets pressed the
 * moment the task is actually marked done - e.g. a vacuum's "resume cleaning"
 * button once its "needs emptying" task is completed.
 *
 * Persisted UI state: the "nicht fällige ausblenden" / "Familienmitglieder
 * ausblenden" / "Nur eigene Aufgaben" / "Batterien ausblenden" toggles and
 * the compact-mode button (top-right of the card, hides the toggle buttons
 * to keep the card small during normal use) are saved to localStorage per
 * browser/device, keyed by the card's title, so they survive dashboard
 * reloads. This is per-device state, not synced between devices - each
 * phone/tablet remembers its own preference.
 *
 * Editing restricted to admins: creating/editing/deleting tasks is only
 * offered to Home Assistant users with an administrator account - Home
 * Assistant's storage-collection websocket API already rejects these actions
 * server-side for non-admin users, so the card simply hides the
 * corresponding buttons/forms for them. Non-admin users can still mark their
 * own tasks done/skipped - that goes through the complete_task/skip_task
 * services, not the storage API.
 *
 * Family members are additionally locked down for children: a user linked
 * (via a member's person_entity_id -> the person's user_id) to a member with
 * role "child" never gets member management UI, regardless of their HA admin
 * flag - and the backend enforces this too (see
 * MemberStorageCollectionWebsocket in storage.py), so this holds even
 * without giving every child their own non-admin HA account.
 *
 * Child tasks: a task assigned to a member with role "child" isn't finished
 * the moment the child taps "Erledigt" - the task shows "Wartet auf
 * Bestätigung" and an auto-generated task appears for the household's
 * parents, unless the task's "requires_confirmation" field is explicitly
 * false. A parent completing *that* task finalizes the child's completion
 * (points + rotation); skipping it rejects the claim. These auto-generated
 * tasks are read-only (no edit/delete) since the coordinator manages them.
 *
 * A user linked to a "child" member also gets a restricted "+ Eigene Aufgabe
 * hinzufügen" form (no admin account needed) to create a task for
 * themselves: no points and no assignee choice - both are forced server-side
 * (family_tasks/task/create_own) - but they choose whether that task
 * requires parental confirmation.
 *
 * Battery monitoring: Home Assistant's battery-level entities
 * (sensor/binary_sensor with device_class "battery") are watched
 * automatically - no task has to be created for it. The moment one is
 * at/below its warning threshold (or, for a binary_sensor, reports low), the
 * backend raises a single one-time task by itself, naming exactly that
 * battery and assigned to every family member linked to a Home Assistant
 * admin account; it shows up in the normal task list like any other task and
 * is dismissed the same way (complete/skip). The admin-only "Batterien"
 * section further down is configuration-only: it lets individual batteries
 * be excluded from monitoring entirely or given their own warning threshold
 * (overriding the household-wide default set in the integration's Options),
 * through the family_tasks/battery_override/* websocket API, and can be
 * collapsed via hide_battery_section above since it's rarely touched day to
 * day. (The older recurrence type "battery" - one aggregate task an admin
 * assigns and that becomes due/idle by itself - still works for any
 * household that already set one up, but is no longer offered when creating
 * a new task.)
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
  const STRATEGY_LABELS = {
    round_robin: "Reihum",
    random: "Zufällig",
    fixed: "Fest zugewiesen",
    least_points: "Wenigste Punkte",
  };
  const RECURRENCE_LABELS = {
    daily: "Täglich",
    weekly: "Wöchentlich (Wochentage)",
    interval_days: "Alle N Tage",
    once: "Einmalig",
    trigger: "Sensor-Ereignis",
    // Legacy recurrence type: battery monitoring now raises its own one-time
    // tasks automatically (see the "Battery monitoring" note at the top of
    // this file) - not offered when creating a new task (see
    // _recurrenceOptionsFor below), kept here only so a household that
    // already has one of these can still see/edit it correctly.
    battery: "Batteriewarnung (automatisch, veraltet)",
  };
  // Recurrence types offered to a child creating a task for themselves - no
  // sensor triggers there, that's an admin-only concept tied to entities.
  const OWN_TASK_RECURRENCE_LABELS = {
    daily: RECURRENCE_LABELS.daily,
    weekly: RECURRENCE_LABELS.weekly,
    interval_days: RECURRENCE_LABELS.interval_days,
    once: RECURRENCE_LABELS.once,
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

  // Opaque, client-generated id for a new checklist sub-item (see
  // TASK_KIND_CHECKLIST in const.py) - only needs to be stable and unique
  // within the task, since it's what family_tasks.toggle_subtask and
  // storage.ChecklistStateStore key checked state on.
  function newSubtaskId() {
    if (window.crypto?.randomUUID) return window.crypto.randomUUID();
    return `st-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  }

  function emptyTaskForm() {
    return {
      name: "",
      points: 0,
      icon: "",
      enabled: true,
      due_time: "",
      overdue_after_minutes: 60,
      requires_confirmation: true,
      kind: "standard",
      subtasks: [],
      completion_button_entity_id: "",
      recurrence: {
        type: "daily",
        interval: 1,
        weekdays: [0],
        anchor_date: "",
        trigger: emptyTriggerForm(),
      },
      rotation: { member_ids: [], strategy: "round_robin", only_children: false },
    };
  }

  function emptyOwnTaskForm() {
    // What a "child" member may set when creating a task for themselves (see
    // family_tasks/task/create_own): no points, no rotation - both are
    // forced server-side to 0 / [self] - but they do get to choose whether a
    // parent has to sign off on their completion.
    return {
      name: "",
      icon: "",
      due_time: "",
      overdue_after_minutes: 60,
      requires_confirmation: true,
      recurrence: { type: "daily", interval: 1, weekdays: [0], anchor_date: "" },
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
      requires_confirmation: task.requires_confirmation ?? true,
      kind: task.kind ?? "standard",
      subtasks: (task.subtasks ?? []).map((s) => ({ ...s })),
      completion_button_entity_id: task.completion_button_entity_id ?? "",
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
        only_children: task.rotation?.only_children ?? false,
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
      this._batteryOverrides = {};
      this._hass = null;
      this._subscribed = false;
      this._listenersAttached = false;
      this._lastSignature = null;
      this._taskFormOpen = false;
      this._memberFormOpen = false;
      this._ownTaskFormOpen = false;
      this._editingTaskId = null;
      this._editingMemberId = null;
      this._taskForm = emptyTaskForm();
      this._memberForm = emptyMemberForm();
      this._ownTaskForm = emptyOwnTaskForm();
      this._hideNotDue = undefined;
      this._hideMembers = undefined;
      this._hideBattery = undefined;
      this._controlsHidden = undefined;
      this._onlyOwnTasks = undefined;
    }

    setConfig(config) {
      this._config = config || {};
      // Seed the persisted UI toggles once: prefer state saved in
      // localStorage from a previous session, falling back to the card
      // config's initial values. Afterwards the in-card buttons own it, so
      // re-applying the same config (e.g. a dashboard reload) doesn't undo a
      // manual toggle - and thanks to localStorage the choice now survives
      // reloads/restarts too, not just re-renders within one session.
      if (this._hideNotDue === undefined) {
        const saved = this._loadUiState();
        this._hideNotDue = saved?.hideNotDue ?? !!this._config.hide_not_due_tasks;
        this._hideMembers = saved?.hideMembers ?? !!this._config.hide_members_list;
        this._hideBattery = saved?.hideBattery ?? !!this._config.hide_battery_section;
        this._controlsHidden = saved?.controlsHidden ?? false;
        this._onlyOwnTasks = saved?.onlyOwnTasks ?? !!this._config.only_own_tasks;
      }
    }

    // --- persisted UI state ---------------------------------------------

    // Namespaced per card title so multiple Family Tasks cards on different
    // dashboards (or with different titles) don't clobber each other's state.
    _storageKey() {
      return `family-tasks-card-ui-state:${this._config?.title ?? "default"}`;
    }

    _loadUiState() {
      try {
        const raw = window.localStorage.getItem(this._storageKey());
        return raw ? JSON.parse(raw) : null;
      } catch (err) {
        // Private browsing / disabled storage / corrupt value - the card
        // still works, it just falls back to the config defaults each time.
        return null;
      }
    }

    _saveUiState() {
      try {
        window.localStorage.setItem(
          this._storageKey(),
          JSON.stringify({
            hideNotDue: this._hideNotDue,
            hideMembers: this._hideMembers,
            hideBattery: this._hideBattery,
            controlsHidden: this._controlsHidden,
            onlyOwnTasks: this._onlyOwnTasks,
          })
        );
      } catch (err) {
        // Storage unavailable/full - toggle still works for this session,
        // it just won't be remembered next time.
      }
    }

    _isAdmin() {
      return this._hass?.user ? !!this._hass.user.is_admin : true;
    }

    // The family member linked to the currently logged-in HA user, resolved
    // via the "person" integration: a member's person_entity_id points at a
    // person entity, and that person's "user_id" attribute (set once the
    // person is linked to a HA user account under Settings -> People)
    // identifies the HA user. Returns null if the current user isn't linked
    // to any member.
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

    // Whether the logged-in user is linked to a member with role "child".
    // Drives both the member-management lockout (req: children may not
    // touch the family member list, regardless of their HA admin flag - the
    // backend enforces this too, see MemberStorageCollectionWebsocket in
    // storage.py) and the "+ Eigene Aufgabe" self-service task form.
    _isChildUser() {
      return this._currentMember()?.role === "child";
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
      if (this._unsubBatteryOverrides) this._unsubBatteryOverrides();
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
      this._unsubBatteryOverrides = await this._hass.connection.subscribeMessage(
        handle(this._batteryOverrides, "battery_override_id"),
        { type: "family_tasks/battery_override/subscribe" }
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

    // Suggestions for the optional "completion button" field on a trigger
    // task (family_tasks/task/*'s completion_button_entity_id) - restricted
    // to the button domain, e.g. a vacuum's "resume cleaning" button.
    _buttonEntityOptions() {
      if (!this._hass) return [];
      return Object.values(this._hass.states)
        .filter((s) => s.entity_id.startsWith("button."))
        .map((s) => ({ id: s.entity_id, name: s.attributes.friendly_name || s.entity_id }))
        .sort((a, b) => a.name.localeCompare(b.name));
    }

    // Every battery-level entity HA currently reports: sensor/binary_sensor
    // with device_class "battery" (mirrors battery.async_discover_battery_entity_ids
    // on the backend, just read straight off hass.states client-side instead
    // of the entity registry - close enough for display purposes here).
    _batteryEntityOptions() {
      if (!this._hass) return [];
      return Object.values(this._hass.states)
        .filter(
          (s) =>
            (s.entity_id.startsWith("sensor.") || s.entity_id.startsWith("binary_sensor.")) &&
            s.attributes.device_class === "battery"
        )
        .map((s) => ({
          entityId: s.entity_id,
          name: s.attributes.friendly_name || s.entity_id,
          isBinary: s.entity_id.startsWith("binary_sensor."),
          state: s.state,
        }))
        .sort((a, b) => a.name.localeCompare(b.name));
    }

    _batteryOverrideFor(entityId) {
      return Object.values(this._batteryOverrides).find((o) => o.entity_id === entityId) ?? null;
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

    _openOwnTaskForm() {
      this._ownTaskForm = emptyOwnTaskForm();
      this._ownTaskFormOpen = true;
      this._render();
    }

    _closeOwnTaskForm() {
      this._ownTaskFormOpen = false;
      this._render();
    }

    async _saveTask() {
      const form = this._taskForm;
      if (!form.name.trim()) return;

      if (form.kind === "checklist") {
        const names = form.subtasks.map((s) => s.name.trim()).filter(Boolean);
        if (!names.length) {
          alert("Bitte mindestens eine Unteraufgabe für die Checkliste angeben.");
          return;
        }
      }

      const recurrence = { type: form.recurrence.type };
      if (form.recurrence.type === "weekly") {
        recurrence.weekdays = form.recurrence.weekdays.length ? form.recurrence.weekdays : [0];
      } else if (form.recurrence.type === "interval_days") {
        recurrence.interval = Math.max(1, Number(form.recurrence.interval) || 1);
        recurrence.anchor_date = form.recurrence.anchor_date || new Date().toISOString().slice(0, 10);
      } else if (form.recurrence.type === "once") {
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
          only_children: form.rotation.strategy === "least_points" ? !!form.rotation.only_children : false,
        },
        requires_confirmation: !!form.requires_confirmation,
        kind: form.kind === "checklist" ? "checklist" : "standard",
      };
      if (form.kind === "checklist") {
        payload.subtasks = form.subtasks
          .map((s) => ({ id: s.id, name: s.name.trim() }))
          .filter((s) => s.name);
      }
      if (form.icon) payload.icon = form.icon.trim();
      if (form.due_time) payload.due_time = form.due_time;
      if (form.overdue_after_minutes !== "") {
        payload.overdue_after_minutes = Math.max(0, Number(form.overdue_after_minutes) || 0);
      }
      // Only meaningful for "trigger" tasks; editing an existing task can
      // explicitly clear it again by sending null (create simply omits it).
      if (form.recurrence.type === "trigger") {
        if (this._editingTaskId) {
          payload.completion_button_entity_id = form.completion_button_entity_id.trim() || null;
        } else if (form.completion_button_entity_id.trim()) {
          payload.completion_button_entity_id = form.completion_button_entity_id.trim();
        }
      }

      if (this._editingTaskId) {
        await this._hass.callWS({ type: "family_tasks/task/update", task_id: this._editingTaskId, ...payload });
      } else {
        await this._hass.callWS({ type: "family_tasks/task/create", ...payload });
      }
      this._closeTaskForm();
    }

    async _saveOwnTask() {
      // Restricted create path for a "child" member adding a task for
      // themselves: no admin rights needed, but no points and no choice of
      // assignee either - the backend forces both (see ws_create_own_task /
      // family_tasks/task/create_own in storage.py).
      const form = this._ownTaskForm;
      if (!form.name.trim()) return;

      const recurrence = { type: form.recurrence.type };
      if (form.recurrence.type === "weekly") {
        recurrence.weekdays = form.recurrence.weekdays.length ? form.recurrence.weekdays : [0];
      } else if (form.recurrence.type === "interval_days") {
        recurrence.interval = Math.max(1, Number(form.recurrence.interval) || 1);
        recurrence.anchor_date = form.recurrence.anchor_date || new Date().toISOString().slice(0, 10);
      } else if (form.recurrence.type === "once") {
        recurrence.anchor_date = form.recurrence.anchor_date || new Date().toISOString().slice(0, 10);
      }

      const payload = {
        name: form.name.trim(),
        recurrence,
        requires_confirmation: !!form.requires_confirmation,
      };
      if (form.icon) payload.icon = form.icon.trim();
      if (form.due_time) payload.due_time = form.due_time;
      if (form.overdue_after_minutes !== "") {
        payload.overdue_after_minutes = Math.max(0, Number(form.overdue_after_minutes) || 0);
      }

      await this._hass.callWS({ type: "family_tasks/task/create_own", ...payload });
      this._closeOwnTaskForm();
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

    // Per-battery override editing ("Batterien" section): items are created
    // lazily and deleted again once they'd be a no-op, matching how
    // storage.BatteryOverrideStorageCollection is documented to work - only
    // entities the household actually customized get an item at all.
    async _saveBatteryOverrideField(el) {
      const entityId = el.dataset.batteryEntity;
      const field = el.dataset.batteryField;
      const existing = this._batteryOverrideFor(entityId);

      let excluded = existing?.excluded ?? false;
      let threshold = existing?.threshold ?? null;
      if (field === "excluded") {
        excluded = el.checked;
      } else if (field === "threshold") {
        threshold = el.value === "" ? null : Number(el.value);
      }

      const isDefault = !excluded && (threshold === null || threshold === undefined);

      if (existing) {
        if (isDefault) {
          await this._hass.callWS({
            type: "family_tasks/battery_override/delete",
            battery_override_id: existing.id,
          });
        } else {
          await this._hass.callWS({
            type: "family_tasks/battery_override/update",
            battery_override_id: existing.id,
            excluded,
            threshold,
          });
        }
      } else if (!isDefault) {
        const payload = { entity_id: entityId, excluded };
        if (threshold !== null) payload.threshold = threshold;
        await this._hass.callWS({ type: "family_tasks/battery_override/create", ...payload });
      }
    }

    // --- rendering -------------------------------------------------------

    _render() {
      if (!this._hass) return;
      const title = esc(this._config.title ?? "Family Tasks");

      const hideAddMember = !!this._config.hide_add_member;
      const isAdmin = this._isAdmin();
      const isChildUser = this._isChildUser();
      // Children may never create/edit/delete family members, independent of
      // their HA admin flag - the backend enforces this too (see
      // MemberStorageCollectionWebsocket in storage.py); this just keeps the
      // buttons from showing up for them in the first place.
      const canManageMembers = isAdmin && !isChildUser;
      // Compact mode: hides the section toggle buttons below (not the
      // section headers themselves) to keep the card small day-to-day. The
      // button that controls it always stays visible, top-right of the card.
      const controlsHidden = this._controlsHidden;

      const membersSection = this._hideMembers
        ? controlsHidden
          ? ""
          : `<button class="link" data-action="toggle-hide-members">Familienmitglieder anzeigen</button>`
        : `
            <div class="section-header">
              <h3>Familienmitglieder</h3>
              ${controlsHidden ? "" : `<button class="link" data-action="toggle-hide-members">Ausblenden</button>`}
            </div>
            ${this._renderMemberList(canManageMembers)}
            ${!canManageMembers || hideAddMember ? "" : this._memberFormOpen ? this._renderMemberForm() : `<button class="add" data-action="new-member">+ Mitglied hinzufügen</button>`}
          `;

      this.shadowRoot.innerHTML = `
        <style>${this._styles()}</style>
        <ha-card>
          <div class="card-header">
            <div class="name">${title}</div>
            <button
              class="icon-btn"
              data-action="toggle-controls"
              title="${controlsHidden ? "Steuerungen einblenden" : "Steuerungen ausblenden"}"
              aria-label="${controlsHidden ? "Steuerungen einblenden" : "Steuerungen ausblenden"}"
            ><ha-icon icon="${controlsHidden ? "mdi:tune-variant" : "mdi:tune"}"></ha-icon></button>
          </div>
          <div class="card-content">
            <div class="section-header">
              <h3>Aufgaben</h3>
              ${controlsHidden ? "" : `
                <div class="header-actions">
                  <button class="link" data-action="toggle-hide-not-due">${this._hideNotDue ? "Alle anzeigen" : "Nicht fällige ausblenden"}</button>
                  <button class="link" data-action="toggle-only-own-tasks">${this._onlyOwnTasks ? "Alle Aufgaben anzeigen" : "Nur eigene Aufgaben"}</button>
                </div>`}
            </div>
            ${this._renderTaskList(isAdmin)}
            ${isAdmin ? (this._taskFormOpen ? this._renderTaskForm() : `<button class="add" data-action="new-task">+ Aufgabe hinzufügen</button>`) : ""}
            ${isChildUser && !isAdmin ? (this._ownTaskFormOpen ? this._renderOwnTaskForm() : `<button class="add" data-action="new-own-task">+ Eigene Aufgabe hinzufügen</button>`) : ""}

            ${isAdmin ? this._renderBatterySection(controlsHidden) : ""}

            ${membersSection}
          </div>
        </ha-card>
      `;
      this._attachListenersOnce();
    }

    _renderTaskList(isAdmin) {
      let ids = Object.keys(this._tasks);
      const totalCount = ids.length;
      if (this._hideNotDue) {
        ids = ids.filter((id) => DUE_STATUSES.includes(this._statusStateForTask(id)?.state ?? "pending"));
      }
      if (this._onlyOwnTasks) {
        const currentMemberId = this._currentMemberId();
        ids = ids.filter((id) => {
          if (!currentMemberId) return false;
          // assigned_member_ids already lists every member currently
          // responsible - just [assigned_member_id] for most rotation
          // strategies, but every selected member for a "fixed" rotation
          // with more than one assignee (see
          // FamilyTasksCoordinator._assigned_member_ids in coordinator.py) -
          // so a single membership check covers both cases.
          const assignedIds = this._statusStateForTask(id)?.attributes?.assigned_member_ids ?? [];
          return assignedIds.includes(currentMemberId);
        });
      }
      if (!ids.length) {
        return `<p class="muted">${totalCount ? "Keine fälligen Aufgaben." : "Noch keine Aufgaben angelegt."}</p>`;
      }

      return `<div class="list">${ids
        .map((id) => {
          const task = this._tasks[id];
          const statusState = this._statusStateForTask(id);
          const status = statusState?.state ?? "pending";
          const assignedIds = statusState?.attributes?.assigned_member_ids ?? [];
          const label = STATUS_LABELS[status] ?? status;
          const color = STATUS_COLORS[status] ?? "var(--secondary-text-color)";
          const isTrigger = task.recurrence?.type === "trigger";
          const isBattery = task.recurrence?.type === "battery";
          const isChecklist = task.kind === "checklist";
          // Auto-generated by the coordinator when a child's task needs
          // parental sign-off (see async_complete_task in coordinator.py) -
          // read-only row, and "Erledigt"/"Überspringen" mean confirm/reject.
          const isConfirmation = !!task.confirms;
          const batteryEntities = statusState?.attributes?.battery_entities ?? [];
          const subtasks = statusState?.attributes?.subtasks ?? [];
          const triggerValue = statusState?.attributes?.trigger_sensor_value;
          const triggerUnit = statusState?.attributes?.trigger_sensor_unit;
          const triggerValueLabel =
            triggerValue !== undefined && triggerValue !== null && triggerValue !== ""
              ? ` · aktuell: ${esc(triggerValue)}${triggerUnit ? ` ${esc(triggerUnit)}` : ""}`
              : "";
          const assigneeLabel = assignedIds.length
            ? assignedIds.map((mid) => esc(this._memberName(mid))).join(", ")
            : "–";
          const detail = isConfirmation
            ? `Bestätigung für ${esc(this._memberName(task.confirms.member_id))}`
            : isChecklist
            ? `${subtasks.filter((s) => s.checked).length}/${subtasks.length} erledigt`
            : isTrigger
            ? `Sensor: ${esc(task.recurrence.trigger?.entity_id ?? "–")}${triggerValueLabel}`
            : isBattery
            ? batteryEntities.length
              ? batteryEntities
                  .map((b) => esc(`${b.name}${b.level !== null && b.level !== undefined ? ` (${b.level}%)` : " (niedrig)"}`))
                  .join(", ")
              : "Keine Batterie niedrig"
            : `${assigneeLabel} · ${esc(task.points ?? 0)} Pkt.`;
          const resolved = status === "done" || status === "idle" || status === "awaiting_confirmation";
          // A checklist task only becomes "done" once every sub-item is
          // checked (see async_toggle_subtask in coordinator.py) - the
          // manual "Erledigt" button is disabled for it so completion always
          // goes through the checklist itself; "Überspringen" still works
          // like on any other task.
          const disableComplete = resolved || isChecklist;
          const subtaskList = isChecklist && subtasks.length
            ? `<div class="subtask-list">${subtasks
                .map(
                  (st) => `
                  <label class="subtask-item ${st.checked ? "checked" : ""}">
                    <input type="checkbox" data-subtask-toggle data-task-id="${id}" data-subtask-id="${esc(st.id)}" ${st.checked ? "checked" : ""} ${status === "done" ? "disabled" : ""}>
                    <span class="subtask-name">${esc(st.name)}</span>
                  </label>`
                )
                .join("")}</div>`
            : "";
          return `
            <div class="row-wrap">
              <div class="row">
                <div class="row-main">
                  <span class="badge" style="background:${color}">${esc(label)}</span>
                  <span class="name">${task.icon ? `<ha-icon icon="${esc(task.icon)}"></ha-icon> ` : ""}${esc(task.name)}</span>
                  <span class="muted">${detail}</span>
                </div>
                <div class="row-actions">
                  <button data-action="complete-task" data-task-id="${id}" ${disableComplete ? "disabled" : ""}>${isConfirmation ? "Bestätigen" : "Erledigt"}</button>
                  <button data-action="skip-task" data-task-id="${id}" ${resolved ? "disabled" : ""}>${isConfirmation ? "Ablehnen" : "Überspringen"}</button>
                  ${isConfirmation || !isAdmin ? "" : `
                  <button data-action="edit-task" data-task-id="${id}">Bearbeiten</button>
                  <button data-action="delete-task" data-task-id="${id}" class="danger">Löschen</button>`}
                </div>
              </div>
              ${subtaskList}
            </div>`;
        })
        .join("")}</div>`;
    }

    _renderMemberList(canManageMembers) {
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
              ${canManageMembers ? `
              <div class="row-actions">
                <button data-action="edit-member" data-member-id="${id}">Bearbeiten</button>
                <button data-action="delete-member" data-member-id="${id}" class="danger">Löschen</button>
              </div>` : ""}
            </div>`;
        })
        .join("")}</div>`;
    }

    // Admin-only, configuration-only section: which battery-level entities
    // HA reports, with per-entity "exclude" / "custom threshold" controls
    // backed by family_tasks/battery_override/*. Purely a monitoring setting
    // - the actual low-battery task(s) are raised automatically by the
    // backend (see the "Battery monitoring" note at the top of this file),
    // this section never lists or creates one itself. Collapsible like the
    // "Familienmitglieder" section, since it's set-and-forget for most
    // households; controlsHidden additionally hides the toggle button itself
    // (compact mode), same as elsewhere.
    _renderBatterySection(controlsHidden) {
      if (this._hideBattery) {
        return controlsHidden
          ? ""
          : `<button class="link" data-action="toggle-hide-battery">Batterien anzeigen</button>`;
      }
      const batteries = this._batteryEntityOptions();
      return `
        <div class="section-header">
          <h3>Batterien</h3>
          ${controlsHidden ? "" : `<button class="link" data-action="toggle-hide-battery">Ausblenden</button>`}
        </div>
        <p class="muted">Legt fest, welche Batterien überwacht werden und ab welchem Stand gewarnt wird. Sobald eine überwachte Batterie ihren Schwellenwert erreicht oder unterschreitet, legt die Integration automatisch eine einmalige Aufgabe für diese Batterie an, zugewiesen an alle Familienmitglieder mit Admin-Rechten - dieser Abschnitt dient nur der Konfiguration, nicht der Aufgabenverwaltung. Der Standard-Schwellenwert wird in den Integrations-Optionen festgelegt (Einstellungen → Geräte &amp; Dienste → Family Tasks → Konfigurieren).</p>
        ${batteries.length ? `<div class="list">${batteries
          .map((b) => {
            const override = this._batteryOverrideFor(b.entityId);
            const excluded = override?.excluded ?? false;
            const threshold = override?.threshold;
            const levelLabel = b.isBinary ? (b.state === "on" ? "Niedrig" : "OK") : `${esc(b.state)}%`;
            return `
              <div class="row">
                <div class="row-main">
                  <span class="name">${esc(b.name)}</span>
                  <span class="muted">${esc(b.entityId)} · ${levelLabel}</span>
                </div>
                <div class="row-actions battery-controls">
                  ${b.isBinary ? "" : `
                  <label class="inline">Schwelle (%)
                    <input type="number" min="0" max="100" placeholder="Standard"
                           data-battery-entity="${esc(b.entityId)}" data-battery-field="threshold"
                           value="${threshold === undefined || threshold === null ? "" : esc(threshold)}"
                           ${excluded ? "disabled" : ""}>
                  </label>`}
                  <label class="inline">
                    <input type="checkbox" data-battery-entity="${esc(b.entityId)}" data-battery-field="excluded" ${excluded ? "checked" : ""}>
                    Ausschließen
                  </label>
                </div>
              </div>`;
          })
          .join("")}</div>` : `<p class="muted">Keine Batterie-Entities gefunden (Sensoren/Binärsensoren mit device_class "battery").</p>`}
      `;
    }

    // Recurrence options offered in the picker: everything in
    // RECURRENCE_LABELS except the legacy "battery" type, which is only kept
    // selectable while it's already the task being edited (see the "Battery
    // monitoring" note at the top of this file for why it's no longer
    // offered for new tasks).
    _recurrenceOptionsFor(currentType) {
      return Object.entries(RECURRENCE_LABELS).filter(
        ([value]) => value !== "battery" || currentType === "battery"
      );
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

          <label>Aufgabentyp
            <select data-field="kind">
              <option value="standard" ${f.kind !== "checklist" ? "selected" : ""}>Standard</option>
              <option value="checklist" ${f.kind === "checklist" ? "selected" : ""}>Checkliste</option>
            </select>
          </label>
          ${f.kind === "checklist" ? this._renderSubtaskEditor(f.subtasks) : ""}

          <label>Wiederholung
            <select data-field="recurrence.type">
              ${this._recurrenceOptionsFor(f.recurrence.type).map(([value, label]) => `<option value="${value}" ${f.recurrence.type === value ? "selected" : ""}>${label}</option>`).join("")}
            </select>
          </label>
          ${f.recurrence.type === "weekly" ? `<div class="chips">${weekdayCheckboxes}</div>` : ""}
          ${f.recurrence.type === "interval_days" ? `
            <div class="grid2">
              <label>Intervall (Tage)<input type="number" min="1" data-field="recurrence.interval" value="${esc(f.recurrence.interval)}"></label>
              <label>Ankerdatum<input type="date" data-field="recurrence.anchor_date" value="${esc(f.recurrence.anchor_date)}"></label>
            </div>` : ""}
          ${f.recurrence.type === "once" ? `
            <label>Datum<input type="date" data-field="recurrence.anchor_date" value="${esc(f.recurrence.anchor_date)}"></label>` : ""}
          ${f.recurrence.type === "trigger" ? this._renderTriggerFields(f.recurrence.trigger) : ""}
          ${f.recurrence.type === "trigger" ? this._renderCompletionButtonField(f.completion_button_entity_id) : ""}
          ${f.recurrence.type === "battery" ? `
            <p class="muted">Automatische Sammel-Aufgabe: wird fällig, sobald mindestens eine überwachte Batterie ihren Warn-Schwellenwert erreicht oder unterschreitet, und listet alle betroffenen Batterien auf. Welche Batterien überwacht werden und ab welchem Stand, wird im Abschnitt "Batterien" weiter unten festgelegt.</p>` : ""}

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
          ${f.rotation.strategy === "least_points" ? `
          <label class="inline"><input type="checkbox" data-field="rotation.only_children" ${f.rotation.only_children ? "checked" : ""}> Nur Punkte von Kindern berücksichtigen</label>` : ""}

          <label class="inline"><input type="checkbox" data-field="enabled" ${f.enabled ? "checked" : ""}> Aktiv</label>
          <label class="inline"><input type="checkbox" data-field="requires_confirmation" ${f.requires_confirmation ? "checked" : ""}> Bestätigung durch Eltern erforderlich (bei Kindern)</label>

          <div class="form-actions">
            <button type="submit" data-action="save-task">Speichern</button>
            <button type="button" data-action="cancel-task-form">Abbrechen</button>
          </div>
        </form>`;
    }

    _renderOwnTaskForm() {
      // Restricted form for a "child" member creating a task for themselves:
      // no points, no assignee choice, no sensor triggers - just what they
      // want done, how often, and whether a parent has to sign off.
      const f = this._ownTaskForm;
      const weekdayCheckboxes = WEEKDAY_LABELS.map((label, idx) => {
        const checked = f.recurrence.weekdays.includes(idx) ? "checked" : "";
        return `<label class="chip"><input type="checkbox" data-field="recurrence.weekdays" value="${idx}" ${checked}> ${label}</label>`;
      }).join("");

      return `
        <form class="form" data-form="own-task">
          <label>Name<input type="text" data-field="name" value="${esc(f.name)}" required></label>
          <label>Icon (optional)<input type="text" data-field="icon" placeholder="mdi:trash-can" value="${esc(f.icon)}"></label>

          <label>Wiederholung
            <select data-field="recurrence.type">
              ${Object.entries(OWN_TASK_RECURRENCE_LABELS).map(([value, label]) => `<option value="${value}" ${f.recurrence.type === value ? "selected" : ""}>${label}</option>`).join("")}
            </select>
          </label>
          ${f.recurrence.type === "weekly" ? `<div class="chips">${weekdayCheckboxes}</div>` : ""}
          ${f.recurrence.type === "interval_days" ? `
            <div class="grid2">
              <label>Intervall (Tage)<input type="number" min="1" data-field="recurrence.interval" value="${esc(f.recurrence.interval)}"></label>
              <label>Ankerdatum<input type="date" data-field="recurrence.anchor_date" value="${esc(f.recurrence.anchor_date)}"></label>
            </div>` : ""}
          ${f.recurrence.type === "once" ? `
            <label>Datum<input type="date" data-field="recurrence.anchor_date" value="${esc(f.recurrence.anchor_date)}"></label>` : ""}

          <div class="grid2">
            <label>Fällig um (optional)<input type="time" data-field="due_time" value="${esc(f.due_time)}"></label>
            <label>Karenz bis überfällig (Min.)<input type="number" min="0" data-field="overdue_after_minutes" value="${esc(f.overdue_after_minutes)}"></label>
          </div>

          <label class="inline"><input type="checkbox" data-field="requires_confirmation" ${f.requires_confirmation ? "checked" : ""}> Bestätigung durch Eltern anfordern</label>
          <p class="muted">Eigene Aufgaben werden ohne Punkte angelegt und nur dir zugewiesen.</p>

          <div class="form-actions">
            <button type="submit" data-action="save-own-task">Speichern</button>
            <button type="button" data-action="cancel-own-task-form">Abbrechen</button>
          </div>
        </form>`;
    }

    // Editor for a TASK_KIND_CHECKLIST task's sub-items: a free-text name per
    // row plus a remove button, and an "+ Unteraufgabe hinzufügen" button
    // that appends a new (client-generated id, empty name) row. Each row's
    // name is edited through the generic data-field mechanism
    // (subtasks.<index>.name); add/remove go through explicit actions since
    // they change the number of rows, not just a value.
    _renderSubtaskEditor(subtasks) {
      const rows = subtasks
        .map(
          (s, i) => `
          <div class="subtask-edit-row">
            <input type="text" data-field="subtasks.${i}.name" placeholder="z. B. Reisepass" value="${esc(s.name)}">
            <button type="button" class="danger" data-action="remove-subtask" data-subtask-index="${i}">✕</button>
          </div>`
        )
        .join("");
      return `
        <div class="subtask-editor">
          ${rows || `<p class="muted">Noch keine Unteraufgaben.</p>`}
          <button type="button" class="add" data-action="add-subtask">+ Unteraufgabe hinzufügen</button>
        </div>`;
    }

    // Optional button entity pressed once a "trigger" task is actually
    // marked done (family_tasks/task/*'s completion_button_entity_id) - free
    // text with suggestions restricted to the button domain, same pattern as
    // the trigger entity field below.
    _renderCompletionButtonField(value) {
      const buttonList = this._buttonEntityOptions()
        .map((b) => `<option value="${esc(b.id)}">${esc(b.name)}</option>`)
        .join("");
      return `
        <label>Button beim Erledigen drücken (optional)
          <input type="text" list="family-tasks-button-list" data-field="completion_button_entity_id"
                 placeholder="button.staubsauger_fortsetzen" value="${esc(value)}">
        </label>
        <datalist id="family-tasks-button-list">${buttonList}</datalist>`;
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
        .card-header { display: flex; align-items: center; justify-content: space-between; gap: 8px;
                       padding: 16px 16px 0; }
        .card-header .name { font-size: 1.2em; font-weight: 400; letter-spacing: -0.012em;
                              line-height: 1.2; color: var(--ha-card-header-color, var(--primary-text-color)); }
        .icon-btn { background: none; padding: 4px; border-radius: 50%; width: 32px; height: 32px;
                    display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0;
                    color: var(--secondary-text-color); }
        .icon-btn:hover { background: var(--secondary-background-color, #f2f2f2); }
        .icon-btn ha-icon { --mdc-icon-size: 20px; }
        .card-content { padding: 8px 16px 16px; }
        h3 { margin: 16px 0 8px; font-size: 1.05em; }
        .section-header { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
        .section-header h3 { margin: 16px 0 8px; }
        .header-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
        .muted { color: var(--secondary-text-color); font-size: 0.9em; }
        .list { display: flex; flex-direction: column; gap: 4px; }
        .row-wrap { display: flex; flex-direction: column; gap: 4px; }
        .row { display: flex; align-items: center; justify-content: space-between; gap: 8px;
               padding: 8px; border-radius: 8px; background: var(--secondary-background-color, #f2f2f2); }
        .row-main { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
        .row-actions { display: flex; gap: 4px; flex-wrap: wrap; justify-content: flex-end; }
        .subtask-list { display: flex; flex-direction: column; gap: 2px; padding: 4px 8px 4px 24px; }
        .subtask-item { display: flex; flex-direction: row; align-items: center; gap: 8px; font-size: 0.9em; }
        .subtask-item.checked .subtask-name { text-decoration: line-through; opacity: 0.6; }
        .subtask-editor { display: flex; flex-direction: column; gap: 6px; padding: 8px 10px;
                           border-radius: 8px; background: var(--secondary-background-color, #f2f2f2); }
        .subtask-edit-row { display: flex; gap: 6px; align-items: center; }
        .subtask-edit-row input { flex: 1; }
        .battery-controls { align-items: center; gap: 12px; }
        .battery-controls label.inline { flex-direction: row !important; align-items: center; gap: 4px; font-size: 0.85em; }
        .battery-controls input[type="number"] { width: 70px; padding: 4px; border-radius: 4px;
                                                   border: 1px solid var(--divider-color, #ccc);
                                                   background: var(--card-background-color, #fff); color: inherit; }
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
        else if (form.dataset.form === "member") this._saveMember();
        else if (form.dataset.form === "own-task") this._saveOwnTask();
      });

      this.shadowRoot.addEventListener("click", (ev) => {
        const el = ev.target.closest("[data-action]");
        if (!el) return;
        const action = el.dataset.action;
        // Edit/delete/create actions are also gated here (in addition to the
        // buttons simply not being rendered for non-admins/children) as a
        // defense-in-depth check - the backend enforces both the admin
        // requirement and the child-may-not-touch-members rule regardless
        // (see the "editing restricted to admins" note at the top of this
        // file and MemberStorageCollectionWebsocket in storage.py), but
        // failing silently client-side avoids a confusing websocket error
        // reaching a child's screen.
        if (action === "new-task") { if (this._isAdmin()) this._openTaskForm(null); }
        else if (action === "cancel-task-form") this._closeTaskForm();
        else if (action === "edit-task") { if (this._isAdmin()) this._openTaskForm(el.dataset.taskId); }
        else if (action === "delete-task") { if (this._isAdmin()) this._deleteTask(el.dataset.taskId); }
        else if (action === "complete-task")
          this._hass.callService("family_tasks", "complete_task", { task_id: el.dataset.taskId });
        else if (action === "skip-task")
          this._hass.callService("family_tasks", "skip_task", { task_id: el.dataset.taskId });
        else if (action === "new-own-task") { if (this._isChildUser()) this._openOwnTaskForm(); }
        else if (action === "cancel-own-task-form") this._closeOwnTaskForm();
        else if (action === "new-member") { if (this._isAdmin() && !this._isChildUser()) this._openMemberForm(null); }
        else if (action === "cancel-member-form") this._closeMemberForm();
        else if (action === "edit-member") { if (this._isAdmin() && !this._isChildUser()) this._openMemberForm(el.dataset.memberId); }
        else if (action === "delete-member") { if (this._isAdmin() && !this._isChildUser()) this._deleteMember(el.dataset.memberId); }
        else if (action === "toggle-hide-not-due") {
          this._hideNotDue = !this._hideNotDue;
          this._saveUiState();
          this._render();
        } else if (action === "toggle-hide-members") {
          this._hideMembers = !this._hideMembers;
          this._saveUiState();
          this._render();
        } else if (action === "toggle-hide-battery") {
          this._hideBattery = !this._hideBattery;
          this._saveUiState();
          this._render();
        } else if (action === "toggle-only-own-tasks") {
          this._onlyOwnTasks = !this._onlyOwnTasks;
          this._saveUiState();
          this._render();
        } else if (action === "toggle-controls") {
          this._controlsHidden = !this._controlsHidden;
          this._saveUiState();
          this._render();
        } else if (action === "add-subtask") {
          this._taskForm.subtasks.push({ id: newSubtaskId(), name: "" });
          const form = el.closest("[data-form]");
          if (form) form.outerHTML = this._renderTaskForm();
        } else if (action === "remove-subtask") {
          this._taskForm.subtasks.splice(Number(el.dataset.subtaskIndex), 1);
          const form = el.closest("[data-form]");
          if (form) form.outerHTML = this._renderTaskForm();
        }
      });

      this.shadowRoot.addEventListener("change", (ev) => {
        // Battery-override controls live in the "Batterien" section, not in
        // one of the [data-form] forms - each field change saves directly
        // via the family_tasks/battery_override/* websocket API instead of
        // going through the form-draft/save flow the other forms use.
        const batteryEl = ev.target.closest("[data-battery-entity]");
        if (batteryEl) {
          this._saveBatteryOverrideField(batteryEl);
          return;
        }

        // Checklist sub-item checkboxes live in the task list row, not in a
        // form either - each toggle calls the toggle_subtask service
        // directly (mirrors how "Erledigt"/"Überspringen" call services
        // rather than going through a form-draft flow).
        const subtaskEl = ev.target.closest("[data-subtask-toggle]");
        if (subtaskEl) {
          this._hass.callService("family_tasks", "toggle_subtask", {
            task_id: subtaskEl.dataset.taskId,
            subtask_id: subtaskEl.dataset.subtaskId,
          });
          return;
        }

        const el = ev.target.closest("[data-field]");
        if (!el) return;
        const form = ev.target.closest("[data-form]");
        if (!form) return;
        const target =
          form.dataset.form === "task"
            ? this._taskForm
            : form.dataset.form === "member"
            ? this._memberForm
            : this._ownTaskForm;
        this._applyFieldChange(target, el);
        // Re-render only the form itself in place so unrelated typing isn't lost,
        // but recurrence-type / rotation changes need the sub-fields to redraw.
        if (form.dataset.form === "task") {
          form.outerHTML = this._renderTaskForm();
        } else if (form.dataset.form === "member") {
          form.outerHTML = this._renderMemberForm();
        } else {
          form.outerHTML = this._renderOwnTaskForm();
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
