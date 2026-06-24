"""Sección Condicionales: umbrales de producción y parámetros aceptables por tanque.
render(USR, cat, conectar). Edición a mano, rápida (data_editor).
"""
import pandas as pd
import streamlit as st


def _vf(x):
    try:
        return float(x) if (x is not None and pd.notna(x) and str(x).strip() != "") else None
    except Exception:
        return None


def render(USR, cat, conectar):
    st.title("🧮 Condicionales")
    if USR.get("rol") not in ("SUPERVISOR", "ADMIN"):
        st.warning("Sección de dirección (SUPERVISOR / ADMIN).")
        return
    st.caption("Reglas de producción y los **parámetros que cada tanque acepta** para recibir un producto. "
               "Editás a mano, rápido, y se guarda al instante.")
    t1, t2 = st.tabs(["⚗️ Condiciones de producción", "🛢️ Parámetros aceptables por tanque"])

    # ---------------- Condiciones de producción ----------------
    with t1:
        st.caption("Umbrales del proceso. Ej.: ARE corta la reacción con **acidez ≤ 13%**; la **purga OK con glicerina ≤ 2%**; "
                   "el **ARE final aceptable con acidez ≤ 10%**.")
        df = cat("SELECT clave, descripcion, operador, valor, unidad, COALESCE(proceso,'') AS proceso "
                 "FROM produccion.dic_condicion_produccion ORDER BY proceso, clave")
        if df is None or df.empty:
            st.info("Sin condiciones cargadas.")
        else:
            _d = df.rename(columns={"clave": "Clave", "descripcion": "Descripción", "operador": "Op",
                                    "valor": "Valor", "unidad": "Unidad", "proceso": "Proceso"})
            _ed = st.data_editor(
                _d, hide_index=True, use_container_width=True, key="cond_prod_ed",
                disabled=["Clave", "Proceso"],
                column_config={
                    "Op": st.column_config.SelectboxColumn("Op", options=["<=", ">=", "<", ">", "="]),
                    "Valor": st.column_config.NumberColumn("Valor", step=0.1),
                })
            if st.button("💾 Guardar condiciones de producción", type="primary", key="cond_prod_save"):
                try:
                    with conectar(int(USR["id_usuario"])) as (conn, audit):
                        with conn.cursor() as cur:
                            for _, r in _ed.iterrows():
                                cur.execute("UPDATE produccion.dic_condicion_produccion "
                                            "SET operador=%s, valor=%s, unidad=%s, descripcion=%s WHERE clave=%s",
                                            (str(r["Op"]), _vf(r["Valor"]), (r["Unidad"] or None),
                                             (r["Descripción"] or None), r["Clave"]))
                        audit.log("U", "dic_condicion_produccion", 0, {"n": len(_ed)})
                    st.success("Condiciones de producción guardadas.")
                    cat.clear(); st.rerun()
                except Exception as e:
                    st.exception(e)

    # ---------------- Parámetros aceptables por tanque ----------------
    with t2:
        st.caption("Para cada **producto** evaluado, los tanques de acopio asignados tienen **máximos aceptables** "
                   "(acidez, agua, sedimentos, azufre, fósforo). Si el laboratorio supera el máximo, ese tanque no debería recibirlo.")
        _prods = cat("SELECT DISTINCT p.codigo_producto, p.id_producto "
                     "FROM produccion.dim_producto p "
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
            "Tanque": _tk["nombre"], "Código": _tk["codigo"],
            "Acidez máx %": pd.to_numeric(_tk["acidez_max"], errors="coerce"),
            "Agua máx %": pd.to_numeric(_tk["agua_max"], errors="coerce"),
            "Sedim. máx %": pd.to_numeric(_tk["sedimentos_max"], errors="coerce"),
            "Azufre máx ppm": pd.to_numeric(_tk["azufre_max"], errors="coerce"),
            "Fósforo máx ppm": pd.to_numeric(_tk["fosforo_max"], errors="coerce"),
        })
        _ed = st.data_editor(_df.drop(columns=["_idt"]), hide_index=True, use_container_width=True,
                             key=f"cond_tq_ed_{_pid}", disabled=["Tanque", "Código"])
        if st.button("💾 Guardar parámetros por tanque", type="primary", key=f"cond_tq_save_{_pid}"):
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
                                (_idt, _pid, _vf(r["Acidez máx %"]), _vf(r["Agua máx %"]), _vf(r["Sedim. máx %"]),
                                 _vf(r["Azufre máx ppm"]), _vf(r["Fósforo máx ppm"])))
                    audit.log("U", "dic_tanque_condicion", 0, {"producto": _pcod, "n": len(_ed)})
                st.success(f"Parámetros aceptables guardados para los tanques de {_pcod}.")
                cat.clear(); st.rerun()
            except Exception as e:
                st.exception(e)
