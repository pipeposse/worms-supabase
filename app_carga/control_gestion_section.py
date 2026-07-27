"""Control de gestión (Dirección) — desvíos, movimientos, estimado vs real, stock.

Pensada para que un director la abra por primera vez y la entienda sin que nadie
se la explique. Cada bloque responde tres preguntas: qué estoy viendo, de dónde
sale el número, y qué hago si está mal.

Orden deliberado:
  0. Lo que está en juego, en USD — el titular para el que no va a bajar más.
  1. Confiabilidad del dato  — ¿los KPIs de abajo son creíbles?
  2. Conversión de planta    — el único rendimiento medido que no depende de carga manual.
  3. Rendimiento por batch   — estimado vs real, y cuántos batches son realmente "real".
  4. Stock                   — cuánto del inventario es medición y cuánto extrapolación.
  5. Calidad de la MP        — el agua que se compra a precio de producto.

Toda la valorización sale de produccion.dim_precio_ref. Los mapeos producto -> precio
viven en tablas editables (dim_precio_map, dic_flujo_porteria), no acá.

render(USR, cat, conectar)

Vistas de soporte (esquema produccion):
  v_dir_confiabilidad, v_dir_conversion_planta, v_dir_rendimiento_batch,
  v_dir_stock_confianza, v_dir_calidad_mp, v_dir_inventario_valorizado,
  v_dir_precio_producto, v_cobertura_libro_semanal, v_salida_sin_respaldo
"""
import pandas as pd
import streamlit as st

VERDE = "#16a34a"
AMBAR = "#b45309"
ROJO = "#dc2626"
GRIS = "#64748b"


def _num(df, cols):
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def _color_semaforo(valor, meta, mas_es_mejor):
    """Verde si cumple, ámbar si está a menos de 25% de distancia, rojo si no."""
    if valor is None or pd.isna(valor) or meta is None or pd.isna(meta):
        return GRIS
    v, m = float(valor), float(meta)
    if mas_es_mejor:
        if v >= m:
            return VERDE
        return AMBAR if v >= m * 0.75 else ROJO
    if v <= m:
        return VERDE
    return AMBAR if v <= m * 1.5 else ROJO


def _fmt_usd(v):
    """USD compacto: 4,78 M / 415 k / 940."""
    if v is None or pd.isna(v):
        return "—"
    v = float(v)
    a = abs(v)
    if a >= 1_000_000:
        return f"USD {v/1_000_000:,.2f} M"
    if a >= 1_000:
        return f"USD {v/1_000:,.0f} k"
    return f"USD {v:,.0f}"


def _tarjeta(col, titulo, valor, unidad, meta, color, sufijo="", valor_txt=None):
    if valor_txt is not None:
        _v, _sz = valor_txt, "1.5rem"
    else:
        _v = "—" if valor is None or pd.isna(valor) else f"{float(valor):,.1f}{unidad}"
        _sz = "1.9rem"
    _m = "" if meta is None or pd.isna(meta) else f"meta {float(meta):,.0f}{unidad}"
    col.markdown(
        f"<div style='border:1px solid #e2e8f0;border-left:6px solid {color};"
        f"border-radius:8px;padding:.7rem .9rem;height:100%'>"
        f"<div style='font-size:.78rem;color:#475569;line-height:1.2;min-height:2.4em'>{titulo}</div>"
        f"<div style='font-size:{_sz};font-weight:800;color:{color};line-height:1.2'>{_v}</div>"
        f"<div style='font-size:.72rem;color:#94a3b8'>{_m}{sufijo}</div>"
        f"</div>", unsafe_allow_html=True)


# ============================================================================
# Precios y consultas compartidas
# ----------------------------------------------------------------------------
# Los bloques y la banda de USD usan las MISMAS funciones de consulta para que
# el cache de `cat` no las ejecute dos veces.
# ============================================================================
def _precios(cat):
    df = cat("SELECT codigo, rol, precio, unidad, moneda, descripcion, "
             "actualizado_en::date AS al FROM produccion.dim_precio_ref ORDER BY rol, codigo")
    if df is None or df.empty:
        return {}, None, df
    p = {}
    for _, r in df.iterrows():
        try:
            p[str(r["codigo"])] = float(r["precio"])
        except (TypeError, ValueError):
            pass
    try:
        _f = pd.to_datetime(df["al"]).max()
        fecha = None if pd.isna(_f) else _f.strftime("%d-%m-%Y")
    except Exception:
        fecha = None
    return p, fecha, df


def _q_salidas(cat):
    return cat(
        "SELECT s.estado_control, COUNT(*) AS camiones, "
        "ROUND((SUM(s.kg)/1000.0)::numeric,1) AS toneladas, "
        "ROUND((SUM(s.kg/1000.0*COALESCE(p.precio,0)))::numeric,0) AS usd "
        "FROM produccion.v_salida_sin_respaldo s "
        "LEFT JOIN produccion.dic_flujo_porteria d ON d.producto_base = s.producto_base "
        "LEFT JOIN produccion.dim_precio_ref p ON p.codigo = d.codigo_precio_pf "
        "  AND upper(p.unidad)='TN' AND upper(p.moneda)='USD' "
        "WHERE s.fecha >= current_date - 28 GROUP BY 1 ORDER BY 4 DESC NULLS LAST")


def _q_conversion(cat):
    return cat("SELECT semana, mp_entrada_t, pf_salida_t, conversion_pct, camiones_mp, camiones_pf, "
               "usd_mp_entrada, usd_pf_salida "
               "FROM produccion.v_dir_conversion_planta "
               "WHERE semana >= (date_trunc('week', now())::date - INTERVAL '26 weeks') "
               "AND semana < date_trunc('week', now())::date "
               "ORDER BY semana")


def _q_rendimiento(cat):
    return cat("SELECT id_batch, identificador_unidad, tipo_proceso, fecha, mp_kg, objetivo_kg, "
               "producido_kg, kg_ticket_final, tiene_ticket_final, calidad_dato, "
               "rend_medido_pct, rend_objetivo_pct "
               "FROM produccion.v_dir_rendimiento_batch "
               "WHERE fecha >= current_date - 120 ORDER BY fecha DESC")


