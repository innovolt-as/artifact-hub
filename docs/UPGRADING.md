# Oppgradering

Huben kjører som et Docker-image. Dataene (`./data`: artifacts og `hub.db`) ligger utenfor imaget og overlever oppgraderinger. Taggen du kjører bestemmes av `docker-compose.override.yml` på serveren (den er ikke i git).

## Hver gang

1. Ta backup på serveren: `scripts/backup.sh` (trenger `python3` på verten). Arkivet havner i `./backups/` som standard (`hub-ÅÅÅÅMMDD-TTMM.tar.gz`), og stien skrives ut.
2. Les «Før du oppgraderer» i `CHANGELOG.md` for alle versjoner mellom din og den nye.
3. (Valgfritt) Øv på en kopi: hent arkivet hjem med `scp`, og kjør
   ```bash
   ADMIN_EMAIL=deg@example.com scripts/rehearse.sh ghcr.io/innovolt-as/artifact-hub:vX.Y.Z hub-ÅÅÅÅMMDD-TTMM.tar.gz
   ```
   Det starter det nye imaget mot en utpakket kopi av backupen på `localhost:8001` (`PORT` endrer porten). Skriptet kjører i forgrunnen: innloggingslenken skrives ut i samme terminal, og Ctrl-C stopper det. Logg inn og sjekk at alt ser riktig ut.
4. Endre taggen i `docker-compose.override.yml` til `vX.Y.Z`.
5. `docker compose pull && docker compose up -d`
6. Åpne forsiden, en app og `/admin`.

**Tilbakerulling:** sett forrige tag i `docker-compose.override.yml` og kjør de samme to kommandoene (`docker compose pull && docker compose up -d`). Normalt rulles bare image-taggen tilbake, og dataene i `data/` røres ikke. Gjenopprett data fra backupen bare hvis den nye versjonen har endret dem:

1. `docker compose stop hub`
2. Pakk arkivet ut i `data/` (arkivet har `hub.db` og `artifacts/` på toppnivå): `tar xzf backups/hub-ÅÅÅÅMMDD-TTMM.tar.gz -C data`
3. Fjern `data/hub.db-wal` og `data/hub.db-shm` hvis de finnes.
4. `docker compose up -d`

Caddy, `.env` og compose-filene beholdes som de er.

## Fra `latest` til v1.0.0 (første gang)

Rekkefølgen er viktig: override-fila lages **før** repo-filene oppdateres. Nye `docker-compose.yml` bygger imaget lokalt som standard, og uten override ville `up` begynne å bygge i stedet for å hente det publiserte imaget.

0. Forutsetning: `v1.0.0`-imaget må være publisert (taggen pushet og build-workflowen grønn) før du kjører `pull`.
1. Skaff backup-skriptet først, siden `scripts/` ikke finnes på serveren før repoet er oppdatert (og aldri i en mappe med bare kopierte filer):
   - Git-utsjekking: `git fetch && git checkout origin/main -- scripts/backup.sh`
   - Kopierte filer: `scp scripts/backup.sh server:mappe/scripts/backup.sh` (lag `scripts/` først).
2. Ta backup: `scripts/backup.sh` (trenger `python3` på verten; arkivet havner i `./backups/`). Uten `python3` eller skriptet, ta en manuell backup:
   ```bash
   docker compose stop hub && tar czf ../hub-manual-backup.tar.gz -C data hub.db artifacts && docker compose start hub
   ```
3. Legg `DOMAIN` i `.env`, f.eks. `DOMAIN=apps.example.com` (samme vertsnavn som Caddy allerede serverer). Compose krever `.env` (den er `env_file` for `hub`), og `caddy` nekter å starte uten `DOMAIN`.
4. Lag `docker-compose.override.yml` ved siden av `docker-compose.yml`:
   ```yaml
   services:
     hub:
       image: ghcr.io/innovolt-as/artifact-hub:v1.0.0
       pull_policy: always
   ```
5. Oppdater filene fra repoet:
   - Er mappen en git-utsjekking: kjør `git status` først. Hvis `Caddyfile` er endret (vertsnavnet ble tidligere redigert der), kjør `git checkout -- Caddyfile`; `DOMAIN` erstatter den endringen. Deretter `git pull`.
   - Ellers: kopier `docker-compose.yml` og `Caddyfile` fra repoet over de gamle.
6. Sjekk at oppsettet er gyldig: `docker compose config` skal lykkes uten feil. Hvis den klager på `DOMAIN` eller `.env`, rett det før du går videre.
7. `docker compose pull && docker compose up -d`
8. Åpne forsiden, en app og `/admin`.

### Eget utseende (valgfritt)

Legg `logo.svg`, `favicon-32.png` og/eller `apple-touch-icon.png` i `data/branding/` (`BRANDING_DIR`, standard `/data/branding` i containeren). Filene du legger der erstatter standardene; de du utelater beholder standardene. Endringer virker ved neste forespørsel; last siden inn på nytt uten cache hvis nettleseren fortsatt viser det gamle ikonet (favicons caches hardt).

## Gjør GHCR-pakken offentlig

Når repoet blir offentlig må imaget også kunne hentes uten innlogging: GitHub → Packages → `artifact-hub` → Package settings → Change visibility → Public. Test med `docker pull ghcr.io/innovolt-as/artifact-hub:v1.0.0` fra en maskin som ikke er innlogget mot ghcr.io.
