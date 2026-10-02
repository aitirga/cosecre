# Fly deployment

App: `cosecre-aitirga`, organization `personal` (Aitor Iraola), region `fra`.
URL: https://cosecre-aitirga.fly.dev

The Docker image builds the Vue frontend and serves it from FastAPI alongside
`/api/v1`. Uvicorn runs one production worker without reload. Fly provides HTTPS.
Python dependencies use `uv sync --locked --no-dev`; frontend dependencies use
the existing npm workspace lockfile.

## Persistence

One encrypted 3 GB Fly volume, `cosecre_data`, mounts at `/data`:

| Path | Contents |
| --- | --- |
| `/data/cosecre.db` | SQLite: users, sessions, settings, the full document register, jobs |
| `/data/uploads` | Uploaded PDFs and images |
| `/data/backups` | The hub's own daily backups (last 30) |
| `/data/secrets/google.json` | Migrated Google service-account credential |

Database and uploads survive machine restart and image redeployment. Container
root storage is disposable; never store durable data outside `/data`.
Keep exactly one machine: Fly volumes are not shared or automatically replicated.
Do not scale horizontally with independent SQLite copies. Multiple machines would
require shared database and object storage or a deliberate replication design.

Automatic daily volume snapshots retain 14 days. These are recovery aids, not
high availability or a complete independent backup strategy. A host/volume failure
can cause downtime and data loss since the last usable backup. For critical data,
also export consistent SQLite backups and uploads to independent storage.

## Idle shutdown and automatic wake

The app exits cleanly after 600 seconds (10 minutes) without activity and with
no pending, processing or partially written extraction jobs. Active HTTP calls,
streams and their background tasks prevent shutdown; the timer starts again
when they finish. `/healthz` probes do not keep the machine awake. A failed job
check postpones shutdown. An open browser polling the app counts as activity.

Fly has `auto_start_machines = true`, `min_machines_running = 0`, and restart
policy `on-failure`. `auto_stop_machines = "off"` is intentional: the app, which
knows about background work, decides when to exit. Fly wakes it on the next
request. No external scheduler, credentials or keep-alive traffic is needed.
The production entry point is `python -m cosecre_hub.server`; it asks Uvicorn
to drain and return with exit code 0 instead of sending a signal that could
trigger an immediate on-failure restart. Keep one worker and one machine.

`COSECRE_IDLE_TIMEOUT_SECONDS=0` disables shutdown; locally it defaults to 0.
Use `just run` for the production server and `just test-idle` for idle tests.
To change production behaviour, edit the timeout in `fly.toml` and deploy.
The first request after sleeping waits for startup. Users and documents persist
on `/data`. Stopped machines still incur storage charges.

Use `just status` to inspect a sleeping machine without waking it. Opening the
website wakes it; backups and `just memory` require a running machine.
A manual restart/deploy can still interrupt an extraction; avoid deployment
during active jobs.

Verified on 2026-09-22 with a temporary 30-second timeout: the machine stopped
with exit code 0 (no OOM and no automatic restart), and an HTTP request woke it
and returned 200 in 23.3 seconds. The production timeout was then restored to
600 seconds. The backend suite passes 81 tests, including background-work and
clean-exit coverage.

References: https://fly.io/docs/launch/autostop-autostart/#apps-that-shut-down-when-idle
and https://fly.io/docs/machines/guides-examples/machine-restart-policy/

## Cold-start performance and loading UI

The image precompiles dependency, application and standard-library Python
bytecode at build time. `PYTHONDONTWRITEBYTECODE` still prevents runtime writes,
but Python can read the built bytecode. Google discovery and upload imports are
deferred until a Sheets/Drive operation needs them.

The web app shows an indeterminate loading bar during session bootstrap and
slow API calls, with a connection message after three seconds. It tracks
overlapping calls and clears after network errors, and respects reduced motion.
The service worker precaches the public app shell, never private API responses,
so returning visitors can see the loader while the machine wakes. A first visit
without that cache must still wait for Fly to deliver the initial HTML.

Verified the production web build in a browser with delayed requests, concurrent
success/failure, a cached navigation, and reduced motion. Backend tests: 81 pass;
web build and desktop typecheck pass.

