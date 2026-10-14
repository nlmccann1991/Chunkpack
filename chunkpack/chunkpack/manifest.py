"""Loads and validates a package manifest (TOML)."""
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

GOG_SLICE_SIZE = 4294967294  # largest slice that still fits on FAT32, as GOG uses
GALAXY_CHUNK_SIZE = 10 * 1024 * 1024


class ManifestError(Exception):
    pass


@dataclass
class Redist:
    file: Path          # absolute source path
    dest: str           # path inside {app}, backslash-separated
    args: str
    description: str


@dataclass
class Manifest:
    path: Path
    id: str
    name: str
    version: str
    build: str
    publisher: str
    url: str
    exe: str            # main executable, relative to the install dir, backslashes
    exe_args: str
    source_dir: Path
    exclude: list[str]
    output_dir: Path
    basename: str
    default_dir: str
    per_user: bool
    languages: list[str]
    slice_size: int
    chunk_size: int
    zlib_level: int
    icon: Path | None
    license: Path | None
    wizard_image: Path | None
    wizard_small_image: Path | None
    redists: list[Redist] = field(default_factory=list)

    @property
    def slug(self) -> str:
        return re.sub(r"[^a-z0-9]+", "_", self.name.lower()).strip("_") or "app"


def _opt_path(base: Path, value) -> Path | None:
    if not value:
        return None
    p = (base / value).resolve()
    if not p.is_file():
        raise ManifestError(f"file not found: {p}")
    return p


def load(path: str | Path) -> Manifest:
    path = Path(path).resolve()
    base = path.parent
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise ManifestError(f"{path}: {e}") from e

    product = data.get("product", {})
    source = data.get("source", {})
    package = data.get("package", {})
    for key in ("id", "name", "version", "publisher", "exe"):
        if not str(product.get(key, "")).strip():
            raise ManifestError(f"[product] {key} is required")

    source_dir = (base / source.get("dir", ".")).resolve()
    if not source_dir.is_dir():
        raise ManifestError(f"[source] dir not found: {source_dir}")
    exe = product["exe"].replace("/", "\\")
    if not (source_dir / exe.replace("\\", "/")).is_file():
        raise ManifestError(f"[product] exe not found in source dir: {exe}")

    redists = []
    for r in data.get("redist", []):
        src = _opt_path(base, r.get("file"))
        if src is None:
            raise ManifestError("[[redist]] file is required")
        redists.append(Redist(
            file=src,
            dest=r.get("dest", f"__redist\\{src.name}").replace("/", "\\"),
            args=r.get("args", ""),
            description=r.get("description", src.name),
        ))

    name = product["name"]
    build = str(product.get("build", product["version"]))
    m = Manifest(
        path=path,
        id=str(product["id"]),
        name=name,
        version=str(product["version"]),
        build=build,
        publisher=product["publisher"],
        url=product.get("url", ""),
        exe=exe,
        exe_args=product.get("args", ""),
        source_dir=source_dir,
        exclude=list(source.get("exclude", [])),
        output_dir=(base / package.get("output_dir", "dist")).resolve(),
        basename=package.get("basename", ""),
        default_dir=package.get("default_dir", ""),  # empty: {sd}\Games\<name>
        per_user=bool(package.get("per_user", False)),
        languages=list(package.get("languages", ["english"])),
        slice_size=int(package.get("slice_size", GOG_SLICE_SIZE)),
        chunk_size=int(package.get("chunk_size", GALAXY_CHUNK_SIZE)),
        zlib_level=int(package.get("zlib_level", 6)),
        icon=_opt_path(base, product.get("icon")),
        license=_opt_path(base, product.get("license")),
        wizard_image=_opt_path(base, package.get("wizard_image")),
        wizard_small_image=_opt_path(base, package.get("wizard_small_image")),
        redists=redists,
    )
    if not m.basename:
        m.basename = f"setup_{m.slug}_({m.build})"
    if not 262144 <= m.slice_size:
        raise ManifestError("[package] slice_size must be at least 262144")
    if not 1 <= m.chunk_size <= 64 * 1024 * 1024:
        raise ManifestError("[package] chunk_size must be between 1 byte and 64 MiB")
    if not 0 <= m.zlib_level <= 9:
        raise ManifestError("[package] zlib_level must be 0-9")
    return m
