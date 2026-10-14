#!/usr/bin/env bash
# Builds helper/build/chunkhelper.dll (x86, because Inno Setup 6's Setup is 32-bit).
# Uses the Zig toolchain from .tools/ (see scripts/setup_tools.sh) or $ZIG.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
zig="${ZIG:-$here/../.tools/zig/zig}"
mkdir -p "$here/build"
# The .def file strips stdcall decoration so Inno can import "MergeParts" by name.
"$zig" cc -target x86-windows-gnu -shared -O2 -s \
    -DMINIZ_NO_STDIO -DMINIZ_NO_ARCHIVE_APIS -DMINIZ_NO_TIME \
    "$here/chunkhelper.def" \
    -o "$here/build/chunkhelper.dll" \
    "$here/chunkhelper.c" "$here/third_party/miniz/miniz.c" \
    -ladvapi32
rm -f "$here/build/chunkhelper.lib" "$here/build/chunkhelper.pdb"
echo "built $here/build/chunkhelper.dll"
