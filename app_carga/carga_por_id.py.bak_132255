"""Carga Producción por ID (operario).
El operario elige una producción PLANIFICADA por la dirección, ve todo en read-only
(reactor, producto final, movimientos de stock con fuente/origen), completa el checklist
y la caldera, y al iniciar: confirma los movimientos (PLANIFICADO -> EJECUTADO) y pone
el batch en REACCION. No carga datos de la reacción: ya los fijó la dirección.

render(USR, cat, conectar) recibe los helpers de app.py (evita imports circulares).
"""
import streamlit as st

from planificacion import listar_planificadas, listar_movimientos_plan, confirmar_movimientos_plan

CHECKS = [
    ("mp_ok", "Materias primas disponibles y verificadas"),
    ("insumos_ok", "Insumos y catalizadores disponibles"),
    ("corriente_ok", "Corriente correcta (vegetal/animal)"),
    ("temperatura_inicial_ok", "Temperatura inicial OK"),
    ("parametros_ok", "Parámetros del proceso revisados"),
    ("caldera_encendida_ok", "Caldera encendida (≥1 h antes, 80 °C)"),
]


def render(USR, cat, conectar):
    st.title("▶️ Iniciar producción")
    st.caption("Elegí la producción planificada por dirección. Confirmás el checklist y la caldera, y arranca la reacción.")

    planificadas = listar_planificadas(cat)
    if planificadas.empty:
        st.info("No hay producciones planificadas pendientes. La dirección las crea en el Centro de Planificación.")
        return

    opts = {
        f"{r.identificador_unidad} · {r.producto_final or '—'} · {r.reactor or '—'}": int(r.id_batch)
        for r in planificadas.itertuples()
    }
    sel = st.selectbox("Producción planificada", list(opts.keys()), key="cid_sel")
    id_batch = opts[sel]
    fila = planificadas[planificadas["id_batch"] == id_batch].iloc[0]

    c1, c2, c3 = st.columns(3)
    c1.metric("ID de producción", fila["identificador_unidad"])
    c2.metric("Reactor", fila["reactor"] or "—")
    c3.metric("Producto final", fila["producto_final"] or "—")

    st.markdown("##### Movimientos de stock a ejecutar")
    movs = listar_movimientos_plan(cat, id_batch)
    if movs.empty:
        st.warning("Esta producción no tiene movimientos de stock cargados.")
    else:
        st.dataframe(movs, use_container_width=True, hide_index=True)
        st.caption("Al iniciar, estos tickets pasan de **PLANIFICADO** a **EJECUTADO** y descuentan/ingresan stock.")

    st.markdown("##### Checklist previo")
    estados = {}
    cols = st.columns(2)
    for i, (campo, label) in enumerate(CHECKS):
        estados[campo] = cols[i % 2].checkbox(label, key=f"cid_chk_{campo}")

    todo_ok = all(estados.values())
    if not todo_ok:
        st.info("Marcá todos los ítems del checklist para habilitar el inicio.")

    if st.button("🔥 Iniciar reacción", type="primary", use_container_width=True, disabled=not todo_ok):
        uid = int(USR["id_usuario"])
        try:
            with conectar(uid) as (conn, audit):
                with conn.cursor() as cur:
                    # MP principal + kg total (para satisfacer el constraint NORMAL)
                    cur.execute(
                        "SELECT id_producto, COALESCE(SUM(COALESCE(kg, litros, cantidad)),0) q "
                        "FROM fact_movimiento_stock "
                        "WHERE id_batch=%s AND rol='MP' AND anulado IS NOT TRUE "
                        "GROUP BY id_producto ORDER BY q DESC", (id_batch,))
                    mp = cur.fetchall()
                    id_prod_ini = mp[0][0] if mp else None
                    kg_ini = float(sum(float(r[1]) for r in mp)) if mp else 0.0
                    if kg_ini <= 0:
                        kg_ini = 1.0  # salvaguarda del constraint kg_inicial > 0

                    # confirmar movimientos planificados -> ejecutados
                    n_conf = confirmar_movimientos_plan(cur, id_batch, uid)

                    # checklist
                    cur.execute(
                        "INSERT INTO fact_batch_checklist "
                        "(id_batch, mp_ok, insumos_ok, temperatura_inicial_ok, parametros_ok, "
                        " corriente_ok, caldera_encendida_ok, id_usuario, confirmado_en) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s, now())",
                        (id_batch, estados["mp_ok"], estados["insumos_ok"], estados["temperatura_inicial_ok"],
                         estados["parametros_ok"], estados["corriente_ok"], estados["caldera_encendida_ok"], uid))

                    # arrancar la reacción
                    cur.execute(
                        "UPDATE fact_batch_proceso "
                        "SET estado='REACCION', etapa_actual='REACCION', id_usuario_carga=%s, "
                        "    inicio_ts=now(), caldera_encendida_ts=now(), "
                        "    id_producto_inicial=%s, kg_inicial=%s, "
                        "    id_usuario_estado=%s, motivo_estado='Iniciada por operario (checklist OK)' "
                        "WHERE id_batch=%s AND estado='PLANIFICADO'",
                        (uid, id_prod_ini, kg_ini, uid, id_batch))
                    if cur.rowcount == 0:
                        raise RuntimeError("La producción ya no está en estado PLANIFICADO (¿la inició otro?).")
            try:
                cat.clear()
            except Exception:
                pass
            st.success(f"Reacción **{fila['identificador_unidad']}** iniciada. "
                       f"{n_conf} movimiento(s) de stock confirmado(s) (EJECUTADO).")
            st.balloons()
        except Exception as e:
            st.error(f"No se pudo iniciar: {e}")
