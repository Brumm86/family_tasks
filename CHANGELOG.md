# Changelog

All notable changes to Family Tasks are documented here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [1.2.0] - 2026-11-23

### Neu
- Vier Laptopzeit-Schwellen in den Optionen (`laptop_threshold_1_points` .. `laptop_threshold_4_points`, Wochenpunkte, 0 = aus). Schwelle 1 und 2 gewähren je 10 Minuten, Schwelle 3 und 4 je 20 Minuten (zusammen höchstens 60 Minuten). Gesetzte Schwellen müssen aufsteigend sein.
- Blueprint „Handyzeit-Verwaltung“: optionaler Helfer „Ausgleich - letzter Bedarf“ (`correction_pending_helper`). Der Ausgleich der Google-Fehlerfassung schreibt dann nur noch den Fehlbetrag gut, der bei zwei aufeinanderfolgenden 5-Minuten-Prüfungen bestanden hat (Minimum aus vorherigem und aktuellem Bedarf; die erste Prüfung des Tages schreibt nie gut). Ohne Helfer bleibt es bei der sofortigen Gutschrift.
- Unter dem Wochenfortschrittsbalken der Kinder steht an jeder gesetzten Schwelle ein Laptop-Symbol mit der gewährten Minutenzahl; erreichte Schwellen sind hervorgehoben. Die Punkte-Sensoren tragen dazu die Attribute `laptop_threshold_points` und `laptop_threshold_minutes`.

## [1.1.0] - 2026-11-18

### Geändert
- Kinder können eine selbst über die Favoriten angelegte Aufgabe wieder löschen („Löschen (ohne Abzug)“ in der Aufgabenliste), solange die Eltern sie noch nicht bestätigt haben. Es gibt dafür keinen Punktabzug; die zugehörige Bestätigungsaufgabe der Eltern wird mit gelöscht.
- Über die Favoriten angelegte Aufgaben tragen jetzt ihren Ersteller (`created_by_member_id`). Sie sind damit für den Ersteller und die Eltern sichtbar, für andere Kinder nicht.

### Neu
- WebSocket-Befehl `family_tasks/task/withdraw` (nur für den Ersteller der Aufgabe, kein Admin-Konto nötig).

## [1.0.0] - 2026-11-11

Erste stabile Version. Der Funktionsumfang entspricht dem bisherigen Entwicklungsstand; die Änderungshistorie vor 1.0.0 wird nicht fortgeführt.
