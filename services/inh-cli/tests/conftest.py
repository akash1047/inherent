from __future__ import annotations

import os

# Typer forces a Rich terminal when GITHUB_ACTIONS is set, which splits option
# names in --help with ANSI escapes ("-\x1b[0m\x1b[1;36m-json"). The flag is
# read at typer import time, so it must be set before any test imports the app.
os.environ["_TYPER_FORCE_DISABLE_TERMINAL"] = "1"
