# -*- coding: utf-8 -*-
"""
lab_carga.py  —  Seccion LABORATORIO (alta y EDICION de evaluaciones desde Streamlit)
=====================================================================================

Replica los formularios de Access (AG, ARE, AFE, EFLUENTES, BORRA) y escribe en
produccion.lab_evaluaciones. Esa tabla espeja cada fila a produccion.procesos_lab
(source_id = 'app_lab_streamlit') via trigger.

OVERRIDE DE ACCESS
------------------
Access reescribe procesos_lab todos los dias (source_id='laboratorio_pc_1'). Para
que una edicion hecha aca NO se pierda:
  - Al EDITAR un registro que vino de Access, la app lo "adopta": crea una fila en
    lab_evaluaciones con origen_source_id/origen_id_access apuntando al original.
  - La vista produccion.v_procesos_lab_efectivo oculta el registro de Access cuando
    existe esa adopcion, y muestra el de la app. Aunque Access lo reescriba a diario,
    la version de la app prevalece.
  - reporting.v_laboratorio (lo que lee el dashboard y el chat del CEO) ya lee de esa
    vista efectiva.

USO
---
    from lab_carga import render_laboratorio
    render_laboratorio()                      # usa DATABASE_URL del entorno
    render_laboratorio(get_conn=mi_get_conn)  # o tu propio conector psycopg2

Standalone:  streamlit run lab_carga.py
"""

from __future__ import annotations

import os
import uuid
from contextlib import contextmanager

import streamlit as st

try:
    import psycopg2
    import psycopg2.extras
except Exception:  # pragma: no cover
    psycopg2 = None


# ---------------------------------------------------------------------------
# Conexion
# ---------------------------------------------------------------------------
def _database_url():
    url = os.getenv("DATABASE_URL")
    if not url:
        try:
            url = st.secrets.get("DATABASE_URL")  # type: ignore[attr-defined]
        except Exception:
            url = None
    if not url and os.getenv("PGHOST"):
        url = (
            f"postgresql://{os.getenv('PGUSER','postgres')}:"
            f"{os.getenv('PGPASSWORD','')}@{os.getenv('PGHOST')}:{os.getenv('PGPORT','5432')}/"
            f"{os.getenv('PGDATABASE','postgres')}?sslmode={os.getenv('PGSSLMODE','require')}"
        )
    return url


@contextmanager
def _default_conn():
    if psycopg2 is None:
        raise RuntimeError("psycopg2 no esta instalado.")
    url = _database_url()
    if not url:
        raise RuntimeError("No hay DATABASE_URL configurada (.env o st.secrets).")
    conn = psycopg2.connect(url)
    try:
        with conn.cursor() as cur:
            cur.execute("SET search_path TO produccion, public")
        yield conn
    finally:
        conn.close()


def _conn_cm(get_conn):
    return get_conn() if get_conn else _default_conn()


# ---------------------------------------------------------------------------
# Catalogos (valores reales de produccion.procesos_lab)
# ---------------------------------------------------------------------------
EMPLEADOS = ["Cielo", "Manu", "Rich", "Mili"]
RECHAZADO = ["ACEPTADO", "RECHAZADO", "FUERA DE ESPECIFICACION", "REMUESTREO"]
CORRIENTE = ["VEGETAL", "ANIMAL"]
CAL_AG    = ["A", "B", "C", "C.2da", "D", "E", "G"]
CAL_AFE   = ["S", "SG", "B", "C", "A"]
CAL_ARE   = ["UNICA", "A", "B", "C"]
CAL_EFLU  = ["LIQUIDO"]
CAL_BORRA = ["UNICA", "B", "C", "D"]
CAL_GEN   = ["UNICA", "A", "B", "C", "D", "E"]

_TABLE = "produccion.lab_evaluaciones"
_EFECTIVO = "produccion.v_procesos_lab_efectivo"
APP_SOURCE = "app_lab_streamlit"

# columnas de datos que existen en lab_evaluaciones (defensa al insertar/editar)
_VALID_COLS = {
    "tipo_formulario", "usuario_app", "origen_source_id", "origen_id_access",
    "ticket", "num_muestra", "color", "patente_chasis", "patente_acoplado",
    "num_cisterna", "empleado", "producto", "producto_lab", "calidad_final_lab",
    "corriente", "rechazado", "conclusion", "temp_celcius", "id_tanque_1",
    "id_tanque_2", "densidad__g_ml", "prc_acidez", "prc_sedimentos", "prc_agua",
    "prc_producto", "prc_emulsion", "prc_hkf", "prc_hexano_impurezas",
    "ppm_azufre", "ppm_fosforo", "prc_goma_arriba", "prc_goma_medio",
    "prc_goma_abajo", "prc_poliglicerol", "prc_glicerina", "eflu_ph",
    "eflu_conductividad_ms", "eflu_prc_agua", "eflu_prc_sedimentos",
    "eflu_prc_grasa", "eflu_dequo_mg02_l", "borra_prc_grasa", "borra_ph",
    "borra_alcalinidad", "sebo_indice_yodo_gyodo_gmuestra", "concentracion",
}


