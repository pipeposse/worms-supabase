# -*- coding: utf-8 -*-
"""Instructivo de la OP para el operario (Fase 4b) — SEGUIMIENTO PRODUCCIÓN, parte 2.

"El operario carga la orden de producción y el sistema despliega el instructivo":
los pasos de la fórmula (produccion.v_op_instructivo, versión congelada al arrancar,
cantidades ya escaladas a los kg de la OP) con el valor esperado de cada uno. En cada
paso carga lo que corresponde — hora inicio/fin, temperatura y acidez, o la cantidad —
y el sistema le dice al instante si quedó dentro de la tolerancia. Todo va a
fact_paso_medicion; los desvíos salen solos de v_desvio_op.

Corre en un st.fragment dentro de "Producción en planta": confirmar un paso redibuja
sólo este bloque. No reemplaza la máquina de estados (Arrancar → Reacción → …): es el
registro fino, paso a paso, que dirección pidió como input del estado de la RX.
"""

from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

try:
    _FRAGMENT = st.fragment
except AttributeError:
    def _FRAGMENT(f=None, **kw):
        return f if f else (lambda g: g)


def _rerun_fragment():
    """Redibuja sólo el fragment; si no estamos en un rerun de fragment (p. ej. AppTest o
    Streamlit sin fragments), cae al rerun normal."""
    try:
        st.rerun(scope="fragment")
    except Exception:
        st.rerun()

_ICONO = {"CALDERA": "🔥", "CARGA_MP": "🛢️", "CARGA_INSUMO": "🧪", "VALIDAR_TEMP": "🌡️", "INICIO_RX": "⚗️",
          "REVISION": "🔎", "DECANTACION": "🧴", "REPOSO": "🧊", "REPOSANDO": "🧊", "EN_TANQUE": "📦"}
_TZ = "America/Argentina/Buenos_Aires"


# ------------------------------------------------------------------ datos
def _pasos(cat, id_batch):
    df = cat("SELECT * FROM produccion.v_op_instructivo WHERE id_batch=%s ORDER BY orden", (int(id_batch),)).copy()
    for c in ("cant_esperada", "cantidad_real", "acidez_esp", "temp_esp", "tol_acidez", "tol_temp", "tol_cant_pct",
              "acidez_pct", "temp_c", "desvio_acidez", "desvio_temp", "desvio_cant_pct", "duracion_real_min"):
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    for c in ("hora_esperada", "inicio_ts", "fin_ts"):
        if c in df:
            df[c] = pd.to_datetime(df[c], errors="coerce")
            try:
                df[c] = df[c].dt.tz_convert(_TZ).dt.tz_localize(None)
            except Exception:
                pass
    return df


def _congelar(conectar, cat, USR, id_batch):
    """Fija la versión del instructivo con la que arranca la OP (una vez por sesión)."""
    k = f"_op_congelada_{id_batch}"
    if st.session_state.get(k):
        return
    try:
        with conectar(int(USR["id_usuario"])) as (conn, audit):
            with conn.cursor() as cur:
                cur.execute("SELECT produccion.fn_op_congelar_version(%s)", (int(id_batch),))
        inv = getattr(cat, "invalidar", None)
        (inv("fact_batch_proceso") if callable(inv) else cat.clear())   # función llamada con SELECT: el hook no la ve
    except Exception:
        pass
    st.session_state[k] = True


def _guardar(conectar, USR, id_batch, p, **campos):
    """Upsert de lo cargado en un paso (sólo los campos que vienen con valor)."""
    cols = {k: v for k, v in campos.items() if v is not None}
    base_cols = ["id_batch", "orden", "etapa", "id_usuario", "unidad"]
    base_vals = [int(id_batch), int(p["orden"]), p["etapa"], int(USR["id_usuario"]), p.get("unidad")]
    todas = base_cols + list(cols.keys())
    sets = ["id_usuario = EXCLUDED.id_usuario", "actualizado_en = now()"] + [f"{c} = EXCLUDED.{c}" for c in cols]
    sql = ("INSERT INTO produccion.fact_paso_medicion (" + ", ".join(todas) + ") VALUES ("
           + ", ".join(["%s"] * len(todas)) + ") ON CONFLICT (id_batch, orden) DO UPDATE SET " + ", ".join(sets))
    with conectar(int(USR["id_usuario"])) as (conn, audit):
        with conn.cursor() as cur:
            cur.execute(sql, base_vals + list(cols.values()))
        audit.log("U", "fact_paso_medicion", int(id_batch), {"orden": int(p["orden"]), **{k: str(v) for k, v in cols.items()}})


# ------------------------------------------------------------------ helpers
def _n(x, d=0):
    return f"{float(x):,.{d}f}" if x is not None and pd.notna(x) else "—"


