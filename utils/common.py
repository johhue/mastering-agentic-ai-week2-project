"""Shared helpers for the project command-line scripts."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
import os
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any, TypeVar

from dotenv import load_dotenv
import os

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = PROJECT_ROOT / "data"
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_-]*", re.IGNORECASE)

T = TypeVar("T")
DEFAULT_LOG_FORMAT = "%(message)s"
DEBUG_LOG_FORMAT = "%(levelname)s: %(message)s"
FILE_LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
LOG_LEVEL_ENV = "LOG_LEVEL"
LOG_FILE_ENV = "LOGGER_FILE"


def get_log_level(default: int = logging.INFO) -> int:
    """Return the configured logging level from the LOG_LEVEL environment value.

    Called by configure_logging when debug logging is not explicitly requested.

    Args:
        default: Level returned when LOG_LEVEL is unset or invalid.
    """
    configured_level = os.getenv(LOG_LEVEL_ENV)
    if not configured_level:
        return default

    level = logging.getLevelName(configured_level.upper())
    if isinstance(level, int):
        return level
    return default


def ensure_parent_directory(file_path: str) -> None:
    """Create the parent directory for a log file path when one is provided.

    Called by configure_logging before creating a file handler for LOGGER_FILE.

    Args:
        file_path: Log file path from LOGGER_FILE.
    """
    parent = Path(file_path).expanduser().parent
    if str(parent) not in ("", "."):
        parent.mkdir(parents=True, exist_ok=True)


def load_environment(override: bool = True) -> None:
    """Load variables from the local .env file into the process environment.

    Called by configure_logging and parse_args functions across the CLI scripts,
    and by support_chatbot at import time before Streamlit reads configuration.

    Args:
        override: Whether values from .env should replace existing environment
            variables.
    """
    selected = os.getenv('AGENTICAI_CONFIG')
    load_dotenv(Path(selected) if selected else PROJECT_ROOT / '.env',
                override=False if selected else override)


def get_required_env(
    name: str,
    default: str,
) -> str:
    """Return a required environment variable or raise a caller-selected error.

    Called by CLI main functions that need credentials, including
    query_pinecone.main, query_openai.main, query_openai_pinecone.main, and
    generate_test_questions.main.

    Args:
        name: Environment variable name to read.
        default: Default if Env Var not set
    """
    value = os.getenv(name)
    if value:
        return value
    else:
        if default:
            return default
        else:
            return 'unset'


def get_field(value: Any, field_name: str, default: Any = None) -> Any:
    """Read a field from either a mapping or an object attribute.

    Called by response-normalization code in query_pinecone and
    query_openai_pinecone when SDK responses may be dict-like or object-like.

    Args:
        value: Mapping or object to read.
        field_name: Field or attribute name to retrieve.
        default: Value returned when the field is absent.
    """
    if isinstance(value, dict):
        return value.get(field_name, default)
    return getattr(value, field_name, default)


def get_int_field(value: Any, field_name: str) -> int:
    """Read a field and coerce missing or null values to zero.

    Called by query_openai_pinecone usage parsing helpers for embedding and
    chat completion responses.

    Args:
        value: Mapping or object to read.
        field_name: Field or attribute name to retrieve.
    """
    raw_value = get_field(value, field_name, 0)
    if raw_value is None:
        return 0
    return int(raw_value)


def batched(items: Sequence[T], batch_size: int) -> Iterator[Sequence[T]]:
    """Yield fixed-size slices from a sequence.

    Called by query_pinecone.summarize_sources and upsert_to_pinecone.upsert_chunks
    to keep fetch, embedding, and upsert request sizes bounded.

    Args:
        items: Sequence to split into batches.
        batch_size: Maximum number of items per yielded batch.
    """
    if batch_size <= 0:
        raise ValueError("batch size must be greater than zero")
    for start in range(0, len(items), batch_size):
        yield items[start : start + batch_size]


def split_text(text: str, chunk_size: int, chunk_overlap: int) -> Iterator[str]:
    """Split text into overlapping chunks suitable for embedding.

    Used by ingestion and retrieval to keep chunk boundaries consistent.
    Invalid sizing raises ValueError before any chunks are produced.
    """
    if chunk_size <= 0:
        raise ValueError("chunk-size must be greater than zero")
    if chunk_overlap < 0:
        raise ValueError("chunk-overlap must be zero or greater")
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk-overlap must be smaller than chunk-size")

    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunk = text[start:end].strip()
        if chunk:
            yield chunk
        if end == len(text):
            break
        start = end - chunk_overlap


def find_input_dirs(input_glob: str = "RemindMe*") -> list[Path]:
    """Return sorted RemindMe corpus directories under the repository data root."""
    return [path for path in sorted(DATA_ROOT.glob(input_glob))
            if path.is_dir() and path.name.startswith("RemindMe")]


def iter_text_files(input_dirs: Sequence[Path], suffixes: set[str]) -> Iterator[Path]:
    """Yield sorted files recursively, preserving each caller's supported suffixes."""
    for input_dir in input_dirs:
        for path in sorted(input_dir.rglob("*")):
            if path.is_file() and path.suffix.lower() in suffixes:
                yield path


