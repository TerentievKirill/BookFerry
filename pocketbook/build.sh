#!/usr/bin/env bash
# Cross-compile BookFerry InkView client with the pinned SDK used by CoolReader.
set -euo pipefail
cd "$(dirname "$0")/.."

SDK_URL="https://github.com/Sean-on-Git/PocketBook-SDK/releases/download/6.10/SDK-B288-6.10.7z"
SDK_SHA256="18405fb276535d53a4b70d2bbf4033313cded58da5002d563ccf7e1838440c0b"
CACHE="${PB_SDK_CACHE:-$PWD/work/downloads}"
SDK_ROOT="${PB_SDK_ROOT:-$PWD/work/sdk}"
SDK="$SDK_ROOT/SDK-B288-6.10"
PREFIX="$SDK/usr/bin/arm-obreey-linux-gnueabi"
TARGET="${PB_TARGET:-pb632-fw6}"
case "$TARGET" in
  pb632-fw6) FLAGS="-mcpu=cortex-a7 -mfpu=neon-vfpv4 -mfloat-abi=softfp" ;;
  pocketbook-armv7-softfp) FLAGS="-march=armv7-a -mtune=cortex-a7 -mfpu=neon -mfloat-abi=softfp" ;;
  *) echo "Unknown target: $TARGET" >&2; exit 2 ;;
esac
mkdir -p "$CACHE" "$SDK_ROOT" dist
ARCHIVE="$CACHE/SDK-B288-6.10.7z"
if [[ ! -f "$ARCHIVE" ]]; then
  curl --fail --location --retry 3 "$SDK_URL" -o "$ARCHIVE.part"
  mv "$ARCHIVE.part" "$ARCHIVE"
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
test -f "$SYSROOT/usr/include/inkview.h" || {
  echo "InkView headers not found in SDK sysroot" >&2
  exit 1
}
# Shell word splitting on the fixed, locally defined compiler flags is intentional.
# shellcheck disable=SC2086
"$PREFIX-gcc" --sysroot="$SYSROOT" $FLAGS -fsigned-char -DPLATFORM_FC -fcommon \
  -O2 -std=gnu11 -Wall -Wextra -Wno-unused-parameter \
  -I"$SYSROOT/usr/include" pocketbook/main.c -o "dist/BookFerry.app" \
  -L"$SYSROOT/usr/lib" -linkview
"$PREFIX-strip" "dist/BookFerry.app"
file "dist/BookFerry.app"
"$PREFIX-readelf" -h "dist/BookFerry.app" | grep -q 'Machine:.*ARM'
"$PREFIX-readelf" -A "dist/BookFerry.app" > "dist/elf-attributes.txt"
(
  cd dist
  zip -q -9 "BookFerry-$TARGET.zip" BookFerry.app
)
echo "Built dist/BookFerry-$TARGET.zip"
