# backend — superseded by [hub/](../hub)

> **This is the previous single-purpose server. It has been replaced by
> [`cosecre-hub`](../hub), and the web and desktop clients no longer talk to it.**

It is kept here, unchanged, only so a running deployment has something to fall
back to while it is migrated. New work goes in `hub/`.

## Migrating

The hub is schema-compatible with the database this server created — same
tables, same columns, everything it adds either nullable or defaulted — so it
adopts an existing `data/cosecre.db` with its users, uploads, jobs and workspace
settings intact. Point it at the file and copy the rest of `.env` across
unchanged; the env prefix is still `COSECRE_` precisely so that works.

Full instructions, including the endpoint renames clients need, are in
[hub/README.md](../hub/README.md#migrating-from-the-old-backend).

## ⚠ `seed_users.json`

This directory's `seed_users.json` held **plaintext passwords** and was committed
to a public repository. Every password that was ever in it should be treated as
compromised and rotated. The file is now gitignored, and the hub replaces the
mechanism with a bootstrap admin from the environment plus admin-managed accounts
(`POST /api/v1/users`).
