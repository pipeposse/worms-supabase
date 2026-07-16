"""📈 Performance de reacciones finalizadas — Centro de Planificación.

Lee produccion.v_perf_reaccion / v_perf_reaccion_etapa (migración v_perf_reacciones_finalizadas):
  - Tiempos: reales (fact_batch_estado_log) vs programados (cronograma) vs targets (dic_etapa_duracion).
  - Capacidad: formulado vs máximo del reactor (misma fórmula que Terminadas) → TN que se dejaron de producir.
  - Rendimiento: real (cierre asignado / tickets / kg_obtenido) vs formulado.

Confiabilidad del dato: si una etapa duró < 5 min en el log, el operario avanzó las etapas
"a los clicks" (a posteriori) y el tiempo real NO es el de planta → esas reacciones se marcan
y por defecto se excluyen del análisis de tiempos (no del de capacidad, que sí es confiable).

render(USR, cat, conectar)
"""
import pandas as pd
import streamlit as st

_NUMS = ["espera_arranque_h", "reaccion_h", "reposo_h", "decantacion_h", "ciclo_proceso_h",
         "ciclo_total_h", "prog_reaccion_h", "prog_reposo_h", "prog_decantacion_h",
         "prog_total_h", "prog_proceso_h", "desvio_proceso_h", "max_kg", "formula_kg",
         "mp_kg", "tickets_kg", "real_kg", "utilizacion_pct", "capacidad_perdida_kg",
         "rendimiento_pct", "etapas_flash"]

_ETQ = {"REACCION": "Reacción", "REPOSANDO": "Reposo", "DECANTACION": "Decantación"}


def _num(df, cols):
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def _sem_util(v):
    if pd.isna(v):
        return "—"
    return ("🟢" if v >= 90 else ("🟡" if v >= 70 else "🔴")) + f" {v:.0f}%"


def _sem_rango(s):
    return {"EN_RANGO": "🟢 en rango", "EXCEDIDA": "🔴 excedida",
            "MUY_CORTA": "🟠 muy corta", "SIN_DATO": "⚪ sin dato"}.get(s, s)