# ---------------------------------------------------------------------------
# Acceso a datos
# ---------------------------------------------------------------------------
def buscar_registros(ticket=None, producto=None, limite=50, get_conn=None):
    """Busca en la vista efectiva (lo que se ve realmente hoy)."""
    where, params = [], []
    if ticket:
        where.append("ticket ilike %s")
        params.append(f"%{ticket.strip()}%")
    if producto:
        where.append("producto_lab = %s")
        params.append(producto)
    clause = ("where " + " and ".join(where)) if where else ""
    sql = (
        "select source_id, id_access, fecha, ticket, producto_lab, calidad_final_lab, "
        "empleado, rechazado "
        f"from {_EFECTIVO} {clause} order by fecha desc nulls last limit %s"
    )
    params.append(limite)
    with _conn_cm(get_conn) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]


def cargar_registro(source_id, id_access, get_conn=None):
    """Trae la fila completa (todas las columnas) del registro efectivo."""
    sql = f"select * from {_EFECTIVO} where source_id=%s and id_access=%s limit 1"
    with _conn_cm(get_conn) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (source_id, id_access))
            row = cur.fetchone()
            return dict(row) if row else None


def insertar_evaluacion(data, get_conn=None):
    """Alta nueva (o adopcion con origen_*). Devuelve id generado."""
    payload = {k: v for k, v in data.items() if k in _VALID_COLS and v not in (None, "")}
    cols = list(payload.keys())
    ph = ", ".join(["%s"] * len(cols))
    sql = f'insert into {_TABLE} ({", ".join(cols)}) values ({ph}) returning id'
    with _conn_cm(get_conn) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, [payload[c] for c in cols])
            new_id = cur.fetchone()[0]
        conn.commit()
        return new_id


def actualizar_evaluacion(le_id, data, get_conn=None):
    """Actualiza una fila existente de lab_evaluaciones (registro ya propio de la app)."""
    payload = {k: v for k, v in data.items()
               if k in _VALID_COLS and k not in ("origen_source_id", "origen_id_access")}
    sets = ", ".join(f"{c}=%s" for c in payload)
    sql = f"update {_TABLE} set {sets} where id=%s"
    with _conn_cm(get_conn) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, [payload[c] for c in payload] + [le_id])
        conn.commit()


def guardar_edicion(ctx, data, get_conn=None):
    """
    ctx = {'source_id':..., 'id_access':..., 'full':<dict fila original completa>}
    - Si el registro ya es de la app -> UPDATE de esa fila.
    - Si vino de Access/otro -> INSERT de override (adopcion) preservando columnas
      originales no editadas.
    """
    base = {k: v for k, v in (ctx.get("full") or {}).items() if k in _VALID_COLS}
    merged = {**base, **{k: v for k, v in data.items() if k in _VALID_COLS}}

    if ctx["source_id"] == APP_SOURCE:
        le_id = int(ctx["id_access"])  # id_access de filas app = lab_evaluaciones.id
        actualizar_evaluacion(le_id, merged, get_conn=get_conn)
        return ("update", le_id)
    else:
        merged["origen_source_id"] = ctx["source_id"]
        merged["origen_id_access"] = str(ctx["id_access"])
        new_id = insertar_evaluacion(merged, get_conn=get_conn)
        return ("adopt", new_id)


# ---------------------------------------------------------------------------
# Validaciones (replican Form_BeforeUpdate de cada macro)
# ---------------------------------------------------------------------------
def _falta(d, campos):
    return [lbl for key, lbl in campos if d.get(key) in (None, "")]


def _suma_uno(*vals, tol=1e-4):
    total = round(sum(v or 0 for v in vals), 4)
    return abs(total - 1.0) <= tol, total


def validar(tipo, d):
    comunes = [("producto_lab", "Producto laboratorio"),
               ("calidad_final_lab", "Calidad final"),
               ("rechazado", "Rechazado")]
    err = []
    if tipo == "AG":
        falt = _falta(d, comunes + [
            ("prc_acidez", "Acidez (%)"), ("prc_sedimentos", "Sedimentos (%)"),
            ("prc_agua", "Agua (%)"), ("ticket", "Ticket"),
            ("prc_producto", "Producto (%)"), ("ppm_azufre", "Azufre (ppm)"),
            ("ppm_fosforo", "Fosforo (ppm)"), ("prc_emulsion", "Emulsion (%)")])
        if falt:
            err.append("Faltan campos: " + ", ".join(falt))
        else:
            ok, tot = _suma_uno(d.get("prc_sedimentos"), d.get("prc_agua"),
                                d.get("prc_emulsion"), d.get("prc_producto"))
            if not ok:
                err.append(f"Sed+Agua+Emulsion+Producto debe sumar 1. Suma actual: {tot}")
    elif tipo == "ARE":
        falt = _falta(d, comunes + [
            ("prc_acidez", "Acidez (%)"), ("prc_sedimentos", "Sedimentos (%)"),
            ("prc_agua", "Agua (%)"), ("ticket", "Ticket"),
            ("prc_producto", "Producto (%)")])
        if falt:
            err.append("Faltan campos: " + ", ".join(falt))
        else:
            ok, tot = _suma_uno(d.get("prc_sedimentos"), d.get("prc_agua"),
                                d.get("prc_poliglicerol"), d.get("prc_glicerina"),
                                d.get("prc_producto"))
            if not ok:
                err.append(f"Sed+Agua+Poliglicerol+Glicerina+Producto debe sumar 1. Suma actual: {tot}")
    elif tipo == "AFE":
        falt = _falta(d, comunes + [("ticket", "Ticket")])
        if falt:
            err.append("Faltan campos: " + ", ".join(falt))
    else:  # EFLUENTE, BORRA, GENERICO -> solo comunes
        falt = _falta(d, comunes)
        if falt:
            err.append("Faltan campos: " + ", ".join(falt))
    return (len(err) == 0), err


