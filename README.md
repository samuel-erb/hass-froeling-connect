# Fröling Connect – Home Assistant Integration

Liest **alle** Werte deiner Fröling-Heizungsanlage über den (inoffiziellen)
Fröling-Connect-Cloud-Dienst aus und legt sie als Sensoren in Home Assistant an.

## Warum eine neue Integration?

Es gibt bereits [Layf21/hass-froeling-connect](https://github.com/Layf21/hass-froeling-connect).
Sie funktioniert gut für ältere Kessel (Generation `GEN_3200`), liefert aber
**keine Daten** für Anlagen der neuen Steuerungsgeneration `GEN_NXG`
(z. B. S5, S5 Dual, P5, S4 Turbo neuerer Bauart) – die zugrunde liegende API
ist für diese Generation komplett anders aufgebaut und wurde bisher nirgends
dokumentiert.

Diese Integration wurde gegen ein echtes S5-Dual-Konto reverse-engineered und
unterstützt **beide Generationen**:

- `GEN_3200` (ältere Lambdatronic/Touchtronic-Steuerungen)
- `GEN_NXG` (aktuelle Steuerungsgeneration, u. a. S5 Dual)

Statt einzelne Sensoren fest zu verdrahten, läuft ein generischer,
rekursiver Parser über die komplette API-Antwort jeder Komponente und
erkennt jeden Wert, egal wie tief verschachtelt. Dadurch werden wirklich
**alle** Werte gefunden – auch neue, die Fröling künftig per Firmware-Update
hinzufügt.

## Funktionsumfang

- Automatische Erkennung aller Anlagen (Facilities) im Konto
- Automatische Erkennung aller Komponenten je Anlage (Kessel, Heizkreise,
  Boiler/Brauchwasser, Pufferspeicher, Materiallager, Förderung, ...) als
  eigene Home-Assistant-Geräte
- Für jede Komponente werden alle gefundenen Werte als `sensor` (Zahl, Text,
  Auswahlliste/Enum) oder `binary_sensor` (Ja/Nein-Werte) angelegt
- Automatische Zuordnung von Gerätklasse/Einheit bei bekannten Einheiten
  (°C, %, h, t, kg)
- Re-Login bei abgelaufenem Token, HA-Reauth-Flow bei Passwortänderung

**Nur lesend.** Es werden aktuell keine Einstellungen verändert (kein
`number`/`select` zum Schreiben) – für `GEN_3200` wäre das technisch möglich,
für `GEN_NXG` ist der Schreib-Endpoint (noch) nicht verifiziert. Das kann bei
Bedarf ergänzt werden.

## Installation

### Über HACS (empfohlen)

1. HACS → drei Punkte oben rechts → *Benutzerdefinierte Repositories*
2. Dieses Repository als Typ *Integration* hinzufügen
3. "Fröling Connect" installieren, Home Assistant neu starten
4. Einstellungen → Geräte & Dienste → Integration hinzufügen → "Fröling Connect"
5. E-Mail und Passwort deines Fröling-Connect-Kontos eingeben (dieselben
   Zugangsdaten wie auf connect-web.froeling.com)

### Manuell

Den Ordner `custom_components/froeling_connect` in das
`custom_components`-Verzeichnis deiner Home-Assistant-Installation kopieren
und Home Assistant neu starten.

## Wie es funktioniert (technischer Hintergrund)

Fröling Connect hat keine offizielle/öffentliche API. Alle Endpunkte wurden
per Netzwerk-Mitschnitt aus `connect-web.froeling.com` ermittelt:

| Zweck | Endpoint |
|---|---|
| Login | `POST /connect/v1.0/resources/login` |
| Anlagenliste (beide Generationen) | `GET /connect/v1.0/resources/service/user/{userId}/facility` |
| Komponentenliste (GEN_3200) | `GET /fcs/v1.0/resources/user/{userId}/facility/{facilityId}/componentList` |
| Komponente (GEN_3200) | `GET /fcs/v1.0/resources/user/{userId}/facility/{facilityId}/component/{componentId}` |
| Komponentenliste (GEN_NXG) | `GET /fcs/v1.0/resources/user/{userId}/nxg/facility/{facilityId}/web/overview` |
| Komponente (GEN_NXG) | `GET /fcs/v1.0/resources/user/{userId}/nxg/facility/{facilityId}/web/component/{componentId}` |

Es gibt **keine** externe PyPI-Abhängigkeit – die Integration nutzt nur
`aiohttp`, das ohnehin Teil von Home Assistant ist. (Der PyPI-Paketname
`froeling-connect`, den die oben genannte Alternative referenziert, gehört
zu einem unabhängigen, zurückgezogenen Paket und funktioniert nicht als
Abhängigkeit.)

## Diagnose-Tool

`tools/diagnose_froeling.py` ist ein eigenständiges Skript (keine Home-Assistant-
Abhängigkeit), das sich bei Fröling Connect anmeldet und die Rohdaten aller
Anlagen/Komponenten in `diagnostics/` (lokal, per `.gitignore` ausgeschlossen)
speichert. Nützlich, um die Struktur für eine neue/unbekannte Anlagengeneration
zu untersuchen. Passwort wird interaktiv per `getpass` abgefragt, nirgends
gespeichert oder übertragen.

```
python3 tools/diagnose_froeling.py
```
