"""Circuito DESGOMADO_ACUOSO (espejo de decantacion.py para ARE).

Circuito y validaciones (3 actores):
  REACCIÓN  → (evaluación interna: SOLO temperatura; ≥85 °C corta sola por regla) → REPOSO
  REPOSO    → Centro de Planificación decide: transferir a CÓNICO-60 o quedar en el reactor.
              En ambos casos reposa 12 h (DESGOM_REPOSO_HORAS). La decantación se hace
              en el recipiente que lo tiene (Cónico 60 o el propio reactor).
  DECANTACIÓN → Producción purga y decanta; lleva muestra a Laboratorio.
              Laboratorio carga agua + sedimentos: OK si (agua+sed) < 1.5 % (DESGOM_AGUA_SED_MAX_PCT).
  LISTO      → Con lab OK, Centro de Planificación define el destino final (tanque de acopio).
  FINALIZADO → Producción confirma y ademas VALIDA que el recipiente quedó SIN líquido
              (por canilla o por visión). Recién ahí se generan los movimientos (AFE-S → destino)
              y la producción pasa a FINALIZADO.

Funciones (mismas firmas que decantacion.py):
  planificacion(USR, cat, conectar)          -> Centro de Planificación
  produccion(USR, cat, conectar, id_batch)   -> Producción en planta (operario)
  laboratorio(USR, cat, conectar)            -> Laboratorio
"""
import json
import pandas as pd
import streamlit as st

CONICO60_ID = 82                 # tanque "Cónico 60"
AFE_S_ID = 1                     # producto AFE-S (final del desgomado)
FONDO_TK_ID = 56                 # producto Fondo de tanque (subproducto)
DENS_AFE = 0.92
TEMP_CORTE_DEF = 85.0
REPOSO_HS_DEF = 12.0
AYS_MAX_DEF = 1.5                # agua + sedimentos máx (%)


def _cond(cat, clave, default):
    try:
        d = cat("SELECT valor FROM produccion.dic_condicion_produccion WHERE clave=%s", (clave,))
        if d is not None and not d.empty and pd.notna(d.iloc[0]["valor"]):
            return float(d.iloc[0]["valor"])
    except Exception:
        pass
    return default


def _params(b):
    p = b.get("parametros_proceso") or {}
    if isinstance(p, str):
        try:
            p = json.loads(p)
        except Exception:
            p = {}
    return p or {}


def _batches(cat):
    return cat(
        "SELECT b.id_batch, b.identificador_unidad AS ident, b.estado, b.etapa_actual, "
        "       bu.nombre_ui AS reactor, "
        "       b.desg_reposo_modo, b.desg_id_tanque_reposo, b.desg_reposo_ini_ts, "
        "       b.desg_agua_sed_pct, b.desg_lab_ok, b.desg_id_tanque_destino, "
        "       b.desg_recipiente_vacio, b.desg_confirmada_ts, b.id_producto_buscado, b.desg_incidente, b.desg_incidente_motivo, "
        "       b.parametros_proceso, b.litros_inicial, b.kg_inicial "
        "FROM produccion.fact_batch_proceso b "
        "LEFT JOIN produccion.dim_bien_uso bu ON bu.id_bien_uso=b.id_bien_uso "
        "WHERE b.tipo_proceso='DESGOMADO_ACUOSO' AND b.estado IN ('REPOSO','DECANTACION') "
        "  AND COALESCE(b.anulado,false)=false AND b.desg_confirmada_ts IS NULL "
        "ORDER BY b.creado_en DESC")


