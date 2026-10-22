# Artifact Hub

Liten FastAPI-app som hoster Claude-artifacts (HTML-sider og små apper) bak innlogging med magisk lenke.

- **Galleri** på `/` – alle artifacts brukeren har tilgang til
- **Artifacts** serveres på `/a/<slug>/` (bare for innloggede)
- **Admin** på `/admin` – drag-and-drop-opplasting, slett, gjør privat/delt, endre navn/adresse og ikon (bilde eller emoji)
- **`scripts/push.sh`** – last opp fra terminalen uten å logge inn
- **Claude-connector** på `/mcp` – publiser og oppdater apper rett fra en samtale i claude.ai (også i mobilappen)
- **Lagring for artifacts** – artifacts fra claude.ai som bruker `window.claude.use("db")` fungerer uendret (se under)
- **Lenkekort** (`*.link.json`) for apper som kjører for seg selv, f.eks. Recall og Modi – legges til og redigeres i `/admin`, kan merkes `admin_only`

## Oppsett på serveren

```bash
git clone https://github.com/innovolt-as/artifact-hub.git && cd artifact-hub
cp .env.example .env            # fyll inn SECRET_KEY, e-poster, UPLOAD_TOKEN, SMTP
mkdir -p data/artifacts         # + kopier inn recall.link.json (data/ er ikke i git)
docker compose up -d
```

Caddy står foran appen og henter HTTPS-sertifikat for `apps.innovolt.no` automatisk
(krever A-record mot serveren og åpne porter 80/443). Domenet endres i `Caddyfile`.

Alt som skal overleve (artifacts + SQLite) ligger i `./data`. Sertifikatene ligger i volumet `caddy_data`.

## E-post

Magiske lenker sendes via SMTP. Resend, Postmark, Brevo, Gmail app-passord – alt med SMTP fungerer.
Lar du `SMTP_HOST` stå tom, printes lenken i loggen (`docker compose logs -f hub`) – greit for testing.

## Bygge og pushe image lokalt

```bash
GHCR_IMAGE=ghcr.io/<brukernavn>/artifact-hub ./scripts/build-and-push.sh
# på serveren:
docker compose pull && docker compose up -d
```

(Det ligger også en valgfri GitHub Actions-workflow i `.github/workflows/build.yml`.)

## Laste opp artifacts

**Fra nettleseren:** logg inn som admin → `/admin` → dra inn `.html`-filer eller en `.zip` med `index.html`.

**Fra terminalen:**

```bash
# én gang:
mkdir -p ~/.config && cat > ~/.config/artifact-hub.env <<EOF
HUB_URL=https://apps.innovolt.no
HUB_TOKEN=<samme som UPLOAD_TOKEN i .env>
EOF

./scripts/push.sh chart.html
./scripts/push.sh --private hemmelig.html
./scripts/push.sh --slug budsjett --title "Budsjett 2026" fil.html
```

Samme filnavn/slug erstatter det som lå der fra før. Navn, ikon og privat-innstilling beholdes.

Galleriet sorteres alfabetisk på navn (æ, ø, å til slutt).

## Publisere fra Claude

Huben er en custom connector (ekstern MCP-server med OAuth) for claude.ai på `https://apps.innovolt.no/mcp`.

**Legg til én gang** (claude.ai i nettleser på en PC): Innstillinger → Connectors → Add custom connector → lim inn URL-en.
Etter det finnes connectoren i alle samtaler, også i iPhone/Android-appen.

**Innlogging:** claude.ai åpner huben. Logg inn med e-post (den magiske lenken åpnes i en ny fane – fortsett der),
og trykk «Gi tilgang» på godkjenningssiden. Bare e-poster i `ADMIN_EMAILS` kan koble til; andre blir avvist.

| Verktøy | Gjør |
|---|---|
| `list_apps` | list alle apper og lenkekort (slug, tittel, privat, redigerbar) |
| `get_app` | hent HTML-en til en enkeltfils-app |
| `create_app` | publiser en ny enkeltfils-app (`slug`, `html`, `title`, valgfritt `description`, `emoji`, `private`) |
| `update_app` | erstatt hele HTML-en til en eksisterende app |
| `edit_app` | små endringer: liste av `{old, new}`-utdrag, alt eller ingenting |
| `update_app_info` | endre tittel, beskrivelse, emoji eller `private` uten å røre HTML-en |

Connectoren kan ikke slette apper. `update_app`/`edit_app` virker på enkeltfils-apper og på `index.html` i mappe-apper (de andre filene i mappen, som service worker og bilder, blir liggende). Lenkekort endres bare med `update_app_info`.

Eksempler: «legg den i huben», «oppdater timelisten i huben», «gjør Timeliste synlig for alle».

**Data i appene:** `list_app_data`, `get_app_data`, `set_app_data` og `delete_app_data` leser og skriver de samme dokumentene som appen bruker via `window.claude.use("db")`, for brukeren bak koblingen (bare din egen data). Slik kan du for eksempel si «i dag spiste jeg …» i en samtale, og Claude fører det inn i Matboka.

**Nye apper fra Claude er private** (bare admin ser dem) til du deler dem: «🌐 delt»-knappen i `/admin`,
eller be Claude sette `private: false`.

### Versjoner

Ved hver erstatning (admin, `push.sh` og connector) lagres den gamle versjonen i
`data/artifacts/.versions/<slug>/` – de 10 siste per app. Enkeltfiler lagres som `.html`, mappe-apper som `.zip`.
Versjonene beholdes ved endring av adresse og når appen slettes.

Legge tilbake en gammel versjon: kopier fila til `data/artifacts/<slug>.html`
(for `.zip`: pakk ut i `data/artifacts/<slug>/`).

