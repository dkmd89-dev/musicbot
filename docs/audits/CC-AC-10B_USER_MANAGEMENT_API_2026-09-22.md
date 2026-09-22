# CC-AC-10B — User Management API

**Datum:** 2026-09-22
**Auftrag:** freigegebene Master-Prompt `CC-AC-10.md`, Slice **CC-AC-10B**
("User Management: Read + Create + Update + Delete"). Baut auf
`docs/audits/CC-AC-10A_ADMIN_INVENTORY_ARCHITECTURE_CONTRACT_2026-09-22.md`
(Zeilen #2–#6 der dortigen Admin-Funktionsmatrix) auf.

## Implementiert

Vollständige Write-Parität für User Management im Control Center:
User anlegen, Navidrome-User bearbeiten, Rolle ändern (inkl. SEC-005-
Owner-Guard), Berechtigungen setzen, User löschen. Der bestehende
Read-Endpunkt (`GET /api/v1/admin/users`) war bereits vorhanden
(CC-AC-10A-Matrix, Zeile #1) und ist unverändert.

## Application Layer

Neues `services/user_admin.py` — Telegram-freie, reine Funktionen
(`create_user`, `update_navidrome_user`, `set_user_role`,
`set_user_permissions`, `delete_user`) auf einem bereits geladenen
`users`-Dict, mit typisierten Exceptions
(`UserAlreadyExistsError`/`UserNotFoundError`/`InvalidRoleError`/
`InvalidPermissionError`/`OwnerPromotionDeniedError`). Bildet dieselbe
Validierung wie `handlers/admin/user_management_handler.py` 1:1 nach
(Rollen-/Berechtigungs-Whitelist, SEC-005-Owner-Guard, Rolle→Standard-
Berechtigungen) — per Drift-Wächter-Test abgesichert
(`test_roles_and_permissions_match_telegram_handler`).

**Bewusst NICHT in diesem Slice:** `UserManagementHandler` selbst auf
diesen Application Layer umzustellen — CC-AC-10.md §20 sieht die
Telegram-Migration explizit erst in **CC-AC-10G** vor. Die Telegram-Seite
ist in diesem Slice unverändert (0 Zeilen geändert), ihre 40
Characterization-Tests bleiben unangetastet grün — kein Risiko für den
produktiven Telegram-Bot durch diesen Slice.

`services/user_data.py` erhält zusätzlich `save_user_data()` (atomarer
write-tmp+rename, analog zu `MetadataCache.store()`) als eigene,
bewusst *nicht* mit `UserManagementHandler._save_users()`
zusammengelegte Implementierung — Letztere bleibt unverändert, weil
`tests/test_user_management_atomic_persistence.py` den Crash-Fall über
einen Monkeypatch auf den exakten Modulpfad
`handlers.admin.user_management_handler.json.dump` simuliert; ein
Umleiten hätte diesen sicherheitskritischen Regressionstest unbemerkt
wirkungslos gemacht.

## API

Neu in `control_center/routers/admin.py` (Prefix `/api/v1/admin`,
AccessLevel.ADMIN, schreibende Endpunkte zusätzlich CSRF-geschützt über
`verify_same_origin`, identisches Muster wie `admin_maintenance.py`):

| Methode | Pfad | Zweck |
|---|---|---|
| POST | `/users` | User anlegen (201) |
| PATCH | `/users/{id}/navidrome` | Navidrome-User setzen |
| PATCH | `/users/{id}/role` | Rolle ändern (SEC-005-Owner-Guard) |
| PATCH | `/users/{id}/permissions` | Berechtigungsliste setzen (Full-Replace) |
| DELETE | `/users/{id}` | User löschen |

Fehler-Mapping: `UserAlreadyExistsError`→409, `UserNotFoundError`→404,
`InvalidRoleError`/`InvalidPermissionError`/leerer Navidrome-Name→422,
`OwnerPromotionDeniedError`→403, Schreibfehler→500.

Neues Response-Schema `UserDetailResponse` (statt `UserEntry`) für die
Mutations-Endpunkte — `UserEntry`/`UsersResponse` (GET-Liste) bewusst
unverändert, da `test_get_users_response_omits_permissions_field` das
absichtliche Weglassen von `permissions` dort explizit absichert.

## Control Center UI

Noch offen — laut CC-AC-10.md §20 explizit Gegenstand von **CC-AC-10F**
("Control Center UI Parity"), nicht dieses Slices.

## Telegram

Unverändert (0 Zeilen geändert), siehe „Application Layer" oben.

## CLI

Nicht Teil dieses Slices, kein CLI für User Management vorhanden
(CC-AC-10A-Befund, unverändert).

## Tests

- `tests/test_user_admin_service.py` (neu, 20 Tests): reine
  Unit-Tests der Application-Layer-Funktionen, inkl. SEC-005-Owner-Guard-
  Charakterisierung (Spiegel von
  `tests/test_user_management_handler.py::TestSetUserRoleSec005OwnerEscalation`)
  und Drift-Wächter für ROLES/PERMISSIONS.
- `tests/test_control_center_admin_api.py` (erweitert, +21 Tests): HTTP-
  Ebene für alle 5 neuen Endpunkte, inkl. CSRF-/Origin-Ablehnung pro
  schreibendem Endpunkt und einem echten (nicht Dev-Bypass-)Session-Test
  für den Owner-Guard, da der Dev-Bypass immer als Owner agiert.
- Gezielte Tests: 67 passed (`test_user_admin_service.py` +
  `test_control_center_admin_api.py` + alle drei bestehenden
  `test_user_management_handler*.py`-Dateien — 0 Regressionen an der
  Telegram-Seite).
- Thematische Suite (`-k "user_management or user_admin or
  control_center_admin or usermgmt or menu_permissions or
  control_center_auth"`): 205 passed.
- `tests/test_services_layer_boundary.py`: 110 passed (neues
  `services/user_admin.py` verletzt die Schichtgrenze nicht).
- Vollständige Suite: **nicht** durch diesen Prozess ausgeführt
  (CLAUDE.md §8.A) — dem Nutzer zur Ausführung empfohlen.
- **Nicht durch diesen Slice verursacht, vorbestehend:** 19 Fehlschläge
  in `tests/test_control_center_ui.py`/`test_control_center_subpath_ui.py`
  (Sidebar-/Library-Template-Inhalte, z. B. fehlender
  `Zu /library`-Deep-Link im Admin-Template) — betreffen ausschließlich
  HTML-Template-Dateien, die dieser Slice nicht anfasst
  (`control_center/templates/library.html` war laut Git-Status bereits
  vor Beginn dieser Session unfertig verändert, vermutlich Teil der
  laufenden Tabler-Sidebar-Arbeit der letzten Commits). Nicht behoben
  (außerhalb des Scopes von CC-AC-10B, CLAUDE.md §8.A: vorbestehende,
  unabhängige Fehler werden nicht ungefragt mitbehoben).

## Security

- SEC-005-Owner-Guard 1:1 übernommen: nur `config.OWNER_USER_ID` darf
  die Owner-Rolle per API vergeben, sonst 403.
- Rollen-/Berechtigungs-Whitelist serverseitig (nicht nur UI), identisch
  zur Telegram-Seite.
- CSRF/Origin-Schutz auf allen 5 schreibenden Endpunkten.
- `DELETE`/Rollenänderung haben **keine** zusätzliche Schutzregel über
  die Telegram-Parität hinaus (z. B. kein Schutz gegen Selbstlöschung) —
  bewusste Paritätsentscheidung: gleiche Sicherheitslogik wie die
  bestehende Telegram-Seite, nicht strenger (CC-AC-10.md §14: „dieselbe
  fachliche Sicherheitslogik", keine neue Erfindung).

## Entfernte Duplikation

Keine — `UserManagementHandler` bleibt unverändert (siehe „Application
Layer" oben), daher entsteht in diesem Slice bewusst noch eine kleine,
dokumentierte Duplikation (ROLES/PERMISSIONS-Werte, atomare
Schreibfunktion) statt eines riskanten Eingriffs in bereits getesteten,
produktiven Telegram-Code. Auflösung ist expliziter Gegenstand von
CC-AC-10G.

## Noch offen

- CC-AC-10C (Backup + Restart + Maintenance + Navidrome-Scan) — nächster
  Slice laut CC-AC-10A-Priorisierung.
- CC-AC-10F (Control Center UI Parity) — User-Management-Formulare im
  Web-UI fehlen noch vollständig.
- CC-AC-10G (Telegram Migration) — `UserManagementHandler` könnte künftig
  auf `services/user_admin.py` umgestellt werden (löst die oben genannte
  kleine Duplikation auf).
- Die zwei aus CC-AC-10A offenen Punkte (Bot-Neustart-Web-Exposition,
  Logger-Endpunkt-Granularität) sind von CC-AC-10B nicht betroffen,
  weiterhin offen in `docs/FINDINGS_INDEX.md`.

## Read/Write-Parität

User Management: **5/5** Funktionen (User anzeigen/anlegen/bearbeiten/
Rolle ändern/Berechtigungen ändern/löschen — 6 Funktionen der
CC-AC-10A-Matrix, #1 war bereits vorhanden) jetzt vollständig
lesend+schreibend über die API erreichbar. Damit steigt der
CC-AC-10A-Gesamtstand von 12/26 auf **17/26** Admin-Funktionen mit
Web-Endpunkt.

## Regression

Gezielte + thematische Tests grün (s. o.), 0 durch diesen Slice
verursachte Fehlschläge. Volle Suite dem Nutzer zur Ausführung
empfohlen (CLAUDE.md §8.A).

---

## ADMIN PARITY MATRIX (Delta zu CC-AC-10A)

| Funktion | Telegram | CC API | CC UI | CLI | App Command/Query | Tests | Authorization | Status |
|---|---|---|---|---|---|---|---|---|
| User anzeigen | ✅ | ✅ (GET) | ❓ | ❌ | ❌ | ✅ | ADMIN (Router-Dependency) | 🟡 Read fertig, UI offen |
| User anlegen | ✅ | ✅ (POST) | ❌ | ❌ | ✅ `create_user` | ✅ | ADMIN + CSRF | 🟢 API fertig, UI offen (10F) |
| User bearbeiten (Navidrome) | ✅ | ✅ (PATCH) | ❌ | ❌ | ✅ `update_navidrome_user` | ✅ | ADMIN + CSRF | 🟢 API fertig, UI offen (10F) |
| Rolle ändern | ✅ | ✅ (PATCH) | ❌ | ❌ | ✅ `set_user_role` | ✅ | ADMIN + CSRF + Owner-Guard | 🟢 API fertig, UI offen (10F) |
| Berechtigungen ändern | ✅ | ✅ (PATCH) | ❌ | ❌ | ✅ `set_user_permissions` | ✅ | ADMIN + CSRF | 🟢 API fertig, UI offen (10F) |
| User löschen | ✅ | ✅ (DELETE) | ❌ | ❌ | ✅ `delete_user` | ✅ | ADMIN + CSRF | 🟢 API fertig, UI offen (10F) |

Alle übrigen Zeilen der CC-AC-10A-ADMIN-PARITY-MATRIX unverändert.
