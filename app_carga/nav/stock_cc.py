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

Cada sector mira lo suyo con su propia lente: Exportación embarca, Reactores produce y Piletas
recupera. En recuperación el movimiento es la pesada — ticket de portería y tanque asignado —,
así que la cuenta corriente lleva la columna TANQUE y el reporte compara el saldo del libro
contra lo que hoy miden esos tanques. Lo que entra por portería para disposición final (el
efluente líquido de las piletas) no es stock: entra y no vuelve a salir como mercadería, así que
se muestra aparte y no corre por la cuenta corriente.

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

import cache_rev as _cache_rev   # caché que una escritura invalida (no sólo el TTL)

from . import periodo as _per
from .kpis import _FRAGMENT, _TTL, _kpi, _n, _rerun_fragment

_GRUPO_LBL = {"MP": "Materia prima", "INSUMO": "Insumos", "PT": "Producto terminado", "OTRO": "Otros"}
_UM = {"TN": ("kg_neto", 1000.0), "KL": ("litros_neto", 1000.0)}
_COLS = ("id_mov, momento, fecha, cuenta, cuenta_nombre, calidad, corriente_nombre, producto, grupo, "
         "tipo, origen, destino, ticket, tickets_detalle, contraparte, kg_neto, litros_neto, "
         "referencia, usuario, es_ajuste_sistema, observacion, tanque, es_del_sector, sector, "
         "producto_codigo, fuente_dato, es_stock")


# ------------------------------------------------------------------ datos
@_cache_rev.cachear(ttl=_TTL, show_spinner=False)
def _movs(_cf, sector, desde, hasta):
    """`sector` puede ser un código o una tupla de códigos (para comparar sectores)."""
    _secs = list(sector) if isinstance(sector, (list, tuple)) else [sector]
    sql = (f"SELECT {_COLS} FROM produccion.v_stock_cuenta_sector "
           "WHERE sector = ANY(%s) AND fecha BETWEEN %s AND %s ORDER BY momento, id_mov")
    try:
        with _cf() as conn:
            df = pd.read_sql_query(sql, conn, params=(_secs, desde, hasta))
        for c in ("kg_neto", "litros_neto"):
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0).astype(float)
        df["es_ajuste_sistema"] = df["es_ajuste_sistema"].fillna(False).astype(bool)
        df["es_del_sector"] = df["es_del_sector"].fillna(False).astype(bool)
        if "es_stock" in df.columns:
            df["es_stock"] = df["es_stock"].fillna(True).astype(bool)
        df["cuenta"] = df["cuenta"].fillna("(sin producto)")
        return df
    except Exception:
        return None


@_cache_rev.cachear(ttl=_TTL, show_spinner=False)
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


@_cache_rev.cachear(ttl=600, show_spinner=False)
def _nombres(_cf):
    """Nombre oficial de cada producto: el de la planilla de parámetros (dim_producto).
    La pantalla mostraba el código («AFE-S calidad A»); dirección pidió el nombre tal cual
    la planilla («AFE Soja · calidad A»)."""
    try:
        with _cf() as conn:
            df = pd.read_sql_query("SELECT codigo_producto, nombre_producto FROM produccion.dim_producto", conn)
        return dict(zip(df["codigo_producto"].astype(str), df["nombre_producto"].fillna("").astype(str)))
    except Exception:
        return {}


@_cache_rev.cachear(ttl=600, show_spinner=False)
def _tanques_sector(_cf, sectores):
    """Los tanques que aparecen en el libro de esos sectores (para el filtro TK/ACOPIO)."""
    try:
        with _cf() as conn:
            df = pd.read_sql_query("SELECT DISTINCT tanque FROM produccion.v_stock_cuenta_sector "
                                   "WHERE sector = ANY(%s) AND tanque IS NOT NULL ORDER BY 1",
                                   conn, params=(list(sectores),))
        return df["tanque"].astype(str).tolist()
    except Exception:
        return []


@_cache_rev.cachear(ttl=600, show_spinner=False)
def _sectores_nav(_cf):
    try:
        with _cf() as conn:
            df = pd.read_sql_query("SELECT codigo, nombre_ui FROM produccion.dim_sector_nav "
                                   "WHERE COALESCE(activo,true) AND NOT COALESCE(en_construccion,false) "
                                   "ORDER BY nombre_ui", conn)
        return dict(zip(df["codigo"].astype(str), df["nombre_ui"].astype(str)))
    except Exception:
        return {}


