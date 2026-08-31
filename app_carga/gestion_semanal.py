# -*- coding: utf-8 -*-
"""Gestión semanal — Producto × Sector (Centro de Planificación y Producción).

El hilo conductor de dirección, en una sola pantalla:

    Producto → Sector → Objetivo → Planificación → Producción → Desvío → Proyección

Todo se mide en TN sobre la MISMA grilla (producto × sector × semana ISO) y sale
de una única fuente, vw_gestion_semanal, para que no existan dos versiones del
mismo número. Los cuatro sectores de gestión son Reactores, Piletas, Bachas y
Exportación; el nombre de cada unidad de gestión es **Sector + Producto**
("Exportación AG-E"), nunca el booking ni el cliente.

Vistas:
  📊 Tablero    — Objetivo vs Real vs Proyectado vs Desvío, por sector y producto.
  🎯 Objetivos  — carga y cierre del plan de la semana.
  🔤 Nombres    — auditoría de denominaciones y normalización con un click.
  💲 Precios    — precios de insumos con vigencia (base del impacto económico).
"""

import datetime as _dt

import pandas as pd
import streamlit as st

ROLES_DIRECCION = ("SUPERVISOR", "ADMIN")

# Colores del semáforo de cumplimiento (mismo criterio en toda la sección).
_VERDE, _AMBAR, _ROJO, _GRIS = "#16a34a", "#f59e0b", "#dc2626", "#6b7280"


def _f(v, d=0.0):
    try:
        if v is None or pd.isna(v):
            return d
        return float(v)
    except Exception:
        return d


def _tn(v, dec=1):
    return ("{:,.%df}" % dec).format(_f(v))


def _semana_actual():
    _c = _dt.date.today().isocalendar()
    return int(_c[0]), int(_c[1])


def _rango_semana(anio, semana):
    """(lunes, domingo) de una semana ISO."""
    try:
        lun = _dt.date.fromisocalendar(int(anio), int(semana), 1)
    except Exception:
        lun = _dt.date.today() - _dt.timedelta(days=_dt.date.today().weekday())
    return lun, lun + _dt.timedelta(days=6)


def _dias_corridos(anio, semana):
    """Días de la semana ya transcurridos: 0 = todavía no empezó, 7 = cerrada."""
    lun, dom = _rango_semana(anio, semana)
    hoy = _dt.date.today()
    if hoy > dom:
        return 7
    if hoy < lun:
        return 0
    return (hoy - lun).days + 1


def _proyectar(real, dias):
    """Proyección al cierre de la semana al ritmo actual.

    Semana cerrada o no empezada: la proyección es el propio real (no hay nada
    que extrapolar). En curso: se lleva el ritmo de los días transcurridos a 7.
    Es una estimación lineal — sirve para anticipar el desvío, no es un pronóstico.
    """
    if dias <= 0 or dias >= 7:
        return _f(real)
    return _f(real) * 7.0 / float(dias)


def _color_avance(pct):
    if pct is None:
        return _GRIS
    if pct >= 95:
        return _VERDE
    if pct >= 80:
        return _AMBAR
    return _ROJO


