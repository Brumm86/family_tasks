# Family Tasks

Home-Assistant-Integration zur Verwaltung von Familien-Aufgaben: wiederkehrende Aufgaben mit Rotation, Punkte und Münzen, Wochenfortschritt, Belohnungs-Shop und Benachrichtigungen. Die Integration nutzt `config_flow`, `DataUpdateCoordinator` und Storage Collections (keine YAML-Integration) und bringt eine eigene Lovelace-Karte mit.

## Funktionen

### Aufgaben

- **Wiederholung**: täglich, wöchentlich (ein oder mehrere Wochentage), alle N Tage, jährlich, einmalig (wird nach Erledigung gelöscht) oder Sensor-Ereignis.
- **Fälligkeit und „Überfällig ab“** als feste Uhrzeit. Fehlt die Überfällig-Uhrzeit, gilt die Karenzzeit (Minuten) aus den Integrations-Optionen.
- **Zustände**: Inaktiv, Aktiv, Bald fällig (Fälligkeit in der laufenden Woche), Fällig, Überfällig, Wartet auf Bestätigung, Erledigt. Erledigt werden kann eine Aufgabe erst, wenn sie fällig ist.
- **Zuweisung**: „Fest zugewiesen“ (auch an mehrere Personen gleichzeitig) oder Rotation (`round_robin`, `random`, `least_points`; optional zählen nur die Punkte von Kindern).
- **Aufgabentypen**: „Standard“ und „Pflichtaufgabe“. Eine überfällige Pflichtaufgabe pausiert die automatische Handyzeitgewährung (siehe Handyzeit).
- **Checkliste** für jeden Aufgabentyp: Die Aufgabe gilt als erledigt, sobald alle Unterpunkte abgehakt sind. Eltern können sie auch direkt als erledigt markieren.
- **Punkte** und optional ein **Münzwert** pro Aufgabe, **Notiz** (Info-Symbol mit Dialog) und **Urlaubsmodus-Verhalten** („anzeigen“ oder „pausieren“).
- **Sensor-Ereignis**: Auslöser über einen Sensor-Zustand (optional mit „Vorherigem Zustand“) oder einen Schwellenwert (optional mit Sicherheitspuffer in Minuten). Optional wird eine `button.*`-Entity bei Erledigung gedrückt, und die Aufgabe kann sich selbst erledigen, sobald sich der Sensor normalisiert.
- **Kinder-Bestätigung**: Meldet ein Kind eine Aufgabe als erledigt, entsteht eine Bestätigungsaufgabe für die Eltern. Erst nach deren Bestätigung gibt es Punkte und Münzen und rotiert die Aufgabe weiter. Die Bestätigung lässt sich pro Aufgabe abschalten.
- **Aufgabenpool**: Eine Aufgabe ohne Zuweisung und ohne Rotation erscheint in einem eigenen Abschnitt. Jedes aktive Kind kann sie per „Annehmen“ reservieren, jeweils nur eine Aufgabe gleichzeitig. Wird sie innerhalb der Frist nicht erledigt (Standard 60 Minuten), gibt es einen Punktabzug (Standard 1 Punkt). Eltern können eine Reservierung ohne Abzug beenden.
- **Frist verlängern** (Eltern): verlängert nur die aktuell fällige Einzelaufgabe, nicht die Aufgabendefinition.
- **Favoriten**: wiederverwendbare Aufgaben-Vorlagen (Eltern). Kinder können einen Favoriten als bereits erledigt nachmelden, was ebenfalls durch die Eltern-Bestätigung läuft.
- **Batterien**: Batterie-Entities (`device_class: battery`) werden automatisch überwacht. Unterschreitet eine ihre Warnschwelle, entsteht eine Aufgabe für die Admin-Mitglieder. Einzelne Batterien lassen sich ausschließen oder bekommen eine eigene Schwelle. Optional erledigt sich die Aufgabe, sobald sich die Batterie erholt.
- **Urlaubsmodus**: haushaltsweiter Schalter (`switch`), der alle Aufgaben mit Verhalten „pausieren“ aussetzt.
- **Pause pro Mitglied**: ein pausiertes Mitglied bekommt keine neuen Aufgaben und nimmt nicht am Belohnungssystem teil. Bereits Verdientes bleibt erhalten.

### Punkte, Münzen und Belohnungen

