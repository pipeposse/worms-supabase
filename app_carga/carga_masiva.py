# -*- coding: utf-8 -*-
"""Carga masiva semanal (Centro de Planificación).
Sube el Excel de la directora y crea reacciones en PLANIFICADO calculando las TN
de producto final con nuestra fórmula (dic_formula). Segunda pestaña: actividades
necesarias con seguimiento (fact_actividad_plan).
render(USR, cat, conectar, siguiente_identificador)
"""
import json as _json
import unicodedata
import pandas as pd
import streamlit as st

# tipo de proceso de la planilla -> tipo_proceso del sistema (para REACTORES)
_TP_REACTOR = {"GLICEROLISIS": "PRODUCCION_ARE", "DESGOMADO ACUOSO": "DESGOMADO_ACUOSO",
               "DESGOMADO_ACUOSO": "DESGOMADO_ACUOSO"}


def _norm(s):
    if s is None:
        return ""
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return " ".join(s.upper().split())


def _find_col(cols, *keys):
    for c in cols:
        n = _norm(c)
        if all(k in n for k in keys):
            return c
    return None


def _read_sheet(file, sheet):
    try:
        return pd.read_excel(file, sheet_name=sheet, header=3, engine="openpyxl")
    except Exception:
        return None


def _fmt_ident(v):
    return str(v).strip() if v is not None and str(v).strip() else None


