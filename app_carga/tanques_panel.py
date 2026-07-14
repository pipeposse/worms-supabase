"""Vistas de Tanques: panorama por sector + resumen con filtros.
Se alimentan de produccion.vw_tanque_panel (stock, producto, lab, condición, confianza).
render: vista_por_sector(cat) y resumen_filtrado(cat). `cat` = ejecutor de queries de app.py.
"""
import pandas as pd
import streamlit as st


def _fmt_l(x):
    try:
        return f"{float(x):,.0f}"
    except Exception:
        return "—"


def _art_naive_col(df, col):
    """Convierte una columna timestamptz a hora Argentina sin tz (para mostrar bien en Streamlit)."""
    if col in df.columns:
        _s = pd.to_datetime(df[col], errors="coerce", utc=True)
        try:
            df[col] = _s.dt.tz_convert("America/Argentina/Buenos_Aires").dt.tz_localize(None)
        except Exception:
            df[col] = _s
    return df


def _panel(cat):
    df = cat("SELECT * FROM produccion.vw_tanque_panel ORDER BY sector, nombre")
    if df.empty:
        return df
    df["_litros"] = pd.to_numeric(df["litros_actual"], errors="coerce")
    df["_cap"] = pd.to_numeric(df["capacidad_litros"], errors="coerce")
    df["_dens"] = pd.to_numeric(df["densidad"], errors="coerce").fillna(0.91)
    df["_tn"] = df["_litros"] * df["_dens"] / 1000.0
    if "litros_estimado" in df.columns:
        df["_estim"] = pd.to_numeric(df["litros_estimado"], errors="coerce")
    if "movs_post_medicion" in df.columns:
        df["_movs"] = pd.to_numeric(df["movs_post_medicion"], errors="coerce").fillna(0).astype(int)
    return df


def vista_por_sector(cat):
    st.markdown("### 📊 Stock por sector")
    st.caption("El **Stock (L)** es la **última medición física cargada** (lo que registra el operario / sensor). "
               "Si hay movimientos posteriores sin conciliar, se muestran aparte como *Estimado* — no pisan la medición.")
    df = _panel(cat)
    if df.empty:
        st.info("No hay tanques cargados.")
        return
    _n_pend = int((df.get("_movs", pd.Series(dtype=int)) > 0).sum()) if "_movs" in df.columns else 0
    if _n_pend:
        st.warning(f"⚠️ {_n_pend} tanque(s) con movimientos posteriores a la última medición (posible doble conteo "
                   "del ledger de movimientos). El **Stock (L)** sigue mostrando lo medido; revisá la columna *Estimado* en el detalle.")

    # KPIs globales
    g1, g2, g3, g4 = st.columns(4)
    g1.metric("Tanques", f"{len(df)}")
    g2.metric("Capacidad total", f"{_fmt_l(df['_cap'].sum())} L")
    g3.metric("Stock total", f"{_fmt_l(df['_litros'].sum())} L", f"{df['_tn'].sum():,.0f} TN")
    _occ = (df["_litros"].sum() / df["_cap"].sum() * 100.0) if df["_cap"].sum() else 0
    g4.metric("Ocupación", f"{_occ:.0f}%")

    # Resumen por sector
    res = (df.groupby("sector", dropna=False)
             .agg(tanques=("id_tanque", "count"),
                  capacidad_l=("_cap", "sum"),
                  stock_l=("_litros", "sum"),
                  stock_tn=("_tn", "sum"))
             .reset_index())
    res["ocupacion_%"] = (res["stock_l"] / res["capacidad_l"] * 100).round(0)
    res = res.sort_values("stock_l", ascending=False)
    st.markdown("**Resumen por sector**")
    st.dataframe(
        res.rename(columns={"sector": "Sector", "tanques": "Tanques",
                            "capacidad_l": "Capacidad (L)", "stock_l": "Stock (L)",
                            "stock_tn": "Stock (TN)", "ocupacion_%": "Ocupación %"}),
        use_container_width=True, hide_index=True,
        column_config={
            "Capacidad (L)": st.column_config.NumberColumn(format="%.0f"),
            "Stock (L)": st.column_config.NumberColumn(format="%.0f"),
            "Stock (TN)": st.column_config.NumberColumn(format="%.0f"),
            "Ocupación %": st.column_config.ProgressColumn(format="%.0f%%", min_value=0, max_value=100),
        })

    st.divider()
    # Detalle por sector (expanders), con lab y última actualización
    _cols = ["nombre", "producto_principal", "_litros", "_estim", "_movs", "_cap", "nivel_pct_actual",
             "condicion", "fuente_medicion", "confianza", "ultima_medicion",
             "acidez", "fosforo", "azufre", "agua_sedimento", "comentarios_lab", "observacion"]
    _ren = {"nombre": "Tanque", "producto_principal": "Producto", "_litros": "Stock (L) medido",
            "_estim": "Estimado c/movs (L)", "_movs": "Movs post-medición",
            "_cap": "Capacidad (L)", "nivel_pct_actual": "Nivel %", "condicion": "Condición",
            "fuente_medicion": "Medición", "confianza": "Confianza", "ultima_medicion": "Últ. actualización",
            "acidez": "Acidez", "fosforo": "Fósforo", "azufre": "Azufre",
            "agua_sedimento": "Agua+Sed", "comentarios_lab": "Coment. lab", "observacion": "Observación"}
    for sec in res["sector"].tolist():
        sub = df[df["sector"] == sec]
        cap = sub["_cap"].sum(); sto = sub["_litros"].sum()
        occ = (sto / cap * 100) if cap else 0
        with st.expander(f"🛢️ {sec} · {len(sub)} tanques · {_fmt_l(sto)} / {_fmt_l(cap)} L ({occ:.0f}%)",
                         expanded=False):
            show = sub[[c for c in _cols if c in sub.columns]].rename(columns=_ren)
            show = _art_naive_col(show, "Últ. actualización")
            st.dataframe(show, use_container_width=True, hide_index=True,
                         column_config={
                             "Stock (L) medido": st.column_config.NumberColumn(format="%.0f"),
                             "Estimado c/movs (L)": st.column_config.NumberColumn(format="%.0f"),
                             "Movs post-medición": st.column_config.NumberColumn(format="%d"),
                             "Capacidad (L)": st.column_config.NumberColumn(format="%.0f"),
                             "Nivel %": st.column_config.ProgressColumn(format="%.0f%%", min_value=0, max_value=100),
                             "Últ. actualización": st.column_config.DatetimeColumn(format="DD/MM/YY HH:mm"),
                         })


