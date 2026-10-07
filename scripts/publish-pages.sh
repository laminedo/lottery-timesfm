#!/usr/bin/env bash
# Rebuild the hosted site and publish it to GitHub Pages (the gh-pages branch).
#
# This is the whole "server" of the hosted app. It runs on a schedule in GitHub Actions
# (.github/workflows/update-site.yml) and can be run by hand from a machine with the app set up:
#
#   1. fetch new draws and jackpot estimates from the official sources
#   2. bring back the state the last run left on the site (model output already computed)
#   3. run TimesFM for anything not yet forecast, and export the data the site reads
#   4. build the web app as static files
#   5. publish: the original prototype at /, the app at /app/, the state for next time at /_state/
#
#   scripts/publish-pages.sh              all of the above
#   scripts/publish-pages.sh --no-push    stop after step 4, leaving the site in .pages-build/site
#   scripts/publish-pages.sh --no-refresh skip step 1 (work offline from the draws already stored)
#   scripts/publish-pages.sh --no-export  skip steps 1-3 and reuse the data in web/public/data
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [ -d "$ROOT/.tools/node/bin" ]; then export PATH="$ROOT/.tools/node/bin:$PATH"; fi
export NEXT_TELEMETRY_DISABLED=1

PUSH=1
EXPORT=1
REFRESH=1
for arg in "$@"; do
  case "$arg" in
    --no-push) PUSH=0 ;;
    --no-export) EXPORT=0 ;;
    --no-refresh) REFRESH=0 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

# GitHub Pages serves a project site at https://<owner>.github.io/<repository>/.
REMOTE="$(git remote get-url origin)"
REMOTE="${REMOTE%.git}"
REPO_NAME="${REMOTE##*/}"
OWNER="${REMOTE%/*}"
OWNER="${OWNER##*[:/]}"
SITE_URL="https://$OWNER.github.io/$REPO_NAME"
APP_DIR="app"
BUILD="$ROOT/.pages-build"
SITE="$BUILD/site"
WORK="$BUILD/gh-pages"
STATE="$BUILD/state.json.gz"
cli() { (cd backend && uv run --all-extras python -m app.cli "$@"); }

mkdir -p "$BUILD"
if [ "$EXPORT" = 1 ]; then
  if [ "$REFRESH" = 1 ]; then
    echo "==> Fetching new draws"
    cli refresh
  fi

  # After the draws are in: a stored model output is only reused if its draw is in the database.
  echo "==> Restoring state from the live site"
  if curl -fsSL --max-time 120 -o "$STATE.download" "$SITE_URL/_state/state.json.gz"; then
    mv "$STATE.download" "$STATE"
  else
    rm -f "$STATE.download"
    echo "    none found (first publish, or the site is unreachable)"
  fi
  cli import-state "$STATE"

  echo "==> Forecasting and exporting the site data"
  cli export-static ../web/public/data
  cli export-state "$STATE"
fi
if [ ! -f web/public/data/health.json ]; then
  echo "No data in web/public/data. Run without --no-export first." >&2
  exit 1
fi

echo "==> Building the web app for $SITE_URL/$APP_DIR/"
(cd web && NEXT_PUBLIC_BASE_PATH="/$REPO_NAME/$APP_DIR" npm run build:static)

echo "==> Assembling the site"
rm -rf "$SITE"
mkdir -p "$SITE"
cp index.html .nojekyll "$SITE/"   # .nojekyll: Pages must serve folders that start with "_" as they are
cp -R public "$SITE/public"
cp -R web/out "$SITE/$APP_DIR"
if [ -f "$STATE" ]; then
  mkdir -p "$SITE/_state"
  cp "$STATE" "$SITE/_state/state.json.gz"
fi

if [ "$PUSH" = 0 ]; then
  echo "Site assembled in $SITE (not published)"
  exit 0
fi

echo "==> Publishing to the gh-pages branch"
# The branch holds one commit, replaced on every publish: it is build output, and keeping each
# version would grow the repository by megabytes a day.
git worktree remove --force "$WORK" 2>/dev/null || true
git branch -D pages-build >/dev/null 2>&1 || true
git worktree add --quiet --detach "$WORK"
git -C "$WORK" checkout --quiet --orphan pages-build
git -C "$WORK" rm -r --quiet --force --ignore-unmatch .
cp -R "$SITE"/. "$WORK"/
git -C "$WORK" add -A
UPDATED="$(python3 -c "import json; print(json.load(open('web/public/data/health.json'))['exported_at'])")"
# PUBLISH_TRAILER, when set, is appended to the commit message (for example a Co-Authored-By line).
git -C "$WORK" commit --quiet -m "Publish site (data as of $UPDATED, built from $(git rev-parse --short HEAD))" \
  ${PUBLISH_TRAILER:+-m "$PUBLISH_TRAILER"}
git -C "$WORK" push --quiet --force origin HEAD:gh-pages
git worktree remove --force "$WORK"
git branch -D pages-build >/dev/null 2>&1 || true
echo "Published. GitHub Pages serves it at $SITE_URL/$APP_DIR/ within a minute or two."
