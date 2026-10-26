# Oppgradering

Huben kjører som et Docker-image. Dataene (`./data`: artifacts og `hub.db`) ligger utenfor imaget og overlever oppgraderinger. Taggen du kjører bestemmes av `docker-compose.override.yml` på serveren (den er ikke i git).

## Hver gang

1. Ta backup på serveren: `scripts/backup.sh` (trenger `python3` på verten). Arkivet havner i `./backups/` som standard (`hub-ÅÅÅÅMMDD-TTMM.tar.gz`), og stien skrives ut.
2. Les «Before you upgrade» (engelsk overskrift) i `CHANGELOG.md` for alle versjoner mellom din og den nye.
3. (Valgfritt) Øv på en kopi: hent arkivet hjem med `scp`, og kjør
   ```bash
   ADMIN_EMAIL=deg@example.com scripts/rehearse.sh ghcr.io/innovolt-as/artifact-hub:vX.Y.Z hub-ÅÅÅÅMMDD-TTMM.tar.gz
   ```
   Det starter det nye imaget mot en utpakket kopi av backupen på `localhost:8001` (`PORT` endrer porten). Skriptet kjører i forgrunnen: innloggingslenken skrives ut i samme terminal, og Ctrl-C stopper det. Logg inn og sjekk at alt ser riktig ut.
4. Endre taggen i `docker-compose.override.yml` til `vX.Y.Z`.
5. `docker compose pull && docker compose up -d`
6. Åpne forsiden, en app og `/admin`.

**Tilbakerulling:** sett forrige tag (ved første oppgradering: image-referansen du noterte i steg 4 under «Fra `latest` til v1.0.0») i `docker-compose.override.yml` og kjør de samme to kommandoene (`docker compose pull && docker compose up -d`). Normalt rulles bare image-taggen tilbake, og dataene i `data/` røres ikke. Gjenopprett data fra backupen bare hvis den nye versjonen har endret dem:

1. `docker compose stop hub`
2. Pakk arkivet ut i `data/` (arkivet har `hub.db` og `artifacts/` på toppnivå): `tar xzf backups/hub-ÅÅÅÅMMDD-TTMM.tar.gz -C data`
3. Fjern `data/hub.db-wal` og `data/hub.db-shm` hvis de finnes.
4. `docker compose up -d`

Caddy, `.env` og compose-filene beholdes som de er.

## Fra `latest` til v1.0.0 (første gang)

Rekkefølgen er viktig: override-fila lages **før** repo-filene oppdateres. Nye `docker-compose.yml` bygger imaget lokalt som standard, og uten override ville `up` begynne å bygge i stedet for å hente det publiserte imaget.

1. Forutsetning: `v1.0.0`-imaget må være publisert (taggen pushet og build-workflowen grønn) før du kjører `pull`.
2. Skaff backup-skriptet først, siden `scripts/` ikke finnes på serveren før repoet er oppdatert (og aldri i en mappe med bare kopierte filer):
   - Git-utsjekking: `git fetch && git checkout origin/main -- scripts/backup.sh`
   - Kopierte filer: `scp scripts/backup.sh server:mappe/scripts/backup.sh` (lag `scripts/` først).
3. Ta backup: `scripts/backup.sh` (trenger `python3` på verten; arkivet havner i `./backups/`). Uten `python3` eller skriptet, ta en manuell backup:
   ```bash
   docker compose stop hub && tar czf ../hub-manual-backup.tar.gz -C data hub.db artifacts && docker compose start hub
   ```
4. Noter hvilket image som kjører nå, slik at du kan rulle tilbake (det finnes ingen forrige tag, og `latest` flyttes av v1.0.0-bygget): `docker image inspect $(docker inspect artifact-hub --format '{{.Image}}') --format '{{join .RepoDigests "\n"}}'` gir en referanse som `ghcr.io/innovolt-as/artifact-hub@sha256:…`. Skriv den ned. Tilbakerulling ved første oppgradering = denne referansen på `image:`-linjen i override-fila (bruk digesten, ikke image-ID-en: med `pull_policy: always` må referansen kunne hentes fra registeret).
5. Legg `DOMAIN` i `.env`, f.eks. `DOMAIN=apps.example.com` (samme vertsnavn som Caddy allerede serverer). Compose krever `.env` (den er `env_file` for `hub`), og `caddy` nekter å starte uten `DOMAIN`.
6. Lag `docker-compose.override.yml` ved siden av `docker-compose.yml`:
   ```yaml
   services:
     hub:
       image: ghcr.io/innovolt-as/artifact-hub:v1.0.0
       pull_policy: always
   ```