# ---------------------------------------------------------------------------
# Widgets con prefill
# ---------------------------------------------------------------------------
def _k(p, tok, name):
    return f"{p}_{tok}_{name}"


def _t(label, col, pf, p, tok, name):
    return st.text_input(label, value=(pf.get(col) or "") if pf else "", key=_k(p, tok, name))


def _n(label, col, pf, p, tok, name, **kw):
    dv = pf.get(col) if pf else None
    try:
        dv = float(dv) if dv is not None else None
    except (TypeError, ValueError):
        dv = None
    return st.number_input(label, value=dv, key=_k(p, tok, name), format="%g", **kw)


def _s(label, col, options, pf, p, tok, name, default=None):
    cur = (pf.get(col) if pf else None) or default
    opts = [""] + list(options)
    if cur and cur not in opts:
        opts = ["", cur] + list(options)
    idx = opts.index(cur) if cur in opts else 0
    return st.selectbox(label, opts, index=idx, key=_k(p, tok, name))


def _cab(p, pf, tok):
    c1, c2 = st.columns(2)
    with c1:
        d = dict(
            patente_chasis=_t("Patente Chasis", "patente_chasis", pf, p, tok, "pch"),
            patente_acoplado=_t("Patente Acoplado", "patente_acoplado", pf, p, tok, "pac"),
            num_cisterna=_t("Num. de Cisterna", "num_cisterna", pf, p, tok, "cist"),
            empleado=_s("Responsable de carga *", "empleado", EMPLEADOS, pf, p, tok, "emp"),
        )
    with c2:
        d.update(
            ticket=_t("Nº de ticket *", "ticket", pf, p, tok, "tk"),
            num_muestra=_n("Nº de muestra", "num_muestra", pf, p, tok, "nm"),
            color=_t("Color", "color", pf, p, tok, "color"),
        )
    return d


def _cierre(p, pf, tok, calidades, default_corriente=None):
    c1, c2 = st.columns(2)
    with c1:
        corriente = _s("Corriente", "corriente", CORRIENTE, pf, p, tok, "corr",
                       default=default_corriente)
        calidad = _s("Calidad final *", "calidad_final_lab", calidades, pf, p, tok, "cal")
        rechazado = _s("Rechazado/Aceptado *", "rechazado", RECHAZADO, pf, p, tok, "rech")
    with c2:
        id_tanque_1 = _t("Tanque destino (automático/sugerido, editable)", "id_tanque_1", pf, p, tok, "t1")
        id_tanque_2 = _t("Tanque alternativo", "id_tanque_2", pf, p, tok, "t2")
        _mot_tq = _t("Motivo si cambiás el tanque sugerido (queda registrado)", "mot_tq", pf, p, tok, "mottq")
    conclusion = st.text_area("Conclusiones", value=(pf.get("conclusion") or "") if pf else "",
                              key=_k(p, tok, "conc"))
    if _mot_tq:
        conclusion = ((conclusion or "") + " | Cambio de tanque: " + _mot_tq).strip(" |")
    return dict(corriente=corriente, calidad_final_lab=calidad, rechazado=rechazado,
                id_tanque_1=id_tanque_1, id_tanque_2=id_tanque_2, conclusion=conclusion)


# ---------------------------------------------------------------------------
# Guardado comun
# ---------------------------------------------------------------------------
def _persistir(tipo, data, ctx, get_conn, usuario):
    if not data.get("ticket") and tipo in ("AG", "ARE", "AFE"):
        st.error("Ticket is required")
        return False
    if not (data.get("empleado") or "").strip():
        st.error("Elegí el responsable de carga (Cielo, Manu, Rich o Mili).")
        return False
    ok, errores = validar(tipo, data)
    if not ok:
        for e in errores:
            st.error(e)
        return False
    if usuario:
        data.setdefault("usuario_app", usuario)
    try:
        if ctx:  # edicion
            modo, rid = guardar_edicion(ctx, data, get_conn=get_conn)
            if modo == "adopt":
                st.success(f"Registro de Access adoptado y editado (id {rid}). "
                           "Tu version prevalece aunque Access lo reescriba.")
            else:
                st.success(f"Registro actualizado (id {rid}).")
        else:  # alta
            new_id = insertar_evaluacion(data, get_conn=get_conn)
            st.success(f"Registro guardado con exito (id {new_id}). Espejado a procesos_lab.")
        return True
    except Exception as e:
        st.error(f"Error al guardar el registro: {e}")
        return False


