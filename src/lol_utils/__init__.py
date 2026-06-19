"""Shared helpers for the LoL analytics project.

Centralizes logic that was previously copy-pasted across notebooks and scripts:
- project-root discovery (paths.py);
- derived game metrics like kda / per-minute stats (metrics.py).
"""

from .metrics import add_metrics
from .paths import find_project_root, save_parquet_if_available

__all__ = ["add_metrics", "find_project_root", "save_parquet_if_available"]