def _q_calidad(cat):
    return cat("SELECT producto_base, SUM(tickets) AS tickets, SUM(tickets_con_lab) AS con_lab, "
               "ROUND(SUM(t_recibidas)::numeric,1) AS t_recibidas, "
               "ROUND(SUM(t_agua_estimadas)::numeric,1) AS t_agua, "
               "ROUND((SUM(t_recibidas*agua_prom_pct)/NULLIF(SUM(t_recibidas),0))::numeric,2) AS agua_pct, "
               "ROUND((SUM(t_recibidas*acidez_prom)/NULLIF(SUM(t_recibidas),0))::numeric,2) AS acidez, "
               "SUM(usd_agua) AS usd_agua, SUM(usd_recibido) AS usd_recibido, MAX(usd_por_t) AS usd_por_t "
               "FROM produccion.v_dir_calidad_mp WHERE mes >= current_date - 120 "
               "GROUP BY 1 ORDER BY 4 DESC NULLS LAST")


def _q_inventario(cat):
    return cat("SELECT sector, codigo_producto, tipo_producto, tanques, t_medidas, t_estimadas, "
               "usd_por_t, usd_medido, usd_estimado "
               "FROM produccion.v_dir_inventario_valorizado ORDER BY usd_medido DESC NULLS LAST")


def _brecha_rendimiento(df):
    """Brecha real vs objetivo por tipo de proceso, extrapolada a toda la MP procesada.

    Solo los batches con pesada real dan una brecha medida; se asume que los que no
    tienen pesada rinden parecido a los que sí. Es un supuesto, y se dice en pantalla.
    """
    filas = []
    for proc, g in df.groupby("tipo_proceso"):
        med = g[g["rend_medido_pct"].notna() & g["rend_objetivo_pct"].notna()]
        if med.empty:
            continue
        real = float(med["rend_medido_pct"].mean())
        obj = float(med["rend_objetivo_pct"].mean())
        mp_t = float(g["mp_kg"].fillna(0).sum()) / 1000.0
        filas.append({"Proceso": proc, "Batches": int(len(g)), "Con pesada real": int(len(med)),
                      "Rend. real %": real, "Rend. objetivo %": obj, "Brecha (pts)": real - obj,
                      "MP procesada (t)": mp_t, "t no obtenidas": (real - obj) / 100.0 * mp_t})
    return pd.DataFrame(filas)


# ============================================================================
# Portada — para el que abre la sección por primera vez
# ============================================================================
def _portada():
    st.header("🎯 Control de gestión")
    st.markdown(
        "Esta sección responde una sola pregunta: **¿dónde se va la tonelada?** "
        "Entra materia prima, se procesa, sale producto, queda stock. En cada escalón hay una "
        "diferencia entre **lo que el sistema dice** y **lo que realmente pasó**. Eso es un desvío."
    )
    with st.expander("📖 Cómo leer esta pantalla (leelo la primera vez)", expanded=True):
        st.markdown(
            "**La planta tiene tres testigos independientes de lo que pasa, y ninguno depende de los otros:**\n\n"
            "1. **La balanza de portería** — pesa cada camión a la entrada y a la salida. Es el instrumento "
            "más confiable que hay: menos del 0,3 % de los tickets están incompletos.\n"
            "2. **Los sensores de los tanques** — 20 tanques con radar miden el nivel cada ~18 minutos. "
            "El resto se mide a mano, una vez por día o menos.\n"
            "3. **Lo que la gente carga en el sistema** — reacciones, despachos, movimientos, tickets.\n\n"
            "Cuando los tres coinciden, el número es un hecho. Cuando no coinciden, hay un desvío — y el desvío "
            "puede ser un error de carga, una merma real, o algo que se fue sin registrar. **El sistema no puede "
            "distinguir entre esos tres si el dato base no es confiable.**\n\n"
            "---\n\n"
            "**Por eso el primer bloque no mide la planta: mide si los demás números son creíbles.** "
            "Si está en rojo, todo lo que sigue se lee con pinzas. Es incómodo pero es honesto: es preferible "
            "un tablero que avisa que no sabe, a uno que inventa un número tranquilizador.\n\n"
            "**Regla de lectura:** un indicador en rojo acá casi nunca significa \"nos están robando\". "
            "Significa \"no lo estamos midiendo\". Primero se arregla la medición; recién después el número "
            "que sobra o falta se vuelve una pregunta con respuesta."
        )


