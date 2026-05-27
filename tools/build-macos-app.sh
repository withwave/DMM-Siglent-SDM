#!/bin/bash
# Build "Siglent SDM Web.app" as a real macOS .app bundle.
#
# After running this, drag the resulting .app into /Applications (or
# leave it in the repo root) and launch it from Spotlight / Dock /
# Finder like any other Mac app. The bundle is a thin wrapper that
# cd's to this project directory and runs run.sh - so updating the
# repo automatically updates the app.
#
# Usage:
#   ./tools/build-macos-app.sh                    # writes ./Siglent SDM Web.app
#   ./tools/build-macos-app.sh /Applications      # writes there directly
set -euo pipefail

PROJECT_ROOT=$(cd "$(dirname "$0")/.." && pwd)
APP_NAME="Siglent SDM Web"
DEST_DIR="${1:-$PROJECT_ROOT}"
APP="${DEST_DIR%/}/${APP_NAME}.app"

if [ -d "$APP" ]; then
  echo "[build] removing existing $APP"
  rm -rf "$APP"
fi

mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# Info.plist — minimum keys for a UI app that owns its dock icon.
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>${APP_NAME}</string>
  <key>CFBundleDisplayName</key><string>${APP_NAME}</string>
  <key>CFBundleIdentifier</key><string>org.withwave.siglent-sdm-web</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>run</string>
  <key>CFBundleIconFile</key><string>icon</string>
  <key>LSMinimumSystemVersion</key><string>10.15</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSAppTransportSecurity</key>
  <dict>
    <key>NSAllowsLocalNetworking</key><true/>
  </dict>
</dict>
</plist>
PLIST

# Launcher script that lives inside the bundle and calls back into the
# project's run.sh. Using an absolute path means the .app keeps working
# wherever the user moves it (Applications, Desktop, etc.) as long as
# the project itself stays put.
cat > "$APP/Contents/MacOS/run" <<EOF
#!/bin/bash
cd "$PROJECT_ROOT"
exec ./run.sh
EOF
chmod +x "$APP/Contents/MacOS/run"

# Icon: convert the SVG/PNG to .icns if iconutil is available, else
# just drop a PNG fallback (macOS handles this gracefully).
ICONSET="$(mktemp -d)/icon.iconset"
mkdir -p "$ICONSET"
SRC_PNG="$PROJECT_ROOT/web/icon-128.png"
if command -v sips >/dev/null 2>&1 && command -v iconutil >/dev/null 2>&1; then
  for size in 16 32 64 128 256 512; do
    sips -z $size $size "$SRC_PNG" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null 2>&1 || true
    double=$((size * 2))
    sips -z $double $double "$SRC_PNG" --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null 2>&1 || true
  done
  if iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/icon.icns" 2>/dev/null; then
    echo "[build] created icon.icns"
  else
    cp "$SRC_PNG" "$APP/Contents/Resources/icon.png"
  fi
else
  cp "$SRC_PNG" "$APP/Contents/Resources/icon.png"
fi

# Touch so Finder/LaunchServices notices the new bundle.
touch "$APP"

echo "[build] $APP"
echo "[build] open with: open \"$APP\""
echo "[build] move to Applications: mv \"$APP\" /Applications/"