def resumen_filtrado(cat):
    st.markdown("### 🔎 Resumen con filtros")
    st.caption("Filtrá por sector, producto, tipo de medición y confiabilidad para ver el stock consolidado.")
    df = _panel(cat)
    if df.empty:
        st.info("No hay tanques cargados.")
        return

    f1, f2, f3, f4 = st.columns(4)
    sec = f1.multiselect("Sector", sorted(df["sector"].dropna().unique().tolist()), key="tqr_sec")
    prod = f2.multiselect("Producto", sorted(df["producto_principal"].dropna().unique().tolist()), key="tqr_prod")
    med = f3.multiselect("Tipo de medición", sorted(df["fuente_medicion"].dropna().unique().tolist()), key="tqr_med")
    conf = f4.multiselect("Confiabilidad", ["ALTA", "MEDIA", "BAJA", "SIN_DATO"], key="tqr_conf")

    d = df.copy()
    if sec:  d = d[d["sector"].isin(sec)]
    if prod: d = d[d["producto_principal"].isin(prod)]
    if med:  d = d[d["fuente_medicion"].isin(med)]
    if conf: d = d[d["confianza"].isin(conf)]

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Tanques", f"{len(d)}")
    k2.metric("Stock (L)", _fmt_l(d["_litros"].sum()))
    k3.metric("Stock (TN)", f"{d['_tn'].sum():,.0f}")
    k4.metric("Capacidad (L)", _fmt_l(d["_cap"].sum()))

    if d.empty:
        st.info("Sin tanques para esos filtros.")
        return

    # Stock por producto
    by_prod = (d.dropna(subset=["producto_principal"])
                 .groupby("producto_principal")
                 .agg(tanques=("id_tanque", "count"), stock_l=("_litros", "sum"), stock_tn=("_tn", "sum"))
                 .reset_index().sort_values("stock_l", ascending=False))
    st.markdown("**Stock por producto**")
    cA, cB = st.columns([3, 2])
    cA.dataframe(by_prod.rename(columns={"producto_principal": "Producto", "tanques": "Tanques",
                                         "stock_l": "Stock (L)", "stock_tn": "Stock (TN)"}),
                 use_container_width=True, hide_index=True,
                 column_config={"Stock (L)": st.column_config.NumberColumn(format="%.0f"),
                                "Stock (TN)": st.column_config.NumberColumn(format="%.0f")})
    if not by_prod.empty:
        cB.bar_chart(by_prod.set_index("producto_principal")["stock_l"], use_container_width=True)

    # Stock por sector x producto (pivot)
    st.markdown("**Stock (L) por sector × producto**")
    piv = (d.dropna(subset=["producto_principal"])
             .pivot_table(index="sector", columns="producto_principal", values="_litros",
                          aggfunc="sum", fill_value=0))
    if not piv.empty:
        st.dataframe(piv.round(0), use_container_width=True)

    # Detalle filtrado
    st.markdown("**Detalle de tanques**")
    cols = ["sector", "nombre", "producto_principal", "_litros", "_cap", "nivel_pct_actual",
            "fuente_medicion", "confianza", "condicion", "ultima_medicion",
            "acidez", "fosforo", "azufre", "agua_sedimento"]
    ren = {"sector": "Sector", "nombre": "Tanque", "producto_principal": "Producto",
           "_litros": "Stock (L)", "_cap": "Capacidad (L)", "nivel_pct_actual": "Nivel %",
           "fuente_medicion": "Medición", "confianza": "Confianza", "condicion": "Condición",
           "ultima_medicion": "Últ. actualización", "acidez": "Acidez", "fosforo": "Fósforo",
           "azufre": "Azufre", "agua_sedimento": "Agua+Sed"}
    show = d[[c for c in cols if c in d.columns]].rename(columns=ren)
    show = _art_naive_col(show, "Últ. actualización")
    st.dataframe(show, use_container_width=True, hide_index=True,
                 column_config={"Stock (L)": st.column_config.NumberColumn(format="%.0f"),
                                "Capacidad (L)": st.column_config.NumberColumn(format="%.0f"),
                                "Nivel %": st.column_config.ProgressColumn(format="%.0f%%", min_value=0, max_value=100),
                                "Últ. actualización": st.column_config.DatetimeColumn(format="DD/MM/YY HH:mm")})
    st.download_button("⬇️ Descargar CSV", show.to_csv(index=False).encode("utf-8"),
                       file_name="tanques_resumen.csv", mime="text/csv", key="tqr_dl")
