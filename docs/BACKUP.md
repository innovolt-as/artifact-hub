# Backups

## What a backup contains

`scripts/backup.sh` writes one archive, `backups/hub-YYYYMMDD-HHMM.tar.gz`, with:

- `hub.db`: a consistent copy of the database, taken safely while the hub is running.
- `artifacts/`: every app, link card, uploaded icon and the saved earlier versions.

Most of it is **plain text**: everything people store in the apps (`window.claude.use("db")`), e-mail addresses, who may see which app, and who opened what (the statistics). Passwords, login links and Claude connector tokens are stored only as hashes, and sessions are signed with `SECRET_KEY`, which lives in `.env` and is not in the archive. A copy of an archive can't be used to log in, but anyone who has it can read all the app data.

## Taking backups

By hand:

```bash
scripts/backup.sh          # needs python3 on the host; prints the archive path
```

Every night, with cron on the server (`crontab -e`):

```
15 3 * * * cd /path/to/artifact-hub && scripts/backup.sh >> backups/backup.log 2>&1
```

- Archives are readable by their owner only (`-rw-------`). Archives made before v1.1.0 are not; fix them once with `chmod 700 backups && chmod 600 backups/*.tar.gz`.
- After each run only the newest 14 archives are kept. `KEEP=30 scripts/backup.sh` keeps 30, and `KEEP=0` keeps everything. Only files named `hub-YYYYMMDD-HHMM.tar.gz` are ever deleted, so other files in `backups/` stay.

## The weakness: the backups live on the same server

By default the backups never leave the server. That keeps the data in one place, but:

- if the server dies, is deleted or its disk fails, the backups go with it;
- anyone who gets into the server (or gets a copy of its disk) can read the backups as well as the live database;
- the archives are not encrypted.

Decide for yourself whether that is good enough. If it isn't, keep a copy somewhere else, **encrypted**.

## Keeping a copy somewhere else

**Never upload the archives unencrypted** to a cloud service (file storage, an image or media CDN, e-mail, a chat). Pick one of these instead:

1. **Pull them to your own machine.** From your computer, by hand or from its own cron:
   ```bash
   rsync -av user@server:/path/to/artifact-hub/backups/ ~/hub-backups/
   ```
   Keep that folder on an encrypted disk (FileVault on macOS, LUKS/BitLocker elsewhere) and remember the copy holds the same plain-text data.
2. **Encrypt before sending anywhere.** With [age](https://age-encryption.org) and a key pair whose private key is *not* on the server:
   ```bash
   age -r age1yourpublickey... -o backups/hub-YYYYMMDD-HHMM.tar.gz.age backups/hub-YYYYMMDD-HHMM.tar.gz
   ```
   The `.age` file can go to any storage; only the private key can open it (`age -d -i key.txt -o hub.tar.gz hub.tar.gz.age`). With gpg instead: `gpg --encrypt --recipient you@example.com --output backups/hub-YYYYMMDD-HHMM.tar.gz.gpg backups/hub-YYYYMMDD-HHMM.tar.gz`.
3. **Use [restic](https://restic.net)**, which encrypts on the server before anything leaves it and keeps deduplicated snapshots, to an SFTP box, Backblaze B2 or any S3 storage:
   ```bash
   restic -r sftp:user@backup-host:/hub init
   restic -r sftp:user@backup-host:/hub backup backups/
   ```
   Store the restic password somewhere other than the server too, or a dead server leaves you with backups nobody can open.

## Restoring

1. `docker compose stop hub`
2. Move the current data aside, so nothing newer than the backup is mixed in: `mv data/hub.db data/hub.db.old && mv data/artifacts data/artifacts.old`, and remove `data/hub.db-wal` and `data/hub.db-shm` if they exist.
3. Unpack the archive into `data/` (it has `hub.db` and `artifacts/` at the top): `tar xzf backups/hub-YYYYMMDD-HHMM.tar.gz -C data`
4. `docker compose up -d`, check the hub, and delete the `.old` copies when you are happy.

To try a backup without touching the running hub, use `scripts/rehearse.sh` (see `docs/UPGRADING.md`).