def _batch_one(cat, id_batch):
    df = cat(
        "SELECT b.id_batch, b.identificador_unidad AS ident, b.estado, b.etapa_actual, "
        "       bu.nombre_ui AS reactor, "
        "       b.desg_reposo_modo, b.desg_id_tanque_reposo, b.desg_reposo_ini_ts, "
        "       b.desg_agua_sed_pct, b.desg_lab_ok, b.desg_id_tanque_destino, "
        "       b.desg_recipiente_vacio, b.desg_confirmada_ts, b.id_producto_buscado, b.desg_incidente, b.desg_incidente_motivo, "
        "       b.parametros_proceso, b.litros_inicial, b.kg_inicial "
        "FROM produccion.fact_batch_proceso b "
        "LEFT JOIN produccion.dim_bien_uso bu ON bu.id_bien_uso=b.id_bien_uso "
        "WHERE b.id_batch=%s", (int(id_batch),))
    return df.iloc[0] if (df is not None and not df.empty) else None


def _reposo_eta(cat, b):
    ini = b.get("desg_reposo_ini_ts")
    if pd.isna(ini) or ini is None:
        return None
    hs = _cond(cat, "DESGOM_REPOSO_HORAS", REPOSO_HS_DEF)
    try:
        return pd.to_datetime(ini) + pd.Timedelta(hours=float(hs))
    except Exception:
        return None


def _recipiente_nombre(cat, b):
    """Recipiente donde se hace la decantación (Cónico 60 o el reactor)."""
    modo = b.get("desg_reposo_modo")
    if modo == "CONICO60":
        return "Cónico 60"
    if modo == "REACTOR":
        return b.get("reactor") or "el reactor"
    return "el recipiente"


def _sel_batch(cat, key):
    df = _batches(cat)
    if df is None or df.empty:
        st.info("No hay desgomados en reposo/decantación.")
        return None, None
    opt = df.apply(lambda r: f"#{r['id_batch']} · {r['ident'] or '—'} · {r['reactor'] or '—'} · {r['estado']}", axis=1).tolist()
    s = st.selectbox("Desgomado", opt, key=key)
    return df.iloc[opt.index(s)], df


def _cabecera(cat, b):
    eta = _reposo_eta(cat, b)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Estado", b["estado"])
    c2.metric("Recipiente", _recipiente_nombre(cat, b))
    if eta is not None:
        _now = pd.Timestamp.now(tz=getattr(eta, "tz", None))
        _rest = (eta - _now).total_seconds() / 3600.0
        c3.metric("Fin de reposo", eta.strftime("%d/%m %H:%M"),
                  ("listo" if _rest <= 0 else f"en {_rest:.1f} h"))
    else:
        c3.metric("Fin de reposo", "—")
    _ays = b.get("desg_agua_sed_pct")
    c4.metric("Agua+sed. (lab)", f"{float(_ays):.2f}%" if pd.notna(_ays) else "—")


def _hist_lab(cat, id_batch):
    _h = cat("SELECT to_char(ts,'DD/MM HH24:MI') AS \"Hora\", agua_pct AS \"Agua %%\", "
             "sedimentos_pct AS \"Sedim. %%\", suma_pct AS \"Agua+Sed %%\", "
             "CASE WHEN ok THEN 'OK ✅' ELSE 'Seguir' END AS \"Resultado\", "
             "COALESCE(observacion,'') AS \"Obs\" "
             "FROM produccion.fact_desg_decant WHERE id_batch=%s ORDER BY ts DESC", (int(id_batch),))
    if _h is not None and not _h.empty:
        st.caption("Historial de muestras de decantación (laboratorio, con horario):")
        st.dataframe(_h, use_container_width=True, hide_index=True)


def _pf_code(cat, b):
    """Código del producto final del batch (AFE-S para AFE-SG, AFE-G para AFE-G). Fallback AFE-S."""
    try:
        _idp = b.get("id_producto_buscado")
        if _idp is not None and pd.notna(_idp):
            r = cat("SELECT codigo_producto FROM produccion.dim_producto WHERE id_producto=%s", (int(_idp),))
            if r is not None and not r.empty:
                return str(r.iloc[0]["codigo_producto"])
    except Exception:
        pass
    return "AFE-S"


