"""Load root .env and start the project3 Streamlit server on its configured port."""
from __future__ import annotations

import logging
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from project3.config import ROOT, configure_logging, integer

log = logging.getLogger(__name__)


def main() -> int:
    """Validate server settings and replace the launcher with the Streamlit process."""
    try:
        load_dotenv(ROOT / '.env', override=True)
        configure_logging()
        port = integer('P3_STREAMLIT_PORT', 5555, maximum=65535)
        address = os.getenv('P3_STREAMLIT_ADDRESS', '127.0.0.1').strip()
        if not address:
            raise ValueError('P3_STREAMLIT_ADDRESS must not be empty.')
        os.chdir(ROOT)
        log.info('Starting project3 Streamlit at http://%s:%d.', address, port)
        os.execv(sys.executable, [sys.executable, '-m', 'streamlit', 'run',
            str(ROOT / 'project3/app.py'), '--server.port', str(port),
            '--server.address', address, '--server.headless', 'true'])
    except Exception as startup_error:
        log.error('Streamlit startup failed (%s). Check .env and run uv sync.', type(startup_error).__name__)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