Measured an uncached HTTP request from a fully stopped machine after this
deployment: HTTP 200 in 8.13 seconds, compared with the earlier 23.26 seconds
(about 65% faster in these two samples). Startup logs show roughly 4 seconds
from launching Python to readiness, previously about 12 seconds. These are
individual measurements, not a latency guarantee. The idle timeout remains
600 seconds and the machine retains 1 GB RAM.

## Memory and interrupted work

The machine has 1 GB RAM. After briefly returning to 512 MB following the memory
fixes, it was restored to 1 GB at the owner's request for extra headroom.
`just memory` reports worker RSS, its peak since startup and available
machine RAM. `just status` checks availability; `just logs` tails production logs.

One app-scoped Google service reuses at most one Sheets client and one Drive
client, including their nested spreadsheets, values, files and permissions
resources (which otherwise recreate large discovery graphs on every poll).
A reentrant lock serializes their use because the underlying HTTP
transport is not thread-safe. Drive uploads stream in 1 MiB chunks and close the
file on success or failure. Document extraction runs one job at a time; waiting
jobs wait asynchronously rather than occupying the shared request thread pool.
The health endpoint also runs outside that pool.

These controls bound concurrent heavy operations, not total memory independently
of document size or traffic. Keep the 25 MiB upload limit. The generic LLM API,
large spreadsheet responses and concurrent authentication still need headroom.

On startup, unfinished document jobs become errors with an interruption message.
Their files and extracted fields remain available. Check the spreadsheet before
retrying: a remote write may have succeeded just before the process died.
Saving or validating a failed job with extracted fields and no recorded sheet
row now recovers the missing row on demand. It checks the reference under the
Google service lock before inserting; repeated requests update the same row.
Jobs without extracted fields return an actionable 409. Google outages return
502 and never cause insertion based on an assumed empty spreadsheet.
This recovery assumes exactly one Uvicorn worker and one machine; multiple
workers require a durable queue with job ownership instead.

Verification on 21 September 2026: 70 backend tests pass. Before the fix, the
live worker reached a 343.1 MiB RSS peak during invoice polling; caching only
root Google clients still grew to 369.1 MiB after 30 polls. With nested resources
also reused, the final deployment stayed at 169.6 MiB RSS from the first through
the thirtieth live poll, with roughly 637 MiB machine RAM available. Warm list
responses took approximately 0.5–0.7 seconds. A separate local 100-poll test with
real discovery resources and mocked HTTP also showed a flat peak after warmup.
These are polling measurements, not a maximum-size extraction load test.

The subsequent validation fix passed 74 backend tests. The interrupted invoice
`INV-20260921-E4035D02` was recovered through PATCH with unchanged extracted
fields into sheet row 15, still awaiting validation. The reference was verified
to appear exactly once. Its earlier HTTP 500 came from a missing sheet row,
not a new out-of-memory restart.

## Deploy and inspect

```sh
fly deploy --remote-only --ha=false --strategy immediate
fly status
fly checks list
fly volumes list
fly volumes snapshots list vol_4y8qj6lx9xopp11r
fly volumes snapshots create vol_4y8qj6lx9xopp11r
```

Before database-changing deployments, take a backup/snapshot. Startup applies
additive compatibility migrations. Image rollback does not roll back database
changes. Restore a snapshot into a NEW volume and verify before replacing the
active volume; never destroy the only good copy.

Signing and OpenAI keys are Fly secrets; no `.env`, database, local credentials,
or uploads are included in the Docker build context. Bootstrap credentials should
be removed after migration to avoid resetting an existing admin on every startup.

## Versions, sync and backups

**Sheet ↔ database.** Every register entry remembers the values it had the last
time it and its sheet row agreed. Comparing both sides against that common
ancestor tells who changed what — the app, the sheet, or both (a conflict):

- App edits reach the sheet on their own, unless that row also has sheet edits
  waiting; then nothing is overwritten and the entry is flagged.
- Sheet edits, rows typed into the sheet and rows deleted from it wait for a
  person: *Registre → Sincronització* lists every difference field by field,
  with **Integra al registre** (sheet → database) and **Escriu al full**
  (database → sheet). Both take a backup first, including the sheet's values.

