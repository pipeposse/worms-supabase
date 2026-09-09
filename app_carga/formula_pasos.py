# -*- coding: utf-8 -*-
"""Formulación por pasos (Fase 3) — pestaña "📑 Pasos (instructivo)" de Fórmulas.

Cada fórmula (dic_formula) tiene un instructivo (dic_formula_paso): caldera, carga de
MP, carga de cada insumo, validar temperatura, inicio de reacción, revisiones de
acidez/temperatura hora a hora, decantación — con el valor esperado de cada paso y su
tolerancia. Es la tabla FORMULACIÓN del Excel de dirección y el input del
instructivo del operario (Fase 4) y de los desvíos.

Reglas de la pantalla:
* Las cantidades se guardan POR TN de MP cargada (misma base que dic_formula.insumos);
  la vista las escala a las TN que se elijan, sin recargar la página (fragment).
* Editar no escribe nada hasta "Publicar": cada publicación es una versión con
  snapshot (dic_formula_paso_version) y se puede restaurar.
* Invalidación fina: sólo se refrescan las consultas que tocan dic_formula*.
"""

import io
import json
from datetime import datetime

import pandas as pd
import streamlit as st

try:
    _FRAGMENT = st.fragment
except AttributeError:
    def _FRAGMENT(f=None, **kw):
        return f if f else (lambda g: g)

ETAPAS = ["CALDERA", "CARGA_MP", "CARGA_INSUMO", "VALIDAR_TEMP", "INICIO_RX", "REVISION",
          "REPOSO", "DECANTACION", "EN_TANQUE", "ARMADO", "CALENTAMIENTO", "REACCION", "REPOSANDO",
          "FLOCULADO", "EXTRACCION", "OTRO"]
CAPTURAS = ["HORAS", "MEDICION", "CANTIDAD", "NINGUNA"]
_CAPTURA_UI = {"HORAS": "⏱ hora inicio / fin", "MEDICION": "🌡 temp + acidez", "CANTIDAD": "⚖ cantidad cargada", "NINGUNA": "—"}
_COLS = ["orden", "etapa", "descripcion", "codigo_insumo", "cant_por_tn", "unidad", "acidez_esp", "temp_esp",
         "tol_acidez", "tol_temp", "tol_cant_pct", "offset_min", "duracion_min", "captura"]


# ------------------------------------------------------------------ datos
def _formulas(cat, sector=None):
    df = cat("SELECT id_formula, nombre, sector, tipo_proceso, codigo_mp, codigo_pf, es_default, "
             "version_pasos, pasos_actualizado_en FROM produccion.dic_formula WHERE activo "
             "ORDER BY sector, tipo_proceso, codigo_mp, codigo_pf, es_default DESC, nombre")
    if sector and sector != "(todos)":
        df = df[df["sector"] == sector]
    return df


_NUM = ["cant_por_tn", "acidez_esp", "temp_esp", "tol_acidez", "tol_temp", "tol_cant_pct"]
_INT = ["orden", "offset_min", "duracion_min"]


def _pasos(cat, idf):
    df = cat("SELECT " + ", ".join(_COLS) + " FROM produccion.dic_formula_paso "
             "WHERE id_formula=%s AND activo ORDER BY orden", (int(idf),)).copy()
    for c in _NUM:                      # numeric → Decimal en psycopg2; la grilla quiere float
        df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    for c in _INT:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype("Int64")
    return df


def _versiones(cat, idf):
    return cat("SELECT v.version, v.creado_en, v.nota, u.nombre AS usuario, v.pasos "
               "FROM produccion.dic_formula_paso_version v "
               "LEFT JOIN produccion.dim_usuario u ON u.id_usuario = v.id_usuario "
               "WHERE v.id_formula=%s ORDER BY v.version DESC", (int(idf),))


def _invalidar(cat):
    inv = getattr(cat, "invalidar", None)
    if callable(inv):
        inv("dic_formula_paso", "dic_formula", "dic_formula_paso_version")
    else:
        cat.clear()