def iter_support_files(suffixes: set[str]) -> Iterator[Path]:
    """Yield supported files from the repository's RemindMe corpus directories."""
    yield from iter_text_files(find_input_dirs(), suffixes)


def read_text(path: Path) -> str:
    """Read UTF-8 text, logging and skipping files that cannot be read."""
    try:
        return path.read_text(encoding="utf-8", errors="ignore").strip()
    except OSError as corpus_read_error:
        print("Skipping unreadable file %s: %s", path, corpus_read_error)
        return ""


def read_source(path: Path) -> str:
    """Read source text and pretty-print valid JSON for retrieval context."""
    raw_text = read_text(path)
    if path.suffix.lower() == ".json":
        try:
            return json.dumps(json.loads(raw_text), indent=2, ensure_ascii=False)
        except json.JSONDecodeError:
            print("Using raw text for invalid JSON source %s", path)
    return raw_text


def compact_text(text: str) -> str:
    """Collapse whitespace into single spaces for compact source excerpts."""
    return re.sub(r"\s+", " ", text).strip()


def tokenize(text: str) -> list[str]:
    """Return normalized keyword tokens for local retrieval."""
    return [token.lower() for token in TOKEN_RE.findall(text)]


def stable_vector_id(source_path: Path, chunk_index: int, text: str) -> str:
    """Return the shared deterministic ID used by ingestion and retrieval."""
    digest = hashlib.sha256(f"{source_path}:{chunk_index}:{text}".encode("utf-8")).hexdigest()
    return str(uuid.uuid5(uuid.NAMESPACE_URL, digest))

def safe_text(value: object) -> str:
    """Bound messages and redact configured credentials before writing one log line."""
    text = json.dumps(value, ensure_ascii=False, default=str)
    for key, secret in os.environ.items():
        if secret and any(word in key.upper() for word in ('KEY', 'SECRET', 'PASSWORD', 'TOKEN', 'DATABASE_URL')):
            text = text.replace(secret, '[REDACTED]')
    return text[:12000]


def safe_url(value: object) -> str:
    """Keep endpoint paths while removing user information, query values and fragments."""
    try:
        from urllib.parse import urlsplit, urlunsplit
        parts = urlsplit(str(value))
        if parts.scheme not in ('https', 'http') or not parts.hostname:
            return '[non-HTTP endpoint]'
        host = parts.hostname
        if ':' in host:
            host = f'[{host}]'
        if parts.port:
            host += f':{parts.port}'
        return safe_text(urlunsplit((parts.scheme, host, parts.path, '', '')))
    except (ValueError, TypeError):
        return '[invalid endpoint]'


def log_request(request) -> None:
    """Observe actual SDK HTTP requests, including retries, without headers or bodies."""
    log = initialize_logging(__file__)
    log.info('External HTTP request method=%s url=%s', request.method, safe_url(request.url))


def log_response(response) -> None:
    """Record the status of an external response without exposing its contents."""
    log = initialize_logging(__file__)
    log.info('External HTTP response status=%s url=%s', response.status_code, safe_url(response.request.url))


