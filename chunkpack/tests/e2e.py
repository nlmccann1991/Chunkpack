"""End-to-end test (Linux + Wine): builds a demo installer with awkward file names
and tiny slices, installs it silently, checks every file, then uninstalls.
Also checks that a corrupted MD5 makes setup fail instead of installing junk.

    python3 tests/e2e.py
"""
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "tests" / "_work"
ENV = dict(os.environ, WINEPREFIX=str(ROOT / ".tools" / "wine"), WINEDEBUG="-all")
DRIVE_C = Path(ENV["WINEPREFIX"]) / "drive_c"
MiB = 1024 * 1024

FILES = {  # rel path -> content
    "Demo.exe": b"MZ not really a game",
    "data/random_25m.bin": os.urandom(25 * MiB),           # 3 parts
    "data/zeros_12m.bin": bytes(12 * MiB),                 # 2 parts
    "data/zeros_copy.bin": bytes(12 * MiB),                # same parts again (dedup)
    "data/exactly_10m.bin": os.urandom(10 * MiB),          # chunk boundary: 1 part
    "empty.txt": b"",
    "names/it's {weird}; 100% name.txt": b"quotes, braces, semicolons",
    "names/données é ü 日本.txt": "unicode".encode(),
    "names/{#notispp}.txt": b"preprocessor lookalike",
    "debug.pdb": b"excluded by manifest",
}

MANIFEST = """
[product]
id = "1000000001"
name = "Chunkpack Demo"
version = "1.0.0"
build = "42"
publisher = "Chunkpack Tests"
exe = "Demo.exe"

[source]
dir = "src"
exclude = ["*.pdb"]

[package]
output_dir = "dist"
slice_size = 8388608

[[redist]]
file = "redist_probe.exe"
args = "/quiet --from-installer"
description = "Probe redist"
"""


def run(cmd, **kw):
    print("+", " ".join(map(str, cmd)), flush=True)
    return subprocess.run(cmd, env=ENV, **kw)


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def wine_wait():
    subprocess.run(["wineserver", "-w"], env=ENV)


def make_demo():
    shutil.rmtree(WORK, ignore_errors=True)
    src = WORK / "src"
    for rel, data in FILES.items():
        (src / rel).parent.mkdir(parents=True, exist_ok=True)
        (src / rel).write_bytes(data)
    (src / "empty_dir").mkdir()
    (WORK / "manifest.toml").write_text(MANIFEST, encoding="utf-8")
    zig = ROOT / ".tools" / "zig" / "zig"
    run([zig, "cc", "-target", "x86-windows-gnu", "-O2", "-s", "-o", WORK / "redist_probe.exe",
         ROOT / "tests" / "redist_probe.c"], check=True)


def build(*extra):
    run([sys.executable, "-m", "chunkpack", "build", WORK / "manifest.toml", *extra], cwd=ROOT, check=True)


def install(target: str) -> int:
    setup = next((WORK / "dist").glob("*.exe"))
    rc = run(["wine", setup, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
              f"/DIR=C:\\{target}", f"/LOG=C:\\{target}.log"]).returncode
    wine_wait()
    return rc


def check_install(app: Path):
    failures = []
    for rel, data in FILES.items():
        p = app / rel
        if rel.endswith(".pdb"):
            if p.exists():
                failures.append(f"excluded file was installed: {rel}")
        elif not p.is_file():
            failures.append(f"missing: {rel}")
        elif sha(p) != hashlib.sha256(data).hexdigest():
            failures.append(f"content differs: {rel}")
    if not (app / "empty_dir").is_dir():
        failures.append("empty_dir not created")
    if not (app / "chunkpack-1000000001.info").is_file():
        failures.append(".info file missing")
    marker = app / "__redist" / "redist_ran.txt"
    if not marker.is_file() or "--from-installer" not in marker.read_bytes().decode("utf-16-le"):
        failures.append("redist did not run with its arguments")
    leftovers = [p for p in app.rglob("*") if p.name.endswith(".cpk-tmp")]
    if leftovers:
        failures.append(f"temp files left: {leftovers}")
    reg = run(["wine", "reg", "query", r"HKLM\Software\Chunkpack Tests\Games\1000000001", "/v", "path"],
              capture_output=True, text=True)
    if "e2e_ok" not in reg.stdout.lower():
        failures.append(f"registry key missing: {reg.stdout.strip()}")
    return failures


def main():
    make_demo()
    build()
    slices = sorted((WORK / "dist").glob("*.bin"))
    print(f"output: {[p.name for p in (WORK / 'dist').iterdir()]}")
    assert len(slices) >= 3, "expected several .bin slices with an 8 MiB slice size"

    app = DRIVE_C / "e2e_ok"
    shutil.rmtree(app, ignore_errors=True)
    rc = install("e2e_ok")
    failures = check_install(app) if rc == 0 else [f"setup exited with {rc}"]

    if not failures:
        (app / "__redist" / "redist_ran.txt").unlink()  # written by the probe, not the installer
        run(["wine", app / "unins000.exe", "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"])
        wine_wait()
        if app.exists():
            failures.append(f"uninstall left files: {[str(p.relative_to(app)) for p in app.rglob('*')]}")

    # Corrupt the expected MD5 of a file in the middle of the list: setup must
    # fail, and roll back the files merged before it as well as its own.
    build("--no-compile")
    iss = WORK / "build" / "chunkpack_demo" / "setup.iss"
    text = iss.read_text(encoding="utf-8-sig")
    i = text.index("', 'data\\zeros_copy.bin'") - 32
    iss.write_text(text[:i] + "0" * 32 + text[i + 32:], encoding="utf-8-sig")
    run(["wine", ROOT / ".tools/wine/drive_c/InnoSetup/ISCC.exe", "/Q", "setup.iss"], cwd=iss.parent, check=True)
    bad = DRIVE_C / "e2e_bad"
    shutil.rmtree(bad, ignore_errors=True)
    rc = install("e2e_bad")
    log = (DRIVE_C / "e2e_bad.log").read_text(errors="replace")
    if rc == 0 or "zeros_copy.bin (the file failed its MD5 check)" not in log:
        failures.append(f"corrupted package was not rejected (exit {rc})")
    elif bad.exists():
        failures.append(f"rollback left files: {[str(p.relative_to(bad)) for p in bad.rglob('*')]}")
    else:
        print(f"corrupted package rejected and rolled back (exit {rc})")

    if failures:
        print("FAILED:\n  " + "\n  ".join(failures))
        sys.exit(1)
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