def _publicar(conectar, cat, uid, idf, pasos_json, nota):
    with conectar(uid) as (conn, audit):
        with conn.cursor() as cur:
            cur.execute("SELECT produccion.fn_formula_pasos_publicar(%s, %s::jsonb, %s, %s)",
                        (int(idf), json.dumps(pasos_json, default=str), uid, nota or None))
            ver = cur.fetchone()[0]
        audit.log("U", "dic_formula_paso", int(idf), {"version": ver, "n_pasos": len(pasos_json)})
    _invalidar(cat)          # la función se llama con SELECT: el hook de commit no la ve como escritura
    return ver


def _semilla(cat, idf):
    df = cat("SELECT produccion.fn_formula_pasos_semilla(%s)::text AS j", (int(idf),))
    try:
        return json.loads(df.iloc[0]["j"]) if not df.empty else []
    except Exception:
        return []


# ------------------------------------------------------------------ helpers
def _hhmm(base_min, off):
    if off is None or pd.isna(off):
        return ""
    m = int(base_min + off)
    return f"{(m // 60) % 24:02d}:{m % 60:02d}"


def _f(x, d=0):
    try:
        if x is None or pd.isna(x):
            return ""
        return f"{float(x):,.{d}f}"
    except Exception:
        return ""


def _nulo(v):
    if v is None:
        return True
    try:
        if pd.isna(v):
            return True
    except (TypeError, ValueError):
        pass
    return isinstance(v, str) and v.strip() == ""


def _py(v):
    """Valor JSON-able: numpy/pandas → Python, nulos → None."""
    if _nulo(v):
        return None
    if hasattr(v, "item"):
        try:
            return v.item()
        except Exception:
            pass
    return v


def _df_a_json(df):
    out = []
    for i, r in df.reset_index(drop=True).iterrows():
        d = {c: _py(r.get(c)) for c in _COLS}
        d["orden"] = int(d["orden"]) if d.get("orden") is not None else i + 1
        out.append(d)
    out.sort(key=lambda d: d["orden"])
    for i, d in enumerate(out, 1):
        d["orden"] = i          # renumera: el orden es la posición
    return out


def _validar(pasos):
    errs = []
    for p in pasos:
        if not p.get("etapa"):
            errs.append(f"Paso {p['orden']}: falta la etapa.")
        if p.get("captura") not in CAPTURAS:
            errs.append(f"Paso {p['orden']}: captura inválida.")
        if p.get("etapa") in ("CARGA_MP", "CARGA_INSUMO") and not p.get("cant_por_tn"):
            errs.append(f"Paso {p['orden']} ({p['etapa']}): falta la cantidad por TN.")
        if p.get("captura") == "MEDICION" and p.get("temp_esp") in (None, "") and p.get("acidez_esp") in (None, ""):
            errs.append(f"Paso {p['orden']}: una medición necesita temperatura y/o acidez esperada.")
    return errs


