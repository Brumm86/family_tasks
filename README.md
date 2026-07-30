# Family Tasks

Home-Assistant-Integration zur Verwaltung wiederkehrender Familien-Aufgaben (Putzplan-Rotation, Punkte) über `config_flow`, `DataUpdateCoordinator` und eine Storage Collection – keine YAML-Integration.

## Struktur

```
custom_components/family_tasks/
  __init__.py                          Setup, Services (complete_task/skip_task), Frontend-Registrierung
  config_flow.py                        Einmaliges Setup + Options-Flow (Karenzzeit, Default-Rotationsstrategie)
  storage.py                             StorageCollections für Tasks/Members + Websocket-CRUD-API
                                          (inkl. Rollen-Guard für Mitglieder-CRUD und den
                                          nicht-admin-Befehl family_tasks/task/create_own)
  coordinator.py                          Berechnet Status/Fälligkeit/Rotation/Punkte aus Storage + Completion-Log
  sensor.py / button.py                    Dynamische Entities je Task/Mitglied
  www/family-tasks-card.js                Lovelace-Karte (CRUD über die Websocket-API, keine Build-Tools nötig)
  www/family-tasks-leaderboard-card.js    Lovelace-Bestenliste (Wochen-/Monatsansicht)
tests/                                    pytest-homeassistant-custom-component Testsuite
```

## Installation in Home Assistant

1. `custom_components/family_tasks/` in das `custom_components`-Verzeichnis deiner HA-Konfiguration kopieren (bzw. den ganzen Ordner per Samba/SSH dorthin syncen).
2. Home Assistant neu starten.
3. Einstellungen → Geräte & Dienste → Integration hinzufügen → „Family Tasks" suchen, Anzeigename bestätigen.
4. Dashboard bearbeiten → Karte hinzufügen → „Family Tasks" auswählen (oder manuell `type: custom:family-tasks-card`). Die Karte lädt sich automatisch, es ist keine manuelle Lovelace-Resource nötig.
5. In der Karte zunächst Familienmitglieder anlegen (optional mit `person.*`-Verknüpfung und Rolle „Kind", wenn die Erledigung von einem Elternteil bestätigt werden soll), danach Aufgaben mit Wiederholung, Fälligkeit und Rotation. Wiederholung kann „Täglich", „Wöchentlich", „Alle N Tage", „Einmalig" (ein einzelner, nie wiederkehrender Termin) oder „Sensor-Ereignis" sein.
6. „Erledigt" in der Karte oder die Services `family_tasks.complete_task` / `family_tasks.skip_task` in Automatisierungen nutzen. Ist die zugewiesene Person ein „Kind"-Mitglied, wird die Aufgabe erst als „Wartet auf Bestätigung" markiert und eine Bestätigungsaufgabe für die Eltern angelegt (außer die Aufgabe hat „Bestätigung durch Eltern erforderlich" explizit deaktiviert); erst wenn ein Elternteil diese abschließt, gelten Punkte/Rotation als vergeben (Ablehnen über „Überspringen" auf der Bestätigungsaufgabe setzt die Aufgabe zurück).
7. In der Kopfzeile „Aufgaben" lassen sich per Button nicht-fällige Aufgaben ausblenden sowie auf „Nur eigene Aufgaben" filtern (bezogen auf das über die verknüpfte `person`-Entität ermittelte, zum eingeloggten HA-Benutzer gehörende Mitglied). In der Kopfzeile „Familienmitglieder" lässt sich die komplette Mitglieder-Sektion (Überschrift, Liste, „+ Mitglied hinzufügen") ein-/ausblenden. Über den kleinen Button oben rechts in der Karte lassen sich die Umschalt-Buttons komplett verbergen, um die Karte im Alltag kompakt zu halten. Alle Einstellungen werden pro Gerät/Browser gespeichert (localStorage) und überstehen ein Neuladen des Dashboards.
8. Bearbeiten/Löschen von Aufgaben ist in der Karte nur für Home-Assistant-Administratorkonten sichtbar (Home Assistant lehnt diese Aktionen für Nicht-Admins serverseitig ohnehin ab). Für Familienmitglieder gilt zusätzlich: ein Benutzer, der (über `person_entity_id` → die verknüpfte Person → deren `user_id`) einem Mitglied mit Rolle „Kind" zugeordnet ist, bekommt nie Mitglieder-Verwaltung angezeigt und wird serverseitig abgelehnt (`MemberStorageCollectionWebsocket`) - unabhängig vom Admin-Status des HA-Kontos. Aufgaben erledigen/überspringen funktioniert für alle Konten weiterhin, da das über die Services `complete_task`/`skip_task` läuft.
9. Ein Benutzer, der einem „Kind"-Mitglied zugeordnet ist, sieht zusätzlich „+ Eigene Aufgabe hinzufügen" - ganz ohne Admin-Rechte, über den eigenen Websocket-Befehl `family_tasks/task/create_own`. Dabei werden Punkte immer auf 0 und die Zuweisung immer auf das eigene Mitglied erzwungen; wählbar ist lediglich, ob die Aufgabe eine Eltern-Bestätigung benötigt.
10. Rotationsstrategie „Wenigste Punkte" weist eine Aufgabe jeweils demjenigen Mitglied im Rotationspool zu, das aktuell die wenigsten Punkte hat (bei Gleichstand das erste in der Liste); die Option „Nur Punkte von Kindern berücksichtigen" schränkt diesen Vergleich auf Mitglieder mit Rolle „Kind" ein.
11. Die Karte „Family Tasks Leaderboard" (`type: custom:family-tasks-leaderboard-card`) zeigt eine nach Punkten sortierte Bestenliste mit umschaltbaren Ansichten „Woche" und „Monat".

