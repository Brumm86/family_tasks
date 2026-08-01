# Changelog

All notable changes to Family Tasks are documented here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [0.11.0] - 2026-08-01

### Added
- **Belohnungen können sofort etwas auslösen (z. B. zusätzliche Bildschirmzeit)**: ein Belohnungs-Katalogeintrag kann jetzt optional "Zusätzliche Bildschirmzeit in Minuten" tragen (`screen_time_minutes`, im Belohnungsformular der Bestenlisten-Karte, admin-only). Der Wert selbst hat für die Integration keine Bedeutung außer als Anzeige (`· +N Min. Bildschirmzeit` in Katalog und Einlöse-Verlauf) - die eigentliche Wirkung entsteht über ein neues Event `family_tasks_reward_redeemed`, das bei jeder Einlösung gefeuert wird (`member_id`, `member_name`, `reward_id`, `reward_name`, `points_cost`, `screen_time_minutes`). Eine eigene Home-Assistant-Automatisierung mit Event-Trigger reagiert darauf und erhöht z. B. sofort die Google-Family-Link-Bildschirmzeit des passenden Kindes - ohne dass ein Elternteil eingreifen muss. Bewusst kein direkter Aufruf einer fest verdrahteten Automations-ID aus der Integration heraus: das würde deren eigene Trigger-Bedingungen umgehen und eine HA-spezifische Entity-ID im Integrationscode verankern. Da beide Kinder unterschiedlich viel Zeit bekommen sollen, legt man am einfachsten zwei Katalogeinträge mit je eigenem `screen_time_minutes`-Wert an und lässt die Automatisierung anhand von `event_data.member_id` (bzw. der gewählten Belohnung) verzweigen - die konkrete Familiy-Link-Logik bleibt vollständig in der Automatisierung, nicht in der Integration.

### Fixed
- **Bestenlisten-Karte lädt gelegentlich nicht korrekt**: dieselbe Ursache wie ursprünglich bei der Aufgaben-Karte vermutet, aber tatsächlich in beiden Karten nie behoben - `disconnectedCallback` (`family-tasks-card.js` und `family-tasks-leaderboard-card.js`) räumte zwar die Websocket-Subscriptions ab, setzte aber `_subscribed` nicht zurück. Lovelace kann dieselbe Karten-Instanz vom DOM trennen und später wieder anhängen (Dashboard bearbeiten/umsortieren, Ansicht wechseln), ohne sie neu zu erzeugen - `set hass()` überspringt dann `_subscribe()`, weil `_subscribed` noch `true` ist, und die Karte läuft stillschweigend auf toten Subscriptions weiter (leere/veraltete Anzeige ohne Fehler, erst ein voller Seiten-Reload half). Beide Karten setzen `_subscribed` jetzt in `disconnectedCallback` zurück, sodass ein erneutes Anhängen zuverlässig neu abonniert.
- **Einstellungen der Aufgaben-Karte wurden auf manchen Geräten nie gespeichert**: auf Geräten/Browsern, bei denen `window.localStorage` beim Lesen/Schreiben lautlos wirft (beobachtet auf einem Samsung Galaxy S24, vermutlich eine Webview-/privater-Modus-Einschränkung), fiel die Karte bei jedem Laden auf die Konfigurations-Defaults zurück - bisher `false` (alles anzeigen) für "Familienmitglieder"/"Batterien"-Sichtbarkeit und "Nur eigene Aufgaben". Der eigentliche Speicher-Fehler lässt sich von der Integration aus nicht beheben, aber der Fallback-Default für diese drei Einstellungen ist jetzt `true` (kompakt, nur eigene Aufgaben) statt `false` - explizit `hide_members_list: false` / `hide_battery_section: false` / `only_own_tasks: false` in der Karten-Konfiguration stellt bei Bedarf das alte Verhalten wieder her. `hide_not_due_tasks` bleibt unverändert bei `false`.

## [0.10.0] - 2026-07-31

