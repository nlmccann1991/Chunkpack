#!/usr/bin/env bash
# Linux: fetches the pinned toolchain into .tools/ (no sudo, ~/.wine untouched)
#   .tools/zig   Zig 0.16.0 - cross-compiles helper/chunkhelper.dll
#   .tools/wine  private Wine prefix with Inno Setup 6.7.3 at C:\InnoSetup
# Needs: curl, tar, sha256sum, wine.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
tools="$root/.tools"
mkdir -p "$tools/dl"

fetch() {  # url file sha256
    [ -f "$tools/dl/$2" ] || curl -fsSL -o "$tools/dl/$2" "$1"
    echo "$3  $tools/dl/$2" | sha256sum -c --quiet
}

fetch https://ziglang.org/download/0.16.0/zig-x86_64-linux-0.16.0.tar.xz zig.tar.xz \
    70e49664a74374b48b51e6f3fdfbf437f6395d42509050588bd49abe52ba3d00
fetch https://github.com/jrsoftware/issrc/releases/download/is-6_7_3/innosetup-6.7.3.exe innosetup-6.7.3.exe \
    9c73c3bae7ed48d44112a0f48e66742c00090bdb5bef71d9d3c056c66e97b732

if [ ! -x "$tools/zig/zig" ]; then
    tar -xf "$tools/dl/zig.tar.xz" -C "$tools"
    mv "$tools/zig-x86_64-linux-0.16.0" "$tools/zig"
fi

export WINEPREFIX="$tools/wine" WINEDEBUG=-all WINEDLLOVERRIDES="mscoree,mshtml="
if [ ! -f "$WINEPREFIX/drive_c/InnoSetup/ISCC.exe" ]; then
    wineboot -i >/dev/null 2>&1
    wine "$tools/dl/innosetup-6.7.3.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CURRENTUSER '/DIR=C:\InnoSetup'
    wineserver -w
fi

"$root/helper/build.sh"
echo "tools ready in $tools"