def observe_client(client) -> None:
    """Attach request/response hooks to an OpenAI SDK synchronous HTTP client."""
    transport = getattr(client, '_client', None)
    hooks = getattr(transport, 'event_hooks', None)
    if isinstance(hooks, dict):
        if log_request not in hooks.setdefault('request', []):
            hooks['request'].append(log_request)
        if log_response not in hooks.setdefault('response', []):
            hooks['response'].append(log_response)


def message(sender: str, recipient: str, summary: str, payload: object = None) -> None:
    """Log public agent communication; detailed payloads are opt-in DEBUG data."""
    log = initialize_logging(__file__)
    log.info('Agent message %s -> %s: %s', sender, recipient, safe_text(summary))
    if payload is not None:
        log.debug('Agent conversation %s -> %s: %s', sender, recipient, safe_text(payload))

# COMMON SECTION: LOGGING
# ----------------------------------------------------------------------------------------------------
def initialize_logging(label=__name__, logfile=None, stream_stdout=True, stream_syslog=False, logfile_backup_count=1,
                       verbose=False, quiet=False):
    """
    Standard way we want to set up logging
    """
    try:

        # Make sure one or the other exists and if not return None
        if logfile is None and stream_stdout is None:
            return None

        import sys
        import logging
        from logging.handlers import RotatingFileHandler
        # from logging.handlers import SysLogHandler
        from logging import StreamHandler

        # STANDARD FOR BOTH LOGFILE or STDOUT HANDLERS
        formatter = logging.Formatter('%(asctime)s %(levelname)s [%(filename)s:%(lineno)3d] - %(message)s')

        logger = logging.getLogger(label)

        # Logger already initialized — do not reconfigure
        if logger.handlers:
            return logger

        logger.setLevel(logging.INFO)

        # Prevent log propagation to root logger (avoids duplicates / side effects)
        logger.propagate = False

        # LOGFILE
        # If we are asked to write to a log file
        if logfile:
            logfile_handler = RotatingFileHandler(
                logfile,
                maxBytes=1024 * 1024 * 100,
                backupCount=logfile_backup_count,  # use parameter
                delay=True  # open file lazily / recreate safely
            )
            logfile_handler.setFormatter(formatter)
            logger.addHandler(logfile_handler)

        # STREAM / STDOUT
        if stream_stdout is False:
            pass
        else:
            stdout_handler = StreamHandler(sys.stdout)
            stdout_handler.setFormatter(formatter)
            logger.addHandler(stdout_handler)

        # # SYSLOG TBD
        # if stream_syslog == False:
        #     pass
        # else:
        #     syslog_handler = SysLogHandler()
        #     logger.addHandler(syslog_handler)

        # If we need to print out more info
        if verbose:
            logger.setLevel(logging.DEBUG)

        # If we need to print out less info
        if quiet:
            logger.setLevel(logging.ERROR)

        return logger

    except Exception as err:
        raise RuntimeError(generic_error_message(error_code='COMMON-100', err=err))


# ----------------------------------------------------------------------------------------------------
def print_config_dict(config_dict=None):
    try:
        import json
        print_stdout(json.dumps(config_dict, sort_keys=True, indent=4))
    except Exception as err:
        raise RuntimeError(generic_error_message(error_code='COMMON-100', err=err))


# ----------------------------------------------------------------------------------------------------
def get_dict_item(inbound_dict=None, dict_path=None, default=None, error_if_missing=False):
    try:
        # This is the end
        if len(dict_path) == 1:
            item = dict_path[0]
            if item in inbound_dict:
                # This does not exist here
                return inbound_dict[item]
            else:
                if error_if_missing:
                    raise RuntimeError(generic_error_message(error_code='COMMON-100'))
                else:
                    return default

        # We have more work
        elif len(dict_path) > 1:

            if dict_path[0] in inbound_dict:
                item = dict_path[0]
                dict_path.pop(0)
                return get_dict_item(inbound_dict=inbound_dict[item], dict_path=dict_path, default=default,
                                     error_if_missing=error_if_missing)
            else:
                # This does not exist here
                if error_if_missing:
                    raise RuntimeError(generic_error_message(error_code='COMMON-100'))
                else:
                    return default

    except Exception as err:
        raise RuntimeError(generic_error_message(error_code='COMMON-100', err=err))


