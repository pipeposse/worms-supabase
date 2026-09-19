# -*- coding: utf-8 -*-
"""Invalidación de caché POR TABLA en vez de global.

EL PROBLEMA
-----------
`cat(sql)` (app.py) cachea cada consulta 5 min con st.cache_data. Después de cada
escritura la app llamaba `cat.clear()`: se vaciaba la caché de TODAS las consultas
de TODOS los usuarios (la caché es del proceso, no de la sesión). Cuando un
operario guardaba una medición, el siguiente rerun de cada usuario volvía a
pegarle a Supabase con cada consulta de su sección → "la página recarga todo".

LA SOLUCIÓN
-----------
Cada consulta se cachea con una clave que incluye la "revisión" de las tablas
BASE que toca (las vistas se expanden a sus tablas usando el catálogo de
Postgres, en forma transitiva; los triggers se expanden a las tablas que
escriben). Una escritura sube la revisión de las tablas que tocó y sólo las
consultas que dependen de esas tablas se vuelven a ejecutar.

    rev_key(sql)            → tupla de revisiones (va en la clave de cache_data)
    bump_tablas(*tablas)    → invalida lo que dependa de esas tablas
    bump_global()           → invalida todo (compatibilidad con cat.clear())
    on_commit(stmts)        → hook de etl.db.conectar(): mira qué escribió la
                              transacción y hace bump_tablas solo

Todo es conservador: lo que no se puede resolver (tabla desconocida, catálogo
no cargado, parseo dudoso) cae en invalidación global, nunca en dato viejo.
No depende de Streamlit: el estado vive en el módulo (= por proceso, igual que
st.cache_data), así que sirve también fuera de la app.
"""

import re
import threading
import time

# ------------------------------------------------------------------ estado por proceso
_lock = threading.Lock()
_REV = {}                 # tabla -> int
_REV_GLOBAL = [0]
_CATALOGO = {             # se llena con cargar_catalogo(conn_factory)
    "relaciones": set(),  # nombres (sin esquema) de tablas y vistas conocidas
    "base_de": {},        # relación -> frozenset(tablas base transitivas)
    "trigger_escribe": {},# tabla -> frozenset(tablas que escriben sus triggers)
    "cargado_en": 0.0,
}
_CONN_FACTORY = [None]
_TTL_CATALOGO = 6 * 3600
# Revisión EXTERNA por tabla: contadores de pg_stat_user_tables (ins+upd+del).
# Cubre lo que este proceso no ve escribir: la sincronización de portería y de
# laboratorio, los jobs de pg_cron, otra instancia de la app, una función SQL que
# escribe por dentro, un UPDATE a mano en la base. Se relee como mucho cada
# _POLL_EXT segundos POR PROCESO (una consulta chica a una vista de estadísticas,
# no a las tablas), y entra en la clave de caché junto con la revisión local.
_EXT = {}                 # tabla -> int (contador acumulado de modificaciones)
_EXT_TS = [0.0]           # cuándo se leyó por última vez
_POLL_EXT = 20.0
_SQL_EXT = ("SELECT relname, n_tup_ins + n_tup_upd + n_tup_del "
            "FROM pg_stat_user_tables "
            "WHERE schemaname IN ('public','produccion','reporting','gapre','wa')")
_SQL_CACHE = {}           # sql -> frozenset(tablas base)  (memo del parseo)
_SQL_CACHE_MAX = 2000

_IDENT = re.compile(r"(?:[A-Za-z_][\w]*\.)?([A-Za-z_][\w]*)")
_ESCRITURA = re.compile(r"^\s*(?:with\b.*?\)\s*)?(insert|update|delete|truncate|merge|call|refresh)\b",
                        re.IGNORECASE | re.DOTALL)


def configurar(conn_factory):
    """Registra cómo abrir una conexión (context manager que da un psycopg2 conn)."""
    _CONN_FACTORY[0] = conn_factory


