# -*- coding: utf-8 -*-
"""🏊 Recuperado en piletas — tablero visual del AG recuperado trabajando piletas.

Pedido de dirección: una sección especial, linda, donde se vea TODO lo recuperado
en piletas con análisis básicos y descargas (Excel y PNG) según las semanas
solicitadas.

Fuente única: fact_recuperacion_ticket (tickets confirmados, no anulados) con
sector de trabajo PILETAS — los tickets históricos sin sector declarado cuentan
como piletas. El objetivo semanal (si está cargado en 📈 Gestión semanal para el
sector Piletas) se superpone para ver cumplimiento.

render(USR, cat, conectar)
"""
import io as _io

import pandas as pd
import streamlit as st

_AZUL = "#0e7490"      # color del sector Piletas en dim_sector_gestion
_PALETA = ["#0e7490", "#f59e0b", "#7c3aed", "#16a34a", "#dc2626", "#334155"]


def _f(v):
    try:
        x = float(v)
        return x if x == x else 0.0
    except Exception:
        return 0.0


def _sem_lbl(anio, sem):
    return "S%02d/%s" % (int(sem), str(int(anio))[2:])


def _datos(cat, d1, d2):
    df = cat(
        "SELECT r.ticket, r.fecha_ticket, r.kg, r.clasificacion, r.producto, "
        "       r.destino_tipo, r.tanque_label, r.lab_calidad, r.conductor, r.patente, "
        "       r.observaciones, j.responsables "
        "FROM produccion.fact_recuperacion_ticket r "
        "LEFT JOIN produccion.fact_recuperacion_jornada j ON j.id_jornada = r.id_jornada "
        "WHERE NOT COALESCE(r.anulado, false) "
        "  AND COALESCE(NULLIF(upper(btrim(r.sector_gestion)), ''), 'PILETAS') = 'PILETAS' "
        "  AND r.fecha_ticket BETWEEN %s AND %s "
        "ORDER BY r.fecha_ticket, r.ticket", (d1, d2))
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    df["kg"] = pd.to_numeric(df["kg"], errors="coerce").fillna(0.0)
    df["tn"] = df["kg"] / 1000.0
    _fx = pd.to_datetime(df["fecha_ticket"], errors="coerce")
    _iso = _fx.dt.isocalendar()
    df["anio"] = _iso["year"].astype(int)
    df["semana"] = _iso["week"].astype(int)
    df["sem_lbl"] = [_sem_lbl(a, s) for a, s in zip(df["anio"], df["semana"])]
    df["producto"] = df["producto"].fillna("").astype(str).str.strip().str.upper()
    df.loc[df["producto"] == "", "producto"] = "(sin producto)"
    df["es_rec"] = df["clasificacion"].astype(str).str.upper().eq("RECUPERACION")
    df["destino"] = df.apply(
        lambda r: (str(r["tanque_label"]) if pd.notna(r["tanque_label"]) and str(r["tanque_label"]).strip()
                   else (str(r["destino_tipo"]) if pd.notna(r["destino_tipo"]) else "—")), axis=1)
    return df


def _objetivos(cat, semanas):
    """{(anio, semana): tn_objetivo} del sector PILETAS para las semanas pedidas."""
    if not semanas:
        return {}
    try:
        o = cat("SELECT anio, semana, sum(tn_objetivo) AS tn "
                "FROM produccion.fact_objetivo_semanal WHERE sector='PILETAS' "
                "GROUP BY anio, semana")
        if o is None or o.empty:
            return {}
        return {(int(r["anio"]), int(r["semana"])): _f(r["tn"]) for _, r in o.iterrows()
                if (int(r["anio"]), int(r["semana"])) in semanas}
    except Exception:
        return {}


