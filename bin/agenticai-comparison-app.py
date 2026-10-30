#!/usr/bin/env python3
"""Start the comparison Streamlit app with .env defaults and optional CLI overrides."""
from __future__ import annotations

from optparse import OptionParser, OptionGroup, Values, OptionValueError
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.cli import launch_streamlit, parse_server_args
from utils.config import ROOT
from utils import common
from dotenv import load_dotenv

# Load variables from the .env file into the environment
load_dotenv()

def parse_args(argv: list[str] | None = None) -> Values:
    """Parse the same listener and debugging options used by other app launchers."""

    try:

        parser = OptionParser()

        # Options
        main_group = OptionGroup(parser, os.path.basename(__file__) + " options", "Also run the tool-calling loop after MCP discovery")
        main_group.add_option('-w', '--with_agent', dest="with_agent", action="store_true", help="Sample Question", default="Who is the contact in the CAISO Cafe.")
        main_group.add_option('-s', '--sample_question', dest="sample_question", type="string", action="store", help="Puppet Module")
        main_group.add_option('-c', '--conversation', dest="conversation", action="store_true", help="Conduct a conversation or not.")
        parser.add_option_group(main_group)

        # Add the Common environment/app/component/node options
        app_arg_group = common.get_app_arg_group(parser)
        parser.add_option_group(app_arg_group)

        # Add the standard args
        common_arg_group = common.get_common_arg_group(parser)
        parser.add_option_group(common_arg_group)

        options, remainder = parser.parse_args()

        return options

    except Exception as parse_args_err:
        raise RuntimeError(common.generic_error_message(error_code="PUPPET-100", err=parse_args_err))


def main() -> int:
    """Validate launcher options and start a single comparison Streamlit server."""
    return launch_streamlit(ROOT / 'comparison_app/app.py', parse_args())


if __name__ == '__main__':
    sys.exit(main())
