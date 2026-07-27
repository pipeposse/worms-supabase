"""Control de gestión (Dirección) — desvíos, movimientos, estimado vs real, stock.

Pensada para que un director la abra por primera vez y la entienda sin que nadie
se la explique. Cada bloque responde tres preguntas: qué estoy viendo, de dónde
sale el número, y qué hago si está mal.

Orden deliberado:
  1. Confiabilidad del dato  — ¿los KPIs de abajo son creíbles?
  2. Conversión de planta    — el único rendimiento medido que no depende de carga manual.
  3. Rendimiento por batch   — estimado vs real, y cuántos batches son realmente "real".
  4. Stock                   — cuánto del inventario es medición y cuánto extrapolación.
  5. Calidad de la MP        — el agua que se compra a precio de producto.

render(USR, cat, conectar)

Vistas de soporte (esquema produccion):
  v_dir_confiabilidad, v_dir_conversion_planta, v_dir_rendimiento_batch,
  v_dir_stock_confianza, v_dir_calidad_mp, v_cobertura_libro_semanal,
  v_salida_sin_respaldo
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


def _tarjeta(col, titulo, valor, unidad, meta, color, sufijo=""):
    _v = "—" if valor is None or pd.isna(valor) else f"{float(valor):,.1f}{unidad}"
    _m = "" if meta is None or pd.isna(meta) else f"meta {float(meta):,.0f}{unidad}"
    col.markdown(
        f"<div style='border:1px solid #e2e8f0;border-left:6px solid {color};"
        f"border-radius:8px;padding:.7rem .9rem;height:100%'>"
        f"<div style='font-size:.78rem;color:#475569;line-height:1.2;min-height:2.4em'>{titulo}</div>"
        f"<div style='font-size:1.9rem;font-weight:800;color:{color};line-height:1.15'>{_v}</div>"
        f"<div style='font-size:.72rem;color:#94a3b8'>{_m}{sufijo}</div>"
        f"</div>", unsafe_allow_html=True)


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
    sal = cat("SELECT estado_control, COUNT(*) AS camiones, "
              "ROUND((SUM(kg)/1000.0)::numeric,1) AS toneladas "
              "FROM produccion.v_salida_sin_respaldo "
              "WHERE fecha >= current_date - 28 GROUP BY 1 ORDER BY 3 DESC NULLS LAST")
    if sal is None or sal.empty:
        st.info("Sin salidas registradas en los últimos 28 días.")
    else:
        sal = _num(sal.copy(), ["camiones", "toneladas"])
        _lbl = {"OK": "🟢 OK — despacho emitido y tanque descontado",
                "SIN DESPACHO": "🟡 Salió sin despacho emitido",
                "SIN SALIDA DE TANQUE": "🟡 Hay despacho pero no se descontó del tanque",
                "SIN RESPALDO": "🔴 Sin despacho y sin descuento de tanque"}
        sal["Estado"] = sal["estado_control"].map(lambda x: _lbl.get(x, x))
        st.dataframe(sal[["Estado", "camiones", "toneladas"]]
                     .rename(columns={"camiones": "Camiones", "toneladas": "Toneladas"}),
                     hide_index=True, use_container_width=True,
                     column_config={"Toneladas": st.column_config.NumberColumn(format="%.1f")})
        _sr = float(sal.loc[sal["estado_control"] == "SIN RESPALDO", "toneladas"].sum() or 0)
        if _sr > 0:
            st.warning(
                f"**{_sr:,.0f} t salieron en los últimos 28 días sin despacho ni descuento de tanque.** "
                "Cuidado con leer esto como faltante: casi todo es producto legítimamente vendido cuyo "
                "circuito administrativo nunca se cerró en el sistema. El problema no es que falte producto, "
                "es que **no hay forma de saberlo**. Mientras este número no baje, ningún control de pérdidas funciona."
            )


# ============================================================================
# Bloque 2 — Conversión de planta (balanza)
# ============================================================================
def _bloque_conversion(cat):
    st.subheader("2 · Conversión de planta — el rendimiento que no se puede maquillar")
    st.caption("Toneladas de producto terminado que salieron de planta, sobre toneladas de materia prima que "
               "entraron. **Se calcula solo con la balanza**: no depende de que nadie cargue nada en el sistema. "
               "Es el indicador más robusto que tiene la planta hoy.")

    df = cat("SELECT semana, mp_entrada_t, pf_salida_t, conversion_pct, camiones_mp, camiones_pf "
             "FROM produccion.v_dir_conversion_planta "
             "WHERE semana >= (date_trunc('week', now())::date - INTERVAL '26 weeks') "
             "AND semana < date_trunc('week', now())::date "
             "ORDER BY semana")
    if df is None or df.empty:
        st.info("Sin datos de portería para calcular la conversión."); return
    df = _num(df.copy(), ["mp_entrada_t", "pf_salida_t", "conversion_pct", "camiones_mp", "camiones_pf"])
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

    st.info(
        "**Cómo leerlo.** Las barras grises son cada semana; la línea azul es la media móvil de 4 semanas.\n\n"
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
    _t = df[["Semana", "mp_entrada_t", "pf_salida_t", "conversion_pct", "mm4", "camiones_mp", "camiones_pf"]].copy()
    _t = _t.rename(columns={"mp_entrada_t": "MP entrada (t)", "pf_salida_t": "PF salida (t)",
                            "conversion_pct": "Conversión %", "mm4": "Media móvil 4s %",
                            "camiones_mp": "Camiones MP", "camiones_pf": "Camiones PF"})
    st.dataframe(_t.sort_values("Semana", ascending=False), hide_index=True, use_container_width=True,
                 column_config={"MP entrada (t)": st.column_config.NumberColumn(format="%.0f"),
                                "PF salida (t)": st.column_config.NumberColumn(format="%.0f"),
                                "Conversión %": st.column_config.NumberColumn(format="%.1f"),
                                "Media móvil 4s %": st.column_config.NumberColumn(format="%.1f")})


# ============================================================================
# Bloque 3 — Rendimiento por batch: estimado vs real
# ============================================================================
def _bloque_rendimiento(cat):
    st.subheader("3 · Rendimiento por batch — ¿el sistema muestra el plan o el resultado?")
    st.caption("Cuando una reacción termina, el sistema anota cuánto producto se obtuvo. La pregunta es de "
               "dónde sale ese número: de una pesada real, o del objetivo que se había planificado.")

    df = cat("SELECT id_batch, identificador_unidad, tipo_proceso, fecha, mp_kg, objetivo_kg, "
             "producido_kg, kg_ticket_final, tiene_ticket_final, calidad_dato, "
             "rend_medido_pct, rend_objetivo_pct "
             "FROM produccion.v_dir_rendimiento_batch "
             "WHERE fecha >= current_date - 120 ORDER BY fecha DESC")
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


# ============================================================================
# Bloque 5 — Calidad de la materia prima
# ============================================================================
def _bloque_calidad(cat):
    st.subheader("5 · Calidad de la materia prima — el agua que se paga como producto")
    st.caption("El laboratorio analiza el agua y la acidez de buena parte de los camiones que entran. "
               "Ese dato hoy no se cruza con nada. Cruzado, responde una pregunta de plata directa: "
               "**¿cuánto de lo que compramos por tonelada es agua?**")

    df = cat("SELECT producto_base, SUM(tickets) AS tickets, SUM(tickets_con_lab) AS con_lab, "
             "ROUND(SUM(t_recibidas)::numeric,1) AS t_recibidas, "
             "ROUND(SUM(t_agua_estimadas)::numeric,1) AS t_agua, "
             "ROUND((SUM(t_recibidas*agua_prom_pct)/NULLIF(SUM(t_recibidas),0))::numeric,2) AS agua_pct, "
             "ROUND((SUM(t_recibidas*acidez_prom)/NULLIF(SUM(t_recibidas),0))::numeric,2) AS acidez "
             "FROM produccion.v_dir_calidad_mp WHERE mes >= current_date - 120 "
             "GROUP BY 1 ORDER BY 4 DESC NULLS LAST")
    if df is None or df.empty:
        st.info("Sin análisis de laboratorio en portería para el período."); return
    df = _num(df.copy(), ["tickets", "con_lab", "t_recibidas", "t_agua", "agua_pct", "acidez"])
    df["cobertura_lab"] = 100.0 * df["con_lab"] / df["tickets"].replace(0, pd.NA)

    _tagua = df["t_agua"].sum()
    _trec = df["t_recibidas"].sum()
    c1, c2, c3 = st.columns(3)
    _tarjeta(c1, "MP recibida (últimos 4 meses)", _trec, " t", None, GRIS)
    _tarjeta(c2, "Agua estimada dentro de esa MP", _tagua, " t", None,
             (ROJO if _trec and _tagua / _trec > 0.10 else AMBAR if _tagua else VERDE),
             sufijo=(f" · {100.0*_tagua/_trec:,.1f} % del total" if _trec else ""))
    _cob = 100.0 * df["con_lab"].sum() / df["tickets"].sum() if df["tickets"].sum() else None
    _tarjeta(c3, "Camiones con análisis de laboratorio", _cob, " %", 80,
             _color_semaforo(_cob, 80, True))

    _d = df.rename(columns={"producto_base": "Producto", "tickets": "Camiones",
                            "con_lab": "Con lab", "t_recibidas": "Recibido (t)",
                            "t_agua": "Agua estimada (t)", "agua_pct": "Agua prom. %",
                            "acidez": "Acidez prom.", "cobertura_lab": "Cobertura lab %"})
    st.dataframe(_d[["Producto", "Camiones", "Con lab", "Cobertura lab %", "Recibido (t)",
                     "Agua prom. %", "Agua estimada (t)", "Acidez prom."]],
                 hide_index=True, use_container_width=True,
                 column_config={c: st.column_config.NumberColumn(format="%.1f") for c in
                                ["Cobertura lab %", "Recibido (t)", "Agua prom. %",
                                 "Agua estimada (t)", "Acidez prom."]})

    _peor = df.dropna(subset=["agua_pct"]).sort_values("agua_pct", ascending=False)
    if not _peor.empty:
        r = _peor.iloc[0]
        st.warning(
            f"**{r['producto_base']} entra con {r['agua_pct']:,.1f} % de agua promedio** sobre "
            f"{r['t_recibidas']:,.0f} t recibidas — unas **{r['t_agua']:,.0f} t de agua**. "
            "Si se paga por peso bruto sin descontar humedad, esas toneladas se pagan a precio de producto "
            "y además consumen capacidad de tanque, de reactor y de tratamiento de efluentes."
        )

    with st.expander("Qué falta para cerrar este bloque"):
        st.markdown(
            "Hoy esto muestra la **calidad recibida**. Para convertirlo en un control de sobrepago falta "
            "cruzarlo con dos cosas que todavía no están en el sistema:\n\n"
            "- **La calidad pactada por contrato con cada proveedor**, para comparar recibido contra pagado.\n"
            "- **El precio efectivamente pagado por ticket**, para valorizar la diferencia en pesos.\n\n"
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
    _portada()
    st.divider()
    _bloque_confiabilidad(cat)
    st.divider()
    _bloque_conversion(cat)
    st.divider()
    _bloque_rendimiento(cat)
    st.divider()
    _bloque_stock(cat)
    st.divider()
    _bloque_calidad(cat)
    st.divider()
    _cierre()
