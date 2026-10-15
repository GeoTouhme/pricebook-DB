"""Viewport-triggered entrance animation for native Streamlit charts."""
from pathlib import Path
import streamlit.components.v1 as components


def install_chart_animations():
    script = Path(__file__).with_suffix('.js').read_text(encoding='utf-8')
    components.html(f'<script>{script}</script>', height=0, width=0)
