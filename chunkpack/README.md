# chunkpack

Builds Windows installers that work like GOG's offline installers: a signed-able
`setup_<name>_(<build>).exe` plus `-1.bin`, `-2.bin`, … slices, with every file
shipped as Galaxy-style 10 MiB zlib parts that are reassembled and MD5-verified
during install. Linux users run the same installer through Faugus/Lutris/Proton.

## How it works

```
build time (Python)                          install time (Inno Setup 6 + chunkhelper.dll)
-------------------                          ----------------------------------------------
game/ ──► split each file into 10 MiB        setup.exe reads parts from the .bin slices
          blocks, zlib each block            ──► {tmp}\ab\cd\<md5>            (Inno checks its own checksum)
     ──► parts/ab/cd/<md5 of compressed>     ──► after the last part of a file:
          (deduplicated, cached)                  MergeParts() inflates in order, checks each
     ──► setup.iss: one [Files] entry per         part's MD5 and the whole file's MD5, writes
          part, GOG's hook signatures:            dest.cpk-tmp, renames to {app}\<file>,
          before_install('<file md5>',            deletes the parts
            '<path>', <parts>)               ──► on failure: Inno's Abort/Retry/Ignore error;
          after_install('<part md5>',             Abort (the default when silent) rolls back
            <csize>, <usize>)                     everything, exit code 5
     ──► ISCC: DiskSpanning, 4 GiB slices    ──► redists run, shortcuts + registry written,
                                                  uninstaller removes every merged file
```

This mirrors what the reference GOG installer does (see `research/` and the analysis
notes below), without any of GOG's proprietary pieces: the engine is stock Inno Setup,
the merge/verify DLL is ours (C + miniz), and nothing touches GOG Galaxy or GOG's
registry keys.

## Quick start (Linux)

```sh
scripts/setup_tools.sh                 # Zig + Inno Setup 6.7.3 in .tools/, builds the DLL
cp examples/manifest.toml mygame.toml  # edit it
python3 -m chunkpack build mygame.toml
```

Output lands in `dist/` next to the manifest. Work files (parts, `setup.iss`) go to
`build/<slug>/`; parts are cached, so rebuilding only recompresses changed files.
Delete that folder to reclaim space from old builds.

On Windows: install Inno Setup 6, build the DLL with `zig cc` (same flags as
`helper/build.sh`), then run the same `python -m chunkpack build` (Python 3.12+).
Set `CHUNKPACK_ISCC` if ISCC.exe is somewhere unusual.

## Manifest

See `examples/manifest.toml` for every option. Required: `[product]` id, name,
version, publisher, exe, and a `[source]` dir.

## Installed layout

```
<install dir>\
  ...your files...
  __redist\...                  redistributables from [[redist]]
  chunkpack-<id>.info           JSON: id, name, build, version, primary play task
  unins000.exe / .dat           Inno uninstaller
HKLM|HKCU\Software\<publisher>\Games\<id>   path, exe, launchParam, version, buildId…
```

## Testing

```sh
python3 tests/e2e.py
```

Builds a demo with awkward names (`it's {weird}; 100% name.txt`, Unicode,
`{#notispp}.txt`), an empty file and folder, exact-boundary and multi-part files,
duplicate content, an excluded file and a probe redist. It uses 8 MiB slices to
force 5 `.bin` files, then installs silently under Wine, compares every file's
hash, checks the redist, registry and `.info`, and uninstalls. It finally
corrupts one MD5 and checks that setup fails with full rollback.

## Known limits

- innoextract 1.9 cannot read Inno 6.7 installers (format is newer than it).
- `chunkhelper.dll` uses the Universal CRT: built into Windows 10+, needs
  KB2999226 on 7/8.1.
- After a failed merge, "Retry" just fails again (the error entry's source is
  deliberately missing); use Abort or Ignore.
- The progress bar tracks part extraction; inflating isn't counted.
- Paths over 260 characters are not handled.
- No code signing yet (`osslsigncode` on Linux, `signtool` on Windows).

## Reference analysis

`research/` holds the scripts used to take apart the Mouse P.I. For Hire GOG
installer (Inno Setup 5.6.x, GOG-patched): loader table, header blocks,
`setup.e32`, and the 74-byte file-location records. Findings that shaped this tool:
4 GiB slices, files stored as pre-zlibbed 10 MiB parts named by MD5 of the
compressed data, `before_install`/`after_install` hooks, and native helpers
(`unzlib_merge`, `md5thread`) doing the reassembly.
