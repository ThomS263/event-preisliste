# Event-Preisliste – Wiki-Vorlage

> GitHub erzeugt das Wiki-Repository erst, nachdem unter **Wiki → Create the first page** einmal eine Seite gespeichert wurde. Als Titel `Home` und als Inhalt zunächst diese Seite verwenden. Danach können weitere Wiki-Seiten normal angelegt oder per Git übertragen werden.

## Übersicht

Event-Preisliste erstellt mobile Preislisten, Standübersichten, QR-Codes und interaktive Lagepläne für Adventmärkte, Feuerwehrfeste und andere Veranstaltungen.

- [Live-Sandbox](https://thoms263.github.io/event-preisliste/) – sichere Beispieldaten ohne Speicherung
- [CasaOS-Installation](../INSTALLATION.md)
- [Home Assistant und HACS](HOME_ASSISTANT.md)
- Aktuelle Version: **1.0.0**

## Schnellstart

1. [CasaOS-YAML öffnen](https://raw.githubusercontent.com/ThomS263/event-preisliste/v1.0.0/Apps/EventPreisliste/docker-compose.yml) und vollständig kopieren.
2. In CasaOS **App Store → Custom Install → Import** öffnen, YAML einfügen und installieren.
3. Die Kachel auf Port `8090` öffnen und beim ersten Start ein Admin-Passwort festlegen.
4. Veranstaltung, Stände und Preise anlegen, veröffentlichen und den QR-Code testen.

## Home Assistant

In der Verwaltung den nur lesbaren **Home-Assistant-Statustoken** kopieren. Das ist weder das Admin-Passwort noch ein GitHub-Token. Bis zur Katalogaufnahme kann `https://github.com/ThomS263/event-preisliste` in HACS als benutzerdefiniertes Repository vom Typ **Integration** ergänzt werden.

Die [offizielle HACS-Einreichung](https://github.com/hacs/default/pull/15141) wurde erstellt und hat die automatischen Katalogprüfungen bestanden. Die endgültige Aufnahme erfolgt nach Prüfung durch das HACS-Team.

## Häufige Probleme

- **Port belegt:** Nur den Host-Port ändern, z. B. `8091:8080`; der Container-Port bleibt `8080`.
- **QR-Code mit falscher Adresse:** `EVENT_PUBLIC_URL` auf eine erreichbare HTTPS-Adresse ohne Pfad setzen.
- **Home Assistant meldet ungültige Anmeldung:** Den Statustoken erneut kopieren, nicht das Admin-Passwort verwenden.
- **Container prüfen:** `docker compose ps` und `docker compose logs --tail 100 event-preisliste` ausführen.