# ============================================================================
# Bloque 0 — Lo que está en juego, en dólares
# ============================================================================
def _bloque_dinero(cat, precios, fecha_precios, df_precios):
    st.subheader("0 · Lo que está en juego, en dólares")
    st.caption("Las mismas brechas que se detallan más abajo, multiplicadas por el precio de referencia. "
               "Un director actúa sobre *USD 400.000* mucho más rápido que sobre *554 toneladas*.")

    _pf = precios.get("ARE-B")

    # --- Salidas sin circuito cerrado (28 d) ---
    _usd_sr = None
    sal = _q_salidas(cat)
    if sal is not None and not sal.empty:
        sal = _num(sal.copy(), ["camiones", "toneladas", "usd"])
        _m = sal["estado_control"].isin(["SIN RESPALDO", "SIN DESPACHO", "SIN SALIDA DE TANQUE"])
        _usd_sr = float(sal.loc[_m, "usd"].sum())

    # --- Brecha de rendimiento (120 d) ---
    _usd_rend, _t_rend = None, None
    ren = _q_rendimiento(cat)
    if ren is not None and not ren.empty:
        ren = _num(ren.copy(), ["mp_kg", "rend_medido_pct", "rend_objetivo_pct"])
        _br = _brecha_rendimiento(ren)
        if not _br.empty and _pf:
            _t_rend = float(_br["t no obtenidas"].sum())
            _usd_rend = _t_rend * float(_pf)

    # --- Agua comprada dentro de la MP (120 d) ---
    _usd_agua, _t_agua = None, None
    cal = _q_calidad(cat)
    if cal is not None and not cal.empty:
        cal = _num(cal.copy(), ["t_recibidas", "t_agua", "usd_agua", "usd_recibido"])
        _usd_agua = float(cal["usd_agua"].sum())
        _t_agua = float(cal["t_agua"].sum())

    # --- Inventario valorizado ---
    _usd_inv, _t_inv = None, None
    inv = _q_inventario(cat)
    if inv is not None and not inv.empty:
        inv = _num(inv.copy(), ["t_medidas", "t_estimadas", "usd_por_t", "usd_medido", "usd_estimado"])
        _usd_inv = float(inv["usd_medido"].sum())
        _t_inv = float(inv["t_medidas"].sum())

    c1, c2, c3, c4 = st.columns(4)
    _tarjeta(c1, "Producto que salió sin cerrar el circuito · 28 días", None, "", None,
             (ROJO if (_usd_sr or 0) > 0 else VERDE), valor_txt=_fmt_usd(_usd_sr),
             sufijo="valorizado a precio de venta")
    _tarjeta(c2, "Producto no obtenido por brecha de rendimiento · 120 días", None, "", None,
             (ROJO if (_usd_rend or 0) < 0 else GRIS), valor_txt=_fmt_usd(_usd_rend),
             sufijo=(f"{_t_rend:,.0f} t" if _t_rend is not None else ""))
    _tarjeta(c3, "Agua comprada dentro de la materia prima · 120 días", None, "", None,
             (ROJO if (_usd_agua or 0) > 100_000 else AMBAR if (_usd_agua or 0) > 0 else GRIS),
             valor_txt=_fmt_usd(_usd_agua),
             sufijo=(f"{_t_agua:,.0f} t de agua" if _t_agua is not None else ""))
    _tarjeta(c4, "Inventario en tanques valorizado · hoy", None, "", None, GRIS,
             valor_txt=_fmt_usd(_usd_inv),
             sufijo=(f"{_t_inv:,.0f} t medidas" if _t_inv is not None else ""))

    st.caption(f"Precios de referencia al **{fecha_precios or 's/d'}**. "
               "Si están viejos, todo lo de arriba se mueve en bloque: cambiar los precios "
               "en `dim_precio_ref` actualiza esta pantalla entera sin tocar nada más.")

    st.warning(
        "**Las cuatro cifras no se suman ni son todas pérdida.**\n\n"
        "• La primera es **producto real que salió de planta** y cuyo circuito administrativo no se cerró. "
        "Casi todo es venta legítima; el problema es que hoy no hay forma de distinguirla de lo que no lo sea.\n\n"
        "• La segunda es **producto que el proceso no entregó** respecto del objetivo, medido solo sobre los "
        "batches que sí tienen pesada real y extrapolado al resto. Es un supuesto explícito, no un hecho.\n\n"
        "• La tercera es **agua que se paga a precio de materia prima** — real, pero parte puede estar ya "
        "descontada en el precio negociado con cada proveedor.\n\n"
        "• La cuarta es **capital de trabajo inmovilizado**, no una pérdida."
    )

    with st.expander("Con qué precios se valoriza todo esto"):
        st.markdown(
            "Todos los números en USD de esta pantalla salen de una sola tabla, "
            "`produccion.dim_precio_ref`. No hay precios escritos en el código.\n\n"
            "Los productos que no tienen precio propio se valorizan al precio de referencia más "
            "conservador de su familia (por ejemplo, borras y sebos van a AG-C). El mapeo vive en "
            "`produccion.dim_precio_map` para stock y en `produccion.dic_flujo_porteria` para portería, "
            "y se corrige sin tocar código.")
        if df_precios is not None and not df_precios.empty:
            _p = df_precios.rename(columns={"codigo": "Código", "rol": "Rol", "precio": "Precio",
                                            "unidad": "Unidad", "moneda": "Moneda",
                                            "descripcion": "Descripción", "al": "Actualizado"})
            st.dataframe(_p, hide_index=True, use_container_width=True)
        _pp = cat("SELECT codigo_producto AS \"Producto\", tipo_producto AS \"Tipo\", "
                  "codigo_precio AS \"Precio de referencia\", usd_por_t AS \"USD/t\" "
                  "FROM produccion.v_dir_precio_producto WHERE usd_por_t IS NOT NULL "
                  "ORDER BY tipo_producto, codigo_producto")
        if _pp is not None and not _pp.empty:
            st.markdown("**Precio aplicado a cada producto de stock**")
            st.dataframe(_pp, hide_index=True, use_container_width=True,
                         column_config={"USD/t": st.column_config.NumberColumn(format="%.1f")})


