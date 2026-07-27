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


def _esc(t):
    """Escapa comillas y saltos para meter texto dentro de un atributo HTML title."""
    return (str(t).replace("&", "&amp;").replace('"', "&quot;")
            .replace("<", "&lt;").replace(">", "&gt;").replace("\n", " "))


def _tarjeta(col, titulo, valor, unidad, meta, color, sufijo="", valor_txt=None, ayuda=None):
    """Tarjeta de KPI.

    `ayuda` se muestra como tooltip nativo del navegador al pasar el cursor por
    encima de la tarjeta, y marca el título con un ⓘ para que se note que lo tiene.
    Es tooltip nativo a propósito: funciona igual en desktop, no depende de JS y
    no se rompe si Streamlit cambia de versión.
    """
    if valor_txt is not None:
        _v, _sz = valor_txt, "1.5rem"
    else:
        _v = "—" if valor is None or pd.isna(valor) else f"{float(valor):,.1f}{unidad}"
        _sz = "1.9rem"
    _m = "" if meta is None or pd.isna(meta) else f"meta {float(meta):,.0f}{unidad}"
    _t = f"title='{_esc(ayuda)}'" if ayuda else ""
    _i = ("<span style='color:#94a3b8;font-size:.7rem;cursor:help'> &#9432;</span>" if ayuda else "")
    _cur = "cursor:help;" if ayuda else ""
    col.markdown(
        f"<div {_t} style='border:1px solid #e2e8f0;border-left:6px solid {color};"
        f"border-radius:8px;padding:.7rem .9rem;height:100%;{_cur}'>"
        f"<div style='font-size:.78rem;color:#475569;line-height:1.2;min-height:2.4em'>{titulo}{_i}</div>"
        f"<div style='font-size:{_sz};font-weight:800;color:{color};line-height:1.2'>{_v}</div>"
        f"<div style='font-size:.72rem;color:#94a3b8'>{_m}{sufijo}</div>"
        f"</div>", unsafe_allow_html=True)


def _colnum(fmt, ayuda):
    """Columna numérica con tooltip. El ícono ⓘ lo pone Streamlit solo con help=."""
    return st.column_config.NumberColumn(format=fmt, help=ayuda)


def _coltxt(ayuda):
    return st.column_config.TextColumn(help=ayuda)


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
            "que sobra o falta se vuelve una pregunta con respuesta.\n\n"
            "---\n\n"
            "**Dos cosas prácticas.** Pasá el cursor por encima de cualquier tarjeta o encabezado de "
            "columna de esta pantalla: aparece qué mide, cómo se calcula y qué NO significa. "
            "Y al final de todo, el bloque **6 · Qué falta para que esta pantalla sea precisa** lista los "
            "supuestos de cada número y qué hay que cargar para que dejen de ser estimaciones."
        )


# ============================================================================
# Bloque 0 — Lo que está en juego, en dólares
# ============================================================================
DIAS_PRECIO_VENCIDO = 30


def _antiguedad_precios(df_precios, dias=DIAS_PRECIO_VENCIDO):
    """Precios con más de `dias` sin actualizar, o sin fecha.

    Un precio viejo no rompe nada visible: simplemente todos los dólares de la
    pantalla quedan viejos en silencio. Por eso se avisa arriba y no en un pie.
    Devuelve (df_vencidos, dias_maximos).
    """
    if df_precios is None or df_precios.empty or "al" not in df_precios.columns:
        return None, None
    d = df_precios.copy()
    d["_al"] = pd.to_datetime(d["al"], errors="coerce")
    _hoy = pd.Timestamp.now().normalize()
    d["_dias"] = (_hoy - d["_al"].dt.normalize()).dt.days
    _v = d[d["_dias"].isna() | (d["_dias"] > int(dias))]
    _val = d["_dias"].dropna()
    return _v, (int(_val.max()) if len(_val) else None)


def _alerta_precios(df_precios):
    _v, _max = _antiguedad_precios(df_precios)
    if _v is None or _v.empty:
        if _max is not None:
            st.caption(f"✅ Todos los precios de referencia se actualizaron en los últimos "
                       f"{DIAS_PRECIO_VENCIDO} días (el más viejo, hace {_max}).")
        return
    _n = len(_v)
    _lst = ", ".join(
        f"**{r['codigo']}** ({'sin fecha' if pd.isna(r['_dias']) else str(int(r['_dias'])) + ' d'})"
        for _, r in _v.sort_values("_dias", ascending=False, na_position="first").head(8).iterrows())
    if _n > 8:
        _lst += f" y {_n - 8} más"
    st.error(
        f"⚠️ **{_n} de {len(df_precios)} precios de referencia llevan más de "
        f"{DIAS_PRECIO_VENCIDO} días sin actualizarse.** {_lst}.\n\n"
        "Mientras estén viejos, todas las cifras en dólares de esta pantalla son viejas — y no se nota, "
        "porque el número sigue apareciendo igual de prolijo. Se corrigen en *Con qué precios se "
        "valoriza todo esto*, acá abajo."
        + ("\n\nOjo especial con **TC_USD**: si el tipo de cambio quedó atrasado, todo lo cargado en "
           "pesos (fuel, glicerina, potasa) aparece más caro en dólares de lo que realmente es."
           if (_v["codigo"].astype(str) == "TC_USD").any() else ""))


