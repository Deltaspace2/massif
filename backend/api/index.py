"""Vercel entry point for the read API.

Vercel's Python runtime looks for `app` in this file and serves it as an ASGI
application. Everything real lives in `massif.main`; this file exists only to
put the package on `sys.path`, because the function bundle is a copy of
`backend/` and the package is never pip-installed into it.

Nothing here should ever grow logic. If it does, it stops being testable — the
one file in the repo that CI cannot exercise.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from massif.main import app  # noqa: E402

__all__ = ["app"]