### Trekke tilbake tilgang

Fjern e-posten fra `ADMIN_EMAILS` og kjør `docker compose up -d` (sjekkes ved hvert kall etter omstart). Å slette
radene i SQLite-tabellen `oauth_tokens` i `data/hub.db` (evt. også `oauth_codes`, `oauth_requests` og
`oauth_clients`) virker med en gang.

### Tester

`./scripts/test.sh` kjører testene i en `python:3.12-slim`-container (podman eller docker).

## Filer i `data/artifacts/`

| Fil | Betyr |
|---|---|
| `navn.html` | én-fils artifact → `/a/navn/` |
| `navn/index.html` (+ assets) | app med flere filer → `/a/navn/` |
| `navn.meta.json` / `navn/meta.json` | valgfritt: `{"title": "...", "description": "...", "emoji": "📈", "admin_only": true}` |
| `navn.link.json` | eksternt kort: `{"title": "...", "url": "https://...", "admin_only": true}` |
| `.icons/navn.png` (eller .jpg/.webp/.gif/.svg) | ikon lastet opp i admin; `"emoji": "📈"` i meta brukes ellers |

Du kan også bare `scp`/`rsync` filer rett inn i `data/artifacts/` – appen leser mappen ved hver visning.

## Data per bruker for apper

Artifacts kan lagre data for den innloggede brukeren gjennom et lite nøkkel/verdi-API. Hver rad hører til én
e-post og ett app-navn, så brukere ser aldri hverandres data. Kallene gjøres med vanlig `fetch` fra artifacten
(samme domene), så innloggings-cookien følger med automatisk. Dataene ligger i `hub.db` i `./data`.

| Kall | Gjør |
|---|---|
| `GET /api/me` | `{"email", "admin"}`, eller 401 hvis ikke innlogget |
| `GET /api/data/<app>?prefix=logs/` | alle nøkler for appen (valgfritt filtrert på prefiks) |
| `GET /api/data/<app>/<nøkkel>` | én verdi, 404 hvis den ikke finnes |
| `PUT /api/data/<app>/<nøkkel>` | lagre, body `{"value": <json>}` |
| `DELETE /api/data/<app>/<nøkkel>` | slett |
| `POST /api/data/<app>/_batch` | `{"set": {nøkkel: verdi}, "delete": [nøkler]}` i én transaksjon (import) |

Skrivekall må ha `Content-Type: application/json`. Grenser: 512 KB per verdi, 5000 nøkler og 25 MB per bruker per app.
App-navnet bør være artifactens slug, f.eks. `trening`.

## Lagring for artifacts (`hub.js`)

Artifacts laget på claude.ai lagrer data via `window.claude.use("db")`, som bare finnes på claude.ai.
Huben legger derfor automatisk `<script src="/static/hub.js">` først i `<head>` på alle HTML-sider under
`/a/`, og den gir en kompatibel `window.claude.use(...)`:

| Capability | I huben |
|---|---|
| `db` | Lagres i SQLite på serveren, **privat per app og per innlogget bruker**. `collection/doc`, `get/set/update/delete`, `add`, `where/orderBy/limit`, `onSnapshot` (oppdateres hvert 5. sek fra andre faner/enheter) |
| `downloads` | `save({filename, data})` blir en vanlig nedlasting |
| `user` | Den innloggede e-posten. `isOwner()`/`canEdit()` er sant for admin |
| alt annet (`sample`, `room`, `mcp`, …) | `null` – krever claude.ai |

- Dataene følger med når en app får ny adresse, og blir liggende hvis appen slettes (kommer tilbake ved ny opplasting).
- `GET /api/store/<slug>` gir alt du har lagret i én app som JSON – greit som sikkerhetskopi.

## Forsiden

- **Mest brukt** øverst: hver innlogget bruker ser sine 4 mest åpnede apper siste 30 dager (huben logger
  åpninger av `/a/<slug>/`, og eksterne lenkekort via `/go/<slug>`). Festede apper (★, eller hold inne /
  høyreklikk på ikonet) ligger alltid først. Besøk eldre enn 90 dager slettes.
- **Ikoner eller kort**: bryteren øverst til høyre. Valget lagres på kontoen.
- **Blå prikk**: appen er endret siden du sist åpnet den.
- Kan legges på hjemskjermen («Legg til på Hjem-skjerm») og åpnes da uten adresselinje.

### Sammendrag på kortene

En app kan vise én linje på kortet sitt (kortvisning). Appen skriver dokumentet `hub/summary`:

```js
const db = await window.claude.use("db");
await db.doc("hub/summary").set({ text: "4-roms oslo 93 ▼1" });
```

Apper som bruker `/api/data/<slug>` skriver nøkkelen `hub/summary` med `{"value": {"text": "..."}}`.
Teksten er per bruker, kuttes til 140 tegn og vises som ren tekst. Uten sammendrag står kortet uten linje.

## Tilgang

- `ADMIN_EMAILS` – ser admin-siden og alt som er `admin_only`
- `ALLOWED_EMAILS` / `ALLOWED_DOMAINS` – kan logge inn og se delte artifacts
- `ALLOWED_DOMAINS=*` – alle med en e-postadresse kan logge inn (åpen side bak innlogging)
- Maks 3 aktive lenker per e-post og 10 utsendelser per IP per time, så skjemaet ikke kan brukes til spam
- Alle andre får «sjekk e-posten din», men ingen e-post sendes (lekker ikke hvem som er på listen)

Magisk lenke er gyldig i 15 minutter og kan brukes én gang. Innlogging varer 30 dager.
