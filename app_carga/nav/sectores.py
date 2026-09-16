# -*- coding: utf-8 -*-
"""Sectores de navegación (produccion.dim_sector_nav), agrupados por área (dim_area_nav)."""

import pandas as pd
import streamlit as st

_SQL = """
    SELECT s.codigo, s.nombre_ui, s.icono, s.orden, s.activo, s.tiene_datos,
           s.sector_gestion, s.sector_batch, s.seccion_clasica, s.descripcion,
           s.stock_simple, s.patron_tanques,
           s.area, a.nombre_ui AS area_nombre, a.icono AS area_icono,
           COALESCE(a.orden, 999) AS area_orden
    FROM produccion.dim_sector_nav s
    LEFT JOIN produccion.dim_area_nav a ON a.codigo = s.area
    WHERE s.activo
    ORDER BY COALESCE(a.orden, 999), s.orden, s.codigo
"""

# Áreas de planta (dim_area_nav), en el orden de dirección: la portada agrupa los
# sectores por área y respeta este orden. Respaldo si la tabla no existe.
_AREAS_FALLBACK = [
    ("RECEP_LIQ",   "Recepción de Residuos Líquidos",   "🚛", 10),
    ("RECEP_SOL",   "Recepción de Residuos Sólidos",    "🚛", 20),
    ("TRAT_LIQ",    "Tratamiento de Residuos Líquidos", "⚗️", 30),
    ("TRAT_SOL",    "Tratamiento de Residuos Sólidos",  "🧱", 40),
    ("EXPORTACION", "Exportación",                      "🚢", 50),
    ("SOPORTE",     "Soporte",                          "🛠️", 60),
]
_AREA_DE = {   # sector → área, para el respaldo sin base
    "DF_LIQUIDOS": "RECEP_LIQ", "DF_SOLIDOS": "RECEP_SOL",
    "PILETAS": "TRAT_LIQ", "BACHAS": "TRAT_LIQ", "REACTORES": "TRAT_LIQ",
    "NFU": "TRAT_SOL", "COMPOST": "TRAT_SOL", "CEREAL_POLVILLO": "TRAT_SOL", "TIERRAS_FILTRANTES": "TRAT_SOL",
    "EXPORTACION": "EXPORTACION",
    "LABORATORIO": "SOPORTE", "INTENDENCIA": "SOPORTE", "TALLER": "SOPORTE", "MANTENIMIENTO": "SOPORTE",
    "LOGISTICA": "SOPORTE", "ADMINISTRACION": "SOPORTE", "AUDITORIA_STOCK": "SOPORTE", "PORTERIA": "SOPORTE",
}

# Respaldo si la tabla no existe en el entorno (dev local sin la migración):
# la grilla del director, en su orden.
_SIMPLES = {"NFU", "COMPOST",                                       # sin tanques: ledger propio (Fase 5)
            "CEREAL_POLVILLO", "TIERRAS_FILTRANTES"}
_PROPIOS = {"DF_LIQUIDOS", "DF_SOLIDOS"}                            # pantalla propia (nav/sector_*.py)
_PATRONES = {"REACTORES": "^(Reactores|Consumibles Reactores)", "BACHAS": "^Bachas",   # dim_tanque.sector ~ patrón
             "PILETAS": "^Piletas", "EXPORTACION": "^Plataforma"}
_FALLBACK = [  # (codigo, nombre_ui, icono, sector_gestion, sector_batch, seccion_clasica) — orden área → sector
    ("DF_LIQUIDOS", "Disp. Final Líquidos", "💧", None, None, None),   # home propio: sector_efluentes.py
    ("DF_SOLIDOS", "Disp. Final Sólidos", "🗑️", None, None, None),   # home propio: sector_solidos.py
    ("PILETAS", "Piletas", "🌊", "PILETAS", "RECUPERACION", "RECUPERACION"),
    ("BACHAS", "Bachas", "🛢️", "BACHAS", "BACHAS", "INICIAR"), ("REACTORES", "Reactor", "⚙️", "REACTORES", "REACTORES", "INICIAR"),
    ("NFU", "NFU", "♻️", None, None, None), ("COMPOST", "Compost & Fertilizante", "🌱", None, None, None),
    ("CEREAL_POLVILLO", "Cereal & Polvillo", "🌾", None, None, None), ("TIERRAS_FILTRANTES", "Tierras Filtrantes", "🪨", None, None, None),
    ("EXPORTACION", "Exportación", "🚢", "EXPORTACION", "EXPO", "STOCK"),
    ("LABORATORIO", "Laboratorio", "🧪", None, None, "LAB"), ("INTENDENCIA", "Intendencia", "🧹", None, None, None),
    ("TALLER", "Taller Mecánico", "🔧", None, None, "REPUESTOS"), ("MANTENIMIENTO", "Mantenimiento", "🛠️", None, None, None),
    ("LOGISTICA", "Logística", "🚚", None, None, None), ("ADMINISTRACION", "Administración", "🗂️", None, None, None),
    ("AUDITORIA_STOCK", "Auditoría de Stock", "📋", None, None, None), ("PORTERIA", "Portería", "🚧", None, None, "LAB"),
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
    _ar = {c: (n, ic, o) for c, n, ic, o in _AREAS_FALLBACK}
    rows = []
    for k, (c, n, i, g, b, s) in enumerate(_FALLBACK):
        _a = _AREA_DE.get(c)
        _an, _ai, _ao = _ar.get(_a, (None, None, 999))
        rows.append(dict(codigo=c, nombre_ui=n, icono=i, orden=(k + 1) * 10, activo=True,
                         tiene_datos=bool(s) or c in _SIMPLES or c in _PROPIOS, sector_gestion=g, sector_batch=b,
                         seccion_clasica=s, descripcion=None, stock_simple=(c in _SIMPLES),
                         patron_tanques=_PATRONES.get(c),
                         area=_a, area_nombre=_an, area_icono=_ai, area_orden=_ao))
    df = pd.DataFrame(rows)
    return df.sort_values(["area_orden", "orden"]).reset_index(drop=True)


def areas_nav(conn_factory):
    """[(codigo, nombre_ui, icono)] en el orden de dirección — derivado de los sectores
    cargados, así no hace falta otra consulta ni otro cache."""
    df = sectores_nav(conn_factory)
    if df.empty or "area" not in df.columns:
        return [(c, n, ic) for c, n, ic, _ in _AREAS_FALLBACK]
    vistos, out = set(), []
    for _, r in df.sort_values(["area_orden", "orden"]).iterrows():
        a = r.get("area")
        if a and a not in vistos:
            vistos.add(a)
            out.append((a, r.get("area_nombre") or a, r.get("area_icono") or ""))
    return out