def _nombre_cuenta(cuenta, cuentas, nombres):
    """«AFE Soja · calidad A»: nombre oficial + calidad, a partir de la cuenta V-AFE-S-A."""
    cod = None
    if cuentas is not None and not cuentas.empty:
        f = cuentas.loc[cuentas["cuenta"] == cuenta, "producto_codigo"]
        cod = str(f.iloc[0]) if len(f) and pd.notna(f.iloc[0]) else None
    nom = nombres.get(cod or "", "") if cod else ""
    cal = ""
    if cod and str(cuenta).startswith(("V-", "A-")):
        resto = str(cuenta)[2:]
        if resto.startswith(cod + "-"):
            cal = resto[len(cod) + 1:]
    if not nom:
        return str(cuenta)
    if cal == "NE":
        return f"{nom} · NO EVALUADO"
    return f"{nom} · calidad {cal}" if cal else nom


@_cache_rev.cachear(ttl=_TTL, show_spinner=False)
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


@_cache_rev.cachear(ttl=_TTL, show_spinner=False)
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


@_cache_rev.cachear(ttl=_TTL, show_spinner=False)
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


@_cache_rev.cachear(ttl=_TTL, show_spinner=False)
def _medido_cuenta(_cf, sector):
    """Qué tanques tiene asignados hoy cada producto del sector y cuánto miden.

    Es el otro lado del libro: la cuenta corriente dice cuánto debería haber, esto dice
    cuánto hay. En recuperación es además lo que el sector mira todos los días —
    "entró el ticket 6766 al Tanque X10 y el tanque hoy mide tanto"."""
    sql = ("SELECT cuenta, tanques, tanques_con_producto, tanques_txt, "
           "tanques_con_producto_txt, tn, kl FROM produccion.v_stock_medido_cuenta "
           "WHERE sector = %s")
    try:
        with _cf() as conn:
            df = pd.read_sql_query(sql, conn, params=(sector,))
        for c in ("tn", "kl"):
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0).astype(float)
        return df
    except Exception:
        return pd.DataFrame(columns=["cuenta", "tanques", "tanques_con_producto", "tanques_txt",
                                     "tanques_con_producto_txt", "tn", "kl"])


def invalidar():
    _movs.clear(); _saldo_inicial.clear(); _medido_tanques.clear(); _cuentas.clear()
    _sin_evaluar.clear(); _medido_cuenta.clear()


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


def _contraparte(v):
    """ORIGEN/DESTINO en UNA columna: de dónde vino o a dónde fue, y es el SECTOR, el
    PROVEEDOR o el CLIENTE — nunca el tanque. En una entrada la contraparte es el origen
    («Portería · BELTRAMO», «RE-407 · REACTOR 1»); en una salida, el destino («ODV 13 ·
    EGNITRADE (ROTTERDAM)»). El tanque va aparte, en TK/ACOPIO."""
    tipo = v["tipo"].fillna("")
    o = v["origen"].fillna("").astype(str)
    d = v["destino"].fillna("").astype(str)
    out = []
    for t, oo, dd in zip(tipo, o, d):
        if t == "ENTRADA":
            out.append(oo or "—")
        elif t == "SALIDA":
            out.append(dd or "—")
        else:
            out.append("Ajuste de medición")
    return pd.Series(out, index=v.index)


def _comentario(v):
    return [(o or r or d) for o, r, d in
            zip(v["observacion"].fillna(""), v["referencia"].fillna(""),
                (v["tipo"].fillna("").map({"ENTRADA": "Entrada", "SALIDA": "Salida",
                                           "AJUSTE": "Ajuste de medición"}).fillna("Movimiento")))]


