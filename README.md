# Artifact Hub

Liten FastAPI-app som hoster Claude-artifacts (HTML-sider og små apper) bak innlogging med magisk lenke.

- **Forside** på `/` – appene brukeren selv har valgt, blant dem de har tilgang til
- **Artifacts** serveres på `/a/<slug>/` (bare for innloggede)
- **Admin** på `/admin` – drag-and-drop-opplasting, slett, tilgang per app (alle, bestemte personer eller bare meg),
  inviter og fjern personer, endre navn/adresse og ikon (bilde eller emoji)
- **Statistikk** på `/admin/stats` – siste 7 dager: aktive brukere, åpninger, mest brukte apper (med hvem) og hva
  hver bruker har åpnet. Admin telles ikke med. Bygger på åpningene huben logger for «Mest brukt».
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
| `list_apps` | list alle apper og lenkekort (slug, tittel, hvem som har tilgang, redigerbar) |
| `get_app` | hent HTML-en til en enkeltfils-app |
| `create_app` | publiser en ny enkeltfils-app (`slug`, `html`, `title`, valgfritt `description`, `emoji`, `private`) |
| `update_app` | erstatt hele HTML-en til en eksisterende app |
| `edit_app` | små endringer: liste av `{old, new}`-utdrag, alt eller ingenting |
| `update_app_info` | endre tittel, beskrivelse, emoji eller `private` uten å røre HTML-en |

Connectoren kan ikke slette apper. `update_app`/`edit_app` virker på enkeltfils-apper og på `index.html` i mappe-apper (de andre filene i mappen, som service worker og bilder, blir liggende). Lenkekort endres bare med `update_app_info`.

Eksempler: «legg den i huben», «oppdater timelisten i huben», «gjør Timeliste synlig for alle».

**Data i appene:** `list_app_data`, `get_app_data`, `set_app_data` og `delete_app_data` leser og skriver de samme dokumentene som appen bruker via `window.claude.use("db")`, for brukeren bak koblingen (bare din egen data). Slik kan du for eksempel si «i dag spiste jeg …» i en samtale, og Claude fører det inn i Matboka.

