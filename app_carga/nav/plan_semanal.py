# -*- coding: utf-8 -*-
"""Planificación semanal por OP (Fase 4a) — vista PLAN de un sector.

Tabla PLANIFICACIÓN del Excel de dirección: # OP · DÍA · FECHA · SEMANA · PROCESO ·
FORMULACIÓN · HORA INICIO · HORA FIN · RESPONSABLE, con estado (No iniciado /
Iniciado / Finalizado), la "orden del día" arriba y un botón Cargar por fila que
abre Seguimiento Producción parado en esa OP.

La OP es fact_batch_proceso (la crea el Centro de Planificación); esta pantalla
sólo lee produccion.v_plan_semanal y edita los campos del plan (hora inicio/fin,
responsable, fórmula) de las OP todavía no iniciadas. Regla de dirección: la
semana se carga el día anterior; cambiar una OP del día queda permitido pero avisado.
"""

import io
from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st

from . import state as _st
from .kpis import _FRAGMENT, _TTL, _rerun_fragment

_DIAS = {1: "lun", 2: "mar", 3: "mié", 4: "jue", 5: "vie", 6: "sáb", 7: "dom"}
_ESTADO_UI = {"NO_INICIADO": "⚪ No iniciado", "INICIADO": "🟢 Iniciado", "FINALIZADO": "✅ Finalizado"}
_PROCESO_UI = {"PRODUCCION_ARE": "ARE", "DESGOMADO_ACUOSO": "DESGOMADO", "TRATAMIENTO_TERMICO": "TÉRMICO",
               "TRATAMIENTO_TERMOQUIMICO": "TERMOQUÍMICO", "RECUPERACION": "RECUPERACIÓN"}

# qué sección clásica ejecuta la OP de cada sector (Cargar)
_SEGUIMIENTO = {
    "REACTORES":   ("INICIAR", {"iniciar_view": "👷 Iniciar producción"}),
    "BACHAS":      ("INICIAR", {"iniciar_view": "👷 Iniciar producción"}),
    "PILETAS":     ("INICIAR", {"iniciar_view": "♻️ Recuperación AG"}),
    "EXPORTACION": ("INICIAR", {"iniciar_view": "🚢 Exportación"}),
}


# ------------------------------------------------------------------ datos
@st.cache_data(ttl=_TTL, show_spinner=False)
def _leer_plan(_cf, sector, anio, semana):
    sql = ("SELECT id_batch, op, proceso, equipo, plan_inicio, plan_fin, fecha_plan, semana_iso, dia_iso, "
           "id_formula, formula, responsable, responsable_plan, kg_inicial, estado, estado_plan, real_inicio, real_fin "
           "FROM produccion.v_plan_semanal WHERE sector_nav = %s AND anio_iso = %s AND semana_iso = %s "
           "ORDER BY plan_inicio, id_batch")
    try:
        with _cf() as conn:
            df = pd.read_sql_query(sql, conn, params=(sector, int(anio), int(semana)))
        for c in ("plan_inicio", "plan_fin", "real_inicio", "real_fin"):
            df[c] = pd.to_datetime(df[c], errors="coerce")
            try:
                df[c] = df[c].dt.tz_convert("America/Argentina/Buenos_Aires").dt.tz_localize(None)
            except Exception:
                pass
        return df
    except Exception:
        return None


@st.cache_data(ttl=600, show_spinner=False)
def _catalogos(_cf, sector_batch):
    try:
        with _cf() as conn:
            resp = pd.read_sql_query("SELECT nombre_full FROM produccion.dim_usuario WHERE activo "
                                     "AND rol IN ('OPERADOR','SUPERVISOR') ORDER BY nombre_full", conn)
            form = pd.read_sql_query("SELECT id_formula, nombre, tipo_proceso FROM produccion.dic_formula "
                                     "WHERE activo AND sector = %s ORDER BY tipo_proceso, es_default DESC, nombre",
                                     conn, params=(sector_batch,))
        return resp["nombre_full"].tolist(), form
    except Exception:
        return [], pd.DataFrame(columns=["id_formula", "nombre", "tipo_proceso"])