**Versions.** A version (zip in `/data/backups`, last 30 kept, copied to the
Drive backup folder when configured) is taken daily, before an idle shutdown if
anything changed, and before every integrate, overwrite, restore or migration.
Each holds `cosecre.db`, `registre.json`, `registre.csv` (Excel-ready,
`dd/mm/yyyy`), `full.json` when the sheet was captured, and a manifest with a
fingerprint per entry — which is how each version shows `+added ~changed
−removed` against the previous one. In *Configuració → Versions*:

- **Compara**: field-level diff between that version and now.
- **Restaura**: the register (documents, uploads, jobs) goes back to that
  version; accounts, sessions and settings stay. The present is saved as a
  version first, so a restore is undone by restoring that one. Refused while
  documents are being read.
- **Descarrega / Puja una còpia**: a version zip, or a bare `cosecre.db`, can be
  uploaded from outside; it is validated and becomes a version to compare or
  restore. Restoring the whole database file (accounts included) is still done
  by stopping the app and replacing `/data/cosecre.db`.

## Google Drive

Every document is uploaded to one folder, named `<yyyy-mm-dd>_<number>` and
renamed when someone corrects the date or the number. The folder ids are set in
`fly.toml` (`COSECRE_GOOGLE_DRIVE_DOCUMENTS_FOLDER_ID`, `..._BACKUP_FOLDER_ID`);
share both folders with the service account as Editor. The **Google Drive API
must be enabled** in the service account's Cloud project (it was not, which is
why no upload ever reached Drive), and the hub asks for the full `drive` scope —
`drive.file` cannot see folders shared with it. Originals that only live on the
server are uploaded from *Configuració → Migració → Puja'ls a Drive*. Until it is set, no upload reaches Drive
(as of September 2026, none of the 55 production uploads had a Drive copy: the
service account was writing to its own *My Drive*, which has no quota), and the
sheet's "Fitxer" column stays empty. The app still works — the original is kept
on the volume — but the sheet has no thumbnails.

## Classifier (Jev)

`COSECRE_TYPESAFE_API_KEY` (a Fly secret) turns on TypeSafe's Jev as a second
opinion on document type, payment status and payment method. Without it the
vision model decides alone, unflagged. Keys: https://console.typesafe.ai/keys.

## Parallel extraction

Up to `COSECRE_EXTRACTION_CONCURRENCY` documents (default 4) are read at once.
Each read is ~10–20 s spent waiting on the model API, so the limit protects API
rate limits and memory rather than the single CPU: measured during a migration,
the hub used ~215 MiB of the 1 GB machine with ~570 MiB free. A migration's
re-reading uses every slot but one, so a photo taken meanwhile starts at once.

## Download a backup

Run `just backup` from this repository with Fly CLI authenticated and the app
running. It saves a timestamped `.tar.gz` plus a SHA-256 checksum in `backups/`
(gitignored, owner-only file permissions). Requires `uv`, `fly`, and `just`.

The archive contains `cosecre.db`, `uploads/`, and `manifest.json`. SQLite's online
backup API makes a consistent database copy without stopping the app. The download
is checksum-verified and the copied database passes an integrity check before it
is marked complete. Temporary remote backup files are removed afterwards.
Failures leave any partial download labelled `.partial` for diagnosis.

Uploaded files are copied after the database snapshot: avoid uploads/deletions
during a backup if you need an exact database-and-files point in time. The manifest
reports references whose files were already missing. Credentials and Fly secrets
are excluded; provision those separately when restoring. Store the archive safely:
it contains account password hashes and private documents and is not encrypted.

To restore, extract into a private staging directory, validate the database, and
copy `cosecre.db` and `uploads/` onto a recovery volume mounted at `/data` while the
app is stopped. Keep the original volume until the restored deployment is verified.
Local restores must rewrite stored file paths or preserve the `/data/uploads` path.

## Initial migration

Source: `backend/data`, with 7 users and 53 upload records. SQLite's backup API
creates a consistent copy; stored upload paths are rewritten to `/data/uploads`.
Existing password hashes are retained, refresh sessions cleared, and a new signing
key forces clients to sign in again. All available source uploads are copied.
Upload ID 6 has a pre-existing missing source file; its record is retained.

Do not continue writing to the old local deployment after cutover: those changes
will not sync to Fly. The local source remains intact as a migration fallback.

References: https://fly.io/docs/volumes/overview/ and
https://fly.io/docs/volumes/snapshots/
