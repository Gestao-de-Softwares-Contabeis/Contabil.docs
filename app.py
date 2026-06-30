from __future__ import annotations

import streamlit as st

from app.settings import get_n8n_webhook_debug_info, load_settings


st.set_page_config(page_title="Contabil.docs", page_icon="D", layout="wide")

settings = load_settings()
try:
    n8n_debug_info = get_n8n_webhook_debug_info()
except ValueError:
    n8n_debug_info = None

with st.sidebar:
    st.title("Contabil.docs")
    st.caption("V1 operacional")
    if settings.supabase_is_configured:
        st.success("Supabase configurado")
    else:
        st.error("Supabase nao configurado")
    if n8n_debug_info:
        st.success("n8n configurado")
    else:
        st.warning("n8n sem webhook no .env")

pages = [
    st.Page("pages/1_Upload.py", title="Upload", url_path="upload"),
    st.Page("pages/2_Documentos_a_Verificar.py", title="Documentos a verificar", url_path="documentos"),
    st.Page("pages/5_Checklist.py", title="Checklist", url_path="checklist"),
    st.Page("pages/3_Parametrizacao.py", title="Parametrizacao", url_path="parametrizacao"),
    st.Page("pages/4_Historico.py", title="Historico", url_path="historico"),
]

navigation = st.navigation(pages)
navigation.run()
