"""Session-local light/dark styling and a configurable local photo background."""
from __future__ import annotations

import base64
from functools import lru_cache
import logging
import os
from pathlib import Path

import streamlit as st
from project3.config import ROOT

log = logging.getLogger(__name__)


@lru_cache(maxsize=4)
def image_data_uri(path: str, modified_ns: int) -> str:
    """Cache validated local image bytes, invalidating when the asset changes."""
    data = Path(path).read_bytes()
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        mime = 'image/png'
    elif data.startswith(b'\xff\xd8\xff'):
        mime = 'image/jpeg'
    elif data.startswith(b'RIFF') and data[8:12] == b'WEBP':
        mime = 'image/webp'
    else:
        raise ValueError('The background must be a PNG, JPEG or WebP image.')
    return f'data:{mime};base64,{base64.b64encode(data).decode("ascii")}'


def background_uri() -> str:
    """Load the configured photo, falling back gracefully if it is unavailable."""
    if os.getenv('P3_BACKGROUND_ENABLED', 'true').lower() != 'true':
        return ''
    path = Path(os.getenv('P3_BACKGROUND_IMAGE', 'project3/assets/futuristic-it-background.png')).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    try:
        stat = path.stat()
        if stat.st_size > 8 * 1024 * 1024:
            raise ValueError('Background image exceeds the 8 MB asset limit.')
        return image_data_uri(str(path), stat.st_mtime_ns)
    except (OSError, ValueError) as background_error:
        log.warning('Photo background unavailable (%s); using the solid theme.', type(background_error).__name__)
        return ''


