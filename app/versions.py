"""
Silent version history: before an artifact is replaced, its previous state is copied to
    <ARTIFACTS_DIR>/.versions/<slug>/<YYYYmmdd-HHMMSS-ffffff>.html   (single file)
    <ARTIFACTS_DIR>/.versions/<slug>/<YYYYmmdd-HHMMSS-ffffff>.zip    (folder app)
The last KEEP versions are kept. There is no UI; restore by copying a file back by hand.
"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

KEEP = 10


def _dir(artifacts_dir: Path, slug: str) -> Path:
    return artifacts_dir / ".versions" / slug


def save(artifacts_dir: Path, slug: str) -> Path | None:
    """Copy the current artifact into the history; None if there is nothing to save."""
    html = artifacts_dir / f"{slug}.html"
    folder = artifacts_dir / slug
    if not html.is_file() and not (folder / "index.html").is_file():
        return None
    vdir = _dir(artifacts_dir, slug)
    vdir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    if html.is_file():
        dest = vdir / f"{stamp}.html"
        shutil.copyfile(html, dest)
    else:
        dest = Path(shutil.make_archive(str(vdir / stamp), "zip", folder))
    for old in list_versions(artifacts_dir, slug)[:-KEEP]:
        old.unlink(missing_ok=True)
    return dest


def rename(artifacts_dir: Path, old: str, new: str) -> None:
    """Move the history along when an artifact gets a new slug; merges with any history already there."""
    src, dst = _dir(artifacts_dir, old), _dir(artifacts_dir, new)
    if not src.is_dir():
        return
    dst.mkdir(parents=True, exist_ok=True)
    for f in sorted(src.iterdir()):  # history left under the new name (e.g. from a deleted app) is kept too
        target = dst / f.name
        n = 1
        while target.exists():  # same timestamp twice: keep both
            target = dst / f"{f.stem}-{n}{f.suffix}"
            n += 1
        f.rename(target)
    src.rmdir()
    for old in list_versions(artifacts_dir, new)[:-KEEP]:
        old.unlink(missing_ok=True)


def list_versions(artifacts_dir: Path, slug: str) -> list[Path]:
    """Saved versions, oldest first."""
    vdir = _dir(artifacts_dir, slug)
    return sorted(vdir.iterdir()) if vdir.is_dir() else []