### Fixed
- **Familienmitglieder bearbeiten funktionierte nicht**: das Bearbeiten-Formular (und ebenso "+ Mitglied hinzufügen") setzte zwar den internen "Formular offen"-Status, das dazugehörige `<dialog>` fehlte aber komplett in `_render()` (`family-tasks-card.js`) - der Klick auf "Bearbeiten" tat dadurch sichtbar nichts. Das Mitglieder-Formular öffnet jetzt wie das Aufgaben-Formular als natives Dialogfenster.
- **"1 Punkte" statt "1 Punkt"**: der Preis einer Belohnung, der Einlöse-Bestätigungstext, der Belohnungsverlauf und die Guthaben-Anzeige in der Bestenlisten-Karte verwendeten immer die Pluralform. Ein Punkt heißt jetzt korrekt "1 Punkt".

### Changed
- **Familienmitglieder zeigen nur noch ihren Namen**: die verknüpfte Person-Entity-ID (bzw. "keine Verknüpfung") stand bisher zusätzlich unter dem Namen in der Aufgaben-Karte - das ist eine Konfigurationsdetail des Bearbeiten-Formulars und gehört nicht auf die Karte. Status-Hinweise ("inaktiv", "Kind", "nimmt nicht an Belohnungen teil") werden weiterhin angezeigt.
- **"Überspringen" nur noch bei turnusmäßigen Aufgaben**: der Button erschien bisher bei jeder Aufgabe, unabhängig vom Wiederholungstyp. Er wird jetzt nur noch für Aufgaben mit einem festen Rhythmus (täglich, wöchentlich, alle N Tage) angezeigt - bei "Einmalig", "Sensor-Ereignis" und der veralteten automatischen Batteriewarnung ergibt "zur nächsten Zuteilung überspringen" keinen Sinn. Der "Ablehnen"-Button der Eltern-Bestätigung (derselbe Button, andere Beschriftung) bleibt davon unberührt.

## [0.9.0] - 2026-07-31

### Added
- **Punkte-Shop statt Wochengewinner-Belohnung**: das v0.8-Belohnungssystem (nur der aktuelle Wochengewinner darf einmal pro Woche eine Belohnungsgruppe + Freitext auswählen) ist komplett ersetzt. Eltern pflegen jetzt einen Belohnungs-Katalog (Name, optionales Icon, Preis in Punkten - admin-only CRUD, `family_tasks/reward/*`); jedes am Belohnungssystem teilnehmende Familienmitglied kann jederzeit jede Belohnung auswählen und die Auswahl bestätigen, sofern sein aktuelles Punkte-Guthaben ausreicht (`family_tasks/reward_redemption/redeem`, serverseitig erneut geprüft). Das Bestätigen zieht die erforderlichen Punkte sofort vom Konto ab - das Guthaben (`points_available`, neues Attribut des Punkte-Sensors) ist immer die Gesamtpunktzahl abzüglich aller bisherigen Einlösungen, es gibt keinen separat gepflegten Kontostand. Jedes Kind sieht dabei stets den vollständigen Katalog samt Preisen, auch wenn eine Belohnung gerade nicht leistbar ist - nur der "Auswählen"-Button ist dann deaktiviert. Bestehende v0.8-Belohnungsgruppen/-Einlösungen werden beim ersten Start automatisch ins neue Format migriert (Preis 0, keine rückwirkende Punkteabbuchung).
- **Teilnahme-Flag für Familienmitglieder** (`participates_in_rewards`, neue Checkbox "Nimmt am Belohnungssystem teil" im Familienmitglieder-Formular der Aufgaben-Karte, Default an): legt fest, ob ein Mitglied auf der Bestenliste erscheint und Belohnungen einlösen darf - so können z. B. nur die Kinder teilnehmen.