# ============================================================================
# Bloque 1 — Confiabilidad del dato
# ============================================================================
def _bloque_confiabilidad(cat):
    st.subheader("1 · ¿Son creíbles los números?")
    st.caption("Este bloque no mide la planta. Mide **cuánto de lo que pasa físicamente queda registrado**. "
               "Es el prerrequisito de todo lo demás.")

    df = cat("SELECT orden, kpi, valor, meta, unidad, mas_es_mejor, que_mide, por_que_importa "
             "FROM produccion.v_dir_confiabilidad ORDER BY orden")
    if df is None or df.empty:
        st.info("Sin datos para el semáforo de confiabilidad."); return
    df = _num(df.copy(), ["valor", "meta"])

    cols = st.columns(len(df))
    for i, (_, r) in enumerate(df.iterrows()):
        _c = _color_semaforo(r["valor"], r["meta"], bool(r["mas_es_mejor"]))
        _tarjeta(cols[i], r["kpi"], r["valor"], str(r["unidad"]), r["meta"], _c)

    with st.expander("¿Qué mide cada uno y por qué importa?"):
        for _, r in df.iterrows():
            _c = _color_semaforo(r["valor"], r["meta"], bool(r["mas_es_mejor"]))
            _v = "—" if pd.isna(r["valor"]) else f"{float(r['valor']):,.1f}{r['unidad']}"
            st.markdown(
                f"**{r['kpi']} — <span style='color:{_c}'>{_v}</span>** (meta {float(r['meta']):,.0f}{r['unidad']})  \n"
                f"{r['que_mide']}  \n"
                f"*{r['por_que_importa']}*", unsafe_allow_html=True)
            st.write("")

    # --- Detalle: cobertura por sector ---
    st.markdown("**Dónde se pierde la cobertura del libro de tanques**")
    st.caption("Por sector: cuánto movió el tanque de verdad (lo vieron los sensores) contra cuánto movimiento "
               "quedó cargado en el sistema. Un sector en 0 % se mueve sin que el sistema se entere. "
               "Un sector arriba de 110 % registra más movimiento del que ocurrió — no es robo, es doble carga "
               "o carga al tanque equivocado, y es igual de grave porque ensucia el inventario base.")
    cob = cat("SELECT semana, sector, tanques, mov_fisico_kl, mov_libro_kl, cobertura_pct, "
              "bajas_sin_respaldo_kl, no_explicado_neto_kl "
              "FROM produccion.v_cobertura_libro_semanal "
              "WHERE semana >= (date_trunc('week', now())::date - INTERVAL '4 weeks') "
              "ORDER BY semana DESC, mov_fisico_kl DESC")
    if cob is None or cob.empty:
        st.info("Sin datos de cobertura.")
    else:
        cob = _num(cob.copy(), ["tanques", "mov_fisico_kl", "mov_libro_kl", "cobertura_pct",
                                "bajas_sin_respaldo_kl", "no_explicado_neto_kl"])
        agg = (cob.groupby("sector", as_index=False)
                  .agg(**{"Tanques": ("tanques", "max"),
                          "Movió de verdad (kL)": ("mov_fisico_kl", "sum"),
                          "Registrado (kL)": ("mov_libro_kl", "sum"),
                          "Bajas sin respaldo (kL)": ("bajas_sin_respaldo_kl", "sum")}))
        agg["Cobertura"] = (100.0 * agg["Registrado (kL)"] / agg["Movió de verdad (kL)"].replace(0, pd.NA))
        agg = agg.sort_values("Movió de verdad (kL)", ascending=False)
        agg = agg.rename(columns={"sector": "Sector"})

        def _cc(v):
            if pd.isna(v):
                return ""
            return (f"color:{ROJO};font-weight:700" if (v < 50 or v > 130) else
                    (f"color:{AMBAR};font-weight:700" if (v < 90 or v > 110) else
                     f"color:{VERDE};font-weight:700"))
        _fmt = {"Movió de verdad (kL)": "{:,.0f}", "Registrado (kL)": "{:,.0f}",
                "Bajas sin respaldo (kL)": "{:,.0f}", "Cobertura": "{:,.0f} %"}
        try:
            st.dataframe(agg.style.map(_cc, subset=["Cobertura"]).format(_fmt, na_rep="—"),
                         hide_index=True, use_container_width=True)
        except Exception:
            st.dataframe(agg, hide_index=True, use_container_width=True)
        st.caption("Últimas 4 semanas. 🟢 90–110 % · 🟡 50–90 % o 110–130 % · 🔴 fuera de eso.")

    # --- Detalle: salidas sin respaldo ---
    st.markdown("**Camiones que salieron cargados y no cerraron el circuito**")
    st.caption("Un camión que sale con producto debería dejar tres rastros: el peso en balanza, un despacho "
               "emitido y un descuento del tanque del que se cargó. Acá aparece cuáles de los tres faltan.")
    sal = _q_salidas(cat)
    if sal is None or sal.empty:
        st.info("Sin salidas registradas en los últimos 28 días.")
    else:
        sal = _num(sal.copy(), ["camiones", "toneladas", "usd"])
        _lbl = {"OK": "🟢 OK — despacho emitido y tanque descontado",
                "SIN DESPACHO": "🟡 Salió sin despacho emitido",
                "SIN SALIDA DE TANQUE": "🟡 Hay despacho pero no se descontó del tanque",
                "SIN RESPALDO": "🔴 Sin despacho y sin descuento de tanque"}
        sal["Estado"] = sal["estado_control"].map(lambda x: _lbl.get(x, x))
        st.dataframe(sal[["Estado", "camiones", "toneladas", "usd"]]
                     .rename(columns={"camiones": "Camiones", "toneladas": "Toneladas",
                                      "usd": "Valorizado (USD)"}),
                     hide_index=True, use_container_width=True,
                     column_config={"Toneladas": st.column_config.NumberColumn(format="%.1f"),
                                    "Valorizado (USD)": st.column_config.NumberColumn(format="%.0f")})
        st.caption("El valorizado usa el precio de venta de referencia del producto que salió. "
                   "Los flujos sin precio (compost, residuos, ganado) suman toneladas pero no dólares.")
        _f = sal.loc[sal["estado_control"] == "SIN RESPALDO"]
        _sr = float(_f["toneladas"].sum() or 0)
        _su = float(_f["usd"].sum() or 0)
        if _sr > 0:
            st.warning(
                f"**{_sr:,.0f} t — {_fmt_usd(_su)} — salieron en los últimos 28 días sin despacho ni "
                "descuento de tanque.** Cuidado con leer esto como faltante: casi todo es producto "
                "legítimamente vendido cuyo circuito administrativo nunca se cerró en el sistema. "
                "El problema no es que falte producto, es que **no hay forma de saberlo**. "
                "Mientras este número no baje, ningún control de pérdidas funciona."
            )