def _esperado(p):
    out = []
    if pd.notna(p.get("cant_esperada")) and p["cant_esperada"] > 0:
        out.append(f"{_n(p['cant_esperada'])} {p.get('unidad') or ''} ±{_n(p.get('tol_cant_pct'), 0)} %")
    if pd.notna(p.get("temp_esp")):
        out.append(f"{_n(p['temp_esp'])} °C ±{_n(p.get('tol_temp'), 0)}")
    if pd.notna(p.get("acidez_esp")):
        out.append(f"acidez {_n(p['acidez_esp'])} % ±{_n(p.get('tol_acidez'), 0)}")
    if pd.notna(p.get("duracion_min")):
        out.append(f"{int(p['duracion_min'])} min")
    return " · ".join(out)


def _real(p):
    out = []
    if p["captura"] == "HORAS":
        if pd.notna(p.get("inicio_ts")):
            out.append(p["inicio_ts"].strftime("%H:%M") + ("→" + p["fin_ts"].strftime("%H:%M") if pd.notna(p.get("fin_ts")) else " → …"))
    if pd.notna(p.get("cantidad_real")) and p["captura"] == "CANTIDAD":
        out.append(f"{_n(p['cantidad_real'])} {p.get('unidad') or ''}")
    if pd.notna(p.get("temp_c")):
        out.append(f"{_n(p['temp_c'])} °C")
    if pd.notna(p.get("acidez_pct")):
        out.append(f"{_n(p['acidez_pct'], 1)} %")
    return " · ".join(out)


def _estado_icono(p, actual):
    if bool(p.get("fuera_tolerancia")):
        return "⚠️"
    if bool(p.get("hecho")):
        return "✅"
    return "🔵" if actual else "⚪"