# ----------------------------------------------------------------------------------------------------
def get_default_secrets_files(script_run_dir=None, script_file=None, script_group=None):
    try:

        import os
        import sys
        import getpass

        # Try to get user
        user = 'default'
        try:
            user = getpass.getuser()
        except Exception as err:
            pass

        default_secrets_files = [
            '/app/' + user + '/conf/' + os.path.basename(script_file).replace('.py', '') + '-secrets.yml',
            '/app/' + user + '/conf/utils-secrets.yml',
            '~/conf/' + os.path.basename(script_file).replace('.py', '') + '-secrets.yml',
            '~/conf/utils-secrets.yml',
            './' + os.path.basename(script_file).replace('.py', '') + '-secrets.yml',
            './utils-secrets.yml'
        ]

        # If we have SECRETS_FILE in our environment add this as a potential secrets file
        if 'SECRETS_FILE' in os.environ:
            default_secrets_files.append(os.environ['SECRETS_FILE'])

        # If we passed a script group from the script
        if script_group:
            default_secrets_files.append('/app/' + user + '/conf/' + script_group + '-secrets.yml')
            default_secrets_files.append('~/conf/' + script_group + '-secrets.yml')

        return default_secrets_files

    except Exception as err:
        raise RuntimeError(generic_error_message(error_code='COMMON-100'))


# ----------------------------------------------------------------------------------------------------
def get_default_config_files(script_run_dir=None, script_file=None, script_group=None):
    try:

        import os
        import sys
        import getpass

        # Try to get user
        user = 'default'
        try:
            user = getpass.getuser()
        except Exception as err:
            pass

        default_config_files = []

        package_base_dir = get_package_base_dir()

        if os.name == 'nt':

            default_config_files = [
                os.environ['HOMEDRIVE'] + '\\conf\\config.yml',
                os.environ['HOMESHARE'] + '\\conf\\config.yml',
            ]
        else:
            default_config_files = [
                package_base_dir + '/conf/' + os.path.basename(script_file).replace('.py', '') + '-config.yml',
                package_base_dir + '/conf/config.yml',
                '/app/' + user + '/conf/' + os.path.basename(script_file).replace('.py', '') + '-config.yml',
                '/app/' + user + '/conf/config.yml',
                '~/conf/' + os.path.basename(script_file).replace('.py', '') + '-config.yml',
                '~/conf/config.yml'
            ]

        # If we have CONFIG_FILE in our environment add this as a potential config file
        if 'CONFIG_FILE' in os.environ:
            default_config_files.append(os.environ['CONFIG_FILE'])

        # If we passed a script group from the script
        if script_group:
            default_config_files.append('/app/' + user + '/conf/' + script_group + '-config.yml')
            default_config_files.append('~/conf/' + script_group + '-config.yml')

        return default_config_files

    except Exception as err:
        raise RuntimeError(generic_error_message(error_code='COMMON-100', err=err))