# ---------------------------------------------------------------------------
# Formularios por producto
# ---------------------------------------------------------------------------
def _form_AG(pf, ctx, tok, get_conn, usuario):
    p = "ag"
    st.subheader("AG · Aceite (A / B / C / D / E)")
    with st.form(_k(p, tok, "form")):
        cab = _cab(p, pf, tok)
        st.markdown("**Analisis**")
        c1, c2, c3 = st.columns(3)
        with c1:
            prc_acidez = _n("Acidez (%)", "prc_acidez", pf, p, tok, "ac")
            prc_emulsion = _n("Emulsion (%)", "prc_emulsion", pf, p, tok, "em")
            prc_sedimentos = _n("Sedimentos (%)", "prc_sedimentos", pf, p, tok, "sed")
            prc_agua = _n("Agua (%)", "prc_agua", pf, p, tok, "ag")
            prc_producto = _n("Producto (%)", "prc_producto", pf, p, tok, "prod")
        with c2:
            prc_hkf = _n("HKF (%)", "prc_hkf", pf, p, tok, "hkf")
            densidad = _n("Densidad g/ml", "densidad__g_ml", pf, p, tok, "den")
            temp = _t("Temp (Celsius)", "temp_celcius", pf, p, tok, "temp")
            prc_hexano = _n("Hexano impurezas (%)", "prc_hexano_impurezas", pf, p, tok, "hex")
        with c3:
            ppm_azufre = _n("Azufre (ppm)", "ppm_azufre", pf, p, tok, "az")
            ppm_fosforo = _n("Fosforo (ppm)", "ppm_fosforo", pf, p, tok, "fos")
        cier = _cierre(p, pf, tok, CAL_AG, default_corriente="VEGETAL")
        enviar = st.form_submit_button("GUARDAR", use_container_width=True)
    if enviar:
        data = dict(tipo_formulario="AG", producto_lab="AG",
                    prc_acidez=prc_acidez, prc_emulsion=prc_emulsion,
                    prc_sedimentos=prc_sedimentos, prc_agua=prc_agua,
                    prc_producto=prc_producto, prc_hkf=prc_hkf, densidad__g_ml=densidad,
                    temp_celcius=temp, prc_hexano_impurezas=prc_hexano,
                    ppm_azufre=ppm_azufre, ppm_fosforo=ppm_fosforo, **cab, **cier)
        if _persistir("AG", data, ctx, get_conn, usuario):
            _reset(tok)


def _form_ARE(pf, ctx, tok, get_conn, usuario):
    p = "are"
    st.subheader("ARE · (Poliglicerol / Glicerina)")
    with st.form(_k(p, tok, "form")):
        cab = _cab(p, pf, tok)
        st.markdown("**Analisis**")
        c1, c2, c3 = st.columns(3)
        with c1:
            prc_acidez = _n("Acidez (%)", "prc_acidez", pf, p, tok, "ac")
            prc_sedimentos = _n("Sedimentos (%)", "prc_sedimentos", pf, p, tok, "sed")
            prc_agua = _n("Agua (%)", "prc_agua", pf, p, tok, "ag")
            prc_producto = _n("Producto (%)", "prc_producto", pf, p, tok, "prod")
        with c2:
            prc_poli = _n("Poliglicerol (%)", "prc_poliglicerol", pf, p, tok, "poli")
            prc_gli = _n("Glicerina (%)", "prc_glicerina", pf, p, tok, "gli")
            prc_hkf = _n("HKF (%)", "prc_hkf", pf, p, tok, "hkf")
            densidad = _n("Densidad g/ml", "densidad__g_ml", pf, p, tok, "den")
        with c3:
            temp = _t("Temp (Celsius)", "temp_celcius", pf, p, tok, "temp")
            ppm_azufre = _n("Azufre (ppm)", "ppm_azufre", pf, p, tok, "az")
            ppm_fosforo = _n("Fosforo (ppm)", "ppm_fosforo", pf, p, tok, "fos")
        cier = _cierre(p, pf, tok, CAL_ARE, default_corriente="VEGETAL")
        enviar = st.form_submit_button("GUARDAR", use_container_width=True)
    if enviar:
        data = dict(tipo_formulario="ARE", producto_lab="ARE",
                    prc_acidez=prc_acidez, prc_sedimentos=prc_sedimentos,
                    prc_agua=prc_agua, prc_producto=prc_producto,
                    prc_poliglicerol=prc_poli, prc_glicerina=prc_gli, prc_hkf=prc_hkf,
                    densidad__g_ml=densidad, temp_celcius=temp,
                    ppm_azufre=ppm_azufre, ppm_fosforo=ppm_fosforo, **cab, **cier)
        if _persistir("ARE", data, ctx, get_conn, usuario):
            _reset(tok)


