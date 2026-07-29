# Family Tasks

Home-Assistant-Integration zur Verwaltung wiederkehrender Familien-Aufgaben (Putzplan-Rotation, Punkte) über `config_flow`, `DataUpdateCoordinator` und eine Storage Collection – keine YAML-Integration.

## Struktur

```
custom_components/family_tasks/
  __init__.py            Setup, Services (complete_task/skip_task), Frontend-Registrierung
  config_flow.py          Einmaliges Setup + Options-Flow (Karenzzeit, Default-Rotationsstrategie)
  storage.py               StorageCollections für Tasks/Members + Websocket-CRUD-API
  coordinator.py            Berechnet Status/Fälligkeit/Rotation/Punkte aus Storage + Completion-Log
  sensor.py / button.py      Dynamische Entities je Task/Mitglied
  www/family-tasks-card.js  Lovelace-Karte (CRUD über die Websocket-API, keine Build-Tools nötig)
tests/                      pytest-homeassistant-custom-component Testsuite
```

## Installation in Home Assistant

1. `custom_components/family_tasks/` in das `custom_components`-Verzeichnis deiner HA-Konfiguration kopieren (bzw. den ganzen Ordner per Samba/SSH dorthin syncen).
2. Home Assistant neu starten.
3. Einstellungen → Geräte & Dienste → Integration hinzufügen → „Family Tasks" suchen, Anzeigename bestätigen.
4. Dashboard bearbeiten → Karte hinzufügen → „Family Tasks" auswählen (oder manuell `type: custom:family-tasks-card`). Die Karte lädt sich automatisch, es ist keine manuelle Lovelace-Resource nötig.
5. In der Karte zunächst Familienmitglieder anlegen (optional mit `person.*`-Verknüpfung und Rolle „Kind", wenn die Erledigung von einem Elternteil bestätigt werden soll), danach Aufgaben mit Wiederholung, Fälligkeit und Rotation.
6. „Erledigt" in der Karte oder die Services `family_tasks.complete_task` / `family_tasks.skip_task` in Automatisierungen nutzen. Ist die zugewiesene Person ein „Kind"-Mitglied, wird die Aufgabe erst als „Wartet auf Bestätigung" markiert und eine Bestätigungsaufgabe für die Eltern angelegt; erst wenn ein Elternteil diese abschließt, gelten Punkte/Rotation als vergeben (Ablehnen über „Überspringen" auf der Bestätigungsaufgabe setzt die Aufgabe zurück).
7. In der Kopfzeile „Aufgaben" bzw. „Familienmitglieder" lassen sich per Button nicht-fällige Aufgaben bzw. die Mitgliederliste ein-/ausblenden.

## Tests

Die Suite nutzt [pytest-homeassistant-custom-component](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component), das täglich gegen die aktuelle HA-Version gebaut wird – dafür wird **Python 3.13** benötigt (aktuelle HA-Mindestanforderung).

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements_test.txt
pytest
```

Abgedeckt sind: Config-Flow (Singleton-Setup), Storage-Collection-Validierung/-Merge-Verhalten, sowie Coordinator-Logik (Status-Berechnung, Rotation, Punktevergabe, Idempotenz von `complete_task`, `skip_task`, Overdue-Erkennung).

**Hinweis zur Verifikation während der Entwicklung:** Die reine Rekurrenz-/Perioden-Berechnung wurde standalone gegen mehrere Fälle (täglich, wöchentlich mit mehreren Wochentagen, Intervall-Tage vor/nach Ankerdatum) durchgerechnet. Die eigentliche pytest-Suite selbst konnte in der Entwicklungsumgebung nicht ausgeführt werden, da dort nur Python 3.10 verfügbar ist, HA aber Python 3.13 voraussetzt – jede verwendete HA-API (`StorageCollection`, `DataUpdateCoordinator`, `ConfigEntry.runtime_data`, `StaticPathConfig`, `MockConfigEntry` etc.) wurde stattdessen direkt gegen den aktuellen Home-Assistant-Quellcode abgeglichen. Vor dem ersten „richtigen" Feature-Ausbau bitte einmal lokal `pytest` laufen lassen.
