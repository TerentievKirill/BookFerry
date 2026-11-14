#!/usr/bin/env bash
# Cross-compile BookFerry InkView client with the pinned SDK used by CoolReader.
set -euo pipefail
cd "$(dirname "$0")/.."

# Use the firmware-matched SDK for older PocketBooks. Building for
# ARMv7 alone is insufficient if libinkview requires a newer firmware.
TARGET="${PB_TARGET:-pb632-fw6}"
CACHE="${PB_SDK_CACHE:-$PWD/work/downloads}"
SDK_ROOT="${PB_SDK_ROOT:-$PWD/work/sdk}"
SDK_PLATFORM="B288"

case "$TARGET" in
  pb632-fw6)
    SDK_VERSION="6.10"
    SDK_URL="https://github.com/Sean-on-Git/PocketBook-SDK/releases/download/6.10/SDK-B288-6.10.7z"
    SDK_SHA256="18405fb276535d53a4b70d2bbf4033313cded58da5002d563ccf7e1838440c0b"
    SDK_EXPECTED_BYTES="642311775"
    FLAGS="-mcpu=cortex-a7 -mfpu=neon-vfpv4 -mfloat-abi=softfp"
    ;;
  pocketbook-armv7-softfp)
    SDK_VERSION="6.10"
    SDK_URL="https://github.com/Sean-on-Git/PocketBook-SDK/releases/download/6.10/SDK-B288-6.10.7z"
    SDK_SHA256="18405fb276535d53a4b70d2bbf4033313cded58da5002d563ccf7e1838440c0b"
    SDK_EXPECTED_BYTES="642311775"
    FLAGS="-march=armv7-a -mtune=cortex-a7 -mfpu=neon -mfloat-abi=softfp"
    ;;
  pb618-fw68)
    SDK_VERSION="6.8"
    SDK_URL="https://github.com/pocketbook/SDK_6.3.0/releases/download/6.8/SDK-B288-6.8.7z"
    # SHA-256 verified from the downloaded official GitHub release archive.
    SDK_SHA256="b924fbeba90e9258854e910c2c29a3105e6fb9c6e0e6de4cb13a015be3fc23e2"
    SDK_EXPECTED_BYTES="1301230510"
    FLAGS="-march=armv7-a -mfpu=neon -mfloat-abi=softfp"
    ;;
  *)
    echo "Unknown target: $TARGET" >&2
    exit 2
    ;;
esac

# The upstream 6.8 archive has an unversioned SDK-B288 root directory.
if [[ "$SDK_VERSION" == "6.8" ]]; then
  SDK="$SDK_ROOT/SDK-$SDK_PLATFORM"
else
  SDK="$SDK_ROOT/SDK-$SDK_PLATFORM-$SDK_VERSION"
fi
PREFIX="$SDK/usr/bin/arm-obreey-linux-gnueabi"
mkdir -p "$CACHE" "$SDK_ROOT" dist
ARCHIVE="$CACHE/SDK-$SDK_PLATFORM-$SDK_VERSION.7z"
if [[ ! -f "$ARCHIVE" ]]; then
  curl --fail --location --retry 3 "$SDK_URL" -o "$ARCHIVE.part"
  mv "$ARCHIVE.part" "$ARCHIVE"
fi
if [[ "$(stat -c %s "$ARCHIVE")" != "$SDK_EXPECTED_BYTES" ]]; then
  echo "Unexpected SDK archive size: $ARCHIVE" >&2
  rm -f "$ARCHIVE"
  exit 1
fi
echo "$SDK_SHA256  $ARCHIVE" | sha256sum --check
if [[ ! -x "$PREFIX-gcc" ]]; then
  7z x -y "$ARCHIVE" "-o$SDK_ROOT" > /dev/null || {
    # 7zip can report warnings for safe SDK symlink entries.
    echo "7z reported warnings; checking SDK and restoring symlinks..." >&2
  }
  python3 pocketbook/repair_sdk_links.py "$ARCHIVE" "$SDK_ROOT"
fi
test -x "$PREFIX-gcc" || { echo "SDK compiler is missing" >&2; exit 1; }
SYSROOT="$SDK/usr/arm-obreey-linux-gnueabi/sysroot"
INKVIEW_HEADER="$(find "$SDK" -type f -name inkview.h -print -quit)"
INKVIEW_LIBRARY="$(find "$SDK" \( -type f -o -type l \) \( -name libinkview.so -o -name libinkview.a \) -print -quit)"
if [[ -z "$INKVIEW_HEADER" || -z "$INKVIEW_LIBRARY" ]]; then
  echo "InkView SDK headers or library not found" >&2
  exit 1
fi
echo "InkView header: $INKVIEW_HEADER"
echo "InkView library: $INKVIEW_LIBRARY"
# Shell word splitting on the fixed, locally defined compiler flags is intentional.
# shellcheck disable=SC2086
"$PREFIX-gcc" --sysroot="$SYSROOT" $FLAGS -fsigned-char -DPLATFORM_FC -fcommon \
  -O2 -std=gnu11 -Wall -Wextra -Wno-unused-parameter \
  -I"$(dirname "$INKVIEW_HEADER")" pocketbook/main.c -o "dist/BookFerry.app" \
  -L"$(dirname "$INKVIEW_LIBRARY")" -linkview
"$PREFIX-strip" "dist/BookFerry.app"
file "dist/BookFerry.app"
"$PREFIX-readelf" -h "dist/BookFerry.app" | grep -q 'Machine:.*ARM'
"$PREFIX-readelf" -A "dist/BookFerry.app" > "dist/elf-attributes.txt"
(
  cd dist
  zip -q -9 "BookFerry-$TARGET.zip" BookFerry.app
)
echo "Built dist/BookFerry-$TARGET.zip"
