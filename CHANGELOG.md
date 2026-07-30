# Changelog

All notable changes to Family Tasks are documented here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

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