# ----------------------------------------------------------------------------------------------------
def load_config_file(config_file=None, default_config_files=None, log=None):
    try:

        import os
        import sys
        import yaml

        if log is None:
            log = initialize_logging()

        log.debug("Loading config ... ")

        # Load in the config file
        config_dict = None
        if config_file:
            if os.path.isfile(config_file):
                log.debug("Loading config file passed in: " + config_file)
                with open(config_file) as f:
                    config_dict = yaml.safe_load(f)
                    config_dict['loaded_config_file'] = config_file
            else:
                raise RuntimeError(generic_error_message(error_code='COMMON-100'))
        else:
            # Check the default config files
            log.debug("No config file passed in, using defaults")
            for default_config_file in default_config_files:
                expanded_path = os.path.expanduser(default_config_file)
                if os.path.isfile(expanded_path):
                    with open(expanded_path) as f:
                        log.debug("Loading in: " + expanded_path)
                        config_dict = yaml.safe_load(f)
                        config_dict['loaded_config_file'] = expanded_path

        # Make sure we have a config file and if not exit
        if config_dict is None:
            log.error("No configuration here, cannot do anything.")
            if config_file:
                log.error("FYI: config_file=" + config_file)
            if default_config_files:
                for default_config_file in default_config_files:
                    if os.path.isfile(expanded_path):
                        log.error("FILE EXISTS: default_config_file=" + default_config_file)
                    else:
                        log.error("NO SUCH FILE: default_config_file=" + default_config_file)

            return None

        # Now in the config file we did load, check for any ***includes*** to other config files and load those as well
        # These can only be at the ROOT LEVEL, and they must have a str parameter named include_xxx.yml, and the value is set to this spot in the config
        # This included file must also be a yaml file and must be well-formed or the config section will not be included
        # If the file does not exist, it will just skip it
        # The included config file must also be in the same dir as the main config file
        # These included files are usually for secrets and such

        for config_file in os.listdir(os.path.dirname(config_dict['loaded_config_file'])):
            log.debug("Config file: " + str(config_file))

        for config_item in config_dict:
            if isinstance(config_dict[config_item], str):
                if 'include-' in config_dict[config_item] and '-config.yml' in config_dict[config_item]:
                    log.debug("----> Trying to load in file: " + config_dict[config_item])
                    try:
                        base_dir = os.path.dirname(config_dict['loaded_config_file'])
                        included_config_file = base_dir + "/" + config_dict[config_item]
                        if os.path.isfile(included_config_file):
                            with open(included_config_file) as f:
                                included_config_dict = yaml.safe_load(f)
                                included_config_dict['loaded_config_file'] = included_config_file
                                log.debug("Loading in include file OK: " + included_config_file)
                            if config_item in included_config_dict:
                                config_dict[config_item] = included_config_dict[config_item]
                            else:
                                config_dict[config_item] = included_config_dict
                        else:
                            raise Exception(
                                "No such file: " + included_config_file + " Removing this tree and setting it to default.")

                    except Exception as err:
                        pass


        if config_dict:
            return config_dict

    except Exception as err:
        raise RuntimeError(generic_error_message(error_code='COMMON-100', err=err))


# COMMON SECTION: ASSIST DEBUGGING
# -----------------------------------------------------
def get_package_base_dir():
    """
    Standard way to print where we are, what OS we are, what directory we are in, what user we are ...
    """

    try:

        import os
        import utils
        package_base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return package_base_dir

    except Exception as err:
        print_stdout(err)
        return '.'


# ----------------------------------------------------------------------------------------------------
def print_stdout(obj):
    """
    Standard way to print some debug of a variable or somehting -- do it here so that we can better fix
    """

    try:

        # This is the only place whereby we should just be printing via print
        print(obj)

    except Exception as err:
        raise RuntimeError(generic_error_message(err=err))


# COMMON SECTION: EXCEPTION / ERROR HANDLING
# ----------------------------------------------------------------------------------------------------
def generic_error_message(error_code=None, err=None):
    try:

        if error_code is None:
            error_code = 'APP-100'

        return error_code + ' error=' + str(err)

    except Exception as err:
        return 'ERROR ' + str(err)

# ----------------------------------------------------------------------------------------------------
def get_config_secret(log=None, config_dict=None, config_item_path=None, envvar=None, ask_if_missing=False,
                      raise_if_missing=False, default=None):
    try:
        import os

        # This is the same as get_config_dict_item except we have a future hook for lookup in a secrets DB

        # Try and get this from a config
        secret = get_config_dict_item(log=log, config_dict=config_dict, config_item_path=config_item_path,
                                      envvar=envvar,
                                      default=default)
        if secret is None:
            if ask_if_missing is True:
                import getpass
                try:
                    if os.name == 'nt':
                        user_input_secret = None

                        from tkinter import Tk, Frame, StringVar, Entry, Button, Label
                        root = Tk()
                        root.geometry("600x600")
                        root.resizable(False, False)
                        root.title('Secret Collection')

                        # store email address and password
                        email = StringVar()
                        password = StringVar()

                        def login_clicked():
                            collected_password = 'x'
                            collected_password = password.get()  # get password from entry
                            root.setvar(name='collected_password', value=collected_password)
                            root.destroy()

                        # Sign in frame
                        signin = Frame(root)
                        signin.pack(padx=10, pady=10, fill='x', expand=True)

                        # password
                        password_label = Label(signin, text="Password for: " + ' >> '.join(config_item_path))
                        password_label.pack(fill='x', expand=True)

                        password_entry = Entry(signin, textvariable=password, show="*")
                        password_entry.pack(fill='x', expand=True)

                        # login button
                        login_button = Button(signin, text="Password", command=login_clicked)
                        login_button.pack(fill='x', expand=True, pady=10)

                        root.mainloop()

                        secret = root.getvar(name='collected_password')

                        log.info("Secret Collected: " + str(secret))

                    else:
                        log.info("Requesting password from STDIN on UNIX: ")
                        secret = getpass.getpass()
                except Exception as error:
                    log.info('ERROR', error)
                else:
                    log.info('Password entered:')

                return secret
        else:
            return secret

        if raise_if_missing is True and secret is None:
            raise Exception("No secret here.")

    except Exception as err:
        raise RuntimeError(generic_error_message(error_code='COMMON-100'))