def _cc_producto(v, saldo_ini, etiqueta_ini, comentario_ini=""):
    """CUENTA CORRIENTE DEL PRODUCTO, columnas pedidas por dirección (23/09):
    ID · FECHA · ORIGEN/DESTINO · TK/ACOPIO · N° TICKET · INGRESO · EGRESO · SALDO · COMENTARIOS."""
    cols = ["ID", "FECHA", "ORIGEN/DESTINO", "TK/ACOPIO", "N° TICKET", "INGRESO", "EGRESO", "SALDO", "COMENTARIOS"]
    cab = pd.DataFrame([{"ID": "", "FECHA": etiqueta_ini, "ORIGEN/DESTINO": "SALDO INICIAL", "TK/ACOPIO": "—",
                         "N° TICKET": "", "INGRESO": "", "EGRESO": "", "SALDO": f"{float(saldo_ini):,.1f}",
                         "COMENTARIOS": comentario_ini}])
    if v.empty:
        return cab[cols]
    ing = v["_val"].map(lambda x: x if x > 0 else 0.0)
    egr = v["_val"].map(lambda x: -x if x < 0 else 0.0)
    saldo = saldo_ini + (ing - egr).cumsum()
    filas = pd.DataFrame({
        "ID": v["id_mov"].map(lambda i: "" if pd.isna(i) else f"{int(i)}"),
        "FECHA": v["momento"].map(lambda t: pd.to_datetime(t).strftime("%d/%m/%Y %H:%M") if not pd.isna(t) else ""),
        "ORIGEN/DESTINO": _contraparte(v).values,
        "TK/ACOPIO": _col(v, "tanque", "").fillna("").replace("", "—").values,
        "N° TICKET": v["ticket"].fillna("").values,
        "INGRESO": ing.map(lambda x: _q(x, "")).values,
        "EGRESO": egr.map(lambda x: _q(x, "")).values,
        "SALDO": saldo.map(lambda x: f"{float(x):,.1f}").values,
        "COMENTARIOS": _comentario(v),
    })
    return pd.concat([cab, filas], ignore_index=True)[cols]


def _consolidado(v, ini, um, nombre_de):
    """SALDO CONSOLIDADO POR PRODUCTO: el libro de todos los productos elegidos, en orden de
    fecha, con el saldo corriendo por producto. Columnas pedidas por dirección (23/09):
    FECHA · PRODUCTO · ORIGEN/DESTINO · N° TICKET · UM · INGRESO · EGRESO · SALDO · COMENTARIO."""
    cols = ["FECHA", "PRODUCTO", "ORIGEN/DESTINO", "N° TICKET", "UM", "INGRESO", "EGRESO", "SALDO", "COMENTARIO"]
    partes = []
    ctas = sorted(set(v["cuenta"].dropna()) | set(ini["cuenta"].dropna()), key=lambda c: nombre_de(c))
    for c in ctas:
        w = v[v["cuenta"] == c].sort_values(["momento", "id_mov"])
        s0 = float(ini.loc[ini["cuenta"] == c, "_val"].sum())
        partes.append(pd.DataFrame([{"_t": pd.Timestamp.min, "FECHA": "SALDO INICIAL", "PRODUCTO": nombre_de(c),
                                     "ORIGEN/DESTINO": "—", "N° TICKET": "", "UM": um, "INGRESO": "", "EGRESO": "",
                                     "SALDO": f"{s0:,.1f}", "COMENTARIO": "con lo que arranca el período"}]))
        if w.empty:
            continue
        ing = w["_val"].map(lambda x: x if x > 0 else 0.0)
        egr = w["_val"].map(lambda x: -x if x < 0 else 0.0)
        saldo = s0 + (ing - egr).cumsum()
        partes.append(pd.DataFrame({
            "_t": pd.to_datetime(w["momento"]).values,
            "FECHA": w["momento"].map(lambda t: pd.to_datetime(t).strftime("%d/%m/%Y %H:%M") if not pd.isna(t) else "").values,
            "PRODUCTO": nombre_de(c),
            "ORIGEN/DESTINO": _contraparte(w).values,
            "N° TICKET": w["ticket"].fillna("").values,
            "UM": um,
            "INGRESO": ing.map(lambda x: _q(x, "")).values,
            "EGRESO": egr.map(lambda x: _q(x, "")).values,
            "SALDO": saldo.map(lambda x: f"{float(x):,.1f}").values,
            "COMENTARIO": _comentario(w),
        }))
    if not partes:
        return pd.DataFrame(columns=cols)
    out = pd.concat(partes, ignore_index=True)
    # saldos iniciales primero (todos), después los movimientos por fecha
    out = out.sort_values("_t", kind="stable")
    return out[cols].reset_index(drop=True)


