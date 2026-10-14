"""chunkpack: build GOG-style installers (setup.exe + .bin slices, Galaxy-style parts).

    python -m chunkpack build path/to/manifest.toml [--no-compile] [--jobs N]
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from . import chunker, iss, manifest

ROOT = Path(__file__).resolve().parent.parent
HELPER = ROOT / "helper" / "build" / "chunkhelper.dll"


def iscc_command() -> tuple[list[str], dict]:
    env = dict(os.environ)
    if os.name == "nt":
        candidates = [os.environ.get("CHUNKPACK_ISCC", ""),
                      os.path.expandvars(r"%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"),
                      os.path.expandvars(r"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe")]
        for c in candidates:
            if c and Path(c).is_file():
                return [c], env
        sys.exit("ISCC.exe not found: install Inno Setup 6 or set CHUNKPACK_ISCC")
    env.setdefault("WINEPREFIX", str(ROOT / ".tools" / "wine"))
    env.setdefault("WINEDEBUG", "-all")
    iscc = os.environ.get("CHUNKPACK_ISCC") or str(Path(env["WINEPREFIX"]) / "drive_c/InnoSetup/ISCC.exe")
    if not Path(iscc).is_file():
        sys.exit(f"ISCC.exe not found at {iscc}: run scripts/setup_tools.sh or set CHUNKPACK_ISCC")
    return ["wine", iscc], env


def info_json(m: manifest.Manifest) -> str:
    """Metadata dropped into the install dir, modelled on GOG's goggame-<id>.info."""
    return json.dumps({
        "version": 1,
        "gameId": m.id,
        "name": m.name,
        "buildId": m.build,
        "gameVersion": m.version,
        "playTasks": [{"type": "FileTask", "isPrimary": True, "name": m.name, "category": "game",
                       "path": m.exe, "arguments": m.exe_args}],
    }, indent=4) + "\n"


def outputs(m: manifest.Manifest) -> list[Path]:
    """The setup .exe and its -N.bin slices in the output dir."""
    pat = re.compile(re.escape(m.basename) + r"(\.exe|-\d+\.bin)")
    return sorted(p for p in m.output_dir.iterdir() if pat.fullmatch(p.name))


def build(args) -> None:
    m = manifest.load(args.manifest)
    if not HELPER.is_file():
        sys.exit(f"{HELPER} missing: run helper/build.sh first")
    build_dir = Path(args.build_dir or m.path.parent / "build" / m.slug).resolve()
    (build_dir / "generated").mkdir(parents=True, exist_ok=True)

    files, empty_dirs = chunker.scan(m.source_dir, m.exclude)
    info = build_dir / "generated" / f"chunkpack-{m.id}.info"
    info.write_text(info_json(m), encoding="utf-8")
    files.append((info, info.name))
    files += [(r.file, r.dest) for r in m.redists]

    seen = {}
    for path, rel in files:  # Windows paths are case-insensitive
        if (other := seen.setdefault(rel.lower(), path)) is not path:
            sys.exit(f"two files map to the same install path {rel}: {other} and {path}")

    def progress(i, n, rel):
        if i == n or i % 200 == 0:
            print(f"\r  packed {i}/{n} files", end="" if i < n else "\n", file=sys.stderr, flush=True)

    print(f"Chunking {len(files)} files from {m.source_dir}", file=sys.stderr)
    packed = chunker.pack_all(files, build_dir / "parts", m.chunk_size, m.zlib_level, args.jobs, progress)
    parts = sum(len(f.parts) for f in packed)
    total = sum(f.size for f in packed)
    stored = sum(p.csize for f in packed for p in f.parts)
    print(f"  {parts} parts, {total / 1e9:.2f} GB -> {stored / 1e9:.2f} GB stored", file=sys.stderr)

    script = build_dir / "setup.iss"
    script.write_text(iss.render(m, packed, empty_dirs, {rel: p for p, rel in files}), encoding="utf-8-sig")
    shutil.copy2(HELPER, build_dir / HELPER.name)
    print(f"Wrote {script}", file=sys.stderr)
    if args.no_compile:
        return

    m.output_dir.mkdir(parents=True, exist_ok=True)
    for old in outputs(m):  # stale slices from a bigger previous build would confuse setup
        old.unlink()
    cmd, env = iscc_command()
    print("Compiling with Inno Setup...", file=sys.stderr)
    if subprocess.run(cmd + ["/Q", script.name], cwd=build_dir, env=env).returncode:
        sys.exit("ISCC failed")
    for out in outputs(m):
        print(f"  {out}  ({out.stat().st_size:,} bytes)")


def main() -> None:
    ap = argparse.ArgumentParser(prog="chunkpack", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="chunk files and compile the installer")
    b.add_argument("manifest")
    b.add_argument("--build-dir", help="work dir for parts and setup.iss (default: build/<slug> next to the manifest)")
    b.add_argument("--jobs", type=int, help="compression threads (default: CPU count)")
    b.add_argument("--no-compile", action="store_true", help="stop after writing setup.iss")
    args = ap.parse_args()
    try:
        build(args)
    except manifest.ManifestError as e:
        sys.exit(f"manifest error: {e}")


if __name__ == "__main__":
    main()
