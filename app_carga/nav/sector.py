# -*- coding: utf-8 -*-
"""Home de un sector (Fase 2 · piloto Reactores, mismo código para Bachas, Piletas y Exportación).

    SECTOR REACTORES
    ├─ 5 indicadores del sector (acopio disponible · MP a procesar · procesos activos ·
    │  personal · % cumplimiento de la planificación semanal)      ← produccion.v_kpi_sector
    └─ tarjetas: Planificación · Seguimiento Producción · Desvíos · Formulación ·
       Stock · Acopio · Laboratorio · Reportes

Cada tarjeta es un WRAPPER: abre la sección clásica que hoy hace ese trabajo y le
deja preseteados los filtros de la sección (clave de widget en session_state) para
que se abra parada en el sector. No hay lógica nueva de negocio acá: cuando una
sección aprenda a filtrar por sector, el wrapper sólo cambia el preset.
"""

import pandas as pd
import streamlit as st

from . import state as _st
from .kpis import _FRAGMENT, _TTL, _kpi, _n, _i, _presencia_abierta, _marcar_presencia, _leer_kpis, _rerun_fragment
from .sectores import sector_por_codigo

# ------------------------------------------------------------------ tarjetas por sector
# (vista, icono, título, descripción, sección clásica, presets de widgets)
_COMUNES = [
    ("PLAN", "🗓️", "Planificación",
     "Plan semanal por OP: día, fórmula, horario, responsable y el botón Cargar de cada orden.",
     None, {}),          # None = vista propia de nav (plan_semanal.py); el alta sigue en el Centro de Planificación
    ("SEGUIMIENTO", "👷", "Seguimiento Producción",
     "Orden del día: arrancar la producción y avanzarla etapa por etapa.",
     "INICIAR", {"iniciar_view": "👷 Iniciar producción"}),
    ("DESVIOS", "⚠️", "Desvíos",
     "Por OP y variable: lo formulado vs. lo que cargó el operario (MP, insumos, acidez, temperatura, tiempos).",
     None, {}),          # vista propia de nav (desvios.py) sobre v_desvio_op
    ("FORMULACION", "⚗️", "Formulación",
     "Fórmulas del sector: materia prima, insumos, tiempos y la default que usa Planificación.",
     "FORMULAS", {"__fx_sector__": True}),
    ("STOCK", "📦", "Stock",
     "Cuenta corriente por producto (MP · insumos · producto terminado) con saldo; el stock físico sigue en la sección clásica.",
     None, {}),          # vista propia de nav (stock_cc.py) sobre v_cuenta_corriente_producto
    ("ACOPIO", "🛢️", "Acopio",
     "Tanques del sector: contenido, capacidad y última medición.",
     "TANQUES", {}),
    ("LAB", "🧪", "Laboratorio",
     "Evaluaciones de laboratorio; el supervisor busca por producto o ticket.",
     "LAB", {}),
    ("REPORTES", "📊", "Reportes",
     "Gestión semanal: objetivo vs. real en TN, producto por producto.",
     "PLANIFICACION", {"pl_grupo_sc": "📈 Gestión semanal", "pl_grupo": "📈 Gestión semanal"}),
]

# Ajustes por sector: qué vista clásica cubre "Seguimiento" en cada uno.
_SEGUIMIENTO_POR_SECTOR = {
    "PILETAS":     ("INICIAR", {"iniciar_view": "♻️ Recuperación AG"}),
    "EXPORTACION": ("INICIAR", {"iniciar_view": "🚢 Exportación"}),
}


def tiene_home(sec):
    """Un sector tiene home propio si es unidad de gestión (KPIs y tarjetas) o si lleva
    su stock en el ledger simple (home mínimo con carga de movimientos, Fase 5)."""
    return bool(sec) and (bool(sec.get("sector_gestion")) or bool(sec.get("stock_simple")))


