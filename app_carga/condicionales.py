"""Condicionales: umbrales de produccion, parametros por proceso y parametros aceptables por tanque.
Editores reutilizables (se usan en la seccion Condicionales y embebidos en Formulas).
"""
import pandas as pd
import streamlit as st


def _vf(x):
    try:
        return float(x) if (x is not None and pd.notna(x) and str(x).strip() != "") else None
    except Exception:
        return None


def _puede(USR):
    return (USR.get("rol") in ("SUPERVISOR", "ADMIN")
            or "FORMULAS" in (USR.get("secciones_app") or [])
            or "CONDICIONALES" in (USR.get("secciones_app") or []))


def editor_produccion(USR, cat, conectar):
    st.caption("Umbrales del proceso. Ej.: ARE corta con **acidez <= 13%**; **purga OK con glicerina <= 2%**; "
               "**ARE final aceptable con acidez <= 10%**; y el **aporte de glicerina (10%)** que suma al ARE objetivo.")
    df = cat("SELECT clave, descripcion, operador, valor, unidad, COALESCE(proceso,'') AS proceso "
             "FROM produccion.dic_condicion_produccion ORDER BY proceso, clave")
    if df is None or df.empty:
        st.info("Sin condiciones cargadas.")
        return
    _d = df.rename(columns={"clave": "Clave", "descripcion": "Descripcion", "operador": "Op",
                            "valor": "Valor", "unidad": "Unidad", "proceso": "Proceso"})
    _ed = st.data_editor(_d, hide_index=True, use_container_width=True, key="cond_prod_ed",
                         disabled=["Clave", "Proceso"],
                         column_config={
                             "Op": st.column_config.SelectboxColumn("Op", options=["<=", ">=", "<", ">", "="]),
                             "Valor": st.column_config.NumberColumn("Valor", step=0.1),
                         })
    if st.button("Guardar condiciones de produccion", type="primary", key="cond_prod_save"):
        try:
            with conectar(int(USR["id_usuario"])) as (conn, audit):
                with conn.cursor() as cur:
                    for _, r in _ed.iterrows():
                        cur.execute("UPDATE produccion.dic_condicion_produccion "
                                    "SET operador=%s, valor=%s, unidad=%s, descripcion=%s WHERE clave=%s",
                                    (str(r["Op"]), _vf(r["Valor"]), (r["Unidad"] or None),
                                     (r["Descripcion"] or None), r["Clave"]))
                audit.log("U", "dic_condicion_produccion", 0, {"n": len(_ed)})
            st.success("Condiciones de produccion guardadas.")
            cat.clear(); st.rerun()
        except Exception as e:
            st.exception(e)


def editor_proceso(USR, cat, conectar):
    st.caption("Objetivos por tipo de proceso que usa el **Centro de Planificacion**: acidez objetivo, "
               "temperatura inicial, tiempo y calidad buscada. Esto **si lo lee la planificacion**.")
    df = cat("SELECT tipo_proceso, temp_inicial_c, tiempo_total_horas, acidez_objetivo_pct, "
             "COALESCE(calidad_objetivo,'') AS calidad_objetivo, COALESCE(observaciones,'') AS observaciones "
             "FROM produccion.dic_proceso_parametros ORDER BY tipo_proceso")
    if df is None or df.empty:
        st.info("Sin parametros por proceso cargados.")
        return
    _d = df.rename(columns={"tipo_proceso": "Proceso", "temp_inicial_c": "Temp inicial C",
                            "tiempo_total_horas": "Tiempo h", "acidez_objetivo_pct": "Acidez objetivo %",
                            "calidad_objetivo": "Calidad objetivo", "observaciones": "Observaciones"})
    _ed = st.data_editor(_d, hide_index=True, use_container_width=True, key="cond_proc_ed",
                         disabled=["Proceso"],
                         column_config={
                             "Temp inicial C": st.column_config.NumberColumn(step=1.0),
                             "Tiempo h": st.column_config.NumberColumn(step=0.5),
                             "Acidez objetivo %": st.column_config.NumberColumn(step=0.5),
                         })
    if st.button("Guardar parametros por proceso", type="primary", key="cond_proc_save"):
        try:
            with conectar(int(USR["id_usuario"])) as (conn, audit):
                with conn.cursor() as cur:
                    for _, r in _ed.iterrows():
                        cur.execute("UPDATE produccion.dic_proceso_parametros "
                                    "SET temp_inicial_c=%s, tiempo_total_horas=%s, acidez_objetivo_pct=%s, "
                                    "calidad_objetivo=%s, observaciones=%s WHERE tipo_proceso=%s",
                                    (_vf(r["Temp inicial C"]), _vf(r["Tiempo h"]), _vf(r["Acidez objetivo %"]),
                                     (r["Calidad objetivo"] or None), (r["Observaciones"] or None), r["Proceso"]))
                audit.log("U", "dic_proceso_parametros", 0, {"n": len(_ed)})
            st.success("Parametros por proceso guardados.")
            cat.clear(); st.rerun()
        except Exception as e:
            st.exception(e)


