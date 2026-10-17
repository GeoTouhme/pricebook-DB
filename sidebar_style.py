"""Animated sidebar styling; navigation stays in Streamlit's native widgets."""
from urllib.parse import quote

# Small outline icons share one stroke weight and remain legible in the compact rail.
ICONS = [
    '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    '<path d="m3 7 9-4 9 4-9 4-9-4Zm0 0v10l9 4 9-4V7M12 11v10"/>',
    '<path d="M3 9h18v12H3zM2 3h20v6H2zM9 13h6"/>',
    '<path d="M6 3h12v18l-3-2-3 2-3-2-3 2V3ZM9 7h6M9 11h6M9 15h3"/>',
    '<circle cx="10" cy="10" r="6"/><path d="m15 15 6 6M7 8h6M7 11h4"/>',
    '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M8 3v4M16 3v4M3 11h18m-12 5 2 2 4-4"/>',
    '<path d="M4 20V10m8 10V4m8 16v-7M2 20h20"/>',
    '<path d="M12 16V3m-5 5 5-5 5 5M4 15v6h16v-6"/>',
    '<path d="M2 5h12v12H2zM14 9h4l4 4v4h-8M5 17a2 2 0 1 0 4 0m8 0a2 2 0 1 0 4 0"/>',
]


def sidebar_css(pinned=False):
    expanded = '[data-testid="stSidebar"]' if pinned else (
        '[data-testid="stSidebar"]:is(:hover, :focus-within)')
    icons = []
    for i, paths in enumerate(ICONS, 1):
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#0c0a09" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">{paths}</svg>'
        icons.append(f'''[data-testid="stSidebar"] [role="radiogroup"] > label:nth-child({i})::before {{
            background-image:url("data:image/svg+xml,{quote(svg, safe='')}"); }}''')
    return '<style>' + '''
[data-testid="stSidebar"] {background:var(--dashboard-sidebar, #ffffff) !important;border-right:1px solid var(--dashboard-border, #e8e6e5);}
[data-testid="stSidebarContent"] {padding-left:0 !important;padding-right:0 !important;scrollbar-gutter:auto;}
[data-testid="stSidebarUserContent"] {padding:1.1rem 1rem;}
[data-testid="stSidebar"] [role="radiogroup"] {gap:8px;}
[data-testid="stSidebar"] [role="radiogroup"] > label {
    position:relative;display:flex;align-items:center;gap:13px;
    min-height:48px;padding:10px 13px;border:1px solid transparent;
    border-radius:10px;white-space:nowrap;overflow:hidden;
    transition:background .2s ease,border-color .2s ease,box-shadow .2s ease;
}
[data-testid="stSidebar"] [role="radiogroup"] > label > div:first-child {display:none;}
[data-testid="stSidebar"] [role="radiogroup"] > label::before {
    filter:var(--dashboard-icon-filter, none);
    content:"";width:22px;height:22px;flex:0 0 22px;
    background-size:contain;background-position:center;background-repeat:no-repeat;
}
[data-testid="stSidebar"] [role="radiogroup"] > label:hover {background:var(--dashboard-hover, #e8e6e5);}
[data-testid="stSidebar"] [role="radiogroup"] > label:has(input:checked) {
    background:var(--dashboard-selected, #f5f5f4);border-color:var(--dashboard-selected-border, #e8e6e5);box-shadow:none;
}
[data-testid="stSidebar"] [role="radiogroup"] > label:has(input:checked)::after {
    content:"";position:absolute;left:0;top:15px;bottom:15px;width:3px;
    border-radius:4px;background:var(--dashboard-accent, #3ba6f1);
}
[data-testid="stSidebar"] [role="radiogroup"] > label:focus-within {
    outline:2px solid var(--dashboard-accent, #3ba6f1);outline-offset:2px;
}
.sidebar-brand {display:flex;align-items:center;gap:13px;height:52px;white-space:nowrap;overflow:hidden;}
.sidebar-monogram {flex:0 0 48px;height:48px;display:grid;place-items:center;
    background:var(--dashboard-hover, #f5f5f4);color:var(--dashboard-brand, #0c0a09);border:1px solid var(--dashboard-border, #e8e6e5);border-radius:10px;font:500 21px "Inter Tight",sans-serif;}
.sidebar-brand-name {font-weight:500;color:var(--dashboard-brand, #0c0a09);font-size:16px;}
.sidebar-brand-name small {display:block;color:var(--dashboard-muted, #78716c);font-weight:400;font-size:12px;margin-top:3px;}
.st-key-sign_out button {height:48px;white-space:nowrap;}
.st-key-sidebar_toggle button {height:48px;white-space:nowrap;border-color:var(--dashboard-border, #e8e6e5);background:transparent;border-radius:9999px;}
.st-key-sidebar_toggle button:focus:not(:active) {box-shadow:0 0 0 2px var(--dashboard-accent, #3ba6f1);}
@media (min-width: 769px) {
    [data-testid="stSidebar"][aria-expanded="true"] {
        width:84px !important;min-width:84px !important;max-width:280px !important;
        transition:width .18s ease-out,min-width .18s ease-out;
    }
    [data-testid="stSidebarUserContent"] {padding:1.1rem 16px;overflow-x:hidden;}
    [data-testid="stSidebar"] [role="radiogroup"] > label {width:52px;}
    [data-testid="stSidebar"] [role="radiogroup"] p,
    .sidebar-brand-name, .st-key-sidebar_details,
    .st-key-sidebar_toggle button p, .st-key-sign_out button p {white-space:nowrap;opacity:0;max-width:0;overflow:hidden;transition:opacity .15s ease;}
    .st-key-sidebar_details {display:none;}
    .st-key-sidebar_details p {white-space:normal !important;overflow-wrap:anywhere;}
    EXPANDED[aria-expanded="true"] {width:280px !important;min-width:280px !important;}
    EXPANDED [role="radiogroup"] > label {width:100%;}
    EXPANDED [role="radiogroup"] p,
    EXPANDED .sidebar-brand-name,
    EXPANDED .st-key-sidebar_toggle button p,
    EXPANDED .st-key-sign_out button p {opacity:1;max-width:240px;}
    EXPANDED .st-key-sidebar_details {display:block;opacity:1;max-width:248px;}
}
@media (prefers-reduced-motion: reduce) {
    [data-testid="stSidebar"], [data-testid="stSidebar"] * {transition:none !important;}
}
''' .replace('EXPANDED', expanded) + '\n'.join(icons) + '</style>'