# ============================================================ PLANIFICACIÓN
def planificacion(USR, cat, conectar):
    st.subheader("🫗 Desgomado acuoso — decisiones (dirección)")
    st.caption("La reacción cortó al llegar a 85 °C y pasó a **reposo**. Decidí el reposo "
               "(transferir a **Cónico 60** o dejarlo en el **reactor**) y, cuando laboratorio "
               "confirme agua+sedimentos < 1,5 %, el **destino final** del producto.")
    b, _ = _sel_batch(cat, "desg_plan_sel")
    if b is None:
        return
    _cabecera(cat, b)
    uid = int(USR["id_usuario"])
    _pf = _pf_code(cat, b)   # AFE-S (de AFE-SG) o AFE-G (de AFE-G): el desgomado de AFE-G termina en AFE-G
    ays_max = _cond(cat, "DESGOM_AGUA_SED_MAX_PCT", AYS_MAX_DEF)
    reposo_hs = _cond(cat, "DESGOM_REPOSO_HORAS", REPOSO_HS_DEF)

    # ---- 1) Decisión de reposo (si todavía no se decidió) ----
    st.markdown("##### 1 · Reposo")
    if not b["desg_reposo_modo"]:
        st.info(f"Elegí dónde reposa **{reposo_hs:.0f} h**. La decantación se hará en ese mismo recipiente.")
        modo = st.radio("¿Dónde reposa?",
                        ["🛢️ Transferir a Cónico 60", "⚗️ Queda en el reactor"],
                        key="desg_modo")
        if st.button("💾 Confirmar reposo (arranca el conteo de 12 h)", type="primary", key="desg_modo_ok"):
            es_conico = modo.startswith("🛢️")
            try:
                with conectar(uid) as (conn, audit):
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE produccion.fact_batch_proceso "
                            "SET desg_reposo_modo=%s, desg_id_tanque_reposo=%s, desg_reposo_ini_ts=now(), "
                            "    id_usuario_estado=%s, motivo_estado=%s "
                            "WHERE id_batch=%s",
                            ("CONICO60" if es_conico else "REACTOR",
                             (CONICO60_ID if es_conico else None), uid,
                             ("Reposo en Cónico 60" if es_conico else "Reposo en el reactor"),
                             int(b["id_batch"])))
                    audit.log("U", "fact_batch_proceso", int(b["id_batch"]),
                              {"desg_reposo_modo": "CONICO60" if es_conico else "REACTOR"})
                st.success("Reposo confirmado. Cuando pasen las 12 h, producción arranca la decantación.")
                cat.clear(); st.rerun()
            except Exception as e:
                st.exception(e)
    else:
        eta = _reposo_eta(cat, b)
        _txt = f"en el **{_recipiente_nombre(cat, b)}**"
        if eta is not None:
            _now = pd.Timestamp.now(tz=getattr(eta, "tz", None))
            _rest = (eta - _now).total_seconds() / 3600.0
            if _rest > 0:
                st.info(f"🕐 Reposando {_txt}. Termina **{eta.strftime('%d/%m %H:%M')}** (en {_rest:.1f} h).")
            else:
                st.success(f"✅ Reposo {_txt} cumplido ({eta.strftime('%d/%m %H:%M')}). Producción puede decantar.")
        else:
            st.info(f"Reposando {_txt}.")

    # ---- 2) Estado de laboratorio (agua+sed) ----
    st.markdown("##### 2 · Laboratorio (decantación)")
    _ays = b["desg_agua_sed_pct"]
    if pd.isna(_ays) or _ays is None:
        st.caption("Laboratorio todavía no cargó agua+sedimentos de la decantación.")
    elif bool(b["desg_lab_ok"]):
        st.success(f"✅ Agua+sedimentos **{float(_ays):.2f}% (< {ays_max:g}%)** → apto para definir destino.")
    else:
        st.warning(f"🔴 Agua+sedimentos **{float(_ays):.2f}% (≥ {ays_max:g}%)** → seguir decantando.")

    # ---- 3) Destino final (solo con lab OK) ----
    st.markdown(f"##### 3 · Destino final del {_pf}")
    if not bool(b["desg_lab_ok"]):
        st.info("Disponible cuando laboratorio confirme agua+sedimentos < 1,5 %.")
        return
    _codes = ["AFE-S", "AFE-SG"] if _pf == "AFE-S" else [_pf]
    _sql_ft = ("SELECT t.id_tanque, t.nombre, t.codigo, t.sector, "
               "       COALESCE(s.litros_actual,0) lt, COALESCE(t.capacidad_litros,0) cap "
               "FROM produccion.dim_tanque t "
               "LEFT JOIN produccion.vw_tanque_panel s ON s.id_tanque=t.id_tanque "
               "WHERE COALESCE(t.activo,true) AND t.id_tanque IN ({}) "
               "ORDER BY t.nombre")
    ft = cat(_sql_ft.format(
        "SELECT pp.id_tanque FROM produccion.dim_tanque_producto_permitido pp "
        "JOIN produccion.dim_producto p ON p.id_producto=pp.id_producto "
        "WHERE p.codigo_producto = ANY(%s)"), (_codes,))
    if ft is None or ft.empty:   # sin 'permitido' cargado: cae a los tanques habilitados del maestro
        ft = cat(_sql_ft.format(
            "SELECT tp.id_tanque FROM produccion.dim_tanque_producto tp "
            "JOIN produccion.dim_producto p2 ON p2.id_producto=tp.id_producto "
            "WHERE p2.codigo_producto = ANY(%s)"), (_codes,))
    if ft is None or ft.empty:
        st.warning(f"No hay tanques que admitan {_pf}. Cargá el producto permitido en el tanque o elegí manualmente en Tanques.")
        return
    fop = ft.apply(lambda r: f"{r['nombre']} · {r['sector'] or ''} · {float(r['lt']):,.0f}/{float(r['cap']):,.0f} L", axis=1).tolist()
    _curf = b["desg_id_tanque_destino"]
    _ixf = next((i for i, (_, r) in enumerate(ft.iterrows())
                 if int(r["id_tanque"]) == (int(_curf) if pd.notna(_curf) else -1)), 0)
    fsel = st.selectbox(f"Tanque destino del {_pf}", fop, index=_ixf, key="desg_dest_tk")
    dest_fin = int(ft.iloc[fop.index(fsel)]["id_tanque"])
    if st.button("💾 Guardar destino final", type="primary", use_container_width=True, key="desg_save_dest"):
        try:
            with conectar(uid) as (conn, audit):
                with conn.cursor() as cur:
                    cur.execute("UPDATE produccion.fact_batch_proceso SET desg_id_tanque_destino=%s WHERE id_batch=%s",
                                (dest_fin, int(b["id_batch"])))
                audit.log("U", "fact_batch_proceso", int(b["id_batch"]), {"desg_destino": dest_fin})
            st.success("Destino guardado. Producción confirma y valida el recipiente vacío.")
            cat.clear(); st.rerun()
        except Exception as e:
            st.exception(e)


