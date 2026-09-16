# -*- coding: utf-8 -*-
"""Stock del sector con el MODELO DE STOCK DE DIRECCIÓN: una cuenta corriente por producto.

Modelo entregado por dirección (15/09/2026, planilla "modelo_stock"):

    · Una hoja por producto, y el producto se nombra corriente + producto + calidad
      (V-AFE-S, V-AG-E: V = vegetal, A = animal).
    · Cada hoja es una cuenta corriente:
          FECHA · ORIGEN · DESTINO · N° TICKET · INGRESO · EGRESO · SALDO · DESCRIPCIÓN
      arrancando en un SALDO INICIAL y con el saldo corriendo fila por fila.
      Origen y destino van en columnas separadas: todo movimiento tiene los dos.
    · Una hoja REPORTE con el saldo consolidado de todos los productos a una fecha.
    · "El stock se tiene que ver por producto y sólo el Q" — la cantidad. Después se
      cruza con laboratorio y producción.

Acá está eso mismo, sin planilla: el Q sale del libro de movimientos de la planta
(produccion.v_stock_cuenta_sector), que atribuye cada movimiento a un sector por el
TANQUE, así que cada sector ve lo suyo y nada más.

El SALDO INICIAL es un número monitoreable, no un acumulado infinito: el PRIMER DÍA HÁBIL de
cada mes queda grabado el stock de cada producto con la medición física de los tanques del
sector (produccion.fact_stock_saldo_inicial, automático a las 3:30 y botón para rehacerlo).
Contra ese número corre la cuenta corriente del mes, y la diferencia contra lo que miden los
tanques hoy es el desvío del mes — lo que dirección quiere monetizar.

Están TODOS los productos que pasaron por los tanques del sector: no se esconde ninguno. La
columna DESCRIPCIÓN dice qué es cada uno y qué papel juega ahí — si sale por ODV o si sólo
está acopiado (produccion.v_cuenta_sector) — y el filtro de arriba deja mirar una parte.
Así se ve de una por qué en Exportación aparece, por ejemplo, AFE Soja con goma: está
guardado en un tanque de plataforma y nunca salió por una orden de venta.

La calidad la define laboratorio y la cuenta se abre por calidad. En la familia AFE el grado
sale del azufre y el fósforo del TANQUE, con la misma regla que ya usa el brief de dirección
(produccion.fn_categoria_afe: A hasta el 80% del límite, B 90%, C 100%, D por encima), así que
el AFE de soja se lleva en V-AFE-S-A, V-AFE-S-C y V-AFE-S-D. Nunca queda "sin calidad": un
tanque que laboratorio todavía no calificó va a V-AFE-S-NE, NO EVALUADO, y se lista con el
ticket de su último ingreso para ir a buscar la muestra. La letra que distingue al
producto no es calidad: AFE-S es AFE Soja, corriente vegetal.

Unidad: TN por defecto (litros × densidad del producto), con opción de verlo en KL
como viene la planilla.
"""

import io

import pandas as pd
import streamlit as st

from . import periodo as _per
from .kpis import _FRAGMENT, _TTL, _kpi, _n, _rerun_fragment

_GRUPO_LBL = {"MP": "Materia prima", "INSUMO": "Insumos", "PT": "Producto terminado", "OTRO": "Otros"}
_UM = {"TN": ("kg_neto", 1000.0), "KL": ("litros_neto", 1000.0)}
_COLS = ("id_mov, momento, fecha, cuenta, cuenta_nombre, calidad, corriente_nombre, producto, grupo, "
         "tipo, origen, destino, ticket, tickets_detalle, contraparte, kg_neto, litros_neto, "
         "referencia, usuario, es_ajuste_sistema, observacion, tanque, es_del_sector")


# ------------------------------------------------------------------ datos
@st.cache_data(ttl=_TTL, show_spinner=False)
def _movs(_cf, sector, desde, hasta):
    sql = (f"SELECT {_COLS} FROM produccion.v_stock_cuenta_sector "
           "WHERE sector = %s AND fecha BETWEEN %s AND %s ORDER BY momento, id_mov")
    try:
        with _cf() as conn:
            df = pd.read_sql_query(sql, conn, params=(sector, desde, hasta))
        for c in ("kg_neto", "litros_neto"):
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0).astype(float)
        df["es_ajuste_sistema"] = df["es_ajuste_sistema"].fillna(False).astype(bool)
        df["es_del_sector"] = df["es_del_sector"].fillna(False).astype(bool)
        df["cuenta"] = df["cuenta"].fillna("(sin producto)")
        return df
    except Exception:
        return None