# ----------------------------------------------------------------------------------------------------
def get_config_dict_item(log=None, config_dict=None, config_item_path=None, envvar=None, default=None):
    """
    This function is a more graceful way to get a config item out of the configuration file.
    Since config files may not be 100% or missing some configuration item, we want to make sure we tell the user EXACTLY what the issue is instead of bombing
    """
    try:

        import json
        import os

        # If we have an env var for this, use it no matter what
        if envvar:
            if log:
                log.debug("get_config_dict_item ENVVAR CONFIG REQUESTED: " + str(envvar))

            if envvar in os.environ:
                if log:
                    log.debug("get_config_dict_item ENVVAR EXISTS: " + str(envvar))
                return os.environ[envvar]
            else:
                if log:
                    log.debug(
                        "get_config_dict_item ENVVAR DOES NOT EXIST, SHOWING ENVIRONMENT + CHECKING OTHER CONFIG SETTINGS")
                    for env in sorted(os.environ):
                        log.debug("ENV VAR: " + env + " = " + os.environ[env])

        # Function for error handling
        def handle_config_lookup_error(log=None, default=None, error_message=None):

            if log:
                log.debug("get_config_dict_item RETURNING handle_config_lookup_error: " + str(default))

            # We ran into a problem and are asking for default, so would like to just send back the default
            if default:
                if log:
                    log.debug("get_config_dict_item RETURNING DEFAULT: " + str(default))
                return default
            else:
                if log:
                    log.debug("get_config_dict_item RETURNING NONE BECAUSE WE HAVE AN ERROR AND NO DEFAULT")
                return None

        # Print info
        if log:
            log.debug("get_config_dict_item CONFIG DICT AS JSON: " + json.dumps(config_dict, indent=2))
            # log.debug("get_config_dict_item CONFIG PATH: " + ' >> '.join(config_item_path))
            log.debug("get_config_dict_item DEFAULT: " + str(default))

        # Did we pass in a config dict?
        if config_dict is None:
            return_value = handle_config_lookup_error(log=log, default=default,
                                                      error_message="No config_dict passed, how am I supposed to look up any config item")
            return return_value

        # Did we pass in a config dict?
        if config_item_path is None:
            return_value = handle_config_lookup_error(log=log, default=default,
                                                      error_message="No config item passed, how am I supposed to look up any config item")
            return return_value

        # Is config item path a liast?
        if isinstance(config_item_path, list) is False:
            return_value = handle_config_lookup_error(log=log, default=default,
                                                      error_message="Did not pass a list for the path")
            return return_value

        config_dict_item = None

        config_item_path_length = len(config_item_path)

        current_config_pointer = config_dict

        index = 0

        for item in config_item_path:
            index += 1
            if item in current_config_pointer:
                current_config_pointer = current_config_pointer[item]
            else:
                return_value = handle_config_lookup_error(log=log, default=default,
                                                          error_message="No config item found at the path you specified")
                return return_value

            if index >= config_item_path_length:
                # Break out of loop
                if log:
                    log.debug("get_config_dict_item BREAKING OUT OF LOOP")
                break

        # Check if we have a path but the config location is not set
        if current_config_pointer is None:
            return handle_config_lookup_error(log=log, default=default, error_message="Configuration item is None")

        # We never set it to anything other than the config_dict:
        if current_config_pointer == config_dict:
            return handle_config_lookup_error(log=log, default=default,
                                              error_message="Could not find config you were looking for.")

        # OK we got something at the full path we were looking for ...
        if log:
            log.debug("get_config_dict_item RETURNING FOUND LOCATION: " + str(current_config_pointer))
        return current_config_pointer

    except Exception as err:
        raise RuntimeError(generic_error_message(error_code='COMMON-100'))