def tarjetas(sec):
    out = []
    for vista, ic, tit, desc, seccion, presets in _COMUNES:
        presets = dict(presets)
        if vista == "SEGUIMIENTO" and sec["codigo"] in _SEGUIMIENTO_POR_SECTOR:
            seccion, presets = _SEGUIMIENTO_POR_SECTOR[sec["codigo"]]
        if presets.pop("__fx_sector__", False):
            # dic_formula.sector usa los códigos de batch (REACTORES, BACHAS); el
            # selectbox de Fórmulas sólo acepta valores que existan en sus opciones.
            if sec.get("sector_batch") in ("REACTORES", "BACHAS"):
                presets["fx_fsec"] = sec["sector_batch"]
        out.append((vista, ic, tit, desc, seccion, presets))
    return out


# ------------------------------------------------------------------ datos
@st.cache_data(ttl=_TTL, show_spinner=False)
def _leer_kpi_sector(_cf, codigo):
    try:
        with _cf() as conn:
            df = pd.read_sql_query("SELECT * FROM produccion.v_kpi_sector WHERE codigo = %s", conn, params=(codigo,))
        return df.iloc[0].to_dict() if not df.empty else None
    except Exception:
        return None


# ------------------------------------------------------------------ navegación
def _ir_vista(ctx, sec, vista, seccion, presets):
    def _cb():
        _st.set_nav("PRODUCCION", sec["codigo"], vista, rerun=False)
        for k, v in presets.items():
            st.session_state[k] = v
        st.session_state.section = seccion      # None → la vista vive en la portada (nav)
    return _cb


# ------------------------------------------------------------------ pantalla
@_FRAGMENT
def _kpis_sector(ctx, sec):
    cf, USR = ctx["conn_factory"], ctx["USR"]
    k = _leer_kpi_sector(cf, sec["codigo"])
    if not k:
        st.caption("Indicadores del sector: sin conexión a la base en este momento.")
        return
    tn = _i(k.get("tanques_n"))
    if tn:
        libre, cap = float(k.get("libre_kl") or 0), float(k.get("cap_kl") or 0)
        pct = 100.0 * (1 - libre / cap) if cap else 0.0
        c1 = _kpi("Acopio disponible del sector",
                  f"{_n(libre)}<span style='font-size:1rem;font-weight:700;'> kL</span>",
                  f"{_i(k.get('tanques_con_espacio'))} de {tn} tanques con lugar · {pct:.0f}% ocupado",
                  "bad" if pct >= 90 else ("warn" if pct >= 75 else ""))
        mp = float(k.get("mp_tn") or 0)
        c2 = _kpi("Materia prima a procesar",
                  f"{_n(mp)}<span style='font-size:1rem;font-weight:700;'> TN</span>",
                  (k.get("mp_productos") or "sin materia prima en acopio")
                  + (f" · producto terminado {_n(k.get('pf_tn'))} TN" if float(k.get("pf_tn") or 0) > 0 else "")
                  + (f" · insumos {_n(k.get('insumo_tn'))} TN" if float(k.get("insumo_tn") or 0) > 0 else ""),
                  "")
    else:
        c1 = _kpi("Acopio disponible del sector", "—", "este sector no tiene tanques asociados todavía", "")
        c2 = _kpi("Materia prima a procesar", "—", "sin dato", "")
    pa, pp = _i(k.get("procesos_activos")), _i(k.get("procesos_planificados"))
    c3 = _kpi("Procesos activos", str(pa),
              (f"{pp} planificados sin arrancar" if pp else "ninguno planificado sin arrancar")
              + f" · {_i(k.get('eventos_hoy'))} eventos hoy",
              "ok" if pa else "")
    pers = _i(k.get("personal_presente"))
    c4 = _kpi("Personal en planta", str(pers),
              "marcaron presencia en este sector" if pers else "nadie marcó presencia en este sector", "ok" if pers else "")
    if k.get("tn_objetivo") and float(k["tn_objetivo"]) > 0:
        pct = float(k.get("pct_cumplimiento") or 0)
        c5 = _kpi("Cumplimiento de la planificación",
                  f"{pct:.0f}<span style='font-size:1rem;font-weight:700;'> %</span>",
                  f"semana {_i(k.get('semana_iso'))}: {_n(k.get('tn_real'))} de {_n(k.get('tn_objetivo'))} TN objetivo"
                  + (" · plan cerrado" if k.get("plan_cerrado") else " · plan abierto"),
                  "ok" if pct >= 90 else ("warn" if pct >= 50 else "bad"))
    else:
        c5 = _kpi("Cumplimiento de la planificación", "—",
                  f"sin objetivo cargado para la semana {_i(k.get('semana_iso'))} (Gestión semanal → Objetivos)", "")
    st.markdown(f'<div class="kpi-grid">{c1}{c2}{c3}{c4}{c5}</div>', unsafe_allow_html=True)

    b1, b2, _ = st.columns([1.6, 0.8, 3])
    conectar = ctx.get("conectar")
    if conectar is not None:
        abierta = _presencia_abierta(cf, USR["id_usuario"])
        if abierta:
            if b1.button("🔴 Me retiro de planta", key="nav_sec_pres_out", use_container_width=True):
                try:
                    _marcar_presencia(conectar, USR, entrar=False)
                    _leer_kpi_sector.clear(); _leer_kpis.clear()
                    _rerun_fragment()
                except Exception as e:
                    st.error(f"No se pudo registrar la salida: {e}")
        else:
            if b1.button(f"🟢 Estoy en {sec['nombre_ui']}", key="nav_sec_pres_in", type="primary",
                         use_container_width=True, help="Marca tu entrada en este sector."):
                try:
                    _marcar_presencia(conectar, USR, entrar=True, sector=sec["codigo"])
                    _leer_kpi_sector.clear(); _leer_kpis.clear()
                    _rerun_fragment()
                except Exception as e:
                    st.error(f"No se pudo registrar la entrada: {e}")
    if b2.button("↻", key="nav_sec_refresh", use_container_width=True, help="Recalcular ahora"):
        _leer_kpi_sector.clear()
        _rerun_fragment()