# ------------------------------------------------------------------ catálogo
_SQL_CATALOGO = """
WITH rel AS (
  SELECT c.oid, n.nspname AS esquema, c.relname AS nombre, c.relkind
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE n.nspname IN ('public','produccion','reporting','gapre','wa')
    AND c.relkind IN ('r','v','m','p')
),
dep AS (  -- vista -> relación de la que depende (un nivel)
  SELECT DISTINCT v.nombre AS vista, r.nombre AS depende_de
  FROM pg_depend d
  JOIN pg_rewrite w ON w.oid = d.objid
  JOIN rel v ON v.oid = w.ev_class AND v.relkind IN ('v','m')
  JOIN rel r ON r.oid = d.refobjid AND r.oid <> v.oid
  WHERE d.classid = 'pg_rewrite'::regclass AND d.refclassid = 'pg_class'::regclass
),
trg AS (  -- tabla -> cuerpo de la función de cada trigger
  SELECT r.nombre AS tabla, p.prosrc
  FROM pg_trigger t JOIN rel r ON r.oid = t.tgrelid
  JOIN pg_proc p ON p.oid = t.tgfoid
  WHERE NOT t.tgisinternal
)
SELECT 'rel' AS tipo, nombre AS a, relkind::text AS b FROM rel
UNION ALL SELECT 'dep', vista, depende_de FROM dep
UNION ALL SELECT 'trg', tabla, prosrc FROM trg
"""


def cargar_catalogo(conn_factory=None, forzar=False):
    """Lee tablas/vistas, dependencias de vistas y triggers. Idempotente; con TTL."""
    cf = conn_factory or _CONN_FACTORY[0]
    if cf is None:
        return False
    if not forzar and time.time() - _CATALOGO["cargado_en"] < _TTL_CATALOGO:
        return bool(_CATALOGO["relaciones"])
    try:
        with cf() as conn:
            with conn.cursor() as cur:
                cur.execute(_SQL_CATALOGO)
                filas = cur.fetchall()
    except Exception:
        # no martillar la base en cada consulta: reintentar recién en 60 s
        with _lock:
            _CATALOGO["cargado_en"] = time.time() - _TTL_CATALOGO + 60
        return False
    relaciones, es_tabla, dep1, trg = set(), set(), {}, {}
    for tipo, a, b in filas:
        if tipo == "rel":
            relaciones.add(a)
            if b in ("r", "p"):
                es_tabla.add(a)   # mismo nombre en dos esquemas: si alguno es tabla, cuenta como tabla
        elif tipo == "dep":
            dep1.setdefault(a, set()).add(b)
        elif tipo == "trg":
            trg.setdefault(a, []).append(b or "")
    # expansión transitiva vista -> tablas base
    base_de = {}

    def _base(nombre, visto):
        if nombre in base_de:
            return base_de[nombre]
        if nombre in visto:
            return frozenset()
        visto.add(nombre)
        out = set([nombre]) if (nombre in es_tabla or nombre not in dep1) else set()
        for d in dep1.get(nombre, ()):
            out |= _base(d, visto)
        out = frozenset(out)
        base_de[nombre] = out
        return out

    for r in relaciones:
        _base(r, set())
    # triggers: tabla -> tablas base que escriben sus funciones (conservador: cualquier relación mencionada)
    trigger_escribe = {}
    for tabla, cuerpos in trg.items():
        menc = set()
        for cuerpo in cuerpos:
            for m in _IDENT.finditer(cuerpo):
                nm = m.group(1).lower()
                if nm in relaciones and nm != tabla:
                    menc |= base_de.get(nm, frozenset([nm]))
        if menc:
            trigger_escribe[tabla] = frozenset(menc)
    with _lock:
        _CATALOGO.update(relaciones=relaciones, base_de=base_de,
                         trigger_escribe=trigger_escribe, cargado_en=time.time())
        _SQL_CACHE.clear()
    return True


