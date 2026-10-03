---
name: ship
description: Ship a Cosecre change to production. Use when asked to deploy, push, release, "subir a fly" or "push into main" for this repo — it commits on main in the cosecre-main worktree, checks it, pushes, and follows the GitHub Actions deploy to Fly (app cosecre-aitirga) until /healthz answers.
---

# Ship to Fly

Production is `cosecre-aitirga` on Fly. Nobody runs `fly deploy` by hand: a push
to `main` runs `.github/workflows/deploy.yml` (hub tests, typecheck, then
`flyctl deploy --remote-only`). Shipping means getting a clean commit onto
`main` and watching that workflow through.

## 1. Work on main, in the main worktree

- `main` is checked out at `../cosecre-main` (next to the `cosecre` checkout,
  which is usually on a feature branch). Make and commit the change there.
- Never commit files you did not touch; the feature checkout often has the
  user's own uncommitted edits.

## 2. Check before pushing — the same gates CI runs

```bash
cd ../cosecre-main/hub && uv run --locked pytest -q
```

```bash
cd ../cosecre-main && npm run typecheck
```

If the change shows in the web app, look at it running first. The user's own
dev server usually holds :5173/:8000, so run a throwaway one beside it, from an
env file in the session scratchpad:

```
COSECRE_DATABASE_URL=sqlite:///<scratch>/hubdata/cosecre.db
COSECRE_UPLOAD_DIR=<scratch>/hubdata/uploads
COSECRE_PORT=8100
COSECRE_HUB_URL=http://127.0.0.1:8100
COSECRE_FRONTEND_PORT=5174
COSECRE_BOOTSTRAP_ADMIN_EMAIL=admin@example.com   # .localhost/.test fail email validation
COSECRE_BOOTSTRAP_ADMIN_PASSWORD=<generated>
```

Start both through a `.claude/launch.json` entry (`set -a; . <env>; set +a;
(cd hub && uv run cosecre-hub) & npm run dev:web`), seed the rows the screen
needs with the hub's own models (`uv run python seed.py`), and screenshot it.
Never point a local hub at production data or at the production Google Sheet.

## 3. Commit and push

- Conventional subject (`feat(web): …`, `fix(hub): …`), body says why.
- `git push origin main`.

## 4. Follow the deploy

```bash
gh run list --workflow deploy.yml --branch main --limit 1
```

```bash
gh run watch <run-id> --exit-status
```

Then confirm the app is up:

```bash
curl -fsS https://cosecre-aitirga.fly.dev/healthz
```

If the workflow fails, read the failing step's log (`gh run view <id> --log-failed`),
fix on main, and push again. Report the run URL and the health result.
