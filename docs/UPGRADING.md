# Oppgradering

Huben kjører som et Docker-image. Dataene (`./data`: artifacts og `hub.db`) ligger utenfor imaget og overlever oppgraderinger. Taggen du kjører bestemmes av `docker-compose.override.yml` på serveren (den er ikke i git).

## Hver gang

1. Ta backup på serveren: `scripts/backup.sh`. Den skriver `hub-ÅÅÅÅMMDD-TTMM.tar.gz` og skriver ut stien.
2. Les «Før du oppgraderer» i `CHANGELOG.md` for alle versjoner mellom din og den nye.
3. (Valgfritt) Øv på en kopi: hent arkivet hjem med `scp`, og kjør
   ```bash
   ADMIN_EMAIL=deg@example.com scripts/rehearse.sh ghcr.io/innovolt-as/artifact-hub:vX.Y.Z hub-ÅÅÅÅMMDD-TTMM.tar.gz
   ```
   Det starter det nye imaget mot en utpakket kopi av backupen på `localhost:8001` (`PORT` endrer porten). Logg inn og sjekk at alt ser riktig ut.
4. Endre taggen i `docker-compose.override.yml` til `vX.Y.Z`.
5. `docker compose pull && docker compose up -d`
6. Åpne forsiden, en app og `/admin`.

**Tilbakerulling:** sett forrige tag i `docker-compose.override.yml` og kjør de samme to kommandoene (`docker compose pull && docker compose up -d`). Trenger du dataene slik de var, pakk ut backupen over `data/`.

## Fra `latest` til v1.0.0 (første gang)

Rekkefølgen er viktig: override-fila lages **før** repo-filene oppdateres. Nye `docker-compose.yml` bygger imaget lokalt som standard, og uten override ville `up` begynne å bygge i stedet for å hente det publiserte imaget.

1. Ta backup: `scripts/backup.sh`.
2. Legg `DOMAIN` i `.env`, f.eks. `DOMAIN=apps.example.com` (samme vertsnavn som Caddy allerede serverer). Compose krever `.env` (den er `env_file` for `hub`), og `caddy` nekter å starte uten `DOMAIN`.
3. Lag `docker-compose.override.yml` ved siden av `docker-compose.yml`:
   ```yaml
   services:
     hub:
       image: ghcr.io/innovolt-as/artifact-hub:v1.0.0
       pull_policy: always
   ```
4. Oppdater filene fra repoet:
   - Er mappen en git-utsjekking: `git pull`.
   - Ellers: kopier `docker-compose.yml` og `Caddyfile` fra repoet over de gamle.
5. Sjekk at oppsettet er gyldig: `docker compose config` skal lykkes uten feil. Hvis den klager på `DOMAIN` eller `.env`, rett det før du går videre.
6. `docker compose pull && docker compose up -d`
7. Åpne forsiden, en app og `/admin`.

### Eget utseende (valgfritt)

Legg `logo.svg`, `favicon-32.png` og/eller `apple-touch-icon.png` i `data/branding/` (`BRANDING_DIR`, standard `/data/branding` i containeren). Filene du legger der erstatter standardene; de du utelater beholder standardene. Start huben på nytt (`docker compose up -d --force-recreate hub`) hvis ikoner ikke endrer seg.

## Gjør GHCR-pakken offentlig

Når repoet blir offentlig må imaget også kunne hentes uten innlogging: GitHub → Packages → `artifact-hub` → Package settings → Change visibility → Public. Test med `docker pull ghcr.io/innovolt-as/artifact-hub:v1.0.0` fra en maskin som ikke er innlogget mot ghcr.io.
