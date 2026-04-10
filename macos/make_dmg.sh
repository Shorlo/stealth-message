#!/usr/bin/env bash
# make_dmg.sh — Builds StealthMessage.app (Release) and packages it as a DMG.
# Usage: bash make_dmg.sh
# Output: dist/StealthMessage-1.0.dmg

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR/StealthMessage"
PROJECT_FILE="$PROJECT_DIR/StealthMessage.xcodeproj"
SCHEME="StealthMessage"
VERSION="1.0"
DMG_NAME="StealthMessage-$VERSION"
DIST_DIR="$SCRIPT_DIR/dist"
STAGING_DIR="$DIST_DIR/dmg-staging"
BUILD_DIR="$DIST_DIR/build"
MOUNT_DIR="$DIST_DIR/dmg-mount"
FINAL_DMG="$DIST_DIR/$DMG_NAME.dmg"
TMP_DMG="$DIST_DIR/$DMG_NAME-tmp.dmg"

# ── 1. Build Release ──────────────────────────────────────────────────────────
echo "→ Building Release…"
xcodebuild \
  -project "$PROJECT_FILE" \
  -scheme "$SCHEME" \
  -configuration Release \
  -derivedDataPath "$BUILD_DIR" \
  ONLY_ACTIVE_ARCH=NO \
  clean build 2>&1 | grep -E "^(error:|warning:|Build succeeded|BUILD SUCCEEDED|BUILD FAILED)" || true

APP_PATH="$BUILD_DIR/Build/Products/Release/StealthMessage.app"

if [ ! -d "$APP_PATH" ]; then
  echo "✗ Build failed — app not found at $APP_PATH"
  exit 1
fi
echo "✓ Build succeeded: $APP_PATH"

# ── 1b. Ad-hoc code sign ─────────────────────────────────────────────────────
# Required so macOS allows the app to run on other machines (no paid dev account).
echo "→ Signing app (ad-hoc)…"
codesign --deep --force --sign - "$APP_PATH"
echo "✓ Signed"

# ── 2. Generate background image ─────────────────────────────────────────────
BG_DIR="$DIST_DIR/dmg-bg"
BG_IMG="$BG_DIR/background.png"
echo "→ Generating background image…"
mkdir -p "$BG_DIR"
swift "$SCRIPT_DIR/generate_dmg_bg.swift" "$BG_IMG"

# ── 3. Prepare staging folder ─────────────────────────────────────────────────
echo "→ Preparing staging folder…"
rm -rf "$STAGING_DIR"
mkdir -p "$STAGING_DIR/.background"
cp -R "$APP_PATH" "$STAGING_DIR/StealthMessage.app"
ln -s /Applications "$STAGING_DIR/Applications"
cp "$BG_IMG" "$STAGING_DIR/.background/background.png"

# ── 4. Create writable DMG ────────────────────────────────────────────────────
echo "→ Creating temporary writable DMG…"
rm -f "$TMP_DMG" "$FINAL_DMG"
hdiutil create \
  -srcfolder "$STAGING_DIR" \
  -volname "$DMG_NAME" \
  -fs HFS+ \
  -fsargs "-c c=64,a=16,b=16" \
  -format UDRW \
  -size 300m \
  "$TMP_DMG"

# ── 5. Mount and configure Finder view ───────────────────────────────────────
# Eject any stale mount with the same volume name
hdiutil detach "/Volumes/$DMG_NAME" -force 2>/dev/null || true
sleep 1
echo "→ Mounting DMG to set icon layout…"
MOUNT_DIR="$(hdiutil attach -readwrite -noverify -noautoopen "$TMP_DMG" \
  | awk '/Apple_HFS/{print $NF}')"
echo "  Mounted at: $MOUNT_DIR"
sleep 5

# Copy the app icon as the volume icon (.VolumeIcon.icns)
cp "$APP_PATH/Contents/Resources/AppIcon.icns" "$MOUNT_DIR/.VolumeIcon.icns"
SetFile -c icnC "$MOUNT_DIR/.VolumeIcon.icns" 2>/dev/null || true

osascript - "$MOUNT_DIR" "$DMG_NAME" <<'APPLESCRIPT'
on run argv
  set mountPath to item 1 of argv
  set diskName  to item 2 of argv
  set bgFile    to POSIX file (mountPath & "/.background/background.png")
  tell application "Finder"
    tell disk diskName
      open
      set current view of container window to icon view
      set toolbar visible of container window to false
      set statusbar visible of container window to false
      set the bounds of container window to {200, 120, 780, 430}
      set viewOptions to the icon view options of container window
      set arrangement of viewOptions to not arranged
      set icon size of viewOptions to 128
      set background picture of viewOptions to bgFile
      try
        set text color of viewOptions to {65535, 65535, 65535}
      end try
      set position of item "StealthMessage.app" of container window to {155, 130}
      set position of item "Applications"       of container window to {425, 130}
      delay 8
      close
    end tell
  end tell
end run
APPLESCRIPT
sync
sleep 3

# Set custom volume icon flag
SetFile -a C "$MOUNT_DIR" 2>/dev/null || true

# ── 6. Unmount and convert to read-only compressed DMG ───────────────────────
echo "→ Unmounting…"
hdiutil detach "$MOUNT_DIR" -force 2>/dev/null || diskutil unmount force "$MOUNT_DIR" 2>/dev/null || true
sleep 1
sleep 1

echo "→ Converting to read-only compressed DMG…"
hdiutil convert "$TMP_DMG" -format UDZO -imagekey zlib-level=9 -o "$FINAL_DMG"
rm -f "$TMP_DMG"

echo ""
echo "✓ Done: $FINAL_DMG"
echo "  $(du -sh "$FINAL_DMG" | cut -f1)  StealthMessage-$VERSION.dmg"