### Changed
- **Belohnungen sind jetzt Teil der Bestenlisten-Karte, nicht mehr der Aufgaben-Karte**: die komplette Belohnungsverwaltung (Katalog, Einlösen, Verlauf) sitzt jetzt in `family-tasks-leaderboard-card.js`, zusammen mit dem Punkte-Guthaben jedes teilnehmenden Mitglieds (namentlich angezeigt, unabhängig von der Wochen-/Monatsansicht). Die Bestenliste selbst zeigt nur noch Mitglieder, die am Belohnungssystem teilnehmen.
- **Sensor-Ereignis-Aufgaben zeigen auf der Aufgaben-Karte nur noch den aktuellen Sensorwert**: bisher stand dort z. B. "Sensor: binary_sensor.muelleimer_voll · aktuell: on", jetzt nur noch "Sensor: on" - der Entity-Name/die Entity-ID ist weiterhin im Bearbeiten-Formular sichtbar, gehört aber nicht auf die Karte.
- **"Batterien anzeigen" und "Familienmitglieder anzeigen"** (die Buttons, die eine ausgeblendete Sektion wieder einblenden) stehen jetzt jeweils in einer eigenen Reihe statt nebeneinander.

## [0.8.0] - 2026-07-31

### Added
- **Kinder können eigene Checklisten-Aufgaben anlegen**: das nicht-admin-Formular „+ Eigene Aufgabe hinzufügen" (`family_tasks/task/create_own`) bietet jetzt auch den Aufgabentyp „Checkliste" mit demselben Unteraufgaben-Editor wie im Admin-Formular - weiterhin ohne Punkte und nur sich selbst zugewiesen (`storage.CREATE_OWN_TASK_SCHEMA`).
- **Wochengewinner-Belohnung**: wer in der aktuellen Woche die meisten Punkte hat (`is_weekly_winner`, neues Attribut des Punkte-Sensors, Gleichstand teilt den Gewinn, niemand gewinnt bei 0 Punkten), bekommt in der Karte einen „Belohnung auswählen"-Hinweis. Zur Auswahl stehen von den Eltern angelegte Belohnungsgruppen (neuer admin-only Kartenabschnitt „Belohnungen" → „Belohnungsgruppen", z. B. „Mittagessen auswählen"); dazu trägt der Gewinner einen freien Text ein (z. B. welches Mittagessen) und speichert - die Belohnung erscheint dann mit dem Namen des Gewinners in der offenen Liste. Eltern können eine Belohnung als „erledigt" markieren; ein Kind kann das nicht, auch nicht mit einem Admin-Konto. Neue Websocket-API `family_tasks/reward_group/*` (admin-only CRUD) und `family_tasks/reward/*` (Auswahl ausschließlich über den eigenen, nicht-admin Befehl `family_tasks/reward/claim`, der serverseitig erneut prüft, dass der Aufrufer wirklich aktueller Wochengewinner ist und diese Woche noch keine Belohnung gewählt hat; „erledigt"-Markierung über `family_tasks/reward/update`, gesperrt für Kinder-Konten).

### Changed
- **Sichtbarkeitseinstellungen der Karte sind jetzt Eltern-only**: ein Nutzer, der einem „Kind"-Mitglied zugeordnet ist, sieht die Umschalt-Buttons „Nicht fällige ausblenden", „Nur eigene Aufgaben", die Sichtbarkeit von „Familienmitglieder"/„Batterien" sowie den Kompaktmodus-Button oben rechts nicht mehr - für Kinder ist die Aufgabenliste immer (nicht nur standardmäßig) auf die eigenen Aufgaben gefiltert.
- **Aufgabe bearbeiten/anlegen öffnet jetzt in einem eigenen Fenster**: das Formular für „Aufgabe hinzufügen"/„Bearbeiten" (Admin) sowie „Eigene Aufgabe hinzufügen" (Kind) und die neue Belohnungsauswahl öffnen als natives Dialog-Fenster (`<dialog>`/`showModal()`) statt inline in der Karte. Zuvor konnte das Formular bei mehreren offenen Aufgaben-Karten unterhalb aller anderen landen und leicht übersehen werden; ein modales Dialogfenster liegt immer über der gesamten Seite, unabhängig davon, wo die Karte im Dashboard sitzt, und schließt sich per „Abbrechen" oder Escape.

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