def render(USR, cat, conectar):
    st.subheader("📈 Performance de reacciones finalizadas")
    st.caption("Qué tan bien salieron las reacciones **ya terminadas**: cumplimiento de tiempos, "
               "cuánto se cargó vs la capacidad máxima de cada reactor y rendimiento real vs formulado.")

    df = cat("SELECT * FROM produccion.v_perf_reaccion ORDER BY fecha DESC, id_batch DESC")
    if df is None or df.empty:
        st.info("Todavía no hay reacciones finalizadas para analizar.")
        return
    df = _num(df, _NUMS)
    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
    df["tiempos_confiables"] = df["tiempos_confiables"].fillna(False).astype(bool)

    # ---------- filtros ----------
    c1, c2, c3 = st.columns([1.2, 1, 1])
    _rango = c1.selectbox("Período", ["Últimos 30 días", "Últimos 60 días", "Últimos 90 días", "Todo"],
                          index=3, key="perf_rango")
    _tipos = ["Todos"] + sorted(df["tipo"].dropna().unique().tolist())
    _tipo = c2.selectbox("Proceso", _tipos, key="perf_tipo")
    _reactores = ["Todos"] + sorted(df["reactor"].dropna().unique().tolist())
    _reactor = c3.selectbox("Reactor", _reactores, key="perf_reactor")

    if _rango != "Todo":
        _dias = int(_rango.split()[1])
        df = df[df["fecha"] >= (pd.Timestamp.now() - pd.Timedelta(days=_dias))]
    if _tipo != "Todos":
        df = df[df["tipo"] == _tipo]
    if _reactor != "Todos":
        df = df[df["reactor"] == _reactor]
    if df.empty:
        st.info("No hay reacciones finalizadas con esos filtros.")
        return

    dfc = df[df["tiempos_confiables"]]          # tiempos confiables
    n_flash = int((~df["tiempos_confiables"]).sum())

    # ---------- KPIs ----------
    _max_t = df["max_kg"].sum(skipna=True) / 1000.0
    _for_t = df["formula_kg"].sum(skipna=True) / 1000.0
    _util = (100.0 * _for_t / _max_t) if _max_t else None
    _perd_t = df["capacidad_perdida_kg"].sum(skipna=True) / 1000.0
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Reacciones", len(df))
    k2.metric("MP procesada (TN)", f"{df['mp_kg'].sum(skipna=True)/1000.0:,.2f}")
    k3.metric("Utilización de reactores", (f"{_util:.0f}%" if _util is not None else "—"),
              help="Σ formulado / Σ máximo a reactor lleno. 100% = siempre se cargó al máximo.")
    k4.metric("Capacidad no usada (TN)", f"{_perd_t:,.2f}",
              help="TN de producto que se dejaron de formular por no cargar los reactores al máximo. "
                   "Es producción 'perdida' del período.")
    _cm = dfc["ciclo_proceso_h"].median() if not dfc.empty else None
    k5.metric("Ciclo mediano (h)", (f"{_cm:.1f}" if _cm is not None else "—"),
              help="Mediana de inicio de reacción → finalizada (solo reacciones con tiempos confiables).")
    if n_flash:
        st.warning(f"⚠️ **{n_flash} de {len(df)}** reacciones tienen etapas avanzadas 'a los clicks' "
                   "(etapas de < 5 min en el log): sus **tiempos** no reflejan la planta y se excluyen "
                   "del análisis de tiempos. La **capacidad** sí se analiza para todas.")

    t_cap, t_tie, t_rin, t_rit, t_edit = st.tabs(["🏭 Capacidad de carga", "⏱️ Tiempos y desvíos",
                                                  "🎯 Rendimiento", "📆 Ritmo de planta",
                                                  "✏️ Inicio/Fin (editar)"])

    # ---------- capacidad ----------
    with t_cap:
        st.caption("**Cuánto se cargó vs la capacidad máxima del reactor** (misma fórmula que Terminadas: "
                   "objetivo a reactor lleno). Cargar menos que el máximo = menos TN por ciclo con el mismo "
                   "fuel/tiempo de reactor.")
        _agg = (df.groupby("reactor", dropna=False)
                  .agg(reacciones=("id_batch", "count"), max_tn=("max_kg", "sum"),
                       formulado_tn=("formula_kg", "sum"), perdido_tn=("capacidad_perdida_kg", "sum"))
                  .reset_index())
        for c in ("max_tn", "formulado_tn", "perdido_tn"):
            _agg[c] = _agg[c] / 1000.0
        _agg["utilización"] = (100.0 * _agg["formulado_tn"] / _agg["max_tn"]).where(_agg["max_tn"] > 0)
        cc = st.columns(max(len(_agg), 1))
        for i, (_, r) in enumerate(_agg.iterrows()):
            cc[i].metric(f"{r['reactor'] or '—'} · {int(r['reacciones'])} reacciones",
                         (f"{r['utilización']:.0f}%" if pd.notna(r["utilización"]) else "—"),
                         f"-{r['perdido_tn']:,.2f} TN no usadas", delta_color="off")
        _t = df[["ident", "etiqueta", "tipo", "reactor", "fecha", "max_kg", "formula_kg",
                 "utilizacion_pct", "capacidad_perdida_kg"]].copy()
        _t["Utilización"] = _t["utilizacion_pct"].map(_sem_util)
        _t = _t.rename(columns={"ident": "ID", "etiqueta": "Reacción", "tipo": "Tipo",
                                "reactor": "Reactor", "fecha": "Fecha", "max_kg": "Máx reactor (kg)",
                                "formula_kg": "Formulado (kg)", "capacidad_perdida_kg": "No usado (kg)"})
        st.dataframe(_t.drop(columns=["utilizacion_pct"]), hide_index=True, use_container_width=True,
                     column_config={"Fecha": st.column_config.DateColumn(format="DD/MM/YYYY"),
                                    "Máx reactor (kg)": st.column_config.NumberColumn(format="%.0f"),
                                    "Formulado (kg)": st.column_config.NumberColumn(format="%.0f"),
                                    "No usado (kg)": st.column_config.NumberColumn(format="%.0f")})
        st.caption("🟢 ≥90% · 🟡 70–90% · 🔴 <70% del máximo. Ojo: a veces cargar menos es una decisión "
                   "(falta de MP, pedido chico); el número muestra el costo de esa decisión, no una culpa.")

    # ---------- tiempos ----------
    with t_tie:
        _solo_conf = st.toggle("Solo reacciones con tiempos confiables", value=True, key="perf_conf",
                               help="Excluye reacciones con etapas avanzadas a los clicks (< 5 min en el log).")
        _dft = dfc if _solo_conf else df
        if _dft.empty:
            st.info("No hay reacciones con tiempos confiables en el período. "
                    "Cuando las etapas se avancen en el momento (y no a posteriori), este análisis se llena solo.")
        else:
            _ids = tuple(int(x) for x in _dft["id_batch"].tolist())
            _et = cat("SELECT * FROM produccion.v_perf_reaccion_etapa WHERE id_batch IN %s", (_ids,))
            _et = _num(_et, ["real_h", "prog_h", "target_h", "min_h", "max_h", "desvio_prog_h"]) \
                if _et is not None else pd.DataFrame()
            a1, a2, a3 = st.columns(3)
            _esp = _dft["espera_arranque_h"].median()
            a1.metric("Espera para arrancar (h, mediana)", (f"{_esp:.1f}" if pd.notna(_esp) else "—"),
                      help="Planificada → arrancó la reacción. Espera alta = cuello antes del reactor.")
            _dsv = _dft["desvio_proceso_h"].median()
            a2.metric("Desvío vs cronograma (h, mediana)", (f"{_dsv:+.1f}" if pd.notna(_dsv) else "—"),
                      help="Duración real del proceso − programada en el cronograma. + = más lento.")
            if not _et.empty:
                _val = _et[_et["estado_rango"].isin(["EN_RANGO", "EXCEDIDA", "MUY_CORTA"])]
                _pct = (100.0 * (_val["estado_rango"] == "EN_RANGO").sum() / len(_val)) if len(_val) else None
                a3.metric("Etapas dentro de rango", (f"{_pct:.0f}%" if _pct is not None else "—"),
                          help="Etapas cuya duración real cayó dentro del rango min–max definido en "
                               "dic_etapa_duracion (editable).")
            st.markdown("**Por etapa** — real vs programado vs target")
            if not _et.empty:
                _res = (_et.groupby("etapa")
                           .agg(n=("id_batch", "count"), real_h=("real_h", "median"),
                                prog_h=("prog_h", "median"), target_h=("target_h", "first"),
                                excedidas=("estado_rango", lambda s: int((s == "EXCEDIDA").sum())))
                           .reindex(["REACCION", "REPOSANDO", "DECANTACION"]).dropna(how="all").reset_index())
                _res["etapa"] = _res["etapa"].map(_ETQ).fillna(_res["etapa"])
                _res = _res.rename(columns={"etapa": "Etapa", "n": "N", "real_h": "Real mediana (h)",
                                            "prog_h": "Prog. mediana (h)", "target_h": "Target (h)",
                                            "excedidas": "Excedidas"})
                st.dataframe(_res, hide_index=True, use_container_width=True,
                             column_config={c: st.column_config.NumberColumn(format="%.1f")
                                            for c in ("Real mediana (h)", "Prog. mediana (h)", "Target (h)")})
                _det = _et.copy()
                _det["Etapa"] = _det["etapa"].map(_ETQ).fillna(_det["etapa"])
                _det["Estado"] = _det["estado_rango"].map(_sem_rango)
                _det = _det.rename(columns={"ident": "ID", "reactor": "Reactor", "fecha": "Fecha",
                                            "real_h": "Real (h)", "prog_h": "Prog. (h)",
                                            "desvio_prog_h": "Δ vs prog (h)"})
                with st.expander("Detalle por reacción y etapa", expanded=False):
                    st.dataframe(_det[["ID", "Reactor", "Fecha", "Etapa", "Real (h)", "Prog. (h)",
                                       "Δ vs prog (h)", "Estado"]], hide_index=True, use_container_width=True,
                                 column_config={"Fecha": st.column_config.DateColumn(format="DD/MM/YYYY"),
                                                **{c: st.column_config.NumberColumn(format="%.1f")
                                                   for c in ("Real (h)", "Prog. (h)", "Δ vs prog (h)")}})
            _lentas = _dft.nlargest(5, "desvio_proceso_h")[["ident", "etiqueta", "reactor",
                                                            "ciclo_proceso_h", "prog_proceso_h",
                                                            "desvio_proceso_h"]]
            _lentas = _lentas[_lentas["desvio_proceso_h"] > 0]
            if not _lentas.empty:
                st.markdown("**Mayores desvíos** (proceso completo, real − programado)")
                st.dataframe(_lentas.rename(columns={"ident": "ID", "etiqueta": "Reacción",
                                                     "reactor": "Reactor", "ciclo_proceso_h": "Real (h)",
                                                     "prog_proceso_h": "Prog. (h)",
                                                     "desvio_proceso_h": "Desvío (h)"}),
                             hide_index=True, use_container_width=True,
                             column_config={c: st.column_config.NumberColumn(format="%.1f")
                                            for c in ("Real (h)", "Prog. (h)", "Desvío (h)")})
                st.caption("Una **decantación** de días suele ser espera de validación de lab o de tanque "
                           "destino, no proceso: el desvío marca dónde está el cuello, no quién trabajó lento.")

    # ---------- rendimiento ----------
    with t_rin:
        st.caption("**Real obtenido vs formulado.** Real = kg asignado en el cierre → tickets de pesada → "
                   "kg_obtenido, en ese orden. El detalle fino por tanque está en **Terminadas**.")
        _dr = df[df["formula_kg"].notna()].copy()
        _con_real = _dr[_dr["real_kg"].notna() & (_dr["real_kg"] > 0)]
        r1, r2, r3 = st.columns(3)
        r1.metric("Con dato real", f"{len(_con_real)} / {len(_dr)}",
                  help="Reacciones finalizadas con algún kg real registrado (cierre, tickets o kg_obtenido).")
        if not _con_real.empty:
            _rp = 100.0 * _con_real["real_kg"].sum() / _con_real["formula_kg"].sum()
            r2.metric("Rendimiento global", f"{_rp:.0f}%",
                      help="Σ real / Σ formulado, solo sobre reacciones con dato real.")
            r3.metric("Real obtenido (TN)", f"{_con_real['real_kg'].sum()/1000.0:,.2f}")
        _t = _dr[["ident", "etiqueta", "tipo", "reactor", "fecha", "formula_kg", "real_kg",
                  "rendimiento_pct"]].copy()
        _t["Rendimiento"] = _t["rendimiento_pct"].map(
            lambda v: "—" if pd.isna(v) else ("🟢" if 85 <= v <= 115 else "🔴") + f" {v:.0f}%")
        st.dataframe(_t.drop(columns=["rendimiento_pct"]).rename(
                        columns={"ident": "ID", "etiqueta": "Reacción", "tipo": "Tipo", "reactor": "Reactor",
                                 "fecha": "Fecha", "formula_kg": "Formulado (kg)", "real_kg": "Real (kg)"}),
                     hide_index=True, use_container_width=True,
                     column_config={"Fecha": st.column_config.DateColumn(format="DD/MM/YYYY"),
                                    "Formulado (kg)": st.column_config.NumberColumn(format="%.0f"),
                                    "Real (kg)": st.column_config.NumberColumn(format="%.0f")})
        st.caption("Un rendimiento de 0% o >150% casi siempre es un problema de **registro** (no se midió el "
                   "tanque, o el salto del tanque incluye otra cosa), no de proceso. Cerrarlas bien en "
                   "Terminadas mejora este número.")

    # ---------- ritmo ----------
    with t_rit:
        st.caption("**Cuántas reacciones salen y cuánto tiempo queda el reactor parado entre una y otra.** "
                   "El hueco entre reacciones es la otra mitad de la capacidad perdida: reactor vacío = 0 TN.")
        _dfr = df.dropna(subset=["inicio_local", "fin_local"]).copy()
        _dfr["inicio_local"] = pd.to_datetime(_dfr["inicio_local"], errors="coerce")
        _dfr["fin_local"] = pd.to_datetime(_dfr["fin_local"], errors="coerce")
        rows = []
        for _r, g in _dfr.sort_values("inicio_local").groupby("reactor", dropna=False):
            _sem = max(((g["inicio_local"].max() - g["inicio_local"].min()).days / 7.0), 1 / 7.0)
            _gaps = (g["inicio_local"].shift(-1) - g["fin_local"]).dt.total_seconds() / 3600.0
            _gaps = _gaps[_gaps >= 0]
            rows.append({"Reactor": _r or "—", "Reacciones": len(g),
                         "Por semana": round(len(g) / _sem, 1),
                         "Hueco mediano entre reacciones (h)":
                             (round(float(_gaps.median()), 1) if len(_gaps) else None),
                         "TN formuladas": round(g["formula_kg"].sum(skipna=True) / 1000.0, 2)})
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        _sm = (_dfr.assign(semana=_dfr["inicio_local"].dt.to_period("W").dt.start_time)
                   .groupby("semana")["formula_kg"].sum() / 1000.0)
        if len(_sm) > 1:
            st.markdown("**TN formuladas por semana**")
            st.bar_chart(_sm)

    # ---------- editor masivo inicio/fin ----------
    with t_edit:
        _editor_inicio_fin(USR, cat, conectar)

    with st.expander("🔭 Qué más podríamos medir mejorando el registro", expanded=False):
        st.markdown(
            "- **Tiempos reales de verdad**: hoy la mayoría de las etapas se avanzan a posteriori "
            "(clicks seguidos). Si el operario avanza la etapa **cuando pasa** (o se registra hora manual "
            "al avanzar), el análisis de tiempos deja de descartar reacciones.\n"
            "- **Velocidad de reacción química**: con 2+ evaluaciones internas por reacción se puede medir "
            "la caída de acidez por hora y comparar MP/proveedores (la tabla ya existe: fact_evaluacion_interna).\n"
            "- **Consumo real de insumos**: hoy solo hay *estimados* por fórmula. Registrando kg reales de "
            "glicerina/KOH/fuel por batch → costo real por TN y desvío de fórmula.\n"
            "- **Motivo de carga parcial**: un campo 'por qué no se cargó al máximo' (sin MP / pedido chico / "
            "limitación técnica) separa capacidad perdida evitable de la inevitable.\n"
            "- **Cierre completo en Terminadas**: asignar el real de cada reacción (ya hay validador) para que "
            "el rendimiento global sea representativo.\n"
            "- **Paradas y esperas**: registrar por qué un reactor quedó vacío (limpieza, falta de MP, lab) "
            "convertiría el 'hueco entre reacciones' en un pareto accionable.")