**Nye apper fra Claude er private** (bare admin ser dem) til du deler dem: tilgangsknappen («🔒 Bare meg») i
`/admin`, eller be Claude sette `private: false` (da ser alle som kan logge inn den). Deling med bestemte personer
gjøres i `/admin`. `private` endrer ikke en liste med personer; den blir liggende til «Bestemte personer» velges igjen.

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
Dette gjelder Claude-koblingen. Innlogging på selve huben trekkes tilbake med «Fjern» under «Personer» i `/admin`
(se [Tilgang](#tilgang)).

### Tester

`./scripts/test.sh` kjører testene i en `python:3.12-slim`-container (podman eller docker).

## Filer i `data/artifacts/`

| Fil | Betyr |
|---|---|
| `navn.html` | én-fils artifact → `/a/navn/` |
| `navn/index.html` (+ assets) | app med flere filer → `/a/navn/` |
| `navn.meta.json` / `navn/meta.json` | valgfritt: `{"title": "...", "description": "...", "emoji": "📈", "admin_only": true}`; tilgang for bestemte personer: `"access": "people", "people": ["a@b.no"]` |
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

- **Hver bruker velger sine apper.** En ny bruker får et stort «Legg til apper»-kort. Det åpner listen «Velg apper»
  med alle appene brukeren har tilgang til; huk av for å legge til, ta bort haken for å fjerne (lagres med en
  gang). Etterpå åpner den lille knappen «＋ Legg til eller fjern apper» nederst den samme listen.
- **Nye apper** havner ikke på forsiden av seg selv. De står øverst i listen merket «Ny», og den lille knappen
  får en prikk, til brukeren har åpnet listen. Første gang listen åpnes er ingenting «Ny».
- **Admin** fikk alle appene som fantes da dette kom på, og nye apper (opplasting, `push.sh`, Claude, lenkekort)
  legges rett på admins forside. Erstatter du en app, kommer den ikke tilbake hvis du har fjernet den.
- Tar man en app av forsiden, beholdes stjerna og besøkene; mister man tilgangen, forsvinner den til tilgangen
  kommer tilbake. Får appen ny adresse, følger valget med.
- **Favoritter** øverst: alle appene brukeren har lagt til i favoritter (★ i kortvisning, eller hold inne /
  høyreklikk på ikonet), uansett antall, i den rekkefølgen de ble lagt til.
- **Mest brukt** under: brukerens 4 mest åpnede apper siste 30 dager som ikke er favoritter (huben logger
  åpninger av `/a/<slug>/`, og eksterne lenkekort via `/go/<slug>`). Besøk eldre enn 90 dager slettes.
- **Ikoner eller kort**: bryteren øverst til høyre. Valget lagres på kontoen.
- **Blå prikk**: appen er endret siden du sist åpnet den.
- Kan legges på hjemskjermen («Legg til på Hjem-skjerm») og åpnes da uten adresselinje.
- **Dra ned for å oppdatere** (`static/pull.js`): som hjemskjermapp mangler iOS dette, så huben legger det inn
  på egne sider og i alle apper. Det virker bare når siden står øverst. Det virker ikke mens du skriver i et
  felt, ikke på noe som ligger fast (ark, menyer, tab-barer) og ikke i et område som ruller for seg selv og
  ikke står øverst. I en vanlig nettleserfane gjør det ingenting, siden nettleseren har sitt eget.
- Forsiden laster seg selv på nytt når du kommer tilbake til den etter mer enn 5 minutter.

### Sammendrag på kortene

En app kan vise én linje på kortet sitt (kortvisning). Appen skriver dokumentet `hub/summary`:

```js
const db = await window.claude.use("db");
await db.doc("hub/summary").set({ text: "4-roms oslo 93 ▼1" });
```

Apper som bruker `/api/data/<slug>` skriver nøkkelen `hub/summary` med `{"value": {"text": "..."}}`.
Teksten er per bruker, kuttes til 140 tegn og vises som ren tekst. Uten sammendrag står kortet uten linje.

## Banneret i appene

Øverst i hver app setter huben inn en mørkeblå stripe: «‹ [logo] | 🥗 Appnavn». Hele stripa lenker til
forsiden, og den ruller bort med siden. Den settes inn når siden serveres (`app/banner.py`), så appene
trenger ikke å gjøre noe. Den ligger i et eget shadow DOM, slik at appens CSS ikke påvirker den og den ikke
påvirker appen.
Den kommer bare på sider nettleseren åpner, ikke på HTML som en app henter med `fetch()` eller viser i en
iframe. Den vises heller ikke ved utskrift.

Knappen «▭ banner» i `/admin` slår stripa av for én app. Det lagres som `"banner": false` i appens meta
og beholdes ved ny opplasting.

Et lite skript rett bak stripa flytter den ut av `<body>`, så flex- eller grid-oppsett på `body` ikke flytter
den. Skriptet trekker den også opp over eventuell luke over seg, for eksempel safe-area-padding på `:root`. Uten
JS står stripa der serveren satte den. Slå av stripa for apper som har **fast topplinje** (`position: fixed;
top: 0`), for da dekker stripa topplinjen til du ruller. Det samme gjelder apper som **ikke ruller**
(`html, body { height: 100%; overflow: hidden }`), for da blir bunnen av appen kuttet.

## Tilgang

Hvem som ser en app, velges med tilgangsknappen per app i `/admin` (lagres i appens meta, beholdes ved ny opplasting):

- **🌍 Alle** – alle som kan logge inn
- **👥 Bestemte personer** – e-postene du krysser av eller skriver inn. De blir samtidig invitert (kan logge inn).
  Listen huskes om du bytter nivå, og gjelder bare så lenge «Bestemte personer» er valgt.
- **🔒 Bare meg** – bare admin (`admin_only`)

En app man ikke har tilgang til, finnes ikke for en: den står ikke i noen liste, og lenker og ikon gir 404.

Hvem som kan logge inn:

- `ADMIN_EMAILS` – ser admin-siden og alle apper
- **«Personer» i `/admin`** – inviter en e-post for å slippe den inn uten å endre serveroppsettet. De ser
  «Alle»-appene og appene de står på. «Fjern» tar bort invitasjonen og tar personen av alle app-listene; er de
  innlogget, ser de etterpå bare «Alle»-appene. Å fjerne noen fra én app stenger dem ikke ute.
- `ALLOWED_EMAILS` / `ALLOWED_DOMAINS` – kan logge inn som før (vises under «Personer» som «fra serveroppsettet»)
- `ALLOWED_DOMAINS=*` – alle med en e-postadresse kan logge inn (åpen side bak innlogging)
- Maks 3 aktive lenker per e-post og 10 utsendelser per IP per time, så skjemaet ikke kan brukes til spam
- Alle andre får «sjekk e-posten din», men ingen e-post sendes (lekker ikke hvem som er på listen)

Magisk lenke er gyldig i 15 minutter og kan brukes én gang. Innlogging varer 30 dager.
