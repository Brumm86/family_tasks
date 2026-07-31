# Changelog

All notable changes to Family Tasks are documented here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [0.7.0] - 2026-07-31

### Added
- **New task type "Checkliste"**: a task can now carry an open-ended list of named sub-items instead of a single "Erledigt" action (e.g. "Kofferpacken" with one sub-item per thing to pack). Sub-items are checked off individually - checked ones render struck-through - and the task itself only becomes "Erledigt" once every sub-item is checked for the current period (new `family_tasks.toggle_subtask` service, `FamilyTasksCoordinator.async_toggle_subtask` in `coordinator.py`, new `storage.ChecklistStateStore`). The manual "Erledigt" button is disabled for these tasks so completion always goes through the checklist; "Überspringen" still works as before.
- **Trigger-task completion button**: a "Sensor-Ereignis" task can optionally name a `button.*` entity (new `completion_button_entity_id` task field) that gets pressed the moment the task is actually marked done - e.g. a vacuum's "resume cleaning" button once its "needs emptying" task is completed.
- **Current sensor value on trigger tasks**: the task list now shows the bound sensor's current state/value (with unit, if any) next to its trigger definition, so it's visible how close a numeric sensor is to its threshold without leaving the card.

### Changed
- **Fixed multi-assignee tasks now show every assignee**: a task whose rotation is "Fest zugewiesen" (fixed) with more than one member selected previously only ever displayed one of them on the task card (`assigned_member_id`, an index into the rotation). The status sensor now also exposes `assigned_member_ids` - every member currently responsible, all of them for a fixed multi-assignee task - and the card's task list and "Nur eigene Aufgaben" filter both use it instead.
- **Einmalige ("once") Aufgaben werden nach Erledigung gelöscht**: completing a `once`-recurrence task now removes it entirely instead of leaving it sitting in the list marked "Erledigt" forever. This also applies to the automatic battery-alert tasks (v0.6, also `once`), which previously piled up once resolved. Skipping a `once` task is unchanged (still resolves it in place); only actual completion deletes it.
- **Lovelace cards occasionally failing to load correctly**: the bundled card URLs now carry a `?v=<integration version>` cache-buster. Registering the static file with `cache_headers=False` doesn't stop every client from caching it regardless - browsers can still apply heuristic caching, and Home Assistant's installed-PWA/companion-app service worker in particular caches same-URL requests aggressively - so a device could keep running an older, incompatible copy of the card after an update. Bumping the query string on every release forces a fresh fetch instead.

## [0.6.0] - 2026-07-30

### Added
- **Automatic battery-warning tasks**: monitored batteries no longer need a manually created "Batteriewarnung" task. The moment a battery is at/below its warning threshold (or a binary low-battery sensor trips), the coordinator itself raises a single one-time task naming exactly that battery, assigned to every family member linked to a Home Assistant admin account (`FamilyTasksCoordinator._async_raise_battery_alerts` in `coordinator.py`, new `battery_alert` task field). Only one such task is open per battery at a time - a new one is only raised once the previous alert is completed or skipped. The recurrence type "battery" itself still works for households that already set one up, but is no longer offered when creating a new task.
- **Collapsible "Batterien" card section**: the admin-only per-battery configuration section (exclude / custom threshold) can now be hidden, the same way the "Familienmitglieder" section already could (new `hide_battery_section` card option, persisted per device). The section has always been configuration-only and stays that way - it never lists or creates tasks itself.

### Changed
- **"Nur eigene Aufgaben" filter**: a task whose rotation is "Fest zugewiesen" (fixed) with more than one member selected is now shown to every one of those members, not just whoever happens to sit at `rotation.current_index` - a fixed multi-assignee task never actually rotates, so it's a shared task rather than "belonging" to one person at a time. Every other rotation option is unchanged: the filter still only shows the task to whoever is currently responsible for it.
- **Leaderboard card**: member rows no longer show the "· Kind" role suffix after the name.

## [0.5.0] - 2026-07-30

### Added
- **Automatic battery-warning task** (recurrence type "battery"): a single task that aggregates *every* battery-level entity Home Assistant reports (`sensor`/`binary_sensor` with `device_class: battery`) instead of tracking one sensor. It becomes due the moment any monitored battery is at/below its warning threshold and lists exactly which ones (name + level) on the task; stays idle otherwise. New admin-only "Batterien" card section lets individual batteries be excluded from monitoring or given their own warning threshold, backed by the new `family_tasks/battery_override/*` storage-collection websocket API (`storage.BatteryOverrideStorageCollection`). The household-wide default threshold (20% unless changed) is configurable in the integration's Options.

## [0.4.0] - 2026-07-30

### Added
- **Leaderboard card** (`family-tasks-leaderboard-card.js`): new Lovelace card ranking family members by points, with switchable "Woche" (week) / "Monat" (month) views. Backed by a new `points_month` attribute on the member points sensor.
- **"Einmalig" (once) recurrence**: a task can now be a single, non-repeating occurrence pinned to a specific date. Once completed or skipped it stays resolved for good.
- **"Wenigste Punkte" (least points) rotation strategy**: assigns a task to whoever in the rotation pool currently has the fewest points, recomputed on every refresh. Optional "Nur Punkte von Kindern berücksichtigen" (only consider children's points) narrows the comparison to members with role "child".
- **Self-service tasks for children**: a user linked (via `person_entity_id`) to a "child" member can create a task for themselves without an admin account, via the new `family_tasks/task/create_own` websocket command. Points are always forced to 0 and the task is always assigned to themselves only; they choose whether the task requires parental confirmation (`requires_confirmation`).
- **`requires_confirmation` override**: any task can now explicitly opt out of the parent-confirmation gate for child assignees (previously always required for any task assigned to a "child" member).
- **"Nur eigene Aufgaben" toggle**: filter the task list down to occurrences assigned to the family member linked to the logged-in HA user. Persisted per device like the existing toggles.

### Changed
- Hiding the "Familienmitglieder" section now hides the entire section - heading, list, and "+ Mitglied hinzufügen" button - instead of just the member list.

### Security
- Family member management (create/update/delete) is now blocked server-side for any HA user linked to a member with role "child", regardless of that user's HA admin flag (`MemberStorageCollectionWebsocket` in `storage.py`). Previously this relied entirely on giving children a separate non-admin HA account.

## [0.3.0] - 2026-07-29

### Added
- Member roles: "parent" / "child". A "child" member's task completion no longer awards points immediately - it raises an auto-generated confirmation task for the household's parents. Completing that task finalizes the child's claim (points + rotation); skipping it rejects the claim.

## [0.2.0] - 2026-07-29

### Added
- Sensor-triggered tasks (recurrence type "trigger"): a task can become due when a bound sensor/binary_sensor reaches a given state, or a numeric sensor crosses a threshold (above/below), instead of on a fixed calendar schedule.

## [0.1.0] - 2026-07-27

### Added
- Initial release: task and family member management via `config_flow`, `DataUpdateCoordinator`, and Storage Collections. Daily/weekly/interval-days recurrence, round-robin/random/fixed rotation, points tracking, and the `family-tasks-card` Lovelace card.
