"""Sanitize env for children of a frozen (PyInstaller) BAKLOG process.

Frozen onedir builds set ``LD_LIBRARY_PATH`` to the bundle ``_internal`` folder
so the app's own native libs resolve. System Chrome wrappers (``#!/bin/bash``)
and ``/bin/bash`` update helpers then load the bundled ``libreadline`` and can
die with ``undefined symbol: rl_trim_arg_from_keyseq`` (exit 127).

Fetcher subprocesses already use a clean whitelist
(``auth.manager.subprocess_env_for_profile``). Browser Connect and in-app apply
need a lighter scrub that keeps display/session vars but drops PyInstaller
linker pollution.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, MutableMapping


def scrub_pyinstaller_library_path(
    env: MutableMapping[str, str] | None = None,
) -> dict[str, str]:
    """Return a copy of ``env`` safe for system bash / Chrome shell wrappers.

    - If ``LD_LIBRARY_PATH_ORIG`` is set (PyInstaller backup), restore it to
      ``LD_LIBRARY_PATH``.
    - Otherwise remove ``LD_LIBRARY_PATH``.
    - Drop ``LD_PRELOAD`` entries that point under a frozen ``_internal`` tree.
    """
    out: dict[str, str] = dict(os.environ if env is None else env)

    orig = out.pop("LD_LIBRARY_PATH_ORIG", None)
    if orig is not None and str(orig).strip():
        out["LD_LIBRARY_PATH"] = str(orig)
    else:
        out.pop("LD_LIBRARY_PATH", None)

    preload = out.get("LD_PRELOAD")
    if preload:
        kept: list[str] = []
        for part in str(preload).replace(";", ":").split(":"):
            chunk = part.strip()
            if not chunk:
                continue
            normalized = chunk.replace("\\", "/").lower()
            if "/_internal/" in normalized or normalized.endswith("/_internal"):
                continue
            kept.append(chunk)
        if kept:
            out["LD_PRELOAD"] = os.pathsep.join(kept)
        else:
            out.pop("LD_PRELOAD", None)

    return out


def browser_child_env(
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Environment for a Chrome/Edge CDP child of the BAKLOG process."""
    return scrub_pyinstaller_library_path(dict(base) if base is not None else None)