# ------------------------------------------------------------------ bloque
@_FRAGMENT
def render(USR, cat, conectar, id_batch):
    _congelar(conectar, cat, USR, id_batch)
    df = _pasos(cat, id_batch)
    if df.empty:
        st.caption("📑 Esta producción no tiene instructivo: la fórmula todavía no tiene pasos publicados "
                   "(Fórmulas → Pasos (instructivo)).")
        return
    hechos = int(df["hecho"].fillna(False).astype(bool).sum())
    total = len(df)
    pend = df[~df["hecho"].fillna(False).astype(bool)]
    actual_orden = int(pend.iloc[0]["orden"]) if not pend.empty else None
    fuera = int(df["fuera_tolerancia"].fillna(False).astype(bool).sum())

    st.markdown(f"#### 📑 Instructivo · {hechos} de {total} pasos" + (f" · ⚠️ {fuera} fuera de tolerancia" if fuera else ""))
    st.progress(hechos / total if total else 0.0)
    ver = df.iloc[0].get("version")
    st.caption(f"Fórmula versión {int(ver) if pd.notna(ver) else '—'} · cantidades para {_n(df.iloc[0]['kg_inicial'])} kg de MP · "
               "el valor esperado viene de la formulación; lo que cargás acá se cruza contra eso.")

    # ---- lista compacta ----
    filas = []
    for _, p in df.iterrows():
        filas.append({
            "": _estado_icono(p, int(p["orden"]) == actual_orden), "#": int(p["orden"]),
            "Paso": f"{_ICONO.get(p['etapa'], '•')} {p.get('descripcion') or p['etapa']}" + (f" · {p['codigo_insumo']}" if p.get("codigo_insumo") else ""),
            "Esperado": _esperado(p),
            "Hora": p["hora_esperada"].strftime("%H:%M") if pd.notna(p.get("hora_esperada")) else "",
            "Real": _real(p),
        })
    st.dataframe(pd.DataFrame(filas), hide_index=True, use_container_width=True, height=min(60 + 35 * total, 420))

    # ---- paso a cargar ----
    opciones = [int(o) for o in df["orden"]]
    etiquetas = {int(p["orden"]): f"{int(p['orden'])} · {p.get('descripcion') or p['etapa']}" for _, p in df.iterrows()}
    idx = opciones.index(actual_orden) if actual_orden in opciones else 0
    sel = st.selectbox("Paso", opciones, index=idx, format_func=lambda o: etiquetas[o], key=f"opi_sel_{id_batch}",
                       label_visibility="collapsed")
    p = df[df["orden"] == sel].iloc[0]
    with st.container(border=True):
        st.markdown(f"**{_ICONO.get(p['etapa'], '•')} Paso {int(p['orden'])} · {p.get('descripcion') or p['etapa']}**"
                    + (f" · {p['codigo_insumo']}" if p.get("codigo_insumo") else ""))
        esp = _esperado(p)
        if esp:
            st.caption("Esperado: " + esp + (f" · a las {p['hora_esperada'].strftime('%H:%M')}" if pd.notna(p.get("hora_esperada")) else ""))
        cap = p["captura"]
        ahora = datetime.now()
        campos, avisos = {}, []

        if cap == "HORAS":
            c1, c2 = st.columns(2)
            ini_prev = p["inicio_ts"] if pd.notna(p.get("inicio_ts")) else None
            fin_prev = p["fin_ts"] if pd.notna(p.get("fin_ts")) else None
            if c1.button("▶ Inicio ahora" if ini_prev is None else f"▶ Inicio {ini_prev.strftime('%H:%M')} (cambiar a ahora)",
                         key=f"opi_ini_{id_batch}_{sel}", use_container_width=True, type=("primary" if ini_prev is None else "secondary")):
                _guardar(conectar, USR, id_batch, p, inicio_ts=ahora)
                _rerun_fragment()
            if c2.button("⏹ Fin ahora" if fin_prev is None else f"⏹ Fin {fin_prev.strftime('%H:%M')} (cambiar a ahora)",
                         key=f"opi_fin_{id_batch}_{sel}", use_container_width=True, type=("primary" if ini_prev is not None and fin_prev is None else "secondary")):
                _guardar(conectar, USR, id_batch, p, fin_ts=ahora, inicio_ts=(ini_prev or ahora))
                _rerun_fragment()
            with st.expander("Cargar horas a mano", expanded=False):
                h1 = st.time_input("Inicio", value=(ini_prev.time() if ini_prev else ahora.time()), key=f"opi_h1_{id_batch}_{sel}")
                h2 = st.time_input("Fin", value=(fin_prev.time() if fin_prev else ahora.time()), key=f"opi_h2_{id_batch}_{sel}")
                obs = st.text_input("Observación", key=f"opi_obs_{id_batch}_{sel}")
                if st.button("✔ Guardar horas", key=f"opi_go_{id_batch}_{sel}", type="primary"):
                    d = (ini_prev or ahora).date()
                    ini = datetime.combine(d, h1); fin = datetime.combine(d, h2)
                    if fin < ini:
                        fin += timedelta(days=1)
                    _guardar(conectar, USR, id_batch, p, inicio_ts=ini, fin_ts=fin, observacion=(obs or None))
                    _rerun_fragment()
            return

        if cap == "MEDICION":
            c1, c2 = st.columns(2)
            if pd.notna(p.get("temp_esp")):
                campos["temp_c"] = c1.number_input("Temperatura (°C)", 0.0, 300.0,
                                                   float(p["temp_c"]) if pd.notna(p.get("temp_c")) else float(p["temp_esp"]),
                                                   1.0, key=f"opi_t_{id_batch}_{sel}")
                d = campos["temp_c"] - float(p["temp_esp"])
                if abs(d) > float(p.get("tol_temp") or 4):
                    avisos.append(f"temperatura {d:+.0f} °C fuera de tolerancia (±{_n(p.get('tol_temp'))})")
            if pd.notna(p.get("acidez_esp")):
                campos["acidez_pct"] = c2.number_input("Acidez (%)", 0.0, 100.0,
                                                       float(p["acidez_pct"]) if pd.notna(p.get("acidez_pct")) else float(p["acidez_esp"]),
                                                       0.5, key=f"opi_a_{id_batch}_{sel}")
                d = campos["acidez_pct"] - float(p["acidez_esp"])
                if abs(d) > float(p.get("tol_acidez") or 3):
                    avisos.append(f"acidez {d:+.1f} pts fuera de tolerancia (±{_n(p.get('tol_acidez'))})")
        elif cap == "CANTIDAD":
            campos["cantidad"] = st.number_input(f"Cantidad cargada ({p.get('unidad') or ''})", 0.0, 10_000_000.0,
                                                 float(p["cantidad_real"]) if pd.notna(p.get("cantidad_real")) else float(p.get("cant_esperada") or 0),
                                                 10.0, key=f"opi_q_{id_batch}_{sel}")
            if pd.notna(p.get("cant_esperada")) and p["cant_esperada"] > 0:
                d = 100.0 * (campos["cantidad"] - float(p["cant_esperada"])) / float(p["cant_esperada"])
                if abs(d) > float(p.get("tol_cant_pct") or 3):
                    avisos.append(f"cantidad {d:+.1f} % respecto de lo formulado (±{_n(p.get('tol_cant_pct'))} %)")
        else:
            st.caption("Este paso no pide datos: confirmalo cuando esté hecho.")

        obs = st.text_input("Observación (opcional)", key=f"opi_obs_{id_batch}_{sel}")
        for a in avisos:
            st.warning("Desvío: " + a + ". Queda registrado con tu nombre y la hora, y lo ve el supervisor.")
        if st.button(f"✔ Confirmar paso {int(p['orden'])}", key=f"opi_ok_{id_batch}_{sel}", type="primary", use_container_width=True):
            try:
                if cap == "NINGUNA" and not campos:
                    campos["fin_ts"] = ahora
                _guardar(conectar, USR, id_batch, p, observacion=(obs or None), **campos)
                _rerun_fragment()
            except Exception as e:
                st.error(f"No se pudo guardar: {e}")