@st.cache_data(ttl=_TTL, show_spinner=False)
def _saldo_inicial(_cf, sector, desde):
    """El saldo con el que arranca el período, por cuenta.

    Sale de produccion.fn_stock_saldo_a: toma el último CORTE cargado (el saldo inicial
    del mes, que se toma de la medición física de los tanques el día 1) y le suma los
    movimientos entre el corte y el inicio del período. Si todavía no hay ningún corte
    para el sector, cae al arrastre del libro entero y lo dice."""
    sql = ("SELECT cuenta, cuenta_nombre, calidad, corriente_nombre, kg_neto, litros_neto, "
           "base_fecha, base_fuente FROM produccion.fn_stock_saldo_a(%s, %s)")
    try:
        with _cf() as conn:
            df = pd.read_sql_query(sql, conn, params=(sector, desde))
        for c in ("kg_neto", "litros_neto"):
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0).astype(float)
        df["cuenta"] = df["cuenta"].fillna("(sin producto)")
        return df
    except Exception:
        return None


def _cerrar_corte(conectar, USR, sector, fecha):
    """Deja grabado el saldo inicial del mes: la foto física de los tanques del sector.
    Pasa por conectar() como cualquier escritura de la app: auditoría y commit."""
    with conectar(int(USR["id_usuario"])) as (conn, _audit):
        with conn.cursor() as cur:
            cur.execute("SELECT r_cuentas, r_tn FROM produccion.fn_stock_cerrar_saldo_inicial(%s, %s, %s)",
                        (sector, fecha, int(USR["id_usuario"])))
            row = cur.fetchone()
    return row


@st.cache_data(ttl=_TTL, show_spinner=False)
def _cuentas(_cf, sector):
    """Qué es cada producto del sector y qué papel juega: si se exporta o sólo está acopiado.
    Es la columna DESCRIPCIÓN y el filtro de la pantalla (produccion.v_cuenta_sector)."""
    sql = ("SELECT cuenta, descripcion, rol, del_sector, producto_codigo, tanques_en_uso, "
           "salidas_odv, tn_odv FROM produccion.v_cuenta_sector WHERE sector = %s")
    try:
        with _cf() as conn:
            df = pd.read_sql_query(sql, conn, params=(sector,))
        df["descripcion"] = df["descripcion"].fillna("")
        df["rol"] = df["rol"].fillna("HISTORICO")
        return df
    except Exception:
        return pd.DataFrame(columns=["cuenta", "descripcion", "rol", "del_sector",
                                     "producto_codigo", "tanques_en_uso", "salidas_odv", "tn_odv"])


@st.cache_data(ttl=_TTL, show_spinner=False)
def _sin_evaluar(_cf, sector):
    """Lo que está en tanque esperando que laboratorio lo califique, con el ticket del último
    ingreso para ir a buscarlo. Es la cuenta NO EVALUADO."""
    sql = ("SELECT tanque, grupo_fisico, producto, tn, ultimo_ticket, fecha_ultimo_ingreso, "
           "ultimo_proveedor, dias_desde_el_ingreso, ultima_medicion, metodo_medicion, "
           "tanque_dado_de_alta, dias_de_alta, movimientos_reales, medicion_al_tope "
           "FROM produccion.v_stock_sin_evaluar WHERE sector = %s ORDER BY tn DESC")
    try:
        with _cf() as conn:
            return pd.read_sql_query(sql, conn, params=(sector,))
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=_TTL, show_spinner=False)
def _medido_tanques(_cf, sector):
    """Control: lo que hoy hay MEDIDO en los tanques del sector (TN y KL)."""
    sql = ("SELECT COALESCE(SUM(act_tn),0) AS tn, COALESCE(SUM(act_l),0)/1000.0 AS kl "
           "FROM produccion.v_acopio_sector WHERE sector = %s AND activo "
           "AND condicion <> 'FUERA DE USO'")
    try:
        with _cf() as conn:
            df = pd.read_sql_query(sql, conn, params=(sector,))
        return (float(df.iloc[0]["tn"]), float(df.iloc[0]["kl"])) if not df.empty else None
    except Exception:
        return None


def invalidar():
    _movs.clear(); _saldo_inicial.clear(); _medido_tanques.clear(); _cuentas.clear(); _sin_evaluar.clear()


# ------------------------------------------------------------------ helpers
def _col(df, nombre, defecto=None):
    """La columna si está; si no, una vacía. Para que una vista vieja no rompa la pantalla."""
    if nombre in df.columns:
        return df[nombre]
    return pd.Series([defecto] * len(df), index=df.index)


def _q(x, cero="—"):
    """La cantidad, con un decimal. Cero se escribe, no se deja en blanco."""
    if x is None or pd.isna(x) or abs(float(x)) < 0.05:
        return cero
    return f"{float(x):,.1f}"


def _od(v, col):
    """ORIGEN y DESTINO, cada uno en su columna: de dónde salió y a dónde fue el producto.
    Dirección los quiere separados — en un movimiento de stock los dos son un dato."""
    return v[col].fillna("").replace("", "—")