# ============================================================================
# Bloque 2 — Conversión de planta (balanza)
# ============================================================================
def _bloque_conversion(cat):
    st.subheader("2 · Conversión de planta — el rendimiento que no se puede maquillar")
    st.caption("Toneladas de producto terminado que salieron de planta, sobre toneladas de materia prima que "
               "entraron. **Se calcula solo con la balanza**: no depende de que nadie cargue nada en el sistema. "
               "Es el indicador más robusto que tiene la planta hoy.")

    df = _q_conversion(cat)
    if df is None or df.empty:
        st.info("Sin datos de portería para calcular la conversión."); return
    df = _num(df.copy(), ["mp_entrada_t", "pf_salida_t", "conversion_pct", "camiones_mp", "camiones_pf",
                          "usd_mp_entrada", "usd_pf_salida"])
    df["mm4"] = (100.0 * df["pf_salida_t"].rolling(4, min_periods=2).sum()
                 / df["mp_entrada_t"].rolling(4, min_periods=2).sum())
    df["Semana"] = pd.to_datetime(df["semana"]).dt.strftime("S%V")

    _ult = df.iloc[-1]
    _mm4 = df["mm4"].dropna()
    c1, c2, c3, c4 = st.columns(4)
    _tarjeta(c1, "Conversión última semana", _ult["conversion_pct"], " %", None, GRIS)
    _tarjeta(c2, "Media móvil 4 semanas", (_mm4.iloc[-1] if len(_mm4) else None), " %", None, GRIS)
    _rng = df["conversion_pct"].dropna()
    _amp = (_rng.max() - _rng.min()) if len(_rng) else None
    _tarjeta(c3, "Oscilación semana a semana",
             _amp, " pts", None, (ROJO if (_amp or 0) > 30 else AMBAR if (_amp or 0) > 15 else VERDE))
    _tarjeta(c4, "MP entrada últimas 4 sem.",
             df["mp_entrada_t"].tail(4).sum(), " t", None, GRIS)

    try:
        import altair as alt
        _ord = df["Semana"].tolist()
        base = alt.Chart(df.dropna(subset=["conversion_pct"]))
        barras = base.mark_bar(color="#cbd5e1").encode(
            x=alt.X("Semana:O", sort=_ord, title="Semana"),
            y=alt.Y("conversion_pct:Q", title="Conversión (%)"),
            tooltip=["Semana",
                     alt.Tooltip("mp_entrada_t:Q", title="MP entrada (t)", format=",.0f"),
                     alt.Tooltip("pf_salida_t:Q", title="PF salida (t)", format=",.0f"),
                     alt.Tooltip("conversion_pct:Q", title="Conversión %", format=",.1f")])
        linea = alt.Chart(df.dropna(subset=["mm4"])).mark_line(color="#2563eb", size=3, point=True).encode(
            x=alt.X("Semana:O", sort=_ord), y=alt.Y("mm4:Q"),
            tooltip=[alt.Tooltip("mm4:Q", title="Media móvil 4 sem. %", format=",.1f")])
        st.altair_chart((barras + linea).properties(height=320), use_container_width=True)
    except Exception:
        st.line_chart(df.set_index("Semana")[["conversion_pct", "mm4"]])

    _u_mp = float(df["usd_mp_entrada"].tail(4).sum())
    _u_pf = float(df["usd_pf_salida"].tail(4).sum())
    d1, d2, d3 = st.columns(3)
    _tarjeta(d1, "MP que entró · últimas 4 semanas", None, "", None, GRIS, valor_txt=_fmt_usd(_u_mp),
             sufijo=f"{df['mp_entrada_t'].tail(4).sum():,.0f} t")
    _tarjeta(d2, "PF que salió · últimas 4 semanas", None, "", None, GRIS, valor_txt=_fmt_usd(_u_pf),
             sufijo=f"{df['pf_salida_t'].tail(4).sum():,.0f} t")
    _tarjeta(d3, "Diferencia — entró y todavía no salió", None, "", None,
             (AMBAR if (_u_mp - _u_pf) > 0 else VERDE), valor_txt=_fmt_usd(_u_mp - _u_pf),
             sufijo="acopio + merma + desfasaje")

    st.info(
        "**Cómo leerlo.** Las barras grises son cada semana; la línea azul es la media móvil de 4 semanas.\n\n"
        "**La diferencia en dólares no es una pérdida.** Es materia prima que entró en la ventana y todavía "
        "no salió como producto: parte está en acopio, parte se procesó y sale la semana que viene, parte "
        "es merma real de proceso. Separar esos tres pedazos es exactamente lo que hoy no se puede hacer, "
        "y lo que se destraba cuando suba la cobertura del libro de tanques.\n\n"
        "Parte de la oscilación semanal es normal y no es pérdida: lo que entra una semana puede salir la "
        "siguiente, porque la planta acopia. Por eso el número que importa es **la línea azul, no las barras**.\n\n"
        "Pero **la amplitud de la oscilación es en sí misma un indicador**. Una planta que convierte de forma "
        "estable no salta 40 puntos entre semanas seguidas. Si salta, o el acopio se está usando como "
        "amortiguador sin control, o hay semanas donde entró materia prima que nunca salió como producto."
    )

    with st.expander("De dónde sale este número"):
        st.markdown(
            "**Entra (materia prima):** camiones que llegaron llenos y salieron vacíos, con producto "
            "clasificado como MP en el diccionario de portería (AFE, AG, BORRA, SEBO, fondos de tanque, ácido).\n\n"
            "**Sale (producto terminado):** camiones que llegaron vacíos y salieron llenos, con producto "
            "clasificado como PF (AG de exportación, ARE, pellets, glicerina).\n\n"
            "Se descartan tickets de menos de 300 kg. **No entran** residuos, efluentes, compost, tierra ni "
            "ganado: son flujos que no pasan por el proceso y ensuciarían el ratio.\n\n"
            "El diccionario vive en `produccion.dic_flujo_porteria` y se puede corregir sin tocar código.")
        _d = cat("SELECT producto_base AS \"Producto\", es_mp_entrada AS \"Cuenta como MP\", "
                 "es_pf_salida AS \"Cuenta como PF\", nota AS \"Nota\" "
                 "FROM produccion.dic_flujo_porteria ORDER BY 1")
        if _d is not None and not _d.empty:
            st.dataframe(_d, hide_index=True, use_container_width=True)

    st.markdown("**Detalle semanal**")
    _t = df[["Semana", "mp_entrada_t", "pf_salida_t", "conversion_pct", "mm4",
             "usd_mp_entrada", "usd_pf_salida", "camiones_mp", "camiones_pf"]].copy()
    _t["Δ USD"] = _t["usd_mp_entrada"] - _t["usd_pf_salida"]
    _t = _t.rename(columns={"mp_entrada_t": "MP entrada (t)", "pf_salida_t": "PF salida (t)",
                            "conversion_pct": "Conversión %", "mm4": "Media móvil 4s %",
                            "usd_mp_entrada": "MP entrada (USD)", "usd_pf_salida": "PF salida (USD)",
                            "camiones_mp": "Camiones MP", "camiones_pf": "Camiones PF"})
    st.dataframe(_t.sort_values("Semana", ascending=False), hide_index=True, use_container_width=True,
                 column_config={"MP entrada (t)": st.column_config.NumberColumn(format="%.0f"),
                                "PF salida (t)": st.column_config.NumberColumn(format="%.0f"),
                                "Conversión %": st.column_config.NumberColumn(format="%.1f"),
                                "Media móvil 4s %": st.column_config.NumberColumn(format="%.1f"),
                                "MP entrada (USD)": st.column_config.NumberColumn(format="%.0f"),
                                "PF salida (USD)": st.column_config.NumberColumn(format="%.0f"),
                                "Δ USD": st.column_config.NumberColumn(format="%.0f")})


