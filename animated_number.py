"""Install a single reusable browser-side AnimatedNumber for native metrics.

Native metric formatting supplies value, decimals, prefix and suffix; duration
is 200ms by default. The parent-document bridge is specific to Streamlit 1.50.
"""
from pathlib import Path
import streamlit.components.v1 as components


def install_animated_numbers():
    script = Path(__file__).with_suffix('.js').read_text(encoding='utf-8')
    components.html(f'<script>{script}</script>', height=0, width=0)