# ============================================================ PRODUCCIÓN
def produccion(USR, cat, conectar, id_batch=None):
    st.header("🫗 Desgomado — producción en planta")
    if id_batch is not None:
        b = _batch_one(cat, int(id_batch))
        if b is None:
            st.info("No se encontró el desgomado.")
            return
    else:
        b, _ = _sel_batch(cat, "desg_prod_sel")
        if b is None:
            return
    _cabecera(cat, b)
    uid = int(USR["id_usuario"])
    _pf = _pf_code(cat, b)   # producto final real del batch (AFE-S o AFE-G)
    ays_max = _cond(cat, "DESGOM_AGUA_SED_MAX_PCT", AYS_MAX_DEF)

    # -------- REPOSO: esperar decisión + fin de reposo, luego arrancar decantación --------
    if b["estado"] == "REPOSO":
        if not b["desg_reposo_modo"]:
            st.info("⏳ Esperando que **Centro de Planificación** decida el reposo "
                    "(Cónico 60 o queda en el reactor).")
            return
        eta = _reposo_eta(cat, b)
        _txt = _recipiente_nombre(cat, b)
        if eta is not None:
            _now = pd.Timestamp.now(tz=getattr(eta, "tz", None))
            _rest = (eta - _now).total_seconds() / 3600.0
            if _rest > 0:
                st.info(f"🕐 Reposando en **{_txt}** hasta **{eta.strftime('%d/%m %H:%M')}** (faltan {_rest:.1f} h).")
                st.caption("Cuando termine el reposo, vas a poder arrancar la purga y decantación.")
                return
        st.success(f"✅ Reposo cumplido en **{_txt}**. Podés arrancar la purga y decantación.")
        if st.button("▶️ Iniciar purga y decantación", type="primary", key="desg_to_decant"):
            try:
                with conectar(uid) as (conn, audit):
                    with conn.cursor() as cur:
                        cur.execute("UPDATE produccion.fact_etapa_evento SET fin_ts=now() "
                                    "WHERE id_batch=%s AND fin_ts IS NULL", (int(b["id_batch"]),))
                        cur.execute("INSERT INTO produccion.fact_etapa_evento (id_batch,etapa,inicio_ts,id_usuario) "
                                    "VALUES (%s,'DECANTACION',now(),%s)", (int(b["id_batch"]), uid))
                        cur.execute("UPDATE produccion.fact_batch_proceso SET estado='DECANTACION', "
                                    "etapa_actual='DECANTACION', id_usuario_estado=%s, "
                                    "motivo_estado='Inicio de purga/decantación' WHERE id_batch=%s",
                                    (uid, int(b["id_batch"])))
                    audit.log("U", "fact_batch_proceso", int(b["id_batch"]), {"estado": "DECANTACION"})
                cat.clear(); st.rerun()
            except Exception as e:
                st.exception(e)
        return

    # -------- DECANTACIÓN --------
    st.markdown("##### 🧪 Decantación")
    st.caption("Purgá y decantá hasta que salga **libre de goma, agua y sedimentos**. Llevá muestra a "
               f"laboratorio: corta cuando **agua+sedimentos < {ays_max:g}%**.")
    if st.button("📤 Enviar muestra a laboratorio", key="desg_envio_lab"):
        st.success("Muestra marcada para laboratorio. La ves en Laboratorio → Producciones en marcha (Desgomado).")

    _ays = b["desg_agua_sed_pct"]
    if pd.isna(_ays) or _ays is None:
        st.caption("Laboratorio todavía no cargó agua+sedimentos.")
    elif bool(b["desg_lab_ok"]):
        st.success(f"✅ Última muestra **{float(_ays):.2f}% (< {ays_max:g}%)** → apto. Falta que dirección defina el destino.")
    else:
        st.warning(f"🔴 Última muestra **{float(_ays):.2f}% (≥ {ays_max:g}%)** → seguí decantando.")
    _hist_lab(cat, int(b["id_batch"]))

    st.divider()
    st.markdown("##### ✅ Confirmar y enviar a destino")
    if not bool(b["desg_lab_ok"]):
        st.info("Disponible cuando laboratorio confirme agua+sedimentos < 1,5 %.")
        return
    dest = b["desg_id_tanque_destino"]
    if pd.isna(dest) or dest is None:
        st.warning(f"Falta que **Centro de Planificación** defina el tanque destino del {_pf}.")
        return
    nt = cat("SELECT nombre FROM produccion.dim_tanque WHERE id_tanque=%s", (int(dest),))
    dest_nm = nt.iloc[0]["nombre"] if (nt is not None and not nt.empty) else f"tanque {int(dest)}"

    # ---- envíos ya registrados (pases anteriores) ----
    _tot = cat("SELECT COALESCE(SUM(litros_afe),0) t FROM produccion.fact_desg_envio WHERE id_batch=%s", (int(b["id_batch"]),))
    _enviado = float(_tot.iloc[0]["t"]) if (_tot is not None and not _tot.empty) else 0.0
    if _enviado > 0:
        st.info(f"📦 Ya enviado a destino en pases anteriores: **{_enviado:,.0f} L** de {_pf}. "
                "Terminá de sacar el remanente y cerrá cuando el recipiente quede vacío.")
        _eh = cat(f"SELECT to_char(ts,'DD/MM HH24:MI') AS \"Hora\", litros_afe AS \"{_pf} L\", "
                  "litros_remanente AS \"Remanente L\", "
                  "CASE WHEN recipiente_vacio THEN 'cierre ✅' WHEN es_error THEN 'parcial ⚠️' ELSE 'parcial' END AS \"Tipo\", "
                  "COALESCE(motivo,'') AS \"Motivo\" "
                  "FROM produccion.fact_desg_envio WHERE id_batch=%s ORDER BY ts DESC", (int(b["id_batch"]),))
        if _eh is not None and not _eh.empty:
            st.dataframe(_eh, use_container_width=True, hide_index=True)
    if b.get("desg_incidente"):
        st.warning(f"⚠️ Este desgomado tiene un **incidente** registrado: {b.get('desg_incidente_motivo') or 'decantación parcial'}.")

    _lit_def = float(b["litros_inicial"] or 0) or (float(b["kg_inicial"] or 0) / DENS_AFE if b["kg_inicial"] else 0.0)
    _lit_def = max(_lit_def - _enviado, 0.0)

    # ---- CIERRE CON AJUSTE: lo que realmente se vació y lo que quedó ----
    st.markdown("##### 🚚 Cierre con ajuste (lo que realmente salió y lo que quedó)")
    st.caption(f"Estimado a sacar en este pase: **{_lit_def:,.0f} L**. Cargá lo que **realmente vaciaste** a destino "
               "y **cuánto quedó** en el tanque.")
    c1, c2, c3 = st.columns(3)
    l_afe = c1.number_input(f"{_pf} vaciado a {dest_nm} (L)", min_value=0.0, max_value=1_000_000.0,
                            value=float(round(_lit_def, 0)), step=10.0, key="desg_l_afe")
    l_rem = c2.number_input("¿Cuánto quedó en el tanque? (L)", min_value=0.0, max_value=1_000_000.0,
                            value=0.0, step=10.0, key="desg_l_rem",
                            help="0 si vaciaste todo. Si quedó líquido, cargá el remanente estimado.")
    l_fondo = c3.number_input("Fondo de tanque (L, opcional)", min_value=0.0, max_value=1_000_000.0,
                              value=0.0, step=10.0, key="desg_l_fondo")
    _merma = round(_lit_def - l_afe - l_rem, 0)
    if abs(_merma) >= 1:
        st.caption(f"Ajuste vs estimado: {'merma' if _merma>0 else 'excedente'} de **{abs(_merma):,.0f} L** "
                   f"(estimado {_lit_def:,.0f} − vaciado {l_afe:,.0f} − quedó {l_rem:,.0f}).")

    # ---- tickets de destino final (pesadas del producto, evaluadas por lab) ----
    st.markdown("###### 🏁 Tickets de destino final (pesadas del producto)")
    st.caption("Cargá acá las pesadas de balanza del producto final ya evaluadas por laboratorio. "
               "La suma define los kilos finales reales de la reacción.")
    try:
        import planificacion as _plan
        _plan._ficha_final_tickets(USR, cat, conectar, int(b["id_batch"]), _pf, kp="desg")
    except Exception as _etk:
        st.caption(f"No se pudieron cargar los tickets finales: {_etk}")
    st.divider()

    # confirmación de vaciado: DOS chequeos
    st.markdown("###### Confirmación de vaciado")
    k1, k2 = st.columns(2)
    canilla_ok = k1.checkbox("🚰 Probé la **canilla** y ya no tira más", key="desg_canilla_ok")
    vision_ok = k2.checkbox("👁️ Verifiqué **por visión desde arriba** que quedó vacío", key="desg_vision_ok")
    motivo = st.text_input("Nota / motivo (obligatorio si quedó remanente)",
                           value=("Error del operario: se decantó solo una parte" if l_rem > 0 else ""),
                           key="desg_inc_motivo")

    es_vacio = (l_rem <= 0) and canilla_ok and vision_ok

    def _envio(cur, vacio, es_err, l_rem_, motivo_):
        id_afe = int(b["id_producto_buscado"]) if pd.notna(b["id_producto_buscado"]) else AFE_S_ID
        _mov(cur, b, uid, "PRODUCTO_FINAL", id_afe, _pf, int(dest), l_afe, DENS_AFE)
        if l_fondo and l_fondo > 0:
            _mov(cur, b, uid, "SUBPRODUCTO", FONDO_TK_ID, "Fondo de tanque", int(dest), l_fondo, 1.0)
        cur.execute("INSERT INTO produccion.fact_desg_envio "
                    "(id_batch,litros_afe,litros_fondo,id_tanque_destino,recipiente_vacio,es_error,"
                    " litros_remanente,motivo,canilla_ok,vision_ok,id_usuario) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (int(b["id_batch"]), float(l_afe), float(l_fondo or 0), int(dest),
                     bool(vacio), bool(es_err), (float(l_rem_) if l_rem_ else None), (motivo_ or None),
                     bool(canilla_ok), bool(vision_ok), uid))

    if es_vacio:
        st.success("✅ Vaciado confirmado por canilla y visión. Al registrar, el desgomado queda FINALIZADO.")
    elif l_rem > 0:
        st.warning(f"⚠️ Quedó **{l_rem:,.0f} L** en {_recipiente_nombre(cat, b)}. Se registra el ajuste como "
                   "**incidente** y el batch sigue en decantación para terminar de sacarlo.")
    else:
        st.info("Para cerrar como vacío marcá **canilla** y **visión**. Si quedó líquido, cargá cuánto quedó.")

    if st.button("💾 Registrar vaciado", type="primary", use_container_width=True, key="desg_reg"):
        if l_afe <= 0 and l_rem <= 0:
            st.error("Cargá cuánto vaciaste (y/o cuánto quedó).")
            return
        if l_rem <= 0 and not (canilla_ok and vision_ok):
            st.error("Para cerrar como vacío tenés que confirmar **canilla** y **visión**. Si quedó líquido, cargá el remanente.")
            return
        if l_rem > 0 and not (motivo or "").strip():
            st.error("Si quedó remanente, poné el motivo.")
            return
        try:
            with conectar(uid) as (conn, audit):
                with conn.cursor() as cur:
                    _envio(cur, vacio=es_vacio, es_err=(l_rem > 0), l_rem_=l_rem, motivo_=motivo)
                    if es_vacio:
                        cur.execute("UPDATE produccion.fact_etapa_evento SET fin_ts=now() WHERE id_batch=%s AND fin_ts IS NULL",
                                    (int(b["id_batch"]),))
                        cur.execute("INSERT INTO produccion.fact_etapa_evento (id_batch,etapa,inicio_ts,fin_ts,id_usuario) "
                                    "VALUES (%s,'EN_TANQUE',now(),now(),%s)", (int(b["id_batch"]), uid))
                        cur.execute(
                            "UPDATE produccion.fact_batch_proceso SET estado='FINALIZADO', etapa_actual='EN_TANQUE', "
                            "desg_recipiente_vacio=true, desg_recipiente_metodo='CANILLA+VISION', desg_recipiente_ts=now(), "
                            "desg_confirmada_ts=now(), id_usuario_estado=%s, "
                            "motivo_estado='Desgomado FINALIZADO: vaciado confirmado (canilla + visión)' WHERE id_batch=%s",
                            (uid, int(b["id_batch"])))
                    else:
                        cur.execute("UPDATE produccion.fact_batch_proceso SET desg_incidente=true, "
                                    "desg_incidente_motivo=%s, id_usuario_estado=%s, "
                                    "motivo_estado=%s WHERE id_batch=%s",
                                    ((motivo or "Quedó remanente"), uid,
                                     "AJUSTE: vaciado " + f"{l_afe:.0f}" + " L, quedó " + f"{l_rem:.0f}" + " L (" + (motivo or "") + ")",
                                     int(b["id_batch"])))
                    audit.log("U", "fact_batch_proceso", int(b["id_batch"]),
                              {"vaciado_L": l_afe, "quedo_L": l_rem, "vacio": es_vacio})
            if es_vacio:
                st.success("Desgomado FINALIZADO. Vaciado confirmado (canilla + visión).")
                st.balloons()
            else:
                st.success(f"Ajuste registrado: vaciaste {l_afe:,.0f} L, quedaron {l_rem:,.0f} L. Sigue en decantación.")
            cat.clear(); st.rerun()
        except Exception as e:
            st.exception(e)