def _editor_precios(USR, cat, conectar, df_precios):
    """Editor de precios de referencia, para que comercial los corrija sin SQL ni redeploy.

    Escribe solo la columna `precio` y sella `actualizado_en` / `usuario`. No permite
    crear ni borrar códigos: alta de un producto nuevo sigue siendo una migración, para
    que nadie invente un código que después nadie mapea.
    """
    if conectar is None:
        return
    if str(USR.get("rol", "")).upper() not in ("SUPERVISOR", "ADMIN"):
        return
    st.markdown("**Actualizar precios**")
    st.caption("Editá la columna *Precio nuevo* y guardá. Solo se escribe lo que cambiaste. "
               "Cada cambio queda con tu usuario y la fecha de hoy. "
               "Si actualizás `TC_USD`, se re-valorizan de golpe todos los insumos cargados en pesos.")
    _e = df_precios[["codigo", "rol", "unidad", "moneda", "precio"]].copy()
    _e = _e.rename(columns={"codigo": "Código", "rol": "Rol", "unidad": "Unidad",
                            "moneda": "Moneda", "precio": "Precio nuevo"})
    _e["Precio nuevo"] = pd.to_numeric(_e["Precio nuevo"], errors="coerce")
    _orig = dict(zip(_e["Código"], _e["Precio nuevo"]))
    try:
        _ed = st.data_editor(
            _e, hide_index=True, use_container_width=True, key="cg_precios_editor",
            disabled=["Código", "Rol", "Unidad", "Moneda"],
            column_config={
                "Código": _coltxt("No se puede cambiar. Dar de alta un código nuevo requiere migración, "
                                  "para que no queden precios que ningún producto mapea."),
                "Rol": _coltxt("MP, FINAL, INSUMO o FX."),
                "Unidad": _coltxt("TN, KG o L. Si el precio que tenés está en otra unidad, avisá antes de "
                                  "cargarlo: la conversión la hace el sistema en función de esta columna."),
                "Moneda": _coltxt("USD o ARS."),
                "Precio nuevo": _colnum("%.2f", "Escribí acá el precio vigente, en la unidad y moneda de "
                                                "las columnas de al lado.")})
    except Exception:
        st.caption("El editor no está disponible en esta versión de Streamlit.")
        return
    if _ed is None:
        return
    _cambios = []
    for _, r in _ed.iterrows():
        _cod = str(r["Código"])
        _new = r["Precio nuevo"]
        if _new is None or pd.isna(_new):
            continue
        _old = _orig.get(_cod)
        if _old is None or pd.isna(_old) or abs(float(_new) - float(_old)) > 1e-9:
            _cambios.append((_cod, float(_new)))
    if not _cambios:
        st.caption("Sin cambios pendientes.")
        return
    st.warning("Cambios sin guardar: " +
               ", ".join(f"**{c}** → {v:,.2f}" for c, v in _cambios))
    if not st.button("Guardar precios", key="cg_precios_guardar", type="primary"):
        return
    try:
        with conectar(USR["id_usuario"]) as (conn, audit):
            with conn.cursor() as cur:
                for _cod, _val in _cambios:
                    cur.execute(
                        "UPDATE produccion.dim_precio_ref SET precio = %s, actualizado_en = now(), "
                        "usuario = %s WHERE codigo = %s",
                        (_val, str(USR.get("nombre") or USR.get("id_usuario")), _cod))
        cat.clear()
        st.success(f"{len(_cambios)} precio(s) actualizado(s). "
                   "Todos los dólares de la pantalla se recalculan al recargar.")
        try:
            st.rerun()
        except Exception:
            pass
    except Exception as e:
        st.error(f"No se pudieron guardar los precios: {e}")


