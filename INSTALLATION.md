# Installation auf CasaOS

## Einfache Installation über die Oberfläche

1. Die [CasaOS-Importdatei](https://raw.githubusercontent.com/ThomS263/event-preisliste/v0.5.1/Apps/EventPreisliste/docker-compose.yml) öffnen und den gesamten Inhalt kopieren.
2. In CasaOS **App Store → Custom Install** öffnen.
3. Oben rechts **Import** wählen, den YAML-Inhalt einfügen und bestätigen.
4. Optional als `EVENT_PUBLIC_URL` eine externe HTTPS-Adresse für öffentlich nutzbare QR-Codes eintragen. Im Heimnetz kann das Feld leer bleiben.
5. **Installieren** wählen und danach die Kachel **Event-Preisliste** öffnen.
6. Beim ersten Öffnen ein persönliches Adminpasswort festlegen. Es sind keine Terminalbefehle nötig.

Die Weboberfläche verwendet standardmäßig Port **8090**. Die Verwaltung befindet sich unter `/admin/login`.

## Wenn ein Host-Port belegt ist

Beim Start aus einem Git-Checkout verwendet die Compose-Datei fest den Host-Port 8090. Falls Docker noch `Bind for 0.0.0.0:8080 failed: port is already allocated` meldet, ist die lokale Compose-Datei veraltet. Führe `git pull --ff-only origin main` aus und starte den Container erneut. Ist auch 8090 belegt, ändere in `compose.yaml` links vom Doppelpunkt `8090` auf einen freien Host-Port. Öffne anschließend `http://SERVER-IP:8090/admin/login` beziehungsweise die Adresse mit deinem gewählten Port.

## Daten und Sicherung

CasaOS speichert Events, Preislisten und Pläne unter `/DATA/AppData/event-preisliste/data`. Diesen Ordner regelmäßig sichern und bei Updates nicht ändern.

## Aktualisieren – ohne Datenverlust

1. Im Admin-Panel unter **Sicherheit & Backup** vorher ein Backup herunterladen.
2. In CasaOS bei **Event-Preisliste → Einstellungen** das Docker-Image auf den Tag der [neuesten Version](https://github.com/ThomS263/event-preisliste/releases/latest) ändern, zum Beispiel `ghcr.io/thoms263/event-preisliste:0.5.1`.
3. **Speichern** beziehungsweise **Neu erstellen** wählen. CasaOS lädt das neue Image automatisch.
4. Die Kachel öffnen und unten in der Seitenleiste die Versionsnummer kontrollieren.

Dabei den Datenpfad `/DATA/AppData/event-preisliste/data`, den Container-Pfad `/data`, den Container-Port `8080` und den Host-Port `8090` unverändert lassen. Events, Preise, Pläne und Passwort bleiben erhalten.

### Installation aus einem Git-Checkout aktualisieren

```bash
cd /home/thomas/event-preisliste
git pull --ff-only origin main
docker compose up -d --build --wait
```

Danach zeigt `http://SERVER-IP:8090/health` die aktive Versionsnummer an.

## QR-Codes außerhalb des Heimnetzes

Für QR-Codes, die auch außerhalb des eigenen WLANs funktionieren sollen, wird eine öffentlich erreichbare HTTPS-Adresse benötigt. Diese in CasaOS als `EVENT_PUBLIC_URL` ohne zusätzlichen Pfad eintragen, beispielsweise `https://preise.example.org`.
