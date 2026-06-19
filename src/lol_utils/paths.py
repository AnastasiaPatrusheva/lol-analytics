"""Project path helpers.

The same ``while not (PROJECT_ROOT / "data").exists(): ...`` snippet was
copy-pasted into every notebook. ``find_project_root`` replaces it and works
both from a notebook (cwd-based) and from a script (file-based).
"""

from __future__ import annotations

from pathlib import Path


def find_project_root(start: Path | None = None, marker: str = "data") -> Path:
    """Walk up from ``start`` until a directory containing ``marker`` is found.

    In a notebook call ``find_project_root()`` (uses cwd). In a script call
    ``find_project_root(Path(__file__))``.
    """
    current = (start or Path.cwd()).resolve()
    if current.is_file():
        current = current.parent
    while not (current / marker).exists() and current != current.parent:
        current = current.parent
    return current


def save_parquet_if_available(df, path: Path) -> None:
    """Best-effort Parquet export. CSV stays the source of truth, so a missing
    pyarrow/fastparquet engine is logged and skipped rather than crashing."""
    try:
        df.to_parquet(path, index=False)
    except Exception as exc:  # noqa: BLE001 - any engine/IO error is non-fatal here
        print(f"Parquet skipped for {path.name}: {exc}")