def _form_AFE(pf, ctx, tok, get_conn, usuario):
    p = "afe"
    st.subheader("AFE · (Goma arriba / medio / abajo)")
    with st.form(_k(p, tok, "form")):
        cab = _cab(p, pf, tok)
        st.markdown("**Analisis**")
        c1, c2, c3 = st.columns(3)
        with c1:
            prc_acidez = _n("Acidez (%)", "prc_acidez", pf, p, tok, "ac")
            prc_sedimentos = _n("Sedimentos (%)", "prc_sedimentos", pf, p, tok, "sed")
            prc_agua = _n("Agua (%)", "prc_agua", pf, p, tok, "ag")
            prc_producto = _n("Producto (%)", "prc_producto", pf, p, tok, "prod")
        with c2:
            ga = _n("Goma Arriba (%)", "prc_goma_arriba", pf, p, tok, "ga")
            gm = _n("Goma Medio (%)", "prc_goma_medio", pf, p, tok, "gm")
            gb = _n("Goma Abajo (%)", "prc_goma_abajo", pf, p, tok, "gb")
            prc_hkf = _n("HKF (%)", "prc_hkf", pf, p, tok, "hkf")
        with c3:
            densidad = _n("Densidad g/ml", "densidad__g_ml", pf, p, tok, "den")
            temp = _t("Temp (Celsius)", "temp_celcius", pf, p, tok, "temp")
            ppm_azufre = _n("Azufre (ppm)", "ppm_azufre", pf, p, tok, "az")
            ppm_fosforo = _n("Fosforo (ppm)", "ppm_fosforo", pf, p, tok, "fos")
        cier = _cierre(p, pf, tok, CAL_AFE, default_corriente="VEGETAL")
        enviar = st.form_submit_button("GUARDAR", use_container_width=True)
    if enviar:
        data = dict(tipo_formulario="AFE", producto_lab="AFE",
                    prc_acidez=prc_acidez, prc_sedimentos=prc_sedimentos,
                    prc_agua=prc_agua, prc_producto=prc_producto,
                    prc_goma_arriba=ga, prc_goma_medio=gm, prc_goma_abajo=gb,
                    prc_hkf=prc_hkf, densidad__g_ml=densidad, temp_celcius=temp,
                    ppm_azufre=ppm_azufre, ppm_fosforo=ppm_fosforo, **cab, **cier)
        if _persistir("AFE", data, ctx, get_conn, usuario):
            _reset(tok)


def _form_EFLUENTE(pf, ctx, tok, get_conn, usuario):
    p = "eflu"
    st.subheader("EFLUENTES")
    with st.form(_k(p, tok, "form")):
        cab = _cab(p, pf, tok)
        st.markdown("**Analisis**")
        c1, c2 = st.columns(2)
        with c1:
            eflu_ph = _n("pH", "eflu_ph", pf, p, tok, "ph")
            eflu_cond = _n("Conductividad (ms)", "eflu_conductividad_ms", pf, p, tok, "cond")
            eflu_agua = _n("Agua (%)", "eflu_prc_agua", pf, p, tok, "ag")
        with c2:
            eflu_sed = _n("Sedimentos (%)", "eflu_prc_sedimentos", pf, p, tok, "sed")
            eflu_grasa = _n("Grasa (%)", "eflu_prc_grasa", pf, p, tok, "gr")
            eflu_dqo = _n("DQO (mg O2/L)", "eflu_dequo_mg02_l", pf, p, tok, "dqo")
        c1, c2 = st.columns(2)
        with c1:
            calidad = _s("Calidad final *", "calidad_final_lab", CAL_EFLU, pf, p, tok, "cal",
                         default="LIQUIDO")
            rechazado = _s("Rechazado/Aceptado *", "rechazado", RECHAZADO, pf, p, tok, "rech")
        with c2:
            conclusion = st.text_area("Conclusiones",
                                      value=(pf.get("conclusion") or "") if pf else "",
                                      key=_k(p, tok, "conc"))
        enviar = st.form_submit_button("GUARDAR", use_container_width=True)
    if enviar:
        data = dict(tipo_formulario="EFLUENTE", producto_lab="EFLUENTE",
                    calidad_final_lab=calidad, rechazado=rechazado, conclusion=conclusion,
                    eflu_ph=eflu_ph, eflu_conductividad_ms=eflu_cond, eflu_prc_agua=eflu_agua,
                    eflu_prc_sedimentos=eflu_sed, eflu_prc_grasa=eflu_grasa,
                    eflu_dequo_mg02_l=eflu_dqo, **cab)
        if _persistir("EFLUENTE", data, ctx, get_conn, usuario):
            _reset(tok)


def _form_BORRA(pf, ctx, tok, get_conn, usuario):
    p = "borra"
    st.subheader("BORRA / EMULSION")
    with st.form(_k(p, tok, "form")):
        cab = _cab(p, pf, tok)
        st.markdown("**Analisis**")
        c1, c2 = st.columns(2)
        with c1:
            borra_ph = _n("PH", "borra_ph", pf, p, tok, "ph")
            borra_alc = _n("Alcalinidad (%)", "borra_alcalinidad", pf, p, tok, "alc")
            borra_grasa = _n("Materia grasa (%)", "borra_prc_grasa", pf, p, tok, "gr")
        with c2:
            prc_sedimentos = _n("Sedimentos (%)", "prc_sedimentos", pf, p, tok, "sed")
            prc_agua = _n("Agua (%)", "prc_agua", pf, p, tok, "ag")
        cier = _cierre(p, pf, tok, CAL_BORRA, default_corriente="VEGETAL")
        enviar = st.form_submit_button("GUARDAR", use_container_width=True)
    if enviar:
        data = dict(tipo_formulario="BORRA", producto_lab="BORRA",
                    borra_ph=borra_ph, borra_alcalinidad=borra_alc, borra_prc_grasa=borra_grasa,
                    prc_sedimentos=prc_sedimentos, prc_agua=prc_agua, **cab, **cier)
        if _persistir("BORRA", data, ctx, get_conn, usuario):
            _reset(tok)