def _datos(cat, anio, semana):
    df = cat("SELECT sector, sector_ui, sector_color, sector_orden, codigo_producto, "
             "nombre_gestion, tn_objetivo, tn_real, tn_desvio, pct_avance, tiene_objetivo, "
             "plan_cerrado, sin_producto, n_registros, nota "
             "FROM produccion.vw_gestion_semanal WHERE anio=%s AND semana=%s "
             "ORDER BY sector_orden NULLS LAST, sector, codigo_producto", (int(anio), int(semana)))
    if df is None:
        return pd.DataFrame()
    df = df.copy()
    for c in ("tn_objetivo", "tn_real", "tn_desvio", "pct_avance"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


# ------------------------------------------------------------------ 📊 tablero

def _tablero(USR, cat, anio, semana):
    df = _datos(cat, anio, semana)
    lun, dom = _rango_semana(anio, semana)
    dias = _dias_corridos(anio, semana)
    _estado = ("semana cerrada" if dias >= 7 else
               ("todavía no empezó" if dias <= 0 else "día %d de 7" % dias))
    st.caption("**Semana %d de %d** · %s al %s · %s. La proyección lleva el ritmo "
               "de los días transcurridos al cierre del domingo."
               % (int(semana), int(anio), lun.strftime("%d/%m"), dom.strftime("%d/%m"), _estado))

    if df.empty:
        st.info("No hay objetivos cargados ni producción registrada en esta semana. "
                "Cargá el plan en **🎯 Objetivos**.")
        return

    _val = df[~df["sin_producto"]]
    obj = float(_val["tn_objetivo"].sum())
    real = float(_val["tn_real"].sum())
    proy = _proyectar(real, dias)
    desv = proy - obj

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Objetivo", "%s TN" % _tn(obj))
    k2.metric("Real a hoy", "%s TN" % _tn(real),
              ("%.0f%% del objetivo" % (100.0 * real / obj)) if obj > 0 else None,
              delta_color="off")
    k3.metric("Proyectado al cierre", "%s TN" % _tn(proy),
              help="Real ÷ días transcurridos × 7. En una semana cerrada es el real.")
    k4.metric("Desvío proyectado", "%s%s TN" % ("+" if desv >= 0 else "", _tn(desv)),
              ("%.0f%% del objetivo" % (100.0 * desv / obj)) if obj > 0 else None,
              delta_color=("normal" if desv >= 0 else "inverse"))

    _sd = df[df["sin_producto"]]
    if not _sd.empty:
        st.warning("⚠️ **%s TN quedan fuera del análisis** porque no tienen producto "
                   "asignado (%d registro(s)). Están excluidas de los totales de arriba — "
                   "corregilas desde **🔤 Nombres**."
                   % (_tn(_sd["tn_real"].sum()), int(_sd["n_registros"].sum())))

    st.markdown("")
    for _sec in df["sector"].dropna().unique().tolist():
        _s = df[(df["sector"] == _sec) & (~df["sin_producto"])]
        if _s.empty:
            continue
        _nom = str(_s.iloc[0]["sector_ui"] or _sec)
        _clr = str(_s.iloc[0]["sector_color"] or "#334155")
        _o, _r = float(_s["tn_objetivo"].sum()), float(_s["tn_real"].sum())
        _p = _proyectar(_r, dias)
        _pct = (100.0 * _p / _o) if _o > 0 else None
        _cerr = bool(_s["plan_cerrado"].any())

        st.markdown(
            "<div style='border-left:6px solid %s;background:#f8fafc;border-radius:8px;"
            "padding:8px 14px;margin:10px 0 4px'>"
            "<span style='font-size:1.05rem;font-weight:900;color:#0f172a'>%s</span>"
            "<span style='color:#64748b;font-size:.85rem'> · objetivo %s TN · real %s TN · "
            "proyectado <b style='color:%s'>%s TN</b>%s</span></div>"
            % (_clr, _nom, _tn(_o), _tn(_r), _color_avance(_pct), _tn(_p),
               (" · <b>plan cerrado</b>" if _cerr else "")),
            unsafe_allow_html=True)

        _rows = []
        for _, r in _s.iterrows():
            _ro, _rr = _f(r["tn_objetivo"]), _f(r["tn_real"])
            _rp = _proyectar(_rr, dias)
            _rows.append({
                "Unidad de gestión": r["nombre_gestion"],
                "Objetivo (TN)": round(_ro, 1),
                "Real (TN)": round(_rr, 1),
                "Proyectado (TN)": round(_rp, 1),
                "Desvío (TN)": round(_rp - _ro, 1),
                "Avance": (min(1.0, _rp / _ro) if _ro > 0 else 0.0),
                "Estado": ("sin objetivo" if not bool(r["tiene_objetivo"])
                           else ("✅" if _ro > 0 and _rp >= _ro * 0.95
                                 else ("🟡" if _ro > 0 and _rp >= _ro * 0.8 else "🔴"))),
            })
        st.dataframe(
            pd.DataFrame(_rows), hide_index=True, use_container_width=True,
            column_config={
                "Objetivo (TN)": st.column_config.NumberColumn(format="%.1f"),
                "Real (TN)": st.column_config.NumberColumn(format="%.1f"),
                "Proyectado (TN)": st.column_config.NumberColumn(
                    format="%.1f", help="Al ritmo de los días ya transcurridos."),
                "Desvío (TN)": st.column_config.NumberColumn(
                    format="%.1f", help="Proyectado − Objetivo. Negativo = no se llega."),
                "Avance": st.column_config.ProgressColumn(
                    "Avance proyectado", format="%.0f%%", min_value=0.0, max_value=1.0),
            })

    _sin_obj = _val[~_val["tiene_objetivo"] & (_val["tn_real"] > 0)]
    if not _sin_obj.empty:
        st.info("ℹ️ **Producción sin objetivo planificado:** %s. Son %s TN que nadie "
                "planificó esta semana — cargales objetivo o revisá por qué se produjeron."
                % (", ".join(_sin_obj["nombre_gestion"].astype(str).tolist()),
                   _tn(_sin_obj["tn_real"].sum())))


# ------------------------------------------------------------------ 🎯 objetivos

def _objetivos(USR, cat, conectar, anio, semana):
    uid = int(USR.get("id_usuario") or 0)
    ss = st.session_state
    _nz = int(ss.get("gs_nonce_%d_%d" % (anio, semana)) or 0)

    _sec = cat("SELECT codigo, nombre_ui FROM produccion.dim_sector_gestion "
               "WHERE activo ORDER BY orden")
    _secs = _sec["codigo"].astype(str).tolist() if _sec is not None and not _sec.empty else []
    _sec_lbl = dict(zip(_sec["codigo"].astype(str), _sec["nombre_ui"].astype(str))) if _secs else {}
    _pr = cat("SELECT codigo_producto FROM produccion.dim_producto "
              "WHERE COALESCE(activo,true) ORDER BY codigo_producto")
    _prods = _pr["codigo_producto"].astype(str).str.strip().str.upper().tolist() \
        if _pr is not None and not _pr.empty else []

    cur = cat("SELECT sector, codigo_producto, tn_objetivo, nota, cerrado "
              "FROM produccion.fact_objetivo_semanal WHERE anio=%s AND semana=%s "
              "ORDER BY sector, codigo_producto", (int(anio), int(semana)))
    _base = pd.DataFrame({
        "Sector": (cur["sector"].astype(str) if cur is not None and not cur.empty
                   else pd.Series(dtype="object")),
        "Producto": (cur["codigo_producto"].astype(str) if cur is not None and not cur.empty
                     else pd.Series(dtype="object")),
        "TN objetivo": (pd.to_numeric(cur["tn_objetivo"], errors="coerce")
                        if cur is not None and not cur.empty else pd.Series(dtype="float64")),
        "Nota": (cur["nota"].fillna("").astype(str) if cur is not None and not cur.empty
                 else pd.Series(dtype="object")),
    })
    _cerrado = bool(cur["cerrado"].any()) if cur is not None and not cur.empty else False

    lun, dom = _rango_semana(anio, semana)
    st.caption("Plan de la **semana %d de %d** (%s al %s). Una fila por **unidad de "
               "gestión = Sector + Producto**. Cerrar el plan lo deja formalizado como "
               "el compromiso de la semana; se puede reabrir."
               % (int(semana), int(anio), lun.strftime("%d/%m"), dom.strftime("%d/%m")))
    if _cerrado:
        st.success("🔒 El plan de esta semana está **cerrado**.")

    ed = st.data_editor(
        _base, hide_index=True, use_container_width=True, num_rows="dynamic",
        key="gs_obj_%d_%d_%d" % (anio, semana, _nz),
        column_config={
            "Sector": st.column_config.SelectboxColumn(
                options=_secs, required=True,
                help=" · ".join("%s = %s" % (k, v) for k, v in _sec_lbl.items())),
            "Producto": st.column_config.SelectboxColumn(options=_prods, required=True),
            "TN objetivo": st.column_config.NumberColumn(format="%.1f", min_value=0.0),
            "Nota": st.column_config.TextColumn(help="Por qué este número (opcional)."),
        })

    c1, c2, c3 = st.columns([1.2, 1.2, 2.2])
    if c1.button("💾 Guardar objetivos", type="primary", key="gs_obj_save_%d_%d" % (anio, semana)):
        _fil = []
        for _i in range(len(ed)):
            _s = str(ed.iloc[_i]["Sector"] or "").strip().upper()
            _p = str(ed.iloc[_i]["Producto"] or "").strip().upper()
            if not _s or not _p:
                continue
            _fil.append((_s, _p, round(_f(ed.iloc[_i]["TN objetivo"]), 2),
                         (str(ed.iloc[_i]["Nota"] or "").strip() or None)))
        _dups = [x for x in set((a, b) for a, b, _c, _d in _fil)
                 if [(a2, b2) for a2, b2, _c, _d in _fil].count(x) > 1]
        if _dups:
            st.error("Hay filas repetidas para la misma unidad de gestión: %s. "
                     "Dejá una sola por Sector + Producto."
                     % ", ".join("%s / %s" % d for d in _dups))
        else:
            try:
                with conectar(uid) as (conn, audit):
                    with conn.cursor() as cur2:
                        cur2.execute("DELETE FROM produccion.fact_objetivo_semanal "
                                     "WHERE anio=%s AND semana=%s", (int(anio), int(semana)))
                        for _s, _p, _t, _n in _fil:
                            cur2.execute(
                                "INSERT INTO produccion.fact_objetivo_semanal "
                                "(anio, semana, sector, codigo_producto, tn_objetivo, nota, "
                                " cerrado, actualizado_por) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                                (int(anio), int(semana), _s, _p, _t, _n, _cerrado,
                                 (USR.get("nombre") or str(uid))))
                    audit.log("U", "fact_objetivo_semanal", int(anio) * 100 + int(semana),
                              {"semana": "%d-S%d" % (anio, semana), "filas": len(_fil)})
                cat.clear()
                ss["gs_nonce_%d_%d" % (anio, semana)] = _nz + 1
                st.success("✅ %d objetivo(s) guardados." % len(_fil))
                st.rerun()
            except Exception as e:
                st.error("No se pudo guardar: %s" % e)

    _lbl = "🔓 Reabrir el plan" if _cerrado else "🔒 Cerrar el plan de la semana"
    if c2.button(_lbl, key="gs_obj_cerrar_%d_%d" % (anio, semana)):
        try:
            with conectar(uid) as (conn, audit):
                with conn.cursor() as cur2:
                    cur2.execute("UPDATE produccion.fact_objetivo_semanal "
                                 "SET cerrado=%s, cerrado_en=CASE WHEN %s THEN now() END, "
                                 "    actualizado_por=%s "
                                 "WHERE anio=%s AND semana=%s",
                                 (not _cerrado, not _cerrado,
                                  (USR.get("nombre") or str(uid)), int(anio), int(semana)))
                audit.log("U", "fact_objetivo_semanal", int(anio) * 100 + int(semana),
                          {"cerrado": not _cerrado})
            cat.clear()
            st.rerun()
        except Exception as e:
            st.error("No se pudo cambiar el estado: %s" % e)

    with c3.expander("📋 Copiar el plan de otra semana", expanded=False):
        _wo = st.number_input("Semana de origen", min_value=1, max_value=53,
                              value=max(1, int(semana) - 1), step=1,
                              key="gs_copy_w_%d_%d" % (anio, semana))
        if st.button("Copiar acá", key="gs_copy_go_%d_%d" % (anio, semana)):
            try:
                with conectar(uid) as (conn, audit):
                    with conn.cursor() as cur2:
                        cur2.execute(
                            "INSERT INTO produccion.fact_objetivo_semanal "
                            "(anio, semana, sector, codigo_producto, tn_objetivo, nota, "
                            " actualizado_por) "
                            "SELECT %s, %s, sector, codigo_producto, tn_objetivo, "
                            "       'Copiado de la semana '||semana, %s "
                            "FROM produccion.fact_objetivo_semanal "
                            "WHERE anio=%s AND semana=%s "
                            "ON CONFLICT (anio, semana, sector, codigo_producto) DO UPDATE "
                            "SET tn_objetivo=EXCLUDED.tn_objetivo, actualizado_en=now()",
                            (int(anio), int(semana), (USR.get("nombre") or str(uid)),
                             int(anio), int(_wo)))
                    audit.log("I", "fact_objetivo_semanal", int(anio) * 100 + int(semana),
                              {"copiado_de": int(_wo)})
                cat.clear()
                st.success("✅ Plan copiado de la semana %d." % int(_wo))
                st.rerun()
            except Exception as e:
                st.error("No se pudo copiar: %s" % e)


