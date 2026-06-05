"""UI del chat de consultas. Se renderiza como una sección más de la app.
Acceso restringido a SUPERVISOR y ADMIN."""
import pandas as pd
import streamlit as st

from . import config_chat as cfg
from .engine import resolver, is_select_only


@st.cache_data(show_spinner=False, ttl=300)
def _resolver_cacheado(pregunta: str) -> dict:
    """Genera + ejecuta + autocorrige una vez por pregunta (cache corto).
    Evita re-pegarle a Gemini/BD en cada rerun de Streamlit."""
    return resolver(pregunta)

SUGERENCIAS = [
    "¿Cuántos camiones entraron ayer y de qué categorías?",
    "¿Entraron más camiones en abril o en mayo?",
    "¿Cuánto stock hay en cada tanque ahora?",
    "Stock total por producto en los tanques",
    "¿Cuántas muestras de laboratorio se rechazaron este mes por producto?",
    "Acidez promedio de AFE por día en la última semana",
]


def _auto_chart(df: pd.DataFrame):
    """Gráfico simple cuando el resultado se presta (sin dependencias extra)."""
    if df is None or len(df) < 2 or df.shape[1] < 2:
        return
    num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    cat_cols = [c for c in df.columns if c not in num_cols]
    if not num_cols or not cat_cols:
        return
    x = cat_cols[0]
    y = num_cols[:3]
    try:
        primera = str(x).lower()
        if "fecha" in primera or "dia" in primera or "mes" in primera:
            st.line_chart(df.set_index(x)[y], use_container_width=True)
        else:
            st.bar_chart(df.set_index(x)[y], use_container_width=True)
    except Exception:
        pass


def render(usr: dict):
    st.title("🤖 Consultas IA")
    st.caption("Preguntá en lenguaje natural sobre camiones, laboratorio, producción y tanques. Solo lectura.")

    # gate por rol (defensa en profundidad; la tarjeta del landing ya se oculta)
    if usr.get("rol") not in cfg.ROLES_PERMITIDOS:
        st.warning("Esta sección está disponible solo para SUPERVISOR y ADMIN.")
        return

    miss = cfg.faltantes()
    if miss:
        st.error(
            "Falta configurar: **" + ", ".join(miss) + "**.\n\n"
            "Agregalos en *Settings -> Secrets* (Streamlit Cloud). "
            "Ver `.streamlit/secrets.toml.example`."
        )
        return

    st.write("**Ejemplos** (tocá uno o escribí tu pregunta):")
    cols = st.columns(2)
    for i, s in enumerate(SUGERENCIAS):
        if cols[i % 2].button(s, use_container_width=True, key=f"chat_ej_{i}"):
            st.session_state["chat_input"] = s

    ver_sql = st.toggle("Mostrar el SQL generado", value=False, key="chat_ver_sql")

    pregunta = st.text_input(
        "Tu pregunta",
        placeholder="¿Cuántos camiones entraron ayer y de qué categorías?",
        key="chat_input",
    )
    if not pregunta:
        return

    with st.spinner("Generando y ejecutando la consulta…"):
        try:
            res = _resolver_cacheado(pregunta)
        except Exception as e:
            st.error(f"No pude resolver la consulta: {e}")
            return

    sql = res.get("sql")
    n_correcciones = max(0, len(res.get("intentos", [])) - 1)

    if ver_sql and sql:
        st.code(sql, language="sql")

    if not res.get("ok"):
        if sql and not is_select_only(sql):
            st.error("La consulta generada no es de solo lectura. Reformulá la pregunta.")
        else:
            st.error("No pude obtener un resultado válido para esa pregunta.")
        if n_correcciones:
            st.caption(f"Intenté autocorregir {n_correcciones} vez/veces sin éxito.")
        if res.get("error"):
            with st.expander("Detalle del error"):
                st.code(res["error"])
        return

    if n_correcciones:
        st.caption(f"✅ Resuelto tras autocorregir {n_correcciones} intento(s).")

    df = res.get("df")
    if df is None or df.empty:
        st.info("La consulta no devolvió resultados.")
        return

    st.dataframe(df, use_container_width=True, hide_index=True)
    st.download_button(
        "⬇️ Descargar CSV",
        df.to_csv(index=False).encode("utf-8"),
        file_name="consulta.csv",
        mime="text/csv",
        key="chat_dl",
    )
    _auto_chart(df)