7. Oppdater filene fra repoet:
   - Er mappen en git-utsjekking: kjør `git status` og `git diff Caddyfile docker-compose.yml` først.
     - `Caddyfile`: er bare vertsnavnet endret, kjør `git checkout -- Caddyfile`; `DOMAIN` erstatter den endringen. Er noe annet endret (ekstra headere, redirects, et ekstra site), lagre en kopi (`cp Caddyfile ../Caddyfile.mine`) før `git checkout -- Caddyfile`, og legg endringene inn igjen etter `git pull`.
     - `docker-compose.yml`: er den redigert lokalt, avbryter `git pull`. Kjør `git stash` (eller lagre en kopi og `git checkout -- docker-compose.yml`), og flytt de lokale endringene til `docker-compose.override.yml` etterpå.
     - Deretter `git pull`.
   - Kopierte filer: kjør `diff` mellom de gamle og de nye `docker-compose.yml` og `Caddyfile` før du overskriver, og ta med egne endringer (compose-endringer hører hjemme i `docker-compose.override.yml`). Kopier så filene fra repoet over de gamle.
8. Sjekk at oppsettet er gyldig: `docker compose config --quiet`. Den skriver ingenting og gir exit-kode 0 når oppsettet er gyldig; ellers kommer feilmeldingen (f.eks. om `DOMAIN` eller `.env`), og den må rettes før du går videre. Bruk alltid `--quiet`: uten det skriver compose ut hele konfigurasjonen inkludert `.env`-hemmelighetene (SECRET_KEY, SMTP_PASS, UPLOAD_TOKEN).
9. `docker compose pull && docker compose up -d`
10. Åpne forsiden, en app og `/admin`.

### Eget utseende (valgfritt)

Legg `logo.svg`, `favicon-32.png` og/eller `apple-touch-icon.png` i `data/branding/` (`BRANDING_DIR`, standard `/data/branding` i containeren). Filene du legger der erstatter standardene; de du utelater beholder standardene. Endringer virker ved neste forespørsel; last siden inn på nytt uten cache hvis nettleseren fortsatt viser det gamle ikonet (favicons caches hardt).

## Bytte innloggingsmåte

Fra magisk lenke til passord:

1. Sett `LOGIN_MODE=password` i `.env` og kjør `docker compose up -d`.
2. Sett passord for admin på kommandolinjen: `docker compose exec hub python -m app.passwd set you@example.com`.
3. Logg inn og sett midlertidige passord for de andre under «Personer» i `/admin`. De må bytte passordet ved første innlogging. Passord må ha minst 10 tegn (gjelder både midlertidige og selvvalgte). Kommandolinjen kan også lage et midlertidig passord med `--temporary`.

Folk som allerede er innlogget, forblir det til innloggingen utløper (30 dager). De har ikke passord ennå, og må få et midlertidig passord av admin før de kan bytte passord.

Mot gjetting: maks 10 feil per e-post per 15 minutter og 30 per IP per time. Å sette et nytt passord (kommandolinjen eller admin) opphever sperren for den e-posten. `docker compose restart hub` nullstiller alle tellere.

Tilbake til magisk lenke: sett `LOGIN_MODE=magic-link` og kjør `docker compose up -d`. Passordene blir liggende i databasen og brukes igjen hvis du bytter til passord senere.

`scripts/rehearse.sh` leser `LOGIN_MODE` fra miljøet. Skal du øve på en hub med passord-innlogging: `LOGIN_MODE=password ADMIN_EMAIL=you@example.com scripts/rehearse.sh <image> <backup.tar.gz>`. Containeren heter `hub-rehearsal-<port>`. En backup fra en hub uten passord har ingen passord, så sett admin-passordet i øvingscontaineren fra et annet terminalvindu: `docker exec -it hub-rehearsal-<port> python -m app.passwd set you@example.com` (skriptet skriver kommandoen ut). En backup tatt etter at passordene ble satt, trenger ingenting ekstra.

## Gjør GHCR-pakken offentlig

Når repoet blir offentlig må imaget også kunne hentes uten innlogging: GitHub → Packages → `artifact-hub` → Package settings → Change visibility → Public. Test med `docker pull ghcr.io/innovolt-as/artifact-hub:v1.0.0` fra en maskin som ikke er innlogget mot ghcr.io.