def _mov(cur, b, uid, rol, id_prod, prod_txt, id_tanque, litros, dens):
    if not litros or litros <= 0:
        return
    cur.execute(
        "INSERT INTO produccion.fact_movimiento_stock "
        "(momento,id_batch,identificador_prod,tipo_movimiento,rol,sentido,id_producto,producto,"
        " fuente,id_tanque,cantidad,unidad,kg,litros,id_usuario,origen,estado_mov) "
        "VALUES (now(),%s,%s,'ENTRADA',%s,1,%s,%s,'TANQUE',%s,%s,'LT',%s,%s,%s,'decantacion','EJECUTADO')",
        (int(b["id_batch"]), b["ident"], rol, id_prod, prod_txt, int(id_tanque),
         float(litros), float(litros) * float(dens), float(litros), uid))


# ============================================================ LABORATORIO
def laboratorio(USR, cat, conectar):
    st.subheader("🔬 Desgomado en decantación — agua + sedimentos")
    ays_max = _cond(cat, "DESGOM_AGUA_SED_MAX_PCT", AYS_MAX_DEF)
    st.caption(f"Cargá **agua** y **sedimentos** de la muestra de decantación. "
               f"Corta cuando la **suma < {ays_max:g}%** (libre de goma/agua/sedimentos).")
    b, _ = _sel_batch(cat, "desg_lab_sel")
    if b is None:
        return
    _cabecera(cat, b)
    uid = int(USR["id_usuario"])

    c1, c2, c3 = st.columns(3)
    agua = c1.number_input("Agua (%)", 0.0, 100.0, value=0.0, step=0.05, key="desg_lab_agua")
    sed = c2.number_input("Sedimentos (%)", 0.0, 100.0, value=0.0, step=0.05, key="desg_lab_sed")
    suma = float(agua) + float(sed)
    c3.metric("Agua + sedimentos", f"{suma:.2f}%", ("OK ✅" if suma < ays_max else f"≥ {ays_max:g}%"))
    obs = st.text_input("Observación (opcional)", key="desg_lab_obs")
    if st.button("💾 Guardar muestra (agua+sedimentos)", type="primary", key="desg_lab_save"):
        ok = suma < ays_max
        try:
            with conectar(uid) as (conn, audit):
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO produccion.fact_desg_decant "
                        "(id_batch, agua_pct, sedimentos_pct, suma_pct, ok, observacion, id_usuario) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                        (int(b["id_batch"]), float(agua), float(sed), float(suma), bool(ok), (obs or None), uid))
                    cur.execute("UPDATE produccion.fact_batch_proceso "
                                "SET desg_agua_sed_pct=%s, desg_lab_ok=%s WHERE id_batch=%s",
                                (float(suma), bool(ok), int(b["id_batch"])))
                audit.log("I", "fact_desg_decant", int(b["id_batch"]), {"suma": suma, "ok": ok})
            st.success(f"Agua+sedimentos {suma:.2f}% → " +
                       (f"✅ apto (< {ays_max:g}%)" if ok else f"🔴 seguir decantando (≥ {ays_max:g}%)"))
            cat.clear(); st.rerun()
        except Exception as e:
            st.exception(e)
    _hist_lab(cat, int(b["id_batch"]))