## Tests

Die Suite nutzt [pytest-homeassistant-custom-component](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component), das täglich gegen die aktuelle HA-Version gebaut wird – dafür wird **Python 3.13** benötigt (aktuelle HA-Mindestanforderung).

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements_test.txt
pytest
```

Abgedeckt sind: Config-Flow (Singleton-Setup), Storage-Collection-Validierung/-Merge-Verhalten, Coordinator-Logik (Status-Berechnung, Rotation, Punktevergabe, Idempotenz von `complete_task`, `skip_task`, Overdue-Erkennung), Kind-Bestätigungs-Workflow, sowie (neu) die Rollen-Guards für Mitglieder-CRUD/`create_own_task` (`tests/test_permissions.py`) und die Rekurrenz „einmalig", Rotation „Wenigste Punkte" (inkl. „Nur Kinderpunkte") und das `requires_confirmation`-Override (`tests/test_new_features.py`).

**Hinweis zur Verifikation während der Entwicklung:** Die pytest-Suite selbst konnte in der Entwicklungsumgebung nicht ausgeführt werden, da dort nur Python 3.10 mit einem auf `homeassistant==2023.7.3` eingefrorenen `pytest-homeassistant-custom-component`-Mirror verfügbar ist, der Code aber gegen eine deutlich aktuellere HA-Version geschrieben ist (`StaticPathConfig`, `EventStateChangedData`, `ConfigEntry.runtime_data` u. a. existieren dort schlicht nicht). Stattdessen wurde die neue Logik direkt gegen den echten Code verifiziert, unter Umgehung nur des Pakets `__init__.py` (das die inkompatiblen Frontend-Imports enthält): `storage.py`/`coordinator.py` wurden isoliert importiert (nach `import pytest_homeassistant_custom_component.plugins`, das HA intern sauber genug bootstrapt, um den zirkulären Import von `websocket_api`/`http` zu vermeiden), und darüber wurden echte `vol.Schema`-Validierungen (u. a. „einmalig", „least_points" + „only_children", `requires_confirmation`) sowie die Coordinator-Methoden `_current_period_date`, `_member_with_least_points`, `_assigned_member_id` und die Berechtigungs-Helfer `_member_id_for_user`/`_member_role_for_user`/`MemberStorageCollectionWebsocket._reject_if_child` mit echten Aufrufen (nur die HA-Objekte `hass.states`/`connection` sind Leichtgewicht-Fakes) durchgespielt - alle bestanden. Die hier eingecheckten pytest-Dateien selbst (inkl. `test_permissions.py`, das echte `hass_ws_client`-Websocket-Verbindungen mit frisch erzeugten HA-Benutzern nutzt) wurden **nicht** durch einen echten `pytest`-Lauf bestätigt. Bitte vor dem nächsten Feature-Ausbau einmal lokal (mit passender HA-Version) `pytest` laufen lassen.