def render_sector(ctx, codigo):
    """Home del sector `codigo`. Devuelve False si el sector no tiene home (la portada decide qué hacer)."""
    sec = sector_por_codigo(ctx["conn_factory"], codigo)
    if not tiene_home(sec):
        return False
    if not sec.get("sector_gestion"):
        from .sector_simple import render_sector_simple
        return render_sector_simple(ctx, sec)
    from .portada import _hero, _grid, _pie_soporte   # mismo lenguaje visual que el área
    USR, puede = ctx["USR"], ctx["puede_seccion"]
    _hero(f"SECTOR {sec['nombre_ui'].upper()}", USR, icono=sec["icono"],
          sub=(sec.get("descripcion") or "") + " Indicadores del sector y accesos a su trabajo diario.")
    _kpis_sector(ctx, sec)

    items = []
    for vista, ic, tit, desc, seccion, presets in tarjetas(sec):
        habil = True if seccion is None else puede(seccion)
        items.append(dict(icono=ic, titulo=tit, desc=desc, key=f"nav_sv_{sec['codigo']}_{vista}",
                          disabled=not habil, label=("Entrar" if habil else "Sin acceso"),
                          tipo=("primary" if habil else "secondary"), atenuado=not habil,
                          on_click=(_ir_vista(ctx, sec, vista, seccion, presets) if habil else None)))
    st.markdown('<div class="section-title">Trabajo del sector</div>', unsafe_allow_html=True)
    _grid(items, por_fila=4)
    st.caption("Indicadores del sector propuestos por dirección · a validar con Eugenia, Pablo y Fernando. "
               "Cada tarjeta abre la sección de siempre, parada en este sector.")
    _pie_soporte(ctx)
    return True