- **Punkte** zählen für den **Wochenfortschritt**: pro Kind ein Balken mit Schwellen. Punkte sinken nie unter 0, und Punkte über der zweiten Münz-Schwelle werden zu Beginn der Folgewoche gutgeschrieben.
- **Münzen** sind die Währung des Belohnungs-Shops. Sie kommen aus dem Münzwert erledigter Aufgaben, dem Meilensteinbonus, dem Streak-Bonus, dem Wochensieger-Bonus und der manuellen Vergabe durch Eltern.
- **Meilensteinbonus**: Münzen, sobald ein Kind in der Woche die Münz-Schwelle 1 (Silber) bzw. 2 (Gold) erreicht.
- **Streak-Bonus**: Münzen für die zweite und ab der dritten Woche in Folge über Münz-Schwelle 2.
- **Wochensieger-Bonus**: Münzen für das Kind mit den meisten Wochenpunkten, sofern es auch sein Wochenziel erreicht hat (bei Gleichstand kein Bonus).
- **Belohnungs-Shop**: Eltern pflegen einen Katalog (Preis in Münzen). Bei einer Einlösung feuert das Event `family_tasks_reward_redeemed`, auf das eigene Automatisierungen reagieren können. Eine Belohnung kann sofort als erledigt gelten (`auto_fulfill`). Die Belohnung „Handyzeit“ trägt Minuten und kann alternativ vom Kind mit frei gewählten Münzen „investiert“ werden.
- **Spotify-Freigabe**: Option „Mindestpunktzahl der Vorwoche“ (0 = aus) und `binary_sensor.<name>_spotify_freigegeben` pro Kind.

### Handyzeit

Der Referenz-Blueprint [`blueprints/handyzeit_verwaltung.yaml`](blueprints/handyzeit_verwaltung.yaml) verwaltet die Bildschirmzeit über Google Family Link. Die Integration selbst spricht nicht mit Family Link.

- Der `binary_sensor` „Handyzeitgewährung aktiv“ pro Mitglied wird `aus`, solange eine zugewiesene Pflichtaufgabe überfällig ist oder auf Bestätigung wartet. Der Blueprint kann ihn zum Pausieren der automatischen Ticks nutzen.
- Der **Tick-Malus** richtet sich nach den Punkten der abgeschlossenen Vorwoche, mit vier einstellbaren Schwellen. Ab dem Wochenziel gibt es keinen Malus. Das Sensor-Attribut `screen_time_tick_adjustment_minutes` liefert den Wert an den Blueprint. Wann der Malus erstmals gilt, legt die Option „Handyzeit-Tick-Malus berücksichtigt ab (Datum)“ fest.
- Der Blueprint kann außerdem von Google zu Unrecht angerechnete Zeit ausgleichen und Spotify wochenweise freischalten. Die Eingänge dafür sind optional.
- Die Karte zeigt eine Schätzung der Handyzeit pro Tag, wenn „Handyzeit pro Tick“ und „Ticks pro Tag“ in den Optionen eingetragen sind. Diese beiden Werte müssen mit dem Blueprint übereinstimmen und werden nicht automatisch abgeglichen.

### Benachrichtigungen

Pro Mitglied lässt sich ein `notify`-Dienst hinterlegen (z. B. `mobile_app_pixel_8`). Ohne ihn erscheint eine `persistent_notification`. Benachrichtigt wird bei neu zugewiesenen Aufgaben, bei „fällig“ und bei „überfällig“ (jeweils einmal pro Periode und Mitglied) und bei jeder neuen Aufgabenpool-Aufgabe. Dieselben Anlässe feuern Events für eigene Automatisierungen: `family_tasks_task_assigned`, `family_tasks_task_due`, `family_tasks_task_overdue`, `family_tasks_task_pool_added`.

### Rechte

- Aufgaben, Mitglieder, Favoriten, Belohnungen und Einstellungen bearbeiten dürfen nur Home-Assistant-Administratoren.
- Ein Konto, das einem Mitglied mit Rolle „Kind“ zugeordnet ist, wird für Verwaltungsaktionen auch mit Admin-Rechten abgelehnt. Kinder sehen die Wochenfortschritte aller Kinder, aber nur die eigenen Aufgaben.
- Kinder können keine eigenen Aufgaben anlegen. Sie melden erledigte Favoriten nach, die von den Eltern freigegebene Vorlagen sind.

## Struktur

```
custom_components/family_tasks/
  __init__.py            Setup, Services, Frontend-Registrierung
  services.py            Administrative Services (CRUD, Punkte/Münzen, Einstellungen)
  config_flow.py         Setup und Options-Flow
  storage.py             Storage Collections (Aufgaben, Mitglieder, Favoriten, Belohnungen,
                         Batterie-Overrides, Einlösungen), Stores und Websocket-API
  coordinator.py         Status, Fälligkeit, Rotation, Punkte, Bonus- und Benachrichtigungslogik
  trigger.py             Sensor-Auslöser (Zustand, Schwellenwert mit Puffer)
  battery.py             Batterie-Erkennung und -Überwachung
  sensor.py, button.py, binary_sensor.py, switch.py   Entities
  www/family-tasks-card.js   Die Lovelace-Karte (ohne Build-Tools)
blueprints/handyzeit_verwaltung.yaml
tests/                   pytest-homeassistant-custom-component
```

