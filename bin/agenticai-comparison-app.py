"""Load root .env and start the comparison_app Streamlit server on its configured port."""
from __future__ import annotations

import logging
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from utils.config import ROOT, integer
from utils.common import configure_logging, get_required_env

log = configure_logging()


def main() -> int:
    """Validate server settings and replace the launcher with the Streamlit process."""
    try:
        log.info("Starting ...")
        load_dotenv(ROOT / '.env', override=True)
        port = integer('P3_STREAMLIT_PORT', 5555, maximum=65535)
        address = os.getenv('P3_STREAMLIT_ADDRESS', '127.0.0.1').strip()
        if not address:
            raise ValueError('P3_STREAMLIT_ADDRESS must not be empty.')
        os.chdir(ROOT)
        log.info('Starting comparison_app Streamlit at http://%s:%d.', address, port)
        os.execv(sys.executable, [sys.executable, '-m', 'streamlit', 'run',
            str(ROOT / 'comparison_app/app.py'), '--server.port', str(port),
            '--server.address', address, '--server.headless', 'true'])
    except Exception as startup_error:
        log.error('Streamlit startup failed (%s). Check .env and run uv sync.', type(startup_error).__name__)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
