"""Shared OptionParser, configuration precedence and startup for bin scripts."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation
import logging
import os
from optparse import BadOptionError, Option, OptionParser, OptionValueError, Values
from pathlib import Path
import re
import sys

import utils.common
from utils import common

from dotenv import dotenv_values, load_dotenv
from utils.common import PROJECT_ROOT


def positive_integer(value: str) -> int:
    """Reject zero and negative counts using the shared option validation error."""
    try:
        number = int(value)
        if number < 1:
            raise ValueError('not positive')
        return number
    except (ValueError, TypeError) as integer_error:
        raise OptionValueError('Must be a positive integer.') from integer_error


def nonempty_text(value: str) -> str:
    """Trim a text value and reject blank input before external work."""
    result = value.strip()
    if not result:
        raise OptionValueError('Must not be blank.')
    return result


def check_custom_type(option: Option, opt: str, value: str):
    """Convert custom option types without exposing invalid configuration values."""
    try:
        if option.type == 'positive_int':
            return positive_integer(value)
        if option.type == 'nonempty':
            return nonempty_text(value)
        if option.type == 'path':
            return Path(value).expanduser()
        return Decimal(value)
    except (ValueError, TypeError, InvalidOperation, OptionValueError) as value_error:
        raise OptionValueError(f'{opt}: invalid {option.type} value.') from value_error


class CLIOption(Option):
    """Native optparse option with the project's reusable validated value types."""

    TYPES = Option.TYPES + ('positive_int', 'nonempty', 'path', 'decimal')
    TYPE_CHECKER = {**Option.TYPE_CHECKER,
        **{name: check_custom_type for name in ('positive_int', 'nonempty', 'path', 'decimal')}}


class CLIOptionParser(OptionParser):
    """Keep strict long options and defer default validation until after help."""

    def add_option(self, *args, **kwargs) -> Option:
        """Register native options and provide inverse flags for configured booleans."""
        option = super().add_option(*args, **kwargs)
        if option.action == 'store_true' and option._long_opts:
            negative = '--no-' + option._long_opts[0][2:]
            super().add_option(negative, action='store_false', dest=option.dest,
                               help=f'Disable {option._long_opts[0]} even when enabled in configuration.')
        return option

    def get_default_values(self) -> Values:
        """Copy defaults without converting them before --help can exit."""
        return Values(deepcopy(self.defaults))

    def _match_long_opt(self, opt: str) -> str:
        """Require exact long-option spelling instead of optparse abbreviations."""
        if opt not in self._long_opt:
            raise BadOptionError(opt)
        return opt


def config_path(argv: list[str]) -> tuple[Path, bool]:
    """Locate the final --config argument without consuming command-specific flags."""
    path = Path(os.getenv('AGENTICAI_CONFIG') or str(PROJECT_ROOT / '.env')).expanduser()
    explicit = bool(os.getenv('AGENTICAI_CONFIG'))
    for index, token in enumerate(argv):
        if token == '--':
            break
        if token.startswith('--config='):
            path, explicit = Path(token.split('=', 1)[1]).expanduser(), True
        elif token == '--config' and index + 1 < len(argv):
            path, explicit = Path(argv[index + 1]).expanduser(), True
    return path.resolve(), explicit