def _cuenta_corriente(v, saldo_ini, etiqueta_ini, comentario_ini=""):
    """La hoja del producto tal cual la pidió dirección, con el saldo corriendo."""
    cols = ["ID", "FECHA", "ORIGEN", "DESTINO", "N° TICKET", "INGRESO", "EGRESO", "SALDO", "DESCRIPCIÓN"]
    if v.empty:                      # producto con saldo de arrastre y sin movimientos en el período
        filas = pd.DataFrame(columns=cols)
    else:
        filas = _filas(v, saldo_ini)
    cab = pd.DataFrame([{
        "ID": "", "FECHA": etiqueta_ini, "ORIGEN": "SALDO INICIAL", "DESTINO": "—", "N° TICKET": "",
        "INGRESO": "", "EGRESO": "", "SALDO": f"{float(saldo_ini):,.1f}",
        "DESCRIPCIÓN": comentario_ini,
    }])
    return pd.concat([cab, filas], ignore_index=True)[cols]


def _filas(v, saldo_ini):
    ing = v["_val"].map(lambda x: x if x > 0 else 0.0)
    egr = v["_val"].map(lambda x: -x if x < 0 else 0.0)
    saldo = saldo_ini + (ing - egr).cumsum()
    return pd.DataFrame({
        "ID": v["id_mov"].map(lambda i: "" if pd.isna(i) else f"{int(i)}"),
        "FECHA": v["momento"].map(lambda t: pd.to_datetime(t).strftime("%d/%m/%Y %H:%M") if not pd.isna(t) else ""),
        "ORIGEN": _od(v, "origen"),
        "DESTINO": _od(v, "destino"),
        "N° TICKET": v["ticket"].fillna(""),
        "INGRESO": ing.map(lambda x: _q(x, "")),
        "EGRESO": egr.map(lambda x: _q(x, "")),
        "SALDO": saldo.map(lambda x: f"{float(x):,.1f}"),
        # Qué fue ese movimiento, en palabras. Si nadie escribió nada, se arma con lo que hay:
        # de dónde vino o a dónde fue, para que ninguna fila quede sin explicación.
        "DESCRIPCIÓN": [(o or r or d) for o, r, d in
                        zip(v["observacion"].fillna(""), v["referencia"].fillna(""),
                            (v["tipo"].fillna("").map({"ENTRADA": "Entrada", "SALIDA": "Salida",
                                                       "AJUSTE": "Ajuste de medición"})
                             .fillna("Movimiento")))],
    })


_ROL_TXT = {"EXPORTA": "sale por ODV", "ACOPIO": "sólo acopio, no sale por ODV",
            "TANQUE FUERA DE USO": "tanque fuera de uso", "HISTORICO": "ya no está en ningún tanque"}
# El filtro arranca en "Del sector": los productos que el sector despacha o que el maestro de
# productos le asigna. Lo demás está en sus tanques por una designación equivocada — se sigue
# pudiendo ver con "Todos", pero no ensucia la pantalla de todos los días.
# El filtro depende de lo que hace el sector. Exportación mira lo que embarca; un sector de
# proceso (Reactores, Bachas, Piletas) mira su producción: materia prima, insumos y producto
# final. En los dos casos "Del sector" es lo que le pertenece y "Todos" muestra hasta lo que
# está ahí por una designación de tanque equivocada.
_FILTRO_EXPO = {"Lo que exportamos": "EXPORTA", "Del sector": "DEL_SECTOR",
                "Sólo acopio": "ACOPIO", "Todos": None}
_FILTRO_PROD = {"Del sector": "DEL_SECTOR", "Materia prima": "G:MP", "Insumos": "G:INSUMO",
                "Producto final": "G:PT", "Todos": None}
_GRUPO_NOM = {"MP": "materia prima", "INSUMO": "insumos", "PT": "producto final"}


def _describir(cta, cuentas):
    """Qué es el producto y qué hace en este sector. Contesta de una la pregunta "¿y esto qué
    tiene que ver con exportación?": dice si salió alguna vez por una ODV o si sólo está acopiado."""
    if cuentas is None or cuentas.empty:
        return ""
    f = cuentas[cuentas["cuenta"] == cta]
    if f.empty:
        return ""
    r = f.iloc[0]
    txt = (r.get("descripcion") or "").strip()
    rol = _ROL_TXT.get(r.get("rol"), "")
    tn = float(r.get("tn_odv") or 0)
    if r.get("rol") == "EXPORTA" and tn >= 0.05:
        rol = f"sale por ODV ({tn:,.0f} TN embarcadas)"
    if not bool(r.get("del_sector", True)):
        rol = "⚠️ no es un producto de este sector: está acá porque un tanque quedó designado así"
    return " · ".join(x for x in (txt, rol) if x)


