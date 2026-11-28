# Home Assistant und HACS

Die Integration liest nur zusammengefasste Statusdaten und kann keine Veranstaltungen oder Preise verändern.

1. In der Event-Preisliste unter **Verwaltung** den **Statustoken** kopieren. Das ist weder das Admin-Passwort noch ein GitHub-Token.
2. In HACS nach **Event-Preisliste** suchen und installieren. Bis zur Katalogaufnahme kann `https://github.com/ThomS263/event-preisliste` als benutzerdefiniertes Repository vom Typ **Integration** ergänzt werden.
3. Home Assistant neu starten und unter **Einstellungen → Geräte & Dienste → Integration hinzufügen** „Event-Preisliste“ wählen.
4. Serveradresse (z. B. `http://192.168.1.20:8090`) und Statustoken eintragen.

Angezeigt werden Erreichbarkeit, Version, Veranstaltungen, Angebote, Stände, Kartenpunkte und ausverkaufte Angebote.