# ============================================================================
# Bloque 3 — Rendimiento por batch: estimado vs real
# ============================================================================
def _bloque_rendimiento(cat, precios):
    st.subheader("3 · Rendimiento por batch — ¿el sistema muestra el plan o el resultado?")
    st.caption("Cuando una reacción termina, el sistema anota cuánto producto se obtuvo. La pregunta es de "
               "dónde sale ese número: de una pesada real, o del objetivo que se había planificado.")

    df = _q_rendimiento(cat)
    if df is None or df.empty:
        st.info("Sin batches en los últimos 120 días."); return
    df = _num(df.copy(), ["mp_kg", "objetivo_kg", "producido_kg", "kg_ticket_final",
                          "rend_medido_pct", "rend_objetivo_pct"])

    _n = len(df)
    _med = int((df["calidad_dato"] == "MEDIDO").sum())
    _obj = int((df["calidad_dato"] == "IGUAL AL OBJETIVO").sum())
    _sin = int(df["calidad_dato"].isin(["SIN DATO", "ESTIMADO"]).sum())

    c1, c2, c3, c4 = st.columns(4)
    _pct = 100.0 * _med / _n if _n else None
    _tarjeta(c1, "Batches con pesada real", _pct, " %", 95,
             _color_semaforo(_pct, 95, True), sufijo=f" · {_med} de {_n}")
    _tarjeta(c2, "Batches donde el resultado = el objetivo", (100.0 * _obj / _n if _n else None), " %", None,
             (ROJO if _obj else VERDE), sufijo=f" · {_obj} batches")
    _rm = df["rend_medido_pct"].dropna()
    _ro = df.loc[df["rend_medido_pct"].notna(), "rend_objetivo_pct"].dropna()
    _tarjeta(c3, "Rendimiento real (solo batches pesados)",
             (_rm.mean() if len(_rm) else None), " %", None, GRIS, sufijo=f" · {len(_rm)} batches")
    _brecha = (_rm.mean() - _ro.mean()) if (len(_rm) and len(_ro)) else None
    _tarjeta(c4, "Brecha real vs objetivo", _brecha, " pts", None,
             (ROJO if (_brecha is not None and _brecha < -5) else
              AMBAR if (_brecha is not None and _brecha < 0) else GRIS))

    if _obj:
        st.error(
            f"**{_obj} de {_n} batches reportan exactamente el objetivo como resultado.** "
            "No es que la planta clave el plan al kilo: es que cuando no se carga el ticket final pesado, "
            "el sistema copia el objetivo y lo muestra como si fuera lo producido. "
            "El rendimiento de esos batches da 100 % por construcción, no por desempeño.\n\n"
            "**Consecuencia:** el indicador de pérdida por rendimiento da cero siempre. "
            "Un KPI que dice 100 % es peor que uno vacío, porque el vacío se ve y el 100 % tranquiliza."
        )
        if len(_rm) and len(_ro):
            st.markdown(
                f"Los **{len(_rm)} batches que sí tienen pesada real** rinden **{_rm.mean():,.1f} %** contra un "
                f"objetivo de **{_ro.mean():,.1f} %**. Esa brecha de **{_brecha:+,.1f} puntos** es la que está "
                "invisible en los otros batches."
            )

    # --- Valorización de la brecha ---
    _pf = precios.get("ARE-B")
    _br = _brecha_rendimiento(df)
    if not _br.empty and _pf:
        _br["Impacto (USD)"] = _br["t no obtenidas"] * float(_pf)
        _tot_t = float(_br["t no obtenidas"].sum())
        _tot_u = float(_br["Impacto (USD)"].sum())
        st.markdown("**Cuánto vale esa brecha**")
        e1, e2, e3 = st.columns(3)
        _tarjeta(e1, "Toneladas no obtenidas · 120 días", _tot_t, " t", None,
                 (ROJO if _tot_t < 0 else VERDE))
        _tarjeta(e2, "Valorizado a precio de venta", None, "", None,
                 (ROJO if _tot_u < 0 else VERDE), valor_txt=_fmt_usd(_tot_u),
                 sufijo=f"a USD {float(_pf):,.0f}/t")
        _tarjeta(e3, "Proyección a 12 meses", None, "", None,
                 (ROJO if _tot_u < 0 else VERDE), valor_txt=_fmt_usd(_tot_u * 365.0 / 120.0),
                 sufijo="si el ritmo se mantiene")
        _cfg = {c: st.column_config.NumberColumn(format="%.1f") for c in
                ["Rend. real %", "Rend. objetivo %", "Brecha (pts)", "MP procesada (t)", "t no obtenidas"]}
        _cfg["Impacto (USD)"] = st.column_config.NumberColumn(format="%.0f")
        st.dataframe(_br, hide_index=True, use_container_width=True, column_config=_cfg)
        st.caption(
            "**El supuesto está a la vista.** La brecha se mide solo sobre los batches con pesada real y se "
            "aplica a *toda* la materia prima procesada del mismo proceso. Si los batches sin pesar rinden "
            "distinto, este número cambia. Es el precio de no medir: hoy no se puede saber si la brecha es "
            "de USD 0 o el doble de lo que dice acá. Con el ticket final cargado en cada batch, deja de ser "
            "una extrapolación y pasa a ser una cuenta.")

    st.markdown("**De dónde sale el número de producción, batch por batch**")
    _lbl = {"MEDIDO": "🟢 Pesada real (ticket final)",
            "IGUAL AL OBJETIVO": "🔴 Copiado del objetivo",
            "ESTIMADO": "🟡 Estimado desde tanque",
            "SIN DATO": "⚪ Sin producción cargada"}
    _res = (df.groupby("calidad_dato", as_index=False)
              .agg(Batches=("id_batch", "count"),
                   MP_t=("mp_kg", lambda s: s.sum() / 1000.0)))
    _res["Origen del dato"] = _res["calidad_dato"].map(lambda x: _lbl.get(x, x))
    _res = _res[["Origen del dato", "Batches", "MP_t"]].rename(columns={"MP_t": "MP procesada (t)"})
    st.dataframe(_res.sort_values("Batches", ascending=False), hide_index=True, use_container_width=True,
                 column_config={"MP procesada (t)": st.column_config.NumberColumn(format="%.1f")})

    with st.expander("Ver los batches uno por uno"):
        _d = df.copy()
        _d["Origen del dato"] = _d["calidad_dato"].map(lambda x: _lbl.get(x, x))
        _d["MP (t)"] = _d["mp_kg"] / 1000.0
        _d["Objetivo (t)"] = _d["objetivo_kg"] / 1000.0
        _d["Producido s/sistema (t)"] = _d["producido_kg"] / 1000.0
        _d["Pesada real (t)"] = _d["kg_ticket_final"].where(_d["tiene_ticket_final"]) / 1000.0
        _d = _d[["fecha", "identificador_unidad", "tipo_proceso", "Origen del dato", "MP (t)",
                 "Objetivo (t)", "Producido s/sistema (t)", "Pesada real (t)",
                 "rend_medido_pct", "rend_objetivo_pct"]]
        _d = _d.rename(columns={"fecha": "Fecha", "identificador_unidad": "Unidad",
                                "tipo_proceso": "Proceso", "rend_medido_pct": "Rend. real %",
                                "rend_objetivo_pct": "Rend. objetivo %"})
        st.dataframe(_d, hide_index=True, use_container_width=True,
                     column_config={c: st.column_config.NumberColumn(format="%.1f") for c in
                                    ["MP (t)", "Objetivo (t)", "Producido s/sistema (t)",
                                     "Pesada real (t)", "Rend. real %", "Rend. objetivo %"]})

    st.info(
        "**Cómo se arregla.** Dos cosas, en este orden. "
        "**Primero, disciplina:** cargar el ticket final pesado al cerrar cada batch. "
        "**Segundo, sistema:** que cuando no haya ticket final, la producción quede vacía en vez de caer al "
        "objetivo. Un hueco visible obliga a llenarlo; un 100 % falso no."
    )


