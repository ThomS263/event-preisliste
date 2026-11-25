# Event-Preisliste

Eine selbst gehostete, mobilfreundliche Preisliste für Adventmärkte, Feuerwehrfeste, Vereinsfeste und andere Veranstaltungen. Für jedes Event wird eine eigene öffentliche Seite mit QR-Code erzeugt.

## Funktionen

- mehrere Veranstaltungen getrennt verwalten
- Titel, Untertitel, Datum, Ort und Farbe pro Event
- Artikel nach Kategorien mit Beschreibung und Europreis
- Event zunächst als Entwurf vorbereiten und später veröffentlichen
- eigener QR-Code zum Herunterladen und Ausdrucken
- interaktiver Geländeplan mit hochgeladenem Planbild und anklickbaren Punkten für Stände, Essen, Getränke, WC, Eingang, Information und Erste Hilfe
- große, schnelle Handyansicht ohne App und ohne externe Schriftarten
- persistente SQLite-Daten im Docker-Volume
- Adminbereich mit Passwort, Same-Origin-Schutz und Sicherheitsheadern
- zentrales Admin-Panel mit Übersicht, Eventbearbeitung, Öffnungszeiten, Preisbearbeitung, Ausverkauft-Status, Kennzeichnungen und Allergenen
- Docker-Healthcheck und eingeschränkte Containerrechte

## Schnellstart

```bash
git clone https://github.com/ThomS263/event-preisliste.git
cd event-preisliste
cp .env.example .env
# In .env unbedingt ein eigenes starkes Adminpasswort setzen.
docker compose up -d --build --wait
```

Danach `http://SERVER-IP:8080/admin/login` öffnen, anmelden und das erste Event erstellen. Für korrekte QR-Codes außerhalb des Heimnetzes in `.env` eine erreichbare HTTPS-Adresse als `EVENT_PUBLIC_URL` eintragen.

## Aktualisieren

```bash
cd event-preisliste
git pull --ff-only origin main
docker compose up -d --build --wait
```

Die Daten liegen im lokalen Verzeichnis `data/` und bleiben bei Updates erhalten. Vor Updates diesen Ordner sichern.

## Entwicklung und Tests

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q
```

## Interaktiven Plan einrichten

1. Veranstaltung in der Verwaltung öffnen.
2. Unter **Interaktiver Plan** ein PNG-, JPEG- oder WebP-Bild bis 2 MB hochladen.
3. Auf die gewünschte Position im Plan tippen.
4. Name, Art und Beschreibung eingeben und **Punkt hinzufügen** wählen.
5. Auf der öffentlichen Eventseite können Gäste die nummerierten Punkte antippen.

## Admin-Panel

Unter `/admin/login` werden alle Veranstaltungen zentral verwaltet. Das Dashboard zeigt Events, veröffentlichte Events, Artikel und Planpunkte. In jedem Event gibt es Bereiche für Eventdaten, Preise, Plan und QR-Code. Artikel können nachträglich geändert, als ausverkauft markiert und mit Kennzeichnungen wie `vegan` sowie Allergencodes versehen werden.

## Geplante nächste Schritte

- Events und bestehende Artikel vollständig bearbeiten
- Artikel als „ausverkauft“ markieren
- optionale Bilder und Logos pro Event
- mehrsprachige Preislisten
- Druckansicht für QR-Code-Schilder
- CasaOS-Installationspaket

## Lizenz

GNU Affero General Public License v3.0 (`AGPL-3.0-only`).
