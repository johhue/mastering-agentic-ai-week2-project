#!/usr/bin/env python3
"""Start the comparison Streamlit app with .env defaults and optional CLI overrides."""
from __future__ import annotations

from optparse import Values
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.cli import launch_streamlit, parse_server_args
from utils.config import ROOT


def parse_args(argv: list[str] | None = None) -> Values:
    """Parse the same listener and debugging options used by other app launchers."""
    return parse_server_args(__doc__, 'P3_STREAMLIT_PORT', 5555, 'P3_STREAMLIT_ADDRESS', argv,
                             prog=Path(__file__).name)


def main() -> int:
    """Validate launcher options and start a single comparison Streamlit server."""
    return launch_streamlit(ROOT / 'comparison_app/app.py', parse_args())


if __name__ == '__main__':
    sys.exit(main())