def theme_css(dark: bool, photo: str) -> str:
    """Style the current page only; never change Streamlit's global theme config."""
    palette = {
        'text': '#e8f1ff' if dark else '#13263f',
        'muted': '#b7c8de' if dark else '#435c76',
        'surface': 'rgba(9, 20, 36, .94)' if dark else 'rgba(251, 253, 255, .95)',
        'sidebar': 'rgba(7, 17, 31, .97)' if dark else 'rgba(240, 247, 253, .97)',
        'panel': '#14273f' if dark else '#edf4fa',
        'input': '#0b1c30' if dark else '#ffffff',
        'border': '#35506b' if dark else '#c4d4e3',
        'accent': '#67e8f9' if dark else '#00677b',
        'shade': 'rgba(2, 8, 18, .38)' if dark else 'rgba(229, 241, 250, .34)',
        'base': '#07111f' if dark else '#e9f2fa',
    }
    variables = ';'.join(f'--p3-{key}:{value}' for key, value in palette.items())
    background = f'linear-gradient({palette["shade"]},{palette["shade"]}),url("{photo}")' if photo else 'none'
    return f'''<style>
:root {{ {variables}; color-scheme: {'dark' if dark else 'light'}; }}
[data-testid="stAppViewContainer"] {{
    background-color: var(--p3-base);
    background-image: {background};
    background-size: cover; background-position: center; background-attachment: fixed;
}}
.stApp {{ color: var(--p3-text); }}
[data-testid="stHeader"] {{ background: transparent; }}
[data-testid="stMainBlockContainer"] {{
    background: var(--p3-surface); border: 1px solid var(--p3-border);
    border-radius: 22px; margin: 1.5rem auto; padding: 2rem 2.5rem;
    width: calc(100% - 3rem); max-width: 1320px;
    box-shadow: 0 16px 60px rgba(0, 12, 28, .24);
}}
[data-testid="stSidebar"] {{ background: var(--p3-sidebar); border-right: 1px solid var(--p3-border); }}
[data-testid="stSidebar"], [data-testid="stMain"] {{
    --text-color: var(--p3-text); --background-color: var(--p3-input);
    --secondary-background-color: var(--p3-panel); --primary-color: var(--p3-accent);
    --st-text-color: var(--p3-text); --st-background-color: var(--p3-input);
    --st-secondary-background-color: var(--p3-panel); --st-primary-color: var(--p3-accent);
    color: var(--p3-text);
}}
[data-testid="stMarkdownContainer"], [data-testid="stMarkdownContainer"] p,
[data-testid="stWidgetLabel"] p, [data-testid="stMetricLabel"],
[data-testid="stMetricValue"], h1, h2, h3, h4, label {{ color: var(--p3-text) !important; }}
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {{ color: var(--p3-muted) !important; }}
[data-testid="stMarkdownContainer"] a {{ color: var(--p3-accent); }}
[data-testid="stForm"], [data-testid="stExpander"] details {{
    border-color: var(--p3-border); background: var(--p3-panel); border-radius: 12px;
}}
[data-baseweb="input"], [data-baseweb="input"] > div, input, textarea, select {{
    background: var(--p3-input) !important; color: var(--p3-text) !important;
    border-color: var(--p3-border) !important; caret-color: var(--p3-accent);
}}
input::placeholder, textarea::placeholder {{ color: var(--p3-muted) !important; opacity: 1; }}
input:disabled {{ -webkit-text-fill-color: var(--p3-muted); opacity: 1; }}
button {{ color: var(--p3-text) !important; }}
[data-testid="stBaseButton-secondary"], [data-testid="stBaseButton-secondaryFormSubmit"],
[data-testid="stBaseButton-linkButton"], [data-testid="stDownloadButton"] button {{
    background: var(--p3-input); border: 1px solid var(--p3-border); color: var(--p3-text);
}}
[data-testid="stBaseButton-primary"], [data-testid="stBaseButton-primaryFormSubmit"] {{
    background: #087f91 !important; color: #ffffff !important; border-color: #087f91 !important;
}}
[data-testid="stBaseButton-primary"] p, [data-testid="stBaseButton-primaryFormSubmit"] p {{
    color: #ffffff !important;
}}
button:hover {{ border-color: var(--p3-accent) !important; }}
[data-testid="stAlert"] {{ background: var(--p3-panel); color: var(--p3-text); border: 1px solid var(--p3-border); }}
[role="tab"] {{ color: var(--p3-muted) !important; }}
[role="tab"][aria-selected="true"] {{ color: var(--p3-accent) !important; }}
[data-baseweb="tab-highlight"] {{ background: var(--p3-accent); }}
[data-testid="stTable"] table {{ width: 100%; color: var(--p3-text); background: var(--p3-input); }}
[data-testid="stTable"] th {{ background: var(--p3-panel); color: var(--p3-text); }}
[data-testid="stTable"] td, [data-testid="stTable"] th {{
    color: var(--p3-text); border-color: var(--p3-border); vertical-align: top;
}}
[data-testid="stMetric"] {{ background: var(--p3-panel); border-radius: 12px; padding: 14px; }}
[data-baseweb="popover"], [role="listbox"], [role="dialog"], [role="menu"] {{
    background: var(--p3-panel); color: var(--p3-text);
}}
hr {{ border-color: var(--p3-border); }}
@media (max-width: 700px) {{
    [data-testid="stMainBlockContainer"] {{ width: calc(100% - 1rem); margin: .5rem auto; padding: 1.25rem; border-radius: 14px; }}
    [data-testid="stTable"] {{ overflow-x: auto; }}
}}
</style>'''


def remember_theme() -> None:
    """Retain the user's choice across page refreshes without affecting other users."""
    dark = st.session_state['p3_dark_theme']
    st.query_params['appearance'] = 'dark' if dark else 'light'
    log.info('User selected %s appearance.', 'dark' if dark else 'light')


def render_appearance() -> None:
    """Provide a sidebar toggle and render this session's readable photo treatment."""
    if 'p3_dark_theme' not in st.session_state:
        default = os.getenv('P3_DEFAULT_THEME', 'light').lower()
        preference = st.query_params.get('appearance', default)
        st.session_state['p3_dark_theme'] = preference == 'dark'
    dark = st.sidebar.toggle('Dark theme', key='p3_dark_theme', on_change=remember_theme,
                             help='Switch appearance without losing your briefing.')
    st.markdown(theme_css(dark, background_uri()), unsafe_allow_html=True)
