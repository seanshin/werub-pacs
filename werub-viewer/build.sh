#!/bin/bash
# WeRU.B Viewer Build Script
# Clones OHIF source, applies WeRU.B branding, builds static files
# Does NOT modify existing OHIF installation
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OHIF_VERSION="v3.12.0"
SRC_DIR="$SCRIPT_DIR/.ohif-src"

echo "============================================="
echo "  WeRU.B Viewer Build"
echo "  OHIF base: $OHIF_VERSION"
echo "============================================="

# 1. Clone OHIF source (if not already cloned)
if [ ! -d "$SRC_DIR" ]; then
  echo "[1/7] Cloning OHIF Viewers $OHIF_VERSION ..."
  git clone --depth 1 --branch "$OHIF_VERSION" \
    https://github.com/OHIF/Viewers.git "$SRC_DIR" 2>/dev/null || \
  git clone --depth 1 https://github.com/OHIF/Viewers.git "$SRC_DIR"
else
  echo "[1/7] Using cached OHIF source"
fi

cd "$SRC_DIR"

# 2. Apply WeRU.B branding assets
echo "[2/7] Applying WeRU.B branding..."
cp "$SCRIPT_DIR/branding/werub-logo.svg" platform/app/public/ 2>/dev/null || true
cp "$SCRIPT_DIR/branding/werub-logo-dark.svg" platform/app/public/ 2>/dev/null || true
cp "$SCRIPT_DIR/branding/"werub-favicon* platform/app/public/ 2>/dev/null || true
cp "$SCRIPT_DIR/branding/"werub-apple* platform/app/public/ 2>/dev/null || true

# 3. Apply WeRU.B config
echo "[3/7] Applying WeRU.B config..."
cp "$SCRIPT_DIR/config/werub-app-config.js" platform/app/public/config/default.js

# 4. Apply Korean translation
echo "[4/7] Applying Korean locale..."
if [ -f "$SCRIPT_DIR/i18n/ko-KR.json" ]; then
  # Method A: Split into namespace files for OHIF's i18n system
  I18N_DIR="platform/i18n/src/locales/ko-KR"
  mkdir -p "$I18N_DIR"
  python3 -c "
import json, os
with open('$SCRIPT_DIR/i18n/ko-KR.json') as f:
    data = json.load(f)
outdir = '$I18N_DIR'
for ns, vals in data.items():
    with open(os.path.join(outdir, ns + '.json'), 'w', encoding='utf-8') as out:
        json.dump(vals, out, ensure_ascii=False, indent=2)
    print(f'  -> {ns}.json ({len(vals)} keys)')
# Generate index.js that exports all namespaces
namespaces = list(data.keys())
lines = []
for ns in namespaces:
    lines.append(f\"import {ns} from './{ns}.json';\")
lines.append('')
lines.append(\"export default {\")
lines.append(\"  'ko-KR': {\")
for ns in namespaces:
    lines.append(f'    {ns},')
lines.append('  },')
lines.append('};')
with open(os.path.join(outdir, 'index.js'), 'w') as out:
    out.write('\n'.join(lines) + '\n')
print(f'  -> index.js ({len(namespaces)} namespaces)')
"
  # Register ko-KR in OHIF's i18n locale index
  LOCALE_INDEX="platform/i18n/src/locales/index.js"
  if [ -f "$LOCALE_INDEX" ] && ! grep -q 'ko_KR' "$LOCALE_INDEX" 2>/dev/null; then
    echo "  -> Registering ko-KR in $LOCALE_INDEX"
    sed -i.bak "s|import test_lng from './test-LNG/';|import test_lng from './test-LNG/';\nimport ko_KR from './ko-KR/';|" "$LOCALE_INDEX"
    sed -i.bak "s|\.\.\\.test_lng,|...test_lng,\n  ...ko_KR,|" "$LOCALE_INDEX"
    rm -f "${LOCALE_INDEX}.bak"
  fi

  # Method B: Also copy as single translation.json (fallback for runtime loading)
  mkdir -p platform/app/public/locales/ko-KR/
  cp "$SCRIPT_DIR/i18n/ko-KR.json" platform/app/public/locales/ko-KR/translation.json
fi

# 5. Apply source patches (formatDate, formatPN, WorkList, AboutModal, etc.)
echo "[5/8] Applying source patches..."
if [ -f "$SCRIPT_DIR/patches/werub-source.patch" ]; then
  git apply --whitespace=nowarn "$SCRIPT_DIR/patches/werub-source.patch" 2>/dev/null && \
    echo "  -> Source patch applied" || \
    echo "  -> Patch already applied or conflicts (skipping)"
fi

# 6. Apply OHIF extensions (source-level, built into bundle)
echo "[6/9] Copying OHIF extensions..."
for ext in werub-report werub-ai; do
  if [ -d "$SCRIPT_DIR/extensions/$ext" ]; then
    # rm first: `cp -r src dest` nests into dest/src when dest already exists
    rm -rf "extensions/$ext"
    cp -r "$SCRIPT_DIR/extensions/$ext" "extensions/$ext"
    echo "  -> $ext extension copied"
  fi
done

# 6b. OHIF modes: the WeRU.B reading workflow uses the patched longitudinal mode
# (route /viewer — what all backend viewer_url links point to). The separate
# werub-reading mode was unused (route /reading, never linked) and was removed.

# 6c. Legacy JS extensions no longer needed (replaced by OHIF Extension)
# Old report-panel.js is now built-in as werub-report extension

# 7. Change HTML title
echo "[7/9] Updating HTML title..."
find platform/app -name "*.html" -exec \
  sed -i.bak 's/<title>OHIF Viewer<\/title>/<title>WeRU.B Viewer<\/title>/g' {} + 2>/dev/null || true
find platform/app -name "*.html.bak" -delete 2>/dev/null || true

# 8. Install + Build
echo "[8/9] Installing dependencies..."
yarn install --frozen-lockfile 2>/dev/null || yarn install

echo "[9/9] Building (this may take 5-10 minutes)..."
# NX_SKIP_NX_CACHE: Nx caches build:viewer but does NOT hash extensions/*/src as
# inputs (extensions load via pluginConfig, not as graph deps) → stale-cache replays
# old bundles when only an extension changed. Skip cache to guarantee a real rebuild.
NX_SKIP_NX_CACHE=true QUICK_BUILD=true PUBLIC_URL=/werub-viewer/ yarn run build

# Copy build output
echo ""
echo "Copying build to $SCRIPT_DIR/dist ..."
rm -rf "$SCRIPT_DIR/dist"
cp -r platform/app/dist "$SCRIPT_DIR/dist"

# Copy license
cp "$SCRIPT_DIR/LICENSE" "$SCRIPT_DIR/dist/"

echo ""
echo "============================================="
echo "  WeRU.B Viewer build COMPLETE"
echo "  Output: $SCRIPT_DIR/dist/"
echo "  Next: docker build -t openpacs-werub ."
echo "============================================="