def _bloque_dinero(USR, cat, conectar, precios, fecha_precios, df_precios):
    st.subheader("0 · Lo que está en juego, en dólares")
    st.markdown(
        "Este bloque **no agrega información nueva**: son las mismas brechas que se detallan en los "
        "bloques 1 a 5, multiplicadas por el precio de referencia de cada producto. Está arriba de todo "
        "por una razón práctica — *554 toneladas de agua* es un dato de laboratorio, *USD 415.000* es "
        "una decisión de compras. El mismo hecho, expresado en la unidad en la que se actúa."
    )

    with st.expander("📖 Cómo se lee este bloque (y cómo NO se lee)", expanded=False):
        st.markdown(
            "**Cada tarjeta es una pregunta distinta, con una ventana de tiempo distinta.** No son cuatro "
            "partes de un mismo total, no se suman, y solo una de las cuatro es una pérdida en el sentido "
            "contable de la palabra. Leerlas juntas como \"lo que perdemos\" sería un error de varios "
            "millones de dólares.\n\n"
            "| Tarjeta | Qué mide | Ventana | ¿Es pérdida? |\n"
            "|---|---|---|---|\n"
            "| Salió sin circuito cerrado | Producto que cruzó la balanza de salida sin despacho emitido "
            "ni descuento de tanque | 28 días | **No.** Casi todo es venta legítima mal registrada |\n"
            "| Brecha de rendimiento | Producto que el proceso no entregó respecto del objetivo de receta "
            "| 120 días | **Parcialmente.** Es un supuesto extrapolado |\n"
            "| Agua dentro de la MP | Humedad que se compró y se pagó como si fuera producto | 120 días "
            "| **Depende.** Puede estar ya descontada en el precio negociado |\n"
            "| Inventario valorizado | Producto físicamente en tanques ahora mismo | Foto de hoy "
            "| **No.** Es capital de trabajo inmovilizado |\n\n"
            "---\n\n"
            "**De dónde sale cada dólar.** Ninguno está escrito en el código. Todos salen de la tabla "
            "`produccion.dim_precio_ref`, que tiene un precio de referencia por producto y el tipo de cambio. "
            "El sistema resuelve tres cosas por su cuenta:\n\n"
            "- **La unidad.** Un precio cargado en ARS por litro se convierte a USD por tonelada usando la "
            "densidad del producto y el tipo de cambio. No hay que cargar nada dos veces.\n"
            "- **El producto sin precio propio.** Las borras y los sebos no tienen precio de lista: se "
            "valorizan al precio más conservador de su familia (AG-C). Se prefiere subestimar antes que inflar.\n"
            "- **El mapeo.** Qué precio le corresponde a cada producto vive en dos tablas editables "
            "(`dim_precio_map` para stock, `dic_flujo_porteria` para portería). Cambiar un mapeo no requiere "
            "tocar código ni volver a desplegar la aplicación.\n\n"
            "**Consecuencia práctica:** si un precio está mal, toda esta pantalla está mal — pero se arregla "
            "en un renglón de una tabla y se corrige sola en la siguiente recarga."
        )

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
             sufijo="valorizado a precio de venta",
             ayuda="QUÉ MIDE: camiones que cruzaron la balanza de salida en los últimos 28 días sin "
                   "un despacho emitido en el sistema o sin el descuento correspondiente en el tanque. "
                   "CÓMO SE CALCULA: suma de kg de v_salida_sin_respaldo con estado distinto de OK, "
                   "convertida a toneladas y multiplicada por el precio de referencia del producto final "
                   "que corresponde a ese flujo de portería. "
                   "OJO: NO es faltante. Es producto real, casi todo vendido de forma legítima, cuyo "
                   "circuito administrativo nunca se cerró. Mide el tamaño del agujero de trazabilidad, "
                   "no el tamaño de un robo.")
    _tarjeta(c2, "Producto no obtenido por brecha de rendimiento · 120 días", None, "", None,
             (ROJO if (_usd_rend or 0) < 0 else GRIS), valor_txt=_fmt_usd(_usd_rend),
             sufijo=(f"{_t_rend:,.0f} t" if _t_rend is not None else ""),
             ayuda="QUÉ MIDE: cuánto producto dejó de obtenerse respecto del objetivo de receta. "
                   "CÓMO SE CALCULA: sobre los batches que SÍ tienen pesada real se saca el rendimiento "
                   "promedio y se resta el objetivo; esa diferencia en puntos porcentuales se aplica a "
                   "TODA la materia prima procesada del período, incluidos los batches sin pesada. El "
                   "resultado en toneladas se multiplica por el precio del producto final. "
                   "OJO: es una extrapolación. Hoy solo una minoría de los batches tiene pesada real, "
                   "así que el número supone que los batches no medidos rinden como los medidos.")
    _tarjeta(c3, "Agua comprada dentro de la materia prima · 120 días", None, "", None,
             (ROJO if (_usd_agua or 0) > 100_000 else AMBAR if (_usd_agua or 0) > 0 else GRIS),
             valor_txt=_fmt_usd(_usd_agua),
             sufijo=(f"{_t_agua:,.0f} t de agua" if _t_agua is not None else ""),
             ayuda="QUÉ MIDE: las toneladas de agua que entraron a planta dentro de la materia prima y "
                   "se pagaron al precio del producto seco. "
                   "CÓMO SE CALCULA: por cada ticket con análisis de laboratorio, toneladas recibidas × "
                   "porcentaje de humedad; el promedio de humedad se extiende a los tickets sin análisis "
                   "del mismo producto. Se valoriza al precio de referencia de esa materia prima. "
                   "OJO: parte de esta humedad puede estar ya contemplada en el precio negociado con el "
                   "proveedor. Es un techo, no una factura.")
    _tarjeta(c4, "Inventario en tanques valorizado · hoy", None, "", None, GRIS,
             valor_txt=_fmt_usd(_usd_inv),
             sufijo=(f"{_t_inv:,.0f} t medidas" if _t_inv is not None else ""),
             ayuda="QUÉ MIDE: cuánto capital hay parado en los tanques en este momento. "
                   "CÓMO SE CALCULA: kilos de la ÚLTIMA MEDICIÓN REAL de cada tanque (no el estimado), "
                   "pasados a toneladas y multiplicados por el precio de referencia del producto de ese "
                   "tanque. Se usa el medido a propósito: es el número respaldado por un sensor. "
                   "OJO: no es una pérdida, es capital de trabajo. Tampoco incluye los tanques cuyo "
                   "producto no tiene precio de referencia cargado.")

    st.caption(f"Precios de referencia al **{fecha_precios or 's/d'}**. "
               "Si están viejos, todo lo de arriba se mueve en bloque: cambiar los precios "
               "en `dim_precio_ref` actualiza esta pantalla entera sin tocar nada más. "
               "Pasá el cursor por encima de cualquier tarjeta o encabezado de columna de esta pantalla "
               "para ver qué mide y cómo se calcula.")
    _alerta_precios(df_precios)

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
            "`produccion.dim_precio_ref`. **No hay precios escritos en el código.** Eso es deliberado: "
            "quien conoce los precios es comercial, no sistemas, y tiene que poder corregirlos sin pedirle "
            "nada a nadie ni esperar un despliegue.\n\n"
            "**Cómo se normaliza cada precio.** La tabla acepta el precio en la unidad en la que se compra "
            "o se vende — USD por tonelada, ARS por litro, ARS por kilo — y el sistema lo lleva a **USD por "
            "tonelada**, que es la unidad común de toda la pantalla:\n\n"
            "- *USD/tn* → se usa tal cual.\n"
            "- *USD/kg* → se multiplica por 1.000.\n"
            "- *ARS/kg* → se multiplica por 1.000 y se divide por el tipo de cambio `TC_USD`.\n"
            "- *ARS/litro* → se multiplica por 1.000, se divide por el tipo de cambio y se divide por la "
            "densidad del producto (de `dim_precio_map` o, si no está, de `dim_producto`).\n\n"
            "**Qué pasa con un producto sin precio propio.** Se valoriza al precio de referencia más "
            "conservador de su familia — borras y sebos van a AG-C. Si un producto no tiene ni eso, queda "
            "fuera del total en dólares y sus toneladas se cuentan aparte, para que no se confunda "
            "\"vale cero\" con \"no sabemos cuánto vale\".\n\n"
            "**Dónde se corrige el mapeo.** `produccion.dim_precio_map` para los productos de stock y "
            "`produccion.dic_flujo_porteria` para los flujos de portería. Ambas son tablas, no código.")
        if df_precios is not None and not df_precios.empty:
            _p = df_precios.rename(columns={"codigo": "Código", "rol": "Rol", "precio": "Precio",
                                            "unidad": "Unidad", "moneda": "Moneda",
                                            "descripcion": "Descripción", "al": "Actualizado"})
            try:
                _dd = (pd.Timestamp.now().normalize()
                       - pd.to_datetime(_p["Actualizado"], errors="coerce").dt.normalize()).dt.days
                _p["Días sin actualizar"] = _dd
                _p["Estado"] = _dd.map(
                    lambda x: "⚪ sin fecha" if pd.isna(x)
                    else ("🔴 vencido" if x > DIAS_PRECIO_VENCIDO
                          else "🟡 por vencer" if x > DIAS_PRECIO_VENCIDO * 0.7 else "🟢 vigente"))
            except Exception:
                pass
            st.markdown("**Precios de referencia cargados**")
            st.dataframe(_p, hide_index=True, use_container_width=True, column_config={
                "Código": _coltxt("Identificador del precio. Es lo que apuntan dim_precio_map y "
                                  "dic_flujo_porteria para saber qué precio le toca a cada producto."),
                "Rol": _coltxt("MP = materia prima que se compra · FINAL = producto que se vende · "
                               "INSUMO = se consume en el proceso · FX = tipo de cambio."),
                "Precio": _colnum("%.2f", "Valor cargado, en la unidad y moneda de las columnas de al lado. "
                                          "Se normaliza a USD/t antes de usarse."),
                "Unidad": _coltxt("TN, KG o L. Determina cómo se convierte a USD por tonelada."),
                "Moneda": _coltxt("USD o ARS. Si es ARS se divide por TC_USD."),
                "Actualizado": _coltxt("Fecha de la última modificación del precio. Si está vieja, todos "
                                       "los dólares de esta pantalla están viejos."),
                "Días sin actualizar": _colnum("%.0f", "Días transcurridos desde la última modificación."),
                "Estado": _coltxt(f"Vigente hasta {DIAS_PRECIO_VENCIDO} días; por vencer a partir de "
                                  f"{int(DIAS_PRECIO_VENCIDO * 0.7)}; vencido después. Es una convención "
                                  "de la pantalla, no una regla del negocio: si tus precios se mueven más "
                                  "rápido, avisá y se baja el umbral.")})
            _editor_precios(USR, cat, conectar, df_precios)
        _pp = cat("SELECT codigo_producto AS \"Producto\", tipo_producto AS \"Tipo\", "
                  "codigo_precio AS \"Precio de referencia\", usd_por_t AS \"USD/t\" "
                  "FROM produccion.v_dir_precio_producto WHERE usd_por_t IS NOT NULL "
                  "ORDER BY tipo_producto, codigo_producto")
        if _pp is not None and not _pp.empty:
            st.markdown("**Precio aplicado a cada producto de stock**")
            st.caption("Esta es la traducción final: qué USD por tonelada termina usando el sistema para "
                       "cada producto, después de resolver el mapeo, la unidad y el tipo de cambio.")
            st.dataframe(_pp, hide_index=True, use_container_width=True, column_config={
                "Producto": _coltxt("Código del producto tal como aparece en stock y en las recetas."),
                "Tipo": _coltxt("MP, FINAL o INSUMO, según dim_producto."),
                "Precio de referencia": _coltxt("Qué precio de dim_precio_ref se le aplicó. Si dice AG-C "
                                                "en un producto que no es AG-C, es un fallback conservador "
                                                "de familia, no un error."),
                "USD/t": _colnum("%.1f", "Precio final normalizado a dólares por tonelada. Este es el "
                                         "número que multiplica a las toneladas en toda la pantalla.")})


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
        _tarjeta(cols[i], r["kpi"], r["valor"], str(r["unidad"]), r["meta"], _c,
                 ayuda=f"{r.get('que_mide') or ''} — {r.get('por_que_importa') or ''}")

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
        _cfg_cob = {
            "Sector": _coltxt("Grupo de tanques. El control se hace por sector porque los desvíos "
                              "suelen ser de operación, no de un tanque puntual."),
            "Tanques": _colnum("%d", "Cantidad de tanques del sector considerados en el período."),
            "Movió de verdad (kL)": _colnum(
                "%.0f", "Suma de las variaciones de nivel que vieron los sensores, en valor absoluto: "
                        "subidas y bajadas se suman, no se compensan. Es el movimiento físico real."),
            "Registrado (kL)": _colnum(
                "%.0f", "Suma de los movimientos cargados en el libro de tanques para el mismo período, "
                        "también en valor absoluto."),
            "Bajas sin respaldo (kL)": _colnum(
                "%.0f", "Litros que BAJARON del tanque sin ningún movimiento registrado que lo explique. "
                        "Es el subconjunto que más importa: el producto que se fue sin papel."),
            "Cobertura": _colnum(
                "%.0f", "Registrado ÷ movió de verdad, en porcentaje. 100 % = el sistema explica todo lo "
                        "que pasó. Por debajo, hay movimiento invisible. POR ENCIMA de 110 % el sistema "
                        "registra más de lo que ocurrió: doble carga o carga al tanque equivocado."),
        }
        try:
            st.dataframe(agg.style.map(_cc, subset=["Cobertura"]).format(_fmt, na_rep="—"),
                         hide_index=True, use_container_width=True, column_config=_cfg_cob)
        except Exception:
            st.dataframe(agg, hide_index=True, use_container_width=True, column_config=_cfg_cob)
        st.caption("Últimas 4 semanas. 🟢 90–110 % · 🟡 50–90 % o 110–130 % · 🔴 fuera de eso. "
                   "Pasá el cursor por el encabezado de cada columna para ver cómo se calcula.")

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
                     column_config={
                         "Estado": _coltxt(
                             "Qué rastros dejó el camión. OK = pesada + despacho emitido + descuento de "
                             "tanque. Los demás estados indican cuál de los tres falta."),
                         "Camiones": _colnum(
                             "%d", "Cantidad de tickets de salida de portería en ese estado, últimos 28 días."),
                         "Toneladas": _colnum(
                             "%.1f", "Kilos netos de la balanza de portería, pasados a toneladas. Es peso "
                                     "real medido, no declarado."),
                         "Valorizado (USD)": _colnum(
                             "%.0f", "Toneladas × precio de referencia del producto final de ese flujo. "
                                     "Los flujos sin precio (compost, residuos, ganado) suman toneladas "
                                     "pero aportan cero dólares.")})
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
    _tarjeta(c1, "Conversión última semana", _ult["conversion_pct"], " %", None, GRIS,
             ayuda="Toneladas de producto terminado que salieron ÷ toneladas de materia prima que "
                   "entraron, en la última semana cerrada. La semana en curso se excluye a propósito: "
                   "estaría incompleta y daría un número engañoso. Ambas cifras salen de la balanza.")
    _tarjeta(c2, "Media móvil 4 semanas", (_mm4.iloc[-1] if len(_mm4) else None), " %", None, GRIS,
             ayuda="El mismo cociente pero sumando las últimas 4 semanas antes de dividir (no es el "
                   "promedio de los 4 porcentajes). Suaviza el desfasaje de acopio: lo que entra una "
                   "semana suele salir la siguiente. Es el número que hay que mirar, no la semana suelta.")
    _rng = df["conversion_pct"].dropna()
    _amp = (_rng.max() - _rng.min()) if len(_rng) else None
    _tarjeta(c3, "Oscilación semana a semana",
             _amp, " pts", None, (ROJO if (_amp or 0) > 30 else AMBAR if (_amp or 0) > 15 else VERDE),
             ayuda="Diferencia en puntos entre la mejor y la peor semana del período mostrado. "
                   "Es un indicador por sí mismo: una planta que convierte de forma estable no salta "
                   "40 puntos entre semanas. Mucha amplitud = el acopio se usa como amortiguador sin "
                   "control, o hubo semanas donde entró MP que nunca salió como producto.")
    _tarjeta(c4, "MP entrada últimas 4 sem.",
             df["mp_entrada_t"].tail(4).sum(), " t", None, GRIS,
             ayuda="Toneladas de materia prima que descargaron en planta en las últimas 4 semanas "
                   "cerradas, según balanza. Es el denominador de la media móvil.")

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
             sufijo=f"{df['mp_entrada_t'].tail(4).sum():,.0f} t",
             ayuda="QUÉ MIDE: el valor de la materia prima que descargó en planta en las 4 semanas "
                   "cerradas más recientes. "
                   "CÓMO SE CALCULA: por cada ticket de portería clasificado como MP, kg de balanza ÷ 1000 "
                   "× el precio de referencia en USD/t del producto de ese flujo. Se suma por semana. "
                   "OJO: es valor de reposición a precio de referencia, no lo que efectivamente se pagó. "
                   "Sirve para dimensionar, no para conciliar contra facturas.")
    _tarjeta(d2, "PF que salió · últimas 4 semanas", None, "", None, GRIS, valor_txt=_fmt_usd(_u_pf),
             sufijo=f"{df['pf_salida_t'].tail(4).sum():,.0f} t",
             ayuda="QUÉ MIDE: el valor del producto terminado que salió por balanza en la misma ventana. "
                   "CÓMO SE CALCULA: kg de balanza de cada ticket clasificado como PF ÷ 1000 × precio de "
                   "referencia en USD/t del producto final de ese flujo. "
                   "OJO: es el producto que físicamente cruzó el portón, tenga o no despacho emitido. "
                   "No es facturación.")
    _tarjeta(d3, "Diferencia — entró y todavía no salió", None, "", None,
             (AMBAR if (_u_mp - _u_pf) > 0 else VERDE), valor_txt=_fmt_usd(_u_mp - _u_pf),
             sufijo="acopio + merma + desfasaje",
             ayuda="QUÉ MIDE: la resta entre las dos tarjetas anteriores. "
                   "CÓMO SE CALCULA: USD de MP que entró menos USD de PF que salió, en las mismas 4 semanas. "
                   "OJO: NO es una pérdida. Junta tres cosas que hoy no se pueden separar: producto que "
                   "quedó en acopio, producto que se procesó y sale la semana siguiente, y merma real de "
                   "proceso. Además, MP y PF se valorizan a precios distintos, así que una parte de la "
                   "diferencia es margen, no volumen. Separar los tres pedazos requiere que suba la "
                   "cobertura del libro de tanques.")

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
            st.dataframe(_d, hide_index=True, use_container_width=True, column_config={
                "Producto": _coltxt("Código de producto tal como lo registra portería en la balanza."),
                "Cuenta como MP": _coltxt("Si está en verdadero, los camiones que entran llenos con este "
                                          "producto suman al numerador de MP entrada."),
                "Cuenta como PF": _coltxt("Si está en verdadero, los camiones que salen llenos con este "
                                          "producto suman a PF salida."),
                "Nota": _coltxt("Motivo de la clasificación. Editable en produccion.dic_flujo_porteria "
                                "sin tocar código ni redeploy.")})

    st.markdown("**Detalle semanal**")
    _t = df[["Semana", "mp_entrada_t", "pf_salida_t", "conversion_pct", "mm4",
             "usd_mp_entrada", "usd_pf_salida", "camiones_mp", "camiones_pf"]].copy()
    _t["Δ USD"] = _t["usd_mp_entrada"] - _t["usd_pf_salida"]
    _t = _t.rename(columns={"mp_entrada_t": "MP entrada (t)", "pf_salida_t": "PF salida (t)",
                            "conversion_pct": "Conversión %", "mm4": "Media móvil 4s %",
                            "usd_mp_entrada": "MP entrada (USD)", "usd_pf_salida": "PF salida (USD)",
                            "camiones_mp": "Camiones MP", "camiones_pf": "Camiones PF"})
    st.dataframe(_t.sort_values("Semana", ascending=False), hide_index=True, use_container_width=True,
                 column_config={
                     "Semana": _coltxt("Lunes de la semana. La semana en curso no aparece: está incompleta "
                                       "y daría una conversión falsamente baja."),
                     "MP entrada (t)": _colnum("%.0f", "Toneladas de materia prima descargadas esa semana "
                                                       "según balanza de portería, tickets de más de 300 kg."),
                     "PF salida (t)": _colnum("%.0f", "Toneladas de producto terminado que salieron esa "
                                                      "semana según balanza de portería."),
                     "Conversión %": _colnum("%.1f", "PF salida ÷ MP entrada × 100, dentro de la misma "
                                                     "semana. Puede pasar de 100 % si se despacha stock "
                                                     "acopiado de semanas anteriores."),
                     "Media móvil 4s %": _colnum("%.1f", "Suma de PF de 4 semanas ÷ suma de MP de esas "
                                                         "mismas 4 semanas × 100. Se suman los totales y "
                                                         "recién ahí se divide: no es el promedio de los "
                                                         "cuatro porcentajes."),
                     "MP entrada (USD)": _colnum("%.0f", "MP de la semana valorizada al precio de "
                                                         "referencia en USD/t de cada producto."),
                     "PF salida (USD)": _colnum("%.0f", "PF de la semana valorizada al precio de "
                                                        "referencia en USD/t de cada producto."),
                     "Δ USD": _colnum("%.0f", "MP entrada (USD) menos PF salida (USD) de esa semana. "
                                              "Mezcla acopio, desfasaje temporal y margen entre precio de "
                                              "MP y de PF. No es pérdida."),
                     "Camiones MP": _colnum("%.0f", "Cantidad de tickets de entrada de materia prima."),
                     "Camiones PF": _colnum("%.0f", "Cantidad de tickets de salida de producto terminado.")})


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
             _color_semaforo(_pct, 95, True), sufijo=f" · {_med} de {_n}",
             ayuda="QUÉ MIDE: qué porcentaje de los batches cerrados en los últimos 120 días tiene un "
                   "ticket de pesada del producto obtenido. "
                   "CÓMO SE CALCULA: batches con calidad_dato = MEDIDO ÷ total de batches × 100. "
                   "OJO: es el indicador madre de todo este bloque. Si está bajo, el rendimiento que muestra "
                   "el sistema no es un resultado, es un plan.")
    _tarjeta(c2, "Batches donde el resultado = el objetivo", (100.0 * _obj / _n if _n else None), " %", None,
             (ROJO if _obj else VERDE), sufijo=f" · {_obj} batches",
             ayuda="QUÉ MIDE: batches donde el kilaje producido que guarda el sistema coincide exactamente "
                   "con el objetivo planificado. "
                   "CÓMO SE CALCULA: batches con calidad_dato = IGUAL AL OBJETIVO ÷ total × 100. "
                   "OJO: no significa que la planta clave el plan al kilo. Significa que, al no cargarse el "
                   "ticket final, el sistema copió el objetivo y lo mostró como producción. Esos batches "
                   "rinden 100 % por construcción.")
    _rm = df["rend_medido_pct"].dropna()
    _ro = df.loc[df["rend_medido_pct"].notna(), "rend_objetivo_pct"].dropna()
    _tarjeta(c3, "Rendimiento real (solo batches pesados)",
             (_rm.mean() if len(_rm) else None), " %", None, GRIS, sufijo=f" · {len(_rm)} batches",
             ayuda="QUÉ MIDE: rendimiento promedio de los batches que sí tienen pesada real. "
                   "CÓMO SE CALCULA: por batch, kg del ticket final ÷ kg de materia prima cargada × 100; "
                   "después se promedian esos porcentajes. "
                   "OJO: es un promedio simple entre batches, no ponderado por tamaño. Con pocos batches "
                   "medidos, un batch chico pesa lo mismo que uno grande.")
    _brecha = (_rm.mean() - _ro.mean()) if (len(_rm) and len(_ro)) else None
    _tarjeta(c4, "Brecha real vs objetivo", _brecha, " pts", None,
             (ROJO if (_brecha is not None and _brecha < -5) else
              AMBAR if (_brecha is not None and _brecha < 0) else GRIS),
             ayuda="QUÉ MIDE: cuántos puntos porcentuales rinde de menos la planta respecto de lo que la "
                   "receta dice que debería rendir. "
                   "CÓMO SE CALCULA: rendimiento real promedio menos rendimiento objetivo promedio, "
                   "comparando solo los batches que tienen pesada real. "
                   "OJO: negativo es rendir menos que el objetivo. Se calcula sobre la minoría de batches "
                   "medidos, así que es una señal, no una medición de toda la planta.")

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
                 (ROJO if _tot_t < 0 else VERDE),
                 ayuda="QUÉ MIDE: cuántas toneladas de producto terminado no se obtuvieron por rendir "
                       "debajo del objetivo, en los últimos 120 días. "
                       "CÓMO SE CALCULA: por proceso, la brecha en puntos ÷ 100 × toda la materia prima "
                       "procesada por ese proceso en la ventana. "
                       "OJO: la brecha se mide solo sobre los batches pesados y se extrapola a todos. Si "
                       "los batches sin pesar rindieran distinto, este número cambia.")
        _tarjeta(e2, "Valorizado a precio de venta", None, "", None,
                 (ROJO if _tot_u < 0 else VERDE), valor_txt=_fmt_usd(_tot_u),
                 sufijo=f"a USD {float(_pf):,.0f}/t",
                 ayuda="QUÉ MIDE: cuánto valen esas toneladas si se hubieran vendido. "
                       "CÓMO SE CALCULA: toneladas no obtenidas × el precio de referencia del producto "
                       "final ARE-B, tomado de dim_precio_ref. "
                       "OJO: valoriza a precio de venta, no a margen. La ganancia real de cerrar la brecha "
                       "es menor, porque esas toneladas también costarían materia prima y proceso.")
        _tarjeta(e3, "Proyección a 12 meses", None, "", None,
                 (ROJO if _tot_u < 0 else VERDE), valor_txt=_fmt_usd(_tot_u * 365.0 / 120.0),
                 sufijo="si el ritmo se mantiene",
                 ayuda="QUÉ MIDE: el mismo impacto anualizado, para dimensionar si vale la pena invertir "
                       "en corregirlo. "
                       "CÓMO SE CALCULA: impacto de 120 días × 365 ÷ 120. Regla de tres directa. "
                       "OJO: supone volumen y brecha constantes todo el año. No contempla estacionalidad "
                       "ni cambios de mezcla de producto.")
        _cfg = {"Proceso": _coltxt("Tipo de proceso productivo, tal como lo clasifica el batch."),
                "Rend. real %": _colnum("%.1f", "Promedio del rendimiento medido en los batches de ese "
                                                "proceso que tienen ticket final pesado."),
                "Rend. objetivo %": _colnum("%.1f", "Promedio del rendimiento que la receta define como "
                                                    "objetivo, para esos mismos batches."),
                "Brecha (pts)": _colnum("%.1f", "Rendimiento real menos objetivo, en puntos porcentuales. "
                                                "Negativo es rendir de menos."),
                "MP procesada (t)": _colnum("%.1f", "Toda la materia prima que pasó por ese proceso en "
                                                    "120 días, incluidos los batches sin pesar."),
                "t no obtenidas": _colnum("%.1f", "Brecha ÷ 100 × MP procesada. Es la extrapolación: "
                                                  "aplica la brecha de los batches medidos a todo el "
                                                  "volumen del proceso."),
                "Impacto (USD)": _colnum("%.0f", "Toneladas no obtenidas × precio de referencia del "
                                                 "producto final, en USD/t.")}
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
                 column_config={
                     "Origen del dato": _coltxt(
                         "Pesada real: hay ticket final de balanza. Copiado del objetivo: no hay ticket y "
                         "el sistema usó el objetivo como si fuera producción. Estimado desde tanque: se "
                         "dedujo de la diferencia de nivel. Sin producción cargada: el batch se cerró sin "
                         "informar resultado."),
                     "Batches": _colnum("%.0f", "Cantidad de batches en esa categoría, últimos 120 días."),
                     "MP procesada (t)": _colnum("%.1f", "Toneladas de materia prima cargadas en esos "
                                                         "batches. Muestra cuánto volumen real está "
                                                         "respaldado por cada tipo de dato.")})

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
        st.dataframe(_d, hide_index=True, use_container_width=True, column_config={
            "Fecha": _coltxt("Fecha de cierre del batch."),
            "Unidad": _coltxt("Reactor o unidad donde se hizo el batch."),
            "Proceso": _coltxt("Tipo de proceso: define qué objetivo de rendimiento aplica."),
            "Origen del dato": _coltxt("De dónde salió el kilaje producido de esta fila."),
            "MP (t)": _colnum("%.1f", "Materia prima cargada al batch, en toneladas."),
            "Objetivo (t)": _colnum("%.1f", "Producto que la receta dice que debería salir con esa MP."),
            "Producido s/sistema (t)": _colnum("%.1f", "Lo que el sistema guarda como producido. Si el "
                                                       "origen dice Copiado del objetivo, esta columna es "
                                                       "igual a la anterior y no aporta información."),
            "Pesada real (t)": _colnum("%.1f", "Kilos del ticket final de balanza. Vacío cuando no se "
                                               "cargó: ese vacío es el problema, no un error de la vista."),
            "Rend. real %": _colnum("%.1f", "Pesada real ÷ MP × 100. Solo existe si hay ticket final."),
            "Rend. objetivo %": _colnum("%.1f", "Objetivo ÷ MP × 100, según la receta.")})

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
    _tarjeta(c1, "Stock medido (última medición real)", _tot, " kL", None, GRIS,
             ayuda="QUÉ MIDE: el volumen total que efectivamente reportó un sensor de nivel, sumando todos "
                   "los tanques. "
                   "CÓMO SE CALCULA: suma de litros_actual de vw_stock_tanque_actual, en kilolitros. Cada "
                   "tanque aporta su última medición registrada, sea de hace una hora o de hace un mes. "
                   "OJO: no es stock a hoy. Es stock a la fecha de la última medición de cada tanque. La "
                   "tarjeta de la derecha dice qué tan vieja puede ser esa foto.")
    _tarjeta(c2, "Movimiento posterior a la medición", _pend, " kL", None,
             (AMBAR if _tot and _pend / _tot > 0.05 else VERDE),
             sufijo=(f" · {100.0*_pend/_tot:,.1f} % del total" if _tot else ""),
             ayuda="QUÉ MIDE: cuántos kilolitros del stock reportado no son medición sino cuenta: "
                   "movimientos cargados después de la última medición de cada tanque. "
                   "CÓMO SE CALCULA: suma del valor absoluto de delta_litros_pendiente de todos los "
                   "tanques, en kL. Se usa valor absoluto para que las cargas no cancelen las descargas. "
                   "OJO: cuanto más alto respecto del total, más se está informando una extrapolación. "
                   "Se corrige midiendo más seguido, no cargando menos movimientos.")
    _peor = df["horas_peor_medicion"].max()
    _tarjeta(c3, "Tanque medido hace más tiempo", _peor, " h", 48,
             _color_semaforo(_peor, 48, False),
             ayuda="QUÉ MIDE: la antigüedad de la medición más vieja de toda la planta, en horas. "
                   "CÓMO SE CALCULA: máximo, entre todos los sectores, de las horas transcurridas desde la "
                   "última medición del peor tanque de cada uno. "
                   "OJO: es el peor caso, no el promedio. Un solo tanque de acopio olvidado dispara este "
                   "número sin que el resto de la planta esté mal medido. Sirve para ir a buscar ese tanque.")

    _d = df.rename(columns={"sector": "Sector", "tanques": "Tanques",
                            "kl_medidos": "Medido (kL)", "kl_estimados": "Estimado (kL)",
                            "kl_pendientes": "Δ sin medir (kL)", "movs_sin_medir": "Movs. sin medir",
                            "horas_prom_pond": "Antigüedad prom. (h)",
                            "horas_peor_medicion": "Peor caso (h)"})
    st.dataframe(_d, hide_index=True, use_container_width=True, column_config={
        "Sector": _coltxt("Agrupación física de tanques: reactores, plataformas, piletas, bachas, "
                          "exportación."),
        "Tanques": _colnum("%.0f", "Cantidad de tanques activos en ese sector."),
        "Medido (kL)": _colnum("%.1f", "Suma de la última medición real de cada tanque del sector."),
        "Estimado (kL)": _colnum("%.1f", "Esa medición más o menos los movimientos cargados después. Es el "
                                         "número que el sistema reporta como stock actual."),
        "Δ sin medir (kL)": _colnum("%.1f", "Estimado menos medido. Es la porción del stock que ningún "
                                            "sensor confirmó todavía."),
        "Movs. sin medir": _colnum("%.0f", "Cantidad de movimientos registrados posteriores a la última "
                                           "medición. Cuantos más, más se acumula error."),
        "Antigüedad prom. (h)": _colnum("%.1f", "Horas desde la última medición, promediadas entre los "
                                                "tanques del sector y ponderadas por volumen: un tanque "
                                                "grande desactualizado pesa más que uno chico."),
        "Peor caso (h)": _colnum("%.1f", "Horas desde la última medición del tanque peor medido del "
                                         "sector. Es el que hay que ir a medir.")})
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
             sufijo=f"{inv['t_medidas'].sum():,.0f} t medidas",
             ayuda="QUÉ MIDE: cuánta plata hay parada adentro de los tanques en este momento. "
                   "CÓMO SE CALCULA: por tanque, litros de la última medición × densidad del producto ÷ "
                   "1000 para pasar a toneladas, × el precio de referencia en USD/t de ese producto. "
                   "OJO: se valoriza sobre lo medido, no sobre lo estimado, para no inflar el número con "
                   "extrapolaciones. Las toneladas sin precio quedan afuera: ver la tercera tarjeta.")
    _tarjeta(g2, "De eso, producto terminado", None, "", None, GRIS, valor_txt=_fmt_usd(_fin),
             sufijo=(f"{100.0*_fin/_tot:,.0f} % del total" if _tot else ""),
             ayuda="QUÉ MIDE: qué parte del capital inmovilizado ya es producto vendible, y no materia "
                   "prima o insumo. "
                   "CÓMO SE CALCULA: mismo cálculo que la tarjeta anterior, filtrando los productos con "
                   "tipo_producto = FINAL en dim_producto. "
                   "OJO: es la porción que se convierte en cobranza apenas se despache. El resto todavía "
                   "tiene que pasar por proceso.")
    _tarjeta(g3, "Toneladas sin precio de referencia", _sinp, " t", None,
             (AMBAR if _sinp > 0 else VERDE), sufijo="quedan fuera del valorizado",
             ayuda="QUÉ MIDE: cuántas toneladas medidas no pudieron valorizarse porque su producto no "
                   "tiene precio ni mapeo a una familia con precio. "
                   "CÓMO SE CALCULA: suma de t_medidas de las filas donde usd_por_t viene nulo. "
                   "OJO: mientras esto sea mayor a cero, el capital inmovilizado está subestimado. Se "
                   "corrige agregando el código a dim_precio_ref o mapeándolo en dim_precio_map.")

    _prod = (inv.groupby(["tipo_producto", "codigo_producto"], as_index=False)
                .agg(**{"Tanques": ("tanques", "sum"), "Toneladas": ("t_medidas", "sum"),
                        "USD/t": ("usd_por_t", "max"), "Valorizado (USD)": ("usd_medido", "sum")})
                .rename(columns={"tipo_producto": "Tipo", "codigo_producto": "Producto"})
                .sort_values("Valorizado (USD)", ascending=False))
    st.dataframe(_prod, hide_index=True, use_container_width=True,
                 column_config={
                     "Tipo": _coltxt("MP = materia prima, FINAL = producto terminado, INSUMO = insumo de "
                                     "proceso. Sale de dim_producto."),
                     "Producto": _coltxt("Código del producto principal asignado al tanque."),
                     "Tanques": _colnum("%.0f", "Cantidad de tanques que contienen ese producto."),
                     "Toneladas": _colnum("%.1f", "Toneladas según la última medición real: litros × "
                                                  "densidad ÷ 1000. No incluye movimientos posteriores."),
                     "USD/t": _colnum("%.0f", "Precio de referencia normalizado a USD por tonelada. Si el "
                                              "precio original está en USD/kg se multiplica por 1000; si "
                                              "está en ARS se divide además por el tipo de cambio; si está "
                                              "por litro se divide también por la densidad."),
                     "Valorizado (USD)": _colnum("%.0f", "Toneladas × USD/t. Vacío cuando el producto no "
                                                         "tiene precio de referencia.")})
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
    _tarjeta(c1, "MP recibida (últimos 4 meses)", _trec, " t", None, GRIS,
             ayuda="QUÉ MIDE: toneladas de materia prima que descargaron en planta en los últimos 120 días. "
                   "CÓMO SE CALCULA: suma del peso neto de balanza de los tickets de entrada clasificados "
                   "como MP, agrupados por familia de producto. "
                   "OJO: es peso bruto de la carga, agua incluida. Ese es justamente el punto del bloque.")
    _tarjeta(c2, "Agua estimada dentro de esa MP", _tagua, " t", None,
             (ROJO if _trec and _tagua / _trec > 0.10 else AMBAR if _tagua else VERDE),
             sufijo=(f" · {100.0*_tagua/_trec:,.1f} % del total" if _trec else ""),
             ayuda="QUÉ MIDE: cuántas de esas toneladas son agua, según el laboratorio de portería. "
                   "CÓMO SE CALCULA: por familia de producto, porcentaje de agua promedio de los tickets "
                   "analizados × las toneladas recibidas de esa familia. "
                   "OJO: el promedio sale de los camiones que sí tuvieron análisis y se aplica a todos. Si "
                   "la cobertura de laboratorio es baja, el número es una proyección, no un conteo.")
    _tarjeta(c3, "Esa agua, valorizada a precio de MP", None, "", None,
             (ROJO if _uagua else GRIS), sufijo="últimos 4 meses", valor_txt=_fmt_usd(_uagua),
             ayuda="QUÉ MIDE: cuánta plata representa comprar esa agua como si fuera producto. "
                   "CÓMO SE CALCULA: toneladas de agua × el precio de referencia en USD/t de esa materia "
                   "prima. "
                   "OJO: usa el precio de REFERENCIA, no el precio realmente pagado en cada operación. Es "
                   "el orden de magnitud del sobrepago, no el sobrepago exacto. Para eso falta cargar el "
                   "precio por ticket y la calidad pactada por contrato.")

    _d = df.rename(columns={"producto_base": "Producto", "tickets": "Camiones",
                            "con_lab": "Con lab", "t_recibidas": "Recibido (t)",
                            "t_agua": "Agua estimada (t)", "agua_pct": "Agua prom. %",
                            "acidez": "Acidez prom.", "cobertura_lab": "Cobertura lab %",
                            "usd_agua": "Agua (USD)"})
    st.dataframe(_d[["Producto", "Camiones", "Con lab", "Cobertura lab %", "Recibido (t)",
                     "Agua prom. %", "Agua estimada (t)", "Agua (USD)", "Acidez prom."]],
                 hide_index=True, use_container_width=True,
                 column_config={
                     "Producto": _coltxt("Familia de materia prima según el código de portería: AFE, AG, "
                                         "BORRA, SEBO, fondos de tanque."),
                     "Camiones": _colnum("%.0f", "Tickets de entrada de esa familia en los últimos 120 "
                                                 "días."),
                     "Con lab": _colnum("%.0f", "De esos tickets, cuántos tienen análisis de laboratorio "
                                                "cargado."),
                     "Cobertura lab %": _colnum("%.1f", "Con lab ÷ Camiones × 100. Cuanto más baja, más "
                                                        "extrapolado es el resto de la fila."),
                     "Recibido (t)": _colnum("%.1f", "Toneladas de balanza recibidas de esa familia, agua "
                                                     "incluida."),
                     "Agua prom. %": _colnum("%.1f", "Promedio del porcentaje de agua de los tickets que "
                                                     "tienen análisis."),
                     "Agua estimada (t)": _colnum("%.1f", "Agua prom. % ÷ 100 × Recibido (t). Aplica el "
                                                          "promedio de los analizados a todo el volumen."),
                     "Agua (USD)": _colnum("%.0f", "Agua estimada × precio de referencia en USD/t de esa "
                                                   "materia prima."),
                     "Acidez prom.": _colnum("%.1f", "Acidez promedio de los tickets analizados. Es un "
                                                     "indicador de calidad de proceso, no entra en el "
                                                     "cálculo del dinero.")})

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
# Qué falta para que esta pantalla sea precisa
# ============================================================================
def _que_falta():
    st.subheader("6 · Qué falta para que esta pantalla sea precisa")
    st.markdown(
        "Todo lo de arriba está calculado con los datos que hoy existen. Varios números son **órdenes de "
        "magnitud, no mediciones**, y conviene que eso esté escrito acá abajo y no escondido en un pie de "
        "página. Esta sección es la lista honesta de los supuestos: qué hipótesis sostiene cada número, "
        "qué pasa si la hipótesis es falsa, y qué hay que cargar para que el número deje de ser una "
        "estimación.\n\n"
        "**La regla de lectura:** un número con supuesto sirve para decidir *dónde mirar*. No sirve para "
        "decidir *cuánto reclamar*. Ninguna cifra de esta pantalla debería usarse todavía como base de un "
        "reclamo a un proveedor, una sanción a una persona o un ajuste contable."
    )

    st.markdown("**Los cinco supuestos que más pesan**")
    st.markdown(
        "| # | El número | Qué está suponiendo | Si el supuesto es falso | Qué lo arregla |\n"
        "|---|---|---|---|---|\n"
        "| 1 | Producto que salió sin cerrar el circuito (USD) | Que todo lo que salió por balanza sin "
        "despacho es comparable a producto terminado vendible | El monto se infla varias veces: buena "
        "parte son flujos internos o de menor valor | Emitir despacho para toda salida; distinguir venta "
        "de movimiento interno en portería |\n"
        "| 2 | Brecha de rendimiento (USD) | Que los batches sin pesar rinden igual que los pesados | La "
        "brecha real puede ser cero o el doble: hoy no hay forma de saberlo | Cargar el ticket final "
        "pesado en cada batch |\n"
        "| 3 | Agua dentro de la MP (USD) | Que el % de agua de los camiones analizados representa a los "
        "no analizados, y que se pagó el precio de referencia | Se atribuye sobrepago donde quizá el "
        "precio ya venía castigado por calidad | Precio pagado por ticket + calidad pactada por contrato |\n"
        "| 4 | Capital inmovilizado en tanques (USD) | Que la última medición de cada tanque sigue "
        "vigente, y que la densidad cargada es la real | Un tanque medido hace 800 horas puede estar "
        "vacío o lleno | Rutina de medición con frecuencia mínima; validar densidades por producto |\n"
        "| 5 | Conversión de planta (%) | Que MP entrada y PF salida de la misma semana son comparables | "
        "Una semana con mucho acopio parece pérdida y no lo es | Cobertura del libro de tanques al 90 %, "
        "para separar acopio de merma |\n"
    )

    st.markdown("**Lo que falta cargar, en orden de impacto sobre la precisión**")
    st.markdown(
        "**1 · Despacho emitido en toda salida.** Es el que más mueve la aguja: hoy la cobertura de "
        "salidas con respaldo es del 0 %, lo que convierte el KPI de trazabilidad en un número que no "
        "discrimina nada. Mientras todo esté sin respaldo, no se puede distinguir la salida legítima de "
        "la que hay que investigar. Es disciplina operativa, no desarrollo.\n\n"
        "**2 · Ticket final pesado por batch.** Sin esto, el rendimiento que muestra el sistema es el "
        "plan, no el resultado, y la brecha valorizada es una extrapolación desde una minoría de batches. "
        "Además hay un cambio de sistema pendiente: cuando no hay ticket, la producción debería quedar "
        "**vacía** en vez de copiar el objetivo. Un hueco visible se llena; un 100 % falso tranquiliza.\n\n"
        "**3 · Movimientos de tanque completos.** Cada trasvase, carga y purga tiene que dejar registro. "
        "Con la cobertura actual no se puede cerrar el balance físico de ningún sector, y por lo tanto no "
        "se puede afirmar ni descartar un faltante. Hay sectores en 0 % y otros que registran más de lo "
        "que físicamente ocurrió: los segundos son errores de imputación y ensucian el inventario tanto "
        "como los primeros.\n\n"
        "**4 · Frecuencia mínima de medición de tanques.** El inventario valorizado se calcula sobre la "
        "última medición real de cada tanque. Un tanque de acopio medido hace semanas arrastra todo el "
        "número. Una regla simple — ningún tanque con carga sin medir más de 48 horas — sube la confianza "
        "del inventario sin desarrollar nada.\n\n"
        "**5 · Precio pagado por ticket de compra.** Hoy la valorización de la materia prima usa el precio "
        "de referencia. Con el precio real por operación, el bloque de calidad deja de ser informativo y "
        "pasa a ser una lista de proveedores ordenada por cuánta agua facturaron.\n\n"
        "**6 · Equivalencia entre códigos de portería y códigos de consumo.** Portería registra el ingreso "
        "de materia prima con un código y producción la consume con otro. Mientras esa tabla de "
        "equivalencias no exista, el consumo de MP queda fuera del balance por producto y el desvío de "
        "stock de materia prima no se puede calcular.\n\n"
        "**7 · Precios comerciales al día.** Los precios de referencia los conoce comercial, no sistemas. "
        "El editor está arriba, en *Con qué precios se valoriza todo esto*. Cuando un precio queda viejo, "
        "no se rompe nada visible: simplemente todos los dólares de la pantalla quedan viejos en silencio. "
        "Por eso cada precio muestra su fecha, su antigüedad en días y un semáforo, y el bloque 0 avisa en "
        "rojo cuando alguno pasa los 30 días."
    )

    st.info(
        "**Lo que esta pantalla ya hace bien, y conviene no perder de vista.** No inventa datos. Cuando "
        "un producto no tiene precio, sus toneladas se cuentan aparte en vez de valorizarse en cero. "
        "Cuando un batch no tiene pesada, aparece clasificado como tal en vez de mezclarse con los "
        "medidos. Cuando el stock es extrapolación, se muestra separado de la medición. "
        "La precisión que falta es de **carga de datos**, no de cálculo: el día que se carguen los siete "
        "puntos de arriba, esta misma pantalla pasa de estimar a medir sin cambiar una línea de código."
    )


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
    _bloque_dinero(USR, cat, conectar, precios, fecha_precios, df_precios)
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
    _que_falta()
    st.divider()
    _cierre()
