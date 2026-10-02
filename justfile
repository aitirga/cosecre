# Cosecre task runner.
#
#   just            list everything
#   just setup      first run
#   just dev        hub + web, the usual working session
#   just mac        build a DMG for this Mac and open it
#
# Recipes are grouped, so `just --list` reads the same way this file does.

set shell := ["bash", "-euo", "pipefail", "-c"]

# The app's own palette, as 256-colour terminal codes: terracotta accent,
# olive, gold. Output that matches the product is easier to scan than output
# that shouts.
_r := '\033[0m'
_b := '\033[1m'
_d := '\033[2m'
_acc := '\033[38;5;173m'
_olive := '\033[38;5;65m'
_gold := '\033[38;5;179m'
_err := '\033[38;5;167m'

# electron-builder needs to be told which slice to build. Building only the
# architecture you are sitting at turns a five-minute package into about one.
_arch := if arch() == "x86_64" { "--x64" } else { "--arm64" }
_version := `node -p "require('./desktop/package.json').version" 2>/dev/null || echo "?"`

[private]
default:
    #!/usr/bin/env bash
    printf '%b\n' ""
    printf '%b\n' "  {{_b}}{{_acc}}Cosecre{{_r}} {{_d}}{{_version}}{{_r}}   {{_d}}hub · web · desktop{{_r}}"
    printf '%b\n' ""
    printf '%b\n' "  {{_b}}{{_gold}}SETUP{{_r}}"
    printf '%b\n' "    {{_olive}}just setup{{_r}}          install dependencies and create hub/.env"
    printf '%b\n' "    {{_olive}}just doctor{{_r}}         check the toolchain is complete"
    printf '%b\n' ""
    printf '%b\n' "  {{_b}}{{_gold}}DEVELOP{{_r}}"
    printf '%b\n' "    {{_olive}}just dev{{_r}}            {{_acc}}hub + web together{{_r}} — the usual one"
    printf '%b\n' "    {{_olive}}just hub{{_r}}            the API server alone      {{_d}}:8000{{_r}}"
    printf '%b\n' "    {{_olive}}just web{{_r}}            the web client alone      {{_d}}:5173{{_r}}"
    printf '%b\n' "    {{_olive}}just app{{_r}}            the desktop app           {{_d}}needs a hub running{{_r}}"
    printf '%b\n' "    {{_olive}}just docs{{_r}}           open the hub's API docs"
    printf '%b\n' ""
    printf '%b\n' "  {{_b}}{{_gold}}CHECK{{_r}}"
    printf '%b\n' "    {{_olive}}just check{{_r}}          typecheck and tests, everything"
    printf '%b\n' "    {{_olive}}just test{{_r}}           hub test suite            {{_d}}no network, no keys{{_r}}"
    printf '%b\n' "    {{_olive}}just types{{_r}}          typecheck both clients"
    printf '%b\n' ""
    printf '%b\n' "  {{_b}}{{_gold}}BUILD{{_r}}"
    printf '%b\n' "    {{_olive}}just build{{_r}}          bundle the web and desktop apps"
    printf '%b\n' "    {{_olive}}just icons{{_r}}          regenerate the icon from brand/icon.svg"
    printf '%b\n' "    {{_olive}}just clean{{_r}}          delete build output"
    printf '%b\n' ""
    printf '%b\n' "  {{_b}}{{_gold}}PACKAGE{{_r}}"
    printf '%b\n' "    {{_olive}}just mac{{_r}}            {{_acc}}DMG for this Mac, then open it{{_r}}"
    printf '%b\n' "    {{_olive}}just install{{_r}}        skip the DMG — copy straight to /Applications"
    printf '%b\n' "    {{_olive}}just mac-all{{_r}}        both architectures, DMG + zip {{_d}}(what CI builds){{_r}}"
    printf '%b\n' "    {{_olive}}just linux{{_r}}          AppImage"
    printf '%b\n' "    {{_olive}}just win{{_r}}            NSIS installer            {{_d}}must run on Windows{{_r}}"
    printf '%b\n' ""
    printf '%b\n' "  {{_b}}{{_gold}}RELEASE{{_r}}"
    printf '%b\n' "    {{_olive}}just release 0.1.2{{_r}}  bump, tag and push — CI builds and publishes"
    printf '%b\n' "    {{_olive}}just ci{{_r}}             watch the release build"
    printf '%b\n' "    {{_olive}}just releases{{_r}}       open the releases page"
    printf '%b\n' ""

