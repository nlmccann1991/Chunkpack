"""Splits files into Galaxy-style parts: fixed-size blocks, each an independent
zlib stream, stored content-addressed as <store>/ab/cd/<md5 of compressed part>."""
import fnmatch
import hashlib
import json
import os
import threading
import zlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Part:
    md5: str     # MD5 of the compressed bytes; also the stored file name
    csize: int
    usize: int
    umd5: str    # MD5 of the inflated bytes


@dataclass
class PackedFile:
    rel: str     # path inside {app}, backslash-separated
    size: int
    md5: str
    parts: list[Part]


def part_path(store: Path, md5: str) -> Path:
    return store / md5[:2] / md5[2:4] / md5


def scan(source_dir: Path, exclude: list[str]) -> tuple[list[tuple[Path, str]], list[str]]:
    """Returns (files as (abs path, rel), empty dirs as rel), sorted for reproducible builds."""
    files, empty_dirs = [], []
    for root, dirs, names in os.walk(source_dir):
        dirs.sort()
        rel_root = Path(root).relative_to(source_dir).as_posix()
        kept = 0
        for n in sorted(names):
            rel = n if rel_root == "." else f"{rel_root}/{n}"
            if any(fnmatch.fnmatch(rel, pat) for pat in exclude):
                continue
            files.append((Path(root) / n, rel.replace("/", "\\")))
            kept += 1
        if rel_root != "." and not kept and not dirs:
            empty_dirs.append(rel_root.replace("/", "\\"))
    return files, empty_dirs


def _pack(path: Path, rel: str, store: Path, chunk_size: int, level: int) -> PackedFile:
    whole, parts, size = hashlib.md5(), [], 0
    with open(path, "rb") as f:
        while block := f.read(chunk_size):
            size += len(block)
            whole.update(block)
            comp = zlib.compress(block, level)
            md5 = hashlib.md5(comp).hexdigest()
            dest = part_path(store, md5)
            if not dest.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                tmp = dest.with_name(f"{md5}.{threading.get_ident()}.tmp")
                tmp.write_bytes(comp)
                os.replace(tmp, dest)
            parts.append(Part(md5, len(comp), len(block), hashlib.md5(block).hexdigest()))
    return PackedFile(rel, size, whole.hexdigest(), parts)


def pack_all(files: list[tuple[Path, str]], store: Path, chunk_size: int, level: int,
             jobs: int | None = None, progress=None) -> list[PackedFile]:
    """Packs every file, reusing cached results when size, mtime and settings match."""
    store.mkdir(parents=True, exist_ok=True)
    cache_file = store / "cache.json"
    try:
        cache = json.loads(cache_file.read_text())
    except (OSError, ValueError):
        cache = {}
    settings = [chunk_size, level]

    def one(item):
        path, rel = item
        st = path.stat()
        key = [st.st_size, st.st_mtime_ns, *settings]
        hit = cache.get(str(path))
        if hit and hit["key"] == key and all(part_path(store, p["md5"]).exists() for p in hit["parts"]):
            packed = PackedFile(rel, hit["size"], hit["md5"], [Part(**p) for p in hit["parts"]])
        else:
            packed = _pack(path, rel, store, chunk_size, level)
        return str(path), key, packed

    out = []
    with ThreadPoolExecutor(jobs or os.cpu_count()) as pool:
        for i, (abspath, key, packed) in enumerate(pool.map(one, files), 1):
            cache[abspath] = {"key": key, "size": packed.size, "md5": packed.md5,
                              "parts": [asdict(p) for p in packed.parts]}
            out.append(packed)
            if progress:
                progress(i, len(files), packed.rel)
    cache_file.write_text(json.dumps(cache))
    return out