# ============================================================================
# Bloque 4 — Stock: medición vs extrapolación
# ============================================================================
def _bloque_stock(cat):
    st.subheader("4 · Stock — cuánto es medición y cuánto es cuenta")
    st.caption("El stock que se reporta mezcla dos cosas distintas: lo que un sensor midió hace un rato, y lo "
               "que el sistema calcula sumando y restando movimientos desde la última medición. "
               "No son lo mismo y conviene verlos separados.")

    df = cat("SELECT sector, tanques, kl_medidos, kl_estimados, kl_pendientes, movs_sin_medir, "
             "horas_peor_medicion, horas_prom_pond "
             "FROM produccion.v_dir_stock_confianza ORDER BY kl_medidos DESC NULLS LAST")
    if df is None or df.empty:
        st.info("Sin datos de stock por sector."); return
    df = _num(df.copy(), ["tanques", "kl_medidos", "kl_estimados", "kl_pendientes",
                          "movs_sin_medir", "horas_peor_medicion", "horas_prom_pond"])

    c1, c2, c3 = st.columns(3)
    _tot = df["kl_medidos"].sum()
    _pend = df["kl_pendientes"].abs().sum()
    _tarjeta(c1, "Stock medido (última medición real)", _tot, " kL", None, GRIS)
    _tarjeta(c2, "Movimiento posterior a la medición", _pend, " kL", None,
             (AMBAR if _tot and _pend / _tot > 0.05 else VERDE),
             sufijo=(f" · {100.0*_pend/_tot:,.1f} % del total" if _tot else ""))
    _peor = df["horas_peor_medicion"].max()
    _tarjeta(c3, "Tanque medido hace más tiempo", _peor, " h", 48,
             _color_semaforo(_peor, 48, False))

    _d = df.rename(columns={"sector": "Sector", "tanques": "Tanques",
                            "kl_medidos": "Medido (kL)", "kl_estimados": "Estimado (kL)",
                            "kl_pendientes": "Δ sin medir (kL)", "movs_sin_medir": "Movs. sin medir",
                            "horas_prom_pond": "Antigüedad prom. (h)",
                            "horas_peor_medicion": "Peor caso (h)"})
    st.dataframe(_d, hide_index=True, use_container_width=True,
                 column_config={c: st.column_config.NumberColumn(format="%.1f") for c in
                                ["Medido (kL)", "Estimado (kL)", "Δ sin medir (kL)",
                                 "Antigüedad prom. (h)", "Peor caso (h)"]})
    st.caption(
        "**Medido** = último nivel que reportó el tanque. **Estimado** = ese nivel más o menos los movimientos "
        "que se cargaron después. **Δ sin medir** = la diferencia entre ambos, es decir cuánto del stock "
        "reportado todavía no confirmó ningún sensor. Cuanto más grande sea, más se está reportando una "
        "cuenta en vez de una medición.")

    # --- Inventario valorizado ---
    st.markdown("**Inventario valorizado**")
    inv = _q_inventario(cat)
    if inv is None or inv.empty:
        st.info("Sin inventario valorizado."); return
    inv = _num(inv.copy(), ["tanques", "t_medidas", "t_estimadas", "usd_por_t", "usd_medido", "usd_estimado"])

    _tot = float(inv["usd_medido"].sum())
    _fin = float(inv.loc[inv["tipo_producto"] == "FINAL", "usd_medido"].sum())
    _sinp = float(inv.loc[inv["usd_por_t"].isna(), "t_medidas"].sum())
    g1, g2, g3 = st.columns(3)
    _tarjeta(g1, "Capital inmovilizado en tanques", None, "", None, GRIS, valor_txt=_fmt_usd(_tot),
             sufijo=f"{inv['t_medidas'].sum():,.0f} t medidas")
    _tarjeta(g2, "De eso, producto terminado", None, "", None, GRIS, valor_txt=_fmt_usd(_fin),
             sufijo=(f"{100.0*_fin/_tot:,.0f} % del total" if _tot else ""))
    _tarjeta(g3, "Toneladas sin precio de referencia", _sinp, " t", None,
             (AMBAR if _sinp > 0 else VERDE), sufijo="quedan fuera del valorizado")

    _prod = (inv.groupby(["tipo_producto", "codigo_producto"], as_index=False)
                .agg(**{"Tanques": ("tanques", "sum"), "Toneladas": ("t_medidas", "sum"),
                        "USD/t": ("usd_por_t", "max"), "Valorizado (USD)": ("usd_medido", "sum")})
                .rename(columns={"tipo_producto": "Tipo", "codigo_producto": "Producto"})
                .sort_values("Valorizado (USD)", ascending=False))
    st.dataframe(_prod, hide_index=True, use_container_width=True,
                 column_config={"Toneladas": st.column_config.NumberColumn(format="%.1f"),
                                "USD/t": st.column_config.NumberColumn(format="%.0f"),
                                "Valorizado (USD)": st.column_config.NumberColumn(format="%.0f")})
    st.caption("Valorizado sobre la **última medición real** de cada tanque, no sobre el estimado: es el "
               "número respaldado por un sensor. Los productos sin precio propio se valorizan al precio "
               "de referencia más conservador de su familia.")