# ── Setup ────────────────────────────────────────────────────────────────────

[group('setup')]
[doc('Install dependencies and create hub/.env')]
setup:
    #!/usr/bin/env bash
    set -euo pipefail
    printf '%b\n' "{{_acc}}→{{_r}} npm workspaces"
    npm install
    printf '%b\n' "{{_acc}}→{{_r}} hub (uv)"
    cd hub && uv sync
    cd ..
    if [ ! -f hub/.env ]; then
      cp hub/.env.example hub/.env
      printf '%b\n' "{{_gold}}✎{{_r}} created {{_b}}hub/.env{{_r}} — set COSECRE_SECRET_KEY, COSECRE_OPENAI_API_KEY"
      printf '%b\n' "  and the two COSECRE_BOOTSTRAP_ADMIN_* variables before {{_olive}}just dev{{_r}}"
    else
      printf '%b\n' "{{_d}}·{{_r}} hub/.env already exists, left alone"
    fi
    printf '%b\n' "{{_olive}}✓{{_r}} ready — {{_olive}}just dev{{_r}}"

[group('setup')]
[doc('Check the toolchain is complete')]
doctor:
    #!/usr/bin/env bash
    set -uo pipefail
    missing=0
    check() {
      if command -v "$1" >/dev/null 2>&1; then
        printf '%b\n' "  {{_olive}}✓{{_r}} $(printf '%-14s' "$1") {{_d}}$($2 2>&1 | head -1){{_r}}"
      else
        printf '%b\n' "  {{_err}}✗{{_r}} $(printf '%-14s' "$1") {{_d}}$3{{_r}}"
        missing=1
      fi
    }
    printf '%b\n' ""
    printf '%b\n' "  {{_b}}Required{{_r}}"
    check node    "node --version"           "install Node 22+"
    check npm     "npm --version"            "ships with Node"
    check uv      "uv --version"             "brew install uv"
    printf '%b\n' ""
    printf '%b\n' "  {{_b}}Optional{{_r}}"
    check rsvg-convert "rsvg-convert --version" "brew install librsvg — only for 'just icons'"
    check gh           "gh --version"           "brew install gh — only for 'just ci' and 'just release'"
    printf '%b\n' ""
    if [ -f hub/.env ]; then
      printf '%b\n' "  {{_olive}}✓{{_r}} hub/.env present"
    else
      printf '%b\n' "  {{_err}}✗{{_r}} hub/.env missing — run {{_olive}}just setup{{_r}}"
      missing=1
    fi
    printf '%b\n' ""
    exit $missing

# ── Develop ──────────────────────────────────────────────────────────────────

[group('operations')]
[doc('Download and verify a Fly database + documents backup into backups/')]
backup:
    uv run --no-project python scripts/backup.py

[group('operations')]
[doc('Show Fly worker RAM usage and its peak since startup')]
memory:
    uv run --no-project python scripts/fly_memory.py

[group('operations')]
[doc('Show Fly machine status and HTTP health checks')]
status:
    flyctl status -a cosecre-aitirga
    flyctl checks list -a cosecre-aitirga

[group('operations')]
[doc('Tail production logs on Fly')]
logs:
    flyctl logs -a cosecre-aitirga

[group('operations')]
[doc('Deploy the single persistent Fly machine after backend tests')]
deploy: test
    flyctl deploy --remote-only --ha=false --strategy immediate -a cosecre-aitirga

[group('develop')]
[doc('Run the production hub; honours COSECRE_IDLE_TIMEOUT_SECONDS')]
run:
    cd hub && uv run python -m cosecre_hub.server