# ------------------------------------------------------------------ vistas
@_FRAGMENT
def _vista_instructivo(pasos, f, key):
    """Tabla del instructivo con el layout de dirección, escalada a las TN elegidas. Fragment:
    cambiar TN u hora de inicio no recarga la página."""
    c1, c2, c3 = st.columns([1.2, 1.2, 3])
    tn = c1.number_input("Simular para (TN de MP)", 1.0, 200.0, 30.0, 1.0, key=f"{key}_tn")
    hora = c2.time_input("Hora de inicio", value=datetime.strptime("08:00", "%H:%M").time(), key=f"{key}_h0")
    base = hora.hour * 60 + hora.minute
    filas = []
    for _, p in pasos.iterrows():
        cant = float(p["cant_por_tn"]) * tn if pd.notna(p["cant_por_tn"]) else None
        filas.append({
            "#": int(p["orden"]), "ETAPA": p["etapa"], "DESCRIPCIÓN": p["descripcion"] or "",
            "MP / INSUMO": p["codigo_insumo"] or "",
            f"CANT. ({tn:g} TN)": (f"{cant:,.0f} {p['unidad'] or ''}".strip() if cant is not None else ""),
            "ACIDEZ": (f"{float(p['acidez_esp']):g} % ±{float(p['tol_acidez']):g}" if pd.notna(p["acidez_esp"]) else ""),
            "TEMP": (f"{float(p['temp_esp']):g} °C ±{float(p['tol_temp']):g}" if pd.notna(p["temp_esp"]) else ""),
            "HORA": _hhmm(base, p["offset_min"]),
            "DUR.": (f"{int(p['duracion_min'])} min" if pd.notna(p["duracion_min"]) else ""),
            "CARGA": _CAPTURA_UI.get(p["captura"], p["captura"]),
        })
    tabla = pd.DataFrame(filas)
    st.dataframe(tabla, hide_index=True, use_container_width=True)
    c3.caption(f"**{f['nombre']}** · {f['sector']} · {f['tipo_proceso']} · MP {f['codigo_mp']} → {f['codigo_pf']} · "
               f"versión {int(f['version_pasos'] or 0)}"
               + (f" · actualizada {pd.to_datetime(f['pasos_actualizado_en']).strftime('%d/%m/%Y %H:%M')}"
                  if pd.notna(f.get("pasos_actualizado_en")) else ""))
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        tabla.to_excel(xw, index=False, sheet_name="Instructivo")
        pasos.to_excel(xw, index=False, sheet_name="Pasos por TN")
    st.download_button("⬇️ Descargar Excel", buf.getvalue(),
                       file_name=f"instructivo_{f['nombre'].replace(' ', '_')}_v{int(f['version_pasos'] or 0)}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key=f"{key}_xls")


def _editor(pasos, f, key, USR, cat, conectar):
    """Edición en grilla; nada se escribe hasta Publicar."""
    ver = int(f["version_pasos"] or 0)
    base = pasos[_COLS].copy() if not pasos.empty else pd.DataFrame(columns=_COLS)
    ed = st.data_editor(
        base, num_rows="dynamic", hide_index=True, use_container_width=True, key=f"{key}_ed_v{ver}",
        column_config={
            "orden": st.column_config.NumberColumn("#", min_value=1, step=1, width="small"),
            "etapa": st.column_config.SelectboxColumn("Etapa", options=ETAPAS, required=True),
            "descripcion": st.column_config.TextColumn("Descripción", width="large"),
            "codigo_insumo": st.column_config.TextColumn("MP / insumo"),
            "cant_por_tn": st.column_config.NumberColumn("Cant. por TN", min_value=0.0, format="%.3f"),
            "unidad": st.column_config.SelectboxColumn("Un.", options=["KG", "L"], width="small"),
            "acidez_esp": st.column_config.NumberColumn("Acidez %", min_value=0.0, max_value=100.0, format="%.1f"),
            "temp_esp": st.column_config.NumberColumn("Temp °C", min_value=0.0, max_value=300.0, format="%.0f"),
            "tol_acidez": st.column_config.NumberColumn("± acidez", min_value=0.0, format="%.1f", width="small"),
            "tol_temp": st.column_config.NumberColumn("± temp", min_value=0.0, format="%.1f", width="small"),
            "tol_cant_pct": st.column_config.NumberColumn("± cant %", min_value=0.0, format="%.1f", width="small"),
            "offset_min": st.column_config.NumberColumn("+min desde inicio", min_value=0, step=5),
            "duracion_min": st.column_config.NumberColumn("Dur. min", min_value=0, step=5),
            "captura": st.column_config.SelectboxColumn("Carga el operario", options=CAPTURAS, required=True),
        })
    c1, c2 = st.columns([3, 1.4])
    nota = c1.text_input("Nota de esta versión (qué cambió y por qué)", key=f"{key}_nota_v{ver}")
    if c2.button(f"💾 Publicar versión {ver + 1}", type="primary", use_container_width=True, key=f"{key}_pub_v{ver}"):
        pasos_json = _df_a_json(ed)
        errs = _validar(pasos_json)
        if not pasos_json:
            errs.append("No hay pasos para publicar.")
        if errs:
            for e in errs:
                st.error(e)
            return
        try:
            nv = _publicar(conectar, cat, int(USR["id_usuario"]), f["id_formula"], pasos_json, nota)
            st.success(f"Versión {nv} publicada ({len(pasos_json)} pasos).")
            st.rerun()
        except Exception as e:
            st.error(f"No se pudo publicar: {e}")


def _historial(f, key, USR, cat, conectar):
    vers = _versiones(cat, f["id_formula"])
    if vers.empty:
        st.caption("Sin versiones publicadas todavía.")
        return
    for _, v in vers.iterrows():
        try:
            n = len(json.loads(v["pasos"]) if isinstance(v["pasos"], str) else v["pasos"])
        except Exception:
            n = "?"
        c1, c2 = st.columns([4, 1.2])
        c1.write(f"**v{int(v['version'])}** · {pd.to_datetime(v['creado_en']).strftime('%d/%m/%Y %H:%M')} · "
                 f"{v['usuario'] or '—'} · {n} pasos" + (f" · _{v['nota']}_" if v["nota"] else ""))
        if int(v["version"]) != int(f["version_pasos"] or 0):
            if c2.button("↩️ Restaurar", key=f"{key}_rest_{int(v['version'])}", use_container_width=True):
                try:
                    pasos = json.loads(v["pasos"]) if isinstance(v["pasos"], str) else v["pasos"]
                    nv = _publicar(conectar, cat, int(USR["id_usuario"]), f["id_formula"], pasos,
                                   f"restaurada desde v{int(v['version'])}")
                    st.success(f"Versión {nv} publicada (copia de v{int(v['version'])}).")
                    st.rerun()
                except Exception as e:
                    st.error(f"No se pudo restaurar: {e}")


# ------------------------------------------------------------------ entrada
def render(USR, cat, conectar):
    st.caption("**Instructivo de cada fórmula**: el paso a paso que ve el operario, con el valor esperado y su "
               "tolerancia. Las cantidades van por TN de materia prima cargada y se escalan a cada producción. "
               "Cada publicación es una versión; una producción en curso sigue con la versión con la que arrancó.")
    puede_editar = USR.get("rol") in ("SUPERVISOR", "ADMIN")

    todas = _formulas(cat)
    if todas.empty:
        st.info("No hay fórmulas activas.")
        return
    sectores = ["(todos)"] + sorted(todas["sector"].dropna().unique().tolist())
    pref = st.session_state.get("fx_fsec")
    c1, c2 = st.columns([1, 3])
    sec = c1.selectbox("Sector", sectores, index=(sectores.index(pref) if pref in sectores else 0), key="fxp_sector")
    df = _formulas(cat, sec)
    if df.empty:
        st.info("No hay fórmulas en ese sector.")
        return
    opts = {f"{'⭐ ' if r['es_default'] else ''}{r['nombre']} · {r['tipo_proceso']} · {r['codigo_mp']} → {r['codigo_pf']}"
            + (f" · v{int(r['version_pasos'])}" if int(r["version_pasos"] or 0) else " · sin pasos"): int(r["id_formula"])
            for _, r in df.iterrows()}
    sel = c2.selectbox("Fórmula", list(opts.keys()), key="fxp_formula")
    idf = opts[sel]
    f = df[df["id_formula"] == idf].iloc[0]
    pasos = _pasos(cat, idf)
    key = f"fxp_{idf}"

    if pasos.empty:
        st.info("Esta fórmula todavía no tiene instructivo. Se puede generar uno inicial a partir de sus etapas e "
                "insumos (para Producción ARE: la plantilla de dirección con las 6 revisiones de acidez) y después ajustarlo.")
        if puede_editar and st.button("✨ Generar pasos iniciales", type="primary", key=f"{key}_seed"):
            try:
                semilla = _semilla(cat, idf)
                if not semilla:
                    st.warning("No se pudo armar la semilla (¿el proceso no tiene etapas cargadas?).")
                    return
                nv = _publicar(conectar, cat, int(USR["id_usuario"]), idf, semilla, "pasos iniciales generados")
                st.success(f"Versión {nv} publicada con {len(semilla)} pasos.")
                st.rerun()
            except Exception as e:
                st.error(f"No se pudo generar: {e}")
        return

    _vista_instructivo(pasos, f, key)
    if puede_editar:
        with st.expander("✏️ Editar pasos (no se guarda nada hasta Publicar)", expanded=False):
            _editor(pasos, f, key, USR, cat, conectar)
        with st.expander("🕘 Versiones", expanded=False):
            _historial(f, key, USR, cat, conectar)
