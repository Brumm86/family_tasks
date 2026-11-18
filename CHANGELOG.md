# Changelog

All notable changes to Family Tasks are documented here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [1.1.0] - 2026-11-18

### Geändert
- Kinder können eine selbst über die Favoriten angelegte Aufgabe wieder löschen („Löschen (ohne Abzug)“ in der Aufgabenliste), solange die Eltern sie noch nicht bestätigt haben. Es gibt dafür keinen Punktabzug; die zugehörige Bestätigungsaufgabe der Eltern wird mit gelöscht.
- Über die Favoriten angelegte Aufgaben tragen jetzt ihren Ersteller (`created_by_member_id`). Sie sind damit für den Ersteller und die Eltern sichtbar, für andere Kinder nicht.

### Neu
- WebSocket-Befehl `family_tasks/task/withdraw` (nur für den Ersteller der Aufgabe, kein Admin-Konto nötig).

## [1.0.0] - 2026-11-11

Erste stabile Version. Der Funktionsumfang entspricht dem bisherigen Entwicklungsstand; die Änderungshistorie vor 1.0.0 wird nicht fortgeführt.
