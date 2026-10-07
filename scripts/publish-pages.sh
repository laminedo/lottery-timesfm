#!/usr/bin/env bash
# Build the read-only demo and publish it to GitHub Pages (the gh-pages branch), beside the prototype.
#
#   scripts/publish-pages.sh              export a fresh data snapshot, build, publish
#   scripts/publish-pages.sh --no-push    stop after assembling the site in .pages-build/site
#   scripts/publish-pages.sh --no-export  reuse the snapshot already in web/public/data
#
# The published site is:   /            the original prototype (index.html, public/)
#                          /app/        the static build of web/, reading /app/data/*.json
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [ -d "$ROOT/.tools/node/bin" ]; then export PATH="$ROOT/.tools/node/bin:$PATH"; fi
export NEXT_TELEMETRY_DISABLED=1

PUSH=1
EXPORT=1
for arg in "$@"; do
  case "$arg" in
    --no-push) PUSH=0 ;;
    --no-export) EXPORT=0 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

# GitHub Pages serves a project site under /<repository name>/.
REPO_NAME="$(basename -s .git "$(git remote get-url origin)")"
APP_DIR="app"
SITE="$ROOT/.pages-build/site"
WORK="$ROOT/.pages-build/gh-pages"

if [ "$EXPORT" = 1 ]; then
  echo "==> Exporting the data snapshot (backtests are forecast with the model the first time)"
  (cd backend && uv run --all-extras python -m app.cli export-static ../web/public/data)
fi
if [ ! -f web/public/data/health.json ]; then
  echo "No snapshot in web/public/data. Run without --no-export first." >&2
  exit 1
fi

echo "==> Building the static web app for /$REPO_NAME/$APP_DIR"
(cd web && NEXT_PUBLIC_BASE_PATH="/$REPO_NAME/$APP_DIR" npm run build:static)

echo "==> Assembling the site"
rm -rf "$SITE"
mkdir -p "$SITE"
cp index.html .nojekyll "$SITE/"   # .nojekyll: Pages must serve the _next/ folder as it is
cp -R public "$SITE/public"
cp -R web/out "$SITE/$APP_DIR"

if [ "$PUSH" = 0 ]; then
  echo "Site assembled in $SITE (not published)"
  exit 0
fi

echo "==> Publishing to the gh-pages branch"
git worktree remove --force "$WORK" 2>/dev/null || true
if git ls-remote --exit-code --heads origin gh-pages >/dev/null 2>&1; then
  git fetch --quiet origin gh-pages
  git worktree add --quiet -B gh-pages "$WORK" origin/gh-pages
  git -C "$WORK" rm -r --quiet --ignore-unmatch .
else
  git worktree add --quiet --detach "$WORK"
  git -C "$WORK" checkout --quiet --orphan gh-pages
  git -C "$WORK" rm -r --quiet --force --ignore-unmatch .
fi
cp -R "$SITE"/. "$WORK"/
git -C "$WORK" add -A
if git -C "$WORK" diff --cached --quiet; then
  echo "Nothing changed since the last publish."
else
  SNAPSHOT="$(python3 -c "import json; print(json.load(open('web/public/data/health.json'))['exported_at'][:10])")"
  # PUBLISH_TRAILER, when set, is appended to the commit message (for example a Co-Authored-By line).
  git -C "$WORK" commit --quiet -m "Publish demo (snapshot $SNAPSHOT, built from $(git rev-parse --short HEAD))" \
    ${PUBLISH_TRAILER:+-m "$PUBLISH_TRAILER"}
  git -C "$WORK" push --quiet origin gh-pages
  echo "Published. GitHub Pages updates within a minute or two."
fi
git worktree remove --force "$WORK"
