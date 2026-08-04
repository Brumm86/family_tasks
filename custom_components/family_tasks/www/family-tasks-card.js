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
 *                               manual toggle). Defaults to false (shown)
 *                               unless set here.
 *   hide_members_list: false - initial value for the "Familienmitglieder"
 *                               visibility toggle (same first-run-only rule
 *                               as above, and same v0.11 default flip as
 *                               only_own_tasks below - explicitly set this to
 *                               false to have the section shown by default
 *                               again). When active, the entire members
 *                               section - heading, list, and the "+
 *                               Mitglied hinzufügen" button - is hidden, not
 *                               just the list.
 *   only_own_tasks: false    - initial value for the member-filter chips atop
 *                               the "Aufgaben" section (same first-run-only
 *                               rule as above) - `false` starts on the "Alle"
 *                               chip, anything else starts on whichever chip
 *                               matches the logged-in user's own linked
 *                               family member (see the "Aufgaben-Filter nach
 *                               Familienmitglied" note below for how that
 *                               resolves and how a manual chip pick differs).
 *                               For a task whose rotation is "fest
 *                               zugewiesen" (fixed) with more than one member
 *                               selected, "own tasks" additionally includes
 *                               every one of those members (a fixed
 *                               multi-assignee task never rotates, so it's
 *                               shared rather than "currently belonging" to
 *                               just one of them). Any other rotation option
 *                               only ever shows the task to whoever is
 *                               currently responsible.
 *   hide_battery_section: false - initial value for the "Batterien"
 *                               visibility toggle (same first-run-only rule
 *                               as above). That section is configuration-only
 *                               (see "Battery monitoring" below) so hiding it
 *                               has no effect on monitoring itself.
 *   hide_leaderboard_section: false - initial value for the "Bestenliste"
 *                               visibility toggle (v0.21, same first-run-only
 *                               rule as above). Unlike hide_members_list/
 *                               hide_battery_section this is *not* Eltern-
 *                               only - the toggle button renders for every
 *                               user, including a "Kind"-linked one, and
 *                               defaults to `false` (shown) rather than
 *                               joining the v0.11 default-true flip below,
 *                               since a child typically needs to see this
 *                               section right away.
 *   hide_rewards_section: false - same as hide_leaderboard_section, for the
 *                               "Belohnungen" section (catalog + redemption
 *                               history) directly below it.
 *
 * v0.11 default flip: hide_members_list, hide_battery_section and
 * only_own_tasks default to *true* (compact, own-tasks-only) the very first
 * time the card runs on a device and no persisted localStorage state exists
 * yet, instead of *false* (everything shown) - set any of them to `false`
 * explicitly in the card config to keep the pre-v0.11 "show everything"
 * first-run behavior. hide_leaderboard_section/hide_rewards_section (v0.21)
 * are deliberately *not* part of this group - see above. (hide_favorites_
 * section, v0.19-v0.20, briefly was part of this group too; removed in
 * v0.21 along with the collapsible-inline-section approach it belonged to -
 * see the Favoriten note further down.) This also softens a real-world
 * failure
 * mode: on some devices/browsers (observed on a Samsung Galaxy S24, likely a
 * webview/private-mode storage restriction) window.localStorage silently
 * throws on every read/write, so the toggle state never persists at all and
 * every load falls back to this default - previously that meant "always
 * shows everything, every time", now it means "always compact, own tasks
 * only", which is the safer default to be stuck with. hide_not_due_tasks is
 * unchanged (still defaults to false) - it's a task-list filter, not an
 * extra section, and hiding not-yet-due tasks by default isn't obviously
 * desirable the way collapsing the admin-only sections is.
 *
 * The "Familienmitglieder anzeigen" / "Batterien anzeigen" buttons (shown
 * once their section is hidden) each render on their own row (v0.9) - they
 * used to sit side by side with nothing forcing a line break between them.
 *
 * Visibility settings are admin/parent-only (v0.8): a user linked to a
 * "child" member never sees the "nicht fällige ausblenden" / "Nur eigene
 * Aufgaben" toggles, the compact-mode button, or the "Familienmitglieder"/
 * "Batterien" show/hide buttons - there is nothing for them to configure,
 * since a child's task list is always filtered down to their own tasks (the
 * "Nur eigene Aufgaben" filter is forced on, not just defaulted, for them).
 *
 * Task types: a task defaults to a single "Erledigt" action. Setting
 * "Aufgabentyp" to "Checkliste" instead gives it an open-ended list of named
 * sub-items (e.g. "Kofferpacken" with one sub-item per thing to pack) that
 * get checked off individually - checked items render struck-through - and
 * the task itself only becomes "Erledigt" once every sub-item is checked for
 * the current period; the manual "Erledigt" button is disabled for these
 * (see FamilyTasksCoordinator.async_toggle_subtask in coordinator.py). A
 * "child" member creating a task for themselves (see below) can also pick
 * "Checkliste" (v0.8) - the same self-service restrictions apply (no points,
 * assigned only to themselves).
 *
 * Editing a task (admin) or adding one's own task (child) opens in a modal
 * dialog (v0.8, native <dialog>/showModal) instead of being inlined into the
 * card's content. Previously, with several task cards on a dashboard, the
 * edit form could end up rendered below other cards and easy to miss; a
 * modal dialog is always shown on top of everything else on the page,
 * regardless of where the card sits, and closes on Escape or "Abbrechen".
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
 *
 * Rewards (v0.9, re-merged into this card in v0.15 - see the "Bestenliste &
 * Belohnungen" note below): a member's participation in the reward system
 * (whether they show up on the leaderboard at all, and whether they may
 * redeem a catalog reward) is set per-member via the "Nimmt am
 * Belohnungssystem teil" checkbox in the Familienmitglieder section below
 * (CONF_MEMBER_REWARDS_OPT_IN in const.py).
 *
 * Bestenliste & Belohnungen (v0.15): previously a separate Lovelace card
 * ("family-tasks-leaderboard-card", v0.4-v0.14, see this file's git history)
 * so a dashboard needed two cards to get the full picture. Folded back into
 * this single card so only one Lovelace card type exists - a new "Bestenliste"
 * section (below the task list, above "Batterien"/"Familienmitglieder") shows
 * the points ranking plus the reward catalog, redeem flow, and redemption
 * history, unchanged in behavior from the old standalone card: every family
 * member's points_week sensor attribute drives the ranking, points_available
 * drives the reward balance/affordability, and CRUD on the catalog
 * (family_tasks/reward/*)/redemptions (family_tasks/reward_redemption/*)
 * follows the exact same admin/child rules as tasks and members elsewhere in
 * this card. This section is always *usable* by everyone, including a
 * "Kind"-linked user (who needs to see and redeem rewards, not just
 * configure something). v0.16 removes the "Woche"/"Monat" tab switcher that
 * used to sit above the ranking - it always ranks by points_week now, so
 * points_month is no longer read by this card at all (the sensor attribute
 * itself is untouched, just unused here).
 *
 * v0.21: "Bestenliste" and "Belohnungen" are now each independently
 * collapsible (_renderRankingSection/_renderRewardsSection,
 * hide_leaderboard_section/hide_rewards_section above) - unlike
 * "Familienmitglieder"/"Batterien" the "Ausblenden"/"... anzeigen" buttons
 * render for *every* user, not just parents, since a child needs to be able
 * to get the reward catalog back out of the way (or bring it back) just as
 * much as a parent does. Both default to shown on a fresh device, not the
 * v0.11 compact default the admin-only sections use.
 *
 * Aufgaben-Filter nach Familienmitglied (v0.16): the "Aufgaben" section's
 * header now shows a row of filter chips - "Alle" plus one per family
 * member - replacing the old plain "Nur eigene Aufgaben"/"Alle Aufgaben
 * anzeigen" toggle button. Clicking a member's chip narrows the task list to
 * occurrences currently assigned to them (see only_own_tasks above for the
 * exact "currently assigned" rule, including the fixed-multi-assignee
 * carve-out); "Alle" clears the filter. Same first-run default as before
 * (whichever member is linked to the logged-in user, unless only_own_tasks
 * is explicitly `false`), same admin/parent-only visibility (never rendered
 * for a "child" user, whose list is always forced to their own tasks
 * regardless - see _effectiveTaskMemberFilterId). Persisted per device like
 * the other toggles.
 *
 * Favoriten (v0.17, replaces the v0.16 star-toggle/quick-complete bar
 * entirely): a "Favorit" is a reusable task *template* a parent maintains -
 * name, points, optional fixed assignee, task type (incl. Checkliste/
 * Pflichtaufgabe) - independent of the tasks collection itself
 * (family_tasks/favorite/*, FavoriteStorageCollection in storage.py). It's
 * meant for chores that come up irregularly (e.g. "Auto waschen", "Keller
 * aufräumen"): not worth setting up as a real recurring task (there's no
 * fixed schedule to hang a Wiederholung off of), but tedious to retype every
 * time. Clicking "Aufgabe erstellen" on a favorite (family_tasks/favorite/
 * instantiate) creates a brand new, independent, open "Einmalig" task from
 * it - not pre-completed - that behaves exactly like one created by hand;
 * the template itself is untouched and can be clicked again any number of
 * times. Parent-only end to end, same rule as member/reward-catalog
 * management (isAdmin && !isChildUser) - a child never sees the "Favoriten"
 * launcher button, the dialog it opens, or any favorite at all.
 *
 * v0.19 made the "Favoriten" section collapsible inline (hide_favorites_
 * section, same pattern as "Familienmitglieder"/"Batterien"), since a
 * household with several favorites would otherwise permanently push the
 * task list further down the card. v0.21 goes a step further and moves it
 * out of the regular card flow entirely: a small "Favoriten" button next to
 * "+ Aufgabe hinzufügen" (_renderFavoritesLauncher) opens the whole catalog
 * in its own modal dialog (_renderFavoritesSection now renders only the
 * dialog's content; _openFavoritesDialog/_closeFavoritesDialog and the
 * "favorites-list" entry in _syncDialogs manage it, same native <dialog>/
 * showModal() mechanism as the task/member/reward/favorite-edit dialogs
 * elsewhere in this file) - so the regularly-used task view never grows
 * with the catalog's size at all, not even a single collapsed row.
 * hide_favorites_section and the inline collapse it controlled are removed
 * as of v0.21; a card config that still sets it is simply ignored.
 *
 * Checklist display (v0.12): a checklist task's sub-items are now sorted
 * alphabetically for display - open items first (alphabetically among
 * themselves), then checked items (also alphabetically) - instead of
 * whatever order they were originally typed in when the task was created.
 * Purely a display-order concern (see the sortedSubtasks sort in
 * _renderTaskList); the stored order in task.subtasks is untouched, and the
 * task's own edit form (where sub-items are added/removed/named) still shows
 * them in that original order, not this sorted one.
 *
 * Also v0.12: fixed a bug where checking off several sub-items of a
 * checklist task in quick succession could leave some of them showing as
 * still unchecked even after things had settled - see the last_updated vs.
 * last_changed note on _relevantStatesSignature below.
 *
 * Also v0.16: fixed the Bestenliste's name/points columns not lining up
 * between rows (a name-length-dependent misalignment caused by .row-main not
 * filling the row - see the flex: 1 comment on that CSS rule in _styles);
 * fixed redeeming an investable Handyzeit reward's "Bestätigen" button
 * silently doing nothing (a backend schema/type bug - see the
 * screen_time_minutes comments in storage.py's REWARD_REDEMPTION_CREATE_SCHEMA
 * and ws_redeem_reward); and every backend-mutating action in this card
 * (task/member/reward/battery-override CRUD, redeeming, marking a redemption
 * fulfilled) now surfaces a rejected call via alert() instead of failing
 * silently - see _callWS.
 *
 * v0.21: the card's big top-level sections - "Aufgaben" (including its "+
 * Aufgabe hinzufügen"/"+ Eigene Aufgabe hinzufügen"/"Favoriten" buttons),
 * "Bestenliste", "Belohnungen", "Batterien", "Familienmitglieder" - are now
 * visually separated by a thin divider line (.section-divider, see
 * cardSections in _render()) instead of relying on spacing alone, since a
 * card with several sections open at once had started to read as one long
 * undifferentiated block. Dividers are only inserted between sections that
 * actually rendered something, so a "Kind" user (who never sees "Batterien"/
 * "Familienmitglieder" at all) doesn't end up with a stray line at the
 * bottom of the card. See the Favoriten note above and the "Bestenliste &
 * Belohnungen" note further up for the other two v0.21 changes (Favoriten
 * moved into its own dialog; Bestenliste/Belohnungen each independently
 * collapsible).
 *
 * v0.22: several changes across the whole card.
 * - "Erledigt"/"Bestätigen" only renders for whoever a task occurrence is
 *   actually assigned to right now (assigned_member_ids, the same list the
 *   member-filter chips use) - see the `canAct` check in _renderTaskList.
 *   Previously anyone with access to the card could mark any task done for
 *   anyone. The plain "Überspringen" button (skip a recurring task to its
 *   next occurrence) is removed entirely; the parent-confirmation flow's
 *   "Ablehnen" (reject a child's completion claim) is a distinct action that
 *   reuses the same skip-task service call under a different label and
 *   stays available, gated by the same `canAct` check.
 * - "Erledigt"/"Bearbeiten"/"Löschen" - and the equivalent actions elsewhere
 *   on the card ("Bestätigen"/"Ablehnen", a favorite's "Aufgabe erstellen",
 *   a redemption's "Als erledigt markieren") - are now small round icon
 *   buttons (see iconActionButton/.icon-action-btn) instead of large text
 *   buttons, everywhere the card uses them (Aufgaben, Favoriten,
 *   Familienmitglieder, Bestenliste/Belohnungen). They fit next to a row's
 *   content in the same line even on narrow screens, so the v0.20 mobile
 *   media query that stacked .row-main/.row-actions into two rows and
 *   buttons onto full-width lines of their own is simplified back down.
 * - "+ Aufgabe hinzufügen"/"+ Eigene Aufgabe hinzufügen" and the "Favoriten"
 *   launcher sit in a shared .task-actions-row now, left- and right-aligned
 *   respectively (space-between), instead of just one after another on the
 *   left.
 * - A task a "child" member created for themselves (family_tasks/task/
 *   create_own, see CONF_TASK_CREATED_BY_MEMBER_ID in const.py) is now
 *   visible only to whoever created it - not other children (already mostly
 *   excluded by their own forced "own tasks" filter) and, new in v0.22, not
 *   parents/admins either, whose view previously showed every task
 *   regardless. See the creator-only filter at the top of _renderTaskList.
 *   The coordinator-generated parent-confirmation task raised once such a
 *   task is completed (if it requires confirmation) is a separate task
 *   entity without this field, so it's unaffected and still shows up for
 *   parents as before.
 * - Clicking a Bestenliste row (or pressing Enter/Space on it) opens a
 *   dialog listing exactly which tasks that member completed during the
 *   current calendar week, via the new family_tasks/member/
 *   weekly_completions command - see _openMemberCompletions/
 *   _renderMemberCompletionsList.
 * - The Bestenliste shows "Wochensieger-Bonus: N Punkte" above the ranking
 *   whenever the household has the weekly-winner-bonus feature (v0.14)
 *   turned on - see _weeklyWinnerBonus, which reads it off a
 *   weekly_winner_bonus_enabled/...points attribute now carried by every
 *   member's points sensor (FamilyTasksData in coordinator.py).
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

  // "1 Punkt" vs. "2 Punkte" - jede Stelle, an der ein Belohnungspreis oder ein
  // Punkte-Guthaben als das Wort "Punkte" (nicht die anderswo verwendete
  // Abkürzung "Pkt.") dargestellt wird, geht hierüber, damit der Singular
  // korrekt gelesen wird.
  function pointsLabel(value) {
    const n = Number(value) || 0;
    return `${esc(n)} ${n === 1 ? "Punkt" : "Punkte"}`;
  }

  // Kleiner "· +30 Min. Bildschirmzeit"-Zusatz, gemeinsam genutzt vom
  // Belohnungs-Katalog und dem Einlöse-Verlauf - undefined/null/"" bedeuten
  // alle "nicht gesetzt".
  function screenTimeSuffix(minutes) {
    return minutes ? ` · +${esc(minutes)} Min. Bildschirmzeit` : "";
  }

  // Kompakter Icon-Button (v0.22) für Zeilen-Aktionen wie "Erledigt"/
  // "Bearbeiten"/"Löschen" - ersetzt die bisherigen großen Text-Buttons in
  // .row-actions überall auf der Karte (Aufgaben, Favoriten,
  // Familienmitglieder, Belohnungen, Einlösungen), damit mehrere Aktionen
  // nebeneinander in einer Zeile neben der jeweiligen Zeile Platz finden,
  // statt die Zeile unnötig hoch zu machen. `extraClass` steuert nur die
  // Icon-Farbe (success/danger), Größe/Form sind für jeden Icon-Button
  // gleich (siehe .icon-action-btn in _styles). `dataset` ist ein bereits
  // fertig formatierter String mit den data-*-Attributen, die der jeweilige
  // Klick-Handler in _attachListenersOnce braucht (z. B. data-task-id).
  function iconActionButton(action, icon, title, { dataset = "", extraClass = "", disabled = false } = {}) {
    return `<button type="button" class="icon-action-btn ${extraClass}" data-action="${action}" ${dataset} title="${esc(title)}" aria-label="${esc(title)}" ${disabled ? "disabled" : ""}><ha-icon icon="${icon}"></ha-icon></button>`;
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
    // parent has to sign off on their completion, and (v0.8) whether it's a
    // checklist task with their own named sub-items.
    return {
      name: "",
      icon: "",
      due_time: "",
      overdue_after_minutes: 60,
      requires_confirmation: true,
      kind: "standard",
      subtasks: [],
      recurrence: { type: "daily", interval: 1, weekdays: [0], anchor_date: "" },
    };
  }

  function emptyMemberForm() {
    return {
      name: "",
      person_entity_id: "",
      icon: "",
      active: true,
      role: "parent",
      participates_in_rewards: true,
      notify_service: "",
    };
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
      participates_in_rewards: member.participates_in_rewards !== false,
      notify_service: member.notify_service ?? "",
    };
  }

  function emptyRewardForm() {
    return {
      name: "",
      icon: "",
      points_cost: 0,
      reward_type: "custom",
      screen_time_minutes: "",
      auto_fulfill: false,
      screen_time_investable: false,
    };
  }

  function rewardToForm(reward) {
    return {
      name: reward?.name ?? "",
      icon: reward?.icon ?? "",
      points_cost: reward?.points_cost ?? 0,
      // "Belohnungstyp" ist ein reines Formular-Konzept, kein eigenes
      // gespeichertes Feld - abgeleitet davon, ob ein Bildschirmzeit-Wert
      // gesetzt ist (siehe _renderRewardForm). Zurückschalten auf "Sonstige"
      // löscht den Wert beim Speichern (_saveReward).
      reward_type: reward?.screen_time_minutes || reward?.screen_time_investable ? "screen_time" : "custom",
      // Leer (nicht 0), wenn nicht gesetzt, damit das Feld als "keine
      // Handyzeit-Belohnung" statt "0 Minuten" gelesen wird - siehe
      // CONF_REWARD_SCREEN_TIME_MINUTES in const.py.
      screen_time_minutes: reward?.screen_time_minutes ?? "",
      // Siehe CONF_REWARD_AUTO_FULFILL in const.py.
      auto_fulfill: reward?.auto_fulfill ?? false,
      // v0.14 - siehe CONF_REWARD_SCREEN_TIME_INVESTABLE in const.py: lässt
      // das einlösende Mitglied selbst wählen, wie viele Punkte investiert
      // werden, statt eines festen Preis-/Minuten-Paars.
      screen_time_investable: reward?.screen_time_investable ?? false,
    };
  }

  function emptyFavoriteForm() {
    return { name: "", points: 0, icon: "", member_ids: [], kind: "standard", subtasks: [] };
  }

  function favoriteToForm(favorite) {
    return {
      name: favorite?.name ?? "",
      points: favorite?.points ?? 0,
      icon: favorite?.icon ?? "",
      member_ids: [...(favorite?.member_ids ?? [])],
      kind: favorite?.kind ?? "standard",
      subtasks: (favorite?.subtasks ?? []).map((s) => ({ ...s })),
    };
  }

  class FamilyTasksCard extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: "open" });
      this._tasks = {};
      this._members = {};
      this._batteryOverrides = {};
      this._rewards = {};
      this._redemptions = {};
      this._favorites = {};
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
      // Aufgaben-Filter nach Familienmitglied (v0.16, ersetzt das frühere
      // reine An/Aus von "Nur eigene Aufgaben"): null = "Alle", "own" =
      // Sentinel für "wer auch immer gerade eingeloggt ist" (der Default,
      // löst sich bei jedem Rendern neu über _currentMemberId() auf, siehe
      // _renderTaskList), oder eine konkrete Mitglieds-ID, sobald jemand
      // gezielt einen der Filter-Chips oben in der Aufgaben-Karte anklickt.
      this._taskMemberFilter = undefined;
      this._rewardFormOpen = false;
      this._editingRewardId = null;
      this._rewardForm = emptyRewardForm();
      // Welche Katalog-Belohnung gerade ihren "wirklich einlösen?"-
      // Bestätigungsschritt für den aktuellen Nutzer zeigt - immer nur eine.
      this._pendingRedeemId = null;
      // Wie viele Punkte der aktuelle Nutzer in das "Punkte investieren"-Feld
      // für die anstehende investierbare (Handyzeit-)Einlösung eingetragen
      // hat - siehe CONF_REWARD_SCREEN_TIME_INVESTABLE in const.py.
      this._pendingInvestPoints = 1;
      // Ob bereits erledigte Einlösungen in "Bisherige Einlösungen"
      // ausgeblendet sind - siehe setConfig für die Default-an/persistierte
      // First-Run-Regel, gleiches Muster wie die übrigen Karten-Toggles.
      this._hideFulfilled = undefined;
      // Favoriten (v0.17) - task-template CRUD, mirrors the reward-form state
      // just above (_rewardFormOpen/_editingRewardId/_rewardForm).
      this._favoriteFormOpen = false;
      this._editingFavoriteId = null;
      this._favoriteForm = emptyFavoriteForm();
      // Whether the "Favoriten" catalog dialog itself is open (v0.21,
      // replaces the v0.19 _hideFavorites inline-collapse toggle - see
      // _renderFavoritesLauncher/_openFavoritesDialog). Not persisted, same
      // as the other *FormOpen dialog flags: it always starts closed on
      // load, same as _taskFormOpen/_memberFormOpen/etc.
      this._favoritesDialogOpen = false;
      // Bestenliste/Belohnungen (v0.21): independently collapsible, unlike
      // _hideMembers/_hideBattery this toggle is available to *every* user
      // including a "Kind"-account (see _renderRankingSection/
      // _renderRewardsSection) since both sections are used by children too,
      // not just parents configuring something.
      this._hideLeaderboard = undefined;
      this._hideRewards = undefined;
      // v0.22: "welche Aufgaben hat dieses Mitglied diese Woche erledigt"-
      // Dialog, geöffnet per Klick auf eine Bestenlisten-Zeile (siehe
      // _openMemberCompletions/_renderRankingSection). Nicht persistiert -
      // startet wie jedes andere Dialog-Flag immer geschlossen.
      this._memberCompletionsDialogOpen = false;
      this._memberCompletionsMemberId = null;
      this._memberCompletions = [];
      this._memberCompletionsLoading = false;
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
        // v0.11: default to hidden/own-tasks-only on a genuinely fresh device
        // (no saved state) unless the config explicitly opts back into the
        // old "show everything" default with `false` - see the file header
        // comment for why. Previously these three fell back to `false`
        // (shown) the same way hide_not_due_tasks still does.
        this._hideMembers = saved?.hideMembers ?? this._config.hide_members_list !== false;
        this._hideBattery = saved?.hideBattery ?? this._config.hide_battery_section !== false;
        this._controlsHidden = saved?.controlsHidden ?? false;
        // v0.16: replaces the old plain "Nur eigene Aufgaben"/"Alle Aufgaben
        // anzeigen" toggle button with per-member filter chips (see
        // _renderMemberFilterChips) - same first-run default as before
        // (only_own_tasks !== false), just expressed as the "own" sentinel
        // instead of a boolean, since a chip has to point at *someone*
        // rather than just being on/off.
        this._taskMemberFilter =
          saved?.taskMemberFilter !== undefined
            ? saved.taskMemberFilter
            : this._config.only_own_tasks === false
            ? null
            : "own";
        // Erledigte Einlösungen sind standardmäßig ausgeblendet, wie schon in
        // der ehemals eigenständigen Bestenlisten-Karte.
        this._hideFulfilled = saved?.hideFulfilled ?? true;
        // v0.21: Bestenliste/Belohnungen bleiben - anders als
        // Mitglieder/Batterien/die alte Favoriten-Sektion - standardmäßig
        // sichtbar (kein v0.11-Kompakt-Default), da auch ein "Kind"-Konto
        // sie normalerweise sofort braucht (Belohnungen einlösen). Optional
        // per Config-Option von Anfang an ausgeblendet startbar.
        this._hideLeaderboard = saved?.hideLeaderboard ?? !!this._config.hide_leaderboard_section;
        this._hideRewards = saved?.hideRewards ?? !!this._config.hide_rewards_section;
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
            taskMemberFilter: this._taskMemberFilter,
            hideFulfilled: this._hideFulfilled,
            hideLeaderboard: this._hideLeaderboard,
            hideRewards: this._hideRewards,
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
      return (
        4 +
        Object.keys(this._tasks).length +
        Object.keys(this._members).length +
        Object.keys(this._rewards).length +
        Object.keys(this._redemptions).length
      );
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
      if (this._unsubRewards) this._unsubRewards();
      if (this._unsubRedemptions) this._unsubRedemptions();
      // Reset so a later reconnect actually resubscribes (v0.11 fix): Lovelace
      // can detach and reattach the very same element instance - e.g.
      // reordering/editing a dashboard, or switching between views that reuse
      // it - which fires disconnectedCallback/set hass() again on the *same*
      // instance without ever recreating it. Since "set hass" only calls
      // _subscribe() while _subscribed is still false, leaving it true here
      // meant the card silently kept running on dead subscriptions after
      // reattachment - no error, just a card that "occasionally fails to load
      // correctly" (stale/empty task list until a full page reload).
      this._subscribed = false;
    }

    // Only entities belonging to this integration should trigger a re-render;
    // otherwise unrelated state churn elsewhere in the house would rebuild the
    // whole card (and any open form) every few seconds.
    //
    // Uses last_updated, not last_changed (v0.12 fix): last_changed only
    // moves when the entity's *state string* changes (e.g. "pending" ->
    // "done"), while checking off one sub-item of a checklist task only
    // changes the "subtasks" *attribute* - the state string stays "pending"
    // until the very last sub-item is checked. With last_changed, that
    // attribute-only update produced the exact same signature as before, so
    // the render was silently skipped: the checkbox looked unchanged (or, if
    // several were ticked in quick succession, some appeared to "not take"
    // even after things had settled) until some unrelated state change
    // finally forced a re-render. last_updated moves on every attribute
    // change too, so each toggle is now always picked up.
    _relevantStatesSignature() {
      if (!this._hass) return "";
      const parts = [];
      for (const state of Object.values(this._hass.states)) {
        if (
          state.entity_id.startsWith("sensor.") &&
          (state.attributes.task_id || state.attributes.member_id)
        ) {
          parts.push(`${state.entity_id}:${state.state}:${state.last_updated}`);
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
      this._unsubRewards = await this._hass.connection.subscribeMessage(
        handle(this._rewards, "reward_id"),
        { type: "family_tasks/reward/subscribe" }
      );
      this._unsubRedemptions = await this._hass.connection.subscribeMessage(
        handle(this._redemptions, "reward_redemption_id"),
        { type: "family_tasks/reward_redemption/subscribe" }
      );
      this._unsubFavorites = await this._hass.connection.subscribeMessage(
        handle(this._favorites, "favorite_id"),
        { type: "family_tasks/favorite/subscribe" }
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

    // --- Bestenliste/Belohnungen helpers (v0.15) ------------------------

    _pointsSensorForMember(memberId) {
      if (!this._hass) return null;
      return Object.values(this._hass.states).find(
        (s) => s.entity_id.startsWith("sensor.") && s.attributes.member_id === memberId
      );
    }

    // Aktuelles einlösbares Guthaben: Gesamtpunkte abzüglich aller bereits
    // eingelösten Belohnungen - siehe MemberSummaryData.points_available in
    // coordinator.py. Wird unabhängig von der Woche/Monat-Ansicht immer
    // angezeigt, da es die tatsächliche Währung des Belohnungs-Katalogs
    // unten ist, keine periodenbezogene Rangliste-Kennzahl.
    _availablePointsFor(memberId) {
      return Number(this._pointsSensorForMember(memberId)?.attributes?.points_available ?? 0);
    }

    // v0.22: household-wide weekly-winner-bonus settings (see
    // CONF_WEEKLY_WINNER_BONUS_ENABLED/...POINTS in const.py) - rides along
    // as an attribute on every member's points sensor (identical on all of
    // them, see FamilyTasksMemberPointsSensor in sensor.py), so any one of
    // them will do; "points_week" is a unique-enough discriminator to find a
    // points sensor specifically (the open-tasks sensor also carries a bare
    // "member_id" attribute but not this one).
    _weeklyWinnerBonus() {
      if (!this._hass) return { enabled: false, points: 0 };
      const sensor = Object.values(this._hass.states).find(
        (s) => s.entity_id.startsWith("sensor.") && s.attributes.points_week !== undefined
      );
      return {
        enabled: !!sensor?.attributes?.weekly_winner_bonus_enabled,
        points: Number(sensor?.attributes?.weekly_winner_bonus_points ?? 0),
      };
    }

    // v0.16: always ranks by points_week now - the "Woche"/"Monat" tab
    // switcher (and points_month) is gone, see the file header note on the
    // Bestenliste section for why.
    _rankedMembers() {
      return Object.keys(this._members)
        .map((id) => {
          const member = this._members[id];
          const sensor = this._pointsSensorForMember(id);
          const points = Number(sensor?.attributes?.points_week ?? 0);
          return { id, member, points };
        })
        .filter((entry) => entry.member.active !== false)
        // Nur Mitglieder, die am Belohnungssystem teilnehmen, tauchen hier
        // überhaupt auf - ein Haushalt kann z. B. nur die Kinder um Punkte
        // konkurrieren lassen.
        .filter((entry) => entry.member.participates_in_rewards !== false)
        .sort((a, b) => b.points - a.points);
    }

    // --- actions -------------------------------------------------------

    // Every backend-mutating websocket call in this card goes through here
    // (v0.16 fix) instead of calling this._hass.callWS(...) directly. Home
    // Assistant rejects the returned promise when the backend refuses a
    // command (bad input, insufficient permissions, a business-rule check
    // like "not enough points") - previously nothing here ever caught that,
    // so a rejection just aborted whichever async method was mid-flight
    // (e.g. _confirmRedeem never reached the code that clears
    // _pendingRedeemId and re-renders) with no feedback at all. From the
    // user's side that looked exactly like the button they clicked - most
    // notably "Bestätigen" on an investable Handyzeit reward, see
    // ws_redeem_reward's screen_time_minutes computation in storage.py for
    // the actual bug that used to trigger this - had simply done nothing.
    // Surfacing the message via alert() at least tells the user why, and
    // re-throwing keeps every caller's existing "stop here, don't clear
    // form/pending state" behavior on failure.
    async _callWS(msg) {
      try {
        return await this._hass.callWS(msg);
      } catch (err) {
        alert(err?.message || "Die Aktion konnte nicht ausgeführt werden.");
        throw err;
      }
    }

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
        kind: form.kind === "checklist" || form.kind === "mandatory" ? form.kind : "standard",
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
        await this._callWS({ type: "family_tasks/task/update", task_id: this._editingTaskId, ...payload });
      } else {
        await this._callWS({ type: "family_tasks/task/create", ...payload });
      }
      this._closeTaskForm();
    }

    async _saveOwnTask() {
      // Restricted create path for a "child" member adding a task for
      // themselves: no admin rights needed, but no points and no choice of
      // assignee either - the backend forces both (see ws_create_own_task /
      // family_tasks/task/create_own in storage.py). A checklist kind is
      // allowed too (v0.8), same "at least one named sub-item" rule as the
      // admin task form.
      const form = this._ownTaskForm;
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
      }

      const payload = {
        name: form.name.trim(),
        recurrence,
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

      await this._callWS({ type: "family_tasks/task/create_own", ...payload });
      this._closeOwnTaskForm();
    }

    async _deleteTask(taskId) {
      const name = this._tasks[taskId]?.name ?? taskId;
      if (!confirm(`Aufgabe "${name}" wirklich löschen?`)) return;
      await this._callWS({ type: "family_tasks/task/delete", task_id: taskId });
    }

    async _saveMember() {
      const form = this._memberForm;
      if (!form.name.trim()) return;

      const payload = {
        name: form.name.trim(),
        active: form.active,
        role: form.role || "parent",
        participates_in_rewards: !!form.participates_in_rewards,
      };
      if (form.person_entity_id) payload.person_entity_id = form.person_entity_id;
      if (form.icon) payload.icon = form.icon.trim();
      // Explicit null clears a previously set notify service when editing
      // (see CONF_MEMBER_NOTIFY_SERVICE in const.py); omitting the key
      // entirely is enough when creating a new member.
      if (form.notify_service.trim()) {
        payload.notify_service = form.notify_service.trim();
      } else if (this._editingMemberId) {
        payload.notify_service = null;
      }

      if (this._editingMemberId) {
        await this._callWS({ type: "family_tasks/member/update", member_id: this._editingMemberId, ...payload });
      } else {
        await this._callWS({ type: "family_tasks/member/create", ...payload });
      }
      this._closeMemberForm();
    }

    async _deleteMember(memberId) {
      const name = this._members[memberId]?.name ?? memberId;
      if (!confirm(`Mitglied "${name}" wirklich löschen?`)) return;
      await this._callWS({ type: "family_tasks/member/delete", member_id: memberId });
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
          await this._callWS({
            type: "family_tasks/battery_override/delete",
            battery_override_id: existing.id,
          });
        } else {
          await this._callWS({
            type: "family_tasks/battery_override/update",
            battery_override_id: existing.id,
            excluded,
            threshold,
          });
        }
      } else if (!isDefault) {
        const payload = { entity_id: entityId, excluded };
        if (threshold !== null) payload.threshold = threshold;
        await this._callWS({ type: "family_tasks/battery_override/create", ...payload });
      }
    }

    // --- Bestenliste/Belohnungen actions (v0.15) ------------------------

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
      // "Belohnungstyp" entscheidet, ob das Minuten-Feld überhaupt gilt
      // (siehe _renderRewardForm/rewardToForm) - "Sonstige" löscht einen
      // zuvor gesetzten Wert immer, unabhängig davon, was noch im
      // (versteckten) Minuten-Feld steht.
      const isScreenTime = f.reward_type === "screen_time";
      const isInvestable = isScreenTime && !!f.screen_time_investable;
      if (isScreenTime && !isInvestable && (f.screen_time_minutes === "" || f.screen_time_minutes == null)) {
        alert("Bitte die Bildschirmzeit in Minuten angeben (oder \"Punkte investieren lassen\" aktivieren).");
        return;
      }
      const payload = {
        name: f.name.trim(),
        points_cost: Math.max(0, Number(f.points_cost) || 0),
        auto_fulfill: !!f.auto_fulfill,
        screen_time_investable: isInvestable,
      };
      if (f.icon) payload.icon = f.icon.trim();
      // Keine Handyzeit-Belohnung -> nicht gesetzt. Beim Bearbeiten muss das
      // als explizites null gesendet werden, damit der Backend einen zuvor
      // gesetzten Wert löscht (siehe CONF_REWARD_SCREEN_TIME_MINUTES in
      // const.py); beim Neuanlegen reicht das Weglassen des Felds. Eine
      // investierbare Handyzeit-Belohnung (v0.14) hat ebenfalls keine feste
      // Minutenzahl - das Mitglied wählt beim Einlösen - wird also genauso
      // gelöscht wie eine Nicht-Handyzeit-Belohnung.
      if (isScreenTime && !isInvestable) {
        payload.screen_time_minutes = Math.max(1, Number(f.screen_time_minutes) || 1);
      } else if (this._editingRewardId) {
        payload.screen_time_minutes = null;
      }
      if (this._editingRewardId) {
        await this._callWS({
          type: "family_tasks/reward/update",
          reward_id: this._editingRewardId,
          ...payload,
        });
      } else {
        await this._callWS({ type: "family_tasks/reward/create", ...payload });
      }
      this._closeRewardForm();
    }

    async _deleteReward(rewardId) {
      const name = this._rewards[rewardId]?.name ?? rewardId;
      if (!confirm(`Belohnung "${name}" wirklich löschen?`)) return;
      await this._callWS({ type: "family_tasks/reward/delete", reward_id: rewardId });
    }

    _selectReward(rewardId) {
      this._pendingRedeemId = rewardId;
      this._pendingInvestPoints = 1;
      this._render();
    }

    _cancelRedeem() {
      this._pendingRedeemId = null;
      this._render();
    }

    // Nicht-admin Einlösen: das Backend prüft unabhängig noch einmal, ob der
    // Aufrufer am Belohnungssystem teilnimmt und sich die Belohnung wirklich
    // leisten kann (siehe ws_redeem_reward in storage.py) - der clientseitige
    // "disabled"-Zustand der "Auswählen"/"Bestätigen"-Buttons sorgt nur
    // dafür, dass es gar nicht erst angeboten wird, ist aber nicht die
    // eigentliche Absicherung.
    async _confirmRedeem(rewardId) {
      const reward = this._rewards[rewardId];
      const msg = { type: "family_tasks/reward_redemption/redeem", reward_id: rewardId };
      if (reward?.screen_time_investable) {
        msg.points_spent = Math.max(1, Number(this._pendingInvestPoints) || 1);
      }
      await this._callWS(msg);
      this._pendingRedeemId = null;
      this._pendingInvestPoints = 1;
      this._render();
    }

    async _fulfillRedemption(redemptionId) {
      await this._callWS({
        type: "family_tasks/reward_redemption/update",
        reward_redemption_id: redemptionId,
        fulfilled: true,
      });
    }

    // v0.22: opened by clicking a Bestenliste row - fetches which tasks that
    // member completed *this* calendar week (family_tasks/member/
    // weekly_completions, see ws_list_member_weekly_completions in
    // storage.py, which computes the same Monday-00:00-local week boundary
    // the points_week figure already shown on the row is based on). Loads on
    // open rather than being derived from anything the card already has
    // locally - there is no per-completion detail (task name/timestamp)
    // subscribed to client-side, only the aggregate points_week total.
    async _openMemberCompletions(memberId) {
      this._memberCompletionsMemberId = memberId;
      this._memberCompletionsDialogOpen = true;
      this._memberCompletions = [];
      this._memberCompletionsLoading = true;
      this._render();
      try {
        const result = await this._callWS({
          type: "family_tasks/member/weekly_completions",
          member_id: memberId,
        });
        this._memberCompletions = result?.completions ?? [];
      } catch (err) {
        // _callWS already alerted the user - just leave the list empty.
      } finally {
        this._memberCompletionsLoading = false;
        this._render();
      }
    }

    _closeMemberCompletions() {
      this._memberCompletionsDialogOpen = false;
      this._memberCompletionsMemberId = null;
      this._render();
    }

    // --- Favoriten actions (v0.17) ---------------------------------------

    _openFavoriteForm(favoriteId) {
      this._editingFavoriteId = favoriteId;
      this._favoriteForm = favoriteId ? favoriteToForm(this._favorites[favoriteId]) : emptyFavoriteForm();
      this._favoriteFormOpen = true;
      this._render();
    }

    _closeFavoriteForm() {
      this._favoriteFormOpen = false;
      this._editingFavoriteId = null;
      this._render();
    }

    // v0.21: opens/closes the "Favoriten" catalog dialog itself (as opposed
    // to _openFavoriteForm/_closeFavoriteForm above, which is the nested
    // add/edit form for a single favorite) - a second, independent <dialog>
    // that can be shown on top of it, since native <dialog> elements stack.
    _openFavoritesDialog() {
      this._favoritesDialogOpen = true;
      this._render();
    }

    _closeFavoritesDialog() {
      this._favoritesDialogOpen = false;
      this._render();
    }

    async _saveFavorite() {
      const f = this._favoriteForm;
      if (!f.name.trim()) return;
      if (f.kind === "checklist") {
        const names = f.subtasks.map((s) => s.name.trim()).filter(Boolean);
        if (!names.length) {
          alert("Bitte mindestens eine Unteraufgabe für die Checkliste angeben.");
          return;
        }
      }
      const payload = {
        name: f.name.trim(),
        points: Math.max(0, Number(f.points) || 0),
        kind: f.kind === "checklist" || f.kind === "mandatory" ? f.kind : "standard",
        member_ids: [...f.member_ids],
      };
      if (f.icon) payload.icon = f.icon.trim();
      if (f.kind === "checklist") {
        payload.subtasks = f.subtasks.map((s) => ({ id: s.id, name: s.name.trim() })).filter((s) => s.name);
      }
      if (this._editingFavoriteId) {
        await this._callWS({
          type: "family_tasks/favorite/update",
          favorite_id: this._editingFavoriteId,
          ...payload,
        });
      } else {
        await this._callWS({ type: "family_tasks/favorite/create", ...payload });
      }
      this._closeFavoriteForm();
    }

    async _deleteFavorite(favoriteId) {
      const name = this._favorites[favoriteId]?.name ?? favoriteId;
      if (!confirm(`Favorit "${name}" wirklich löschen?`)) return;
      await this._callWS({ type: "family_tasks/favorite/delete", favorite_id: favoriteId });
    }

    // Erzeugt sofort eine neue, offene, einmalige Aufgabe aus der Vorlage -
    // keine Rückfrage, da genau das der Sinn des Ein-Klick-Konzepts ist (siehe
    // die Favoriten-Notiz im Datei-Header oben). Die Vorlage selbst bleibt
    // dabei unverändert und lässt sich beliebig oft erneut anklicken.
    async _instantiateFavorite(favoriteId) {
      await this._callWS({ type: "family_tasks/favorite/instantiate", favorite_id: favoriteId });
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
      // Same rule, same reasoning - see the Favoriten note in the file header
      // comment above. Also gates *seeing*/using the section at all, not
      // just editing it (unlike canManageMembers, where a non-admin can
      // still see the member list itself).
      const canManageFavorites = canManageMembers;
      // Visibility settings (v0.8) are admin/parent-only: a child's task list
      // is always filtered to their own tasks, with no toggle to change that
      // or any of the other display preferences - there's nothing for them
      // to configure, so the controls simply don't render for them.
      const showVisibilityControls = !isChildUser;
      // Compact mode: hides the section toggle buttons below (not the
      // section headers themselves) to keep the card small day-to-day. The
      // button that controls it always stays visible, top-right of the card
      // - but never for a child, since it only ever toggles the visibility
      // controls they don't have anyway.
      const controlsHidden = isChildUser ? false : this._controlsHidden;

      const membersSection = this._hideMembers
        ? controlsHidden || !showVisibilityControls
          ? ""
          : `<div class="section-toggle-row"><button class="link" data-action="toggle-hide-members">Familienmitglieder anzeigen</button></div>`
        : `
            <div class="section-header">
              <h3>Familienmitglieder</h3>
              ${controlsHidden || !showVisibilityControls ? "" : `<button class="link" data-action="toggle-hide-members">Ausblenden</button>`}
            </div>
            ${this._renderMemberList(canManageMembers)}
            ${!canManageMembers || hideAddMember ? "" : `<button class="add" data-action="new-member">+ Mitglied hinzufügen</button>`}
          `;

      const taskSection = `
        <div class="section-header">
          <h3>Aufgaben</h3>
          ${!showVisibilityControls || controlsHidden ? "" : `
            <div class="header-actions">
              <button class="link" data-action="toggle-hide-not-due">${this._hideNotDue ? "Alle anzeigen" : "Nicht fällige ausblenden"}</button>
            </div>`}
        </div>
        ${!showVisibilityControls || controlsHidden ? "" : this._renderMemberFilterChips()}
        ${this._renderTaskList(isAdmin)}
        <div class="task-actions-row">
          <div>
            ${isAdmin ? `<button class="add" data-action="new-task">+ Aufgabe hinzufügen</button>` : ""}
            ${isChildUser && !isAdmin ? `<button class="add" data-action="new-own-task">+ Eigene Aufgabe hinzufügen</button>` : ""}
          </div>
          <div>${this._renderFavoritesLauncher(canManageFavorites)}</div>
        </div>
      `;

      // v0.21: die großen Kartenbereiche (Aufgaben inkl. "hinzufügen"/
      // "Favoriten"-Buttons, Bestenliste, Belohnungen, Batterien,
      // Familienmitglieder) werden jetzt durch einen dünnen Trennstrich
      // (.section-divider) optisch voneinander abgesetzt statt nur durch
      // vertikalen Abstand - nur zwischen tatsächlich gerenderten (nicht
      // leeren) Bereichen, damit z. B. ein "Kind"-Konto (das weder
      // Batterien- noch Mitglieder-Abschnitt sieht) keine überflüssigen
      // Striche am Kartenende bekommt.
      const cardSections = [
        taskSection,
        this._renderLeaderboardSection(isAdmin, isChildUser),
        isAdmin ? this._renderBatterySection(controlsHidden, showVisibilityControls) : "",
        membersSection,
      ].filter((section) => section && section.trim());

      this.shadowRoot.innerHTML = `
        <style>${this._styles()}</style>
        <ha-card>
          <div class="card-header">
            <div class="name">${title}</div>
            ${showVisibilityControls ? `
            <button
              class="icon-btn"
              data-action="toggle-controls"
              title="${controlsHidden ? "Steuerungen einblenden" : "Steuerungen ausblenden"}"
              aria-label="${controlsHidden ? "Steuerungen einblenden" : "Steuerungen ausblenden"}"
            ><ha-icon icon="${controlsHidden ? "mdi:tune-variant" : "mdi:tune"}"></ha-icon></button>` : ""}
          </div>
          <div class="card-content">
            ${cardSections.join('<hr class="section-divider">')}
          </div>

          ${this._taskFormOpen ? `
          <dialog class="dialog" data-dialog="task">
            <h3>${this._editingTaskId ? "Aufgabe bearbeiten" : "Aufgabe hinzufügen"}</h3>
            ${this._renderTaskForm()}
          </dialog>` : ""}
          ${this._ownTaskFormOpen ? `
          <dialog class="dialog" data-dialog="own-task">
            <h3>Eigene Aufgabe hinzufügen</h3>
            ${this._renderOwnTaskForm()}
          </dialog>` : ""}
          ${this._memberFormOpen ? `
          <dialog class="dialog" data-dialog="member">
            <h3>${this._editingMemberId ? "Mitglied bearbeiten" : "Mitglied hinzufügen"}</h3>
            ${this._renderMemberForm()}
          </dialog>` : ""}
          ${this._rewardFormOpen ? `
          <dialog class="dialog" data-dialog="reward">
            <h3>${this._editingRewardId ? "Belohnung bearbeiten" : "Belohnung hinzufügen"}</h3>
            ${this._renderRewardForm()}
          </dialog>` : ""}
          ${this._favoriteFormOpen ? `
          <dialog class="dialog" data-dialog="favorite">
            <h3>${this._editingFavoriteId ? "Favorit bearbeiten" : "Favorit hinzufügen"}</h3>
            ${this._renderFavoriteForm()}
          </dialog>` : ""}
          ${this._favoritesDialogOpen ? `
          <dialog class="dialog" data-dialog="favorites-list">
            <div class="section-header">
              <h3>Favoriten</h3>
              <button type="button" class="link" data-action="close-favorites">Schließen</button>
            </div>
            ${this._renderFavoritesSection(canManageFavorites)}
          </dialog>` : ""}
          ${this._memberCompletionsDialogOpen ? `
          <dialog class="dialog" data-dialog="member-completions">
            <div class="section-header">
              <h3>${esc(this._memberName(this._memberCompletionsMemberId))}: diese Woche erledigt</h3>
              <button type="button" class="link" data-action="close-member-completions">Schließen</button>
            </div>
            ${this._renderMemberCompletionsList()}
          </dialog>` : ""}
        </ha-card>
      `;
      this._attachListenersOnce();
      this._syncDialogs();
    }

    // Opens any dialog whose *FormOpen flag is true but that isn't already
    // showing as a native modal yet (every _render() rebuilds the whole
    // shadow DOM from scratch, so a freshly (re)inserted <dialog> always
    // starts closed) - see the "Editing a task ... opens in a modal dialog"
    // note at the top of this file. Also keeps our own state in sync if the
    // dialog is closed natively (Escape key fires "cancel" then "close").
    _syncDialogs() {
      const specs = [
        ["task", () => this._taskFormOpen, () => this._closeTaskForm()],
        ["own-task", () => this._ownTaskFormOpen, () => this._closeOwnTaskForm()],
        ["member", () => this._memberFormOpen, () => this._closeMemberForm()],
        ["reward", () => this._rewardFormOpen, () => this._closeRewardForm()],
        ["favorite", () => this._favoriteFormOpen, () => this._closeFavoriteForm()],
        ["favorites-list", () => this._favoritesDialogOpen, () => this._closeFavoritesDialog()],
        ["member-completions", () => this._memberCompletionsDialogOpen, () => this._closeMemberCompletions()],
      ];
      for (const [name, isOpenFlag, close] of specs) {
        const el = this.shadowRoot.querySelector(`dialog[data-dialog="${name}"]`);
        if (!el || !isOpenFlag() || el.open) continue;
        try {
          el.showModal();
        } catch (err) {
          // Not supported / already open - nothing to do.
        }
        el.addEventListener(
          "close",
          () => {
            if (isOpenFlag()) close();
          },
          { once: true }
        );
      }
    }

    // v0.16: resolves this._taskMemberFilter to either null ("Alle", no
    // filtering) or a concrete member id - a "child" user always gets forced
    // to their own tasks regardless of the persisted filter, same rule as
    // the old onlyOwnTasks toggle enforced (children can't access these
    // controls at all, see _renderMemberFilterChips), and the "own" sentinel
    // (the first-run default) resolves freshly against whoever is currently
    // logged in rather than a member id baked in at setConfig time.
    _effectiveTaskMemberFilterId() {
      const filter = this._isChildUser() ? "own" : this._taskMemberFilter;
      if (filter === null || filter === undefined) return null;
      return filter === "own" ? this._currentMemberId() : filter;
    }

    _renderTaskList(isAdmin) {
      let ids = Object.keys(this._tasks);
      const currentMemberId = this._currentMemberId();
      // v0.22: a task a "child" member created for themselves (see
      // "created_by_member_id" / CONF_TASK_CREATED_BY_MEMBER_ID in const.py,
      // set by ws_create_own_task in storage.py) is only ever visible to
      // whoever created it - not even a parent/admin sees it in the normal
      // task list, so a child's casual self-reminder doesn't clutter
      // everyone else's view. The coordinator-generated parent-confirmation
      // task raised once such a task is actually completed (if
      // requires_confirmation is set) is a *separate* task entity with no
      // created_by_member_id of its own, so it's unaffected and still shows
      // up for parents as normal.
      ids = ids.filter((id) => {
        const createdBy = this._tasks[id].created_by_member_id;
        return !createdBy || createdBy === currentMemberId;
      });
      const totalCount = ids.length;
      if (this._hideNotDue) {
        ids = ids.filter((id) => DUE_STATUSES.includes(this._statusStateForTask(id)?.state ?? "pending"));
      }
      const filterMemberId = this._effectiveTaskMemberFilterId();
      if (filterMemberId !== null) {
        ids = ids.filter((id) => {
          if (!filterMemberId) return false;
          // assigned_member_ids already lists every member currently
          // responsible - just [assigned_member_id] for most rotation
          // strategies, but every selected member for a "fixed" rotation
          // with more than one assignee (see
          // FamilyTasksCoordinator._assigned_member_ids in coordinator.py) -
          // so a single membership check covers both cases.
          const assignedIds = this._statusStateForTask(id)?.attributes?.assigned_member_ids ?? [];
          return assignedIds.includes(filterMemberId);
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
          // v0.14: called out to the child as mandatory - see
          // TASK_KIND_MANDATORY in const.py. While overdue, tick-based
          // screen-time granting pauses for whoever it's assigned to (see
          // the "Handyzeitgewährung aktiv" binary_sensor per member).
          const isMandatory = task.kind === "mandatory";
          // Auto-generated by the coordinator when a child's task needs
          // parental sign-off (see async_complete_task in coordinator.py) -
          // read-only row, and "Bestätigen"/"Ablehnen" mean confirm/reject.
          const isConfirmation = !!task.confirms;
          const batteryEntities = statusState?.attributes?.battery_entities ?? [];
          const subtasks = statusState?.attributes?.subtasks ?? [];
          const triggerValue = statusState?.attributes?.trigger_sensor_value;
          const triggerUnit = statusState?.attributes?.trigger_sensor_unit;
          // Only the sensor's current value is shown here, not which entity
          // it is - that's a configuration detail visible in the edit form,
          // not on the task card itself (v0.9).
          const triggerValueLabel =
            triggerValue !== undefined && triggerValue !== null && triggerValue !== ""
              ? `${esc(triggerValue)}${triggerUnit ? ` ${esc(triggerUnit)}` : ""}`
              : "–";
          const assigneeLabel = assignedIds.length
            ? assignedIds.map((mid) => esc(this._memberName(mid))).join(", ")
            : "–";
          const detail = isConfirmation
            ? `Bestätigung für ${esc(this._memberName(task.confirms.member_id))}`
            : isChecklist
            ? `${subtasks.filter((s) => s.checked).length}/${subtasks.length} erledigt`
            : isTrigger
            ? `Sensor: ${triggerValueLabel}`
            : isBattery
            ? batteryEntities.length
              ? batteryEntities
                  .map((b) => esc(`${b.name}${b.level !== null && b.level !== undefined ? ` (${b.level}%)` : " (niedrig)"}`))
                  .join(", ")
              : "Keine Batterie niedrig"
            : `${assigneeLabel} · ${esc(task.points ?? 0)} Pkt.`;
          const resolved = status === "done" || status === "idle" || status === "awaiting_confirmation";
          // v0.22: the plain "Überspringen" button (skip to the next
          // occurrence of a recurring task) is removed entirely. The
          // parent-confirmation flow's "Ablehnen" (reject the child's claim)
          // is a distinct action - reusing the same skip-task service call
          // under a different label - and stays available, since a parent
          // still needs a way to reject a child's completion claim.
          const showReject = isConfirmation;
          // v0.22: "Erledigt"/"Bestätigen" only renders for whoever the
          // occurrence is actually assigned to (or, for a parent-
          // confirmation task, one of the household's parents) - see the
          // file header/CHANGELOG note. A user with no linked family member
          // (currentMemberId null) never matches any assignedIds, so they
          // simply never see the button, same as before this member never
          // being one of the assignees.
          const canAct = assignedIds.includes(currentMemberId);
          // A checklist task only becomes "done" once every sub-item is
          // checked (see async_toggle_subtask in coordinator.py) - the
          // manual "Erledigt" button is disabled for it so completion always
          // goes through the checklist itself.
          const disableComplete = resolved || isChecklist;
          // Alphabetical, unchecked items first (v0.12): a checklist can grow
          // to a couple dozen items (e.g. a packing list) and the backend
          // preserves whatever order they were originally typed in, which
          // stops being useful once several are checked off in different
          // sessions. Sorting open items alphabetically first, then done
          // items alphabetically, keeps the still-open work easy to scan at
          // the top without the list visually reshuffling item-by-item as
          // things get checked (each item only ever moves into the "done"
          // block, never around within it).
          const sortedSubtasks = [...subtasks].sort((a, b) => {
            if (a.checked !== b.checked) return a.checked ? 1 : -1;
            return a.name.localeCompare(b.name, "de", { sensitivity: "base" });
          });
          const subtaskList = isChecklist && subtasks.length
            ? `<div class="subtask-list">${sortedSubtasks
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
                  ${isMandatory ? `<span class="badge" style="background:var(--error-color, #db4437)">Pflicht</span>` : ""}
                  <span class="name">${task.icon ? `<ha-icon icon="${esc(task.icon)}"></ha-icon> ` : ""}${esc(task.name)}</span>
                  <span class="muted">${detail}</span>
                </div>
                <div class="row-actions">
                  ${canAct ? iconActionButton("complete-task", isConfirmation ? "mdi:check-bold" : "mdi:check", isConfirmation ? "Bestätigen" : "Erledigt", { dataset: `data-task-id="${id}"`, extraClass: "success", disabled: disableComplete }) : ""}
                  ${showReject && canAct ? iconActionButton("skip-task", "mdi:close", "Ablehnen", { dataset: `data-task-id="${id}"`, extraClass: "danger", disabled: resolved }) : ""}
                  ${isConfirmation || !isAdmin ? "" : `
                  ${iconActionButton("edit-task", "mdi:pencil", "Bearbeiten", { dataset: `data-task-id="${id}"` })}
                  ${iconActionButton("delete-task", "mdi:delete", "Löschen", { dataset: `data-task-id="${id}"`, extraClass: "danger" })}`}
                </div>
              </div>
              ${subtaskList}
            </div>`;
        })
        .join("")}</div>`;
    }

    // v0.16: filter chips at the top of the "Aufgaben" section, replacing
    // the old plain "Nur eigene Aufgaben"/"Alle Aufgaben anzeigen" toggle
    // button - "Alle" plus one chip per family member, so a parent can just
    // as easily narrow the list down to one specific child's tasks instead
    // of only being able to pick between "everything" and "just me". Never
    // rendered for a "child" user (see the call site in _render, same
    // showVisibilityControls gating as the other visibility toggles) since
    // their list is always forced to their own tasks regardless.
    _renderMemberFilterChips() {
      const activeFilterId = this._effectiveTaskMemberFilterId();
      const memberChips = Object.keys(this._members)
        .map((id) => {
          const member = this._members[id];
          const active = activeFilterId === id;
          return `
            <button class="chip-filter ${active ? "active" : ""}" data-action="filter-member" data-member-id="${id}">
              ${member.icon ? `<ha-icon icon="${esc(member.icon)}"></ha-icon> ` : ""}${esc(member.name)}
            </button>`;
        })
        .join("");
      return `
        <div class="member-filter-row">
          <button class="chip-filter ${activeFilterId === null ? "active" : ""}" data-action="filter-member" data-member-id="">Alle</button>
          ${memberChips}
        </div>`;
    }

    // v0.17: parent-only "Favoriten" catalog - a reusable task-template list
    // (family_tasks/favorite/*, see the file header comment above and
    // FavoriteStorageCollection in storage.py). Structurally mirrors
    // _renderRewardsSection below (a small parent-maintained list with
    // Bearbeiten/Löschen, plus a "+ ... hinzufügen" button), not the old
    // v0.16 quick-complete bar this replaces - the primary action per row is
    // "Aufgabe erstellen" (family_tasks/favorite/instantiate), not
    // "Erledigt". Never rendered at all for a non-parent (canManageFavorites
    // false) - unlike the reward catalog, there is nothing here for a child
    // to see or use, so the whole section (including the ability to
    // instantiate) is admin/parent-only, not just management.
    //
    // v0.21: no longer inlined into the "Aufgaben" section (that was the
    // v0.19 collapsible-section approach, _hideFavorites) - this now only
    // renders the *content* of the "Favoriten" dialog opened via
    // _renderFavoritesLauncher/_openFavoritesDialog below, so it no longer
    // needs its own hide toggle or heading (the dialog wrapper in _render()
    // supplies the "Favoriten" <h3> and a "Schließen" button).
    _renderFavoritesSection(canManageFavorites) {
      if (!canManageFavorites) return "";
      const favoriteIds = Object.keys(this._favorites).sort((a, b) =>
        (this._favorites[a].name ?? "").localeCompare(this._favorites[b].name ?? "", "de", { sensitivity: "base" })
      );
      const list = favoriteIds.length
        ? `<div class="list">${favoriteIds
            .map((id) => {
              const f = this._favorites[id];
              const memberNames = (f.member_ids ?? []).map((mid) => this._memberName(mid)).join(", ");
              const detailParts = [pointsLabel(f.points ?? 0)];
              if (memberNames) detailParts.push(memberNames);
              if (f.kind === "checklist") detailParts.push("Checkliste");
              if (f.kind === "mandatory") detailParts.push("Pflichtaufgabe");
              return `
                <div class="row">
                  <div class="row-main">
                    <span class="name">${f.icon ? `<ha-icon icon="${esc(f.icon)}"></ha-icon> ` : ""}${esc(f.name)}</span>
                    <span class="muted">${esc(detailParts.join(" · "))}</span>
                  </div>
                  <div class="row-actions">
                    ${iconActionButton("instantiate-favorite", "mdi:playlist-plus", "Aufgabe erstellen", { dataset: `data-favorite-id="${id}"`, extraClass: "success" })}
                    ${iconActionButton("edit-favorite", "mdi:pencil", "Bearbeiten", { dataset: `data-favorite-id="${id}"` })}
                    ${iconActionButton("delete-favorite", "mdi:delete", "Löschen", { dataset: `data-favorite-id="${id}"`, extraClass: "danger" })}
                  </div>
                </div>`;
            })
            .join("")}</div>`
        : `<p class="muted">Noch keine Favoriten angelegt.</p>`;
      return `
        ${list}
        <button class="add" data-action="new-favorite">+ Favorit hinzufügen</button>`;
    }

    // v0.21: small launcher button in the "Aufgaben" section (next to "+
    // Aufgabe hinzufügen") that opens the "Favoriten" catalog in its own
    // modal dialog instead of rendering the whole catalog inline - keeps the
    // regularly-used task view from growing with every favorite a household
    // adds. Shows the current favorite count so there's a hint of what's
    // behind it without opening the dialog. Same admin/parent-only gating as
    // the catalog itself.
    _renderFavoritesLauncher(canManageFavorites) {
      if (!canManageFavorites) return "";
      const count = Object.keys(this._favorites).length;
      return `<button class="add" data-action="open-favorites">${count ? `Favoriten (${count})` : "Favoriten"}</button>`;
    }

    _renderMemberList(canManageMembers) {
      const ids = Object.keys(this._members);
      if (!ids.length) return `<p class="muted">Noch keine Familienmitglieder angelegt.</p>`;

      return `<div class="list">${ids
        .map((id) => {
          const member = this._members[id];
          // Only the member's own name is shown here (v0.10) - the linked
          // person entity id used to be appended too, but that's an internal
          // configuration detail (edited via the member form), not something
          // that belongs on the card itself.
          const statusParts = [];
          if (member.active === false) statusParts.push("inaktiv");
          if (member.role === "child") statusParts.push("Kind");
          if (member.participates_in_rewards === false) statusParts.push("nimmt nicht an Belohnungen teil");
          return `
            <div class="row">
              <div class="row-main">
                <span class="name">${esc(member.name)}</span>
                ${statusParts.length ? `<span class="muted">${esc(statusParts.join(" · "))}</span>` : ""}
              </div>
              ${canManageMembers ? `
              <div class="row-actions">
                ${iconActionButton("edit-member", "mdi:pencil", "Bearbeiten", { dataset: `data-member-id="${id}"` })}
                ${iconActionButton("delete-member", "mdi:delete", "Löschen", { dataset: `data-member-id="${id}"`, extraClass: "danger" })}
              </div>` : ""}
            </div>`;
        })
        .join("")}</div>`;
    }

    // Bestenliste + Belohnungen (v0.15, gemerged aus der ehemals
    // eigenständigen family-tasks-leaderboard-card.js - siehe Datei-Header).
    // Anders als "Familienmitglieder"/"Batterien" ist der Zugriff selbst
    // nicht eingeschränkt: die Rangliste und der Belohnungs-Katalog sind für
    // jeden - auch ein "Kind"-Konto - immer nutzbar, da ein Kind hier
    // auswählen/einlösen können muss, nicht nur Eltern etwas zu
    // konfigurieren haben. Seit v0.21 aber jeweils für sich ausblendbar
    // (_renderRankingSection/_renderRewardsSection unten) - siehe dort für
    // die Begründung, warum die Umschalter dafür trotzdem für alle
    // sichtbar bleiben.
    _renderLeaderboardSection(isAdmin, isChildUser) {
      // Gleiche Regel wie canManageMembers oben - ein "Kind"-verknüpfter
      // Nutzer bekommt keine Katalog-/Einlösungs-Verwaltung, unabhängig vom
      // HA-Admin-Flag (serverseitig ebenfalls erzwungen, siehe
      // RewardRedemptionStorageCollectionWebsocket in storage.py).
      const canManageRewards = isAdmin && !isChildUser;
      const currentMemberId = this._currentMemberId();
      return `
        ${this._renderRankingSection()}
        <hr class="section-divider">
        ${this._renderRewardsSection(canManageRewards, currentMemberId)}
      `;
    }

    // v0.21: "Bestenliste" ausblendbar, wie schon länger "Familienmitglieder"/
    // "Batterien"/(bis v0.20) "Favoriten" - anders als bei diesen ist der
    // Umschalter hier aber *nicht* an showVisibilityControls/controlsHidden
    // gekoppelt (also nicht Eltern-only und nicht vom Kompakt-Modus-Button
    // betroffen): die Bestenliste ist für ein "Kind"-Konto genauso relevant
    // wie für Eltern, das Ausblenden ist hier reiner Anzeige-Komfort pro
    // Gerät, keine Admin-Einstellung. Startet standardmäßig sichtbar (siehe
    // setConfig) - anders als der v0.11-Kompakt-Default der übrigen
    // Abschnitte, da ein Kind sonst beim allerersten Laden gar nicht sähe,
    // dass es hier etwas einlösen kann.
    _renderRankingSection() {
      if (this._hideLeaderboard) {
        return `<div class="section-toggle-row"><button class="link" data-action="toggle-hide-leaderboard">Bestenliste anzeigen</button></div>`;
      }
      const ranked = this._rankedMembers();
      const maxPoints = ranked.length ? Math.max(...ranked.map((r) => r.points), 1) : 1;
      // v0.22: jede Zeile öffnet per Klick einen Dialog mit den diese Woche
      // von diesem Mitglied erledigten Aufgaben - siehe
      // _openMemberCompletions. role="button"/tabindex sorgen zusammen mit
      // dem Enter/Leertaste-Handler in _attachListenersOnce für einfache
      // Tastaturbedienbarkeit.
      const rankingList = ranked.length
        ? `<div class="list">${ranked
            .map((entry, index) => {
              const pct = Math.round((entry.points / maxPoints) * 100);
              const available = this._availablePointsFor(entry.id);
              return `
                <div class="row clickable" data-action="open-member-completions" data-member-id="${entry.id}" role="button" tabindex="0">
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
        : `<p class="muted">Noch keine teilnehmenden Familienmitglieder.</p>`;

      // v0.22: Bonuspunkte für den Wochensieger (siehe
      // CONF_WEEKLY_WINNER_BONUS_ENABLED/...POINTS in const.py) oben in der
      // Bestenliste anzeigen, sofern der Haushalt die Funktion aktiviert hat
      // - reine Anzeige, die eigentliche Vergabe übernimmt weiterhin
      // FamilyTasksCoordinator._async_process_weekly_winner_bonus.
      const bonus = this._weeklyWinnerBonus();

      return `
        <div class="section-header">
          <h3>Bestenliste</h3>
          <button class="link" data-action="toggle-hide-leaderboard">Ausblenden</button>
        </div>
        ${bonus.enabled && bonus.points > 0 ? `<p class="muted">Wochensieger-Bonus: ${pointsLabel(bonus.points)}</p>` : ""}
        ${rankingList}
      `;
    }

    // v0.22: Inhalt des "diese Woche erledigt"-Dialogs, geöffnet per Klick
    // auf eine Bestenlisten-Zeile - siehe _openMemberCompletions.
    _renderMemberCompletionsList() {
      if (this._memberCompletionsLoading) return `<p class="muted">Lädt…</p>`;
      if (!this._memberCompletions.length) {
        return `<p class="muted">Diese Woche noch keine Aufgabe erledigt.</p>`;
      }
      return `<div class="list">${this._memberCompletions
        .map((c) => {
          const when = c.completed_at
            ? new Date(c.completed_at).toLocaleString("de-DE", {
                weekday: "short",
                hour: "2-digit",
                minute: "2-digit",
              })
            : "";
          return `
            <div class="row">
              <div class="row-main">
                <span class="name">${esc(c.task_name)}</span>
                <span class="muted">${esc(when)}${c.points_awarded ? ` · ${pointsLabel(c.points_awarded)}` : ""}</span>
              </div>
            </div>`;
        })
        .join("")}</div>`;
    }

    // v0.21: "Belohnungen" ausblendbar - gleiches Muster/gleiche Begründung
    // wie _renderRankingSection oben (für alle sichtbarer Umschalter, nicht
    // Eltern-only, standardmäßig sichtbar). Umfasst sowohl den Katalog als
    // auch "Bisherige Einlösungen" als einen gemeinsamen Block - dessen
    // eigener _hideFulfilled-Umschalter bleibt unverändert eine Ebene
    // darunter bestehen.
    _renderRewardsSection(canManageRewards, currentMemberId) {
      if (this._hideRewards) {
        return `<div class="section-toggle-row"><button class="link" data-action="toggle-hide-rewards">Belohnungen anzeigen</button></div>`;
      }
      return this._renderRewardsContent(canManageRewards, currentMemberId);
    }

    _renderRewardsContent(canManageRewards, currentMemberId) {
      const currentMember = currentMemberId ? this._members[currentMemberId] : null;
      const currentParticipates = !!currentMember && currentMember.participates_in_rewards !== false;
      const availablePoints = currentMemberId ? this._availablePointsFor(currentMemberId) : 0;

      const rewardIds = Object.keys(this._rewards).sort(
        (a, b) => (this._rewards[a].points_cost ?? 0) - (this._rewards[b].points_cost ?? 0)
      );
      // Jede Katalog-Belohnung samt Preis ist für jeden immer sichtbar - auch
      // für ein Kind, das sehen soll was verfügbar ist und was es kostet,
      // selbst wenn es sich das gerade nicht leisten kann. Nur "Auswählen"
      // ist an Teilnahme+Leistbarkeit gebunden, "Bearbeiten"/"Löschen" an
      // canManageRewards.
      const catalogList = rewardIds.length
        ? `<div class="list">${rewardIds
            .map((id) => {
              const r = this._rewards[id];
              const isInvestable = !!r.screen_time_investable;
              const cost = r.points_cost ?? 0;
              // Eine investierbare Handyzeit-Belohnung (v0.14) hat keinen
              // festen Preis - das Mitglied wählt beim Einlösen, wie viele
              // Punkte investiert werden - daher genügt für Leistbarkeit
              // mindestens 1 verfügbarer Punkt statt eines konkreten Preises.
              const affordable = currentParticipates && (isInvestable ? availablePoints >= 1 : availablePoints >= cost);
              const isPending = this._pendingRedeemId === id;
              const priceLabel = isInvestable ? "Punkte frei wählbar" : `${pointsLabel(cost)}${screenTimeSuffix(r.screen_time_minutes)}`;
              return `
                <div class="row-wrap">
                  <div class="row">
                    <div class="row-main">
                      <span class="name">${r.icon ? `<ha-icon icon="${esc(r.icon)}"></ha-icon> ` : ""}${esc(r.name)}</span>
                      <span class="muted">${priceLabel}</span>
                    </div>
                    <div class="row-actions">
                      ${currentMemberId && currentParticipates ? `<button data-action="select-reward" data-reward-id="${id}" ${affordable ? "" : "disabled"}>Auswählen</button>` : ""}
                      ${canManageRewards ? `
                      ${iconActionButton("edit-reward", "mdi:pencil", "Bearbeiten", { dataset: `data-reward-id="${id}"` })}
                      ${iconActionButton("delete-reward", "mdi:delete", "Löschen", { dataset: `data-reward-id="${id}"`, extraClass: "danger" })}` : ""}
                    </div>
                  </div>
                  ${isPending && isInvestable ? `
                  <div class="confirm-row">
                    <label>Punkte investieren
                      <input type="number" min="1" max="${availablePoints}" data-action="invest-points" data-reward-id="${id}" value="${esc(this._pendingInvestPoints ?? 1)}">
                    </label>
                    <button data-action="confirm-redeem" data-reward-id="${id}" ${this._pendingInvestPoints >= 1 && this._pendingInvestPoints <= availablePoints ? "" : "disabled"}>Bestätigen</button>
                    <button type="button" class="link" data-action="cancel-redeem">Abbrechen</button>
                  </div>` : ""}
                  ${isPending && !isInvestable ? `
                  <div class="confirm-row">
                    <span>„${esc(r.name)}" für ${pointsLabel(cost)} einlösen?</span>
                    <button data-action="confirm-redeem" data-reward-id="${id}">Bestätigen</button>
                    <button type="button" class="link" data-action="cancel-redeem">Abbrechen</button>
                  </div>` : ""}
                </div>`;
            })
            .join("")}</div>`
        : `<p class="muted">Noch keine Belohnungen angelegt.</p>`;

      // Erledigte Einlösungen sind standardmäßig ausgeblendet - siehe
      // _hideFulfilled in setConfig - da ein Haushalt, der regelmäßig
      // einlöst, sonst schnell eine größtenteils erledigte Liste ansammelt.
      const allRedemptionIds = Object.keys(this._redemptions).sort((a, b) =>
        (this._redemptions[b].redeemed_at ?? "").localeCompare(this._redemptions[a].redeemed_at ?? "")
      );
      const redemptionIds = this._hideFulfilled
        ? allRedemptionIds.filter((id) => !this._redemptions[id].fulfilled)
        : allRedemptionIds;
      const historyList = redemptionIds.length
        ? `<div class="list">${redemptionIds
            .map((id) => {
              const r = this._redemptions[id];
              return `
                <div class="row">
                  <div class="row-main">
                    <span class="name">${esc(r.member_name)} · ${esc(r.reward_name)}</span>
                    <span class="muted">${pointsLabel(r.points_cost ?? 0)}${screenTimeSuffix(r.screen_time_minutes)}${r.fulfilled ? " · erledigt" : ""}</span>
                  </div>
                  ${!r.fulfilled && canManageRewards ? `
                  <div class="row-actions">
                    ${iconActionButton("fulfill-redemption", "mdi:check", "Als erledigt markieren", { dataset: `data-redemption-id="${id}"`, extraClass: "success" })}
                  </div>` : ""}
                </div>`;
            })
            .join("")}</div>`
        : `<p class="muted">${
            allRedemptionIds.length ? "Keine offenen Einlösungen." : "Noch keine Belohnungen eingelöst."
          }</p>`;

      return `
        <div class="section-header">
          <h4>Belohnungen</h4>
          <button class="link" data-action="toggle-hide-rewards">Ausblenden</button>
        </div>
        ${currentMemberId ? `<p class="muted">Dein Guthaben: ${pointsLabel(availablePoints)}${currentParticipates ? "" : " (nimmt nicht am Belohnungssystem teil)"}</p>` : ""}
        ${catalogList}
        ${canManageRewards ? `<button class="add" data-action="new-reward">+ Belohnung hinzufügen</button>` : ""}
        <div class="section-header">
          <h4>Bisherige Einlösungen</h4>
          ${allRedemptionIds.length ? `<button class="link" data-action="toggle-hide-fulfilled">${this._hideFulfilled ? "Erledigte anzeigen" : "Erledigte ausblenden"}</button>` : ""}
        </div>
        ${historyList}
      `;
    }

    _renderRewardForm() {
      const f = this._rewardForm;
      const isScreenTime = f.reward_type === "screen_time";
      const isInvestable = isScreenTime && !!f.screen_time_investable;
      return `
        <form class="form" data-form="reward">
          <label>Name<input type="text" data-reward-field="name" placeholder="z. B. Filmabend aussuchen" value="${esc(f.name)}" required></label>
          <label>Icon (optional)<input type="text" data-reward-field="icon" placeholder="mdi:gift" value="${esc(f.icon)}"></label>
          ${isInvestable ? "" : `
          <label>Preis (Punkte)<input type="number" min="0" data-reward-field="points_cost" value="${esc(f.points_cost)}"></label>
          `}
          <label>Belohnungstyp
            <select data-reward-field="reward_type">
              <option value="custom" ${!isScreenTime ? "selected" : ""}>Sonstige</option>
              <option value="screen_time" ${isScreenTime ? "selected" : ""}>Handyzeit</option>
            </select>
          </label>
          ${isScreenTime ? `
          <label class="checkbox-label">
            <input type="checkbox" data-reward-field="screen_time_investable" ${isInvestable ? "checked" : ""}>
            Kind wählt Punkte selbst aus (Minuten = investierte Punkte × Bonusfaktor aus den Integrations-Optionen)
          </label>
          ` : ""}
          ${isScreenTime && !isInvestable ? `
          <label>Bildschirmzeit in Minuten<input type="number" min="1" data-reward-field="screen_time_minutes" placeholder="z. B. 30" value="${esc(f.screen_time_minutes)}" required></label>
          ` : ""}
          <label class="checkbox-label">
            <input type="checkbox" data-reward-field="auto_fulfill" ${f.auto_fulfill ? "checked" : ""}>
            Gilt mit der Einlösung sofort als erledigt${isScreenTime ? " (bei Handyzeit meist sinnvoll, da automatisch gewährt)" : ""}
          </label>
          <div class="form-actions">
            <button type="submit" data-action="save-reward">Speichern</button>
            <button type="button" data-action="cancel-reward-form">Abbrechen</button>
          </div>
        </form>`;
    }

    // Nutzt den generischen data-field/_formSpec-Mechanismus (wie das
    // Aufgaben-Formular), nicht das data-reward-field-Muster des
    // Belohnungs-Formulars direkt oberhalb - dadurch funktionieren
    // add-subtask/remove-subtask (Checkliste) hier ohne eigenen Code, siehe
    // _formSpec/_applyFieldChange.
    _renderFavoriteForm() {
      const f = this._favoriteForm;
      // v0.18: multi-select checkboxes for the fixed assignee(s)
      // (f.member_ids), mirroring the task form's rotation checkboxes -
      // originally (v0.17) a single optional <select> (f.member_id).
      const memberCheckboxes = Object.keys(this._members)
        .map((id) => {
          const checked = f.member_ids.includes(id) ? "checked" : "";
          return `<label class="chip"><input type="checkbox" data-field="member_ids" value="${id}" ${checked}> ${esc(this._members[id].name)}</label>`;
        })
        .join("") || `<p class="muted">Erst Familienmitglieder anlegen.</p>`;
      return `
        <form class="form" data-form="favorite">
          <label>Name<input type="text" data-field="name" placeholder="z. B. Auto waschen" value="${esc(f.name)}" required></label>
          <div class="grid2">
            <label>Punkte<input type="number" min="0" data-field="points" value="${esc(f.points)}"></label>
            <label>Icon (optional)<input type="text" data-field="icon" placeholder="mdi:car-wash" value="${esc(f.icon)}"></label>
          </div>
          <label>Fest zugewiesen an (optional, mehrere möglich)</label>
          <div class="chips">${memberCheckboxes}</div>
          <label>Aufgabentyp
            <select data-field="kind">
              <option value="standard" ${f.kind !== "checklist" && f.kind !== "mandatory" ? "selected" : ""}>Standard</option>
              <option value="checklist" ${f.kind === "checklist" ? "selected" : ""}>Checkliste</option>
              <option value="mandatory" ${f.kind === "mandatory" ? "selected" : ""}>Pflichtaufgabe</option>
            </select>
          </label>
          ${f.kind === "checklist" ? this._renderSubtaskEditor(f.subtasks) : ""}
          <p class="muted">Jede daraus erstellte Aufgabe ist immer einmalig (keine Wiederholung) und offen, nicht bereits erledigt.</p>
          <div class="form-actions">
            <button type="submit" data-action="save-favorite">Speichern</button>
            <button type="button" data-action="cancel-favorite-form">Abbrechen</button>
          </div>
        </form>`;
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
    _renderBatterySection(controlsHidden, showVisibilityControls) {
      if (this._hideBattery) {
        return controlsHidden || !showVisibilityControls
          ? ""
          : `<div class="section-toggle-row"><button class="link" data-action="toggle-hide-battery">Batterien anzeigen</button></div>`;
      }
      const batteries = this._batteryEntityOptions();
      return `
        <div class="section-header">
          <h3>Batterien</h3>
          ${controlsHidden || !showVisibilityControls ? "" : `<button class="link" data-action="toggle-hide-battery">Ausblenden</button>`}
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
              <option value="standard" ${f.kind !== "checklist" && f.kind !== "mandatory" ? "selected" : ""}>Standard</option>
              <option value="checklist" ${f.kind === "checklist" ? "selected" : ""}>Checkliste</option>
              <option value="mandatory" ${f.kind === "mandatory" ? "selected" : ""}>Pflichtaufgabe</option>
            </select>
          </label>
          ${f.kind === "mandatory" ? `<p class="muted">Pflichtaufgaben werden dem Kind besonders gekennzeichnet. Wird eine Pflichtaufgabe überfällig, pausiert die tick-basierte Handyzeitgewährung (siehe Entity "Handyzeitgewährung aktiv") für genau die Nutzer, denen sie zugewiesen ist, bis sie erledigt ist.</p>` : ""}
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

          <label>Aufgabentyp
            <select data-field="kind">
              <option value="standard" ${f.kind !== "checklist" ? "selected" : ""}>Standard</option>
              <option value="checklist" ${f.kind === "checklist" ? "selected" : ""}>Checkliste</option>
            </select>
          </label>
          ${f.kind === "checklist" ? this._renderSubtaskEditor(f.subtasks) : ""}

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
          <label class="inline"><input type="checkbox" data-field="participates_in_rewards" ${f.participates_in_rewards ? "checked" : ""}> Nimmt am Belohnungssystem teil (Leaderboard &amp; Belohnungen einlösen)</label>
          <label>Notify-Service für Push-Benachrichtigungen (optional)<input type="text" data-field="notify_service" placeholder="z. B. mobile_app_pixel_8" value="${esc(f.notify_service)}"></label>
          <p class="muted">Wird bei neuen, diesem Mitglied zugewiesenen Aufgaben aufgerufen (notify.&lt;Wert&gt;), damit die Benachrichtigung wirklich auf dem Handy erscheint - ohne das hier landet nur eine Home-Assistant-interne Benachrichtigung, keine echte Push-Nachricht. Der Name der Companion-App-Notify-Entity ist unter Einstellungen → Geräte &amp; Dienste → &lt;Gerätename&gt; zu finden.</p>
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
        /* flex: 1 (v0.16 fix): without it, .row-main only ever sized itself to
           its own content width - and since .row uses justify-content:
           space-between with just two children (.rank/.row-actions and
           .row-main), that content-sized box got pushed flush to the row's
           right edge instead of stretching to fill the space after .rank.
           The Bestenliste's .row-top (name/points, itself space-between)
           then had a different-width box to work with on every row - a
           short name gave it a narrow box hugging the right edge, a long
           name a wide one starting further left - so the "Pkt." column
           never lined up between rows despite looking like it should.
           Letting .row-main actually fill the row makes its inner
           space-between consistent across every row. */
        .row-main { display: flex; flex-direction: column; gap: 2px; min-width: 0; flex: 1; }
        .row-actions { display: flex; gap: 2px; flex-wrap: nowrap; justify-content: flex-end; flex-shrink: 0; }
        /* v0.22: Erledigt/Bearbeiten/Löschen (und die entsprechenden
           Aktionen anderswo auf der Karte - Favoriten, Belohnungen,
           Einlösungen) sind jetzt kleine runde Icon-Buttons statt großer
           Text-Buttons (.icon-action-btn) - dadurch passen sie auch auf
           schmalen (Handy-)Bildschirmen ohne Weiteres neben .row-main in
           dieselbe Zeile, ohne sie zu überlagern. Ersetzt die bis v0.21
           nötige Sonderbehandlung unterhalb von 480px (.row-main/.row-actions
           komplett untereinander, Buttons einzeln auf voller Breite) - die
           ist mit den kompakten Icon-Buttons nicht mehr nötig. */
        .icon-action-btn { background: none; border: none; border-radius: 50%; width: 30px; height: 30px;
                            padding: 0; display: inline-flex; align-items: center; justify-content: center;
                            color: var(--secondary-text-color); cursor: pointer; flex-shrink: 0; }
        .icon-action-btn:hover { background: var(--card-background-color, #fff); }
        .icon-action-btn:disabled { opacity: 0.4; cursor: default; background: none; }
        .icon-action-btn ha-icon { --mdc-icon-size: 18px; }
        .icon-action-btn.success { color: var(--success-color, #43a047); }
        .icon-action-btn.danger { color: var(--error-color, #db4437); }
        /* "+ Aufgabe hinzufügen"/"+ Eigene Aufgabe hinzufügen" links, der
           "Favoriten"-Launcher rechts, in derselben Reihe (v0.22) - ist der
           rechte Teil leer (kein Favoriten-Zugriff), bleibt der linke Teil
           dank justify-content: space-between trotzdem einfach linksbündig. */
        .task-actions-row { display: flex; justify-content: space-between; align-items: center;
                              gap: 8px; flex-wrap: wrap; }
        .task-actions-row button.add { padding: 8px 0; }
        /* v0.22: klickbare Bestenlisten-Zeile (öffnet die "diese Woche
           erledigt"-Übersicht für das jeweilige Mitglied, siehe
           _openMemberCompletions) - optische/Tastatur-Hinweise, dass die
           ganze Zeile ein Button ist. */
        .row.clickable { cursor: pointer; }
        .row.clickable:hover { background: var(--card-background-color, #fff); }
        .row.clickable:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }
        @media (max-width: 480px) {
          .row { flex-wrap: wrap; }
          .row-main { flex-basis: 100%; }
          .row-actions { flex-basis: 100%; justify-content: flex-start; }
        }
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
        .form label.checkbox-label { flex-direction: row; align-items: center; gap: 8px; }
        .form input[type="checkbox"] { width: auto; }
        h4 { margin: 12px 0 8px; font-size: 0.95em; color: var(--secondary-text-color); }
        /* Aufgaben-Filter nach Familienmitglied (v0.16) - dieselbe Chip-Optik
           wie die Bestenliste einst für ihre Woche/Monat-Tabs verwendet hat. */
        .member-filter-row { display: flex; gap: 4px; margin: 4px 0 12px; flex-wrap: wrap; }
        .chip-filter { border: none; border-radius: 6px; padding: 6px 14px; font-size: 0.85em;
               background: var(--secondary-background-color, #f2f2f2); color: var(--secondary-text-color);
               cursor: pointer; }
        .chip-filter.active { background: var(--primary-color); color: var(--text-primary-color, #fff); }
        .rank { width: 22px; text-align: center; font-weight: 500; color: var(--secondary-text-color); flex-shrink: 0; }
        .row-top { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
        .points { font-size: 0.85em; color: var(--secondary-text-color); flex-shrink: 0; }
        .balance { font-size: 0.8em; color: var(--secondary-text-color); }
        .bar-track { height: 6px; border-radius: 3px; background: var(--secondary-background-color, #f2f2f2); overflow: hidden; }
        .bar-fill { height: 100%; border-radius: 3px; background: var(--primary-color); }
        .confirm-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding: 8px;
                       border-radius: 8px; background: var(--secondary-background-color, #f2f2f2); font-size: 0.9em; }
        /* Each collapsed-section "... anzeigen" button gets its own block-
           level row (v0.9) - without this, two adjacent buttons with no
           wrapping element between them would sit side by side. */
        .section-toggle-row { display: block; margin: 4px 0; }
        /* v0.21: dünner Trennstrich zwischen den großen Kartenbereichen
           (Aufgaben, Bestenliste, Belohnungen, Batterien,
           Familienmitglieder) - siehe cardSections in _render(). */
        hr.section-divider { border: none; border-top: 1px solid var(--divider-color, #e0e0e0); margin: 16px 0; }
        /* Native modal dialog (task editing/creation, v0.8) - shown via
           showModal() so it always renders on top of the whole page, never
           hidden behind other open cards. */
        dialog.dialog { border: none; border-radius: 12px; padding: 16px; max-width: 480px;
                         width: calc(100vw - 32px); max-height: calc(100vh - 64px); overflow: auto;
                         background: var(--card-background-color, #fff); color: var(--primary-text-color);
                         box-shadow: 0 8px 28px rgba(0, 0, 0, 0.3); }
        dialog.dialog::backdrop { background: rgba(0, 0, 0, 0.5); }
        dialog.dialog h3 { margin: 0 0 12px; }
        dialog.dialog .form { border: none; padding: 0; margin: 0; }
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
        const saveHandlers = {
          task: () => this._saveTask(),
          member: () => this._saveMember(),
          "own-task": () => this._saveOwnTask(),
          reward: () => this._saveReward(),
          favorite: () => this._saveFavorite(),
        };
        // .catch(() => {}) (v0.16): the alert() feedback for a rejected
        // callWS already happens inside _callWS/_saveXxx - this just keeps a
        // failed save from also logging an "unhandled promise rejection" to
        // the console on top of that, since nothing here awaits the result.
        saveHandlers[form.dataset.form]?.()?.catch(() => {});
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
        else if (action === "delete-task") { if (this._isAdmin()) this._deleteTask(el.dataset.taskId)?.catch(() => {}); }
        else if (action === "complete-task")
          this._hass.callService("family_tasks", "complete_task", { task_id: el.dataset.taskId });
        else if (action === "skip-task")
          this._hass.callService("family_tasks", "skip_task", { task_id: el.dataset.taskId });
        else if (action === "new-own-task") { if (this._isChildUser()) this._openOwnTaskForm(); }
        else if (action === "cancel-own-task-form") this._closeOwnTaskForm();
        else if (action === "new-member") { if (this._isAdmin() && !this._isChildUser()) this._openMemberForm(null); }
        else if (action === "cancel-member-form") this._closeMemberForm();
        else if (action === "edit-member") { if (this._isAdmin() && !this._isChildUser()) this._openMemberForm(el.dataset.memberId); }
        else if (action === "delete-member") { if (this._isAdmin() && !this._isChildUser()) this._deleteMember(el.dataset.memberId)?.catch(() => {}); }
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
        } else if (action === "filter-member") {
          this._taskMemberFilter = el.dataset.memberId || null;
          this._saveUiState();
          this._render();
        } else if (action === "toggle-controls") {
          this._controlsHidden = !this._controlsHidden;
          this._saveUiState();
          this._render();
        } else if (action === "select-reward") {
          this._selectReward(el.dataset.rewardId);
        } else if (action === "cancel-redeem") {
          this._cancelRedeem();
        } else if (action === "confirm-redeem") {
          this._confirmRedeem(el.dataset.rewardId)?.catch(() => {});
        } else if (action === "new-reward") {
          // Defense-in-depth, same reasoning as the edit/delete gating above -
          // the backend enforces this too regardless (see
          // RewardRedemptionStorageCollectionWebsocket in storage.py).
          if (this._isAdmin() && !this._isChildUser()) this._openRewardForm(null);
        } else if (action === "edit-reward") {
          if (this._isAdmin() && !this._isChildUser()) this._openRewardForm(el.dataset.rewardId);
        } else if (action === "cancel-reward-form") {
          this._closeRewardForm();
        } else if (action === "delete-reward") {
          if (this._isAdmin() && !this._isChildUser()) this._deleteReward(el.dataset.rewardId)?.catch(() => {});
        } else if (action === "fulfill-redemption") {
          if (this._isAdmin() && !this._isChildUser()) this._fulfillRedemption(el.dataset.redemptionId)?.catch(() => {});
        } else if (action === "toggle-hide-fulfilled") {
          this._hideFulfilled = !this._hideFulfilled;
          this._saveUiState();
          this._render();
        } else if (action === "toggle-hide-leaderboard") {
          this._hideLeaderboard = !this._hideLeaderboard;
          this._saveUiState();
          this._render();
        } else if (action === "toggle-hide-rewards") {
          this._hideRewards = !this._hideRewards;
          this._saveUiState();
          this._render();
        } else if (action === "new-favorite") {
          // Defense-in-depth, same reasoning as new-reward/new-member above -
          // the backend enforces this too regardless (see
          // FavoriteStorageCollectionWebsocket in storage.py).
          if (this._isAdmin() && !this._isChildUser()) this._openFavoriteForm(null);
        } else if (action === "edit-favorite") {
          if (this._isAdmin() && !this._isChildUser()) this._openFavoriteForm(el.dataset.favoriteId);
        } else if (action === "cancel-favorite-form") {
          this._closeFavoriteForm();
        } else if (action === "delete-favorite") {
          if (this._isAdmin() && !this._isChildUser()) this._deleteFavorite(el.dataset.favoriteId)?.catch(() => {});
        } else if (action === "instantiate-favorite") {
          if (this._isAdmin() && !this._isChildUser()) this._instantiateFavorite(el.dataset.favoriteId)?.catch(() => {});
        } else if (action === "open-favorites") {
          // Defense-in-depth, same reasoning as new-favorite/new-member above.
          if (this._isAdmin() && !this._isChildUser()) this._openFavoritesDialog();
        } else if (action === "close-favorites") {
          this._closeFavoritesDialog();
        } else if (action === "open-member-completions") {
          this._openMemberCompletions(el.dataset.memberId)?.catch(() => {});
        } else if (action === "close-member-completions") {
          this._closeMemberCompletions();
        } else if (action === "add-subtask") {
          // Works for both the admin task form and a child's own-task form -
          // both can carry a checklist (v0.8) - see _formSpec.
          const form = el.closest("[data-form]");
          const spec = form && this._formSpec(form.dataset.form);
          if (spec) {
            spec.target.subtasks.push({ id: newSubtaskId(), name: "" });
            form.outerHTML = spec.render();
          }
        } else if (action === "remove-subtask") {
          const form = el.closest("[data-form]");
          const spec = form && this._formSpec(form.dataset.form);
          if (spec) {
            spec.target.subtasks.splice(Number(el.dataset.subtaskIndex), 1);
            form.outerHTML = spec.render();
          }
        }
      });

      // v0.22: Enter/Leertaste lösen einen [role="button"] (aktuell nur die
      // klickbaren Bestenlisten-Zeilen, siehe _renderRankingSection) wie
      // einen Klick aus - native <button>-Elemente brauchen das nicht, ein
      // per Tastatur fokussiertes <div role="button"> aber schon, da der
      // Browser dafür keinen "click" von selbst auslöst.
      this.shadowRoot.addEventListener("keydown", (ev) => {
        if (ev.key !== "Enter" && ev.key !== " ") return;
        const el = ev.target.closest('[role="button"][data-action]');
        if (!el) return;
        ev.preventDefault();
        el.click();
      });

      this.shadowRoot.addEventListener("change", (ev) => {
        // Battery-override controls live in the "Batterien" section, not in
        // one of the [data-form] forms - each field change saves directly
        // via the family_tasks/battery_override/* websocket API instead of
        // going through the form-draft/save flow the other forms use.
        const batteryEl = ev.target.closest("[data-battery-entity]");
        if (batteryEl) {
          this._saveBatteryOverrideField(batteryEl)?.catch(() => {});
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

        // Points-to-invest field for an investable Handyzeit redemption
        // (v0.14) - not part of the reward-catalog form itself, just the
        // pending-redeem confirm row, so it's handled separately from the
        // data-reward-field inputs below.
        const investEl = ev.target.closest('[data-action="invest-points"]');
        if (investEl) {
          this._pendingInvestPoints = Math.max(1, Number(investEl.value) || 1);
          this._render();
          return;
        }

        // The reward-catalog form uses its own data-reward-field mechanism
        // (not the generic data-field/_formSpec one below) so that switching
        // "Belohnungstyp" can redraw just the <form> in place, same reasoning
        // as the other forms' data-field handling.
        const rewardFieldEl = ev.target.closest("[data-reward-field]");
        if (rewardFieldEl) {
          this._rewardForm[rewardFieldEl.dataset.rewardField] =
            rewardFieldEl.type === "checkbox" ? rewardFieldEl.checked : rewardFieldEl.value;
          const rewardForm = ev.target.closest('[data-form="reward"]');
          if (rewardForm) rewardForm.outerHTML = this._renderRewardForm();
          return;
        }

        const el = ev.target.closest("[data-field]");
        if (!el) return;
        const form = ev.target.closest("[data-form]");
        if (!form) return;
        const spec = this._formSpec(form.dataset.form);
        if (!spec) return;
        this._applyFieldChange(spec.target, el);
        // Re-render only the form itself in place so unrelated typing isn't lost,
        // but recurrence-type / rotation changes need the sub-fields to redraw.
        form.outerHTML = spec.render();
      });
    }

    // Maps a [data-form] name to its draft object and its render function -
    // shared by the submit/change handlers and the checklist add/remove-
    // subtask actions above, so every form (including the two that can carry
    // a checklist, "task" and "own-task") is wired up in one place.
    _formSpec(name) {
      const specs = {
        task: { target: this._taskForm, render: () => this._renderTaskForm() },
        member: { target: this._memberForm, render: () => this._renderMemberForm() },
        "own-task": { target: this._ownTaskForm, render: () => this._renderOwnTaskForm() },
        favorite: { target: this._favoriteForm, render: () => this._renderFavoriteForm() },
      };
      return specs[name];
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
        // Generic parent lookup (not hardcoded to target.rotation) so this
        // works both for the task form's "rotation.member_ids" and the
        // favorite form's flat "member_ids" (see _renderFavoriteForm).
        let parent = target;
        for (let i = 0; i < path.length - 1; i++) parent = parent[path[i]];
        const list = parent.member_ids;
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
    description: "Aufgaben, Rotation, Bestenliste und Belohnungen für die Familie verwalten.",
  });
})();
