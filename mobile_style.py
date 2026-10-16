"""Responsive layout adjustments shared by login and dashboard pages."""

MOBILE_CSS = '''<style>
.st-key-mobile_navigation {display:none;}
@media (max-width: 768px) {
    .st-key-mobile_navigation {display:block;}
    .stMainBlockContainer.block-container {
        padding:1rem 1rem 2rem;
        padding-top:calc(3.75rem + env(safe-area-inset-top, 0px));
    }
    [data-testid="stHorizontalBlock"] {
        flex-direction:column;
        gap:1rem;
    }
    [data-testid="stColumn"] {
        width:100% !important;
        min-width:0 !important;
        flex:1 1 100% !important;
    }
    [data-testid="stMetric"] {padding:12px 14px;}
    [data-testid="stMetricValue"] {font-size:clamp(1.5rem, 7vw, 2rem);}
    [data-testid="stMetricLabel"] {white-space:normal;}
    h1 {font-size:1.8rem;overflow-wrap:anywhere;}
    h2 {font-size:1.45rem;overflow-wrap:anywhere;}
    h3 {font-size:1.2rem;overflow-wrap:anywhere;}
    [data-testid="stButton"] button,
    [data-testid="stDownloadButton"] button,
    [data-testid="stFormSubmitButton"] button {min-height:44px;width:100%;}
    [data-baseweb="input"] input,
    [data-baseweb="textarea"] textarea,
    [data-baseweb="select"] input {font-size:16px;}
    [data-baseweb="select"] > div {min-height:44px;}
    [data-testid="stRadio"] label,
    [data-testid="stCheckbox"] label {min-height:44px;}
    [data-testid="stDataFrame"], [data-testid="stDataEditor"],
    [data-testid="stVegaLiteChart"] {max-width:100%;min-width:0;}
    [data-testid="stFileUploaderDropzone"] {padding:1rem;flex-wrap:wrap;gap:.5rem;}
    [data-testid="stFileUploaderDropzone"] button {min-height:44px;}
    [data-testid="stSidebar"] {max-width:calc(100vw - 3rem) !important;}
    .st-key-sidebar_toggle {display:none;}
    [data-testid="stSidebar"] [role="radiogroup"] > label {white-space:normal;}
    [data-testid="stSidebar"] [role="radiogroup"] p {overflow-wrap:anywhere;}
}
</style>'''
