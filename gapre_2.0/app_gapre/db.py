"""Conexión a Supabase (Postgres) y helpers de datos para GAPRE - canal 2."""
import os
import re
import psycopg2
import psycopg2.extras
import streamlit as st


# ----------------------------------------------------------------------------
# Conexión
# ----------------------------------------------------------------------------
def _dsn() -> str:
    """DSN de Postgres. Prioridad: st.secrets['db']['dsn'] -> env GAPRE_DSN."""
    try:
        return st.secrets["db"]["dsn"]
    except Exception:
        dsn = os.environ.get("GAPRE_DSN")
        if not dsn:
            st.error(
                "Falta la cadena de conexión. Configurá `.streamlit/secrets.toml` "
                "con [db] dsn = \"postgresql://...\" o la variable GAPRE_DSN."
            )
            st.stop()
        return dsn


@st.cache_resource
def get_conn():
    conn = psycopg2.connect(_dsn())
    conn.autocommit = True
    return conn


def q(sql, params=None):
    """SELECT -> lista de dicts."""
    with get_conn().cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params or [])
        return cur.fetchall()


def execute(sql, params=None):
    """INSERT/UPDATE/DELETE sin retorno."""
    with get_conn().cursor() as cur:
        cur.execute(sql, params or [])


def insert_returning_id(table, data: dict) -> int:
    cols = list(data.keys())
    vals = [data[c] for c in cols]
    collist = ", ".join(cols)
    ph = ", ".join(["%s"] * len(cols))
    sql = f"insert into gapre.{table} ({collist}) values ({ph}) returning id"
    with get_conn().cursor() as cur:
        cur.execute(sql, vals)
        return cur.fetchone()[0]


# ----------------------------------------------------------------------------
# Maestros
# ----------------------------------------------------------------------------
@st.cache_data(ttl=30)
def listar_clientes():
    return q("select id, nombre, cuit, forma_pago, plazo_dias from gapre.clientes order by nombre")


@st.cache_data(ttl=30)
def listar_proveedores():
    return q("select id, nombre, cuit from gapre.proveedores order by nombre")


@st.cache_data(ttl=300)
def listar_productos():
    return q("select codigo, producto from gapre.productos order by codigo")


def crear_cliente(d: dict) -> int:
    new_id = insert_returning_id("clientes", d)
    listar_clientes.clear()
    return new_id


def crear_proveedor(d: dict) -> int:
    new_id = insert_returning_id("proveedores", d)
    listar_proveedores.clear()
    return new_id


# ----------------------------------------------------------------------------
# Numeración sugerida (siguiente correlativo según prefijo)
# ----------------------------------------------------------------------------
def sugerir_numero(tabla: str, columna: str, prefijo: str, talonario: str = "0001",
                   ancho: int = 8) -> str:
    """Devuelve el siguiente número correlativo para un prefijo dado.

    Ej: prefijo='OV', talonario='0001' -> 'OV 0001-00002795'
    """
    rows = q(f"select {columna} as n from gapre.{tabla} "
             f"where {columna} ilike %s", [f"%{prefijo}%"])
    maxn = 0
    for r in rows:
        if not r["n"]:
            continue
        nums = re.findall(r"(\d+)", str(r["n"]))
        if nums:
            cand = int(nums[-1])
            maxn = max(maxn, cand)
    return f"{prefijo} {talonario}-{str(maxn + 1).zfill(ancho)}"
