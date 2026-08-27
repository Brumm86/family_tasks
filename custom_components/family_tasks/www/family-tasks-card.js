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
 *   hide_excluded_batteries: false - initial value for the "Ausgeschlossene
 *                               anzeigen"/"Ausgeschlossene ausblenden" toggle
 *                               *within* the "Batterien" section (v0.35,
 *                               same first-run-only rule as above): whether
 *                               a battery entity already marked "Ausschließen"
 *                               is filtered out of that list. Defaults to
 *                               `true` (hidden) on a fresh device regardless
 *                               of this key's own default (`false` here just
 *                               means "don't force-show" - see setConfig) -
 *                               set to `false` explicitly to start with
 *                               excluded batteries shown instead. Purely a
 *                               display filter, same as hide_battery_section
 *                               itself - never affects which batteries are
 *                               actually monitored.
 *   hide_progress_section: false - initial value for the "Wochenfortschritt"
 *                               progress-bar visibility toggle (v0.29,
 *                               replaces the old "Bestenliste" ranking - see
 *                               _renderProgressSection). Falls back to the
 *                               older hide_leaderboard_section key if this
 *                               one isn't set, so an existing dashboard that
 *                               already hid the Bestenliste keeps behaving
 *                               the same way without editing its config.
 *                               Unlike hide_members_list/hide_battery_section
 *                               this toggle button itself only renders for a
 *                               parent (Eltern-only, per household request) -
 *                               a "Kind"-linked user always just sees
 *                               whatever the parent last chose on that
 *                               device, with nothing to change it back
 *                               themselves. Defaults to `false` (shown)
 *                               rather than joining the v0.11 default-true
 *                               flip below, since a child typically needs to
 *                               see their own progress right away.
 *   hide_rewards_section: false - same as hide_progress_section, for the
 *                               "Belohnungen" section (catalog + redemption
 *                               history) directly below it - still toggle-able
 *                               by every user, including a "Kind"-linked one.
 *   hide_completed_tasks: false - initial value for the "Erledigte
 *                               ausblenden" task-list toggle (v0.28, same
 *                               first-run-only rule as above). Like
 *                               hide_rewards_section this is *not* Eltern-
 *                               only - the toggle button renders for every
 *                               user, including a "Kind"-linked one - but
 *                               unlike that one it defaults to `true`
 *                               (hidden) rather than `false`, since an
 *                               already-done occurrence is rarely useful
 *                               clutter in the day-to-day list for parent or
 *                               child alike. Set this to `false` explicitly
 *                               to start with completed tasks shown.
 *
 * v0.11 default flip: hide_members_list, hide_battery_section and
 * only_own_tasks default to *true* (compact, own-tasks-only) the very first
 * time the card runs on a device and no persisted localStorage state exists
 * yet, instead of *false* (everything shown) - set any of them to `false`
 * explicitly in the card config to keep the pre-v0.11 "show everything"
 * first-run behavior. hide_progress_section/hide_rewards_section (v0.21/
 * v0.29) are deliberately *not* part of this group - see above. (hide_favorites_
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
 * "Erledigte ausblenden" (v0.28) is a deliberate exception to this rule, same
 * as the "Bestenliste"/"Belohnungen" show/hide buttons below - a child needs
 * to declutter their own already-done tasks just as much as a parent does,
 * so that button renders and works identically for every user regardless of
 * role, and (unlike hide_not_due_tasks) starts hidden by default - see
 * hide_completed_tasks above and _hideCompleted in the constructor.
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
 * Persisted UI state: the "nicht fällige ausblenden" / "Erledigte
 * ausblenden" / "Familienmitglieder ausblenden" / "Nur eigene Aufgaben" /
 * "Batterien ausblenden" toggles and the compact-mode button (top-right of
 * the card, hides the toggle buttons to keep the card small during normal
 * use) are saved to localStorage per browser/device, keyed by the card's
 * title, so they survive dashboard reloads. This is per-device state, not
 * synced between devices - each phone/tablet remembers its own preference.
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
 * is dismissed the same way (complete/skip) - or, if the household turned on
 * "Auto-complete battery alert tasks once the battery recovers" in the
 * integration's Options (v0.35, off by default), it resolves itself the
 * moment that same battery recovers (back above threshold, or a
 * binary_sensor no longer reporting low), with no one having to press
 * "Erledigt"/"Überspringen" by hand. The admin-only "Batterien" section
 * further down is configuration-only: it lets individual batteries be
 * excluded from monitoring entirely or given their own warning threshold
 * (overriding the household-wide default set in the integration's Options),
 * through the family_tasks/battery_override/* websocket API, and can be
 * collapsed via hide_battery_section above since it's rarely touched day to
 * day. Within that section, batteries already marked "Ausschließen" are
 * themselves filtered out of the list by default (v0.35) - an "Ausgeschlossene
 * anzeigen"/"Ausgeschlossene ausblenden" toggle un-hides them again, see
 * hide_excluded_batteries above. (The older recurrence type "battery" - one
 * aggregate task an admin assigns and that becomes due/idle by itself - still
 * works for any household that already set one up, but is no longer offered
 * when creating a new task; the new auto-complete-on-recovery option above
 * does not apply to it, since it already falls back to idle by itself once
 * every monitored battery recovers.)
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
 * collapsible (hide_leaderboard_section/hide_rewards_section above) - unlike
 * "Familienmitglieder"/"Batterien" the "Ausblenden"/"... anzeigen" buttons
 * render for *every* user, not just parents, since a child needs to be able
 * to get the reward catalog back out of the way (or bring it back) just as
 * much as a parent does. Both default to shown on a fresh device, not the
 * v0.11 compact default the admin-only sections use.
 *
 * v0.29: "Bestenliste" itself is replaced by a per-child weekly progress bar
 * (_renderProgressSection, hide_progress_section above, see that method's
 * comment for details) - "Belohnungen" (_renderRewardsSection) is
 * unaffected and still toggle-able by every user as described above. Unlike
 * "Belohnungen", hiding the progress bars is Eltern-only per household
 * request - a "Kind"-linked user gets no toggle for it at all.
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
 * regardless - see _effectiveTaskMemberFilterId). v0.23: a manual chip pick
 * is now persisted per logged-in HA user (taskMemberFilterByUser in
 * localStorage), not flatly per device like the other toggles - on a shared
 * device where more than one parent logs in, each of them keeps landing on
 * their own default/pick instead of inheriting whatever the last person who
 * used the card happened to have selected.
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
 * - Each "Wochenfortschritt" progress bar shows two "Meilensteinbonus"
 *   threshold markers (v0.30, replaces the old weekly-winner bonus) whenever
 *   the household has that feature turned on - see _milestoneBonus, which
 *   reads the thresholds/bonus points off milestone_bonus_enabled/...
 *   attributes now carried by every member's points sensor (FamilyTasksData
 *   in coordinator.py). A short legend line above the bars spells the same
 *   thresholds out in text for accessibility/narrow screens.
 * - "Aufgabenpool" (v0.30): a task with no fixed assignee(s) and no rotation
 *   (empty rotation.member_ids, see is_pool_task in coordinator.py) gets its
 *   own always-visible section - _renderTaskPoolSection/_isPoolTask - below
 *   the normal "Aufgaben" list (v0.32 - previously above it), unaffected by
 *   hideNotDue/hideCompleted/the member-filter chips and showing occurrences
 *   even before their weekday arrives (see _pool_period_date in
 *   coordinator.py). Any active child may reserve one via the existing
 *   "Annehmen" claim mechanism, same canClaim/canAct logic and row markup
 *   (_renderTaskRow) as a normal task. v0.32: once claimed, an occurrence
 *   moves out of this section into the normal list instead - see
 *   _isClaimedPoolTask, and claimed_by_member_id/assigned_member_id(s) in
 *   coordinator.py, which now firmly attributes a claimed pool occurrence to
 *   its claimant.
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

  // v0.29: curated fallback icon list for every "Icon (optional)" field
  // (Aufgabe/Favorit/Mitglied/Belohnung, see _hydrateIconPickers below) -
  // most people don't have Material Design Icon names memorized, so typing
  // "mdi:..." from scratch was the actual complaint this addresses. The
  // primary path is a real <ha-icon-picker> (full searchable MDI catalog),
  // used whenever Home Assistant's frontend has registered it; this list
  // only backs the <input list="..."> fallback for a setup where that
  // custom element isn't available (same "detect + degrade gracefully"
  // pattern as _hydrateDateTimeInputs/_replaceWithPlainDateTimeInput) - a
  // datalist still lets someone type any other "mdi:whatever" by hand, this
  // is purely a set of one-click suggestions relevant to household chores/
  // rewards/family members, not an exhaustive icon set.
  const COMMON_ICON_OPTIONS = [
    "mdi:broom", "mdi:trash-can", "mdi:dishwasher", "mdi:washing-machine",
    "mdi:tshirt-crew", "mdi:bed", "mdi:toothbrush", "mdi:shower",
    "mdi:silverware-fork-knife", "mdi:pot-steam", "mdi:fridge-outline",
    "mdi:broom-outline", "mdi:vacuum", "mdi:spray-bottle", "mdi:paw",
    "mdi:dog-side", "mdi:cat", "mdi:flower", "mdi:tree-outline",
    "mdi:car", "mdi:car-wash", "mdi:bike", "mdi:trash-can-outline",
    "mdi:recycle", "mdi:book-open-variant", "mdi:school", "mdi:pencil",
    "mdi:home", "mdi:home-outline", "mdi:door", "mdi:window-closed-variant",
    "mdi:lightbulb-on-outline", "mdi:battery-charging", "mdi:account",
    "mdi:account-child", "mdi:account-child-outline", "mdi:human-male-child",
    "mdi:human-female-girl", "mdi:account-multiple", "mdi:star",
    "mdi:star-outline", "mdi:trophy", "mdi:gift", "mdi:cash",
    "mdi:cellphone", "mdi:television", "mdi:gamepad-variant",
    "mdi:movie-open", "mdi:ice-cream", "mdi:pizza", "mdi:food-apple",
    "mdi:cake-variant", "mdi:swim", "mdi:soccer", "mdi:basketball",
    "mdi:music", "mdi:paintbrush", "mdi:checkbox-marked-circle-outline",
    "mdi:alert", "mdi:calendar-check",
  ];
  const ICON_DATALIST_ID = "family-tasks-icon-suggestions";
  // Rendered once per shadow-DOM rebuild (see the outer template) regardless
  // of whether any fallback icon input is actually on screen right now -
  // cheap, and every fallback input just references it by `list=`.
  const ICON_DATALIST_HTML = `<datalist id="${ICON_DATALIST_ID}">${COMMON_ICON_OPTIONS.map(
    (icon) => `<option value="${icon}"></option>`
  ).join("")}</datalist>`;

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

  // v0.36: gleiches Prinzip wie pointsLabel oben, für die neue
  // Belohnungs-Shop-Währung "Münzen" (CoinLedgerStore in storage.py) - jede
  // Stelle, an der ein Belohnungspreis, ein Münzen-Guthaben oder ein
  // Meilenstein-/Streak-Bonus als das Wort "Münzen" dargestellt wird, geht
  // hierüber.
  function coinsLabel(value) {
    const n = Number(value) || 0;
    return `${esc(n)} ${n === 1 ? "Münze" : "Münzen"}`;
  }

  // Kleiner "· +30 Min. Bildschirmzeit"-Zusatz, gemeinsam genutzt vom
  // Belohnungs-Katalog und dem Einlöse-Verlauf - undefined/null/"" bedeuten
  // alle "nicht gesetzt".
  function screenTimeSuffix(minutes) {
    return minutes ? ` · +${esc(minutes)} Min. Bildschirmzeit` : "";
  }

  // v0.27: "18:30" for a timestamp falling on today, "Mo 18:30" otherwise
  // (e.g. a Karenzzeit that pushes a late due_time past midnight) - shared by
  // the per-task "Zu erledigen bis"/"Reserviert bis" labels below (see
  // deadline_at/claim_expires_at task attributes, both ISO datetimes from
  // coordinator.py). Returns "" for anything that doesn't parse so callers
  // can use it directly in a template without an extra guard.
  function formatDeadline(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "";
    const sameDay = d.toDateString() === new Date().toDateString();
    return d.toLocaleString(
      "de-DE",
      sameDay
        ? { hour: "2-digit", minute: "2-digit" }
        : { weekday: "short", hour: "2-digit", minute: "2-digit" }
    );
  }

  // v0.24: inline SVG path data for the small, fixed set of MDI icons this
  // file itself chooses (row-action buttons, the Bestenliste disclosure
  // arrow) - as opposed to an *arbitrary* icon a user types into a task/
  // member/reward's own "icon"-Feld (task.icon/member.icon/r.icon/f.icon),
  // which still goes through <ha-icon> below since there's no fixed set to
  // pre-bake a path for. See ICON_SVG_PATHS' first user (svgIcon) for why.
  const ICON_SVG_PATHS = {
    delete: "M19,4H15.5L14.5,3H9.5L8.5,4H5V6H19M6,19A2,2 0 0,0 8,21H16A2,2 0 0,0 18,19V7H6V19Z",
    pencil:
      "M20.71,7.04C21.1,6.65 21.1,6 20.71,5.63L18.37,3.29C18,2.9 17.35,2.9 16.96,3.29L15.12,5.12L18.87,8.87M3,17.25V21H6.75L17.81,9.93L14.06,6.18L3,17.25Z",
    close: "M19,6.41L17.59,5L12,10.59L6.41,5L5,6.41L10.59,12L5,17.59L6.41,19L12,13.41L17.59,19L19,17.59L13.41,12L19,6.41Z",
    check: "M21,7L9,19L3.5,13.5L4.91,12.09L9,16.17L19.59,5.59L21,7Z",
    "check-bold": "M9,20.42L2.79,14.21L5.62,11.38L9,14.77L18.88,4.88L21.71,7.71L9,20.42Z",
    "playlist-plus": "M3 16H10V14H3M18 14V10H16V14H12V16H16V20H18V16H22V14M14 6H3V8H14M14 10H3V12H14V10Z",
    "chevron-right": "M8.59,16.58L13.17,12L8.59,7.41L10,6L16,12L10,18L8.59,16.58Z",
    "star-plus-outline":
      "M5.8 21L7.4 14L2 9.2L9.2 8.6L12 2L14.8 8.6L22 9.2L18.8 12H18C17.3 12 16.6 12.1 15.9 12.4L18.1 10.5L13.7 10.1L12 6.1L10.3 10.1L5.9 10.5L9.2 13.4L8.2 17.7L12 15.4L12.5 15.7C12.3 16.2 12.1 16.8 12.1 17.3L5.8 21M17 14V17H14V19H17V22H19V19H22V17H19V14H17Z",
  };

  // Renders one of the icons above as a plain inline <svg>, not <ha-icon>.
  //
  // Up to v0.23 every icon-action-btn used <ha-icon icon="mdi:...">, which
  // resolves its actual SVG path asynchronously (a separately-loaded icon
  // metadata lookup - see Home Assistant's ha-icon component) rather than
  // painting synchronously. v0.23 tried to fix the resulting symptom (the
  // small round "Löschen" button briefly/indefinitely showing as a bare red
  // circle with no bin glyph, only appearing once the pointer happened to
  // hover it) by giving the <ha-icon> host a fixed width/height so at least
  // the button's layout didn't jump - that kept the button's *size* stable
  // but never addressed why the glyph itself wasn't painting, and the
  // problem persisted. Since this card rebuilds its entire shadow-DOM
  // innerHTML on every re-render (see the file header), every row's
  // <ha-icon> was torn down and recreated from scratch each time, repeatedly
  // re-triggering that async lookup - for a small, fixed set of icons this
  // file itself controls (never a user-typed icon string), there is no
  // reason to depend on that lookup at all. Embedding the path data directly
  // (see ICON_SVG_PATHS above, taken from the Material Design Icons "delete"/
  // "pencil"/etc. glyphs) paints synchronously with the rest of the
  // innerHTML, on the very first render, every time - no async gap for the
  // button to visibly sit empty (or red-and-empty for the danger-styled
  // delete button) until something incidentally repaints it.
  function svgIcon(name, size = 18) {
    const path = ICON_SVG_PATHS[name];
    if (!path) return `<ha-icon icon="mdi:${name}"></ha-icon>`;
    return `<svg viewBox="0 0 24 24" width="${size}" height="${size}" focusable="false" aria-hidden="true"><path d="${path}" fill="currentColor"></path></svg>`;
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
  // `icon` is still passed as "mdi:delete" etc. (unchanged call sites) - the
  // "mdi:" prefix is stripped to look the glyph up in ICON_SVG_PATHS (see
  // svgIcon above); an icon not in that fixed set still falls back to
  // <ha-icon>, though every current caller is covered.
  function iconActionButton(action, icon, title, { dataset = "", extraClass = "", disabled = false } = {}) {
    const name = icon.startsWith("mdi:") ? icon.slice(4) : icon;
    return `<button type="button" class="icon-action-btn ${extraClass}" data-action="${action}" ${dataset} title="${esc(title)}" aria-label="${esc(title)}" ${disabled ? "disabled" : ""}>${svgIcon(name)}</button>`;
  }

  function emptyTriggerForm() {
    // "direction"/"value" drive the numeric_state UI: a single threshold to
    // cross (above OR below), not a from-x-to-y range - see storage.py's
    // _require_single_threshold. Mapped to/from the backend's above/below
    // fields in taskToForm() / _saveTask().
    return {
      kind: "state",
      entity_id: "",
      to_state: "on",
      direction: "above",
      value: "",
      // v0.34: see the matching field on TASK_TRIGGER_STATE_SCHEMA/
      // TASK_TRIGGER_NUMERIC_STATE_SCHEMA in storage.py.
      auto_complete_on_normalize: false,
    };
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
      // v0.31: paired with the "Fällig um" <ha-time-input>'s hour/minute
      // <select> fallback (see _renderFallbackTimeInput) - holds whichever
      // half (hour/minute) the user has picked so far even while due_time
      // itself is still "" (incomplete). Without this, picking just the
      // hour got wiped out on the very next re-render because due_time was
      // still empty - see _applyFieldChange's due_time branch for the fix.
      _dueTimeHour: "",
      _dueTimeMinute: "",
      overdue_after_minutes: 60,
      requires_confirmation: true,
      kind: "standard",
      subtasks: [],
      completion_button_entity_id: "",
      // v0.32: see CONF_TASK_VACATION_BEHAVIOR in const.py - checked means
      // "pause" (vacation_behavior: "pause"), unchecked means the default
      // "show". Only takes effect while the household-wide Urlaubsmodus
      // switch is on.
      vacation_paused: false,
      // v0.29: "Einmalig" is the default for a brand-new task now, not
      // "Täglich" - most ad-hoc tasks a parent adds on the fly (the common
      // case "+ Aufgabe hinzufügen" is used for) are one-off, and picking
      // "Täglich" by accident silently created a recurring chore nobody
      // meant to set up. Editing an existing task is unaffected - taskToForm
      // above always carries over that task's own stored recurrence.type.
      recurrence: {
        type: "once",
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
      // v0.31: see the matching comment in emptyTaskForm above.
      _dueTimeHour: "",
      _dueTimeMinute: "",
      overdue_after_minutes: 60,
      requires_confirmation: true,
      kind: "standard",
      subtasks: [],
      // v0.29: "Einmalig" default, same reasoning as emptyTaskForm above.
      recurrence: { type: "once", interval: 1, weekdays: [0], anchor_date: "" },
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
      // v0.37: see CONF_MEMBER_PAUSED in const.py - a brand-new member never
      // starts out paused.
      paused: false,
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
      // v0.31: see the matching comment in emptyTaskForm above. Starts empty
      // even when editing a task that already has a due_time - the fallback
      // reads the complete hour/minute straight out of due_time itself in
      // that case (see _renderFallbackTimeInput), these two only matter once
      // the user starts changing the selection.
      _dueTimeHour: "",
      _dueTimeMinute: "",
      overdue_after_minutes: task.overdue_after_minutes ?? 60,
      requires_confirmation: task.requires_confirmation ?? true,
      kind: task.kind ?? "standard",
      subtasks: (task.subtasks ?? []).map((s) => ({ ...s })),
      completion_button_entity_id: task.completion_button_entity_id ?? "",
      // v0.32: see the matching comment in emptyTaskForm above.
      vacation_paused: task.vacation_behavior === "pause",
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
            // v0.34: see the matching field on TASK_TRIGGER_STATE_SCHEMA/
            // TASK_TRIGGER_NUMERIC_STATE_SCHEMA in storage.py.
            auto_complete_on_normalize: t?.auto_complete_on_normalize ?? false,
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
      // v0.37: see CONF_MEMBER_PAUSED in const.py.
      paused: member.paused === true,
      notify_service: member.notify_service ?? "",
    };
  }

  function emptyRewardForm() {
    return {
      name: "",
      icon: "",
      coin_cost: 0,
      reward_type: "custom",
      screen_time_minutes: "",
      auto_fulfill: false,
      screen_time_investable: false,
      note_enabled: false,
      note_label: "",
    };
  }

  function rewardToForm(reward) {
    return {
      name: reward?.name ?? "",
      icon: reward?.icon ?? "",
      coin_cost: reward?.coin_cost ?? 0,
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
      // v0.24 - siehe CONF_REWARD_NOTE_ENABLED/CONF_REWARD_NOTE_LABEL in
      // const.py: verlangt beim Einlösen einen kurzen Freitext (z. B. das
      // gewünschte Mittagessen) statt nur "Bestätigen".
      note_enabled: reward?.note_enabled ?? false,
      note_label: reward?.note_label ?? "",
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
      // v0.36: which recurrence-type groups within the "nicht fällig"
      // (not-due) part of the task list are currently expanded - see
      // _renderNotDueGroups. Array of recurrence "type" strings (task.recurrence.type,
      // same keys as RECURRENCE_LABELS); a group not listed here starts
      // collapsed. Starts as an empty array (every group collapsed) on a
      // genuinely fresh device, same "start compact" reasoning as
      // _hideMembers/_hideBattery - only actually seeded once, in
      // setConfig, same pattern as every other persisted toggle here.
      this._openRecurrenceGroups = undefined;
      // v0.28: "Erledigte ausblenden" for the task list itself - separate
      // from _hideNotDue (which bundles "done" in with "idle"/waiting-for-
      // sensor tasks and is admin-only, see showVisibilityControls). This
      // toggle is available to *every* user including a "Kind"-account
      // (same reasoning as _hideRewards below - a child wants their own
      // list decluttered of what they've already finished just as much as a
      // parent does) and, unlike hideNotDue, defaults to *hidden* on a fresh
      // device - see setConfig.
      this._hideCompleted = undefined;
      this._hideMembers = undefined;
      this._hideBattery = undefined;
      // v0.35: independent of _hideBattery (which collapses the whole
      // "Batterien" section) - filters *within* the section's own list,
      // hiding battery entities already marked "Ausschließen" so the list
      // stays focused on batteries that are actually still monitored.
      // Defaults to hidden on a fresh device (see setConfig), same
      // fallback-to-compact reasoning as _hideMembers/_hideBattery
      // themselves - a household that's already excluded a handful of
      // batteries (dummy/unused sensors, etc.) doesn't want them cluttering
      // this list by default, but they're never fully inaccessible: the
      // toggle button right there un-hides them again.
      this._hideExcludedBatteries = undefined;
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
      // Wie viele Münzen der aktuelle Nutzer in das "Münzen investieren"-Feld
      // für die anstehende investierbare (Handyzeit-)Einlösung eingetragen
      // hat - siehe CONF_REWARD_SCREEN_TIME_INVESTABLE in const.py.
      this._pendingInvestCoins = 1;
      // Freitext für die anstehende Einlösung einer CONF_REWARD_NOTE_ENABLED-
      // Belohnung (v0.24), z. B. das gewünschte Mittagessen - siehe
      // _selectReward/_confirmRedeem.
      this._pendingRedeemNote = "";
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
      // Wochenfortschritt/Belohnungen: independently collapsible. Anders als
      // beim v0.21-"Bestenliste"-Umschalter, den dieser Fortschrittsbalken
      // ersetzt (siehe _renderProgressSection), ist das Ausblenden hier
      // Eltern-only - _hideRewards bleibt weiterhin für *jeden* Nutzer
      // bedienbar, "Kind"-Konto eingeschlossen (siehe _renderRewardsSection),
      // da der Belohnungs-Katalog selbst von Kindern genutzt wird.
      this._hideProgress = undefined;
      this._hideRewards = undefined;
      // v0.22: "welche Aufgaben hat dieses Mitglied diese Woche erledigt"-
      // Dialog, geöffnet per Klick auf eine Fortschritts-Zeile (siehe
      // _openMemberCompletions/_renderProgressSection). Nicht persistiert -
      // startet wie jedes andere Dialog-Flag immer geschlossen.
      this._memberCompletionsDialogOpen = false;
      this._memberCompletionsMemberId = null;
      this._memberCompletions = [];
      this._memberCompletionsLoading = false;
      // v0.24: "Punkte vergeben" - welches Familienmitglied gerade seine
      // Bestätigungs-Zeile in der Mitgliederliste zeigt (immer nur eine,
      // gleiches Muster wie _pendingRedeemId bei Belohnungen), plus die
      // aktuell eingetragene Punktzahl (kann negativ sein, zum Abziehen) und
      // der optionale Grund-Freitext. Siehe WS_API_POINTS_AWARD in const.py.
      this._pendingAwardPointsMemberId = null;
      this._pendingAwardPoints = 1;
      this._pendingAwardNote = "";
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
        // v0.28: "Erledigte ausblenden" defaults to *true* (hidden) on a
        // genuinely fresh device, unlike hideNotDue just above - a
        // household's task list otherwise accumulates every already-done
        // occurrence right alongside what's actually still open, for both
        // parents and children (see the toggle button placement in
        // _render(), deliberately outside the showVisibilityControls/
        // isChildUser gate that hideNotDue sits behind). Explicitly set
        // `hide_completed_tasks: false` in the card config to start shown
        // instead.
        this._hideCompleted = saved?.hideCompleted ?? this._config.hide_completed_tasks !== false;
        // v0.11: default to hidden/own-tasks-only on a genuinely fresh device
        // (no saved state) unless the config explicitly opts back into the
        // old "show everything" default with `false` - see the file header
        // comment for why. Previously these three fell back to `false`
        // (shown) the same way hide_not_due_tasks still does.
        this._hideMembers = saved?.hideMembers ?? this._config.hide_members_list !== false;
        this._hideBattery = saved?.hideBattery ?? this._config.hide_battery_section !== false;
        // v0.35: defaults to hidden (excluded batteries filtered out of the
        // "Batterien" list) on a genuinely fresh device, same as
        // hideMembers/hideBattery just above - explicit
        // `hide_excluded_batteries: false` in the card config opts back
        // into showing everything from the start.
        this._hideExcludedBatteries =
          saved?.hideExcludedBatteries ?? this._config.hide_excluded_batteries !== false;
        this._controlsHidden = saved?.controlsHidden ?? false;
        // v0.16: replaces the old plain "Nur eigene Aufgaben"/"Alle Aufgaben
        // anzeigen" toggle button with per-member filter chips (see
        // _renderMemberFilterChips). v0.23: unlike the other toggles here,
        // _taskMemberFilter is deliberately *not* seeded from storage yet at
        // this point - setConfig runs before `hass` (and therefore the
        // logged-in user) is known, but the whole point of this filter is to
        // default to *that* user's own tasks. It stays `undefined` and is
        // resolved lazily, per logged-in member, the first time
        // _effectiveTaskMemberFilterId() runs - see that method and
        // _saveUiState for how a manual chip pick is now remembered
        // per-member instead of flatly per device (previously any one
        // member/parent picking "Alle" or someone else's chip on a shared
        // device silently changed everyone else's default too).
        // Erledigte Einlösungen sind standardmäßig ausgeblendet, wie schon in
        // der ehemals eigenständigen Bestenlisten-Karte.
        this._hideFulfilled = saved?.hideFulfilled ?? true;
        // v0.21/v0.29: Wochenfortschritt/Belohnungen bleiben - anders als
        // Mitglieder/Batterien/die alte Favoriten-Sektion - standardmäßig
        // sichtbar (kein v0.11-Kompakt-Default), da auch ein "Kind"-Konto
        // sie normalerweise sofort braucht (eigenen Fortschritt sehen,
        // Belohnungen einlösen). Optional per Config-Option von Anfang an
        // ausgeblendet startbar; `hideLeaderboard`/hide_leaderboard_section
        // sind die alten, vor v0.29 verwendeten Namen - werden hier als
        // Fallback weitergelesen, damit ein bereits ausgeblendeter Zustand
        // beim Umstieg auf die Fortschrittsbalken erhalten bleibt.
        this._hideProgress =
          saved?.hideProgress ??
          saved?.hideLeaderboard ??
          !!(this._config.hide_progress_section ?? this._config.hide_leaderboard_section);
        this._hideRewards = saved?.hideRewards ?? !!this._config.hide_rewards_section;
        this._openRecurrenceGroups = saved?.openRecurrenceGroups ?? [];
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
        // v0.23: taskMemberFilter used to be a single flat value shared by
        // every user of a device - a parent picking "Alle" (or a sibling's
        // chip) silently changed the default for the next person to open the
        // same card too, including a different family member who should
        // still land on *their own* tasks. It's now stored per logged-in HA
        // user id (taskMemberFilterByUser) instead, merged on top of
        // whatever's already there so saving some *other* toggle here (e.g.
        // hideMembers) never clobbers a different user's remembered filter
        // pick. this._taskMemberFilter itself still only ever holds the
        // *current* user's in-memory value - see
        // _effectiveTaskMemberFilterId, which lazily seeds it from this same
        // map the first time it runs for a given login.
        const existing = this._loadUiState() || {};
        const taskMemberFilterByUser = { ...(existing.taskMemberFilterByUser || {}) };
        const userId = this._hass?.user?.id;
        if (userId && this._taskMemberFilter !== undefined) {
          taskMemberFilterByUser[userId] = this._taskMemberFilter;
        }
        window.localStorage.setItem(
          this._storageKey(),
          JSON.stringify({
            hideNotDue: this._hideNotDue,
            hideCompleted: this._hideCompleted,
            hideMembers: this._hideMembers,
            hideBattery: this._hideBattery,
            hideExcludedBatteries: this._hideExcludedBatteries,
            controlsHidden: this._controlsHidden,
            taskMemberFilterByUser,
            hideFulfilled: this._hideFulfilled,
            hideProgress: this._hideProgress,
            hideRewards: this._hideRewards,
            openRecurrenceGroups: this._openRecurrenceGroups,
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

    // Aktuelles Münzen-Guthaben (v0.36, ersetzt das alte punktebasierte
    // "einlösbare Guthaben") - siehe MemberSummaryData.coins_available in
    // coordinator.py. Wird unabhängig von der Woche/Monat-Ansicht immer
    // angezeigt, da es die tatsächliche Währung des Belohnungs-Katalogs
    // unten ist, keine periodenbezogene Rangliste-Kennzahl. Liest das
    // "coins_available"-Attribut, das (wie schon die übrigen
    // Options-Werte) auf dem Punkte-Sensor mitreitet - siehe
    // FamilyTasksMemberPointsSensor in sensor.py; es gibt zusätzlich einen
    // eigenen Münzen-Sensor pro Mitglied, dieser hier braucht ihn aber
    // nicht extra nachzuschlagen.
    _coinsAvailableFor(memberId) {
      return Number(this._pointsSensorForMember(memberId)?.attributes?.coins_available ?? 0);
    }

    // v0.36: household-wide "Meilensteinbonus" coin amounts (see
    // CONF_MILESTONE_150_BONUS_COINS/CONF_MILESTONE_200_BONUS_COINS in
    // const.py) - rides along as an attribute on every member's points
    // sensor (identical on all of them, see FamilyTasksMemberPointsSensor
    // in sensor.py), so any one of them will do; "points_week" is a
    // unique-enough discriminator to find a points sensor specifically (the
    // open-tasks/coins sensors also carry a bare "member_id" attribute but
    // not this one). Replaces the pre-v0.36 configurable-threshold,
    // points-based version entirely - the two checkpoints are now fixed at
    // 150%/200% of the weekly goal.
    _milestoneBonus() {
      const empty = { bonus150: 0, bonus200: 0, threshold150Points: 0, threshold200Points: 0 };
      if (!this._hass) return empty;
      const sensor = Object.values(this._hass.states).find(
        (s) => s.entity_id.startsWith("sensor.") && s.attributes.points_week !== undefined
      );
      if (!sensor) return empty;
      return {
        bonus150: Number(sensor.attributes.milestone_150_bonus_coins ?? 0),
        bonus200: Number(sensor.attributes.milestone_200_bonus_coins ?? 0),
        // v0.32: the absolute point value of each checkpoint, computed once
        // server-side (round(), see
        // FamilyTasksData.milestone_150_threshold_points in coordinator.py)
        // - used directly instead of recomputing percent -> points here in
        // JS, since Python's round() (banker's rounding) and JS's
        // Math.round() (always rounds .5 up) can disagree on an exact .5
        // value, which would otherwise show a marker at a slightly
        // different point value than the backend actually awards at.
        threshold150Points: Number(sensor.attributes.milestone_150_threshold_points ?? 0),
        threshold200Points: Number(sensor.attributes.milestone_200_threshold_points ?? 0),
      };
    }

    // v0.36: household-wide "Streak-Bonus" coin amounts, one per fixed tier
    // - same "rides along on every member's points sensor" pattern as
    // _milestoneBonus above. Replaces the pre-v0.36 single
    // configurable-threshold, points-based version entirely.
    _streakBonus() {
      const empty = { requiredWeeks: 2, bonus150: 0, bonus200: 0 };
      if (!this._hass) return empty;
      const sensor = Object.values(this._hass.states).find(
        (s) => s.entity_id.startsWith("sensor.") && s.attributes.points_week !== undefined
      );
      if (!sensor) return empty;
      return {
        requiredWeeks: Number(sensor.attributes.streak_bonus_required_weeks ?? 2),
        bonus150: Number(sensor.attributes.streak_150_bonus_coins ?? 0),
        bonus200: Number(sensor.attributes.streak_200_bonus_coins ?? 0),
      };
    }

    // v0.36: a member's current consecutive-week streak length, one per
    // fixed tier - see MemberSummaryData.streak_weeks_150/streak_weeks_200
    // in coordinator.py.
    _streakWeeksFor(memberId) {
      const sensor = this._pointsSensorForMember(memberId);
      return {
        weeks150: Number(sensor?.attributes?.streak_weeks_150 ?? 0),
        weeks200: Number(sensor?.attributes?.streak_weeks_200 ?? 0),
      };
    }

    // v0.32: whether the household-wide Urlaubsmodus switch is currently on
    // - see FamilyTasksData.vacation_mode_active in coordinator.py, ridden
    // along on every member's points sensor same as the settings above.
    _vacationModeActive() {
      if (!this._hass) return false;
      const sensor = Object.values(this._hass.states).find(
        (s) => s.entity_id.startsWith("sensor.") && s.attributes.points_week !== undefined
      );
      return !!sensor?.attributes?.vacation_mode_active;
    }

    // v0.33: whether this task should currently be hidden for Urlaubsmodus -
    // "Der Urlaubsmodus soll die entsprechenden Aufgaben aber deaktivieren,
    // sodass sie auch nicht unter 'Alle' angezeigt wird." Read straight off
    // the raw task definition (this._tasks) plus _vacationModeActive()
    // rather than relying on the task's status sensor being missing/
    // unavailable - the task list (_renderTaskList/_renderTaskPoolSection)
    // is built from this._tasks, which is populated from the task storage
    // collection independently of whether a status sensor currently exists
    // for it, so a task the coordinator has stopped computing a status for
    // (see CONF_TASK_VACATION_BEHAVIOR in coordinator.py) would otherwise
    // still show up here, just with no sensor data - and every place that
    // reads the (then-missing) status attributes falls back to "pending",
    // which is exactly why a paused task used to reappear as a plain, open,
    // unassigned "offen" task instead of disappearing.
    _isVacationPaused(id) {
      return (
        this._vacationModeActive() && this._tasks[id]?.vacation_behavior === "pause"
      );
    }

    // v0.23: household-wide default rotation strategy (see
    // CONF_DEFAULT_ROTATION_STRATEGY in const.py) - same "rides along on
    // every member's points sensor" pattern as _milestoneBonus above. Used
    // by _openTaskForm to pre-select "Rotationstyp" for a brand new task
    // instead of always hardcoding "Reihum" - previously this option was
    // configurable in the integration's options but never actually read
    // anywhere, so it had no effect at all.
    _defaultRotationStrategy() {
      if (!this._hass) return "round_robin";
      const sensor = Object.values(this._hass.states).find(
        (s) => s.entity_id.startsWith("sensor.") && s.attributes.points_week !== undefined
      );
      return sensor?.attributes?.default_rotation_strategy ?? "round_robin";
    }

    // v0.29: household-wide weekly point goal backing each child's
    // "Wochenfortschritt" progress bar (see CONF_WEEKLY_PROGRESS_GOAL_POINTS
    // in const.py) - same "rides along on every member's points sensor"
    // pattern as _milestoneBonus/_defaultRotationStrategy above. 0 (the
    // default) means no goal is configured - _renderProgressSection then
    // renders each bar as a plain running tally with no target to fill.
    _weeklyProgressGoal() {
      if (!this._hass) return 0;
      const sensor = Object.values(this._hass.states).find(
        (s) => s.entity_id.startsWith("sensor.") && s.attributes.points_week !== undefined
      );
      return Number(sensor?.attributes?.weekly_progress_goal_points ?? 0);
    }

    // v0.29: members shown in the "Wochenfortschritt" section - replaces the
    // old _rankedMembers() leaderboard list. A "child" user only ever sees
    // their own bar; anyone else (parent/admin, or an unlinked account) sees
    // one bar per active "child" member of the household, so a parent can
    // check both kids' progress at a glance without either kid seeing the
    // other's as a competitive ranking (the whole point of replacing the
    // Bestenliste). Still filtered to participates_in_rewards, same as the
    // old ranking - a member opted out of the reward system has no
    // spendable balance for this bar to lead toward.
    _progressMembers(isChildUser, currentMemberId) {
      const ids = isChildUser
        ? currentMemberId
          ? [currentMemberId]
          : []
        : Object.keys(this._members).filter((id) => this._members[id].role === "child");
      return ids
        .map((id) => ({ id, member: this._members[id] }))
        .filter((entry) => entry.member && entry.member.active !== false)
        .filter((entry) => entry.member.participates_in_rewards !== false)
        // v0.37: a paused member (see CONF_MEMBER_PAUSED) temporarily has no
        // bar here either, same reasoning as participates_in_rewards.
        .filter((entry) => entry.member.paused !== true)
        .sort((a, b) => a.member.name.localeCompare(b.member.name, "de"));
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
      if (!taskId) {
        // v0.23: a brand new task starts on the household's configured
        // default rotation strategy (Integrations-Optionen) instead of
        // always "Reihum" - see _defaultRotationStrategy. Only applies to a
        // fresh form; editing an existing task always keeps that task's own
        // rotation.strategy (taskToForm above), untouched.
        this._taskForm.rotation.strategy = this._defaultRotationStrategy();
      }
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
        // v0.34: see TASK_TRIGGER_STATE_SCHEMA/TASK_TRIGGER_NUMERIC_STATE_SCHEMA
        // in storage.py - applies to both trigger kinds above.
        recurrence.trigger.auto_complete_on_normalize = !!t.auto_complete_on_normalize;
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
        // v0.32: see CONF_TASK_VACATION_BEHAVIOR in const.py.
        vacation_behavior: form.vacation_paused ? "pause" : "show",
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
        // v0.37: see CONF_MEMBER_PAUSED in const.py.
        paused: !!form.paused,
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

    // --- Punkte vergeben (v0.24) -----------------------------------------
    //
    // Erlaubt Eltern, einem Mitglied unabhängig von einzelnen Aufgaben
    // Punkte gutzuschreiben oder abzuziehen (negative Punktzahl) - siehe
    // WS_API_POINTS_AWARD in const.py. Gleiches Bestätigungs-Zeilen-Muster
    // wie das Einlösen einer Belohnung oben (_selectReward/_confirmRedeem).

    _selectAwardPoints(memberId) {
      this._pendingAwardPointsMemberId = memberId;
      this._pendingAwardPoints = 1;
      this._pendingAwardNote = "";
      this._render();
    }

    _cancelAwardPoints() {
      this._pendingAwardPointsMemberId = null;
      this._render();
    }

    async _confirmAwardPoints(memberId) {
      const points = Math.trunc(Number(this._pendingAwardPoints)) || 0;
      if (!points) return;
      const msg = { type: "family_tasks/points/award", member_id: memberId, points };
      const note = (this._pendingAwardNote || "").trim();
      if (note) msg.note = note;
      await this._callWS(msg);
      this._pendingAwardPointsMemberId = null;
      this._pendingAwardPoints = 1;
      this._pendingAwardNote = "";
      this._render();
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
      const noteEnabled = !!f.note_enabled;
      const payload = {
        name: f.name.trim(),
        coin_cost: Math.max(0, Number(f.coin_cost) || 0),
        auto_fulfill: !!f.auto_fulfill,
        screen_time_investable: isInvestable,
        note_enabled: noteEnabled,
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
      // Gleiches "explizites null löscht" Muster (v0.24) - siehe
      // CONF_REWARD_NOTE_LABEL in const.py.
      if (noteEnabled && f.note_label.trim()) {
        payload.note_label = f.note_label.trim();
      } else if (this._editingRewardId) {
        payload.note_label = null;
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
      this._pendingInvestCoins = 1;
      this._pendingRedeemNote = "";
      this._render();
    }

    _cancelRedeem() {
      this._pendingRedeemId = null;
      this._pendingRedeemNote = "";
      this._render();
    }

    // Nicht-admin Einlösen: das Backend prüft unabhängig noch einmal, ob der
    // Aufrufer am Belohnungssystem teilnimmt und sich die Belohnung wirklich
    // leisten kann (siehe ws_redeem_reward in storage.py) - der clientseitige
    // "disabled"-Zustand der "Auswählen"/"Bestätigen"-Buttons sorgt nur
    // dafür, dass es gar nicht erst angeboten wird, ist aber nicht die
    // eigentliche Absicherung. Gleiches gilt für die v0.24-Freitext-Prüfung
    // (CONF_REWARD_NOTE_ENABLED) - ws_redeem_reward lehnt eine Einlösung
    // ohne Text serverseitig ebenfalls ab.
    async _confirmRedeem(rewardId) {
      const reward = this._rewards[rewardId];
      const msg = { type: "family_tasks/reward_redemption/redeem", reward_id: rewardId };
      if (reward?.screen_time_investable) {
        msg.coins_spent = Math.max(1, Number(this._pendingInvestCoins) || 1);
      }
      if (reward?.note_enabled) {
        msg.note = (this._pendingRedeemNote || "").trim();
      }
      await this._callWS(msg);
      this._pendingRedeemId = null;
      this._pendingInvestCoins = 1;
      this._pendingRedeemNote = "";
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
          <div class="header-actions">
            <button class="link" data-action="toggle-hide-completed">${this._hideCompleted ? "Erledigte anzeigen" : "Erledigte ausblenden"}</button>
            ${!showVisibilityControls || controlsHidden ? "" : `<button class="link" data-action="toggle-hide-not-due">${this._hideNotDue ? "Alle anzeigen" : "Nicht fällige ausblenden"}</button>`}
          </div>
        </div>
        ${!showVisibilityControls || controlsHidden ? "" : this._renderMemberFilterChips()}
        ${this._renderTaskList(isAdmin)}
        ${this._renderTaskPoolSection(isAdmin)}
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
        this._renderPointsSection(isAdmin, isChildUser),
        isAdmin ? this._renderBatterySection(controlsHidden, showVisibilityControls) : "",
        membersSection,
      ].filter((section) => section && section.trim());

      this.shadowRoot.innerHTML = `
        <style>${this._styles()}</style>
        ${ICON_DATALIST_HTML}
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
          ${this._vacationModeActive() ? `
          <div class="card-content" style="padding-top:0;padding-bottom:0;">
            <p class="muted">🌴 Urlaubsmodus aktiv - Aufgaben mit "Während Urlaubsmodus pausieren" werden derzeit übersprungen. Umschaltbar über <code>switch.family_tasks_urlaubsmodus</code>.</p>
          </div>` : ""}
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
      this._hydrateDateTimeInputs(this.shadowRoot);
      this._hydrateIconPickers(this.shadowRoot);
    }

    // ha-date-input/ha-time-input (used for recurrence.anchor_date/due_time
    // since v0.26, replacing native <input type="date"/"time"> - see the
    // CHANGELOG entry for why: those crashed the official macOS companion
    // app, which renders its native date/time picker as a UIPickerView in a
    // popover, an idiom Mac Catalyst doesn't support) both require a
    // `locale` property to render/open without throwing. That property is
    // *not* HTML-attribute-reflected (Lit's `attribute: false`), so it can't
    // be set via the plain string templates this framework-free card builds
    // its HTML from - it has to be assigned as a real JS property after the
    // elements exist in the DOM. Must run synchronously right after every
    // innerHTML/outerHTML assignment that can (re)create one of these
    // elements (see call sites), *before* returning control to the browser -
    // Lit defers a freshly-upgraded element's first render to a microtask,
    // so setting .locale synchronously here still lands before that first
    // render/before the user could possibly have clicked it yet.
    //
    // v0.27: that v0.26 switch introduced its own regression - ha-date-input/
    // ha-time-input are only ever *registered* as custom elements once Home
    // Assistant's own frontend has, somewhere on the current page, already
    // lazily loaded the bundle that defines them (e.g. by opening certain
    // config panels first). On a bare Lovelace dashboard - the normal way
    // this card is used - that bundle frequently never loads, so the tag
    // stays an unrecognized custom element: no picker UI, no error either,
    // the field just silently isn't there. That's exactly the "the due-time
    // field disappeared" report this fixes. There is no reliable, HA-
    // version-stable way for a card outside HA's own source tree to force
    // that bundle to load on demand, so instead of gambling on one, this
    // detects the failure (customElements.get below returns undefined) and
    // swaps the element for a plain, safe text fallback - see
    // _replaceWithPlainDateTimeInput, "safe" specifically meaning *not* a
    // native <input type="date"/"time">, which is what crashed the
    // companion app in the first place (the whole reason this component
    // switch happened). _renderTaskForm()/_renderOwnTaskForm() keep emitting
    // the real ha-date-input/ha-time-input tag in their template regardless
    // - every field change re-renders the whole form (see the "change"
    // listener's form.outerHTML assignment) and re-runs this hydration, so a
    // household on a setup where the bundle *does* load upgrades back to the
    // native picker automatically the next time the form redraws, with
    // nothing to configure.
    _hydrateDateTimeInputs(root) {
      if (!this._hass) return;
      root.querySelectorAll("ha-date-input, ha-time-input").forEach((el) => {
        if (customElements.get(el.tagName.toLowerCase())) {
          el.locale = this._hass.locale;
          return;
        }
        this._replaceWithPlainDateTimeInput(el);
      });
    }

    // v0.29: same registered-vs-not detection as _hydrateDateTimeInputs
    // above, for the "Icon (optional)" fields (Aufgabe/Favorit/Mitglied/
    // Belohnung) - lets someone pick a Material Design Icon from Home
    // Assistant's own searchable picker instead of having to know/type an
    // exact "mdi:..." name by heart. <ha-icon-picker> needs `.hass` (not
    // `.locale` like the date/time pickers) to search/render its icon list.
    // Falls back to a plain <input list="..."> wired to the shared
    // ICON_DATALIST_HTML datalist (rendered once in the outer template) when
    // the real component isn't registered - same reasoning as
    // _replaceWithPlainDateTimeInput: still free-text (any "mdi:..." can be
    // typed), just with one-click suggestions instead of none.
    _hydrateIconPickers(root) {
      if (!this._hass) return;
      root.querySelectorAll("ha-icon-picker").forEach((el) => {
        if (customElements.get("ha-icon-picker")) {
          el.hass = this._hass;
          return;
        }
        const fieldAttr = el.getAttribute("data-field");
        const rewardFieldAttr = el.getAttribute("data-reward-field");
        const fallback = document.createElement("input");
        fallback.type = "text";
        fallback.setAttribute("list", ICON_DATALIST_ID);
        fallback.placeholder = el.getAttribute("placeholder") || "mdi:...";
        fallback.autocomplete = "off";
        if (fieldAttr) fallback.dataset.field = fieldAttr;
        if (rewardFieldAttr) fallback.dataset.rewardField = rewardFieldAttr;
        fallback.value = el.getAttribute("value") || "";
        el.replaceWith(fallback);
      });
    }

    // Fallback for _hydrateDateTimeInputs above when ha-date-input/
    // ha-time-input isn't actually registered.
    //
    // v0.29: ha-time-input's fallback used to be a single plain text field
    // requiring a literal "hh:mm" (with colon) to match its pattern. That's
    // fine on a desktop keyboard, but the companion app's numeric keypad for
    // a pattern-restricted text input frequently has no ":" key at all -
    // "Fällig um" was effectively impossible to fill in on a phone on a
    // setup where the real component isn't registered, exactly the reported
    // bug this fixes. Replaced with two native <select> dropdowns (hour/
    // minute, see _renderFallbackTimeInput below) - no typing needed at all,
    // "eine komfortablere Auswahloption" as requested, and every phone's
    // on-screen keyboard/picker already handles a <select> natively. The
    // date fallback (ha-date-input, "YYYY-MM-DD") is unaffected - a dash is
    // available on every keyboard, and this report was about the time field
    // specifically.
    _replaceWithPlainDateTimeInput(el) {
      const isTime = el.tagName.toLowerCase() === "ha-time-input";
      const fieldAttr = el.getAttribute("data-field");
      const rawValue = el.getAttribute("value") || "";

      if (isTime) {
        // v0.31: see _renderFallbackTimeInput and _applyFieldChange's
        // due_time branch - these two extra attributes are how a partial
        // hour-only or minute-only selection survives the form's re-render
        // (rawValue/due_time itself is still "" until both are picked).
        const fallbackHour = el.getAttribute("data-fallback-hour") || "";
        const fallbackMinute = el.getAttribute("data-fallback-minute") || "";
        el.replaceWith(this._renderFallbackTimeInput(fieldAttr, rawValue, fallbackHour, fallbackMinute));
        return;
      }

      const fallback = document.createElement("input");
      fallback.type = "text";
      fallback.inputMode = "numeric";
      fallback.placeholder = "jjjj-mm-tt";
      fallback.pattern = "\\d{4}-\\d{2}-\\d{2}";
      fallback.autocomplete = "off";
      if (fieldAttr) fallback.dataset.field = fieldAttr;
      fallback.value = rawValue;
      el.replaceWith(fallback);
    }

    // Builds the <span data-field data-fallback-time> composite described
    // above: two <select> dropdowns plus a leading "--" option in each to
    // represent "no time set" (ha-time-input's `clearable` behavior) -
    // picking "--" on either one clears due_time entirely rather than
    // producing a half-set value. _applyFieldChange's due_time branch reads
    // both selects off this element (via data-fallback-time) instead of a
    // single .value, since no single child element holds the combined
    // "HH:MM" value.
    //
    // v0.31: fixes "the dropdown opens but the picked time is never
    // accepted" - every field change re-renders the whole form (see the
    // "change" listener), and this fallback used to derive both selects'
    // displayed value solely from due_time. Since due_time only becomes
    // non-empty once *both* hour and minute are set, picking just one of
    // them produced due_time="" and the re-render then rebuilt both selects
    // back at "--" - the very selection the user just made was gone before
    // they could pick the second field, so a value could never be built up
    // at all. fallbackHour/fallbackMinute (sourced from the target's
    // _dueTimeHour/_dueTimeMinute, see _applyFieldChange) now carry a
    // still-incomplete selection across that re-render independently of
    // due_time, so the first pick sticks while the user makes the second.
    // rawValue (from due_time itself) still wins once it's a complete
    // "HH:MM" - e.g. right after opening the form to edit an existing task.
    _renderFallbackTimeInput(fieldAttr, rawValue, fallbackHour = "", fallbackMinute = "") {
      const [rawH, rawM] = rawValue.includes(":") ? rawValue.split(":") : ["", ""];
      const h = rawH || fallbackHour;
      const m = rawM || fallbackMinute;
      const options = (count, selected) =>
        [`<option value="">--</option>`]
          .concat(
            Array.from({ length: count }, (_, i) => String(i).padStart(2, "0")).map(
              (v) => `<option value="${v}" ${v === selected ? "selected" : ""}>${v}</option>`
            )
          )
          .join("");
      const wrapper = document.createElement("span");
      wrapper.className = "fallback-time-input";
      if (fieldAttr) wrapper.dataset.field = fieldAttr;
      wrapper.dataset.fallbackTime = "1";
      wrapper.innerHTML = `
        <select data-time-part="hour" aria-label="Stunde">${options(24, h)}</select>
        <span aria-hidden="true">:</span>
        <select data-time-part="minute" aria-label="Minute">${options(60, m)}</select>
      `;
      return wrapper;
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
    //
    // v0.23: this._taskMemberFilter itself is now lazily seeded here (once
    // per session, on first call) instead of eagerly in setConfig, because
    // it has to be looked up per logged-in HA user id - and setConfig runs
    // before `hass` (and therefore the user) is available. Seeds from that
    // user's own remembered pick (taskMemberFilterByUser in localStorage, see
    // _saveUiState) if there is one, otherwise falls back to the "own"/null
    // first-run default exactly as before. Previously a single flat
    // taskMemberFilter value was shared by every user of the same device -
    // whichever member/parent last clicked "Alle" or a sibling's chip
    // silently became the default for the next person to open the card too,
    // instead of everyone always starting on their own tasks.
    _effectiveTaskMemberFilterId() {
      if (this._taskMemberFilter === undefined) {
        const userId = this._hass?.user?.id;
        const byUser = this._loadUiState()?.taskMemberFilterByUser || {};
        this._taskMemberFilter =
          userId && Object.prototype.hasOwnProperty.call(byUser, userId)
            ? byUser[userId]
            : this._config.only_own_tasks === false
            ? null
            : "own";
      }
      const filter = this._isChildUser() ? "own" : this._taskMemberFilter;
      if (filter === null || filter === undefined) return null;
      return filter === "own" ? this._currentMemberId() : filter;
    }

    _renderTaskList(isAdmin) {
      let ids = Object.keys(this._tasks);
      const currentMemberId = this._currentMemberId();
      // v0.25: a non-child admin (a parent/guardian account, as opposed to a
      // "child" account that also happens to be admin - see _isChildUser)
      // may always complete a task currently assigned to a child, regardless
      // of whether it's overdue - see the canAct computation below and
      // MEMBER_ROLE_CHILD in const.py. The backend already never actually
      // restricted who may call the complete_task service (see
      // FamilyTasksCoordinator.async_complete_task's docstring) - this only
      // brings the button back into the UI, re-adding what v0.22 removed for
      // everyone, but scoped to parents acting on a child's task rather than
      // anyone acting on anyone's.
      const isParentUser = isAdmin && !this._isChildUser();
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
      // v0.33: hidden for the duration of Urlaubsmodus - see
      // _isVacationPaused. Filtered out here (independent of hideNotDue/
      // hideCompleted/the member-filter chips below, same as the
      // created_by_member_id filter above) so it disappears from every view
      // including "Alle", not just from whichever filter happened to be
      // selected.
      ids = ids.filter((id) => !this._isVacationPaused(id));
      // v0.30: "Aufgabenpool" tasks (no fixed assignee, no rotation) get
      // their own dedicated section below (_renderTaskPoolSection),
      // unaffected by hideNotDue/hideCompleted/the member-filter chips - so
      // they're excluded here to avoid showing up twice. v0.32: a pool
      // occurrence someone has actively claimed is the one exception - see
      // _isClaimedPoolTask - it belongs in this normal list (subject to the
      // same filters as everything else) instead, since it's no longer
      // "unclaimed pool work", it's firmly the claimant's task now.
      ids = ids.filter((id) => !this._isPoolTask(id) || this._isClaimedPoolTask(id));
      const totalCount = ids.length;
      // v0.28: independent of hideNotDue above (which is admin-only and
      // bundles "done" together with "idle"/waiting-for-sensor) - this
      // hides only actually-completed occurrences ("Erledigt"), and is
      // available to every user, children included, see the button in
      // _render(). Ordering doesn't matter here since both filters only
      // ever remove ids, never add them back.
      if (this._hideCompleted) {
        ids = ids.filter((id) => (this._statusStateForTask(id)?.state ?? "pending") !== "done");
      }
      const filterMemberId = this._effectiveTaskMemberFilterId();
      if (filterMemberId !== null) {
        ids = ids.filter((id) => {
          if (!filterMemberId) return false;
          // v0.25: eligible_member_ids (falling back to assigned_member_ids
          // for an older cached sensor snapshot) rather than
          // assigned_member_ids itself - see the field's comment in
          // coordinator.py. Normally identical, but once an occurrence goes
          // overdue and is assigned to a child, every other active child
          // is added too, so this same "own tasks" filter (forced on for a
          // "child" account, see _effectiveTaskMemberFilterId) also surfaces
          // a sibling's overdue task in their own list instead of hiding it
          // just because it wasn't originally assigned to them.
          const attrs = this._statusStateForTask(id)?.attributes ?? {};
          const eligibleIds = attrs.eligible_member_ids ?? attrs.assigned_member_ids ?? [];
          return eligibleIds.includes(filterMemberId);
        });
      }
      // v0.36: hideNotDue (admin-only, "nicht fällige ausblenden") still
      // drops every not-due occurrence entirely, same as before - moved
      // down here (after the member-filter chips, which used to run after
      // it) purely so the not-due/due split just below sees the exact same
      // filtered id set hideNotDue itself would have used, without
      // duplicating the member-filter logic for both branches.
      if (this._hideNotDue) {
        ids = ids.filter((id) => DUE_STATUSES.includes(this._statusStateForTask(id)?.state ?? "pending"));
      }
      if (!ids.length) {
        return `<p class="muted">${totalCount ? "Keine fälligen Aufgaben." : "Noch keine Aufgaben angelegt."}</p>`;
      }

      if (this._hideNotDue) {
        return `<div class="list">${ids
          .map((id) => this._renderTaskRow(id, isAdmin, isParentUser, currentMemberId))
          .join("")}</div>`;
      }

      // v0.36: not-due occurrences (idle/done) are split out of the flat
      // list and grouped into collapsible per-recurrence-type subsections
      // instead - see _renderNotDueGroups. Only reached when hideNotDue
      // itself is off (every not-due occurrence was already dropped above
      // otherwise, leaving nothing left to group). Due occurrences
      // (DUE_STATUSES) stay exactly as before: a flat list, always
      // expanded, at the top.
      const dueIds = ids.filter((id) =>
        DUE_STATUSES.includes(this._statusStateForTask(id)?.state ?? "pending")
      );
      const notDueIds = ids.filter((id) => !dueIds.includes(id));
      const dueList = dueIds.length
        ? `<div class="list">${dueIds
            .map((id) => this._renderTaskRow(id, isAdmin, isParentUser, currentMemberId))
            .join("")}</div>`
        : "";
      return `${dueList}${this._renderNotDueGroups(notDueIds, isAdmin, isParentUser, currentMemberId)}`;
    }

    // v0.36: groups the not-due (idle/done) part of the task list by
    // recurrence type (task.recurrence.type, same keys as RECURRENCE_LABELS)
    // to improve overview on a household with a lot of tasks - "Nicht
    // fällige Aufgaben sollen in aufklappbare Untergruppen (z. B. nach
    // Wiederholungsintervall) aufgeteilt werden". Each group is collapsed by
    // default (this._openRecurrenceGroups, persisted per device - see
    // _loadUiState/_saveUiState) and toggled independently via the
    // "toggle-recurrence-group" action, same pattern as
    // "toggle-hide-excluded-batteries". Groups are ordered the same way
    // RECURRENCE_LABELS itself is defined (daily/weekly/interval_days/once/
    // trigger/confirmation-absent/battery), with any type not in that map
    // (shouldn't normally happen) appended at the end under its raw name
    // rather than silently dropped.
    _renderNotDueGroups(ids, isAdmin, isParentUser, currentMemberId) {
      if (!ids.length) return "";
      const groups = {};
      for (const id of ids) {
        const type = this._tasks[id]?.recurrence?.type || "once";
        (groups[type] || (groups[type] = [])).push(id);
      }
      const knownTypes = Object.keys(RECURRENCE_LABELS).filter((type) => groups[type]?.length);
      const otherTypes = Object.keys(groups).filter((type) => !RECURRENCE_LABELS[type]);
      const types = [...knownTypes, ...otherTypes];
      return types
        .map((type) => {
          const groupIds = groups[type];
          const label = RECURRENCE_LABELS[type] ?? type;
          const isOpen = (this._openRecurrenceGroups ?? []).includes(type);
          return `
            <div class="recurrence-group">
              <button type="button" class="link recurrence-group-toggle" data-action="toggle-recurrence-group" data-recurrence-type="${esc(type)}">
                <span class="recurrence-group-caret">${isOpen ? "▾" : "▸"}</span> ${esc(label)} (${groupIds.length})
              </button>
              ${isOpen
                ? `<div class="list">${groupIds
                    .map((id) => this._renderTaskRow(id, isAdmin, isParentUser, currentMemberId))
                    .join("")}</div>`
                : ""}
            </div>`;
        })
        .join("");
    }

    // v0.30: extracted out of _renderTaskList (which still uses this for
    // every id it keeps after its own filtering) so _renderTaskPoolSection
    // below can render "Aufgabenpool" rows with exactly the same markup/
    // actions (Annehmen, Erledigt, Bearbeiten, ...) without duplicating this
    // whole block - only which ids each section passes in differs.
    _renderTaskRow(id, isAdmin, isParentUser, currentMemberId) {
      {
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
          // v0.25: eligible_member_ids (see coordinator.py) - who may
          // currently act on this occurrence beyond assignedIds itself. Used
          // below both to decide whether *this* logged-in member can act on
          // a task assigned to someone else (a sibling stepping in once it's
          // overdue) and to surface that as a short hint next to the
          // assignee, since otherwise an "Erledigt" button showing up on a
          // task assigned to someone else would be confusing.
          const eligibleIds = statusState?.attributes?.eligible_member_ids ?? assignedIds;
          const assignedToChild = assignedIds.some((mid) => this._members[mid]?.role === "child");
          // Whoever actually completes an occurrence is credited for it
          // (see async_complete_task in coordinator.py, which always logs
          // the acting member's own id) - so a sibling stepping in on an
          // overdue task, or a parent completing a child's task, both keep
          // their own points instead of the original assignee's.
          const actingForOther =
            currentMemberId &&
            !assignedIds.includes(currentMemberId) &&
            (eligibleIds.includes(currentMemberId) || (isParentUser && assignedToChild));
          const overdueSiblingHint =
            !isConfirmation &&
            status === "overdue" &&
            currentMemberId &&
            !assignedIds.includes(currentMemberId) &&
            eligibleIds.includes(currentMemberId)
              ? " · jetzt auch für dich (überfällig)"
              : "";
          // v0.27: the task's Karenzzeit, shown as the clock time it's
          // actually due by (deadline_at = due_at + overdue_after_minutes,
          // see coordinator.py) instead of just the internal minutes value
          // used to compute the "Überfällig" status - only while there's
          // still something to do (pending/overdue; a done/confirmation
          // occurrence has nothing left to be "due" by).
          const deadlineAt = statusState?.attributes?.deadline_at;
          const deadlineSuffix =
            !isConfirmation && deadlineAt && (status === "pending" || status === "overdue")
              ? ` · Zu erledigen bis ${esc(formatDeadline(deadlineAt))}`
              : "";
          const detail =
            (isConfirmation
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
              : `${assigneeLabel} · ${esc(task.points ?? 0)} Pkt.${overdueSiblingHint}`) + deadlineSuffix;
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
          // v0.25: two additions on top of that v0.22 rule, both re-adding
          // ways to act on someone *else's* task (rather than reverting to
          // the pre-v0.22 "anyone, always" behavior) - see actingForOther
          // above for why points still go to whoever actually clicks either
          // way:
          // - eligibleIds also matches once a child's task goes overdue (see
          //   eligible_member_ids in coordinator.py), so a sibling sees the
          //   button on it too, not just the originally assigned child.
          // - a parent (isParentUser) always sees the button on any task
          //   currently assigned to a child, overdue or not - the backend
          //   never blocked this to begin with, only the card's UI did.
          //
          // v0.27: "Annehmen" reservation (see claimed_by_member_id/
          // claim_expires_at/claimable task attributes, coordinator.py) adds
          // a *narrowing* on top of the above: while someone else has an
          // occurrence claimed, isClaimedByOther below strips even the
          // isParentUser bypass - "können während der Dauer der
          // Reservierung von anderen Nutzern nicht angenommen oder erledigt
          // werden" applies to the parent-override convenience too, not just
          // eligibleIds (which the backend already narrows to [claimedBy]
          // itself, see _async_update_data - this extra check only matters
          // for the isParentUser clause that doesn't consult eligibleIds at
          // all).
          const claimedByMemberId = statusState?.attributes?.claimed_by_member_id;
          const claimExpiresAt = statusState?.attributes?.claim_expires_at;
          const claimable = !!statusState?.attributes?.claimable;
          const isClaimedByOther = !!claimedByMemberId && claimedByMemberId !== currentMemberId;
          const isClaimedByMe = !!claimedByMemberId && claimedByMemberId === currentMemberId;
          const canAct =
            !isClaimedByOther &&
            (eligibleIds.includes(currentMemberId) || (isParentUser && assignedToChild));
          // Offered only to someone actually in eligibleIds (not via the
          // isParentUser bypass - a parent never needs to reserve a child's
          // task against anyone, they can already act on it any time) and
          // only while "claimable" (nobody has already claimed it, and more
          // than one member is currently eligible - see TaskStatusData.
          // claimable in coordinator.py).
          const canClaim = claimable && !!currentMemberId && eligibleIds.includes(currentMemberId);
          const claimSuffix = claimedByMemberId
            ? isClaimedByMe
              ? ` · von dir reserviert bis ${esc(formatDeadline(claimExpiresAt))}`
              : ` · reserviert von ${esc(this._memberName(claimedByMemberId))} bis ${esc(formatDeadline(claimExpiresAt))}`
            : "";
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
          // v0.32: a parent's explanation from the last time this task's
          // claim was rejected ("Ablehnen") - see last_rejection_note/...at
          // (TaskStatusData in coordinator.py), cleared automatically the
          // next time the child retries. Shown regardless of the current
          // status so a child who missed the (also-fired) notification still
          // sees why, right on the task itself.
          const rejectionNote = statusState?.attributes?.last_rejection_note;
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
                  <span class="muted">${detail}${claimSuffix}</span>
                </div>
                <div class="row-actions">
                  ${canClaim ? iconActionButton("claim-task", "mdi:hand-back-right-outline", "Annehmen", { dataset: `data-task-id="${id}"` }) : ""}
                  ${canAct ? iconActionButton("complete-task", isConfirmation ? "mdi:check-bold" : "mdi:check", isConfirmation ? "Bestätigen" : actingForOther ? "Erledigt (Punkte gehen an dich)" : "Erledigt", { dataset: `data-task-id="${id}"`, extraClass: "success", disabled: disableComplete }) : ""}
                  ${isClaimedByMe ? iconActionButton("release-task", "mdi:undo-variant", "Abbrechen", { dataset: `data-task-id="${id}"` }) : ""}
                  ${showReject && canAct ? iconActionButton("skip-task", "mdi:close", "Ablehnen", { dataset: `data-task-id="${id}"`, extraClass: "danger", disabled: resolved }) : ""}
                  ${isConfirmation || !isAdmin ? "" : `
                  ${iconActionButton("edit-task", "mdi:pencil", "Bearbeiten", { dataset: `data-task-id="${id}"` })}
                  ${iconActionButton("delete-task", "mdi:delete", "Löschen", { dataset: `data-task-id="${id}"`, extraClass: "danger" })}`}
                </div>
              </div>
              ${rejectionNote ? `<div class="muted" style="color:var(--error-color,#db4437)">⚠ Nicht freigegeben: ${esc(rejectionNote)}</div>` : ""}
              ${subtaskList}
            </div>`;
      }
    }

    // v0.30: "Aufgabenpool" - a task with no fixed assignee(s) *and* no
    // rotation at all (rotation.member_ids empty - see is_pool_task in
    // coordinator.py). Read straight off the raw task definition (like
    // isTrigger/isChecklist in _renderTaskRow above), not off the sensor
    // attributes, since it never changes between refreshes.
    _isPoolTask(id) {
      const memberIds = this._tasks[id]?.rotation?.member_ids ?? [];
      return memberIds.length === 0 && !this._tasks[id]?.confirms;
    }

    // v0.32: a pool task someone has actively reserved ("Annehmen") right
    // now - see claimed_by_member_id (TaskStatusData in coordinator.py,
    // which also firmly assigns assigned_member_id/assigned_member_ids to
    // the claimant for as long as this is true). Read off the status
    // sensor's attributes (unlike _isPoolTask above, this *does* change
    // between refreshes - a claim can expire or be released). Such an
    // occurrence is treated as a normal, assigned task rather than an
    // unclaimed pool one - "Aufgaben, welche ein Kind reserviert hat, sollen
    // nicht weiter als Poolaufgabe angezeigt werden, sondern dann dem Kind
    // fest zugewiesen sein."
    _isClaimedPoolTask(id) {
      if (!this._isPoolTask(id)) return false;
      return !!this._statusStateForTask(id)?.attributes?.claimed_by_member_id;
    }

    // v0.30: dedicated section for Aufgabenpool tasks, always shown
    // regardless of hideNotDue/hideCompleted/the member-filter chips (see
    // "Unter offenen Aufgaben sollen ungeachtet der Filtereinstellungen auch
    // nicht fällige Aufgaben der aktuellen Woche angezeigt werden" - the
    // whole point is that a child can see and reserve one as soon as the
    // week starts, not only once it's actually due, and not only if they
    // happen to have "Alle anzeigen" selected). Only "done" occurrences are
    // left out - there's nothing left to reserve or complete on those.
    // Reuses _renderTaskRow for the actual row markup/actions (Annehmen,
    // Erledigt, ...), identical to a normal task's.
    _renderTaskPoolSection(isAdmin) {
      const currentMemberId = this._currentMemberId();
      const isParentUser = isAdmin && !this._isChildUser();
      const ids = Object.keys(this._tasks).filter((id) => {
        if (!this._isPoolTask(id)) return false;
        // v0.32: already claimed - shows in the normal task list instead
        // (see _isClaimedPoolTask / the _renderTaskList filter above).
        if (this._isClaimedPoolTask(id)) return false;
        // v0.33: hidden for the duration of Urlaubsmodus - see
        // _isVacationPaused / the matching filter in _renderTaskList.
        if (this._isVacationPaused(id)) return false;
        const status = this._statusStateForTask(id)?.state ?? "pending";
        if (status === "done") return false;
        // v0.36: a sensor-triggered ("trigger" recurrence) pool task should
        // only show up here once its bound sensor has actually opened an
        // occurrence - before that its status is "idle" (no open_occurrence
        // yet, see TriggerStateStore/_current_period_key in
        // coordinator.py), and showing it here all week regardless would
        // offer "Annehmen" on something nobody can actually act on yet.
        // Every other (non-"trigger") pool task has no "due" concept of its
        // own and keeps the previous always-visible-for-the-whole-week
        // behavior unchanged.
        if (this._tasks[id]?.recurrence?.type === "trigger" && status === "idle") return false;
        return true;
      });
      if (!ids.length) return "";

      return `
        <div class="section-header">
          <h3>Aufgabenpool</h3>
        </div>
        <p class="muted">Niemandem zugewiesene Aufgaben - meldet euch mit "Annehmen" dafür.</p>
        <div class="list">${ids
          .map((id) => this._renderTaskRow(id, isAdmin, isParentUser, currentMemberId))
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
          if (member.paused === true) statusParts.push("pausiert");
          // v0.24: "Punkte vergeben" - siehe _selectAwardPoints/
          // _confirmAwardPoints. Gleiches canManageMembers-Gate wie
          // Bearbeiten/Löschen (Eltern-only, serverseitig zusätzlich über
          // ws_award_points erzwungen).
          const isPending = this._pendingAwardPointsMemberId === id;
          return `
            <div class="row-wrap">
              <div class="row">
                <div class="row-main">
                  <span class="name">${esc(member.name)}</span>
                  ${statusParts.length ? `<span class="muted">${esc(statusParts.join(" · "))}</span>` : ""}
                </div>
                ${canManageMembers ? `
                <div class="row-actions">
                  ${iconActionButton("award-points", "mdi:star-plus-outline", "Punkte vergeben", { dataset: `data-member-id="${id}"` })}
                  ${iconActionButton("edit-member", "mdi:pencil", "Bearbeiten", { dataset: `data-member-id="${id}"` })}
                  ${iconActionButton("delete-member", "mdi:delete", "Löschen", { dataset: `data-member-id="${id}"`, extraClass: "danger" })}
                </div>` : ""}
              </div>
              ${isPending ? `
              <div class="confirm-row">
                <label>Punkte (negativ zum Abziehen)
                  <input type="number" step="1" data-action="award-points-value" data-member-id="${id}" value="${esc(this._pendingAwardPoints ?? 1)}">
                </label>
                <label>Grund (optional)
                  <input type="text" data-action="award-points-note" data-member-id="${id}" placeholder="z. B. Extra für Oma geholfen" value="${esc(this._pendingAwardNote ?? "")}">
                </label>
                <button data-action="confirm-award-points" data-member-id="${id}" ${Number(this._pendingAwardPoints) ? "" : "disabled"}>Bestätigen</button>
                <button type="button" class="link" data-action="cancel-award-points">Abbrechen</button>
              </div>` : ""}
            </div>`;
        })
        .join("")}</div>`;
    }

    // Wochenfortschritt + Belohnungen (v0.15 als "Bestenliste" gemerged aus
    // der ehemals eigenständigen family-tasks-leaderboard-card.js - siehe
    // Datei-Header; v0.29 ersetzt die Rangliste durch die Fortschrittsbalken
    // unten, siehe _renderProgressSection). Anders als "Familienmitglieder"/
    // "Batterien" ist der Zugriff selbst nicht eingeschränkt: Fortschritt und
    // Belohnungs-Katalog sind für jeden - auch ein "Kind"-Konto - immer
    // nutzbar, da ein Kind hier den eigenen Stand sehen/einlösen können muss,
    // nicht nur Eltern etwas zu konfigurieren haben. Seit v0.21 aber jeweils
    // für sich ausblendbar (_renderProgressSection/_renderRewardsSection
    // unten) - siehe dort für die Begründung.
    _renderPointsSection(isAdmin, isChildUser) {
      // Gleiche Regel wie canManageMembers oben - ein "Kind"-verknüpfter
      // Nutzer bekommt keine Katalog-/Einlösungs-Verwaltung, unabhängig vom
      // HA-Admin-Flag (serverseitig ebenfalls erzwungen, siehe
      // RewardRedemptionStorageCollectionWebsocket in storage.py).
      const canManageRewards = isAdmin && !isChildUser;
      const currentMemberId = this._currentMemberId();
      return `
        ${this._renderProgressSection(isAdmin, isChildUser, currentMemberId)}
        <hr class="section-divider">
        ${this._renderRewardsSection(canManageRewards, currentMemberId)}
      `;
    }

    // v0.29: "Bestenliste" (Rangliste, siehe CHANGELOG) ersetzt durch einen
    // wöchentlichen Fortschrittsbalken pro Kind - kein Wettbewerb zwischen
    // Geschwistern mehr, sondern jedes Kind gegen sein eigenes Wochenziel
    // (CONF_WEEKLY_PROGRESS_GOAL_POINTS in const.py, siehe
    // _weeklyProgressGoal). Ein "Kind"-Konto sieht ausschließlich den eigenen
    // Balken; Eltern sehen die Balken aller Kinder (_progressMembers), damit
    // beide im Blick behalten werden können. Anders als beim v0.21-
    // "Bestenliste"-Umschalter ist das Ausblenden hier Eltern-only (siehe
    // canToggle unten) - ein Kind bekommt keinen eigenen Schalter dafür,
    // sieht aber weiterhin, was zuletzt auf diesem Gerät eingestellt wurde.
    // Startet standardmäßig sichtbar (siehe setConfig) - anders als der
    // v0.11-Kompakt-Default der übrigen Abschnitte, da ein Kind sonst beim
    // allerersten Laden gar nicht sähe, wie weit es diese Woche schon ist.
    _renderProgressSection(isAdmin, isChildUser, currentMemberId) {
      const canToggle = isAdmin && !isChildUser;
      if (this._hideProgress) {
        return canToggle
          ? `<div class="section-toggle-row"><button class="link" data-action="toggle-hide-progress">Wochenfortschritt anzeigen</button></div>`
          : "";
      }

      const goal = this._weeklyProgressGoal();
      const members = this._progressMembers(isChildUser, currentMemberId);
      // v0.36: Meilensteinbonus - siehe _milestoneBonus. Die beiden
      // Schwellen sind jetzt fest bei 150%/200% des Wochenziels
      // (PROGRESS_THRESHOLD_PERCENTS in const.py), nicht mehr
      // konfigurierbar - nur wirksam, wenn zusätzlich ein Wochenziel > 0
      // konfiguriert ist, da beide Prozentsätze *davon* sind. Siehe
      // FamilyTasksCoordinator._async_process_milestone_coin_bonus.
      const milestone = goal > 0 ? this._milestoneBonus() : null;
      // v0.36: muss vor progressList unten deklariert werden, da dessen
      // .map()-Callback streak bereits liest (sonst ReferenceError: Cannot
      // access 'streak' before initialization bei jedem Render mit
      // mindestens einem Mitglied - const-Deklarationen werden nicht
      // gehoisted nutzbar, "const" bleibt bis zur eigenen Zeile in der
      // "temporal dead zone").
      const streak = this._streakBonus();
      // v0.36: der Balken deckt jetzt immer fest 0-200% des Wochenziels ab
      // (PROGRESS_THRESHOLD_PERCENTS in const.py) statt variabel je nach
      // konfigurierter Meilenstein-2-Schwelle - die Schwellen sind selbst
      // jetzt fest, also gibt es nichts mehr, worüber sich barMaxPercent
      // noch strecken müsste.
      const barMaxPercent = 200;

      // v0.22: jede Zeile öffnet per Klick einen Dialog mit den diese Woche
      // von diesem Mitglied erledigten Aufgaben - siehe
      // _openMemberCompletions. role="button"/tabindex sorgen zusammen mit
      // dem Enter/Leertaste-Handler in _attachListenersOnce für einfache
      // Tastaturbedienbarkeit.
      // v0.23: kleines Pfeil-Icon (".disclosure-icon") rechts in jeder Zeile,
      // rein optisch - macht sichtbar, dass die Zeile anklickbar ist und zu
      // Details führt.
      const progressList = members.length
        ? `<div class="list">${members
            .map(({ id, member }) => {
              const sensor = this._pointsSensorForMember(id);
              const weekPoints = Number(sensor?.attributes?.points_week ?? 0);
              const pct = goal > 0
                ? Math.min(100, Math.round((weekPoints / (goal * barMaxPercent / 100)) * 100))
                : 100;
              const goalReached = goal > 0 && weekPoints >= goal;
              // v0.36: leichte Marken bei 50%/100% zeigen zusätzlich die
              // Handyzeit-Tick-Bänder (PROGRESS_BAND_TICK_ADJUSTMENT_MINUTES
              // in const.py) - rein informativ, kein eigener Bonus, daher
              // ohne "reached"-Zustand.
              const bandMarkers = goal > 0
                ? [50, 100].map((percent) => ({
                    left: (percent / barMaxPercent) * 100,
                    title:
                      percent === 100
                        ? "100% des Wochenziels - Handyzeit-Ticks laufen ab hier mit voller Länge"
                        : "50% des Wochenziels - Handyzeit-Ticks fallen bis hierhin um 2 Min. kleiner aus, danach um 1 Min.",
                  }))
                : [];
              const bandMarkersHtml = bandMarkers
                .map((m) => `<div class="bar-band-marker" style="left:${Math.min(100, m.left)}%" title="${esc(m.title)}"></div>`)
                .join("");
              // v0.36: Marken für die beiden festen Meilenstein-Schwellen
              // (150%/200%), als Prozent-Position *innerhalb* des Balkens
              // (nicht vom Wochenziel) - siehe barMaxPercent oben. Die
              // Punktwerte selbst kommen fertig berechnet vom Backend
              // (milestone.threshold150Points/threshold200Points, siehe
              // _milestoneBonus) statt hier per Math.round() aus dem
              // Prozentsatz neu berechnet zu werden - so kann die Karte nie
              // einen anderen Punktwert anzeigen als der, gegen den der
              // Bonus tatsächlich vergeben wird (Python round() und JS
              // Math.round() runden einen exakten .5-Wert nicht immer
              // gleich).
              const milestone150Points = milestone ? milestone.threshold150Points : null;
              const milestone200Points = milestone ? milestone.threshold200Points : null;
              const milestone150Reached = milestone150Points !== null && weekPoints >= milestone150Points;
              const milestone200Reached = milestone200Points !== null && weekPoints >= milestone200Points;
              const milestoneMarkers = [
                milestone150Points !== null
                  ? { left: (150 / barMaxPercent) * 100, points: milestone150Points, bonus: milestone.bonus150, percent: 150, reached: milestone150Reached }
                  : null,
                milestone200Points !== null
                  ? { left: (200 / barMaxPercent) * 100, points: milestone200Points, bonus: milestone.bonus200, percent: 200, reached: milestone200Reached }
                  : null,
              ].filter(Boolean);
              // v0.32: die Marke selbst zeigt den absoluten Punktwert ("ab X
              // Pkt.") statt nur des Prozentsatzes - der Prozentsatz steht
              // nur noch ergänzend in Klammern im Tooltip. v0.36: der Bonus
              // ist jetzt in Münzen, nicht mehr Punkten.
              const milestoneMarkersHtml = milestoneMarkers
                .map((m) => `<div class="bar-milestone${m.reached ? " reached" : ""}" style="left:${Math.min(100, m.left)}%" title="${esc(`ab ${m.points} Pkt. (${m.percent}% des Wochenziels)${m.bonus > 0 ? ` · +${coinsLabel(m.bonus)}` : ""}`)}"></div>`)
                .join("");
              const barFillClass = milestone200Reached
                ? " milestone-2-reached"
                : milestone150Reached
                  ? " milestone-1-reached"
                  : goalReached
                    ? " goal-reached"
                    : "";
              const pointsLine = goal > 0 ? `${esc(weekPoints)} / ${esc(goal)} Pkt. diese Woche` : `${esc(weekPoints)} Pkt. diese Woche`;
              // v0.36: ein Streak kann jetzt für die 150%- und die
              // 200%-Marke unabhängig voneinander laufen - siehe
              // _streakWeeksFor.
              const streakWeeks = this._streakWeeksFor(id);
              const streakParts = [];
              if (streak.bonus150 > 0 && streakWeeks.weeks150 > 0) {
                streakParts.push(`🔥 ${streakWeeks.weeks150} Wochen (150%)`);
              }
              if (streak.bonus200 > 0 && streakWeeks.weeks200 > 0) {
                streakParts.push(`🔥 ${streakWeeks.weeks200} Wochen (200%)`);
              }
              // v0.37: no longer shows the Münzen balance here - coins now
              // persist independently of the calendar week (see
              // WeeklyCoinConversionStateStore/coins_available in
              // coordinator.py), so there's no reason to fold them into a
              // *weekly* progress readout any more; the balance still shows
              // in the Belohnungen section (_renderRewardsContent) and on
              // each member's dedicated Münzen sensor. Just the remaining
              // goal distance plus any streak - and only rendered at all
              // when there's actually something to say.
              const goalNote = goal > 0 && !goalReached
                ? `noch ${esc(goal - weekPoints)} Pkt. bis zum Wochenziel`
                : "";
              const balanceLine = [goalNote, streakParts.join(" · ")].filter(Boolean).join(" · ");
              return `
                <div class="row clickable" data-action="open-member-completions" data-member-id="${id}" role="button" tabindex="0">
                  <div class="row-main">
                    <div class="row-top">
                      <span class="name">${member.icon ? `<ha-icon icon="${esc(member.icon)}"></ha-icon> ` : ""}${esc(member.name)}</span>
                      <span class="points">${pointsLine}</span>
                    </div>
                    <div class="bar-track">
                      <div class="bar-fill${barFillClass}" style="width:${pct}%"></div>
                      ${bandMarkersHtml}
                      ${milestoneMarkersHtml}
                    </div>
                    ${balanceLine ? `<div class="balance">${balanceLine}</div>` : ""}
                  </div>
                  <span class="disclosure-icon">${svgIcon("chevron-right", 20)}</span>
                </div>`;
            })
            .join("")}</div>`
        : `<p class="muted">${isChildUser ? "Kein verknüpftes Familienmitglied gefunden." : "Noch keine teilnehmenden Kinder."}</p>`;

      // v0.30/v0.36: kurze Legende der beiden festen Meilenstein-Schwellen
      // samt Münzen-Bonus oben im Abschnitt, sofern der Haushalt mindestens
      // eine davon konfiguriert hat - reine Anzeige (auch für
      // Screenreader/schmale Displays, wo die Balken-Marken selbst schlecht
      // lesbar sind); die eigentliche Vergabe übernimmt
      // FamilyTasksCoordinator._async_process_milestone_coin_bonus. v0.32:
      // zeigt den absoluten Punktwert statt nur des Prozentsatzes - siehe
      // die Marker-Berechnung oben für die Rundungs-Begründung.
      const milestoneLegend = milestone
        ? [
            milestone.bonus150 > 0
              ? `150%: ab ${pointsLabel(milestone.threshold150Points)} → +${coinsLabel(milestone.bonus150)}`
              : null,
            milestone.bonus200 > 0
              ? `200%: ab ${pointsLabel(milestone.threshold200Points)} → +${coinsLabel(milestone.bonus200)}`
              : null,
          ]
            .filter(Boolean)
            .join(" · ")
        : "";

      // v0.36: "Streak-Bonus" Legende - siehe _streakBonus/
      // CONF_STREAK_150_BONUS_COINS/CONF_STREAK_200_BONUS_COINS in const.py.
      // Nur Text-Zeilen (kein Balken-Marker, da die Schwelle sich
      // wochenweise über die Zeit erstreckt, nicht auf einer einzelnen
      // Woche liegt) - eine pro konfiguriertem Tier. streak selbst ist
      // bereits weiter oben deklariert (vor progressList).
      const streakLegendParts = [];
      if (streak.bonus150 > 0) {
        streakLegendParts.push(`150%: ${streak.requiredWeeks}× in Folge → +${coinsLabel(streak.bonus150)}`);
      }
      if (streak.bonus200 > 0) {
        streakLegendParts.push(`200%: ${streak.requiredWeeks}× in Folge → +${coinsLabel(streak.bonus200)}`);
      }
      const streakLegend = streakLegendParts.length
        ? `Streak-Bonus: ${streakLegendParts.join(" · ")}`
        : "";

      return `
        <div class="section-header">
          <h3>Wochenfortschritt</h3>
          ${canToggle ? `<button class="link" data-action="toggle-hide-progress">Ausblenden</button>` : ""}
        </div>
        ${goal > 0 ? `<p class="muted">Wochenziel: ${pointsLabel(goal)}</p>` : ""}
        ${milestoneLegend ? `<p class="muted">${esc(milestoneLegend)}</p>` : ""}
        ${streakLegend ? `<p class="muted">${esc(streakLegend)}</p>` : ""}
        ${progressList}
      `;
    }

    // v0.22: Inhalt des "diese Woche erledigt"-Dialogs, geöffnet per Klick
    // auf eine Fortschritts-Zeile - siehe _openMemberCompletions.
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

    // v0.21: "Belohnungen" ausblendbar - für alle sichtbarer Umschalter,
    // nicht Eltern-only (anders als seit v0.29 bei _renderProgressSection
    // oben), standardmäßig sichtbar. Umfasst sowohl den Katalog als auch
    // "Bisherige Einlösungen" als einen gemeinsamen Block - dessen eigener
    // _hideFulfilled-Umschalter bleibt unverändert eine Ebene darunter
    // bestehen.
    _renderRewardsSection(canManageRewards, currentMemberId) {
      if (this._hideRewards) {
        return `<div class="section-toggle-row"><button class="link" data-action="toggle-hide-rewards">Belohnungen anzeigen</button></div>`;
      }
      return this._renderRewardsContent(canManageRewards, currentMemberId);
    }

    _renderRewardsContent(canManageRewards, currentMemberId) {
      const currentMember = currentMemberId ? this._members[currentMemberId] : null;
      // v0.37: a paused member (CONF_MEMBER_PAUSED) can't redeem either -
      // mirrors the server-side check in ws_redeem_reward (storage.py).
      const currentParticipates =
        !!currentMember && currentMember.participates_in_rewards !== false && currentMember.paused !== true;
      const availableCoins = currentMemberId ? this._coinsAvailableFor(currentMemberId) : 0;

      const rewardIds = Object.keys(this._rewards).sort(
        (a, b) => (this._rewards[a].coin_cost ?? 0) - (this._rewards[b].coin_cost ?? 0)
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
              const cost = r.coin_cost ?? 0;
              // Eine investierbare Handyzeit-Belohnung (v0.14) hat keinen
              // festen Preis - das Mitglied wählt beim Einlösen, wie viele
              // Münzen investiert werden - daher genügt für Leistbarkeit
              // mindestens 1 verfügbare Münze statt eines konkreten Preises.
              const affordable = currentParticipates && (isInvestable ? availableCoins >= 1 : availableCoins >= cost);
              const isPending = this._pendingRedeemId === id;
              const priceLabel = isInvestable ? "Münzen frei wählbar" : `${coinsLabel(cost)}${screenTimeSuffix(r.screen_time_minutes)}`;
              // v0.24: CONF_REWARD_NOTE_ENABLED - siehe const.py. Ein
              // Freitext-Feld im Bestätigungsschritt, z. B. für "Mittagessen
              // auswählen" (welches Mittagessen gewünscht ist), statt nur
              // eines einfachen "wirklich einlösen?"-Hinweises.
              const noteEnabled = !!r.note_enabled;
              const noteLabel = r.note_label?.trim() || "Text";
              const noteValid = !noteEnabled || !!(this._pendingRedeemNote || "").trim();
              const investValid = !isInvestable || (this._pendingInvestCoins >= 1 && this._pendingInvestCoins <= availableCoins);
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
                  ${isPending ? `
                  <div class="confirm-row">
                    ${isInvestable ? `
                    <label>Münzen investieren
                      <input type="number" min="1" max="${availableCoins}" data-action="invest-points" data-reward-id="${id}" value="${esc(this._pendingInvestCoins ?? 1)}">
                    </label>` : `<span>„${esc(r.name)}" für ${coinsLabel(cost)} einlösen?</span>`}
                    ${noteEnabled ? `
                    <label>${esc(noteLabel)}
                      <input type="text" data-action="redeem-note" data-reward-id="${id}" value="${esc(this._pendingRedeemNote ?? "")}" required>
                    </label>` : ""}
                    <button data-action="confirm-redeem" data-reward-id="${id}" ${investValid && noteValid ? "" : "disabled"}>Bestätigen</button>
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
                    <span class="muted">${coinsLabel(r.coin_cost ?? 0)}${screenTimeSuffix(r.screen_time_minutes)}${r.fulfilled ? " · erledigt" : ""}</span>
                    ${r.note ? `<span class="muted">„${esc(r.note)}"</span>` : ""}
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
        ${currentMemberId ? `<p class="muted">Dein Guthaben: ${coinsLabel(availableCoins)}${currentParticipates ? "" : " (nimmt nicht am Belohnungssystem teil)"}</p>` : ""}
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
          <label>Icon (optional)<ha-icon-picker data-reward-field="icon" placeholder="mdi:gift" value="${esc(f.icon)}"></ha-icon-picker></label>
          ${isInvestable ? "" : `
          <label>Preis (Münzen)<input type="number" min="0" data-reward-field="coin_cost" value="${esc(f.coin_cost)}"></label>
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
            Kind wählt Münzen selbst aus (Minuten = investierte Münzen × Bonusfaktor aus den Integrations-Optionen)
          </label>
          ` : ""}
          ${isScreenTime && !isInvestable ? `
          <label>Bildschirmzeit in Minuten<input type="number" min="1" data-reward-field="screen_time_minutes" placeholder="z. B. 30" value="${esc(f.screen_time_minutes)}" required></label>
          ` : ""}
          <label class="checkbox-label">
            <input type="checkbox" data-reward-field="auto_fulfill" ${f.auto_fulfill ? "checked" : ""}>
            Gilt mit der Einlösung sofort als erledigt${isScreenTime ? " (bei Handyzeit meist sinnvoll, da automatisch gewährt)" : ""}
          </label>
          <label class="checkbox-label">
            <input type="checkbox" data-reward-field="note_enabled" ${f.note_enabled ? "checked" : ""}>
            Freitext-Eingabe beim Einlösen (z. B. gewünschtes Mittagessen)
          </label>
          ${f.note_enabled ? `
          <label>Beschriftung des Textfelds (optional)<input type="text" data-reward-field="note_label" placeholder="z. B. Gewünschtes Mittagessen" value="${esc(f.note_label)}"></label>
          ` : ""}
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
            <label>Icon (optional)<ha-icon-picker data-field="icon" placeholder="mdi:car-wash" value="${esc(f.icon)}"></ha-icon-picker></label>
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
      const allBatteries = this._batteryEntityOptions();
      // v0.35: entities the household has explicitly excluded from
      // monitoring (see the "Ausschließen" checkbox below) are, by default,
      // filtered out of this list too - once a battery is marked as not
      // worth watching (a dummy/unused sensor, etc.), most households don't
      // want it cluttering the list they actually check regularly. The
      // toggle button just below un-hides them again (e.g. to change a
      // threshold or re-include one), and never affects monitoring itself -
      // purely a display filter, same as _hideBattery/_hideMembers.
      const excludedBatteries = allBatteries.filter(
        (b) => this._batteryOverrideFor(b.entityId)?.excluded
      );
      const batteries = this._hideExcludedBatteries
        ? allBatteries.filter((b) => !this._batteryOverrideFor(b.entityId)?.excluded)
        : allBatteries;
      return `
        <div class="section-header">
          <h3>Batterien</h3>
          ${controlsHidden || !showVisibilityControls ? "" : `<button class="link" data-action="toggle-hide-battery">Ausblenden</button>`}
        </div>
        <p class="muted">Legt fest, welche Batterien überwacht werden und ab welchem Stand gewarnt wird. Sobald eine überwachte Batterie ihren Schwellenwert erreicht oder unterschreitet, legt die Integration automatisch eine einmalige Aufgabe für diese Batterie an, zugewiesen an alle Familienmitglieder mit Admin-Rechten - dieser Abschnitt dient nur der Konfiguration, nicht der Aufgabenverwaltung. Der Standard-Schwellenwert wird in den Integrations-Optionen festgelegt (Einstellungen → Geräte &amp; Dienste → Family Tasks → Konfigurieren).</p>
        ${excludedBatteries.length ? `<div class="section-toggle-row"><button class="link" data-action="toggle-hide-excluded-batteries">${
          this._hideExcludedBatteries
            ? `Ausgeschlossene anzeigen (${excludedBatteries.length})`
            : "Ausgeschlossene ausblenden"
        }</button></div>` : ""}
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
          .join("")}</div>` : allBatteries.length
            ? `<p class="muted">Alle erkannten Batterien sind ausgeschlossen und ausgeblendet - "Ausgeschlossene anzeigen" oben zeigt sie wieder an.</p>`
            : `<p class="muted">Keine Batterie-Entities gefunden (Sensoren/Binärsensoren mit device_class "battery").</p>`}
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
            <label>Icon (optional)<ha-icon-picker data-field="icon" placeholder="mdi:trash-can" value="${esc(f.icon)}"></ha-icon-picker></label>
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
              <label>Ankerdatum<ha-date-input data-field="recurrence.anchor_date" value="${esc(f.recurrence.anchor_date)}"></ha-date-input></label>
            </div>` : ""}
          ${f.recurrence.type === "once" ? `
            <label>Datum<ha-date-input data-field="recurrence.anchor_date" value="${esc(f.recurrence.anchor_date)}"></ha-date-input></label>` : ""}
          ${f.recurrence.type === "trigger" ? this._renderTriggerFields(f.recurrence.trigger) : ""}
          ${f.recurrence.type === "trigger" ? this._renderCompletionButtonField(f.completion_button_entity_id) : ""}
          ${f.recurrence.type === "battery" ? `
            <p class="muted">Automatische Sammel-Aufgabe: wird fällig, sobald mindestens eine überwachte Batterie ihren Warn-Schwellenwert erreicht oder unterschreitet, und listet alle betroffenen Batterien auf. Welche Batterien überwacht werden und ab welchem Stand, wird im Abschnitt "Batterien" weiter unten festgelegt.</p>` : ""}

          ${f.recurrence.type !== "trigger" ? `
          <div class="grid2">
            <label>Fällig um (optional)<ha-time-input clearable data-field="due_time" data-fallback-hour="${esc(f._dueTimeHour ?? "")}" data-fallback-minute="${esc(f._dueTimeMinute ?? "")}" value="${esc(f.due_time)}"></ha-time-input></label>
            <label>Karenz bis überfällig (Min.)<input type="number" min="0" data-field="overdue_after_minutes" value="${esc(f.overdue_after_minutes)}"></label>
          </div>` : `
          <label>Karenz bis überfällig, nachdem der Sensor ausgelöst hat (Min.)<input type="number" min="0" data-field="overdue_after_minutes" value="${esc(f.overdue_after_minutes)}"></label>`}

          <label>Rotation
            <select data-field="rotation.strategy">
              ${Object.entries(STRATEGY_LABELS).map(([value, label]) => `<option value="${value}" ${f.rotation.strategy === value ? "selected" : ""}>${label}</option>`).join("")}
            </select>
          </label>
          <div class="chips">${memberCheckboxes}</div>
          <p class="muted">Niemanden auswählen, um die Aufgabe unzugewiesen in den "Aufgabenpool" zu legen - Kinder können sich dort per "Annehmen" dafür melden.</p>
          ${f.rotation.strategy === "least_points" ? `
          <label class="inline"><input type="checkbox" data-field="rotation.only_children" ${f.rotation.only_children ? "checked" : ""}> Nur Punkte von Kindern berücksichtigen</label>` : ""}

          <label class="inline"><input type="checkbox" data-field="enabled" ${f.enabled ? "checked" : ""}> Aktiv</label>
          <label class="inline"><input type="checkbox" data-field="requires_confirmation" ${f.requires_confirmation ? "checked" : ""}> Bestätigung durch Eltern erforderlich (bei Kindern)</label>
          <label class="inline"><input type="checkbox" data-field="vacation_paused" ${f.vacation_paused ? "checked" : ""}> Während Urlaubsmodus pausieren</label>

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
          <label>Icon (optional)<ha-icon-picker data-field="icon" placeholder="mdi:trash-can" value="${esc(f.icon)}"></ha-icon-picker></label>

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
              <label>Ankerdatum<ha-date-input data-field="recurrence.anchor_date" value="${esc(f.recurrence.anchor_date)}"></ha-date-input></label>
            </div>` : ""}
          ${f.recurrence.type === "once" ? `
            <label>Datum<ha-date-input data-field="recurrence.anchor_date" value="${esc(f.recurrence.anchor_date)}"></ha-date-input></label>` : ""}

          <div class="grid2">
            <label>Fällig um (optional)<ha-time-input clearable data-field="due_time" data-fallback-hour="${esc(f._dueTimeHour ?? "")}" data-fallback-minute="${esc(f._dueTimeMinute ?? "")}" value="${esc(f.due_time)}"></ha-time-input></label>
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
          <label class="inline"><input type="checkbox" data-field="recurrence.trigger.auto_complete_on_normalize" ${t.auto_complete_on_normalize ? "checked" : ""}> Automatisch erledigen, sobald sich der Sensor wieder normalisiert</label>
          <p class="muted">Statt manuell auf "Erledigt" zu tippen: sobald der Sensor die obige Bedingung wieder verlässt (z. B. der Mülleimer wieder als leer gemeldet wird), gilt die Aufgabe direkt als erledigt – auch bei einem Kind ohne extra Eltern-Bestätigung.</p>
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
          <label>Icon (optional)<ha-icon-picker data-field="icon" placeholder="mdi:account" value="${esc(f.icon)}"></ha-icon-picker></label>
          <label>Rolle
            <select data-field="role">
              ${Object.entries(MEMBER_ROLE_LABELS).map(([value, label]) => `<option value="${value}" ${f.role === value ? "selected" : ""}>${label}</option>`).join("")}
            </select>
          </label>
          <label class="inline"><input type="checkbox" data-field="active" ${f.active ? "checked" : ""}> Aktiv (nimmt an der Rotation teil)</label>
          <label class="inline"><input type="checkbox" data-field="participates_in_rewards" ${f.participates_in_rewards ? "checked" : ""}> Nimmt am Belohnungssystem teil (Leaderboard &amp; Belohnungen einlösen)</label>
          <label class="inline"><input type="checkbox" data-field="paused" ${f.paused ? "checked" : ""}> Pausiert (z. B. diese Woche nicht zuhause)</label>
          <p class="muted">Solange pausiert: bekommt keine neuen Aufgaben zugewiesen (Rotation überspringt dieses Mitglied, eine Aufgabe, die nur noch pausierten Mitgliedern zugewiesen ist, wird nicht fällig) und nimmt vorübergehend nicht am Belohnungssystem teil (Wochenfortschritt, Meilenstein-/Streak-Bonus, Belohnungen einlösen). Bereits verdiente Punkte &amp; Münzen bleiben unangetastet und stehen nach dem Entpausieren wieder normal zur Verfügung.</p>
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
        /* v0.24: plain inline <svg> (see svgIcon/ICON_SVG_PATHS), not
           <ha-icon>, so no width/height rule is needed to paper over an
           async icon-path lookup any more - the v0.23 attempt at exactly
           that (sizing the <ha-icon> host so at least the button's layout
           didn't jump) never actually fixed the underlying symptom (the
           round danger delete button showing as a bare red circle with no
           bin glyph until something incidentally repainted it, e.g. a
           hover). See svgIcon's comment for the full explanation - this
           rule just sizes the svg itself now, synchronously correct from
           the very first paint. */
        .icon-action-btn svg { width: 18px; height: 18px; display: block; fill: currentColor; }
        .icon-action-btn.success { color: var(--success-color, #43a047); }
        /* v0.25: the actual cause of the "Löschen"/"Ablehnen" buttons
           rendering as a plain red circle with no visible glyph (until
           hovered) was never the async icon lookup that v0.23/v0.24 above
           addressed - svgIcon has painted a synchronous, correctly-colored
           bin/cross glyph since v0.24. The real culprit is CSS specificity:
           the plain-text-button rule "button.danger { background:
           var(--error-color) }" further down (still used by the actual
           text-button confirm dialogs, e.g. "Aufgabe wirklich löschen?") has
           higher specificity (one class + one type selector) than
           ".icon-action-btn { background: none }" (one class selector), so
           it quietly won and painted every danger-styled icon button's
           circular background solid red - the same red as the icon's own
           color/fill: currentColor, making the glyph invisible against its
           own background. Only ":hover" (".icon-action-btn:hover", two
           selectors, background: card-background-color) was specific enough
           to override it, which is exactly why hovering "fixed" it. Setting
           background: none explicitly here (".icon-action-btn.danger", two
           class selectors - now specific enough to beat "button.danger")
           removes the stray red fill for good, matching how ".success"
           icon buttons (never touched by that rule) already looked all
           along: a transparent circle with just the colored glyph. */
        .icon-action-btn.danger { color: var(--error-color, #db4437); background: none; }
        /* "+ Aufgabe hinzufügen"/"+ Eigene Aufgabe hinzufügen" links, der
           "Favoriten"-Launcher rechts, in derselben Reihe (v0.22) - ist der
           rechte Teil leer (kein Favoriten-Zugriff), bleibt der linke Teil
           dank justify-content: space-between trotzdem einfach linksbündig. */
        .task-actions-row { display: flex; justify-content: space-between; align-items: center;
                              gap: 8px; flex-wrap: wrap; }
        .task-actions-row button.add { padding: 8px 0; }
        /* v0.22: klickbare Fortschritts-Zeile (öffnet die "diese Woche
           erledigt"-Übersicht für das jeweilige Mitglied, siehe
           _openMemberCompletions) - optische/Tastatur-Hinweise, dass die
           ganze Zeile ein Button ist. */
        .row.clickable { cursor: pointer; }
        .row.clickable:hover { background: var(--card-background-color, #fff); }
        .row.clickable:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }
        /* v0.23: reiner optischer Hinweis, dass eine Fortschritts-Zeile
           anklickbar ist (öffnet die "diese Woche erledigt"-Details) - siehe
           _renderProgressSection. */
        .disclosure-icon { display: inline-flex; width: 20px; height: 20px; color: var(--secondary-text-color); flex-shrink: 0; }
        .disclosure-icon svg { fill: currentColor; display: block; }
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
        /* v0.29: hour/minute <select> fallback for due_time when
           ha-time-input isn't registered - see _renderFallbackTimeInput. */
        .fallback-time-input { display: inline-flex; align-items: center; gap: 4px; }
        .fallback-time-input select { width: auto; }
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
        .bar-track { position: relative; height: 6px; border-radius: 3px; background: var(--secondary-background-color, #f2f2f2); overflow: hidden; }
        .bar-fill { height: 100%; border-radius: 3px; background: var(--primary-color); }
        /* v0.29: Wochenziel erreicht (siehe _renderProgressSection,
           goalReached) - eigene Farbe, damit auf einen Blick klar ist,
           welches Kind sein Wochenziel diese Woche schon geschafft hat.
           v0.30: bei aktiviertem Meilensteinbonus wird diese Farbe nur noch
           gezeigt, solange keine der beiden Schwellen erreicht ist - siehe
           milestone-1-reached/milestone-2-reached direkt darunter, die
           Vorrang haben (barFillClass in _renderProgressSection). */
        .bar-fill.goal-reached { background: var(--success-color, #43a047); }
        /* v0.30: Meilensteinbonus-Stufen - zwei zunehmend "wertvollere"
           Farben, damit auf einen Blick erkennbar ist, welche Schwelle ein
           Kind diese Woche schon geschafft hat. */
        .bar-fill.milestone-1-reached { background: #ffb300; }
        .bar-fill.milestone-2-reached { background: #ff6f00; }
        /* v0.30: senkrechte Marke an der Position einer Meilensteinbonus-
           Schwelle innerhalb des Balkens (siehe barMaxPercent/markers in
           _renderProgressSection) - "reached" nur zur Unterscheidung, falls
           künftig gewünscht; aktuell optisch identisch, die Farbe des
           Balkens selbst (bar-fill.milestone-*-reached oben) trägt die
           eigentliche Information. */
        .bar-milestone { position: absolute; top: 0; bottom: 0; width: 2px; margin-left: -1px;
                         background: var(--card-background-color, #fff); opacity: 0.9; }
        /* v0.36: leichte, nicht-interaktive Marken bei 50%/100% des
           Wochenziels (Handyzeit-Tick-Bänder, siehe bandMarkers in
           _renderProgressSection) - bewusst unauffälliger als
           .bar-milestone oben, da sie keinen eigenen Bonus markieren,
           sondern nur informativ die Tick-Anpassungs-Grenzen zeigen. */
        .bar-band-marker { position: absolute; top: 0; bottom: 0; width: 1px; margin-left: -0.5px;
                            background: var(--card-background-color, #fff); opacity: 0.5; }
        .confirm-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding: 8px;
                       border-radius: 8px; background: var(--secondary-background-color, #f2f2f2); font-size: 0.9em; }
        /* v0.36: aufklappbare Untergruppen für nicht fällige Aufgaben, nach
           Wiederholungsintervall - siehe _renderNotDueGroups. */
        .recurrence-group { margin: 2px 0; }
        .recurrence-group-toggle { display: block; width: 100%; text-align: left; padding: 6px 4px;
                                    font-size: 0.9em; color: var(--secondary-text-color); }
        .recurrence-group-caret { display: inline-block; width: 1em; }
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
        else if (action === "skip-task") {
          // v0.32: "Ablehnen" a child's completion (task_id here is the
          // auto-generated parent-confirmation task, task.confirms set - see
          // showReject in _renderTaskRow) additionally offers leaving an
          // optional free-text note explaining why, which the coordinator
          // stores on the original task (last_rejection_note/...at, shown
          // via _renderTaskRow below) and notifies the child with - see
          // async_skip_task in coordinator.py. A plain (non-rejection) skip
          // has no note to attach, so the prompt is skipped entirely for it.
          const taskId = el.dataset.taskId;
          const isRejection = !!this._tasks[taskId]?.confirms;
          if (isRejection) {
            const note = prompt(
              "Notiz für das Kind (optional) - warum wird die Aufgabe nicht freigegeben?"
            );
            if (note === null) return; // Abgebrochen
            const trimmed = note.trim();
            this._hass.callService(
              "family_tasks",
              "skip_task",
              trimmed ? { task_id: taskId, note: trimmed } : { task_id: taskId }
            );
          } else {
            this._hass.callService("family_tasks", "skip_task", { task_id: taskId });
          }
        }
        else if (action === "claim-task")
          this._hass.callService("family_tasks", "claim_task", { task_id: el.dataset.taskId });
        else if (action === "release-task")
          this._hass.callService("family_tasks", "release_task", { task_id: el.dataset.taskId });
        else if (action === "new-own-task") { if (this._isChildUser()) this._openOwnTaskForm(); }
        else if (action === "cancel-own-task-form") this._closeOwnTaskForm();
        else if (action === "new-member") { if (this._isAdmin() && !this._isChildUser()) this._openMemberForm(null); }
        else if (action === "cancel-member-form") this._closeMemberForm();
        else if (action === "edit-member") { if (this._isAdmin() && !this._isChildUser()) this._openMemberForm(el.dataset.memberId); }
        else if (action === "delete-member") { if (this._isAdmin() && !this._isChildUser()) this._deleteMember(el.dataset.memberId)?.catch(() => {}); }
        else if (action === "award-points") {
          // Defense-in-depth, same reasoning as edit-member/delete-member
          // above - the backend enforces this too regardless (see
          // ws_award_points in storage.py).
          if (this._isAdmin() && !this._isChildUser()) this._selectAwardPoints(el.dataset.memberId);
        } else if (action === "cancel-award-points") {
          this._cancelAwardPoints();
        } else if (action === "confirm-award-points") {
          if (this._isAdmin() && !this._isChildUser()) this._confirmAwardPoints(el.dataset.memberId)?.catch(() => {});
        }
        else if (action === "toggle-hide-not-due") {
          this._hideNotDue = !this._hideNotDue;
          this._saveUiState();
          this._render();
        } else if (action === "toggle-hide-completed") {
          // Available to every user, including a "Kind"-account - no
          // isAdmin/isChildUser gate here, unlike toggle-hide-not-due above.
          this._hideCompleted = !this._hideCompleted;
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
        } else if (action === "toggle-hide-excluded-batteries") {
          this._hideExcludedBatteries = !this._hideExcludedBatteries;
          this._saveUiState();
          this._render();
        } else if (action === "toggle-recurrence-group") {
          // v0.36: see _renderNotDueGroups - one entry per currently
          // expanded recurrence-type group within the not-due part of the
          // task list, persisted the same way as every other toggle here.
          const type = el.dataset.recurrenceType;
          const open = this._openRecurrenceGroups ?? [];
          this._openRecurrenceGroups = open.includes(type)
            ? open.filter((t) => t !== type)
            : [...open, type];
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
        } else if (action === "toggle-hide-progress") {
          // v0.29: Eltern-only, wie die anderen isAdmin/isChildUser-gated
          // Actions - der Button selbst rendert für ein "Kind"-Konto ohnehin
          // nicht (siehe _renderProgressSection), diese Prüfung ist nur eine
          // zweite Absicherung falls der Klick trotzdem ankommt.
          if (this._isAdmin() && !this._isChildUser()) {
            this._hideProgress = !this._hideProgress;
            this._saveUiState();
            this._render();
          }
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
      // klickbaren Fortschritts-Zeilen, siehe _renderProgressSection) wie
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

        // Coins-to-invest field for an investable Handyzeit redemption
        // (v0.14, coins since v0.36) - not part of the reward-catalog form
        // itself, just the pending-redeem confirm row, so it's handled
        // separately from the data-reward-field inputs below.
        const investEl = ev.target.closest('[data-action="invest-points"]');
        if (investEl) {
          this._pendingInvestCoins = Math.max(1, Number(investEl.value) || 1);
          this._render();
          return;
        }

        // Freitext-Feld für eine CONF_REWARD_NOTE_ENABLED-Belohnung (v0.24) -
        // gleiches Muster wie invest-points direkt oberhalb, ebenfalls nur
        // Teil der Bestätigungs-Zeile, nicht des Belohnungs-Formulars.
        const redeemNoteEl = ev.target.closest('[data-action="redeem-note"]');
        if (redeemNoteEl) {
          this._pendingRedeemNote = redeemNoteEl.value;
          this._render();
          return;
        }

        // "Punkte vergeben"-Bestätigungszeile (v0.24) - gleiches Muster wie
        // invest-points/redeem-note oberhalb, nur Teil der Zeile in der
        // Mitgliederliste, nicht des Mitglieder-Formulars.
        const awardPointsEl = ev.target.closest('[data-action="award-points-value"]');
        if (awardPointsEl) {
          this._pendingAwardPoints = Math.trunc(Number(awardPointsEl.value)) || 0;
          this._render();
          return;
        }
        const awardNoteEl = ev.target.closest('[data-action="award-points-note"]');
        if (awardNoteEl) {
          this._pendingAwardNote = awardNoteEl.value;
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
          const rewardFormParent = rewardForm?.parentNode;
          if (rewardForm) rewardForm.outerHTML = this._renderRewardForm();
          // v0.29: the icon field is a <ha-icon-picker> too (see
          // _hydrateIconPickers) - needs re-hydrating after the outerHTML
          // swap above just like the generic data-field path below does.
          if (rewardFormParent) this._hydrateIconPickers(rewardFormParent);
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
        // (form.outerHTML replaces the node itself, so `form` is detached
        // afterwards - grab its still-attached parent first so the
        // ha-date-input/ha-time-input .locale hydration below, see
        // _hydrateDateTimeInputs, can find the freshly-rendered replacement.)
        const formParent = form.parentNode;
        form.outerHTML = spec.render();
        this._hydrateDateTimeInputs(formParent);
        this._hydrateIconPickers(formParent);
      });

      // v0.29: <ha-icon-picker> (and, defensively, <ha-date-input>/
      // <ha-time-input>, which follow the same Home Assistant convention)
      // report a change via a "value-changed" CustomEvent (detail.value),
      // not necessarily a native "change" the listener above listens for.
      // Rather than duplicate every branch above for a second event shape,
      // this copies the picked value onto the element itself and replays it
      // as a real "change" event - the listener above then handles it
      // exactly like any native input, data-field vs data-reward-field
      // included. fireEvent (Home Assistant's own dispatch helper) sends
      // "value-changed" with composed:true, so it crosses these elements'
      // internal shadow boundaries and reaches this listener on
      // this.shadowRoot without further wiring.
      this.shadowRoot.addEventListener("value-changed", (ev) => {
        const el = ev.target;
        if (ev.detail?.value === undefined) return;
        if (!el.matches?.("[data-field], [data-reward-field]")) return;
        el.value = ev.detail.value;
        el.dispatchEvent(new Event("change", { bubbles: true, composed: true }));
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

      // due_time comes from <ha-time-input> since v0.26 (see
      // _hydrateDateTimeInputs) instead of a native <input type="time">, and
      // that component's .value always includes seconds ("HH:MM:SS", even
      // with the seconds field itself hidden). Strip that back down to
      // "HH:MM" so storage keeps getting the format storage.py documents
      // ("HH:MM") and existing due_time values/tests aren't affected.
      if (leaf === "due_time") {
        // v0.29: the hour/minute <select> fallback (see
        // _renderFallbackTimeInput) has no single .value of its own - `el`
        // here is the wrapping <span data-fallback-time>, read its two child
        // selects instead. Either one still at "--" (empty) means "no time
        // set", same as clearing the real ha-time-input.
        if (el.dataset.fallbackTime) {
          const hour = el.querySelector('[data-time-part="hour"]')?.value || "";
          const minute = el.querySelector('[data-time-part="minute"]')?.value || "";
          // v0.31: stash whichever half was just picked on the target itself
          // (read back by _renderFallbackTimeInput via the ha-time-input's
          // data-fallback-hour/-minute attributes, see the render call
          // sites) so an hour-only or minute-only selection survives the
          // form re-render below instead of snapping back to "--" - see the
          // long comment on _renderFallbackTimeInput for the full story.
          target._dueTimeHour = hour;
          target._dueTimeMinute = minute;
          target.due_time = hour && minute ? `${hour}:${minute}` : "";
          return;
        }
        target.due_time = el.value ? el.value.slice(0, 5) : el.value;
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
