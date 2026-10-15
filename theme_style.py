"""Keep custom dashboard surfaces in sync with Streamlit's native theme switch."""
from pathlib import Path
import streamlit.components.v1 as components


def install_theme_support():
    components.html(
        '<script>' + Path(__file__).with_suffix('.js').read_text(encoding='utf-8') + '</script>',
        height=0, width=0,
    )