# ------------------------------------------------------------------ parseo
def tablas_base_de_sql(sql):
    """Tablas base (transitivas) que menciona una consulta. frozenset() si no
    reconoce ninguna (→ la consulta queda atada sólo a la revisión global)."""
    if not isinstance(sql, str):
        sql = str(sql)
    hit = _SQL_CACHE.get(sql)
    if hit is not None:
        return hit
    rel = _CATALOGO["relaciones"]
    base_de = _CATALOGO["base_de"]
    out = set()
    if rel:
        for m in _IDENT.finditer(sql):
            nm = m.group(1).lower()
            if nm in rel:
                out |= base_de.get(nm, frozenset([nm]))
    out = frozenset(out)
    if len(_SQL_CACHE) > _SQL_CACHE_MAX:
        _SQL_CACHE.clear()
    _SQL_CACHE[sql] = out
    return out


_FN_OPACA = re.compile(r"\bfn_\w+\s*\(", re.IGNORECASE)


def es_escritura(sql):
    return bool(_ESCRITURA.match(sql if isinstance(sql, str) else str(sql)))


def es_escritura_opaca(sql):
    """`SELECT produccion.fn_x(...)` o `CALL ...` dentro de una transacción de
    escritura: la función puede escribir cualquier tabla y el parseo no lo ve."""
    t = sql if isinstance(sql, str) else str(sql)
    return bool(_FN_OPACA.search(t)) or t.strip().upper().startswith("CALL")


# ------------------------------------------------------------------ revisiones
def _refrescar_ext(forzar=False):
    """Relee los contadores de pg_stat_user_tables si pasaron _POLL_EXT segundos.
    Nunca levanta: si la base no responde, se sigue con lo último leído."""
    ahora = time.time()
    if not forzar and ahora - _EXT_TS[0] < _POLL_EXT:
        return
    cf = _CONN_FACTORY[0]
    if cf is None:
        return
    with _lock:
        # otro hilo ya lo está leyendo: que no se amontonen
        if not forzar and ahora - _EXT_TS[0] < _POLL_EXT:
            return
        _EXT_TS[0] = ahora
    try:
        with cf() as conn:
            with conn.cursor() as cur:
                cur.execute(_SQL_EXT)
                filas = cur.fetchall()
        nuevo = {str(r[0]).lower(): int(r[1] or 0) for r in filas}
        with _lock:
            _EXT.update(nuevo)
    except Exception:
        pass


def rev_de_tablas(tablas):
    """Tupla de revisión para un conjunto de tablas base: (rev global, (tabla, rev
    local, rev externa)...). Es lo que va en la clave de st.cache_data."""
    _refrescar_ext()
    with _lock:
        return (_REV_GLOBAL[0],) + tuple(sorted((t, _REV.get(t, 0), _EXT.get(t, 0)) for t in tablas))


def rev_global():
    """Revisión «todo»: cambia si cambió cualquier tabla (local o externa)."""
    _refrescar_ext()
    with _lock:
        return (_REV_GLOBAL[0], sum(_REV.values()), sum(_EXT.values()))


def rev_key(sql):
    """Clave de revisión de una consulta: (rev global, (tabla, rev local, rev externa)...).
    Si la consulta no menciona ninguna tabla conocida, queda atada a rev_global()."""
    cargar_catalogo()
    tablas = tablas_base_de_sql(sql)
    if not tablas:
        return rev_global()
    return rev_de_tablas(tablas)


def bump_tablas(*tablas):
    """Sube la revisión de esas tablas (y de las que escriben sus triggers).
    Nombres desconocidos → bump global (conservador)."""
    cargar_catalogo()
    rel = _CATALOGO["relaciones"]
    base_de = _CATALOGO["base_de"]
    trg = _CATALOGO["trigger_escribe"]
    objetivo, desconocida = set(), False
    for t in tablas:
        nm = (t or "").split(".")[-1].lower()
        if not nm:
            continue
        if nm not in rel:
            desconocida = True
            continue
        bases = base_de.get(nm, frozenset([nm]))
        objetivo |= bases
        for b in bases:
            objetivo |= trg.get(b, frozenset())
    with _lock:
        if desconocida or not objetivo:
            _REV_GLOBAL[0] += 1
        for t in objetivo:
            _REV[t] = _REV.get(t, 0) + 1