# ------------------------------------------------------------------ 🔤 nombres

def _nombres(USR, cat, conectar):
    uid = int(USR.get("id_usuario") or 0)
    st.caption("Todo lo que hoy **no se puede asociar a un Producto y un Sector**, o está "
               "cargado con nombres distintos para la misma cosa. Cada fila rompe (o "
               "ensucia) el análisis: mientras esté acá, esos kg no cuentan bien en el "
               "tablero. El booking de cada despacho (FLEX…, ISOS…) NO es un problema: "
               "es el identificador real de esa carga.")
    aud = cat("SELECT entidad, id, nombre_actual, nombre_propuesto, problema, severidad "
              "FROM produccion.vw_auditoria_nombres "
              "ORDER BY CASE severidad WHEN 'alta' THEN 1 WHEN 'media' THEN 2 ELSE 3 END, "
              "entidad, nombre_actual")
    if aud is None or aud.empty:
        st.success("✅ Todos los nombres respetan el criterio Producto × Sector.")
        return

    _n = {s: int((aud["severidad"] == s).sum()) for s in ("alta", "media", "baja")}
    k1, k2, k3 = st.columns(3)
    k1.metric("🔴 Alta", _n["alta"], help="Rompen el análisis por Producto × Sector.")
    k2.metric("🟡 Media", _n["media"], help="Mismo valor escrito de varias formas.")
    k3.metric("⚪ Baja", _n["baja"], help="Conviene corregir, no rompe nada.")

    for _e in aud["entidad"].unique().tolist():
        _a = aud[aud["entidad"] == _e]
        with st.expander("%s — %d caso(s)" % (_e, len(_a)),
                         expanded=(str(_a.iloc[0]["severidad"]) == "alta")):
            st.dataframe(
                _a[["nombre_actual", "nombre_propuesto", "problema"]].rename(columns={
                    "nombre_actual": "Nombre actual", "nombre_propuesto": "Debería llamarse",
                    "problema": "Problema"}),
                hide_index=True, use_container_width=True)

    st.markdown("---")
    st.markdown("**Arreglos automáticos**")
    c1, _c2 = st.columns([1.4, 2.0])

    _nn = int(aud["entidad"].isin(["Destino", "Cliente"]).sum())
    if c1.button("🔠 Unificar %d destino(s)/cliente(s) repetidos" % _nn,
                 disabled=(_nn == 0), use_container_width=True, key="gs_fix_txt",
                 help="Deja todos en MAYÚSCULAS y sin espacios sobrantes, así el mismo "
                      "cliente deja de contarse dos veces."):
        try:
            with conectar(uid) as (conn, audit):
                with conn.cursor() as cur2:
                    cur2.execute("UPDATE produccion.fact_despacho "
                                 "SET destino = upper(btrim(destino)) "
                                 "WHERE destino IS DISTINCT FROM upper(btrim(destino))")
                    _c1 = cur2.rowcount
                    cur2.execute("UPDATE produccion.fact_despacho "
                                 "SET cliente = upper(btrim(cliente)) "
                                 "WHERE cliente IS DISTINCT FROM upper(btrim(cliente))")
                    _c2 = cur2.rowcount
                audit.log("U", "fact_despacho", 0,
                          {"auditoria_nombres": "normaliza destino/cliente",
                           "destinos": _c1, "clientes": _c2})
            cat.clear()
            st.success("✅ %d destino(s) y %d cliente(s) normalizados." % (_c1, _c2))
            st.rerun()
        except Exception as e:
            st.error("No se pudo normalizar: %s" % e)

    st.caption("Los registros **sin producto** y las **reacciones** con identificador raro "
               "se corrigen a mano: el sistema no puede adivinar el producto. Recuperación "
               "AG para los tickets, y ✏️ Edición rápida para las reacciones.")

    st.markdown("---")
    with st.expander("📐 Criterio de nombres de sección — proceso → producto final",
                     expanded=False):
        st.markdown(
            "Una sección **no se llama por el proceso químico ni por el movimiento "
            "logístico, sino por lo que produce** — y en genérico, porque se pueden "
            "desgomar varios productos y exportar varios productos. El producto concreto "
            "(AG-E, AFE-S, ARE-B…) se elige **adentro** de la sección, nunca en el título.\n\n"
            "| Antes | Ahora | Por qué |\n|---|---|---|\n"
            "| Despachos | **Exportación** | Es el sector, no el movimiento. Admite "
            "cualquier producto de exportación. |\n"
            "| Desgomado acuoso | **Producción AFE** | El desgomado es el proceso; lo que "
            "importa para gestión es el AFE que sale. |\n"
            "| Decantación ARE | **Producción ARE** | Ídem: la decantación es una etapa, "
            "el producto final es el ARE. |\n"
            "| Cargar nueva reacción | **Nueva producción** | La reacción es el medio; se "
            "gestiona la producción. |\n"
            "| Gestión / Administración de reacciones | **… de producción** | Consistencia "
            "con lo anterior. |\n\n"
            "Los códigos internos (`DESGOMADO_ACUOSO`, `PRODUCCION_ARE`) **no cambian**: "
            "son claves de la base, no títulos. Y el nombre de cada **despacho individual** "
            "sigue siendo su booking (FLEX…, ISOS…), que es su identificador real.")