## Installation

**Über HACS** (empfohlen): Dieses Repository als benutzerdefiniertes Repository (Kategorie „Integration“) hinzufügen und „Family Tasks“ installieren.

**Manuell**: `custom_components/family_tasks/` in das `custom_components`-Verzeichnis der Home-Assistant-Konfiguration kopieren.

Danach:

1. Home Assistant neu starten.
2. Einstellungen → Geräte & Dienste → Integration hinzufügen → „Family Tasks“.
3. Dashboard bearbeiten → Karte hinzufügen → „Family Tasks“ (oder `type: custom:family-tasks-card`). Die Karte registriert sich automatisch, eine manuelle Lovelace-Ressource ist nicht nötig.
4. In der Karte zuerst Familienmitglieder anlegen (optional mit `person.*`-Verknüpfung und Rolle „Kind“), danach Aufgaben.

## Konfiguration

Einstellungen → Geräte & Dienste → Family Tasks → Konfigurieren:

| Bereich | Optionen |
|---|---|
| Aufgaben | Karenzzeit bis „Überfällig“ (Minuten), Standard-Rotationsstrategie |
| Batterien | Standard-Warnschwelle (%), Alarm-Aufgaben bei Erholung automatisch erledigen |
| Wochenfortschritt | Wöchentliche Zielpunktzahl (0 = aus) |
| Münzen | Münz-Schwellen 1 und 2 (Punkte), Meilensteinbonus (Silber/Gold), Streak-Bonus (2 Wochen / ab 3 Wochen), Wochensieger-Bonus |
| Handyzeit | Handyzeit-Minuten pro investiertem Punkt (bei frei investierter Handyzeit-Belohnung), Minuten pro Tick, Ticks pro Tag, Malus-Schwellen 1–4 (Punkte), Beginn des Malus (Datum) |
| Spotify | Mindestpunktzahl der Vorwoche (0 = aus) |
| Urlaubsmodus | Anfangszustand des Schalters |

Die Schwellen müssen aufsteigend sein: Malus 1 < 2 < 3 < 4 < Wochenziel < Münz-Schwelle 1 < 2. Nicht gesetzte Schwellen werden aus dem Wochenziel abgeleitet.

## Services

Die Aktionen sind unter Entwicklerwerkzeuge → Aktionen beschrieben (`services.yaml`).

- **Aufgaben im Alltag**: `complete_task`, `skip_task`, `toggle_subtask`, `claim_task`, `release_task`, `reset_points`.
- **Verwaltung** (nur Admin): `create_/update_/delete_` jeweils für `task`, `member`, `favorite`, `reward` und `battery_override`.
- **Lesen**: `list_tasks`, `list_members`, `list_favorites`, `list_rewards`, `list_battery_overrides`, `list_reward_redemptions`, `get_settings`.
- **Weitere**: `instantiate_favorite`, `award_points`, `award_coins`, `extend_task_deadline`, `fulfill_reward_redemption`, `update_settings`.

Die Services nutzen dieselben Schemas und Storage Collections wie die Karte. Aufrufe ohne Benutzer (Automatisierung, Skript) sind erlaubt.

## Entities

- Pro Aufgabe ein Status-Sensor und ein Button „Erledigt“.
- Pro Mitglied ein Punkte-Sensor (mit Wochenfortschritt-Attributen), ein Münzen-Sensor, ein Sensor „Offene Aufgaben“, `binary_sensor` „Handyzeitgewährung aktiv“ und `binary_sensor` „Spotify freigegeben“.
- Haushaltsweit ein Sensor „Aufgabenpool“ (Anzahl offener Pool-Aufgaben) und der Schalter „Urlaubsmodus“.

## Tests

Die Suite nutzt [pytest-homeassistant-custom-component](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component), das täglich gegen die aktuelle Home-Assistant-Version gebaut wird. Dafür wird **Python 3.13** benötigt.

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements_test.txt
pytest
```

Abgedeckt sind der Config-Flow, die Storage-Collections samt Validierung, die Coordinator-Logik (Status, Rotation, Punkte und Münzen, Boni, Benachrichtigungen), der Kind-Bestätigungs-Workflow, Berechtigungen, Sensor-Auslöser, Batterie-Überwachung und die administrativen Services.