def _semanal(rec, objs):
    g = (rec.groupby(["anio", "semana", "sem_lbl"], as_index=False)
            .agg(tn=("tn", "sum"), tickets=("ticket", "count"),
                 desde=("fecha_ticket", "min"), hasta=("fecha_ticket", "max")))
    g = g.sort_values(["anio", "semana"]).reset_index(drop=True)
    g["objetivo"] = [objs.get((int(a), int(s))) for a, s in zip(g["anio"], g["semana"])]
    g["cumpl_%"] = [round(100.0 * t / o, 1) if (o or 0) > 0 else None
                    for t, o in zip(g["tn"], g["objetivo"])]
    g["acum_tn"] = g["tn"].cumsum().round(2)
    return g


# ------------------------------ descargas ------------------------------

def _excel_bytes(sem, rec, por_prod):
    buf = _io.BytesIO()
    _sem = sem.rename(columns={"sem_lbl": "Semana", "tn": "TN recuperadas",
                               "tickets": "Tickets", "desde": "Desde", "hasta": "Hasta",
                               "objetivo": "TN objetivo", "cumpl_%": "Cumplimiento %",
                               "acum_tn": "TN acumuladas"})
    _sem = _sem[["Semana", "TN recuperadas", "Tickets", "TN objetivo", "Cumplimiento %",
                 "TN acumuladas", "Desde", "Hasta"]]
    _pp = por_prod.rename(columns={"producto": "Producto", "tn": "TN", "tickets": "Tickets",
                                   "pct": "% del total"})
    _det = rec[["ticket", "fecha_ticket", "sem_lbl", "producto", "kg", "tn", "destino",
                "lab_calidad", "conductor", "patente", "responsables", "observaciones"]].copy()
    _det = _det.rename(columns={"ticket": "Ticket", "fecha_ticket": "Fecha", "sem_lbl": "Semana",
                                "producto": "Producto", "kg": "Kg", "tn": "TN",
                                "destino": "Destino", "lab_calidad": "Calidad lab",
                                "conductor": "Conductor", "patente": "Patente",
                                "responsables": "Responsables jornada",
                                "observaciones": "Observaciones"})
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        for _nom, _x in (("Resumen semanal", _sem), ("Por producto", _pp), ("Detalle", _det)):
            _x.to_excel(w, sheet_name=_nom, index=False)
            ws = w.sheets[_nom]
            for i, c in enumerate(_x.columns):
                try:
                    _w = max(12, min(30, int(_x[c].astype(str).str.len().max() or 10) + 2))
                except Exception:
                    _w = 14
                ws.column_dimensions[chr(65 + i)].width = _w
    return buf.getvalue()