# ------------------------------------------------------------------ 💲 precios

def _precios(USR, cat, conectar):
    uid = int(USR.get("id_usuario") or 0)
    ss = st.session_state
    _nz = int(ss.get("gs_prec_nonce") or 0)
    st.caption("Precio de cada insumo con **vigencia**: es la base para pasar el desvío de "
               "consumo (esperado vs real) a **impacto económico** y armar la matriz de "
               "costos por producto. Al cambiar un precio se cierra el anterior y se abre "
               "uno nuevo, así el histórico no se pisa.")

    _ins = cat("SELECT DISTINCT codigo_insumo FROM ("
               "  SELECT codigo_insumo FROM produccion.dic_consumo_proceso "
               "  UNION SELECT codigo_insumo FROM produccion.dic_consumo_sector "
               "  UNION SELECT codigo_insumo FROM produccion.dim_insumo_precio) x "
               "WHERE COALESCE(btrim(codigo_insumo),'') <> '' ORDER BY 1")
    _lista = _ins["codigo_insumo"].astype(str).tolist() if _ins is not None and not _ins.empty else []

    vig = cat("SELECT codigo_insumo, unidad, precio, moneda, vigencia_desde "
              "FROM produccion.vw_insumo_precio_vigente ORDER BY codigo_insumo")
    if vig is not None and not vig.empty:
        st.markdown("**Precios vigentes hoy**")
        st.dataframe(vig.rename(columns={
            "codigo_insumo": "Insumo", "unidad": "Unidad", "precio": "Precio",
            "moneda": "Moneda", "vigencia_desde": "Vigente desde"}),
            hide_index=True, use_container_width=True,
            column_config={"Precio": st.column_config.NumberColumn(format="%.2f"),
                           "Vigente desde": st.column_config.DateColumn(format="DD/MM/YYYY")})
    else:
        st.info("Todavía no hay precios cargados. Cargá el primero acá abajo.")

    st.markdown("**Cargar o actualizar un precio**")
    c1, c2, c3, c4, c5 = st.columns([1.5, 0.8, 1.0, 0.9, 1.0])
    _cod = c1.selectbox("Insumo", (_lista + ["➕ otro…"]) if _lista else ["➕ otro…"],
                        key="gs_prec_cod_%d" % _nz)
    if str(_cod).startswith("➕"):
        _cod = c1.text_input("Código del insumo nuevo", key="gs_prec_new_%d" % _nz).strip().upper()
    _uni = c2.selectbox("Unidad", ["KG", "L", "UN"], key="gs_prec_uni_%d" % _nz)
    _pre = c3.number_input("Precio", min_value=0.0, step=100.0, format="%.2f",
                           key="gs_prec_val_%d" % _nz)
    _mon = c4.selectbox("Moneda", ["ARS", "USD"], key="gs_prec_mon_%d" % _nz)
    _des = c5.date_input("Vigente desde", value=_dt.date.today(), format="DD/MM/YYYY",
                         key="gs_prec_des_%d" % _nz)
    if st.button("💾 Guardar precio", type="primary", key="gs_prec_go_%d" % _nz):
        if not _cod or _pre <= 0:
            st.warning("Elegí el insumo y poné un precio mayor a cero.")
        else:
            try:
                with conectar(uid) as (conn, audit):
                    with conn.cursor() as cur2:
                        cur2.execute(
                            "UPDATE produccion.dim_insumo_precio "
                            "SET vigencia_hasta = %s - 1 "
                            "WHERE codigo_insumo=%s AND vigencia_hasta IS NULL "
                            "  AND vigencia_desde < %s", (_des, _cod, _des))
                        cur2.execute(
                            "INSERT INTO produccion.dim_insumo_precio "
                            "(codigo_insumo, unidad, precio, moneda, vigencia_desde, "
                            " actualizado_por) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id_precio",
                            (_cod, _uni, float(_pre), _mon, _des,
                             (USR.get("nombre") or str(uid))))
                        _new = cur2.fetchone()[0]
                    audit.log("I", "dim_insumo_precio", int(_new),
                              {"insumo": _cod, "precio": float(_pre), "moneda": _mon})
                cat.clear()
                ss["gs_prec_nonce"] = _nz + 1
                st.success("✅ Precio de %s guardado." % _cod)
                st.rerun()
            except Exception as e:
                st.error("No se pudo guardar: %s" % e)

    hist = cat("SELECT codigo_insumo, precio, moneda, unidad, vigencia_desde, vigencia_hasta, "
               "actualizado_por FROM produccion.dim_insumo_precio "
               "ORDER BY codigo_insumo, vigencia_desde DESC LIMIT 200")
    if hist is not None and not hist.empty:
        with st.expander("🕘 Histórico de precios", expanded=False):
            st.dataframe(hist.rename(columns={
                "codigo_insumo": "Insumo", "precio": "Precio", "moneda": "Moneda",
                "unidad": "Unidad", "vigencia_desde": "Desde", "vigencia_hasta": "Hasta",
                "actualizado_por": "Cargó"}), hide_index=True, use_container_width=True)