# ----------------------------------------------------------------------------------------------------
def load_secrets_file(secrets_file=None, default_secrets_files=None, config_dict=None):
    try:

        import os
        import sys
        import yaml

        # Load in the secrets file
        secrets_dict = None
        if secrets_file:
            if os.path.isfile(secrets_file):
                with open(secrets_file) as f:
                    secrets_dict = yaml.safe_load(f)
                    secrets_dict['loaded_secrets_file'] = secrets_file
            else:
                raise RuntimeError(generic_error_message(error_code='COMMON-100'))
        else:
            # Check the default secrets files

            for default_secrets_file in default_secrets_files:
                expanded_path = os.path.expanduser(default_secrets_file)
                if os.path.isfile(expanded_path):
                    with open(expanded_path) as f:
                        secrets_dict = yaml.safe_load(f)
                        secrets_dict['loaded_secrets_file'] = expanded_path

        merged_dict = {**config_dict, **secrets_dict}

        return merged_dict

    except Exception as err:
        raise RuntimeError(generic_error_message(error_code='COMMON-100'))


# COMMON SECTION: COMMAND LINE ARGUMENT PARSING

# ----------------------------------------------------------------------------------------------------
def get_username():
    try:

        import getpass
        return getpass.getuser()

    except Exception as err:
        print(err)
        raise RuntimeError(generic_error_message(error_code='COMMON-100', err=err))


# ----------------------------------------------------------------------------------------------------
def check_args(arg_pick_one_list=None):
    try:
        if arg_pick_one_list:
            check_list = isinstance(arg_pick_one_list, list)
            if check_list:
                for arg in arg_pick_one_list:
                    if arg is None:
                        pass
        return True

    except Exception as err:
        raise RuntimeError(generic_error_message(error_code='COMMON-100'))


# ----------------------------------------------------------------------------------------------------
def get_app_arg_group(parser=None):
    try:
        from optparse import OptionParser, OptionGroup

        # APP Group
        app_arg_group = OptionGroup(parser, "Application Options", "")
        app_arg_group.add_option('-e', '--environment', dest="environment", type="string", action="store",
                                 help="Environment like dev, maptest, mapstage, test, stage, prod, training")
        app_arg_group.add_option('-a', '--app', dest="app", type="string", action="store",
                                 help="Application like sibr, market, iooc, oasis")
        app_arg_group.add_option('-C', '--component', dest="app_component", type="string", action="store",
                                 help="Component like sibrws, marketws, ioocui, oasisiws")
        app_arg_group.add_option('-n', '--node', dest="node", type="string", action="store",
                                 help="Node/Server/Host like fqapintxxx ")

        return app_arg_group

    except Exception as err:
        raise RuntimeError(generic_error_message(error_code='COMMON-100', err=err))


# ----------------------------------------------------------------------------------------------------
def get_common_arg_group(parser=None):
    try:
        from optparse import OptionParser, OptionGroup

        common_arg_group = OptionGroup(parser, "Common Options", "")
        # Standard command line args
        common_arg_group.add_option('-F', '--config_file', dest="config_file", action="store",
                                    help="Location of config file to use -- overrides any other discoverable configuration files")
        common_arg_group.add_option('-V', '--version', dest="version", action="store_true", default=False,
                                    help="Print the version")
        common_arg_group.add_option('-v', '--verbose', dest="verbose", action="store_true", default=False,
                                    help="Print more verbose details. Turn on verbose.")
        common_arg_group.add_option('-q', '--quiet', dest="quiet", action="store_true", default=False,
                                    help="Don't print details. Turn off verbose be as quiet as possible (if script permits).")

        return common_arg_group

    except Exception as err:
        raise RuntimeError(generic_error_message(error_code='COMMON-100', err=err))

#