def _form_GENERICO(pf, ctx, tok, get_conn, usuario):
    """Para editar productos sin formulario propio (SEBO, GLICERINA, etc.)."""
    p = "gen"
    prod = (pf or {}).get("producto_lab") or ""
    st.subheader(f"Edicion generica · {prod}")
    with st.form(_k(p, tok, "form")):
        cab = _cab(p, pf, tok)
        st.caption("Producto poco común: cargá todos los parámetros que tengas (los vacíos se ignoran).")
        c1, c2, c3 = st.columns(3)
        with c1:
            prc_acidez = _n("Acidez (%)", "prc_acidez", pf, p, tok, "ac")
            prc_sedimentos = _n("Sedimentos (%)", "prc_sedimentos", pf, p, tok, "sed")
            prc_agua = _n("Agua (%)", "prc_agua", pf, p, tok, "ag")
            prc_producto = _n("Producto (%)", "prc_producto", pf, p, tok, "prod")
            prc_emulsion = _n("Emulsion (%)", "prc_emulsion", pf, p, tok, "em")
        with c2:
            prc_hkf = _n("HKF (%)", "prc_hkf", pf, p, tok, "hkf")
            prc_hexano = _n("Hexano impurezas (%)", "prc_hexano_impurezas", pf, p, tok, "hex")
            prc_poli = _n("Poliglicerol (%)", "prc_poliglicerol", pf, p, tok, "poli")
            prc_gli = _n("Glicerina (%)", "prc_glicerina", pf, p, tok, "gli")
            densidad = _n("Densidad g/ml", "densidad__g_ml", pf, p, tok, "den")
        with c3:
            ga = _n("Goma Arriba (%)", "prc_goma_arriba", pf, p, tok, "ga")
            gm = _n("Goma Medio (%)", "prc_goma_medio", pf, p, tok, "gm")
            gb = _n("Goma Abajo (%)", "prc_goma_abajo", pf, p, tok, "gb")
            ppm_azufre = _n("Azufre (ppm)", "ppm_azufre", pf, p, tok, "az")
            ppm_fosforo = _n("Fosforo (ppm)", "ppm_fosforo", pf, p, tok, "fos")
        temp = _t("Temp (Celsius)", "temp_celcius", pf, p, tok, "temp")
        producto_lab = _t("Producto laboratorio *", "producto_lab", pf, p, tok, "plab")
        cier = _cierre(p, pf, tok, CAL_GEN)
        enviar = st.form_submit_button("GUARDAR", use_container_width=True)
    if enviar:
        data = dict(tipo_formulario="GENERICO", producto_lab=producto_lab,
                    prc_acidez=prc_acidez, prc_sedimentos=prc_sedimentos, prc_agua=prc_agua,
                    prc_producto=prc_producto, prc_emulsion=prc_emulsion, prc_hkf=prc_hkf,
                    prc_hexano_impurezas=prc_hexano, prc_poliglicerol=prc_poli, prc_glicerina=prc_gli,
                    densidad__g_ml=densidad, prc_goma_arriba=ga, prc_goma_medio=gm, prc_goma_abajo=gb,
                    ppm_azufre=ppm_azufre, ppm_fosforo=ppm_fosforo, temp_celcius=temp, **cab, **cier)
        if _persistir("GENERICO", data, ctx, get_conn, usuario):
            _reset(tok)


_FORMS = {
    "AG": _form_AG, "ARE": _form_ARE, "AFE": _form_AFE,
    "EFLUENTE": _form_EFLUENTE, "BORRA": _form_BORRA,
}


def _form_para_producto(producto_lab):
    """Mapea producto_lab de un registro al formulario adecuado."""
    if not producto_lab:
        return _form_GENERICO
    p = producto_lab.strip().upper()
    if p == "EFLUENTE":
        return _form_EFLUENTE
    if p in ("BORRA", "EMULSION"):
        return _form_BORRA
    if p in _FORMS:
        return _FORMS[p]
    return _form_GENERICO


def _form_para_base(base):
    """Mapea un producto_base elegido al formulario de carga adecuado."""
    b = (base or "").strip().upper()
    if b.startswith("AG"):
        return _form_AG
    if b.startswith("ARE"):
        return _form_ARE
    if b.startswith("AFE"):
        return _form_AFE
    if "EFLUENTE" in b or "EFLIUENTE" in b:
        return _form_EFLUENTE
    if b in ("BORRA", "EMULSION"):
        return _form_BORRA
    return _form_GENERICO


# ---------------------------------------------------------------------------
# Tickets de porteria (v_transacciones_limpias) -> autollenar patente/chasis
# ---------------------------------------------------------------------------
# Sugerencia producto_base (porteria) -> producto_lab (editable; base->lab es N:N)
_SUG_BASE_LAB = {
    "AG": "AG", "ARE": "ARE", "AFE": "AFE",
    "EFLUENTES LIQUIDOS": "EFLUENTE", "EFLIUENTES LIQUIDOS": "EFLUENTE",
    "EFLUENTES SOLIDOS": "EFLUENTE", "COMPOST": "EFLUENTE", "RESIDUOS": "EFLUENTE",
    "BORRA": "BORRA", "EMULSION": "BORRA",
}


def productos_base(dias=180, get_conn=None):
    """Lista de producto_base presentes en porteria (para el filtro)."""
    sql = ("select producto_base, count(*) c "
           "from produccion.v_transacciones_limpias "
           "where fecha_entrada >= current_date - %s and producto_base is not null "
           "group by 1 order by c desc")
    with _conn_cm(get_conn) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (dias,))
            return [r[0] for r in cur.fetchall()]


