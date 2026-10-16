"""Shared Seline-inspired surfaces, type, and controls for the store dashboard."""
DASHBOARD_CSS = '''<style>
:root {
    --dashboard-canvas:#fafaf9;
    --dashboard-card:#ffffff;
    --dashboard-sidebar:#ffffff;
    --dashboard-text:#0c0a09;
    --dashboard-muted:#78716c;
    --dashboard-border:#e8e6e5;
    --dashboard-hover:#f5f5f4;
    --dashboard-selected:#f5f5f4;
    --dashboard-selected-border:#e8e6e5;
    --dashboard-brand:#0c0a09;
    --dashboard-accent:#3ba6f1;
    --dashboard-wash:#c1e1f7;
}
/* Invisible JS helpers must not create empty layout rows. */
[data-testid="stElementContainer"]:has(iframe[height="0"]),
[data-testid="stElementContainer"]:has(> [data-testid="stMarkdown"] style):not(:has(p)) {display:none;}
.stMainBlockContainer.block-container {
    max-width:1200px;padding:2.5rem 2rem 4rem;
}
[data-testid="stAppViewContainer"] {background:var(--dashboard-canvas);}
[data-testid="stHeader"] {background:var(--dashboard-canvas);}
h1, h2, h3 {
    font-family:'Inter Tight',system-ui,sans-serif !important;
    font-weight:400 !important;color:var(--dashboard-text);
    letter-spacing:-.025em;
}
h1 {font-size:2rem !important;line-height:1.25 !important;padding-bottom:1.5rem !important;}
h2 {font-size:1.375rem !important;line-height:1.3 !important;}
h3 {font-size:1.125rem !important;line-height:1.4 !important;}
p, [data-testid="stWidgetLabel"] {font-size:14px;line-height:1.64;}
[data-testid="stCaptionContainer"] p {
    color:var(--dashboard-muted);font-size:13px;line-height:1.6;
}
[data-testid="stMetric"] {
    background:var(--dashboard-card);border:1px solid var(--dashboard-border);
    border-radius:10px;padding:24px;box-shadow:none;min-height:132px;
}
[data-testid="stMetricLabel"] {color:var(--dashboard-muted);font-weight:400;}
[data-testid="stMetricValue"] {
    color:var(--dashboard-text);font-family:'Inter Tight',system-ui,sans-serif;
    font-weight:400;letter-spacing:-.025em;font-variant-numeric:tabular-nums;
}
[data-testid="stVerticalBlockBorderWrapper"] > div {
    border-color:var(--dashboard-border) !important;border-radius:10px !important;
}
.st-key-overview_filters, .st-key-sales_chart_card,
.st-key-department_chart_card, .st-key-product_chart_card {
    background:var(--dashboard-card);border-radius:10px;padding:24px;
}
[data-testid="stExpander"] {
    border:1px solid var(--dashboard-border);border-radius:10px;
    background:var(--dashboard-card);box-shadow:none;
}
[data-testid="stExpander"] summary {padding:12px 16px;font-size:14px;}
[data-testid="stDataFrame"], [data-testid="stDataEditor"] {
    border:1px solid var(--dashboard-border);border-radius:10px;overflow:hidden;
}
[data-testid="stButton"] button, [data-testid="stDownloadButton"] button,
[data-testid="stFormSubmitButton"] button {
    border:1px solid var(--dashboard-border);border-radius:9999px;
    padding:8px 16px;min-height:40px;font-weight:400;
    background:var(--dashboard-card);color:var(--dashboard-text);box-shadow:none;
}
button[kind="primary"], [data-testid="stFormSubmitButton"] button[kind="primaryFormSubmit"] {
    background:#3ba6f1;border-color:#3398e1;color:#0c0a09;font-weight:500;
}
[data-testid="stButton"] button:hover, [data-testid="stDownloadButton"] button:hover {
    border-color:var(--dashboard-accent);color:var(--dashboard-text);
}
button:focus-visible, summary:focus-visible, a:focus-visible {
    outline:2px solid var(--dashboard-accent) !important;outline-offset:3px;
}
[data-baseweb="input"], [data-baseweb="select"] > div,
[data-baseweb="textarea"] {
    border-color:var(--dashboard-border);border-radius:6px;background:var(--dashboard-card);
}
[data-baseweb="input"]:focus-within, [data-baseweb="select"]:focus-within > div,
[data-baseweb="textarea"]:focus-within {
    border-color:var(--dashboard-accent);outline:2px solid var(--dashboard-wash);outline-offset:1px;
}
[data-baseweb="tag"] {
    background:var(--dashboard-hover);color:var(--dashboard-text);border-radius:9999px;
}
[data-testid="stFileUploaderDropzone"] {
    background:var(--dashboard-card);border:1px dashed var(--dashboard-border);border-radius:10px;
}
[data-testid="stAlert"] > div {
    background:var(--dashboard-card);color:var(--dashboard-text);
    border:1px solid var(--dashboard-border);border-radius:10px;
}
[data-testid="stAlert"] svg {color:var(--dashboard-muted);}
[data-testid="stForm"] {
    border-color:var(--dashboard-border);background:var(--dashboard-card);border-radius:10px;
}
.st-key-login {max-width:440px;}
[data-testid="stTabs"] [role="tablist"] {gap:8px;border-bottom-color:var(--dashboard-border);}
[data-testid="stTabs"] button[role="tab"] {
    border:1px solid var(--dashboard-border);border-radius:9999px;padding:8px 16px;height:auto;
}
[data-testid="stTabs"] button[aria-selected="true"] {background:var(--dashboard-text);color:var(--dashboard-card);}
[data-testid="stTabs"] [data-baseweb="tab-highlight"] {display:none;}
hr {border-color:var(--dashboard-border);}
@media (max-width:768px) {
    .stMainBlockContainer.block-container {padding:4.25rem 1rem 2rem;}
    .st-key-overview_filters, .st-key-sales_chart_card,
    .st-key-department_chart_card, .st-key-product_chart_card {padding:16px;}
    [data-testid="stMetric"] {padding:16px;min-height:112px;}
    h1 {font-size:1.75rem !important;}
}
</style>'''