def _reporte(v, ini, um, cuentas=None, exporta=True):
    """La hoja REPORTE: saldo consolidado por producto al cierre del período.

    Lo que se exporta va primero y con su propia columna: es lo que mira dirección."""
    _D = ["cuenta_nombre", "calidad", "corriente_nombre"]
    v = v.copy()
    if exporta:   # lo que salió por una orden de venta, separado del resto de los egresos
        v["_foco"] = [e if str(d or "").startswith("ODV") else 0.0
                      for e, d in zip(v["_egr"], v["destino"])]
    else:         # lo que el sector produjo: las entradas de producto final
        v["_foco"] = [i if g == "PT" else 0.0 for i, g in zip(v["_ing"], v["grupo"])]
    mov = v.groupby("cuenta", dropna=False, as_index=False).agg(
        ING=("_ing", "sum"), EGR=("_egr", "sum"), ODV=("_foco", "sum"))
    base = (ini.groupby("cuenta", dropna=False, as_index=False).agg(INI=("_val", "sum"))
            if not ini.empty else pd.DataFrame({"cuenta": [], "INI": []}))
    g = mov.merge(base, on="cuenta", how="outer")
    # El nombre, la calidad y la corriente de la cuenta salen de donde aparezca: una cuenta puede
    # tener saldo de arrastre y ningún movimiento en el período (o al revés).
    desc = pd.concat([x[["cuenta"] + _D] for x in (v, ini) if not x.empty and set(_D) <= set(x.columns)],
                     ignore_index=True) if (not v.empty or not ini.empty) else pd.DataFrame(columns=["cuenta"] + _D)
    if not desc.empty:
        desc = desc.dropna(subset=["cuenta"]).drop_duplicates(subset=["cuenta"], keep="first")
        g = g.merge(desc, on="cuenta", how="left")
    for c in _D:
        if c not in g.columns:
            g[c] = None
    for c in ("ING", "EGR", "INI", "ODV"):
        if c not in g.columns:
            g[c] = 0.0
        g[c] = pd.to_numeric(g[c], errors="coerce").fillna(0.0)
    g["FIN"] = g["INI"] + g["ING"] - g["EGR"]
    # primero lo que se exportó (o se produjo) en el período, después el resto por saldo
    g = g.sort_values(["ODV", "FIN"], ascending=[False, False])
    out = pd.DataFrame({
        "CUENTA": g["cuenta"].fillna("(sin producto)"),
        "PRODUCTO": g["cuenta_nombre"].fillna(""),
        "DESCRIPCIÓN": [_describir(c, cuentas) for c in g["cuenta"]],
        "CALIDAD": g["calidad"].fillna("—"),
        "CORRIENTE": g["corriente_nombre"].fillna("—"),
        f"SALDO INICIAL {um}": g["INI"].map(lambda x: _q(x, "0.0")),
        f"INGRESOS {um}": g["ING"].map(_q),
        (f"EXPORTADO {um}" if exporta else f"PRODUCIDO {um}"): g["ODV"].map(_q),
        f"EGRESOS {um}": g["EGR"].map(_q),
        f"SALDO FINAL {um}": g["FIN"].map(lambda x: _q(x, "0.0")),
    })
    tot = pd.DataFrame([{
        "CUENTA": "TOTAL", "PRODUCTO": f"{len(g)} producto(s)", "DESCRIPCIÓN": "",
        "CALIDAD": "", "CORRIENTE": "",
        f"SALDO INICIAL {um}": f"{g['INI'].sum():,.1f}", f"INGRESOS {um}": f"{g['ING'].sum():,.1f}",
        (f"EXPORTADO {um}" if exporta else f"PRODUCIDO {um}"): f"{g['ODV'].sum():,.1f}",
        f"EGRESOS {um}": f"{g['EGR'].sum():,.1f}", f"SALDO FINAL {um}": f"{g['FIN'].sum():,.1f}",
    }])
    return pd.concat([out, tot], ignore_index=True), g