def bump_global():
    with _lock:
        _REV_GLOBAL[0] += 1


def on_commit(stmts):
    """Hook para etl.db.conectar(): recibe los statements ejecutados en la
    transacción y hace bump de las tablas escritas. Nunca levanta."""
    try:
        tablas, escritura_opaca = set(), False
        for s in stmts:
            if es_escritura(s):
                t = tablas_base_de_sql(s)
                if t:
                    tablas |= t
                else:
                    escritura_opaca = True   # CALL fn(), tabla desconocida… → global
            elif es_escritura_opaca(s):
                escritura_opaca = True       # SELECT fn_x(): escribe por dentro
        if escritura_opaca:
            bump_global()
            _EXT_TS[0] = 0.0                 # y que la próxima lectura relea pg_stat ya
        elif tablas:
            bump_tablas(*tablas)
    except Exception:
        try:
            bump_global()
        except Exception:
            pass


def estado():
    """Para diagnóstico: revisiones actuales y tamaño del catálogo."""
    with _lock:
        return {"rev_global": _REV_GLOBAL[0], "revs": dict(_REV),
                "relaciones": len(_CATALOGO["relaciones"]),
                "vistas_expandidas": sum(1 for k, v in _CATALOGO["base_de"].items() if v != frozenset([k])),
                "tablas_con_trigger": len(_CATALOGO["trigger_escribe"]),
                "catalogo_hace_s": int(time.time() - _CATALOGO["cargado_en"]) if _CATALOGO["cargado_en"] else None}


# ------------------------------------------------------------------ cachés propias
def cachear(ttl=300, show_spinner=False, **kw):
    """Reemplazo directo de `@st.cache_data(...)` para funciones de LECTURA.

    Las pantallas nuevas (nav/*) y algunos KPIs tenían su propio st.cache_data,
    fuera de cat(): ninguna escritura las invalidaba, sólo el TTL. Con este
    decorador la clave de caché incluye la revisión de las tablas que menciona el
    módulo de la función (local + externa vía pg_stat), así que una escritura de
    la app la invalida al instante y una externa en ≤ _POLL_EXT segundos. Si el
    módulo no menciona ninguna tabla conocida, queda atada a rev_global().

    Respeta las reglas de st.cache_data: los parámetros que empiezan con "_"
    (p. ej. `_cf`, la fábrica de conexiones) siguen fuera del hash, porque se
    conserva la firma original de la función."""
    import functools
    import inspect
    import streamlit as st

    def deco(fn):
        try:
            _src = inspect.getsource(inspect.getmodule(fn)) or ""
        except Exception:
            _src = ""
        _tablas = [None]     # se resuelve en la primera llamada (el catálogo carga tarde)

        def _rev():
            cargar_catalogo()
            if _tablas[0] is None and _CATALOGO["relaciones"]:
                _tablas[0] = tablas_base_de_sql(_src)
            t = _tablas[0]
            return rev_de_tablas(t) if t else rev_global()

        def _inner(rev, *a, **k):
            return fn(*a, **k)
        _inner.__name__ = getattr(fn, "__name__", "cachear")
        _inner.__qualname__ = getattr(fn, "__qualname__", _inner.__name__)
        _inner.__module__ = getattr(fn, "__module__", __name__)
        try:
            _sig = inspect.signature(fn)
            _inner.__signature__ = _sig.replace(
                parameters=[inspect.Parameter("rev", inspect.Parameter.POSITIONAL_OR_KEYWORD)]
                           + list(_sig.parameters.values()))
        except Exception:
            pass
        _cached = st.cache_data(ttl=ttl, show_spinner=show_spinner, **kw)(_inner)

        @functools.wraps(fn)
        def wrapper(*a, **k):
            return _cached(_rev(), *a, **k)
        wrapper.clear = getattr(_cached, "clear", lambda *x, **y: None)
        return wrapper
    return deco