# ============================================================================
# Bloque 5 — Calidad de la materia prima
# ============================================================================
def _bloque_calidad(cat):
    st.subheader("5 · Calidad de la materia prima — el agua que se paga como producto")
    st.caption("El laboratorio analiza el agua y la acidez de buena parte de los camiones que entran. "
               "Ese dato hoy no se cruza con nada. Cruzado, responde una pregunta de plata directa: "
               "**¿cuánto de lo que compramos por tonelada es agua?**")

    df = _q_calidad(cat)
    if df is None or df.empty:
        st.info("Sin análisis de laboratorio en portería para el período."); return
    df = _num(df.copy(), ["tickets", "con_lab", "t_recibidas", "t_agua", "agua_pct", "acidez",
                          "usd_agua", "usd_recibido", "usd_por_t"])
    df["cobertura_lab"] = 100.0 * df["con_lab"] / df["tickets"].replace(0, pd.NA)

    _tagua = df["t_agua"].sum()
    _trec = df["t_recibidas"].sum()
    _uagua = df["usd_agua"].sum()
    c1, c2, c3 = st.columns(3)
    _tarjeta(c1, "MP recibida (últimos 4 meses)", _trec, " t", None, GRIS)
    _tarjeta(c2, "Agua estimada dentro de esa MP", _tagua, " t", None,
             (ROJO if _trec and _tagua / _trec > 0.10 else AMBAR if _tagua else VERDE),
             sufijo=(f" · {100.0*_tagua/_trec:,.1f} % del total" if _trec else ""))
    _tarjeta(c3, "Esa agua, valorizada a precio de MP", None, "", None,
             (ROJO if _uagua else GRIS), sufijo="últimos 4 meses", valor_txt=_fmt_usd(_uagua))

    _d = df.rename(columns={"producto_base": "Producto", "tickets": "Camiones",
                            "con_lab": "Con lab", "t_recibidas": "Recibido (t)",
                            "t_agua": "Agua estimada (t)", "agua_pct": "Agua prom. %",
                            "acidez": "Acidez prom.", "cobertura_lab": "Cobertura lab %",
                            "usd_agua": "Agua (USD)"})
    st.dataframe(_d[["Producto", "Camiones", "Con lab", "Cobertura lab %", "Recibido (t)",
                     "Agua prom. %", "Agua estimada (t)", "Agua (USD)", "Acidez prom."]],
                 hide_index=True, use_container_width=True,
                 column_config={"Cobertura lab %": st.column_config.NumberColumn(format="%.1f"),
                                "Recibido (t)": st.column_config.NumberColumn(format="%.1f"),
                                "Agua prom. %": st.column_config.NumberColumn(format="%.1f"),
                                "Agua estimada (t)": st.column_config.NumberColumn(format="%.1f"),
                                "Agua (USD)": st.column_config.NumberColumn(format="%.0f"),
                                "Acidez prom.": st.column_config.NumberColumn(format="%.1f")})

    _peor = df.dropna(subset=["agua_pct"]).sort_values("agua_pct", ascending=False)
    if not _peor.empty:
        r = _peor.iloc[0]
        _ru = r.get("usd_agua")
        _rtxt = f" — **{_fmt_usd(_ru)}** a precio de referencia de esa materia prima" if pd.notna(_ru) else ""
        st.warning(
            f"**{r['producto_base']} entra con {r['agua_pct']:,.1f} % de agua promedio** sobre "
            f"{r['t_recibidas']:,.0f} t recibidas — unas **{r['t_agua']:,.0f} t de agua**{_rtxt}. "
            "Si se paga por peso bruto sin descontar humedad, esas toneladas se pagan a precio de producto "
            "y además consumen capacidad de tanque, de reactor y de tratamiento de efluentes."
        )

    with st.expander("Qué falta para cerrar este bloque"):
        st.markdown(
            "El dólar de arriba valoriza el agua al **precio de referencia** de esa materia prima, no al "
            "precio que se pagó realmente en cada operación. Para convertir esto en un control de sobrepago "
            "faltan dos cosas que todavía no están en el sistema:\n\n"
            "- **La calidad pactada por contrato con cada proveedor**, para comparar recibido contra pagado.\n"
            "- **El precio efectivamente pagado por ticket**, para atribuir la diferencia a un proveedor y "
            "una factura concretos.\n\n"
            "Con eso, este bloque deja de ser informativo y pasa a ser una lista de proveedores ordenada "
            "por cuánta agua nos facturaron.")


# ============================================================================
# Cierre — qué hacer con todo esto
# ============================================================================
def _cierre():
    with st.expander("🧭 En qué orden conviene atacar esto"):
        st.markdown(
            "**1 · Cerrar el circuito de salida.** Ningún camión sale sin despacho emitido, y todo despacho "
            "descuenta del tanque. La cañería del sistema ya está hecha; falta que operaciones use el módulo "
            "en vez de dejar la salida solo en portería. Mientras esto no pase, todo control de pérdidas es decoración.\n\n"
            "**2 · Cargar el ticket final de cada batch.** Es lo que convierte el rendimiento de un plan en una "
            "medición. Bajo esfuerzo, alto impacto: hoy dos tercios de la producción reporta el objetivo como resultado.\n\n"
            "**3 · Subir la cobertura del libro de tanques al 90 %.** Atacar por sector, empezando por los que "
            "están en 0 %. Cada trasvase, cada carga y cada purga tiene que dejar un movimiento. En paralelo, "
            "corregir los sectores que registran más de lo que ocurrió: son errores de imputación que ensucian el inventario.\n\n"
            "**4 · Recién ahí, detección por evento.** Con cobertura alta, una caída de nivel sin movimiento "
            "registrado deja de ser ruido y pasa a ser una pregunta concreta: qué tanque, qué hora, qué camión. "
            "Y ahí la pregunta *\"¿nos están robando?\"* tiene una respuesta en vez de una opinión.\n\n"
            "---\n\n"
            "**Lo que hay que evitar.** Mirar el número grande de toneladas sin respaldo y leerlo como faltante. "
            "No lo es. Hoy la planta tiene el problema inverso al que parece: no es que haya mucho desvío, "
            "es que todavía no hay medición suficiente para saberlo.")


# ============================================================================
def render(USR, cat, conectar):
    precios, fecha_precios, df_precios = _precios(cat)
    _portada()
    st.divider()
    _bloque_dinero(cat, precios, fecha_precios, df_precios)
    st.divider()
    _bloque_confiabilidad(cat)
    st.divider()
    _bloque_conversion(cat)
    st.divider()
    _bloque_rendimiento(cat, precios)
    st.divider()
    _bloque_stock(cat)
    st.divider()
    _bloque_calidad(cat)
    st.divider()
    _cierre()