_TZ = "America/Argentina/Buenos_Aires"


def _editor_inicio_fin(USR, cat, conectar):
    """Edición masiva del inicio y fin REAL de todas las reacciones finalizadas, en una sola tabla."""
    st.caption("Corregí **inicio y fin reales de todas las reacciones finalizadas** en una sola tabla "
               "(para cuando las etapas se avanzaron a los clicks y el log no refleja la planta). "
               "Guarda en el log de estados (REACCION/FINALIZADO), en inicio_ts/fin_ts y en los eventos "
               "de etapa vinculados; Performance y Terminadas se recalculan solos.")
    df = cat("SELECT id_batch, ident, etiqueta, reactor, tipo, inicio_local AS inicio, "
             "fin_local AS fin, prog_proceso_h "
             "FROM produccion.v_perf_reaccion ORDER BY fecha DESC NULLS LAST, id_batch DESC")
    if df is None or df.empty:
        st.info("No hay reacciones finalizadas para editar.")
        return
    df["inicio"] = pd.to_datetime(df["inicio"], errors="coerce")
    df["fin"] = pd.to_datetime(df["fin"], errors="coerce")
    df["prog_proceso_h"] = pd.to_numeric(df["prog_proceso_h"], errors="coerce")
    base = df.reset_index(drop=True)

    view = pd.DataFrame({
        "ID": base["ident"],
        "Reacción": base["etiqueta"],
        "Reactor": base["reactor"],
        "Inicio real": base["inicio"],
        "Fin real": base["fin"],
        "Programado (h)": base["prog_proceso_h"],
        "Real (h)": ((base["fin"] - base["inicio"]).dt.total_seconds() / 3600.0).round(1),
    })
    view["Δ (h)"] = (view["Real (h)"] - view["Programado (h)"]).round(1)
    ed = st.data_editor(
        view, hide_index=True, use_container_width=True, key="perf_edit_if",
        disabled=["ID", "Reacción", "Reactor", "Programado (h)", "Real (h)", "Δ (h)"],
        column_config={
            "Inicio real": st.column_config.DatetimeColumn("Inicio real", format="DD/MM/YYYY HH:mm", step=60),
            "Fin real": st.column_config.DatetimeColumn("Fin real", format="DD/MM/YYYY HH:mm", step=60),
            "Programado (h)": st.column_config.NumberColumn(format="%.1f",
                                                            help="Horas programadas de inicio a fin "
                                                                 "(reacción+reposo+decantación del cronograma)."),
            "Real (h)": st.column_config.NumberColumn(format="%.1f", help="Fin real − inicio real (guardados)."),
            "Δ (h)": st.column_config.NumberColumn(format="%.1f", help="Real − programado. + = tardó más."),
        })

    # cambios pendientes (vs lo guardado)
    cambios, invalidas = [], []
    for i in range(len(base)):
        idb = int(base.iloc[i]["id_batch"])
        old_i, old_f = base.iloc[i]["inicio"], base.iloc[i]["fin"]
        new_i = pd.to_datetime(ed.iloc[i]["Inicio real"]) if pd.notna(ed.iloc[i]["Inicio real"]) else pd.NaT
        new_f = pd.to_datetime(ed.iloc[i]["Fin real"]) if pd.notna(ed.iloc[i]["Fin real"]) else pd.NaT
        chg_i = pd.notna(new_i) and (pd.isna(old_i) or new_i != old_i)
        chg_f = pd.notna(new_f) and (pd.isna(old_f) or new_f != old_f)
        if not (chg_i or chg_f):
            continue
        eff_i = new_i if pd.notna(new_i) else old_i
        eff_f = new_f if pd.notna(new_f) else old_f
        if pd.notna(eff_i) and pd.notna(eff_f) and eff_f <= eff_i:
            invalidas.append(str(base.iloc[i]["ident"]))
            continue
        cambios.append({"idb": idb, "ident": str(base.iloc[i]["ident"]),
                        "old_i": old_i, "old_f": old_f,
                        "new_i": (new_i if chg_i else None), "new_f": (new_f if chg_f else None),
                        "eff_i": eff_i, "eff_f": eff_f,
                        "prog": base.iloc[i]["prog_proceso_h"]})
    if invalidas:
        st.error("Fin ≤ inicio en: " + ", ".join(invalidas) + " — esas filas no se van a guardar.")
    if cambios:
        _prev = pd.DataFrame([{
            "ID": c["ident"],
            "Nuevo inicio": (c["eff_i"].strftime("%d/%m %H:%M") if pd.notna(c["eff_i"]) else "—"),
            "Nuevo fin": (c["eff_f"].strftime("%d/%m %H:%M") if pd.notna(c["eff_f"]) else "—"),
            "Real (h)": (round((c["eff_f"] - c["eff_i"]).total_seconds() / 3600.0, 1)
                         if pd.notna(c["eff_i"]) and pd.notna(c["eff_f"]) else None),
            "Prog. (h)": (round(float(c["prog"]), 1) if pd.notna(c["prog"]) else None),
        } for c in cambios])
        _prev["Δ (h)"] = (_prev["Real (h)"] - _prev["Prog. (h)"]).round(1)
        st.markdown(f"**{len(cambios)} reacción(es) con cambios:**")
        st.dataframe(_prev, hide_index=True, use_container_width=True)
    else:
        st.caption("Sin cambios pendientes: editá Inicio real / Fin real en la tabla y apretá Guardar.")

    if st.button("💾 Guardar inicios y fines", type="primary", key="perf_edit_save",
                 disabled=(not cambios)):
        try:
            with conectar(int(USR["id_usuario"])) as (conn, audit):
                with conn.cursor() as cur:
                    for c in cambios:
                        idb = c["idb"]
                        if c["new_i"] is not None:
                            _v = str(c["new_i"])
                            cur.execute("UPDATE produccion.fact_batch_estado_log "
                                        "SET ts=(%s::timestamp AT TIME ZONE %s) "
                                        "WHERE id_batch=%s AND estado_nuevo='REACCION'", (_v, _TZ, idb))
                            cur.execute("UPDATE produccion.fact_batch_proceso "
                                        "SET inicio_ts=(%s::timestamp AT TIME ZONE %s) "
                                        "WHERE id_batch=%s", (_v, _TZ, idb))
                            if pd.notna(c["old_i"]):
                                cur.execute("UPDATE produccion.fact_etapa_evento "
                                            "SET inicio_ts=(%s::timestamp AT TIME ZONE %s) "
                                            "WHERE id_batch=%s AND etapa='REACCION' "
                                            "AND inicio_ts=(%s::timestamp AT TIME ZONE %s)",
                                            (_v, _TZ, idb, str(c["old_i"]), _TZ))
                        if c["new_f"] is not None:
                            _v = str(c["new_f"])
                            cur.execute("UPDATE produccion.fact_batch_estado_log "
                                        "SET ts=(%s::timestamp AT TIME ZONE %s) "
                                        "WHERE id_batch=%s AND estado_nuevo='FINALIZADO'", (_v, _TZ, idb))
                            cur.execute("UPDATE produccion.fact_batch_proceso "
                                        "SET fin_ts=(%s::timestamp AT TIME ZONE %s) "
                                        "WHERE id_batch=%s", (_v, _TZ, idb))
                            if pd.notna(c["old_f"]):
                                # cierra la última etapa y corre el arranque de EN_TANQUE si apuntaban al fin viejo
                                cur.execute("UPDATE produccion.fact_etapa_evento "
                                            "SET fin_ts=(%s::timestamp AT TIME ZONE %s) "
                                            "WHERE id_batch=%s AND fin_ts=(%s::timestamp AT TIME ZONE %s)",
                                            (_v, _TZ, idb, str(c["old_f"]), _TZ))
                                cur.execute("UPDATE produccion.fact_etapa_evento "
                                            "SET inicio_ts=(%s::timestamp AT TIME ZONE %s) "
                                            "WHERE id_batch=%s AND etapa='EN_TANQUE' "
                                            "AND inicio_ts=(%s::timestamp AT TIME ZONE %s)",
                                            (_v, _TZ, idb, str(c["old_f"]), _TZ))
                        audit.log("U", "fact_batch_estado_log", idb,
                                  {"inicio": (str(c["new_i"]) if c["new_i"] is not None else None),
                                   "fin": (str(c["new_f"]) if c["new_f"] is not None else None),
                                   "via": "performance_editor_masivo"})
            st.success(f"Guardado: {len(cambios)} reacción(es) actualizadas.")
            cat.clear()
            st.rerun()
        except Exception as e:
            st.exception(e)