def _control(ctx, sec, cod, um, s_fin, ini):
    """De dónde sale el saldo inicial y cuánto se aparta el libro de los tanques.

    El saldo inicial es el stock del PRIMER DÍA HÁBIL del mes, guardado en
    produccion.fact_stock_saldo_inicial: se toma de la medición física de los tanques del
    sector. Contra ese número corre la cuenta corriente del mes."""
    base_f, base_fte = None, "LIBRE"
    if not ini.empty and "base_fecha" in ini.columns:
        _b = ini["base_fecha"].dropna()
        base_f = pd.to_datetime(_b.iloc[0]).date() if len(_b) else None
        if ini["base_fuente"].notna().any():
            base_fte = ini["base_fuente"].dropna().iloc[0]

    med = _medido_tanques(ctx["conn_factory"], cod)
    fisico = (med[0] if um == "TN" else med[1]) if med else None
    c1, c2 = st.columns([4, 1.3])
    if base_f is not None:
        txt = (f"**Saldo inicial del {base_f:%d/%m/%Y}** (primer día hábil del mes), tomado de la medición "
               f"física de los tanques de {sec['nombre_ui']}. El libro corre desde ahí.")
    else:
        txt = (f"**Todavía no hay saldo inicial cargado para {sec['nombre_ui']}.** Lo que se muestra es el "
               "arrastre del libro entero, así que no cierra contra los tanques. Cerrá el saldo inicial "
               "del mes para que empiece a cerrar.")
    if fisico is not None:
        dif = s_fin - fisico
        txt += (f" Hoy los tanques miden **{fisico:,.1f} {um}** y el libro cierra en **{s_fin:,.1f} {um}**: "
                f"diferencia de **{dif:+,.1f} {um}**.")
    c1.caption(txt)

    # Una cuenta con saldo inicial negativo no es un error de cálculo: el libro tiene más
    # entradas que lo que el tanque muestra hoy (salidas sin cargar o cambios de categoría sin
    # asentar). Se avisa por nombre para que se corrija en el origen.
    if not ini.empty:
        _neg = ini.loc[ini["_val"] < -0.05, "cuenta"].tolist() if "_val" in ini.columns else []
        if _neg:
            c1.caption("⚠️ Arrancan en negativo: **" + ", ".join(_neg) + "**. El libro registra más entradas "
                       "que lo que hoy hay en el tanque: falta cargar salidas o asentar un cambio de "
                       "categoría. Es el desvío a corregir en la carga, no un error de la pantalla.")

    # Lo que espera laboratorio: la cuenta NO EVALUADO, con el ticket para ir a buscarlo.
    ne = _sin_evaluar(ctx["conn_factory"], cod)
    if ne is not None and not ne.empty:
        _tn = float(pd.to_numeric(ne["tn"], errors="coerce").fillna(0).sum())
        with st.expander(f"🧪 Esperando laboratorio: {_tn:,.1f} TN sin calificar en {len(ne)} tanque(s)",
                         expanded=False):
            st.dataframe(pd.DataFrame({
                "TANQUE": ne["tanque"].fillna(""),
                "DÓNDE": ne["grupo_fisico"].fillna(""),
                "PRODUCTO": ne["producto"].fillna(""),
                "TN": pd.to_numeric(ne["tn"], errors="coerce").map(lambda x: f"{float(x):,.1f}"),
                "TICKET DEL ÚLTIMO INGRESO": ne["ultimo_ticket"].fillna("— ninguno"),
                "PROVEEDOR": ne["ultimo_proveedor"].fillna("—"),
                "INGRESOS CARGADOS": _col(ne, "movimientos_reales").map(
                    lambda n: "" if pd.isna(n) else f"{int(n)}"),
                "TANQUE DADO DE ALTA": [
                    ("" if pd.isna(f) else f"{pd.to_datetime(f):%d/%m/%Y}"
                     + ("" if pd.isna(d) else f" · hace {int(d)} días"))
                    for f, d in zip(_col(ne, "tanque_dado_de_alta"), _col(ne, "dias_de_alta"))],
                "MEDICIÓN": [f"{m or '—'}" + (" · cargada justo al tope de capacidad ⚠️" if t else "")
                             for m, t in zip(_col(ne, "metodo_medicion"),
                                             _col(ne, "medicion_al_tope").fillna(False).astype(bool))],
            }), hide_index=True, use_container_width=True,
                column_config={"TANQUE DADO DE ALTA": st.column_config.TextColumn(width="medium"),
                               "MEDICIÓN": st.column_config.TextColumn(width="medium")})
            st.caption("Estas toneladas están en la cuenta NO EVALUADO: el tanque no tiene azufre ni "
                       "fósforo cargados, así que el sistema no puede darle calidad. Casi todos los "
                       "tanques sí están evaluados, por eso los que caen acá son la excepción y valen "
                       "una revisada: **si no tiene ingresos cargados**, las toneladas entraron por una "
                       "medición manual y no por portería — nadie le tomó muestra porque para el "
                       "sistema nunca llegó nada. **Si además la medición quedó justo al tope de la "
                       "capacidad**, lo más probable es que se haya cargado el tanque como lleno en "
                       "lugar de medirlo.")

    conectar = ctx.get("conectar")
    if conectar is not None and ctx["puede_seccion"]("STOCK"):
        from datetime import date
        hoy = date.today()
        _pdh = date(hoy.year, hoy.month, 1)
        while _pdh.weekday() >= 5:
            _pdh = _pdh.fromordinal(_pdh.toordinal() + 1)
        if c2.button(f"🔄 Recalcular el stock del {_pdh:%d/%m}", key=f"nav_mv_corte_{cod}",
                     use_container_width=True,
                     help=(f"Vuelve a calcular con qué stock arrancó el mes cada producto: toma la "
                           f"medición de los tanques de hoy y le resta todo lo que entró y salió desde "
                           f"el {_pdh:%d/%m}. Sirve cuando se corrigió una medición o se cargó un "
                           "movimiento viejo. El día 1 de cada mes se hace solo.")):
            try:
                row = _cerrar_corte(conectar, ctx["USR"], cod, hoy)
                invalidar()
                st.success(f"Saldo inicial recalculado: {int(row[0])} producto(s), {float(row[1]):,.1f} TN.")
                _rerun_fragment()
            except Exception as e:
                st.error(f"No se pudo recalcular el saldo inicial: {e}")
    return (f"stock del {base_f:%d/%m/%Y} · medición de los tanques" if base_f is not None
            else "arrastre del libro (todavía sin saldo inicial cargado)")