def proveedores(dias=180, get_conn=None):
    """Lista de proveedores (cliente) presentes en portería, para el primer filtro."""
    sql = ("select cliente, count(*) c from produccion.v_transacciones_limpias "
           "where fecha_entrada >= current_date - %s and cliente is not null and cliente <> '' "
           "group by 1 order by c desc")
    with _conn_cm(get_conn) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (dias,))
            return [r[0] for r in cur.fetchall()]


def ticket_produccion(ticket, get_conn=None):
    """Si el ticket es de producción (ticket_producto_final tipo F8), devuelve datos de la reacción."""
    if not ticket:
        return None
    sql = ("SELECT identificador_unidad, tipo_proceso, id_producto_buscado, calidad_buscada, "
           "parametros_proceso->>'formula_nombre' AS formula, "
           "(parametros_proceso->>'are_objetivo_kg') AS are_kg "
           "FROM produccion.fact_batch_proceso "
           "WHERE ticket_producto_final = %s AND COALESCE(anulado,false)=false "
           "ORDER BY id_batch DESC LIMIT 1")
    try:
        with _conn_cm(get_conn) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (str(ticket).strip(),))
                r = cur.fetchone()
        if not r:
            return None
        return {"identificador": r[0], "tipo_proceso": r[1], "id_producto": r[2],
                "calidad": r[3], "formula": r[4], "are_kg": r[5]}
    except Exception:
        return None


def tickets_porteria(producto_base=None, ticket=None, dias=30, limite=300, get_conn=None, cliente=None):
    """Tickets de porteria filtrados por producto_base / nro, con patentes."""
    where = ["t.fecha_entrada >= current_date - %s"]
    params = [dias]
    if producto_base:
        where.append("t.producto_base = ANY(%s)")
        params.append(list(producto_base))
    if ticket:
        where.append("CAST(t.transaccion AS text) ILIKE %s")
        params.append(f"%{str(ticket).strip()}%")
    if cliente:
        where.append("t.cliente = %s")
        params.append(cliente)
    sql = (
        "select t.transaccion, t.producto_base, t.producto, t.cliente, t.fecha_entrada, "
        "t.patente_chasis, t.patente_acoplado, t.corriente, t.evaluado "
        "from produccion.v_transacciones_limpias t "
        f"where {' and '.join(where)} "
        "order by t.fecha_entrada desc nulls last, t.transaccion desc limit %s"
    )
    params.append(limite)
    with _conn_cm(get_conn) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]


def _lbl_tk(t):
    f = str(t.get("fecha_entrada") or "")[:10]
    pat = "/".join([x for x in [t.get("patente_chasis"), t.get("patente_acoplado")] if x])
    ev = "✓" if str(t.get("evaluado")).upper() == "SI" else "·"
    return (f"#{t['transaccion']} {ev} · {t.get('producto_base') or '?'} · "
            f"{(t.get('cliente') or '')[:22]} · {f} · {pat}")


def _reset(tok):
    """Tras guardar: nuevo token (limpia widgets) y vuelve a modo alta."""
    st.session_state["lab_tok"] = uuid.uuid4().hex[:8]
    st.session_state["lab_edit_ctx"] = None
    st.session_state.pop("lab_ticket_sel", None)
    st.rerun()


