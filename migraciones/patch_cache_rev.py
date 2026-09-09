# -*- coding: utf-8 -*-
"""Fase 0 · invalidación de caché por tabla (cache_rev.py).

  1) etl/db.py  · conectar(): graba los statements de la transacción y, tras el
                  commit, avisa a los hooks registrados (ON_COMMIT_HOOKS).
  2) app.py     · cat(): la clave de cache_data incluye la revisión de las tablas
                  base de la consulta. `cat.clear()` (172 llamadas en la app) sigue
                  existiendo y sigue siendo global → comportamiento idéntico a hoy;
                  `cat.invalidar("tabla", ...)` es la versión fina para migrar de a una.

Coincidencia exacta y única o no escribe nada.  Uso: python patch_cache_rev.py <raíz worms_supabase>
"""
import os, shutil, sys
from datetime import datetime

root = sys.argv[1]


def leer(p):
    raw = open(p, "rb").read()
    return raw.decode("utf-8").replace("\r\n", "\n"), (b"\r\n" in raw)


def escribir(p, src, crlf):
    bak = p + ".bak_cache_rev_" + datetime.now().strftime("%Y%m%d_%H%M")
    shutil.copy2(p, bak)
    open(p, "wb").write((src.replace("\n", "\r\n") if crlf else src).encode("utf-8"))
    print("OK", p, "· backup", os.path.basename(bak))


def once(s, needle):
    n = s.count(needle)
    assert n == 1, f"esperaba 1 coincidencia, hay {n}:\n{needle[:160]!r}"


# ------------------------------------------------------------------ 1) etl/db.py
p = os.path.join(root, "etl", "db.py")
src, crlf = leer(p)
old = '''    conn = db_connect()
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute("SET search_path TO produccion, public; SET TIME ZONE 'America/Argentina/Buenos_Aires'")
            cur.execute("SELECT set_config('app.user_id', %s, false)", (str(id_usuario),))
        yield conn, _Audit(conn, id_usuario)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
'''
once(src, old)
new = '''    conn = db_connect()
    conn.autocommit = False
    _stmts = []
    conn.cursor_factory = _cursor_grabador(_stmts)   # qué escribe esta transacción
    try:
        with conn.cursor() as cur:
            cur.execute("SET search_path TO produccion, public; SET TIME ZONE 'America/Argentina/Buenos_Aires'")
            cur.execute("SELECT set_config('app.user_id', %s, false)", (str(id_usuario),))
        yield conn, _Audit(conn, id_usuario)
        conn.commit()
        _avisar_commit(_stmts)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---- Hooks de commit: la app registra cache_rev.on_commit para invalidar SOLO las
# consultas cacheadas que dependen de las tablas escritas (ver app_carga/cache_rev.py).
ON_COMMIT_HOOKS = []


def _cursor_grabador(stmts):
    """cursor_factory que anota cada statement ejecutado (execute/executemany;
    execute_values también pasa por execute). No cambia el comportamiento."""
    class _C(psycopg2.extensions.cursor):
        def _texto(self, query):
            if isinstance(query, str):
                return query
            if isinstance(query, bytes):
                return query.decode("utf-8", "ignore")
            try:
                return query.as_string(self)      # psycopg2.sql.Composable
            except Exception:
                return "CALL opaco"               # que el hook lo trate como escritura global

        def execute(self, query, vars=None):
            try:
                stmts.append(self._texto(query))
            except Exception:
                pass
            return super().execute(query, vars)

        def executemany(self, query, vars_list):
            try:
                stmts.append(self._texto(query))
            except Exception:
                pass
            return super().executemany(query, vars_list)
    return _C


def _avisar_commit(stmts):
    for h in list(ON_COMMIT_HOOKS):
        try:
            h(stmts)
        except Exception:
            pass
'''
src = src.replace(old, new, 1)
escribir(p, src, crlf)

# ------------------------------------------------------------------ 2) app.py · cat()
p = os.path.join(root, "app_carga", "app.py")
src, crlf = leer(p)
old = '''@st.cache_data(ttl=300, max_entries=400)
def cat(query, params=None):
    # Pool compartido: evita un handshake SSL (~0,5 s) por CADA cache-miss.
    with _lab_conn() as conn:
        return pd.read_sql_query(query, conn, params=params)
'''
once(src, old)
new = '''# ---- Caché de consultas con invalidación POR TABLA (cache_rev.py) ----
# La clave incluye la revisión de las tablas base que toca cada consulta; una
# escritura (commit de conectar()) sube sólo esas revisiones. `cat.clear()` sigue
# siendo global (compatibilidad con las ~170 llamadas existentes); la versión
# fina es `cat.invalidar("fact_x", ...)`. Ver docs/PLAN_NAVEGACION_V2.md §4.
import cache_rev as _cache_rev
_cache_rev.configurar(_lab_conn)
try:
    from etl import db as _etl_db
    if _cache_rev.on_commit not in _etl_db.ON_COMMIT_HOOKS:
        _etl_db.ON_COMMIT_HOOKS.append(_cache_rev.on_commit)
except Exception:
    pass


@st.cache_data(ttl=300, max_entries=400)
def _cat_cached(query, params, _rev):
    # Pool compartido: evita un handshake SSL (~0,5 s) por CADA cache-miss.
    with _lab_conn() as conn:
        return pd.read_sql_query(query, conn, params=params)


def cat(query, params=None):
    return _cat_cached(query, params, _cache_rev.rev_key(query))


cat.clear = _cache_rev.bump_global        # global, como siempre
cat.invalidar = _cache_rev.bump_tablas    # fino: cat.invalidar("fact_batch_proceso")
cat.estado = _cache_rev.estado            # diagnóstico
'''
src = src.replace(old, new, 1)
escribir(p, src, crlf)