def _ir_stock_clasico(ctx):
    def _cb():
        st.session_state.section = "STOCK"
    return _cb


# ------------------------------------------------------------------ pantalla
@_FRAGMENT
def _movimientos(ctx, sec):
    cod = sec["codigo"]
    desde, hasta, etiqueta = _per.selector(f"stk_{cod}")

    cuentas = _cuentas(ctx["conn_factory"], cod)
    # Un sector de proceso (dim_sector_nav.sector_batch) mira su producción: materia prima,
    # insumos y producto final. Reactores despacha algo por ODV, pero lo suyo es producir.
    # Exportación no produce: lo suyo es embarcar.
    _batch = (sec.get("sector_batch") or "").upper()
    exporta = _batch in ("", "EXPO")
    FIL = _FILTRO_EXPO if exporta else _FILTRO_PROD

    c1, c2, c3, c4 = st.columns([0.9, 1.9, 1.5, 0.5])
    um = c1.radio("Unidad", list(_UM), horizontal=True, key=f"nav_mv_um_{cod}",
                  label_visibility="collapsed",
                  help="Toneladas (los litros se pasan con la densidad del producto) o kilolitros.")
    # Están todos los productos; este filtro es para mirar sólo una parte, no para esconder.
    k_rol = f"nav_mv_rol_{cod}"
    if st.session_state.get(k_rol) not in FIL:
        st.session_state[k_rol] = list(FIL)[0]
    rol = c2.radio("Qué productos", list(FIL), horizontal=True, key=k_rol,
                   label_visibility="collapsed",
                   help=("«Del sector» es lo que el sector trabaja: lo que despacha, lo que el maestro "
                         "de productos le asigna y los insumos que consume. Materia prima, insumos y "
                         "producto final filtran por lo que se movió en el período. «Todos» agrega lo "
                         "que está en sus tanques por una designación equivocada, para corregirlo."))
    busca = c3.text_input("Buscar", key=f"nav_mv_q_{cod}", placeholder="ID, ticket, cliente, producto…",
                          label_visibility="collapsed")
    if c4.button("↻", key=f"nav_mv_ref_{cod}", use_container_width=True, help="Releer ahora"):
        invalidar(); _rerun_fragment()

    col, div = _UM[um]
    df = _movs(ctx["conn_factory"], cod, desde, hasta)
    ini = _saldo_inicial(ctx["conn_factory"], cod, desde)
    if df is None or ini is None:
        st.caption("Sin conexión a la base en este momento.")
        return

    ajustes_n = int(df["es_ajuste_sistema"].sum())
    # Están TODOS los productos que pasaron por los tanques del sector: no se esconde ninguno.
    # Lo que decide qué mirar es el filtro de abajo, y la columna DESCRIPCIÓN dice qué es cada
    # producto y si se exporta o sólo está acopiado ahí.
    v = df[~df["es_ajuste_sistema"]].copy()
    v["_val"] = v[col] / div
    v["_ing"] = v["_val"].map(lambda x: x if x > 0 else 0.0)
    v["_egr"] = v["_val"].map(lambda x: -x if x < 0 else 0.0)
    ini = ini.copy()
    ini["_val"] = ini[col] / div
    _f = FIL.get(rol)
    if _f and _f.startswith("G:"):
        # por lo que se movió en el período: las cuentas con materia prima, insumos o producto
        # final. Los saldos siguen siendo los de la cuenta entera, no los del grupo.
        _g = _f[2:]
        _ok = set(v.loc[v["grupo"] == _g, "cuenta"])
        v = v[v["cuenta"].isin(_ok)]
        ini = ini[ini["cuenta"].isin(_ok)]
        if not _ok:
            st.info(f"Sin movimientos de {_GRUPO_NOM.get(_g, _g)} en {sec['nombre_ui']} · {etiqueta}.")
            return
    elif _f and not cuentas.empty:
        if _f == "DEL_SECTOR":
            _ok = set(cuentas.loc[cuentas["del_sector"].fillna(True).astype(bool), "cuenta"])
        elif _f == "EXPORTA":
            # por PRODUCTO, no por calidad: el AFE-S que espera laboratorio también se exporta
            _pe = set(cuentas.loc[cuentas["salidas_odv"].fillna(0) > 0, "producto_codigo"])
            _ok = set(cuentas.loc[cuentas["producto_codigo"].isin(_pe), "cuenta"])
        else:
            _ok = set(cuentas.loc[cuentas["rol"] == _f, "cuenta"])
        v = v[v["cuenta"].isin(_ok)]
        ini = ini[ini["cuenta"].isin(_ok)]
        _aj = cuentas.loc[~cuentas["del_sector"].fillna(True).astype(bool), "cuenta"]
        if _f in ("DEL_SECTOR", "EXPORTA") and len(_aj):
            st.caption(f"Se dejan afuera {len(_aj)} producto(s) que no son de {sec['nombre_ui']} "
                       f"({', '.join(sorted(_aj)[:6])}{'…' if len(_aj) > 6 else ''}): están en sus "
                       "tanques porque quedaron designados así. Con «Todos» se ven, para corregirlos.")

    if v.empty and float(ini["_val"].abs().sum()) == 0:
        st.info(f"Sin movimientos de {sec['nombre_ui']} en {etiqueta}.")
        return

    s_ini = float(ini["_val"].sum())
    s_ing, s_egr = float(v["_ing"].sum()), float(v["_egr"].sum())
    s_fin = s_ini + s_ing - s_egr
    _u = f"<span style='font-size:1rem;font-weight:700;'> {um}</span>"
    if exporta:
        # Exportación: lo que se embarcó va primero, es lo que mira dirección.
        _es_odv = v["destino"].fillna("").astype(str).str.startswith("ODV")
        s_odv = float(v.loc[_es_odv, "_egr"].sum())
        n_odv = int(v.loc[_es_odv, "destino"].nunique())
        k0 = _kpi("Exportado en el período", f"{_n(s_odv,1)}{_u}",
                  (f"{n_odv} orden(es) de venta · " if n_odv else "sin embarques · ")
                  + f"{(100.0 * s_odv / s_egr if s_egr else 0):.0f}% de lo que salió",
                  "ok" if s_odv else "")
        _egr_det = (f"{_n(s_egr - s_odv,1)} {um} a proceso" if s_egr - s_odv >= 0.05
                    else "todo por ODV")
    else:
        # Sector de proceso: lo que produjo, y con qué. Es el movimiento de producción del sector.
        _pt = float(v.loc[v["grupo"] == "PT", "_ing"].sum())
        _mp = float(v.loc[v["grupo"] == "MP", "_egr"].sum())
        _in = float(v.loc[v["grupo"] == "INSUMO", "_egr"].sum())
        k0 = _kpi("Producido en el período", f"{_n(_pt,1)}{_u}",
                  f"con {_n(_mp,1)} {um} de materia prima"
                  + (f" y {_n(_in,1)} {um} de insumos" if _in >= 0.05 else ""),
                  "ok" if _pt else "")
        _egr_det = (f"{_n(_mp,1)} {um} de materia prima a proceso" if _mp >= 0.05
                    else "sin materia prima a proceso")
    k1 = _kpi("Saldo inicial", f"{_n(s_ini,1)}{_u}", f"con lo que arranca {etiqueta}", "")
    k2 = _kpi("Ingresos del período", f"{_n(s_ing,1)}{_u}", f"{int((v['_val'] > 0).sum())} movimientos", "")
    k3 = _kpi("Egresos del período", f"{_n(s_egr,1)}{_u}",
              f"{int((v['_val'] < 0).sum())} movimientos · " + _egr_det, "")
    k4 = _kpi("Saldo final", f"{_n(s_fin,1)}{_u}",
              f"{(s_fin - s_ini):+,.1f} {um} en el período · sólo {sec['nombre_ui']}",
              "warn" if s_fin < 0 else "ok")
    st.markdown(f'<div class="kpi-grid">{k0}{k1}{k2}{k3}{k4}</div>', unsafe_allow_html=True)

    # ---------------- REPORTE: saldo consolidado por producto ----------------
    st.markdown("<div class='section-title' style='margin:10px 0 2px'>Saldo consolidado por producto</div>",
                unsafe_allow_html=True)
    rep, g = _reporte(v, ini, um, cuentas, exporta)
    st.dataframe(rep, hide_index=True, use_container_width=True, height=min(520, 60 + 35 * len(rep)),
                 column_config={"CUENTA": st.column_config.TextColumn(width="small"),
                                "PRODUCTO": st.column_config.TextColumn(width="small"),
                                "DESCRIPCIÓN": st.column_config.TextColumn(width="large")})

    _txt_ini = _control(ctx, sec, cod, um, s_fin, ini)

    # ---------------- La hoja del producto: cuenta corriente ----------------
    # el orden es el del reporte (saldo de mayor a menor): lo primero que se abre es lo que más pesa
    ctas = [c for c in g["cuenta"].tolist() if pd.notna(c)]
    if not ctas:
        return
    st.markdown("<div class='section-title' style='margin:14px 0 2px'>Cuenta corriente del producto</div>",
                unsafe_allow_html=True)
    k_c = f"nav_mv_cta_{cod}"
    if st.session_state.get(k_c) not in ctas:
        st.session_state[k_c] = ctas[0]
    _nom = dict(zip(g["cuenta"], g["cuenta_nombre"].fillna("")))
    cta = st.selectbox("Producto", ctas, key=k_c, label_visibility="collapsed",
                       format_func=lambda c: " · ".join(x for x in (c, _nom.get(c, ""),
                                                                    _describir(c, cuentas)) if x))

    w = v[v["cuenta"] == cta].sort_values(["momento", "id_mov"])
    if busca.strip():
        q = busca.strip().lower()
        m = w["id_mov"].astype(str).str.contains(q, regex=False)
        for c in ("ticket", "tickets_detalle", "contraparte", "origen", "destino", "referencia", "observacion"):
            m = m | w[c].fillna("").astype(str).str.lower().str.contains(q, regex=False)
        w = w[m]
    s_ini_cta = float(ini.loc[ini["cuenta"] == cta, "_val"].sum())
    tabla = _cuenta_corriente(w, s_ini_cta, f"al {desde:%d/%m/%Y}", _txt_ini)
    st.dataframe(tabla, hide_index=True, use_container_width=True, height=min(620, 60 + 35 * len(tabla)),
                 column_config={"ORIGEN": st.column_config.TextColumn(width="medium"),
                                "DESTINO": st.column_config.TextColumn(width="medium"),
                                "DESCRIPCIÓN": st.column_config.TextColumn(width="medium")})
    st.caption(f"Cantidades en **{um}**. Cada fila es un movimiento de {sec['nombre_ui']} y de ningún otro "
               "sector, con su ID del libro de stock y el ticket de portería. El saldo corre de arriba hacia "
               "abajo, arrancando en el saldo inicial."
               + (f" Quedan afuera {ajustes_n} ajustes automáticos de medición, que no son mercadería que "
                  "entró o salió." if ajustes_n else ""))

    # ---------------- Excel: el mismo libro que la planilla ----------------
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        rep.to_excel(xw, index=False, sheet_name="REPORTE")
        for c in ctas[:40]:
            hoja = str(c)[:28].replace("/", "-").replace("\\", "-").replace(":", "-")
            _w = v[v["cuenta"] == c].sort_values(["momento", "id_mov"])
            _si = float(ini.loc[ini["cuenta"] == c, "_val"].sum())
            _cuenta_corriente(_w, _si, f"al {desde:%d/%m/%Y}", _txt_ini).to_excel(xw, index=False,
                                                                                 sheet_name=hoja)

    st.download_button("⬇️ Descargar Excel (una hoja por producto)", buf.getvalue(),
                       file_name=f"stock_{cod.lower()}_{desde:%Y%m%d}_{hasta:%Y%m%d}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       key=f"nav_mv_xls_{cod}")


def render_stock(ctx, sec):
    puede = ctx["puede_seccion"]
    c1, c2 = st.columns([3, 1.2])
    c1.markdown(f"<div class='section-title' style='margin:6px 0'>📦 Stock · {sec['nombre_ui']} · "
                "cuenta corriente por producto</div>", unsafe_allow_html=True)
    if puede("STOCK"):
        c2.button("📋 Stock clásico (físico por tanque)", key="nav_cc_clasico", use_container_width=True,
                  on_click=_ir_stock_clasico(ctx))
    _movimientos(ctx, sec)
    st.caption("Modelo de stock de dirección: el producto se nombra corriente + producto + calidad "
               "(V = vegetal, A = animal; V-AFE-S es AFE Soja de corriente vegetal) y cada producto lleva "
               "su cuenta corriente con saldo inicial, ingresos, egresos y saldo. La calidad la define "
               "laboratorio y se muestra cuando es un grado: en la familia AFE sale del azufre y el "
               "fósforo del tanque (A hasta el 80% del límite, B 90%, C 100%, D por encima), así que "
               "el AFE-S se abre en V-AFE-S-A, -C y -D como está en los tanques; lo que laboratorio "
               "todavía no calificó va a NO EVALUADO, nunca sin calidad. El saldo inicial "
               "es el stock del primer día hábil del mes, medido en los tanques del sector. Sólo se "
               "muestran los productos de este sector.")