[group('check')]
[doc('Test idle shutdown, background-job protection and clean process exit')]
test-idle:
    cd hub && uv run pytest tests/test_idle.py -q

[group('develop')]
[doc('Run the hub and the web client together')]
dev:
    #!/usr/bin/env bash
    set -uo pipefail
    # `kill 0` signals the whole process group, which is what actually stops
    # uvicorn's reloader and Vite's child processes on Ctrl-C. Killing the two
    # background PIDs alone leaves their children running and the ports held.
    trap 'kill 0' EXIT INT TERM
    printf '%b\n' "{{_acc}}▸{{_r}} hub {{_d}}http://127.0.0.1:8000{{_r}}   {{_acc}}▸{{_r}} web {{_d}}http://127.0.0.1:5173{{_r}}   {{_d}}Ctrl-C stops both{{_r}}"
    ( cd hub && uv run cosecre-hub ) &
    npm run dev:web &
    wait

[group('develop')]
[doc('Run the hub alone')]
hub:
    cd hub && uv run cosecre-hub

[group('develop')]
[doc('Run the web client alone')]
web:
    npm run dev:web

[group('develop')]
[doc('Run the desktop app (needs a hub running)')]
app:
    npm run dev:desktop

[group('develop')]
[doc("Open the hub's interactive API docs")]
docs:
    open http://127.0.0.1:8000/docs

# ── Check ────────────────────────────────────────────────────────────────────

[group('check')]
[doc('Typecheck and test everything')]
check: types test

[group('check')]
[doc('Run the hub test suite')]
test *ARGS:
    cd hub && uv run pytest {{ARGS}}

[group('check')]
[doc('Typecheck the web and desktop clients')]
types:
    npm run typecheck

# ── Build ────────────────────────────────────────────────────────────────────

[group('build')]
[doc('Bundle the web and desktop apps')]
build: bundle-web bundle-desktop

[private]
bundle-web:
    npm run build:web

[private]
bundle-desktop:
    npm run build:desktop

[group('build')]
[doc('Regenerate the app icon from brand/icon.svg')]
icons:
    npm run icons

[group('build')]
[doc('Delete build output')]
clean:
    #!/usr/bin/env bash
    set -euo pipefail
    rm -rf frontend/dist desktop/out desktop/release
    find . -name '*.tsbuildinfo' -not -path './node_modules/*' -delete
    printf '%b\n' "{{_olive}}✓{{_r}} cleaned {{_d}}frontend/dist · desktop/out · desktop/release{{_r}}"

# ── Package ──────────────────────────────────────────────────────────────────

[group('package')]
[doc('Build a DMG for this Mac and open it')]
mac: bundle-desktop
    #!/usr/bin/env bash
    set -euo pipefail
    printf '%b\n' "{{_acc}}→{{_r}} packaging {{_b}}{{_arch}}{{_r}} DMG {{_d}}(this Mac only — 'just mac-all' for both){{_r}}"
    cd desktop && npx electron-builder --mac dmg {{_arch}}

    # Newest match, without `ls | head`: under `pipefail`, head closing the pipe
    # early kills ls with SIGPIPE and takes the whole recipe down with it.
    dmg=""
    for f in release/*.dmg; do
      [ -e "$f" ] || continue
      if [ -z "$dmg" ] || [ "$f" -nt "$dmg" ]; then dmg="$f"; fi
    done
    if [ -z "$dmg" ]; then
      printf '%b\n' "{{_err}}✗{{_r}} electron-builder produced no .dmg"
      exit 1
    fi

    printf '%b\n' "{{_olive}}✓{{_r}} {{_b}}desktop/${dmg}{{_r}} {{_d}}($(du -h "$dmg" | cut -f1)){{_r}}"
    printf '%b\n' "{{_d}}  opening — drag Cosecre into Applications{{_r}}"
    open "$dmg"

[group('package')]
[doc('Build and copy straight into /Applications, no DMG')]
install: bundle-desktop
    #!/usr/bin/env bash
    set -euo pipefail
    printf '%b\n' "{{_acc}}→{{_r}} packaging {{_b}}{{_arch}}{{_r}} app bundle"
    cd desktop && npx electron-builder --dir {{_arch}}

    # Newest match, without `ls | head` — see the note in the `mac` recipe.
    app=""
    for f in release/mac*/Cosecre.app; do
      [ -d "$f" ] || continue
      if [ -z "$app" ] || [ "$f" -nt "$app" ]; then app="$f"; fi
    done
    if [ -z "$app" ]; then
      printf '%b\n' "{{_err}}✗{{_r}} electron-builder produced no app bundle"
      exit 1
    fi
    dest=/Applications/Cosecre.app

    # Refuse to replace anything that is not this app. A stray /Applications
    # entry with the same name would otherwise be silently destroyed.
    if [ -e "$dest" ]; then
      existing=$(defaults read "$dest/Contents/Info" CFBundleIdentifier 2>/dev/null || echo "")
      if [ "$existing" != "dev.aitirga.cosecre" ]; then
        printf '%b\n' "{{_err}}✗{{_r}} $dest exists and is not Cosecre (id: ${existing:-unknown}). Not touching it."
        exit 1
      fi
      rm -rf "$dest"
    fi

    cp -R "$app" "$dest"
    printf '%b\n' "{{_olive}}✓{{_r}} installed {{_b}}$dest{{_r}}"
    open "$dest"