# ------------------------------------------------------------------ render

def render(USR, cat, conectar, contexto="PLANIFICACION"):
    st.markdown(
        "<div style='background:linear-gradient(90deg,#0f172a,#1d4ed8);border-radius:14px;"
        "padding:16px 20px;margin:0 0 12px'>"
        "<div style='color:#fff;font-size:1.4rem;font-weight:900'>📈 Gestión semanal · "
        "Producto × Sector</div>"
        "<div style='color:#dbeafe;font-size:.88rem;margin-top:3px'>Objetivo vs Producido "
        "vs Proyectado, con una sola fuente de información para toda la planta.</div></div>",
        unsafe_allow_html=True)

    _a0, _s0 = _semana_actual()
    ss = st.session_state
    ss.setdefault("gs_anio", _a0)
    ss.setdefault("gs_sem", _s0)

    n1, n2, n3, n4, n5 = st.columns([0.6, 0.9, 0.8, 0.6, 2.1])
    if n1.button("←", key="gs_prev", help="Semana anterior", use_container_width=True):
        _s = int(ss["gs_sem"]) - 1
        ss["gs_anio"], ss["gs_sem"] = (int(ss["gs_anio"]) - 1, 52) if _s < 1 else (int(ss["gs_anio"]), _s)
        st.rerun()
    _sem = n2.number_input("Semana", min_value=1, max_value=53, step=1,
                           value=int(ss["gs_sem"]), key="gs_sem_in")
    _anio = n3.number_input("Año", min_value=2024, max_value=2100, step=1,
                            value=int(ss["gs_anio"]), key="gs_anio_in")
    if n4.button("→", key="gs_next", help="Semana siguiente", use_container_width=True):
        _s = int(ss["gs_sem"]) + 1
        ss["gs_anio"], ss["gs_sem"] = (int(ss["gs_anio"]) + 1, 1) if _s > 52 else (int(ss["gs_anio"]), _s)
        st.rerun()
    ss["gs_sem"], ss["gs_anio"] = int(_sem), int(_anio)
    n5.write("")
    if (int(_anio), int(_sem)) != (_a0, _s0):
        if n5.button("↩️ Volver a la semana en curso (S%d)" % _s0, key="gs_hoy"):
            ss["gs_anio"], ss["gs_sem"] = _a0, _s0
            st.rerun()

    _dir = (USR.get("rol") in ROLES_DIRECCION
            or "PLANIFICACION" in (USR.get("secciones_app") or []))
    _opts = ["📊 Tablero"]
    if _dir:
        _opts += ["🎯 Objetivos", "🔤 Nombres", "💲 Precios"]
    try:
        _v = st.segmented_control("Vista", _opts, default=_opts[0],
                                  key="gs_view_%s" % contexto, label_visibility="collapsed")
    except Exception:
        _v = st.radio("Vista", _opts, horizontal=True, key="gs_view_rd_%s" % contexto)
    _v = _v or _opts[0]
    st.write("")

    if _v.startswith("📊"):
        _tablero(USR, cat, int(_anio), int(_sem))
    elif _v.startswith("🎯"):
        _objetivos(USR, cat, conectar, int(_anio), int(_sem))
    elif _v.startswith("🔤"):
        _nombres(USR, cat, conectar)
    else:
        _precios(USR, cat, conectar)