def _guardar(conectar, USR, cambios):
    """cambios: lista de dicts(id_batch, plan_inicio_ts, plan_fin_ts, responsable_plan, id_formula)."""
    with conectar(int(USR["id_usuario"])) as (conn, audit):
        with conn.cursor() as cur:
            for c in cambios:
                cur.execute("UPDATE produccion.fact_batch_proceso SET plan_inicio_ts=%s, plan_fin_ts=%s, "
                            "responsable_plan=%s, id_formula=%s WHERE id_batch=%s AND estado='PLANIFICADO'",
                            (c["plan_inicio_ts"], c["plan_fin_ts"], c["responsable_plan"], c["id_formula"], c["id_batch"]))
                audit.log("U", "fact_batch_proceso", int(c["id_batch"]),
                          {k: (str(v) if v is not None else None) for k, v in c.items() if k != "id_batch"})


# ------------------------------------------------------------------ helpers
def _semana(d: date):
    y, w, _ = d.isocalendar()
    return y, w


def _lunes(anio, semana):
    return date.fromisocalendar(anio, semana, 1)


def _hm(ts):
    return ts.strftime("%H:%M") if pd.notna(ts) else ""


def _tabla_director(df):
    """Las columnas tal cual la tabla de dirección (más el estado)."""
    return pd.DataFrame({
        "# OP": df["op"], "DIA": df["dia_iso"].map(_DIAS), "FECHA": df["fecha_plan"].map(lambda d: pd.to_datetime(d).strftime("%d/%m/%Y")),
        "SEMANA": df["semana_iso"], "PROCESO": df["proceso"].map(lambda p: _PROCESO_UI.get(p, p)),
        "FORMULACION": df["formula"].fillna("—"), "HORA INICIO": df["plan_inicio"].map(_hm), "HORA FIN": df["plan_fin"].map(_hm),
        "RESPONSABLE": df["responsable"].fillna("—"), "EQUIPO": df["equipo"].fillna("—"),
        "ESTADO": df["estado_plan"].map(_ESTADO_UI), "REAL INICIO": df["real_inicio"].map(lambda t: t.strftime("%d/%m %H:%M") if pd.notna(t) else ""),
        "REAL FIN": df["real_fin"].map(lambda t: t.strftime("%d/%m %H:%M") if pd.notna(t) else ""),
    })


def _cargar(sec, id_batch):
    """Abre Seguimiento Producción parado en esta OP. Se llama desde adentro del fragment,
    por eso termina en st.rerun() de toda la app (un callback sólo redibujaría el fragment)."""
    seccion, presets = _SEGUIMIENTO.get(sec["codigo"], ("INICIAR", {"iniciar_view": "👷 Iniciar producción"}))
    st.session_state["pp_sel_id_batch"] = int(id_batch)   # carga_por_id.py preselecciona esta OP
    for k, v in presets.items():
        st.session_state[k] = v
    _st.set_nav("PRODUCCION", sec["codigo"], "SEGUIMIENTO", rerun=False)
    st.session_state.section = seccion
    st.rerun()