[group('package')]
[doc('Build both Mac architectures, DMG + zip, as CI does')]
mac-all: bundle-desktop
    cd desktop && npx electron-builder --mac

[group('package')]
[doc('Build the Linux AppImage')]
linux: bundle-desktop
    cd desktop && npx electron-builder --linux

[group('package')]
[doc('Build the Windows installer (must run on Windows)')]
win: bundle-desktop
    cd desktop && npx electron-builder --win

# ── Release ──────────────────────────────────────────────────────────────────

[group('release')]
[doc('Bump versions, tag and push — CI builds and publishes')]
release VERSION:
    #!/usr/bin/env bash
    set -euo pipefail

    if [ -n "$(git status --porcelain)" ]; then
      printf '%b\n' "{{_err}}✗{{_r}} working tree is dirty — commit or stash first"
      exit 1
    fi
    if [ "$(git rev-parse --abbrev-ref HEAD)" != "main" ]; then
      printf '%b\n' "{{_err}}✗{{_r}} releases are cut from main"
      exit 1
    fi
    if git rev-parse "v{{VERSION}}" >/dev/null 2>&1; then
      printf '%b\n' "{{_err}}✗{{_r}} tag v{{VERSION}} already exists"
      exit 1
    fi

    printf '%b\n' "{{_acc}}→{{_r}} checking before tagging {{_d}}(a bad tag means a release nobody can install){{_r}}"
    just check

    # The tag has to match desktop/package.json: electron-builder writes that
    # version into latest*.yml, and electron-updater compares against it. A
    # mismatch produces a release no client is ever offered.
    node -e '
      const fs = require("fs");
      for (const p of ["package.json", "desktop/package.json", "frontend/package.json"]) {
        const j = JSON.parse(fs.readFileSync(p, "utf8"));
        j.version = "{{VERSION}}";
        fs.writeFileSync(p, JSON.stringify(j, null, 2) + "\n");
      }
    '
    npm install --package-lock-only --silent

    git commit -aqm "release: {{VERSION}}"
    git tag -a "v{{VERSION}}" -m "Cosecre {{VERSION}}"
    git push origin main --follow-tags
    printf '%b\n' "{{_olive}}✓{{_r}} v{{VERSION}} pushed — {{_olive}}just ci{{_r}} to watch the build"

[group('release')]
[doc('Watch the release build')]
ci:
    gh run watch --repo aitirga/cosecre "$(gh run list --repo aitirga/cosecre --limit 1 --json databaseId --jq '.[0].databaseId')"

[group('release')]
[doc('Open the releases page')]
releases:
    open https://github.com/aitirga/cosecre/releases
