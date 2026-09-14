# -*- coding: utf-8 -*-
"""SOL-0036 · Secciones más usadas / últimas usadas arriba de la portada.

Pedido (Joaquín, 14/09/2026): "uso todos los días Tanques y estaría bueno que aparezca
arriba de todo". Solución: cada entrada a una sección deja una fila en
``produccion.fact_uso_seccion``; la portada clásica muestra ARRIBA hasta 3 accesos
destacados (más usados en 30 días, o últimos usados) con el mismo formato de tile, y
abajo el bloque "Accesos" de siempre con el resto en su orden fijo.

Por qué NO se reordena toda la grilla: una grilla que cambia de lugar cada día rompe
la memoria muscular del operario. Un "podio" de 3 arriba + el resto fijo da el acceso
rápido sin mover nada de lugar.

* Los ADMIN no ven el podio (pedido explícito del ticket): modo FIJO siempre.
* El usuario elige el criterio (prefs.orden_secciones: FRECUENTE | RECIENTE | FIJO).
* MEJORAS (soporte) nunca compite por el podio.
* Todo tolerante a fallas: sin tabla / sin DB, la portada es la de siempre.
"""
import json
import time

import streamlit as st

PREF_KEY = "orden_secciones"           # dim_usuario.prefs ->> 'orden_secciones'
MODOS = ("FRECUENTE", "RECIENTE", "FIJO")
ETIQUETAS = {"FRECUENTE": "⭐ Más usadas", "RECIENTE": "🕒 Últimas usadas", "FIJO": "📌 Orden fijo"}
TITULOS = {"FRECUENTE": "⭐ Tus secciones más usadas", "RECIENTE": "🕒 Tus últimas secciones"}
MAX_DESTACADAS = 3
MIN_USOS = 2                           # FRECUENTE: recién con 2 entradas en 30 días
EXCLUIR = ("MEJORAS",)
_TTL = 60                              # segundos de cache de las estadísticas en sesión


# ------------------------------------------------------------------ registro de uso
def registrar_uso(conn_factory, USR, seccion):
    """Una fila por ENTRADA a una sección (no por rerun). Silencioso si falla."""
    if not seccion or seccion in EXCLUIR:
        return
    if st.session_state.get("_uso_ult_sec") == seccion:
        return
    st.session_state["_uso_ult_sec"] = seccion
    try:
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO produccion.fact_uso_seccion (id_usuario, seccion) VALUES (%s, %s)",
                            (USR["id_usuario"], seccion))
            conn.commit()
        st.session_state.pop("_uso_stats", None)
    except Exception:
        pass


# ------------------------------------------------------------------ preferencia
def get_modo(conn_factory, USR):
    if USR.get("rol") == "ADMIN":
        return "FIJO"
    k = "_uso_modo"
    if k in st.session_state:
        return st.session_state[k]
    modo = "FRECUENTE"
    try:
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT prefs->>%s FROM dim_usuario WHERE id_usuario=%s", (PREF_KEY, USR["id_usuario"]))
                row = cur.fetchone()
        if row and row[0] in MODOS:
            modo = row[0]
    except Exception:
        pass
    st.session_state[k] = modo
    return modo


def set_modo(conn_factory, USR, modo):
    if modo not in MODOS:
        return
    st.session_state["_uso_modo"] = modo
    if isinstance(st.session_state.get("_prefs"), dict):
        st.session_state["_prefs"][PREF_KEY] = modo
    try:
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE dim_usuario SET prefs = COALESCE(prefs,'{}'::jsonb) || %s::jsonb WHERE id_usuario=%s",
                            (json.dumps({PREF_KEY: modo}), USR["id_usuario"]))
            conn.commit()
    except Exception:
        pass


# ------------------------------------------------------------------ estadísticas
def _stats(conn_factory, USR):
    """{seccion: (usos_30d, ultimo_uso_epoch)} cacheado _TTL segundos en la sesión."""
    c = st.session_state.get("_uso_stats")
    if c and time.time() - c[0] < _TTL:
        return c[1]
    out = {}
    try:
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT seccion, usos_30d, extract(epoch FROM ultimo_uso) "
                            "FROM produccion.v_uso_seccion_usuario WHERE id_usuario=%s", (USR["id_usuario"],))
                for sec, n, ult in cur.fetchall():
                    out[sec] = (int(n or 0), float(ult or 0))
    except Exception:
        out = {}
    st.session_state["_uso_stats"] = (time.time(), out)
    return out


def destacadas(conn_factory, USR, tiles, puede_seccion):
    """tiles: tuplas (icono, titulo, desc, sec, key, primario) de app.py.
    Devuelve (modo, destacadas, resto) — resto conserva el orden fijo de siempre."""
    st.session_state["_uso_ult_sec"] = None      # volvió a la portada: la próxima entrada cuenta
    permitidas = [t for t in tiles if puede_seccion(t[3])]
    modo = get_modo(conn_factory, USR)
    if modo == "FIJO":
        return modo, [], permitidas
    stats = _stats(conn_factory, USR)
    if modo == "FRECUENTE":
        cand = sorted(((s, v) for s, v in stats.items() if v[0] >= MIN_USOS), key=lambda x: (-x[1][0], -x[1][1]))
    else:
        cand = sorted(((s, v) for s, v in stats.items() if v[1] > 0), key=lambda x: -x[1][1])
    by_sec = {t[3]: t for t in permitidas}
    top = [s for s, _ in cand if s not in EXCLUIR and s in by_sec][:MAX_DESTACADAS]
    dest = [by_sec[s] for s in top]
    resto = [t for t in permitidas if t[3] not in top]
    return modo, dest, resto


# ------------------------------------------------------------------ UI
def selector_modo(conn_factory, USR, key="uso_modo_sel"):
    """Radio chico al pie de los accesos. No se dibuja para ADMIN."""
    if USR.get("rol") == "ADMIN":
        return
    actual = get_modo(conn_factory, USR)
    ops = list(MODOS)
    st.caption("Orden de los accesos")
    sel = st.radio("Orden de los accesos", ops, index=ops.index(actual), horizontal=True,
                   format_func=lambda m: ETIQUETAS[m], key=key, label_visibility="collapsed")
    if sel != actual:
        set_modo(conn_factory, USR, sel)
        st.rerun()