# ------------------------------------------------------------------ pantalla
@_FRAGMENT
def _grilla(ctx, sec, anio, semana):
    cf, USR, puede = ctx["conn_factory"], ctx["USR"], ctx["puede_seccion"]
    df = _leer_plan(cf, sec["codigo"], anio, semana)
    if df is None:
        st.caption("Sin conexión a la base en este momento.")
        return
    hoy = date.today()
    lunes = _lunes(anio, semana)

    # ---- Orden del día ----
    dia_sel = st.session_state.get("nav_plan_dia") or hoy
    if not (lunes <= dia_sel <= lunes + timedelta(days=6)):
        dia_sel = lunes if hoy < lunes else min(hoy, lunes + timedelta(days=6))
    st.markdown(f'<div class="section-title">Orden del día · {_DIAS[dia_sel.isoweekday()]} {dia_sel.strftime("%d/%m")}'
                f'{" (hoy)" if dia_sel == hoy else ""}</div>', unsafe_allow_html=True)
    od = df[df["fecha_plan"].map(lambda d: pd.to_datetime(d).date()) == dia_sel]
    if od.empty:
        st.caption("Nada planificado para este día.")
    seguimiento_ok = puede(_SEGUIMIENTO.get(sec["codigo"], ("INICIAR", {}))[0])
    for _, r in od.iterrows():
        c1, c2, c3, c4, c5 = st.columns([1.1, 2.2, 1.4, 1.6, 1.2])
        c1.markdown(f"**{r['op']}**")
        c2.markdown(f"{_PROCESO_UI.get(r['proceso'], r['proceso'])} · {r['formula'] or '—'} · {r['equipo'] or '—'}")
        c3.markdown(f"{_hm(r['plan_inicio'])} → {_hm(r['plan_fin'])}")
        c4.markdown(f"{r['responsable'] or '—'} · {_ESTADO_UI.get(r['estado_plan'], r['estado_plan'])}")
        if r["estado_plan"] != "FINALIZADO" and seguimiento_ok:
            if c5.button("⬆ Cargar" if r["estado_plan"] == "NO_INICIADO" else "▶ Continuar",
                         key=f"nav_plan_cargar_{int(r['id_batch'])}", type="primary", use_container_width=True,
                         help="Abre Seguimiento Producción parado en esta OP: el sistema despliega el instructivo."):
                _cargar(sec, r["id_batch"])

    # ---- Semana completa ----
    st.markdown(f'<div class="section-title">Semana {semana} · {lunes.strftime("%d/%m")} al '
                f'{(lunes + timedelta(days=6)).strftime("%d/%m")}</div>', unsafe_allow_html=True)
    if df.empty:
        st.info("No hay producciones planificadas esta semana.")
    else:
        tabla = _tabla_director(df)
        st.dataframe(tabla, hide_index=True, use_container_width=True)
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as xw:
            tabla.to_excel(xw, index=False, sheet_name=f"Semana {semana}")
        st.download_button("⬇️ Descargar Excel", buf.getvalue(), file_name=f"plan_{sec['codigo'].lower()}_S{semana}_{anio}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="nav_plan_xls")
        n = df["estado_plan"].value_counts()
        st.caption(f"{int(n.get('NO_INICIADO', 0))} no iniciadas · {int(n.get('INICIADO', 0))} iniciadas · "
                   f"{int(n.get('FINALIZADO', 0))} finalizadas")

    # ---- Edición del plan (sólo OP no iniciadas, supervisor/admin) ----
    if USR.get("rol") in ("SUPERVISOR", "ADMIN") and not df.empty:
        ed_src = df[df["estado_plan"] == "NO_INICIADO"]
        with st.expander(f"✏️ Ajustar el plan ({len(ed_src)} OP no iniciadas)", expanded=False):
            if ed_src.empty:
                st.caption("Todas las OP de la semana ya arrancaron: se editan desde Seguimiento.")
            else:
                resp, form = _catalogos(cf, sec.get("sector_batch") or sec["codigo"])
                fnames = form["nombre"].tolist()
                base = pd.DataFrame({
                    "id_batch": ed_src["id_batch"].values, "OP": ed_src["op"].values,
                    "Fecha": ed_src["fecha_plan"].map(lambda d: pd.to_datetime(d).date()).values,
                    "Inicio": ed_src["plan_inicio"].map(lambda t: t.time() if pd.notna(t) else None).values,
                    "Fin": ed_src["plan_fin"].map(lambda t: t.time() if pd.notna(t) else None).values,
                    "Responsable": ed_src["responsable_plan"].values,
                    "Fórmula": ed_src["formula"].values,
                })
                ed = st.data_editor(
                    base, hide_index=True, use_container_width=True, key=f"nav_plan_ed_{semana}",
                    disabled=["id_batch", "OP"],
                    column_config={
                        "id_batch": None,
                        "Fecha": st.column_config.DateColumn("Fecha"),
                        "Inicio": st.column_config.TimeColumn("Hora inicio", format="HH:mm"),
                        "Fin": st.column_config.TimeColumn("Hora fin", format="HH:mm"),
                        "Responsable": st.column_config.SelectboxColumn("Responsable", options=resp),
                        "Fórmula": st.column_config.SelectboxColumn("Formulación", options=fnames),
                    })
                if st.button("💾 Guardar cambios del plan", type="primary", key=f"nav_plan_save_{semana}"):
                    cambios, avisos = [], []
                    for i in range(len(ed)):
                        o, n_ = base.iloc[i], ed.iloc[i]
                        if all(str(o[c]) == str(n_[c]) for c in ("Fecha", "Inicio", "Fin", "Responsable", "Fórmula")):
                            continue
                        f_dt = pd.to_datetime(n_["Fecha"]).date() if pd.notna(n_["Fecha"]) else o["Fecha"]
                        ini = datetime.combine(f_dt, n_["Inicio"]) if n_["Inicio"] else None
                        fin = datetime.combine(f_dt, n_["Fin"]) if n_["Fin"] else None
                        if ini and fin and fin < ini:
                            fin = fin + timedelta(days=1)
                        idf = None
                        if n_["Fórmula"] and n_["Fórmula"] in fnames:
                            idf = int(form[form["nombre"] == n_["Fórmula"]].iloc[0]["id_formula"])
                        if f_dt <= hoy:
                            avisos.append(str(o["OP"]))
                        cambios.append(dict(id_batch=int(o["id_batch"]), plan_inicio_ts=ini, plan_fin_ts=fin,
                                            responsable_plan=(n_["Responsable"] or None), id_formula=idf))
                    if not cambios:
                        st.info("No hay cambios.")
                    else:
                        try:
                            _guardar(ctx["conectar"], USR, cambios)
                            _leer_plan.clear()
                            if avisos:
                                st.warning("Se modificó el plan del día o de días pasados (" + ", ".join(avisos) +
                                           "). Dirección pide cargar la semana el día anterior; el cambio quedó auditado.")
                            st.success(f"{len(cambios)} OP actualizadas.")
                            _rerun_fragment()
                        except Exception as e:
                            st.error(f"No se pudo guardar: {e}")


def render_plan(ctx, sec):
    """Pantalla PLAN del sector: navegación de semana + grilla (fragment)."""
    hoy = date.today()
    anio, semana = st.session_state.get("nav_plan_semana") or _semana(hoy)
    c1, c2, c3, c4, c5 = st.columns([0.6, 2.2, 0.6, 1, 1.6])
    if c1.button("◀", key="nav_plan_prev", use_container_width=True):
        l = _lunes(anio, semana) - timedelta(days=7)
        st.session_state["nav_plan_semana"] = _semana(l); st.session_state.pop("nav_plan_dia", None); st.rerun()
    c2.markdown(f"<div class='section-title' style='margin:6px 0'>🗓️ Planificación · {sec['nombre_ui']} · semana {semana} / {anio}</div>",
                unsafe_allow_html=True)
    if c3.button("▶", key="nav_plan_next", use_container_width=True):
        l = _lunes(anio, semana) + timedelta(days=7)
        st.session_state["nav_plan_semana"] = _semana(l); st.session_state.pop("nav_plan_dia", None); st.rerun()
    if c4.button("Hoy", key="nav_plan_hoy", use_container_width=True):
        st.session_state["nav_plan_semana"] = _semana(hoy); st.session_state["nav_plan_dia"] = hoy; st.rerun()
    if ctx["puede_seccion"]("PLANIFICACION"):
        def _nueva():
            st.session_state["pl_grupo_sc"] = "➕ Nueva producción"; st.session_state["pl_grupo"] = "➕ Nueva producción"
            _st.set_nav("PRODUCCION", sec["codigo"], "PLAN", rerun=False)
            st.session_state.section = "PLANIFICACION"
        c5.button("➕ Nueva producción", key="nav_plan_nueva", use_container_width=True, on_click=_nueva,
                  help="Centro de Planificación: crea la OP (materia prima, tanques, equipo, fórmula).")
    lunes = _lunes(anio, semana)
    dias = [lunes + timedelta(days=i) for i in range(7)]
    d_sel = st.session_state.get("nav_plan_dia") or (hoy if lunes <= hoy <= dias[-1] else lunes)
    wk = f"nav_plan_dia_{anio}_{semana}"
    if wk not in st.session_state:          # preselección vía session_state, no vía index= (cambiar index cambia la identidad del widget)
        st.session_state[wk] = d_sel if d_sel in dias else dias[0]
    d_new = st.radio("Día", dias, horizontal=True, key=wk,
                     format_func=lambda d: f"{_DIAS[d.isoweekday()]} {d.day:02d}" + (" · hoy" if d == hoy else ""),
                     label_visibility="collapsed")
    st.session_state["nav_plan_dia"] = d_new
    _grilla(ctx, sec, anio, semana)
    st.caption("Fuente: producciones creadas en el Centro de Planificación (fact_batch_proceso). "
               "Cargar abre Seguimiento Producción con la OP seleccionada; el instructivo de la fórmula se despliega ahí.")
