# -*- coding: utf-8 -*-
"""Sectores de navegación (produccion.dim_sector_nav) — las 14 tarjetas del área Producción."""

import pandas as pd
import streamlit as st

_SQL = """
    SELECT codigo, nombre_ui, icono, orden, activo, tiene_datos,
           sector_gestion, sector_batch, seccion_clasica, descripcion
    FROM produccion.dim_sector_nav
    WHERE activo
    ORDER BY orden, codigo
"""

# Respaldo si la tabla no existe en el entorno (dev local sin la migración):
# la grilla del director, en su orden.
_FALLBACK = [  # (codigo, nombre_ui, icono, sector_gestion, sector_batch, seccion_clasica)
    ("REACTORES", "Reactor", "⚙️", "REACTORES", "REACTORES", "INICIAR"), ("BACHAS", "Bachas", "🛢️", "BACHAS", "BACHAS", "INICIAR"),
    ("PILETAS", "Piletas", "🌊", "PILETAS", "RECUPERACION", "RECUPERACION"), ("EXPORTACION", "Exportación", "🚢", "EXPORTACION", "EXPO", "STOCK"),
    ("DF_LIQUIDOS", "Disp. Final Líquidos", "💧", None, None, "LAB"), ("DF_SOLIDOS", "Disp. Final Sólidos", "🗑️", None, None, None),
    ("SOLIDOS", "Sólidos", "🧱", None, None, None), ("NFU", "NFU", "♻️", None, None, None),
    ("COMPOST", "Compost & Fertilizante", "🌱", None, None, None), ("TALLER", "Taller & Mantenimiento", "🔧", None, None, "REPUESTOS"),
    ("LABORATORIO", "Laboratorio", "🧪", None, None, "LAB"), ("PORTERIA", "Portería", "🚧", None, None, "LAB"),
    ("INTENDENCIA", "Intendencia", "🧹", None, None, None), ("LOGISTICA", "Logística", "🚚", None, None, None),
]


def sectores_nav(conn_factory) -> pd.DataFrame:
    """Sectores activos. Es una dimensión: se lee una vez por sesión (session_state),
    no con cache_data, para no depender del clear() global de la app."""
    key = "_nav_sectores_df"
    df = st.session_state.get(key)
    if isinstance(df, pd.DataFrame):
        return df
    df = _cargar(conn_factory)
    st.session_state[key] = df
    return df


def sector_por_codigo(conn_factory, codigo):
    df = sectores_nav(conn_factory)
    hit = df[df["codigo"] == codigo]
    return hit.iloc[0].to_dict() if not hit.empty else None


def _cargar(conn_factory) -> pd.DataFrame:
    try:
        with conn_factory() as conn:
            df = pd.read_sql_query(_SQL, conn)
        if not df.empty:
            return df
    except Exception:
        pass
    rows = [dict(codigo=c, nombre_ui=n, icono=i, orden=(k + 1) * 10, activo=True,
                 tiene_datos=bool(s), sector_gestion=g, sector_batch=b,
                 seccion_clasica=s, descripcion=None)
            for k, (c, n, i, g, b, s) in enumerate(_FALLBACK)]
    return pd.DataFrame(rows)