def create_parser(description: str, argv: list[str] | None = None,
                  usage: str = '%prog [options]', prog: str | None = None) -> CLIOptionParser:
    """Load environment then .env-style file values; CLI options override them last."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    parser = CLIOptionParser(description=description, usage=usage, option_class=CLIOption, prog=prog)
    parser.environment_values = dict(os.environ)
    parser.file_values = {}
    parser.environment_aliases = {}
    path, explicit = config_path(arguments)
    parser.add_option('--config', type='path', default=path,
                      help='Configuration file in .env format (default: %default).')
    parser.add_option('--debug', action='store_true', default=False,
                      help='Enable application debug logging.')
    parser.config_file = path
    # Help is safe even if the selected runtime file cannot be opened.
    if '--help' not in arguments and '-h' not in arguments:
        try:
            if explicit and not path.is_file():
                parser.error('The selected configuration file does not exist or is not a file.')
            if os.getenv('PYTHON_DOTENV_DISABLED', '').lower() not in ('1', 'true', 'yes', 't', 'y'):
                parser.file_values = {key: value for key, value in dotenv_values(path).items() if value is not None}
            load_dotenv(path, override=True)
            parser.set_defaults(debug=os.getenv('P3_DEBUG', 'false').lower() == 'true'
                                or os.getenv('LOG_LEVEL', '').upper() == 'DEBUG')
            if explicit:
                os.environ['AGENTICAI_CONFIG'] = str(path)
        except (OSError, UnicodeError) as config_error:
            parser.error(f'Cannot read configuration file ({type(config_error).__name__}).')
    return parser


def configuration_key(command: str, destination: str) -> str:
    """Map a command and option destination to its documented environment key."""
    name = re.sub(r'[^A-Za-z0-9]+', '_', Path(command).stem.removeprefix('agenticai-'))
    return f'AGENTICAI_{name}_{destination}'.upper()


def configured_value(parser: CLIOptionParser, destination: str):
    """Resolve canonical and legacy aliases by source: environment then file."""
    legacy = {
        'index': ('PINECONE_INDEX_NAME', 'PINECONE_INDEX'),
        'namespace': ('PINECONE_NAMESPACE',),
        'embedding_model': ('OPENAI_EMBEDDING_MODEL',),
        'embedding_dimensions': ('OPENAI_EMBEDDING_DIMENSIONS',),
        'chat_model': ('OPENAI_CHAT_MODEL',), 'model': ('OPENAI_CHAT_MODEL',),
        'question': ('QUESTION',), 'memory_method': ('MEMORY_METHOD',),
        'monthly_bill_limit_usd': ('OPENAI_MONTHLY_BILL_LIMIT_USD',),
        'monthly_token_budget': ('OPENAI_MONTHLY_TOKEN_BUDGET',),
    }
    keys = (configuration_key(parser.get_prog_name(), destination),
            *parser.environment_aliases.get(destination, legacy.get(destination, ())))
    found, value = False, None
    for source in (parser.environment_values, parser.file_values):
        for key in keys:
            if key in source:
                found, value = True, source[key]
                break
    return found, value


def explicit_destinations(parser: CLIOptionParser, arguments: list[str]) -> set[str]:
    """Find supplied options while skipping their values and the -- terminator."""
    destinations = set()
    index = 0
    while index < len(arguments):
        token = arguments[index]
        if token == '--':
            break
        option = parser.get_option(token.split('=', 1)[0])
        if option is not None:
            destinations.add(option.dest)
            if option.takes_value() and '=' not in token:
                index += option.nargs
        index += 1
    return destinations


def parse_options(parser: CLIOptionParser, argv: list[str] | None = None,
                  positionals: tuple[tuple[str, bool], ...] = ()) -> Values:
    """Merge named configuration defaults, parse native options and bind positionals."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if '--help' in arguments or '-h' in arguments:
        parser.parse_args(arguments)
    supplied = explicit_destinations(parser, arguments)
    for option in parser.option_list:
        if not option.dest or option.dest == 'config' or option.action == 'help':
            continue
        key = configuration_key(parser.get_prog_name(), option.dest)
        found, raw = configured_value(parser, option.dest)
        if found and option.dest not in supplied:
            if option.action in ('store_true', 'store_false'):
                if raw.lower() not in ('true', 'false', '1', '0', 'yes', 'no'):
                    parser.error(f'{key} must be true or false.')
                raw = raw.lower() in ('true', '1', 'yes')
            elif option.action == 'append':
                import json
                try:
                    raw = json.loads(raw)
                    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
                        raise ValueError('not a list of strings')
                except (ValueError, TypeError) as list_error:
                    parser.error(f'{key} must be a JSON array of strings ({type(list_error).__name__}).')
            parser.set_defaults(**{option.dest: raw})
        if option.action == 'append' and option.dest in supplied:
            parser.set_defaults(**{option.dest: []})
    values, remaining = parser.parse_args(argv)
    if len(remaining) > len(positionals):
        parser.error('Unexpected positional arguments.')
    try:
        for option in parser.option_list:
            if option.action in ('store_true', 'store_false') and getattr(values, option.dest, None) is None:
                setattr(values, option.dest, False)
            if option.type and option.dest:
                value = getattr(values, option.dest, None)
                if value is not None:
                    if option.action == 'append':
                        value = [option.check_value(option.get_opt_string(), item) for item in value]
                    elif isinstance(value, str):
                        value = option.check_value(option.get_opt_string(), value)
                    setattr(values, option.dest, value)
        for index, (name, required) in enumerate(positionals):
            _, fallback = configured_value(parser, name)
            value = remaining[index] if index < len(remaining) else fallback
            if value is None and required:
                parser.error(f'{name} is required.')
            setattr(values, name, nonempty_text(value) if value is not None else None)
    except OptionValueError as parse_error:
        parser.error(str(parse_error))
    return values


# def configure_cli_logging(args: Values) -> None:
#    """Apply resolved debug settings after parsing and suppress raw SDK payload logs."""
#    # The resolved flag is final, including an explicit --no-debug.
#    if not args.debug and os.getenv('LOG_LEVEL', '').upper() == 'DEBUG':
#        os.environ['LOG_LEVEL'] = 'INFO'
#    # configure_logging(debug=bool(args.debug))
#    for name in ('openai', 'httpx', 'httpcore', 'mem0', 'posthog', 'urllib3'):
#        logging.getLogger(name).setLevel(logging.CRITICAL)


def parse_server_args(description: str, port_env: str, default_port: int,
                      address_env: str, argv: list[str] | None = None,
                      prog: str | None = None) -> Values:
    """Parse shared server options, resolving .env defaults before CLI overrides."""
    parser = create_parser(description, argv, prog=prog)
    parser.environment_aliases.update(port=(port_env,), address=(address_env,))
    parser.add_option('--port', type='positive_int', default=os.getenv(port_env, str(default_port)),
                      help=f'Listener port ({port_env}; default: %default).')
    parser.add_option('--address', type='nonempty', default=os.getenv(address_env, '127.0.0.1'),
                      help=f'Bind address ({address_env}; default: %default).')
    args = parse_options(parser, argv)
    if args.port > 65535:
        parser.error('--port must be between 1 and 65535.')
    return args


def launch_streamlit(app: Path, args: Values) -> int:
    """Start one server using resolved listener settings and inherited configuration."""
    log = common.initialize_logging()
    try:
        # configure_cli_logging(args)
        if args.debug:
            os.environ['LOG_LEVEL'] = 'DEBUG'
        os.environ['P3_DEBUG'] = str(bool(args.debug)).lower()
        log.info('Starting Streamlit at http://%s:%d.', args.address, args.port)
        os.execv(sys.executable, [sys.executable, '-m', 'streamlit', 'run', str(app),
            '--server.port', str(args.port), '--server.address', args.address, '--server.headless', 'true'])
    except Exception as launch_error:
        log.error('Streamlit startup failed (%s). Check configuration and dependencies.', type(launch_error).__name__)
        return 1
    return 0