def render_laboratorio(get_conn=None, usr=None):
    st.header("🧪 Laboratorio · Carga y edicion")
    st.caption("Alta nueva o edicion. Al editar un registro de Access, la app lo adopta "
               "y tu version prevalece (aunque Access lo reescriba a diario).")

    ss = st.session_state
    ss.setdefault("lab_tok", uuid.uuid4().hex[:8])
    ss.setdefault("lab_edit_ctx", None)

    _uname = ""
    if usr:
        _uname = str(usr.get("nombre_full") or usr.get("nombre") or usr.get("id_usuario") or "")
    usuario = st.text_input("Empleado / usuario que carga (queda registrado en la base)",
                            value=_uname, key="lab_user")

    modo = st.radio("Modo", ["➕ Nueva carga", "✏️ Buscar y editar"], horizontal=True,
                    key="lab_modo")

    # -------- BUSCAR Y EDITAR --------
    if modo.startswith("✏️"):
        with st.expander("Buscar registro", expanded=(ss["lab_edit_ctx"] is None)):
            c1, c2, c3 = st.columns([2, 2, 1])
            ticket = c1.text_input("Ticket contiene", key="lab_q_ticket")
            prod = c2.selectbox("Producto", ["(todos)"] + sorted(
                set(list(_FORMS.keys()) + ["EFLUENTE", "BORRA", "SEBO", "GLICERINA"])),
                key="lab_q_prod")
            buscar = c3.button("Buscar", use_container_width=True)
            if buscar:
                try:
                    res = buscar_registros(
                        ticket=ticket or None,
                        producto=None if prod == "(todos)" else prod,
                        get_conn=get_conn)
                    ss["lab_busqueda"] = res
                except Exception as e:
                    st.error(f"Error buscando: {e}")
                    ss["lab_busqueda"] = []

            res = ss.get("lab_busqueda", [])
            if res:
                def _lbl(r):
                    f = str(r["fecha"])[:16] if r.get("fecha") else "s/f"
                    org = "APP" if r["source_id"] == APP_SOURCE else "Access"
                    return (f"[{org}] {f} · {r.get('producto_lab') or '?'} · "
                            f"tk {r.get('ticket') or '-'} · cal {r.get('calidad_final_lab') or '-'} "
                            f"· id {r['id_access']}")
                opciones = {(_lbl(r)): r for r in res}
                elegido = st.selectbox(f"{len(res)} resultado(s)", list(opciones.keys()),
                                       key="lab_sel")
                if st.button("Cargar para editar", type="primary"):
                    r = opciones[elegido]
                    full = cargar_registro(r["source_id"], r["id_access"], get_conn=get_conn)
                    ss["lab_edit_ctx"] = {"source_id": r["source_id"],
                                          "id_access": r["id_access"], "full": full}
                    ss["lab_tok"] = uuid.uuid4().hex[:8]
                    st.rerun()
            elif buscar:
                st.info("Sin resultados.")

        ctx = ss.get("lab_edit_ctx")
        if ctx:
            full = ctx["full"] or {}
            org = "tu app" if ctx["source_id"] == APP_SOURCE else "Access (se adoptara al guardar)"
            st.info(f"Editando registro id {ctx['id_access']} · origen: {org}")
            if st.button("✖ Cancelar edicion"):
                ss["lab_edit_ctx"] = None
                st.rerun()
            st.divider()
            form_fn = _form_para_producto(full.get("producto_lab"))
            form_fn(full, ctx, ss["lab_tok"], get_conn, usuario)
        return

    # -------- NUEVA CARGA (ticket primero) --------
    st.markdown("**1) Nº de ticket** — portería autollena patente/chasis/proveedor; producción (ej. F8) trae la reacción")
    try:
        _pbases = productos_base(get_conn=get_conn)
    except Exception as e:
        _pbases = []
        st.caption(f"(no pude leer productos base: {e})")

    c_tk1, c_tk2 = st.columns([2, 3])
    f_tk = c_tk1.text_input("Nº de ticket", key="lab_ftk",
                            help="Portería (número) o producción (ej. F8).")
    tk_sel = None
    prod_ctx = None
    pf_new = {}
    if f_tk.strip():
        prod_ctx = ticket_produccion(f_tk.strip(), get_conn=get_conn)

    if prod_ctx:
        pf_new = {"ticket": f_tk.strip()}
        _msg = (f"🏭 Ticket de PRODUCCIÓN {f_tk.strip()} · Reacción "
                f"{prod_ctx.get('identificador') or '-'} · {prod_ctx.get('tipo_proceso') or '-'}")
        if prod_ctx.get("formula"):
            _msg += f" · Fórmula: {prod_ctx['formula']}"
        if prod_ctx.get("are_kg"):
            _msg += f" · ARE objetivo: {prod_ctx['are_kg']} kg"
        st.success(_msg)
    else:
        try:
            _ticks = tickets_porteria(None, f_tk or None, 90, get_conn=get_conn)
        except Exception as e:
            _ticks = []
            st.caption(f"(no pude leer tickets: {e})")
        if _ticks:
            _opt = {"— sin ticket —": None}
            for _t in _ticks:
                _opt[_lbl_tk(_t)] = _t
            _elec = c_tk2.selectbox(f"Ticket de portería ({len(_ticks)})", list(_opt.keys()),
                                    key="lab_tksel_box")
            tk_sel = _opt[_elec]
        else:
            c_tk2.caption("Escribí el Nº. Si es de portería aparece para autollenar; si es F# es producción.")
        if tk_sel:
            pf_new = {"ticket": str(tk_sel["transaccion"]),
                      "patente_chasis": tk_sel.get("patente_chasis"),
                      "patente_acoplado": tk_sel.get("patente_acoplado")}
            st.success(f"Ticket #{tk_sel['transaccion']} · {tk_sel.get('producto_base')} · "
                       f"proveedor {tk_sel.get('cliente') or '-'} → patentes "
                       f"{tk_sel.get('patente_chasis') or '-'}/{tk_sel.get('patente_acoplado') or '-'}")
    ss["lab_ticket_sel"] = tk_sel

    st.divider()
    st.markdown("**2) Producto a evaluar**")
    _all_bases = sorted({b for b in _pbases if b} | {"AG", "ARE", "AFE", "EFLUENTE", "BORRA", "SEBO", "GLICERINA"})
    _all_bases = _all_bases + ["OTRO (genérico)"]
    _sugbase = str((tk_sel or {}).get("producto_base") or "").upper()
    _idx = _all_bases.index(_sugbase) if _sugbase in _all_bases else len(_all_bases) - 1
    base_sel = st.selectbox("Producto base", _all_bases, index=_idx, key="lab_prod_nuevo",
                            help="Todos los productos base. Si es uno raro elegí 'OTRO (genérico)' para cargar todos los parámetros.")

    st.divider()
    _tk_id = (f_tk.strip() or (str(tk_sel["transaccion"]) if tk_sel else "blank"))
    _form_tok = f"{ss['lab_tok']}_{_tk_id}_{base_sel}"
    _fn = _form_para_base(base_sel)
    if _fn is _form_GENERICO and base_sel != "OTRO (genérico)":
        pf_new = dict(pf_new or {})
        pf_new.setdefault("producto_lab", base_sel)
    _fn(pf_new or None, None, _form_tok, get_conn, usuario)


if __name__ == "__main__":
    st.set_page_config(page_title="Laboratorio · Carga", page_icon="🧪", layout="wide")
    render_laboratorio()