def render(USR, cat, conectar, siguiente_identificador):
    st.subheader("⬆️ Carga masiva de la semana")
    st.caption("Subí las plantillas de planificación. **Reacciones** → se crean en PLANIFICADO con las TN "
               "calculadas por la fórmula. **Actividades** → se registran con seguimiento. "
               "Descargá las plantillas vacías si no las tenés (pediselas al sistema).")

    _t1, _t2 = st.tabs(["🧪 Reacciones", "🧹 Actividades"])

    # ================= REACCIONES =================
    with _t1:
        up = st.file_uploader("Archivo de reacciones (WORMS_carga_reacciones_semana.xlsx)",
                              type=["xlsx"], key="cm_reac_file")
        if up is not None:
            df = _read_sheet(up, "REACCIONES")
            if df is None or df.empty:
                st.error("No pude leer la hoja **REACCIONES**. Verificá que uses la plantilla.")
                return
            C = df.columns
            col = {
                "cargar": _find_col(C, "CARGAR"), "fecha": _find_col(C, "FECHA"),
                "hora": _find_col(C, "HORA"), "sector": _find_col(C, "SECTOR"),
                "ubic": _find_col(C, "UBICACION"), "tp": _find_col(C, "TIPO", "PROCESO"),
                "corr": _find_col(C, "CORRIENTE"), "mp": _find_col(C, "MATERIA", "PRIMA"),
                "kg": _find_col(C, "CANTIDAD"), "pf": _find_col(C, "PRODUCTO", "FINAL"),
                "acmp": _find_col(C, "ACOPIO", "MP"), "acfin": _find_col(C, "TANQUE", "FINAL"),
                "sulf": _find_col(C, "SULF"), "pot": _find_col(C, "POTASA"),
                "pert": _find_col(C, "PERTENENCIA"), "obs": _find_col(C, "OBSERV"),
            }
            faltan = [k for k in ("fecha", "sector", "ubic", "tp", "mp", "kg", "pf") if not col[k]]
            if faltan:
                st.error(f"Faltan columnas en la plantilla: {faltan}")
                return

            prod = cat("SELECT id_producto, codigo_producto FROM produccion.dim_producto")
            pmap = {_norm(r["codigo_producto"]): int(r["id_producto"]) for _, r in prod.iterrows()} if prod is not None else {}
            bienes = cat("SELECT id_bien_uso, nombre_ui, tipo FROM produccion.dim_bien_uso WHERE COALESCE(activo,true)")
            bmap = {_norm(r["nombre_ui"]): (int(r["id_bien_uso"]), r["tipo"]) for _, r in bienes.iterrows()} if bienes is not None else {}
            fx = cat("SELECT sector, tipo_proceso, codigo_mp, codigo_pf, rendimiento_pct, horas_proceso, "
                     "horas_reposo, es_default, id_formula, nombre FROM produccion.dic_formula WHERE activo")

            def _formula(sector, mp, pf, tp_sistema):
                if fx is None or fx.empty:
                    return None
                f = fx[(fx["sector"] == sector)]
                cand = f[(f["codigo_mp"] == mp) & (f["codigo_pf"] == pf)]
                if cand.empty and tp_sistema:
                    cand = f[(f["tipo_proceso"] == tp_sistema) & ((f["codigo_mp"] == mp) | (f["codigo_mp"] == "*")) &
                             ((f["codigo_pf"] == pf) | (f["codigo_pf"] == "*"))]
                if cand.empty:
                    return None
                cand = cand.sort_values("es_default", ascending=False)
                return cand.iloc[0]

            rows, warns = [], []
            for _, r in df.iterrows():
                if col["cargar"] and _norm(r.get(col["cargar"])) == "NO":
                    continue
                sector = _norm(r.get(col["sector"]))
                mp = _norm(r.get(col["mp"]))
                pf = _norm(r.get(col["pf"]))
                fecha = r.get(col["fecha"])
                if not sector or not mp or not pf or pd.isna(fecha):
                    continue
                try:
                    kg = float(r.get(col["kg"]))
                except Exception:
                    kg = None
                tp_lbl = _norm(r.get(col["tp"]))
                tp_sistema = _TP_REACTOR.get(tp_lbl) if sector == "REACTORES" else None
                frow = _formula(sector, mp, pf, tp_sistema)
                if tp_sistema is None:
                    tp_sistema = (frow["tipo_proceso"] if frow is not None else
                                  ("PRODUCCION_ARE" if sector == "REACTORES" else "TRATAMIENTO_TERMOQUIMICO"))
                rend = float(frow["rendimiento_pct"]) if (frow is not None and pd.notna(frow.get("rendimiento_pct"))) else None
                kg_pf = round(kg * rend / 100.0, 0) if (kg and rend) else None
                ub = _norm(r.get(col["ubic"]))
                bu = bmap.get(ub)
                estado = "✅"
                nota = []
                if bu is None:
                    estado = "❌"; nota.append("ubicación no reconocida")
                if pmap.get(mp) is None:
                    estado = "❌"; nota.append("MP fuera de diccionario")
                if pmap.get(pf) is None:
                    estado = "❌"; nota.append("producto final fuera de diccionario")
                if kg is None:
                    estado = "❌"; nota.append("cantidad inválida")
                if kg_pf is None and estado != "❌":
                    estado = "⚠️"; nota.append("sin rendimiento en fórmula (TN a definir)")
                rows.append({
                    "_ok": estado != "❌",
                    "Estado": estado, "Fecha": pd.to_datetime(fecha).date().isoformat(),
                    "Hora": _fmt_ident(r.get(col["hora"])) or "08:00",
                    "Sector": sector, "Ubicación": _norm(r.get(col["ubic"])),
                    "Proceso": tp_sistema, "Corriente": _norm(r.get(col["corr"])) or "VEGETAL",
                    "MP": mp, "Kg MP": kg, "Producto final": pf,
                    "TN final": (round(kg_pf / 1000.0, 2) if kg_pf else None),
                    "Rend %": rend, "Tanque MP": _fmt_ident(r.get(col["acmp"])),
                    "Tanque final": _fmt_ident(r.get(col["acfin"])),
                    "Sulfúrico L": (float(r.get(col["sulf"])) if col["sulf"] and pd.notna(r.get(col["sulf"])) else None),
                    "Potasa kg": (float(r.get(col["pot"])) if col["pot"] and pd.notna(r.get(col["pot"])) else None),
                    "Pertenencia": _fmt_ident(r.get(col["pert"])) if col["pert"] else None,
                    "Obs": _fmt_ident(r.get(col["obs"])) if col["obs"] else None,
                    "Aviso": ", ".join(nota) or "—",
                    "_bu": bu, "_pf_id": pmap.get(pf), "_mp_id": pmap.get(mp),
                    "_kg_pf": kg_pf, "_frow": (frow if frow is not None else None),
                })
            if not rows:
                st.info("No hay filas con CARGAR = SI para procesar.")
                return
            prev = pd.DataFrame([{k: v for k, v in x.items() if not k.startswith("_")} for x in rows])
            n_ok = sum(1 for x in rows if x["_ok"])
            st.markdown(f"**Vista previa — {len(rows)} fila(s), {n_ok} lista(s) para crear**")
            st.dataframe(prev, hide_index=True, use_container_width=True,
                         column_config={"Kg MP": st.column_config.NumberColumn(format="localized"),
                                        "TN final": st.column_config.NumberColumn(format="%.2f"),
                                        "Rend %": st.column_config.NumberColumn(format="%.1f")})
            st.caption("✅ lista · ⚠️ se crea pero revisá la TN · ❌ no se crea (corregí y volvé a subir). "
                       "La TN final la calcula la fórmula (dic_formula); no se toma del Excel.")
            if n_ok == 0:
                st.warning("Ninguna fila está lista para crear.")
                return
            if st.button(f"✅ Crear {n_ok} reacción(es) en PLANIFICADO", type="primary", key="cm_reac_go"):
                uid = int(USR["id_usuario"])
                creadas, errores = [], []
                try:
                    with conectar(uid) as (conn, audit):
                        with conn.cursor() as cur:
                            for x in rows:
                                if not x["_ok"]:
                                    continue
                                sector = x["Sector"]
                                ident = siguiente_identificador(sector)
                                fr = x["_frow"]
                                horas = None
                                if fr is not None:
                                    try:
                                        horas = float(fr.get("horas_proceso") or 0) + float(fr.get("horas_reposo") or 0)
                                    except Exception:
                                        horas = None
                                params = {
                                    "via": "carga_masiva",
                                    "inicio_programado": f'{x["Fecha"]}T{x["Hora"]}:00',
                                    "kg_mp": x["Kg MP"],
                                    "kg_objetivo": (float(x["_kg_pf"]) if x["_kg_pf"] else None),
                                    "pf_estimado_kg": (float(x["_kg_pf"]) if x["_kg_pf"] else None),
                                    "rendimiento_pct": x["Rend %"],
                                    "ubicacion": x["Ubicación"], "corriente": x["Corriente"],
                                    "producto_final_codigo": x["Producto final"],
                                    "tanque_acopio_mp": x["Tanque MP"], "tanque_final": x["Tanque final"],
                                    "sulfurico_lt": x["Sulfúrico L"], "potasa_kg": x["Potasa kg"],
                                    "pertenencia": x["Pertenencia"],
                                    "tipo_proceso_planilla": None,
                                    "formula": ({"id_formula": int(fr["id_formula"]), "nombre": fr["nombre"]} if fr is not None else None),
                                }
                                cur.execute(
                                    "INSERT INTO produccion.fact_batch_proceso "
                                    "(fecha, sector, id_usuario_carga, identificador_unidad, id_bien_uso, tipo_proceso, "
                                    " id_producto_buscado, tiempo_estimado_horas, parametros_proceso, estado, "
                                    " id_usuario_estado, motivo_estado, observaciones) "
                                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,'PLANIFICADO',%s,'Carga masiva (dirección)',%s) "
                                    "RETURNING id_batch",
                                    (x["Fecha"], sector, uid, ident, x["_bu"][0], x["Proceso"],
                                     x["_pf_id"], horas, _json.dumps(params), uid, x["Obs"]))
                                idb = cur.fetchone()[0]
                                audit.log("C", "fact_batch_proceso", int(idb),
                                          {"via": "carga_masiva", "ident": ident, "sector": sector})
                                creadas.append(f'{ident} · {x["Ubicación"]} · {x["MP"]}→{x["Producto final"]}')
                    try:
                        cat.clear()
                    except Exception:
                        pass
                    st.success(f"Creadas **{len(creadas)}** reacciones en PLANIFICADO.")
                    st.dataframe(pd.DataFrame({"Reacción": creadas}), hide_index=True, use_container_width=True)
                    if errores:
                        st.warning("Con problemas: " + " · ".join(errores))
                except Exception as e:
                    st.error("No se pudieron crear las reacciones.")
                    st.exception(e)

    # ================= ACTIVIDADES =================
    with _t2:
        up = st.file_uploader("Archivo de actividades (WORMS_actividades_semana.xlsx)",
                              type=["xlsx"], key="cm_act_file")
        if up is not None:
            df = _read_sheet(up, "ACTIVIDADES")
            if df is None or df.empty:
                st.error("No pude leer la hoja **ACTIVIDADES**.")
            else:
                C = df.columns
                g = lambda *k: _find_col(C, *k)
                col = {"cargar": g("CARGAR"), "fecha": g("FECHA"), "hora": g("HORA"), "sector": g("SECTOR"),
                       "ubic": g("UBICACION"), "tp": g("TIPO", "ACTIVIDAD"), "prod": g("PRODUCTO"),
                       "orig": g("ORIGEN"), "dest": g("DESTINO"), "nv": g("NEC"), "tv": g("TIPO", "VEHIC"),
                       "mot": g("MOTIVO"), "req": g("REQUERIDO"), "dur": g("DURACION"), "resp": g("RESPONSABLE"),
                       "est": g("ESTADO"), "fc": g("FECHA", "CUMPLIDO"), "obs": g("OBSERV")}
                acts = []
                for _, r in df.iterrows():
                    if col["cargar"] and _norm(r.get(col["cargar"])) == "NO":
                        continue
                    fecha = r.get(col["fecha"]); mot = _fmt_ident(r.get(col["mot"]))
                    if pd.isna(fecha) or not _norm(r.get(col["tp"])):
                        continue
                    def gv(k):
                        return _fmt_ident(r.get(col[k])) if col[k] else None
                    acts.append({
                        "fecha": pd.to_datetime(fecha).date().isoformat(), "hora": gv("hora"),
                        "sector": _norm(r.get(col["sector"])), "ubic": gv("ubic"),
                        "tp": _norm(r.get(col["tp"])), "prod": gv("prod"), "orig": gv("orig"),
                        "dest": gv("dest"), "nv": gv("nv"), "tv": gv("tv"), "mot": mot, "req": gv("req"),
                        "dur": (float(r.get(col["dur"])) if col["dur"] and pd.notna(r.get(col["dur"])) else None),
                        "resp": gv("resp"), "est": (gv("est") or "PENDIENTE"),
                        "fc": (pd.to_datetime(r.get(col["fc"])).date().isoformat() if col["fc"] and pd.notna(r.get(col["fc"])) else None),
                        "obs": gv("obs"),
                    })
                if not acts:
                    st.info("No hay actividades con CARGAR = SI.")
                else:
                    st.markdown(f"**{len(acts)} actividad(es) a registrar / actualizar**")
                    st.dataframe(pd.DataFrame([{"Fecha": a["fecha"], "Hora": a["hora"], "Sector": a["sector"],
                                               "Ubicación": a["ubic"], "Actividad": a["tp"], "Motivo": a["mot"],
                                               "Vehículo": a["tv"], "Estado": a["est"]} for a in acts]),
                                 hide_index=True, use_container_width=True)
                    st.caption("Se actualizan por fecha+hora+sector+ubicación+tipo+motivo (podés re-subir con el seguimiento).")
                    if st.button(f"✅ Registrar {len(acts)} actividad(es)", type="primary", key="cm_act_go"):
                        uid = int(USR["id_usuario"])
                        try:
                            with conectar(uid) as (conn, audit):
                                with conn.cursor() as cur:
                                    for a in acts:
                                        cur.execute(
                                            "INSERT INTO produccion.fact_actividad_plan "
                                            "(fecha,hora,sector,ubicacion,tipo_actividad,producto,origen,destino,"
                                            " nec_vehiculo,tipo_vehiculo,motivo,requerido_para,duracion_hs,responsable,"
                                            " estado,fecha_cumplido,observaciones,id_usuario) "
                                            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                                            "ON CONFLICT (fecha,hora,sector,ubicacion,tipo_actividad,motivo) DO UPDATE SET "
                                            " producto=EXCLUDED.producto, origen=EXCLUDED.origen, destino=EXCLUDED.destino, "
                                            " nec_vehiculo=EXCLUDED.nec_vehiculo, tipo_vehiculo=EXCLUDED.tipo_vehiculo, "
                                            " requerido_para=EXCLUDED.requerido_para, duracion_hs=EXCLUDED.duracion_hs, "
                                            " responsable=EXCLUDED.responsable, estado=EXCLUDED.estado, "
                                            " fecha_cumplido=EXCLUDED.fecha_cumplido, observaciones=EXCLUDED.observaciones, "
                                            " actualizado_en=now()",
                                            (a["fecha"], a["hora"], a["sector"], a["ubic"], a["tp"], a["prod"],
                                             a["orig"], a["dest"], a["nv"], a["tv"], a["mot"], a["req"], a["dur"],
                                             a["resp"], a["est"], a["fc"], a["obs"], uid))
                            try:
                                cat.clear()
                            except Exception:
                                pass
                            st.success(f"Registradas/actualizadas **{len(acts)}** actividades.")
                        except Exception as e:
                            st.error("No se pudieron registrar las actividades."); st.exception(e)

        # seguimiento
        st.divider()
        st.markdown("#### 📋 Seguimiento de actividades")
        _fdesde = st.date_input("Desde", value=None, key="cm_act_desde")
        q = ("SELECT to_char(fecha,'YYYY-MM-DD') AS \"Fecha\", hora AS \"Hora\", sector AS \"Sector\", "
             "ubicacion AS \"Ubicación\", tipo_actividad AS \"Actividad\", motivo AS \"Motivo\", "
             "tipo_vehiculo AS \"Vehículo\", estado AS \"Estado\", "
             "to_char(fecha_cumplido,'YYYY-MM-DD') AS \"Cumplido\", observaciones AS \"Obs\" "
             "FROM produccion.fact_actividad_plan {} ORDER BY fecha DESC, hora")
        if _fdesde:
            segdf = cat(q.format("WHERE fecha >= %s"), (str(_fdesde),))
        else:
            segdf = cat(q.format(""))
        if segdf is not None and not segdf.empty:
            _em = {"HECHO": "✅ HECHO", "NO SE PUDO": "❌ NO SE PUDO", "REPROGRAMADO": "🔁 REPROGRAMADO",
                   "PENDIENTE": "🕗 PENDIENTE"}
            segdf["Estado"] = segdf["Estado"].map(lambda v: _em.get(v, v))
            _tot = len(segdf); _hechas = int((segdf["Estado"].str.contains("HECHO")).sum())
            k = st.columns(3)
            k[0].metric("Actividades", _tot)
            k[1].metric("Cumplidas", _hechas)
            k[2].metric("Pendientes / otras", _tot - _hechas)
            st.dataframe(segdf, hide_index=True, use_container_width=True)
        else:
            st.caption("Todavía no hay actividades registradas.")
