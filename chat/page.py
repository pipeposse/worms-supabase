"""UI del chat de consultas. Se renderiza como una sección más de la app.
Acceso restringido a SUPERVISOR y ADMIN."""
import streamlit as st

from . import config_chat as cfg
from .engine import get_vanna, is_select_only

SUGERENCIAS = [
    "¿Cuántos camiones entraron ayer y de qué categorías?",
    "Comparar camiones entre ARROYO SECO y ALVEAR en los últimos 30 días",
    "Top 10 procedencias por cantidad de camiones este mes",
    "Kg netos ingresados por día en la última semana",
    "¿Cuántas muestras de laboratorio se rechazaron este mes por producto?",
    "Acidez promedio de AFE por día en la última semana",
]


def render(usr: dict):
    st.title("🤖 Consultas IA")
    st.caption("Preguntá en lenguaje natural sobre camiones y laboratorio. Solo lectura.")

    # ── gate por rol (defensa en profundidad; la tarjeta del landing ya se oculta) ──
    if usr.get("rol") not in cfg.ROLES_PERMITIDOS:
        st.warning("Esta sección está disponible solo para SUPERVISOR y ADMIN.")
        return

    # ── secretos presentes ──
    miss = cfg.faltantes()
    if miss:
        st.error(
            "Falta configurar: **" + ", ".join(miss) + "**.\n\n"
            "Agregalos en *Settings → Secrets* (Streamlit Cloud) o en `.env` local. "
            "Ver `.streamlit/secrets.toml.example`."
        )
        return

    try:
        vn = get_vanna()
    except Exception as e:
        st.error(f"No se pudo inicializar el asistente: {e}")
        return

    # ── ejemplos ──
    st.write("**Ejemplos** (tocá uno o escribí tu pregunta):")
    cols = st.columns(2)
    for i, s in enumerate(SUGERENCIAS):
        if cols[i % 2].button(s, use_container_width=True, key=f"chat_ej_{i}"):
            st.session_state["chat_pregunta"] = s

    ver_sql = st.toggle("Mostrar el SQL generado", value=False, key="chat_ver_sql")

    pregunta = st.text_input(
        "Tu pregunta",
        value=st.session_state.get("chat_pregunta", ""),
        placeholder="¿Cuántos camiones entraron ayer y de qué categorías?",
        key="chat_input",
    )
    if not pregunta:
        return

    with st.spinner("Generando la consulta…"):
        try:
            sql = vn.generate_sql(pregunta)
        except Exception as e:
            st.error(f"No pude generar la consulta: {e}")
            return

    if not is_select_only(sql):
        st.error("La consulta generada no es de solo lectura. Reformulá la pregunta.")
        if ver_sql:
            st.code(sql, language="sql")
        return

    if ver_sql:
        st.code(sql, language="sql")

    with st.spinner("Consultando la base…"):
        try:
            df = vn.run_sql(sql)
        except Exception as e:
            st.error(f"Error al ejecutar la consulta: {e}")
            return

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

    # gráfico automático (si falla, queda solo la tabla)
    if len(df) > 1:
        try:
            code = vn.generate_plotly_code(question=pregunta, sql=sql, df=df)
            fig = vn.get_plotly_figure(plotly_code=code, df=df)
            st.plotly_chart(fig, use_container_width=True)
        except Exception:
            pass
