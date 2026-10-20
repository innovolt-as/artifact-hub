# Artifact Hub

Liten FastAPI-app som hoster Claude-artifacts (HTML-sider og små apper) bak innlogging med magisk lenke.

- **Galleri** på `/` – alle artifacts brukeren har tilgang til
- **Artifacts** serveres på `/a/<slug>/` (bare for innloggede)
- **Admin** på `/admin` – drag-and-drop-opplasting, slett, gjør privat/delt
- **`scripts/push.sh`** – last opp fra terminalen uten å logge inn
- **Lenkekort** (`*.link.json`) for apper som kjører for seg selv, f.eks. Recall – kan merkes `admin_only`

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

Samme filnavn/slug erstatter det som lå der fra før.

## Filer i `data/artifacts/`

| Fil | Betyr |
|---|---|
| `navn.html` | én-fils artifact → `/a/navn/` |
| `navn/index.html` (+ assets) | app med flere filer → `/a/navn/` |
| `navn.meta.json` / `navn/meta.json` | valgfritt: `{"title": "...", "description": "...", "admin_only": true}` |
| `navn.link.json` | eksternt kort: `{"title": "...", "url": "https://...", "admin_only": true}` |

Du kan også bare `scp`/`rsync` filer rett inn i `data/artifacts/` – appen leser mappen ved hver visning.

## Tilgang

- `ADMIN_EMAILS` – ser admin-siden og alt som er `admin_only`
- `ALLOWED_EMAILS` / `ALLOWED_DOMAINS` – kan logge inn og se delte artifacts
- `ALLOWED_DOMAINS=*` – alle med en e-postadresse kan logge inn (åpen side bak innlogging)
- Maks 3 aktive lenker per e-post og 10 utsendelser per IP per time, så skjemaet ikke kan brukes til spam
- Alle andre får «sjekk e-posten din», men ingen e-post sendes (lekker ikke hvem som er på listen)

Magisk lenke er gyldig i 15 minutter og kan brukes én gang. Innlogging varer 30 dager.
