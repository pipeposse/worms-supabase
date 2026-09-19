# -*- coding: utf-8 -*-
"""🚨 Errores y trabas — lo que el sistema le está tirando a la gente.

Regla de dirección (19/09): *un sistema que traba y da más trabajo deja de
servir*. Cada error o traba que la app le muestra a un usuario se registra solo
en `produccion.log_error_app` (lo escribe `guardado.registrar_error`, desde los
envoltorios de `st.error` / `st.exception` y desde cada recibo en rojo). Acá se
ven agrupados, con cuántas veces pasó, a cuánta gente y desde cuándo, para
corregirlos sin tener que pedirle al operario que reproduzca nada.

render(USR, cat, conectar)
"""
import pandas as pd
import streamlit as st

import guardado as _g

_SQL_ABIERTO = (
    "SELECT tipo, pantalla, accion, mensaje, veces, usuarios, "
    "       to_char(primera AT TIME ZONE 'America/Argentina/Buenos_Aires','DD/MM HH24:MI') AS desde, "
    "       to_char(ultima  AT TIME ZONE 'America/Argentina/Buenos_Aires','DD/MM HH24:MI') AS ultima, "
    "       id_ultimo "
    "FROM produccion.v_error_app_abierto")

_SQL_DETALLE = (
    "SELECT id_error, ts AT TIME ZONE 'America/Argentina/Buenos_Aires' AS cuando, tipo, pantalla, "
    "       accion, usuario, mensaje, detalle, traceback "
    "FROM produccion.log_error_app WHERE id_error=%s")


def pendientes():
    """Cuántos grupos de error abiertos hay (para el badge del menú). 0 si no se pudo leer."""
    try:
        _n = _g.contar("SELECT count(*) FROM produccion.v_error_app_abierto")
        return int(_n or 0)
    except Exception:
        return 0


def render(USR, cat, conectar):
    st.markdown(
        "<div style='background:linear-gradient(90deg,#7f1d1d,#dc2626);border-radius:14px;"
        "padding:16px 20px;margin:0 0 12px'>"
        "<div style='color:#fff;font-size:1.4rem;font-weight:900'>🚨 Errores y trabas</div>"
        "<div style='color:#fee2e2;font-size:.88rem;margin-top:3px'>Todo lo que el sistema le "
        "tiró a un usuario en los últimos 7 días, agrupado. Se registra solo: nadie tiene que "
        "avisar ni reproducir el error.</div></div>", unsafe_allow_html=True)

    df = _g.leer(_SQL_ABIERTO)
    if df is None:
        df = cat(_SQL_ABIERTO)
    if df is None:
        st.warning("No pude leer el registro de errores.")
        return
    if df.empty:
        st.success("✅ Ningún error ni traba abiertos en los últimos 7 días.")
        return

    k1, k2, k3 = st.columns(3)
    k1.metric("Errores distintos", len(df))
    k2.metric("Veces que pasó", int(pd.to_numeric(df["veces"], errors="coerce").fillna(0).sum()))
    k3.metric("Usuarios afectados",
              int(pd.to_numeric(df["usuarios"], errors="coerce").fillna(0).max() or 0))

    _v = df.rename(columns={"tipo": "Tipo", "pantalla": "Pantalla", "accion": "Acción",
                            "mensaje": "Mensaje", "veces": "Veces", "usuarios": "Usuarios",
                            "desde": "Desde", "ultima": "Última"})
    _cols = ["Tipo", "Pantalla", "Acción", "Mensaje", "Veces", "Usuarios", "Desde", "Última"]
    try:
        _sel = st.dataframe(_v[_cols], hide_index=True, use_container_width=True, height=380,
                            on_select="rerun", selection_mode="single-row", key="err_tabla")
        _rows = list((_sel.get("selection", {}) or {}).get("rows", []))
    except Exception:
        st.dataframe(_v[_cols], hide_index=True, use_container_width=True)
        _rows = []

    if not _rows:
        st.caption("Tocá una fila para ver el detalle técnico del último caso y marcarlo resuelto.")
        return

    _r = df.iloc[_rows[0]]
    _det = _g.leer(_SQL_DETALLE, (int(_r["id_ultimo"]),))
    st.markdown("#### %s · %s" % (_r["tipo"], _r["mensaje"]))
    if _det is not None and not _det.empty:
        _d = _det.iloc[0]
        c1, c2, c3 = st.columns(3)
        c1.metric("Pantalla", str(_d["pantalla"] or "—"))
        c2.metric("Usuario", str(_d["usuario"] or "—"))
        c3.metric("Cuándo", str(_d["cuando"])[:16])
        if _d.get("detalle"):
            st.json(_d["detalle"])
        if _d.get("traceback"):
            with st.expander("🔧 Traceback"):
                st.code(str(_d["traceback"]))

    _nota = st.text_input("Nota de la corrección (opcional)", key="err_nota")
    if st.button("✅ Marcar como resuelto", type="primary", key="err_ok"):
        try:
            with conectar(USR["id_usuario"]) as (conn, _a):
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE produccion.log_error_app SET resuelto=true, resuelto_en=now(), "
                        "nota=COALESCE(%s, nota) "
                        "WHERE NOT resuelto AND tipo=%s AND COALESCE(mensaje,'')=COALESCE(%s,'') "
                        "  AND COALESCE(pantalla,'')=COALESCE(%s,'')",
                        ((_nota or None), _r["tipo"], _r["mensaje"], _r["pantalla"]))
                    _n = cur.rowcount
                _a.log("U", "log_error_app", int(_r["id_ultimo"]), {"resuelto": True})
            cat.clear()
            _g.anotar("err_panel", True, "%d registro(s) marcados como resueltos" % _n,
                      detalle=str(_r["mensaje"])[:200])
            st.rerun()
        except Exception as e:
            _g.anotar("err_panel", False, "No se pudo marcar como resuelto", error=str(e))
            st.rerun()
