"""Bound table previews so routine reruns send only the visible page."""
import streamlit as st


def table_page(frame, key, page_size=200):
    pages = max(1, (len(frame) + page_size - 1) // page_size)
    page_key = f'{key}_page'
    if st.session_state.get(page_key, 1) > pages:
        st.session_state[page_key] = pages
    page = st.number_input('Table page', min_value=1, max_value=pages, value=1,
                           step=1, key=page_key) if pages > 1 else 1
    offset = (page - 1) * page_size
    st.caption(f'Rows {offset + 1 if len(frame) else 0:,}–{min(offset + page_size, len(frame)):,} '
               f'of {len(frame):,}. Downloads include all filtered rows.')
    return frame.iloc[offset:offset + page_size]