def _png_resumen(sem, por_prod, titulo):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 4.6),
                                   gridspec_kw={"width_ratios": [2.2, 1]})
    x = range(len(sem))
    ax1.bar(x, sem["tn"], color=_AZUL, width=0.62, label="Recuperado (TN)")
    if sem["objetivo"].notna().any():
        ax1.plot(x, sem["objetivo"], color="#dc2626", marker="_", markersize=26,
                 linestyle="none", label="Objetivo (TN)")
    for i, v in enumerate(sem["tn"]):
        ax1.text(i, v, "%.1f" % v, ha="center", va="bottom", fontsize=8, fontweight="bold")
    ax1.set_xticks(list(x))
    ax1.set_xticklabels(sem["sem_lbl"], fontsize=8)
    ax1.set_ylabel("TN")
    ax1.set_title("Recuperado en piletas por semana", fontsize=11, fontweight="bold")
    ax1.legend(fontsize=8, frameon=False)
    ax1.spines["top"].set_visible(False)
    ax1.spines["right"].set_visible(False)
    _pp = por_prod.head(6)
    ax2.pie(_pp["tn"], labels=["%s\n%.1f t" % (p, t) for p, t in zip(_pp["producto"], _pp["tn"])],
            colors=_PALETA[:len(_pp)], startangle=90, textprops={"fontsize": 8},
            wedgeprops={"width": 0.42})
    ax2.set_title("Por producto", fontsize=11, fontweight="bold")
    fig.suptitle(titulo, fontsize=12, fontweight="bold", y=1.02)
    buf = _io.BytesIO()
    fig.savefig(buf, format="png", dpi=160, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def _png_tabla(rec, titulo, max_filas=60):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    x = rec[["ticket", "fecha_ticket", "sem_lbl", "producto", "tn", "destino",
             "conductor", "patente"]].head(max_filas).copy()
    x["fecha_ticket"] = pd.to_datetime(x["fecha_ticket"]).dt.strftime("%d/%m")
    x["tn"] = x["tn"].map(lambda z: "%.2f" % z)
    x = x.rename(columns={"ticket": "Ticket", "fecha_ticket": "Fecha", "sem_lbl": "Semana",
                          "producto": "Producto", "tn": "TN", "destino": "Destino",
                          "conductor": "Conductor", "patente": "Patente"})
    x = x.fillna("—").astype(str)
    fig, ax = plt.subplots(figsize=(12, 0.32 * (len(x) + 2) + 1))
    ax.axis("off")
    tb = ax.table(cellText=x.values, colLabels=list(x.columns), loc="center", cellLoc="center")
    tb.auto_set_font_size(False)
    tb.set_fontsize(8)
    tb.scale(1, 1.25)
    for j in range(len(x.columns)):
        tb[0, j].set_facecolor(_AZUL)
        tb[0, j].set_text_props(color="white", fontweight="bold")
    ax.set_title(titulo, fontsize=11, fontweight="bold", pad=8)
    buf = _io.BytesIO()
    fig.savefig(buf, format="png", dpi=160, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


# ------------------------------ sección ------------------------------

def render(USR, cat, conectar):
    st.markdown(
        "<div style='background:linear-gradient(90deg,#155e75,#0891b2);border-radius:14px;"
        "padding:16px 20px;margin:0 0 12px'>"
        "<div style='color:#fff;font-size:1.4rem;font-weight:900'>🏊 Recuperado en piletas</div>"
        "<div style='color:#cffafe;font-size:.88rem;margin-top:3px'>Todo el AG recuperado "
        "trabajando piletas: cuánto, de qué calidad, adónde fue y contra qué objetivo — "
        "con Excel y PNG descargables de las semanas que elijas.</div></div>",
        unsafe_allow_html=True)

    hoy = pd.Timestamp.today().date()
    f1, f2, f3 = st.columns([1, 1, 2])
    d1 = f1.date_input("Desde", hoy - pd.Timedelta(days=56), key="rpil_d1", format="DD/MM/YYYY")
    d2 = f2.date_input("Hasta", hoy, key="rpil_d2", format="DD/MM/YYYY")
    df = _datos(cat, d1, d2)
    if df.empty:
        st.info("No hay tickets de recuperación en piletas en ese rango. Los tickets se "
                "confirman en ♻️ Recuperación AG (con *Trabajado en: Piletas*).")
        return
    _sems_all = (df[["anio", "semana", "sem_lbl"]].drop_duplicates()
                 .sort_values(["anio", "semana"]))
    f_sem = f3.multiselect("Semanas solicitadas", _sems_all["sem_lbl"].tolist(),
                           key="rpil_sem",
                           help="Vacío = todas las semanas del rango. Lo que elijas acá es "
                                "exactamente lo que sale en el Excel y los PNG.")
    if f_sem:
        df = df[df["sem_lbl"].isin(f_sem)]
        if df.empty:
            st.info("Sin tickets en esas semanas.")
            return

    rec = df[df["es_rec"]].copy()
    _norec = df[~df["es_rec"]]
    _claves = set(zip(df["anio"].astype(int), df["semana"].astype(int)))
    objs = _objetivos(cat, _claves)
    sem = _semanal(rec, objs) if not rec.empty else pd.DataFrame()

    # ---------- KPIs ----------
    _tn_tot = float(rec["tn"].sum())
    _obj_tot = sum(v for v in objs.values() if v) or None
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("♻️ Recuperado", "%.1f TN" % _tn_tot)
    k2.metric("🎫 Tickets", "%d" % len(rec))
    k3.metric("📅 Semanas", "%d" % (len(sem) if not sem.empty else 0))
    k4.metric("⚖️ Promedio semanal",
              ("%.1f TN" % (_tn_tot / len(sem))) if not sem.empty else "—")
    if _obj_tot:
        _pct = 100.0 * _tn_tot / _obj_tot
        k5.metric("🎯 vs objetivo", "%.0f%%" % _pct,
                  delta="%+.1f TN" % (_tn_tot - _obj_tot))
    else:
        k5.metric("🎯 vs objetivo", "—",
                  help="Sin objetivo cargado para Piletas en estas semanas "
                       "(se carga en 📈 Gestión semanal → Objetivos).")
    if not _norec.empty:
        st.caption("➕ Además hubo %d movimiento(s) clasificados como NO recuperación "
                   "(%.1f TN) que no cuentan en los números de arriba."
                   % (len(_norec), float(_norec["tn"].sum())))
    if rec.empty:
        st.info("En estas semanas no hubo recuperación (solo movimientos no clasificados "
                "como recuperación).")
        return

    # ---------- gráficos ----------
    try:
        import altair as alt
        cg1, cg2 = st.columns([2.1, 1])
        _base = sem.rename(columns={"sem_lbl": "Semana", "tn": "TN"})
        _orden = _base["Semana"].tolist()
        _bars = (alt.Chart(_base).mark_bar(color=_AZUL, cornerRadiusTopLeft=4,
                                           cornerRadiusTopRight=4)
                 .encode(x=alt.X("Semana:O", sort=_orden, title=None),
                         y=alt.Y("TN:Q", title="TN recuperadas"),
                         tooltip=["Semana", alt.Tooltip("TN:Q", format=",.1f"),
                                  alt.Tooltip("tickets:Q", title="Tickets")]))
        _txt = (alt.Chart(_base).mark_text(dy=-8, fontWeight="bold", color="#155e75")
                .encode(x=alt.X("Semana:O", sort=_orden), y="TN:Q",
                        text=alt.Text("TN:Q", format=",.1f")))
        _capas = [_bars, _txt]
        if _base["objetivo"].notna().any():
            _capas.append(alt.Chart(_base.dropna(subset=["objetivo"]))
                          .mark_tick(color="#dc2626", thickness=3, size=34)
                          .encode(x=alt.X("Semana:O", sort=_orden),
                                  y=alt.Y("objetivo:Q"),
                                  tooltip=[alt.Tooltip("objetivo:Q", title="Objetivo TN",
                                                       format=",.1f")]))
        cg1.altair_chart(alt.layer(*_capas).properties(height=320,
                                                       title="TN recuperadas por semana"),
                         use_container_width=True)

        _pp = (rec.groupby("producto", as_index=False)
               .agg(tn=("tn", "sum"), tickets=("ticket", "count"))
               .sort_values("tn", ascending=False))
        _pp["pct"] = (100.0 * _pp["tn"] / _pp["tn"].sum()).round(1)
        _donut = (alt.Chart(_pp).mark_arc(innerRadius=58)
                  .encode(theta=alt.Theta("tn:Q"),
                          color=alt.Color("producto:N", title="",
                                          scale=alt.Scale(range=_PALETA)),
                          tooltip=["producto", alt.Tooltip("tn:Q", format=",.1f"),
                                   alt.Tooltip("pct:Q", title="%", format=".1f"),
                                   "tickets"])
                  .properties(height=320, title="Por producto (calidad)"))
        cg2.altair_chart(_donut, use_container_width=True)

        cg3, cg4 = st.columns(2)
        _acu = (alt.Chart(_base).mark_area(color=_AZUL, opacity=0.25,
                                           line={"color": _AZUL, "strokeWidth": 2.5})
                .encode(x=alt.X("Semana:O", sort=_orden, title=None),
                        y=alt.Y("acum_tn:Q", title="TN acumuladas"),
                        tooltip=["Semana", alt.Tooltip("acum_tn:Q", format=",.1f")])
                .properties(height=260, title="Acumulado del período"))
        cg3.altair_chart(_acu, use_container_width=True)

        _dd = (rec.groupby("destino", as_index=False).agg(tn=("tn", "sum"))
               .sort_values("tn", ascending=True))
        _dst = (alt.Chart(_dd).mark_bar(color="#0891b2")
                .encode(x=alt.X("tn:Q", title="TN"),
                        y=alt.Y("destino:N", sort="-x", title=None),
                        tooltip=["destino", alt.Tooltip("tn:Q", format=",.1f")])
                .properties(height=260, title="Adónde fue (destino real)"))
        cg4.altair_chart(_dst, use_container_width=True)
    except Exception:
        st.bar_chart(sem.set_index("sem_lbl")["tn"])

    # ---------- resumen semanal ----------
    _pp = (rec.groupby("producto", as_index=False)
           .agg(tn=("tn", "sum"), tickets=("ticket", "count"))
           .sort_values("tn", ascending=False))
    _pp["pct"] = (100.0 * _pp["tn"] / _pp["tn"].sum()).round(1)
    _v = sem.rename(columns={"sem_lbl": "Semana", "tn": "TN", "tickets": "Tickets",
                             "objetivo": "Objetivo TN", "cumpl_%": "Cumpl. %",
                             "acum_tn": "Acum. TN"})
    st.dataframe(_v[["Semana", "TN", "Tickets", "Objetivo TN", "Cumpl. %", "Acum. TN"]]
                 .style.format({"TN": "{:,.1f}", "Objetivo TN": "{:,.1f}",
                                "Cumpl. %": "{:,.0f}", "Acum. TN": "{:,.1f}"}, na_rep="—"),
                 hide_index=True, use_container_width=True)

    # ---------- detalle ----------
    with st.expander("🎫 Detalle ticket por ticket (%d)" % len(rec)):
        _d = rec.rename(columns={"ticket": "Ticket", "fecha_ticket": "Fecha",
                                 "sem_lbl": "Semana", "producto": "Producto",
                                 "tn": "TN", "destino": "Destino",
                                 "lab_calidad": "Lab", "conductor": "Conductor",
                                 "patente": "Patente", "responsables": "Responsables"})
        st.dataframe(_d[["Ticket", "Fecha", "Semana", "Producto", "TN", "Destino", "Lab",
                         "Conductor", "Patente", "Responsables"]]
                     .style.format({"TN": "{:,.2f}"}, na_rep="—"),
                     hide_index=True, use_container_width=True)

    # ---------- descargas ----------
    st.markdown("---")
    _rango = "%s a %s" % (sem.iloc[0]["sem_lbl"], sem.iloc[-1]["sem_lbl"]) \
        if len(sem) > 1 else sem.iloc[0]["sem_lbl"]
    _suf = _rango.replace("/", "-").replace(" ", "")
    b1, b2, b3 = st.columns(3)
    b1.download_button("⬇️ Excel (%s)" % _rango,
                       _excel_bytes(sem, rec, _pp),
                       file_name="recuperado_piletas_%s.xlsx" % _suf,
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       use_container_width=True)
    try:
        b2.download_button("🖼️ PNG resumen (%s)" % _rango,
                           _png_resumen(sem, _pp, "Recuperado en piletas · %s" % _rango),
                           file_name="recuperado_piletas_%s.png" % _suf,
                           mime="image/png", use_container_width=True)
        b3.download_button("🖼️ PNG detalle%s" % (" · primeras 60 filas" if len(rec) > 60 else ""),
                           _png_tabla(rec, "Recuperado en piletas — detalle · %s" % _rango),
                           file_name="recuperado_piletas_detalle_%s.png" % _suf,
                           mime="image/png", use_container_width=True)
    except Exception as _e:
        st.caption("No se pudieron generar los PNG: %s" % _e)
    st.caption("El Excel trae 3 hojas: resumen semanal (con objetivo y cumplimiento), "
               "por producto y el detalle ticket por ticket. Todo respeta las semanas "
               "elegidas arriba.")
