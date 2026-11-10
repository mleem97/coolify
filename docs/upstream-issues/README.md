# Coolify: Aufarbeitung und Import der ausgewählten Upstream-Issues

**Stand: 10. November 2026.** Ziel: `mleem97/coolify`. Geprüfter Code: [`30335d80866f`](https://github.com/mleem97/coolify/commit/30335d80866ff3391d899cf4ccb599b696f47b7e), laut `release.json` stabile Version **4.7.3**.

Dieses Paket enthält die individuelle Aufarbeitung aller **95 offenen Issues** aus dem gewünschten Filter: Problemabgrenzung, Reproduktionsszenario, konkrete Codebefunde, Umsetzungsschritte, Abnahmekriterien, offene Fragen und Quellen. Dazu kommen die Originalbeschreibungen und sämtliche **429 abrufbaren Kommentartexte**.

Die Arbeit ist eine statische Bestandsaufnahme und ein ausführbarer Import. Sie enthält **keine Behebung der 95 Produktmeldungen** und keine Behauptung, diese seien auf einem laufenden Coolify reproduziert worden. Vor einem Produktfix sind die im jeweiligen Dossier beschriebenen Tests auszuführen.

## Schnellstart

Voraussetzungen: Python 3.10 oder neuer, [GitHub CLI](https://cli.github.com/) und Anmeldung als `mleem97`. GitHub-Konto: `mleem97`. Die verfügbare GitHub-Verbindung verwendet für API-Commits `52848568+mleem97@users.noreply.github.com`; eine abweichende Commit-E-Mail lässt sich über diese Verbindung nicht setzen. Die gewünschte Adresse `marvinleede@gmail.com` ist für lokale Git-Commits vorgesehen. Wer Issues erstellt, bestimmt ausschließlich die GitHub-Anmeldung.

Falls noch keine CLI-Anmeldung besteht:

```bash
gh auth login --hostname github.com --git-protocol https --web
```

Im Checkout dieses Branches den vorbereiteten Bestand importieren:

```bash
python3 scripts/import-upstream-issues.py --apply --enable-issues
```

Der Aufruf aktiviert bei Bedarf die Issues-Funktion im Ziel und erstellt die vorbereiteten Kopien. Ohne `--apply` zeigt das Programm nur den geplanten Import. Der Standardbestand ist der mitgelieferte Snapshot vom 10. November 2026. Spätere Änderungen in Upstream werden bei diesem Aufruf nicht automatisch in die Aufarbeitung übernommen.

```bash
# Rein lokale Prüfung; benötigt keine GitHub-Anmeldung und schreibt nichts auf GitHub.
python3 scripts/import-upstream-issues.py --validate-snapshot

# Probelauf mit Prüfung von Identität, Zielrepository und vorhandenen Importen.
python3 scripts/import-upstream-issues.py

# Bewusster Import des dann aktuellen Filters; neue Meldungen haben keine individuelle Aufarbeitung.
python3 scripts/import-upstream-issues.py --live --apply --enable-issues
```

## Verhalten des Imports

- Quelle ist fest `coollabsio/coolify`, Zielstandard `mleem97/coolify`. Der Client schreibt ausschließlich am gewählten Ziel und prüft zuvor den tatsächlich angemeldeten Benutzer. Ein bewusstes anderes `--target` ist nur innerhalb des Kontos `mleem97` möglich; der vorbereitete Snapshot ist an `mleem97/coolify` gebunden.
- Originaltitel, Quellen-IDs, Autor und Zeitstempel, Labels, Originaltext, Diskussion und die individuelle Aufarbeitung bleiben nachvollziehbar. Neue Issues bekommen neue Nummern und werden von `mleem97` erstellt. Original-Autorschaft und ursprüngliche Erstellungsdaten lassen sich nicht als echte GitHub-Metadaten übernehmen.
- Originaltexte werden als wörtliche Markdown-Quelltexte dargestellt. Darin vorhandene Mention- und Issue-Syntax wird nicht zu neuen Benachrichtigungen oder falschen Fork-Referenzen. Quellen sind separat verlinkt. Lange Inhalte werden auf markierte Fortsetzungskommentare verteilt.
- Der Importer gleicht stabile Herkunftsmarker mit **offenen und geschlossenen** Ziel-Issues ab. Ein Wiederanlauf ergänzt fehlende Teile; vorhandene Texte und Label-Farben bleiben erhalten. Bestehende geschlossene Issues werden nicht wieder geöffnet.
- Herkunftsmarker am Anfang importierter Issues und Fortsetzungskommentare müssen erhalten bleiben, damit Wiederanläufe die Zuordnung erkennen.
- Die lokale Sperre schützt vor zwei Läufen auf demselben Rechner. Nicht gleichzeitig von mehreren Rechnern importieren. Nach einem unklaren POST-Ausgang wird keine blinde Wiederholung gestartet; der nächste Lauf gleicht den Zielbestand erneut ab.
- Bei `--live --apply` wird vor der ersten Mutation ein redigierter lokaler Snapshot mit Dateimodus `0600` gesichert und der genaue Wiederaufnahmebefehl angezeigt.
- Schreibzugriffe erfolgen seriell mit mindestens acht Sekunden Abstand. GitHub kann darüber hinaus drosseln. Bei einer Limit-Antwort nennt der Importer den nächsten zulässigen Versuch; den Befehl anschließend erneut starten.
- Assignees und Milestones werden nur als Herkunft dokumentiert. Niemand aus dem Quellrepository wird automatisch dem Fork zugewiesen.

Ein echter GitHub-Transfer setzt denselben Repository-Eigentümer sowie Schreibzugriff auf Quelle und Ziel voraus. Deshalb verwendet dieses Paket die dokumentierten Create-Endpunkte für nachvollziehbare Kopien. [GitHub: Issue-Transfer](https://docs.github.com/en/issues/tracking-your-work-with-issues/administering-issues/transferring-an-issue-to-another-repository)

## Umfang und Quellenqualität

- 95 offene Issues; Filter unabhängig durch fünf REST-Label-Abfragen verifiziert. Die Labels sind ODER-verknüpft; Pull Requests wurden ausgeschlossen.
- 429 abrufbare Kommentartexte gegenüber 431 laut Issue-Zählern. Bei #7642 sind 42 von 44 gezählten Kommentaren abrufbar; auch eine erneute Abfrage und eine leere Folgeseite lösen die Differenz nicht auf. Ursache unbekannt.
- Erkannte Tokenwerte und private Schlüssel wurden vor Veröffentlichung redigiert. Die unveränderten Originale sind nur über die jeweiligen Quellverweise erreichbar.
- Anhänge und Bilder werden per Original-URL referenziert. Externe Downloads und Bildinhalte wurden nicht archiviert oder visuell geprüft.
- Eine Codeanalyse ist keine Laufzeitreproduktion. In diesem Paket wurden keine Änderungen am Coolify-Produktcode vorgenommen.

Die ursprüngliche Suche ist:

```text
repo:coollabsio/coolify is:issue is:open label:"🔍 Triage","🖌️ UI/UX","🐛 Possible Bug","🔴 High Priority","🟠 Medium Priority"
```

| Filterlabel | Offene Issues im Snapshot |
| --- | ---: |
| 🔍 Triage | 83 |
| 🖌️ UI/UX | 3 |
| 🐛 Possible Bug | 84 |
| 🔴 High Priority | 1 |
| 🟠 Medium Priority | 0 |

Die Label-Zahlen überlappen. Ihre Vereinigungsmenge umfasst 95 Issues. Die Abfrage nach UI/UX lieferte zusätzlich einen Pull Request, der korrekt ausgeschlossen wurde.

## Bewertungsmaßstab

| Bewertung | Bedeutung | Anzahl |
| --- | --- | ---: |
| Konkreter Codebefund | Das gemeldete Verhalten oder eine konkrete Diskrepanz ist im geprüften Code sichtbar; ein Ende-zu-Ende-Nachweis steht aus. | 20 |
| Möglicherweise bereits adressiert | Im aktuellen Code existiert ein passender Fix oder eine Gegenmaßnahme. Die ursprüngliche Variante muss gezielt nachgetestet werden. | 17 |
| Reproduktion erforderlich | Meldung plausibel, Ursache oder heutige Betroffenheit aus Quelltext und Diskussion noch nicht gesichert. | 43 |
| Erweiterung | Gewünschte Funktion oder Verbesserung mit eigenständigem Funktionsumfang. | 10 |
| Integration / Dokumentation | Schwerpunkt auf Integration, Fremdkomponente, Konfiguration oder Dokumentation. | 5 |

**Prioritäten sind eine Arbeitsreihenfolge für diesen Fork, keine CVSS-Einstufung und keine Übernahme der Upstream-Priorität.** P1: Zugriffsschutz, Daten-/Backup-Zuverlässigkeit oder erhebliche Betriebsbeeinträchtigung zuerst prüfen (28). P2: übrige Funktionsfehler und Betriebsverbesserungen (63). P3: nachrangige Bedienung, Darstellung oder Ausbau (4). Es werden weder Laufzeit noch notwendige externe Testumgebungen aus dem Prioritätswert abgeleitet.

## Empfohlene Bearbeitungsreihenfolge

1. **Spezifische Codebefunde mit hoher Auswirkung reproduzieren.** Preview-Labels ([#2806](issues/2806.md)), erzwungene Service-Deployments ([#5318](issues/5318.md)), PostgreSQL-Backup-Authentifizierung ([#5325](issues/5325.md)) und CA-Dateien bei Aktualisierungen ([#6081](issues/6081.md)) bekommen jeweils einen abgegrenzten Regressionstest vor der Änderung.
2. **Zusammenhängende Fehler gemeinsam untersuchen.** Compose-/Preview-Pfade, Environment-Serialisierung, Backup-Zugangsdaten und Proxy-Routing jeweils als Arbeitsbereich prüfen. Die einzelnen Issues und Abnahmekriterien bleiben erhalten, bis Gleichursächlichkeit belegt ist.
3. **Möglicherweise bereits adressierte Meldungen nachtesten.** Auf dem tatsächlich betriebenen Stand und mit der jeweiligen Reporter-Konfiguration prüfen. Nur einen nachgewiesenen Fix als erledigt markieren.
4. **Kleine, klar abgrenzbare API-/Dokumentationsabweichungen korrigieren.** Beispielsweise Response-Schema [#5874](issues/5874.md) und Proxy-Schema [#5572](issues/5572.md); das tatsächliche Laufzeitformat bleibt Maßstab.
5. **Vorlagen und externe Integrationen mit echten Zielkomponenten prüfen.** Datenbank-, Mail- und Logging-Stacks benötigen jeweils eigene Integrationsnachweise. Erweiterungen werden anschließend separat geplant.

Die genaue Reproduktion, die betroffenen Codepfade und die notwendigen Abnahmen stehen in jedem der folgenden Dossiers.

## Alle 95 Issues

| Upstream / Dossier | Aufgearbeiteter Titel | Priorität | Bewertung | Bereich |
| --- | --- | --- | --- | --- |
| [#2806](issues/2806.md) | Benutzerdefinierte Schutz- und Logging-Labels in PR-Vorschauen erhalten | P1 | Konkreter Codebefund | Preview / Proxy |
| [#3226](issues/3226.md) | Periodische CPU-Spitzen nach Wartungs- und SSH-Aufgaben eingrenzen | P1 | Reproduktion erforderlich | Server / Performance |
| [#3436](issues/3436.md) | IPv6-Clientadressen am Proxy-Eingang korrekt erhalten | P1 | Konkreter Codebefund | Proxy / Netzwerk |
| [#4448](issues/4448.md) | Build- und Deployment-Server eindeutig zuordnen | P1 | Reproduktion erforderlich | Deployment / Serverwahl |
| [#4490](issues/4490.md) | Berechtigungen erzeugter Bind-Dateien bei Compose-Änderungen erhalten | P1 | Reproduktion erforderlich | Dateispeicher / Berechtigungen |
| [#4519](issues/4519.md) | Eigene PostgreSQL-Konfiguration lesbar bereitstellen | P1 | Möglicherweise bereits adressiert | Datenbank / PostgreSQL |
| [#5045](issues/5045.md) | Vaultwarden-Adminhash unverändert durch die ENV-Verarbeitung führen | P1 | Reproduktion erforderlich | Service-Template / Secrets |
| [#5151](issues/5151.md) | Compose-Datei des PR-Commits für Vorschauen verwenden | P1 | Konkreter Codebefund | Preview / Compose |
| [#5318](issues/5318.md) | force-Deployment für Services an den Image-Pull weitergeben | P1 | Konkreter Codebefund | API / Deployment |
| [#5325](issues/5325.md) | Supabase-PostgreSQL-Sicherungen mit korrekter Authentifizierung ausführen | P1 | Konkreter Codebefund | Backup / PostgreSQL |
| [#5434](issues/5434.md) | Git-Quellen nach Wiederherstellung und Neustart vollständig nutzbar machen | P1 | Reproduktion erforderlich | Backup / Wiederherstellung |
| [#5571](issues/5571.md) | S3-Backup bei angepassten Mount- und Backup-Pfaden prüfen | P1 | Reproduktion erforderlich | Backup / S3 |
| [#5574](issues/5574.md) | Supabase-PostgreSQL mit SSL und richtigem Konfigurationspfad starten | P1 | Reproduktion erforderlich | Datenbank / PostgreSQL |
| [#5706](issues/5706.md) | MySQL-/MariaDB-Backups mit zufälligem Root-Passwort und BookStack-Zugangsdaten absichern | P1 | Reproduktion erforderlich | Datenbanken und Backups |
| [#5896](issues/5896.md) | Veraltete Buildserver-Einstellung beim Wechsel zu Docker Compose neutralisieren | P1 | Konkreter Codebefund | Buildserver und Compose |
| [#5921](issues/5921.md) | Compose-Includes vor der Coolify-Verarbeitung vollständig auflösen | P1 | Konkreter Codebefund | Compose-Parser |
| [#5990](issues/5990.md) | Laufende BookStack-MariaDB wird fälschlich als beendet angezeigt | P1 | Reproduktion erforderlich | Containerstatus und Backups |
| [#6070](issues/6070.md) | Compose-Previews mit mehreren Dateien und stabilen Servicenamen ermöglichen | P1 | Konkreter Codebefund | Compose-Previews |
| [#6081](issues/6081.md) | CA-Datei bei Updates erhalten, damit laufende Nicht-Root-Container sie weiter lesen können | P1 | Konkreter Codebefund | TLS, Dateien und Upgrade |
| [#6097](issues/6097.md) | Geplante Tasks nicht allein durch einen Anwendungsdeploy erneut ausführen | P1 | Reproduktion erforderlich | Scheduler |
| [#6285](issues/6285.md) | Periodische CPU-Spitzen nach Scheduler-, SSH- und UI-Arbeit aufschlüsseln | P1 | Reproduktion erforderlich | Performance / Scheduler / Horizon |
| [#6325](issues/6325.md) | Bestehende WebSocket-Verbindungen während des Deployment-Builds erhalten | P1 | Reproduktion erforderlich | Caddy / WebSockets / Rolling Deployment |
| [#6422](issues/6422.md) | SSH-Handshakefehler mit vollständigen und nachvollziehbaren Retries behandeln | P1 | Reproduktion erforderlich | SSH / Deployment / Wiederholungen |
| [#6571](issues/6571.md) | Externe Pull-Request-Previews vor dem Build gezielt freigeben | P1 | Erweiterung | GitHub / Preview-Deployments / Freigaben |
| [#6579](issues/6579.md) | Deployments ohne Fortschritt nach Worker-, Queue- und Ressourcenfehlern auflösen | P1 | Reproduktion erforderlich | Deployment / Queue / Worker |
| [#6656](issues/6656.md) | Speicherspitzen bei gecachten Next.js-Builds messen und begrenzen | P1 | Reproduktion erforderlich | Build / Next.js / Ressourcen |
| [#9623](issues/9623.md) | Wildcard-Routing abhängig von der tatsächlich laufenden Traefik-Version prüfen | P1 | Möglicherweise bereits adressiert | Proxy / Traefik / Wildcard-Domains |
| [#9643](issues/9643.md) | Verschlüsselte HTTP-Basic-Auth-Passwörter ohne varchar-Überlauf speichern | P1 | Konkreter Codebefund | Datenbankschema / HTTP Basic Auth / Migration |
| [#3292](issues/3292.md) | Compose-Vorschauen mit langen YAML-Strukturen ohne Typfehler parsen | P2 | Reproduktion erforderlich | Compose / Preview |
| [#3718](issues/3718.md) | Appwrite-Funktionsdomains und Wildcard-Routing abstimmen | P2 | Reproduktion erforderlich | Service-Template / Appwrite |
| [#3731](issues/3731.md) | Abmelden und Einladungslinks trotz erzwungenem Passwortwechsel erlauben | P2 | Möglicherweise bereits adressiert | Authentifizierung |
| [#4252](issues/4252.md) | Private Git-Submodule mit GitHub-App-Zugangsdaten klonen | P2 | Reproduktion erforderlich | Git-Quellen |
| [#4313](issues/4313.md) | HTTP-Notzugang und HTTPS-Sitzung verständlich behandeln | P2 | Integration / Dokumentation | Authentifizierung / Cookies |
| [#4314](issues/4314.md) | Neustart-Logs hinter Caddy und vorgeschaltetem Proxy erhalten | P2 | Reproduktion erforderlich | Proxy / Livewire |
| [#4402](issues/4402.md) | Private CA für S3-Verbindungen gezielt vertrauen | P2 | Erweiterung | S3 / TLS |
| [#4468](issues/4468.md) | Relative Compose-Pfade an der richtigen Basis auflösen | P2 | Reproduktion erforderlich | Compose / Dateispeicher |
| [#4595](issues/4595.md) | Mehrzeilige Shared-Variablen ohne Formatverlust auflösen | P2 | Reproduktion erforderlich | Umgebungsvariablen |
| [#4604](issues/4604.md) | GHCR-Zugangsdaten beim tatsächlichen Docker-Ausführer verwenden | P2 | Reproduktion erforderlich | Registry / Deployment |
| [#4675](issues/4675.md) | CSP- und andere quotierte ENV-Werte verlustfrei serialisieren | P2 | Reproduktion erforderlich | Umgebungsvariablen |
| [#4722](issues/4722.md) | Domains für Compose-Dienste mit Inline-Dockerfile speichern | P2 | Möglicherweise bereits adressiert | Compose / Oberfläche |
| [#4734](issues/4734.md) | Führende und abschließende Leerzeichen in ENV-Werten erhalten | P2 | Konkreter Codebefund | Umgebungsvariablen |
| [#4787](issues/4787.md) | Verwaiste Preview-Zertifikate und fehlerhafte Preview-Hosts unterscheiden | P2 | Reproduktion erforderlich | Proxy / ACME |
| [#4849](issues/4849.md) | Authentik-Ersteinrichtung über den richtigen internen Port routen | P2 | Möglicherweise bereits adressiert | Service-Template / Authentik |
| [#4850](issues/4850.md) | 413-Antwort bei großen Uploads der richtigen Schicht zuordnen | P2 | Integration / Dokumentation | Service / Uploads |
| [#4961](issues/4961.md) | Verschachtelte Compose-Defaults und Variablen in Mount-Pfaden korrekt auswerten | P2 | Reproduktion erforderlich | Compose / Umgebungsvariablen |
| [#5030](issues/5030.md) | Dienstidentität und Backupfähigkeit bei Imagewechsel erhalten | P2 | Reproduktion erforderlich | Service / Datenbank-Erkennung |
| [#5084](issues/5084.md) | Erhaltenes Repository im richtigen Preview-Verzeichnis ablegen | P2 | Möglicherweise bereits adressiert | Preview / Dateispeicher |
| [#5184](issues/5184.md) | Plunk-Erststart, Registrierung und Erreichbarkeit reproduzierbar prüfen | P2 | Reproduktion erforderlich | Service-Template / Plunk |
| [#5297](issues/5297.md) | Arch-Derivate anhand unterstützter Plattformmerkmale erkennen | P2 | Konkreter Codebefund | Installation |
| [#5327](issues/5327.md) | New-Relic-Logdrain über die gesamte Kette diagnostizierbar machen | P2 | Reproduktion erforderlich | Logging / Observability |
| [#5334](issues/5334.md) | Schlüssellöschung mit funktionierendem Bestätigungsdialog prüfen | P2 | Reproduktion erforderlich | Sicherheit / Oberfläche |
| [#5336](issues/5336.md) | Cachefreie Deployments über alle Buildpfade verifizieren | P2 | Möglicherweise bereits adressiert | Build / Cache |
| [#5364](issues/5364.md) | Mehrere GitHub-App-Installationen in der Quellenwahl unterstützen | P2 | Erweiterung | Git-Quellen / GitHub |
| [#5372](issues/5372.md) | GitLab-Webhooks mehrerer Anwendungen desselben Repositories richtig zuordnen | P2 | Möglicherweise bereits adressiert | Webhooks / GitLab |
| [#5563](issues/5563.md) | Authentik-ForwardAuth-Anleitung mit reproduzierbarer Konfiguration erneuern | P2 | Integration / Dokumentation | Dokumentation / Authentik |
| [#5624](issues/5624.md) | Root-Benutzeranlage aus ENV validieren und Fehler sichtbar machen | P2 | Möglicherweise bereits adressiert | Installation / Authentifizierung |
| [#5626](issues/5626.md) | GitHub-Quelleneinrichtung ohne gültige öffentliche Instanzadresse abfangen | P2 | Reproduktion erforderlich | Git-Quellen / Onboarding |
| [#5640](issues/5640.md) | Globale Caddy-Konfiguration dauerhaft und validiert verwalten | P2 | Konkreter Codebefund | Proxy / Caddy |
| [#5698](issues/5698.md) | Backupretention und verwaiste Dumpdateien nachvollziehbar behandeln | P2 | Reproduktion erforderlich | Backup / Aufbewahrung |
| [#5725](issues/5725.md) | Git-LFS-Downloads mit einer auf dem Server installierten privaten CA prüfen | P2 | Möglicherweise bereits adressiert | Git und TLS |
| [#5748](issues/5748.md) | Neustart darf vorhandene Dockerfile-Images nicht unnötig neu bauen | P2 | Reproduktion erforderlich | Deployment und Neustart |
| [#5798](issues/5798.md) | Leere Seite nach Sidebar-Navigation nach Transportfehler und JavaScript-Doppelinitialisierung trennen | P2 | Reproduktion erforderlich | Dashboard und Navigation |
| [#5874](issues/5874.md) | OpenAPI-Schema der Deployment-Liste an die tatsächliche Antwort anpassen | P2 | Konkreter Codebefund | API und Dokumentation |
| [#5878](issues/5878.md) | Deaktiviertes Auto-Deploy muss Git-Webhooks für Compose-Anwendungen stoppen | P2 | Möglicherweise bereits adressiert | Git-Webhooks |
| [#5880](issues/5880.md) | Echte Zeilenumbrüche und wörtliche Backslash-n in Umgebungsvariablen verlustfrei erhalten | P2 | Reproduktion erforderlich | Umgebungsvariablen |
| [#5914](issues/5914.md) | Gespeicherte PostgreSQL-Host-Authentifizierung an den Container übergeben | P2 | Konkreter Codebefund | Datenbankkonfiguration |
| [#6000](issues/6000.md) | CloudBeaver-Tabellen bleiben nach WebSocket-Abbruch hinter Caddy hängen | P2 | Reproduktion erforderlich | Servicevorlagen und WebSockets |
| [#6003](issues/6003.md) | Ungültige Domain darf Compose-Domainfelder nicht unbedienbar machen | P2 | Möglicherweise bereits adressiert | Formularvalidierung und Domains |
| [#6094](issues/6094.md) | Chaskiq-Vorlage mit kontrollierter Initialisierung und gültiger WebSocket-URL bereitstellen | P2 | Reproduktion erforderlich | Servicevorlagen |
| [#6122](issues/6122.md) | Lokale Docker-Images ohne erzwungenen Registry-Pull deployen | P2 | Konkreter Codebefund | Docker-Images |
| [#6138](issues/6138.md) | Logs nach externer Container-Umbenennung anhand der Ressourcenzuordnung wiederfinden | P2 | Möglicherweise bereits adressiert | Logs und Containerzuordnung |
| [#6148](issues/6148.md) | Doppelte Label-Editoren und überdeckte Bedienelemente nach Navigation verhindern | P2 | Reproduktion erforderlich | UI und Editor-Lifecycle |
| [#6159](issues/6159.md) | GitLab-Service nach Umstellung auf HTTPS mit Schema- und Serverfehlern prüfen | P2 | Reproduktion erforderlich | Service-Template / GitLab / TLS |
| [#6161](issues/6161.md) | Abschlusszeit bei Deployment-Timeouts zuverlässig speichern | P2 | Konkreter Codebefund | Deployment / Status / Zeitmessung |
| [#6296](issues/6296.md) | GitHub-Ratelimits von fehlendem Repositoryzugriff unterscheiden | P2 | Konkreter Codebefund | GitHub-Integration / API / Fehlermeldungen |
| [#6375](issues/6375.md) | Änderungen an benutzerdefinierten Containerlabels beim Speichern erhalten | P2 | Reproduktion erforderlich | Anwendungsformular / Monaco / Containerlabels |
| [#6395](issues/6395.md) | Compose-Profile, benutzerdefinierte Befehle und Dollar-Escaping getrennt prüfen | P2 | Reproduktion erforderlich | Docker Compose / Profile / Parser |
| [#6398](issues/6398.md) | Registry-Anmeldedaten für Non-Root-SSH und Buildserver eindeutig zuordnen | P2 | Möglicherweise bereits adressiert | Registry / SSH-Benutzer / Deployment |
| [#6401](issues/6401.md) | COOLIFY_RESOURCE_UUID auch bei eigenen Docker-Netzwerken stabil halten | P2 | Möglicherweise bereits adressiert | Compose-Parser / Umgebungsvariablen / Netzwerke |
| [#6481](issues/6481.md) | Commitmetadaten im übergeordneten Repository statt im Submodul lesen | P2 | Konkreter Codebefund | Git / Submodule / Deployment |
| [#6502](issues/6502.md) | Leere Teams trotz sichtbarer systemweiter Git-Quellen löschen können | P2 | Möglicherweise bereits adressiert | Teams / Ressourcenbesitz / Löschen |
| [#6611](issues/6611.md) | Browserterminal und Remote-PTY auf dieselbe Zeilenbreite synchronisieren | P2 | Reproduktion erforderlich | Terminal / xterm / PTY |
| [#6612](issues/6612.md) | Windmill-Template mit konsistenten Versionen und echter Bereitschaft prüfen | P2 | Reproduktion erforderlich | Service-Template / Windmill / Persistenz |
| [#6637](issues/6637.md) | HTTP/2-Protokollfehler am Cloud-Deploy-Endpunkt eingrenzen | P2 | Integration / Dokumentation | Coolify Cloud / API-Transport / GitHub Actions |
| [#6653](issues/6653.md) | Ungültige Service-Compose-Änderungen mit klarem Fehler statt scheinbarem Erfolg behandeln | P2 | Möglicherweise bereits adressiert | Service-Editor / Compose / Validierung |
| [#7163](issues/7163.md) | GCP-Logdrain mit dauerhaft verwalteten Anmeldedaten ermöglichen | P2 | Reproduktion erforderlich | Log Drain / Fluent Bit / GCP |
| [#7596](issues/7596.md) | Teamweite Deploymenthistorie mit Filtern und laufender Aktualisierung ergänzen | P2 | Erweiterung | Dashboard / Deploymenthistorie / Livewire |
| [#7642](issues/7642.md) | SurrealDB als native Datenbank mit geprüften Speicher-Backends integrieren | P2 | Erweiterung | Datenbankintegration / SurrealDB / Persistenz |
| [#8266](issues/8266.md) | Wiederverwendbaren Mailserver-Stack für mehrere Kundendomains vervollständigen | P2 | Erweiterung | Service-Templates / E-Mail / TLS |
| [#8684](issues/8684.md) | Passwortbestätigung beim Backupimport als normales Formular bedienbar machen | P2 | Konkreter Codebefund | Backupimport / Bestätigungsdialog / Barrierefreiheit |
| [#9346](issues/9346.md) | Verwaltete Fluent-Bit-Lua-Dateien und begrenzte Logdatei-Mounts ergänzen | P2 | Erweiterung | Log Drain / Fluent Bit / Dateiverwaltung |
| [#5100](issues/5100.md) | Datenbankcontainer in Docker eindeutig erkennbar benennen | P3 | Erweiterung | Datenbank / Bedienbarkeit |
| [#5165](issues/5165.md) | Build-Kontext und dockerignore bei generierten Buildpacks erklären | P3 | Integration / Dokumentation | Build / Entwicklererlebnis |
| [#5567](issues/5567.md) | Anwendungsliste nach Projekt und Suchbegriff filtern und paginieren | P3 | Erweiterung | API / Listen |
| [#5572](issues/5572.md) | Server-Proxyobjekt im OpenAPI-Schema konkret beschreiben | P3 | Erweiterung | API / OpenAPI |

## Dateien und Prüfung

- [`snapshot.json`](snapshot.json): importierbarer Bestand mit Originalen, abrufbaren Kommentaren, Herkunft, Datenlücken und gerenderter Aufarbeitung.
- [`triage.json`](triage.json): dieselben 95 Analysen als strukturierte Datensätze für weitere Bearbeitung.
- [`issues/`](issues/): 95 lesbare Einzeldossiers mit vollständiger abrufbarer Diskussion und Quellen.
- [`../../scripts/import-upstream-issues.py`](../../scripts/import-upstream-issues.py): Importer mit Probelauf und Wiederanlauf.
- [`../../scripts/tests/test_import_upstream_issues.py`](../../scripts/tests/test_import_upstream_issues.py): gezielte Tests des Importverhaltens.

```bash
python3 scripts/import-upstream-issues.py --validate-snapshot
python3 -B -m unittest discover -s scripts/tests -p 'test_import_upstream_issues.py' -v
```

Die Importtests prüfen den Importer und seine Fehlerfälle. Die Coolify-Produktmeldungen sind damit nicht durch Anwendungstests verifiziert. Es wurde kein Produktivdeployment vorgenommen.

## Technische Primärquellen

- [GitHub-Suche: Label-ODER und Issue-Filter](https://docs.github.com/en/search-github/searching-on-github/searching-issues-and-pull-requests)
- [REST: Issues lesen und anlegen](https://docs.github.com/en/rest/issues/issues)
- [REST: Issue-Kommentare](https://docs.github.com/en/rest/issues/comments)
- [GitHub CLI: gh api, Parameter und Pagination](https://cli.github.com/manual/gh_api)
- [GitHub: API-Rate-Limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)

Die Angaben zu einzelnen Coolify-Meldungen sind unmittelbar in den jeweiligen Dossiers mit Originaldiskussion und commitfesten Codeverweisen belegt.