def _cuenta_corriente(v, saldo_ini, etiqueta_ini, comentario_ini="", tanque=False):
    """La hoja del producto tal cual la pidió dirección, con el saldo corriendo.

    `tanque=True` agrega la columna TANQUE: en recuperación el tanque al que se asignó cada
    pesada es parte del movimiento, no un detalle — es donde hay que ir a buscar el producto."""
    cols = ["ID", "FECHA", "ORIGEN", "DESTINO", "N° TICKET", "INGRESO", "EGRESO", "SALDO", "DESCRIPCIÓN"]
    if tanque:
        cols.insert(4, "TANQUE")
    if v.empty:                      # producto con saldo de arrastre y sin movimientos en el período
        filas = pd.DataFrame(columns=cols)
    else:
        filas = _filas(v, saldo_ini)
        if tanque:
            filas["TANQUE"] = _col(v, "tanque", "").fillna("").replace("", "—").values
    cab = pd.DataFrame([{
        "ID": "", "FECHA": etiqueta_ini, "ORIGEN": "SALDO INICIAL", "DESTINO": "—", "TANQUE": "—",
        "N° TICKET": "", "INGRESO": "", "EGRESO": "", "SALDO": f"{float(saldo_ini):,.1f}",
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
                "Sólo acopio": "ACOPIO", "Todos (incluye mal cargados)": None}
_FILTRO_PROD = {"Del sector": "DEL_SECTOR", "Materia prima": "G:MP", "Insumos": "G:INSUMO",
                "Producto final": "G:PT", "Todos (incluye mal cargados)": None}
# Piletas recupera: lo que se mira todos los días es el ácido graso que se recupera, con su
# ticket de pesada y el tanque al que se asignó. El AFE que pasa por las piletas va aparte.
_FILTRO_RECU = {"Recuperación de AG": "P:AG", "AFE recuperado": "P:AFE",
                "Del sector": "DEL_SECTOR", "Todos (incluye mal cargados)": None}
_GRUPO_NOM = {"MP": "materia prima", "INSUMO": "insumos", "PT": "producto final"}
_FAM_NOM = {"AG": "ácido graso recuperado", "AFE": "AFE"}


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


_FOCO_COL = {"EXPORTA": "EXPORTADO", "PRODUCE": "PRODUCIDO", "RECUPERA": "RECUPERADO"}


def _reporte(v, ini, um, cuentas=None, foco="EXPORTA", medido=None):
    """La hoja REPORTE: saldo consolidado por producto al cierre del período.

    Lo que hace el sector va primero y con su propia columna: es lo que mira dirección.
    Exportación embarca, un reactor produce, las piletas recuperan."""
    _D = ["cuenta_nombre", "calidad", "corriente_nombre"]
    v = v.copy()
    if foco == "EXPORTA":   # lo que salió por una orden de venta, separado del resto de los egresos
        v["_foco"] = [e if str(d or "").startswith("ODV") else 0.0
                      for e, d in zip(v["_egr"], v["destino"])]
    elif foco == "RECUPERA":  # lo recuperado: lo que entró pesado en portería, con su ticket
        v["_foco"] = [i if str(t or "").strip() else 0.0 for i, t in zip(v["_ing"], v["ticket"])]
    else:                   # lo que el sector produjo: las entradas de producto final
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
    # lo que hoy miden los tanques del sector para ese producto: el libro contra la realidad
    if medido is not None and not medido.empty:
        _m = medido[["cuenta", "tn", "kl", "tanques_con_producto_txt"]].copy()
        _m = _m.rename(columns={("tn" if um == "TN" else "kl"): "MED"})
        g = g.merge(_m[["cuenta", "MED", "tanques_con_producto_txt"]], on="cuenta", how="left")
    else:
        g["MED"], g["tanques_con_producto_txt"] = None, None
    g["MED"] = pd.to_numeric(g["MED"], errors="coerce")
    # primero lo que se exportó (o se produjo, o se recuperó) en el período, después por saldo
    g = g.sort_values(["ODV", "FIN"], ascending=[False, False])
    _fc = f"{_FOCO_COL.get(foco, 'EXPORTADO')} {um}"
    out = pd.DataFrame({
        "CUENTA": g["cuenta"].fillna("(sin producto)"),
        "PRODUCTO": g["cuenta_nombre"].fillna(""),
        "DESCRIPCIÓN": [_describir(c, cuentas) for c in g["cuenta"]],
        "CALIDAD": g["calidad"].fillna("—"),
        "CORRIENTE": g["corriente_nombre"].fillna("—"),
        f"SALDO INICIAL {um}": g["INI"].map(lambda x: _q(x, "0.0")),
        f"INGRESOS {um}": g["ING"].map(_q),
        _fc: g["ODV"].map(_q),
        f"EGRESOS {um}": g["EGR"].map(_q),
        f"SALDO FINAL {um}": g["FIN"].map(lambda x: _q(x, "0.0")),
    })
    tot = pd.DataFrame([{
        "CUENTA": "TOTAL", "PRODUCTO": f"{len(g)} producto(s)", "DESCRIPCIÓN": "",
        "CALIDAD": "", "CORRIENTE": "",
        f"SALDO INICIAL {um}": f"{g['INI'].sum():,.1f}", f"INGRESOS {um}": f"{g['ING'].sum():,.1f}",
        _fc: f"{g['ODV'].sum():,.1f}",
        f"EGRESOS {um}": f"{g['EGR'].sum():,.1f}", f"SALDO FINAL {um}": f"{g['FIN'].sum():,.1f}",
    }])
    if medido is not None:
        out[f"TANQUES HOY {um}"] = g["MED"].map(lambda x: "" if pd.isna(x) else _q(x, "0.0"))
        out["TANQUES"] = g["tanques_con_producto_txt"].fillna("— ninguno")
        tot[f"TANQUES HOY {um}"] = f"{float(g['MED'].fillna(0).sum()):,.1f}"
        tot["TANQUES"] = ""
    return pd.concat([out, tot], ignore_index=True), g


def _descuadre(g, um, sec):
    """Los movimientos que faltan asentar, producto por producto.

    El saldo inicial se reconstruye desde la medición física, así que el libro siempre termina
    igual a lo que miden los tanques: lo que no cierra se le carga al arranque del mes. Un saldo
    inicial NEGATIVO es entonces un número con sentido físico — el libro registró más entradas
    de las que los tanques pueden explicar —, y en un sector de recuperación tiene una sola
    causa: la mercadería entró pesada por portería a un tanque y después se movió a otro sector
    sin que nadie asentara la salida. Acá se muestra con el ingreso del período al lado, que es
    de dónde salió el número, y los tanques donde hay que ir a mirar."""
    if g is None or g.empty:
        return
    d = g.copy()
    d["MED"] = pd.to_numeric(d.get("MED"), errors="coerce").fillna(0.0)
    d["DIF"] = d["FIN"] - d["MED"]
    d = d[(d["INI"] < -0.05) | (d["DIF"].abs() >= 0.1)]
    d = d.sort_values("INI", ascending=True)
    if d.empty:
        st.caption(f"✅ El libro de {sec['nombre_ui']} cierra contra lo que miden los tanques, "
                   "producto por producto: no falta asentar ningún movimiento.")
        return
    _falta = float(-d.loc[d["INI"] < 0, "INI"].sum())

    def _porque(ini, dif):
        if ini < -0.05:
            return ("entró y se movió a otro sector sin asentar la salida: el mes arrancó con "
                    f"{-ini:,.1f} {um} de más en el libro")
        return ("el libro no coincide con la medición del tanque: revisá la última medición "
                "o el último movimiento")

    with st.expander(f"⚖️ Faltan asentar {_falta:,.1f} {um} de movimientos en {len(d)} producto(s)",
                     expanded=False):
        st.dataframe(pd.DataFrame({
            "CUENTA": d["cuenta"].fillna("(sin producto)"),
            "PRODUCTO": d["cuenta_nombre"].fillna(""),
            f"ARRANCÓ EN {um}": d["INI"].map(lambda x: _q(x, "0.0")),
            f"ENTRÓ {um}": d["ING"].map(_q),
            f"SALIÓ {um}": d["EGR"].map(_q),
            f"MIDEN LOS TANQUES {um}": d["MED"].map(lambda x: _q(x, "0.0")),
            "QUÉ PASA": [_porque(i, x) for i, x in zip(d["INI"], d["DIF"])],
            "TANQUES": d["tanques_con_producto_txt"].fillna("— ninguno"),
        }), hide_index=True, use_container_width=True,
            column_config={"QUÉ PASA": st.column_config.TextColumn(width="large"),
                           "TANQUES": st.column_config.TextColumn(width="medium")})
        st.caption("Cada ingreso entra con su ticket de pesada y su tanque; las salidas internas "
                   "hacia bachas, reactores o plataforma muchas veces no se cargan, y ahí es donde "
                   "el libro se despega de la planta. No es un error de la pantalla: es el "
                   "movimiento que falta asentar, y es lo que hay que corregir en la carga para "
                   "que el stock del sector sea confiable.")


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
def _cat_de(cf):
    """Adaptador: la barra de filtros compartida (filtros_stock) lee con cat(sql, params)."""
    def _cat(sql, params=None):
        with cf() as conn:
            return pd.read_sql_query(sql, conn, params=params)
    return _cat


@_FRAGMENT
def _movimientos(ctx, sec):
    """Rediseño pedido por dirección (23/09):
       1. una sola barra de filtros — Producto y Sector (uno o varios, vacío = todos), Fecha
          desde/hasta con calendario, N° ticket, y «➕ Más» con el resto — y el botón BUSCAR:
          el resultado aparece cuando se aprieta, no mientras se elige;
       2. sin indicadores (se repensarán aparte);
       3. los productos con el nombre de la planilla de parámetros;
       4. SALDO CONSOLIDADO POR PRODUCTO y CUENTA CORRIENTE DEL PRODUCTO con las columnas
          pedidas; ORIGEN/DESTINO es el sector / proveedor / cliente, nunca el tanque, que va
          en TK/ACOPIO."""
    import filtros_stock as _fs
    cf = ctx["conn_factory"]
    cod = sec["codigo"]
    key = f"stkcc_{cod}"

    _batch = (sec.get("sector_batch") or "").upper()
    exporta = _batch in ("", "EXPO")
    recupera = _batch == "RECUPERACION"
    FIL = _FILTRO_EXPO if exporta else (_FILTRO_RECU if recupera else _FILTRO_PROD)

    nombres = _nombres(cf)
    secs_nav = _sectores_nav(cf)
    cuentas = _cuentas(cf, cod)
    # el desplegable de producto: las cuentas del sector, con el nombre de la planilla
    _ctas = sorted(cuentas["cuenta"].dropna().astype(str).unique().tolist()) if not cuentas.empty else []
    _etq = {c: _nombre_cuenta(c, cuentas, nombres) for c in _ctas}
    _etq.update({k: v for k, v in secs_nav.items()})   # el sector también se muestra por nombre

    # Sector: por defecto el de la pantalla; se pueden sumar otros para comparar.
    st.session_state.setdefault(f"{key}_sec", [cod])

    def _mas():
        """Lo que va dentro de «➕ Más»: todos los filtros posibles de esta pantalla."""
        out = {}
        out["Unidad"] = st.radio("Unidad", list(_UM), horizontal=True, key=f"{key}_um",
                                 help="TN (litros × densidad del producto) o KL, como la planilla.")
        k_rol = f"{key}_rol"
        if st.session_state.get(k_rol) not in FIL:
            # arranca en «Del sector»: lo que el sector trabaja, sin esconder productos que
            # todavía no salieron por ODV (el AFE-AL del 6850 no aparecía con «Lo que exportamos»)
            st.session_state[k_rol] = "Del sector" if "Del sector" in FIL else list(FIL)[0]
        out["Qué productos"] = st.selectbox("Qué productos", list(FIL), key=k_rol,
                                            help="«Del sector» es lo que el sector trabaja. «Todos» agrega lo "
                                                 "que está en sus tanques por una designación equivocada.")
        out["Tipo"] = st.selectbox("Tipo de movimiento", ["(todos)", "Entradas", "Salidas"], key=f"{key}_tipo")
        out["Tanque"] = st.selectbox("Tanque (TK/ACOPIO)", ["(todos)"] + _tanques_sector(cf, tuple(st.session_state.get(f"{key}_sec") or [cod])),
                                     key=f"{key}_tq")
        out["Origen/Destino"] = st.text_input("Origen / destino contiene", key=f"{key}_od",
                                              placeholder="proveedor, cliente, ODV, reactor…")
        out["Usuario"] = st.text_input("Usuario", key=f"{key}_usr", placeholder="quien cargó el movimiento")
        out["Incluir ajustes"] = st.checkbox("Incluir ajustes automáticos de medición", key=f"{key}_aj", value=False)
        return out

    f, apretado = _fs.barra(
        _cat_de(cf), key=key, titulo=None,
        campos=("prod", "sec", "fecha", "tk"),
        catalogos={"prod": _ctas, "sec": list(secs_nav)},
        multi=True, extras_fn=_mas, buscar=True, etiquetas=_etq)
    c_ref = st.columns([6, 1])[1]
    if c_ref.button("↻", key=f"{key}_ref", use_container_width=True, help="Releer la base ahora"):
        invalidar(); _rerun_fragment()

    # El resultado se muestra sólo después de BUSCAR (y queda hasta la próxima búsqueda).
    k_ap = f"{key}_aplicado"
    if apretado:
        st.session_state[k_ap] = f
    fa = st.session_state.get(k_ap)
    if not fa:
        st.info("Elegí los filtros y apretá **🔍 Buscar** para ver el saldo consolidado y la cuenta corriente.")
        return

    desde, hasta = fa["desde"], fa["hasta"]
    if desde is None or hasta is None:
        from datetime import date as _d
        desde = desde or _d(2020, 1, 1)
        hasta = hasta or _d.today()
    etiqueta = f"{desde:%d/%m/%Y} al {hasta:%d/%m/%Y}"
    secs = fa["sec"] or [cod]
    propios = fa.get("propios") or {}
    um = propios.get("Unidad") or "TN"
    col, div = _UM[um]

    df = _movs(cf, tuple(secs), desde, hasta)
    ini = pd.concat([_saldo_inicial(cf, sc, desde) for sc in secs], ignore_index=True) \
        if secs else None
    if df is None or ini is None or (isinstance(ini, pd.DataFrame) and ini.empty and df.empty):
        if df is None or ini is None:
            st.caption("Sin conexión a la base en este momento.")
            return
    ini = ini.copy()
    for c in ("kg_neto", "litros_neto"):
        ini[c] = pd.to_numeric(ini[c], errors="coerce").fillna(0.0)

    v = df.copy()
    if not propios.get("Incluir ajustes"):
        v = v[~v["es_ajuste_sistema"]]
    v = v[_col(v, "es_stock", True).fillna(True).astype(bool)]
    v["_val"] = v[col] / div
    ini["_val"] = ini[col] / div

    # --- filtros ---
    if fa["prod"]:
        v = v[v["cuenta"].isin(fa["prod"])]
        ini = ini[ini["cuenta"].isin(fa["prod"])]
    else:
        _f = FIL.get(propios.get("Qué productos"))
        if _f and _f.startswith("G:"):
            _ok = set(v.loc[v["grupo"] == _f[2:], "cuenta"])
            v, ini = v[v["cuenta"].isin(_ok)], ini[ini["cuenta"].isin(_ok)]
        elif _f and _f.startswith("P:"):
            _p = _f[2:]
            _ok = (set(cuentas.loc[cuentas["producto_codigo"].fillna("").str.startswith(_p), "cuenta"])
                   if not cuentas.empty else set())
            _ok |= set(v.loc[_col(v, "producto_codigo", "").fillna("").str.startswith(_p), "cuenta"])
            v, ini = v[v["cuenta"].isin(_ok)], ini[ini["cuenta"].isin(_ok)]
        elif _f and not cuentas.empty and len(secs) == 1:
            if _f == "DEL_SECTOR":
                _ok = set(cuentas.loc[cuentas["del_sector"].fillna(True).astype(bool), "cuenta"])
            elif _f == "EXPORTA":
                _pe = set(cuentas.loc[cuentas["salidas_odv"].fillna(0) > 0, "producto_codigo"])
                _ok = set(cuentas.loc[cuentas["producto_codigo"].isin(_pe), "cuenta"])
            else:
                _ok = set(cuentas.loc[cuentas["rol"] == _f, "cuenta"])
            v, ini = v[v["cuenta"].isin(_ok)], ini[ini["cuenta"].isin(_ok)]
    if fa["tk"]:
        q = fa["tk"].strip().lower()
        m = v["ticket"].fillna("").astype(str).str.lower().str.contains(q, regex=False)
        m |= v["tickets_detalle"].fillna("").astype(str).str.lower().str.contains(q, regex=False)
        m |= v["referencia"].fillna("").astype(str).str.lower().str.contains(q, regex=False)
        v = v[m]
    _tipo = propios.get("Tipo")
    if _tipo == "Entradas":
        v = v[v["_val"] > 0]
    elif _tipo == "Salidas":
        v = v[v["_val"] < 0]
    if propios.get("Tanque") not in (None, "", "(todos)"):
        v = v[_col(v, "tanque", "").fillna("").astype(str) == propios["Tanque"]]
    if (propios.get("Origen/Destino") or "").strip():
        q = propios["Origen/Destino"].strip().lower()
        v = v[_contraparte(v).str.lower().str.contains(q, regex=False)]
    if (propios.get("Usuario") or "").strip():
        q = propios["Usuario"].strip().lower()
        v = v[_col(v, "usuario", "").fillna("").astype(str).str.lower().str.contains(q, regex=False)]

    nombre_de = lambda c: _nombre_cuenta(c, cuentas, nombres)  # noqa: E731
    _secs_txt = ", ".join(secs_nav.get(x, x) for x in secs)

    if v.empty and float(ini["_val"].abs().sum()) == 0:
        st.info(f"Sin movimientos para estos filtros en {_secs_txt} · {etiqueta}.")
        return

    # ---------------- SALDO CONSOLIDADO POR PRODUCTO ----------------
    st.markdown("<div class='section-title' style='margin:10px 0 2px'>Saldo consolidado por producto</div>",
                unsafe_allow_html=True)
    st.caption(f"{_secs_txt} · {etiqueta} · cantidades en **{um}**")
    cons = _consolidado(v, ini, um, nombre_de)
    st.dataframe(cons, hide_index=True, use_container_width=True, height=min(560, 60 + 35 * len(cons)),
                 column_config={"PRODUCTO": st.column_config.TextColumn(width="medium"),
                                "ORIGEN/DESTINO": st.column_config.TextColumn(width="medium"),
                                "COMENTARIO": st.column_config.TextColumn(width="medium"),
                                "UM": st.column_config.TextColumn(width="small")})

    # ---------------- CUENTA CORRIENTE DEL PRODUCTO ----------------
    ctas = sorted(set(v["cuenta"].dropna()) | set(ini.loc[ini["_val"].abs() > 0.05, "cuenta"].dropna()),
                  key=nombre_de)
    if not ctas:
        return
    st.markdown("<div class='section-title' style='margin:14px 0 2px'>Cuenta corriente del producto</div>",
                unsafe_allow_html=True)
    k_c = f"{key}_cta"
    if st.session_state.get(k_c) not in ctas:
        st.session_state[k_c] = ctas[0]
    cta = st.selectbox("Producto", ctas, key=k_c, label_visibility="collapsed",
                       format_func=lambda c: f"{nombre_de(c)}  ·  {c}")
    w = v[v["cuenta"] == cta].sort_values(["momento", "id_mov"])
    s_ini_cta = float(ini.loc[ini["cuenta"] == cta, "_val"].sum())
    _txt_ini = _control(ctx, sec, cod, um, float(ini["_val"].sum() + v["_val"].sum()), ini) \
        if len(secs) == 1 else "saldo inicial de cada sector"
    tabla = _cc_producto(w, s_ini_cta, f"al {desde:%d/%m/%Y}", _txt_ini)
    st.dataframe(tabla, hide_index=True, use_container_width=True, height=min(620, 60 + 35 * len(tabla)),
                 column_config={"ORIGEN/DESTINO": st.column_config.TextColumn(width="medium"),
                                "TK/ACOPIO": st.column_config.TextColumn(width="small"),
                                "COMENTARIOS": st.column_config.TextColumn(width="medium")})
    st.caption(f"Cantidades en **{um}**. ORIGEN/DESTINO es el sector, proveedor o cliente con el que se hizo el "
               "movimiento; TK/ACOPIO es el tanque donde entró o de donde salió. El saldo corre de arriba hacia "
               "abajo desde el saldo inicial.")

    # ---------------- Excel ----------------
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        cons.to_excel(xw, index=False, sheet_name="CONSOLIDADO")
        for c in ctas[:40]:
            hoja = nombre_de(c)[:28].replace("/", "-").replace("\\", "-").replace(":", "-").replace("·", "-")
            _w = v[v["cuenta"] == c].sort_values(["momento", "id_mov"])
            _si = float(ini.loc[ini["cuenta"] == c, "_val"].sum())
            _cc_producto(_w, _si, f"al {desde:%d/%m/%Y}", "").to_excel(xw, index=False, sheet_name=hoja)
    st.download_button("⬇️ Descargar Excel (consolidado + una hoja por producto)", buf.getvalue(),
                       file_name=f"stock_{'_'.join(secs).lower()}_{desde:%Y%m%d}_{hasta:%Y%m%d}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       key=f"{key}_xls")


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