def editor_tanques(USR, cat, conectar):
    st.caption("Para cada **producto** evaluado, los tanques de acopio asignados tienen **maximos aceptables** "
               "(acidez, agua, sedimentos, azufre, fosforo). Si el laboratorio supera el maximo, ese tanque no deberia recibirlo.")
    _prods = cat("SELECT DISTINCT p.codigo_producto, p.id_producto FROM produccion.dim_producto p "
                 "JOIN produccion.dim_tanque t ON t.id_producto_principal=p.id_producto "
                 "WHERE COALESCE(t.activo,true) ORDER BY p.codigo_producto")
    if _prods is None or _prods.empty:
        st.info("No hay productos asignados a tanques.")
        return
    _pcod = st.selectbox("Producto", _prods["codigo_producto"].tolist(), key="cond_tq_prod")
    _pid = int(_prods[_prods["codigo_producto"] == _pcod].iloc[0]["id_producto"])
    _tk = cat("SELECT t.id_tanque, t.nombre, t.codigo, "
              "c.acidez_max, c.agua_max, c.sedimentos_max, c.azufre_max, c.fosforo_max "
              "FROM produccion.dim_tanque t "
              "LEFT JOIN produccion.dic_tanque_condicion c ON c.id_tanque=t.id_tanque AND c.id_producto=%s "
              "WHERE t.id_producto_principal=%s AND COALESCE(t.activo,true) ORDER BY t.nombre", (_pid, _pid))
    if _tk is None or _tk.empty:
        st.info("Este producto no tiene tanques asignados.")
        return
    _df = pd.DataFrame({
        "_idt": _tk["id_tanque"].astype(int),
        "Tanque": _tk["nombre"], "Codigo": _tk["codigo"],
        "Acidez max %": pd.to_numeric(_tk["acidez_max"], errors="coerce"),
        "Agua max %": pd.to_numeric(_tk["agua_max"], errors="coerce"),
        "Sedim max %": pd.to_numeric(_tk["sedimentos_max"], errors="coerce"),
        "Azufre max ppm": pd.to_numeric(_tk["azufre_max"], errors="coerce"),
        "Fosforo max ppm": pd.to_numeric(_tk["fosforo_max"], errors="coerce"),
    })
    _ed = st.data_editor(_df.drop(columns=["_idt"]), hide_index=True, use_container_width=True,
                         key=f"cond_tq_ed_{_pid}", disabled=["Tanque", "Codigo"])
    if st.button("Guardar parametros por tanque", type="primary", key=f"cond_tq_save_{_pid}"):
        try:
            with conectar(int(USR["id_usuario"])) as (conn, audit):
                with conn.cursor() as cur:
                    for i, r in _ed.reset_index(drop=True).iterrows():
                        _idt = int(_df.iloc[i]["_idt"])
                        cur.execute(
                            "INSERT INTO produccion.dic_tanque_condicion "
                            "(id_tanque,id_producto,acidez_max,agua_max,sedimentos_max,azufre_max,fosforo_max,actualizado_en) "
                            "VALUES (%s,%s,%s,%s,%s,%s,%s,now()) "
                            "ON CONFLICT (id_tanque,id_producto) DO UPDATE SET "
                            "acidez_max=EXCLUDED.acidez_max, agua_max=EXCLUDED.agua_max, sedimentos_max=EXCLUDED.sedimentos_max, "
                            "azufre_max=EXCLUDED.azufre_max, fosforo_max=EXCLUDED.fosforo_max, actualizado_en=now()",
                            (_idt, _pid, _vf(r["Acidez max %"]), _vf(r["Agua max %"]), _vf(r["Sedim max %"]),
                             _vf(r["Azufre max ppm"]), _vf(r["Fosforo max ppm"])))
                audit.log("U", "dic_tanque_condicion", 0, {"producto": _pcod, "n": len(_ed)})
            st.success(f"Parametros aceptables guardados para los tanques de {_pcod}.")
            cat.clear(); st.rerun()
        except Exception as e:
            st.exception(e)


def render_tabs(USR, cat, conectar):
    t1, t2, t3 = st.tabs(["Condiciones de produccion", "Parametros por proceso", "Parametros por tanque"])
    with t1:
        editor_produccion(USR, cat, conectar)
    with t2:
        editor_proceso(USR, cat, conectar)
    with t3:
        editor_tanques(USR, cat, conectar)


def render(USR, cat, conectar):
    st.title("Condicionales")
    if not _puede(USR):
        st.warning("Seccion de direccion (SUPERVISOR / ADMIN).")
        return
    st.caption("Todas las reglas en un lugar: umbrales de produccion, objetivos por proceso y parametros por tanque.")
    render_tabs(USR, cat, conectar)
