# Installation auf CasaOS

## Einfache Installation über die Oberfläche

1. Die [CasaOS-Importdatei](https://raw.githubusercontent.com/ThomS263/event-preisliste/v0.3.0/Apps/EventPreisliste/docker-compose.yml) öffnen und den gesamten Inhalt kopieren.
2. In CasaOS **App Store → Custom Install** öffnen.
3. Oben rechts **Import** wählen, den YAML-Inhalt einfügen und bestätigen.
4. Optional unter den Umgebungsvariablen ein eigenes `EVENT_ADMIN_PASSWORD` und eine externe HTTPS-Adresse als `EVENT_PUBLIC_URL` eintragen.
5. **Installieren** wählen und danach die Kachel **Event-Preisliste** öffnen.

Die Weboberfläche verwendet standardmäßig Port **8090**. Die Verwaltung befindet sich unter `/admin/login`.

Wurde kein Adminpasswort gesetzt, im CasaOS-Terminal auslesen:

```bash
docker exec event-preisliste cat /data/.initial-admin-password
```

## Daten und Sicherung

CasaOS speichert Events, Preislisten und Pläne unter `/DATA/AppData/event-preisliste/data`. Diesen Ordner regelmäßig sichern und bei Updates nicht ändern.

## Aktualisieren

Bei einer neuen Version in den CasaOS-App-Einstellungen den Image-Tag auf die neue veröffentlichte Version ändern und den Container neu erstellen. Datenpfad `/data`, Container-Port `8080` und Host-Port `8090` beibehalten.

## QR-Codes außerhalb des Heimnetzes

Für QR-Codes, die auch außerhalb des eigenen WLANs funktionieren sollen, wird eine öffentlich erreichbare HTTPS-Adresse benötigt. Diese in CasaOS als `EVENT_PUBLIC_URL` ohne zusätzlichen Pfad eintragen, beispielsweise `https://preise.example.org`.
