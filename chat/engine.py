"""Motor liviano del chat: traduce la pregunta a SQL con Gemini (vía HTTPS directo,
urllib de la stdlib — SIN dependencias nuevas) y la ejecuta SIEMPRE con el rol
read-only (ai_readonly), validada por el guardia SELECT-only.

Incluye:
  - RAG: recuperación semántica de ejemplos pregunta->SQL (pgvector + text-embedding-004),
    con fallback a los ejemplos estáticos si los embeddings no están sincronizados.
  - Self-heal: si Postgres rechaza el SQL, se reinyecta el error a Gemini para corregir.
"""
import os
import re
import json
import urllib.request
import urllib.error

import pandas as pd
import psycopg2
import streamlit as st

from . import config_chat as cfg
from .guard import assert_safe, is_select_only

CONTEXTO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "contexto")
_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
_EMBED_MODEL = "text-embedding-004"
_EMBED_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:embedContent?key={key}"
_RAG_TOP_K = 6


# ──────────────────────── ejecución read-only ────────────────────────
def run_sql_readonly(sql: str) -> pd.DataFrame:
    """Ejecuta SOLO SELECT, con el rol ai_readonly, sesión read-only y timeout."""
    assert_safe(sql)
    conn = psycopg2.connect(cfg.DATABASE_URL_RO)
    try:
        conn.set_session(readonly=True, autocommit=False)
        with conn.cursor() as cur:
            cur.execute(f"SET statement_timeout = {int(cfg.STATEMENT_TIMEOUT_MS)}")
        return pd.read_sql_query(sql, conn)
    finally:
        try:
            conn.rollback()
        except Exception:
            pass
        conn.close()


# ──────────────────────── contexto (esquema + ejemplos) ────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def _schema_context() -> str:
    """Lista columnas + comentarios de las vistas de reporting (leído de la BD)."""
    df = run_sql_readonly("""
        SELECT c.relname AS vista, a.attname AS columna,
               format_type(a.atttypid, a.atttypmod) AS tipo,
               col_description(c.oid, a.attnum) AS comentario
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
        WHERE n.nspname = 'reporting' AND c.relkind IN ('v','m','r')
          AND c.relname <> 'nl_examples'
        ORDER BY c.relname, a.attnum
    """)
    lineas = []
    for vista, grp in df.groupby("vista"):
        lineas.append(f"\nVista reporting.{vista}:")
        for r in grp.itertuples():
            com = f"  -- {r.comentario}" if r.comentario else ""
            lineas.append(f"  - {r.columna} ({r.tipo}){com}")
    return "\n".join(lineas)


def _doc_negocio() -> str:
    p = os.path.join(CONTEXTO_DIR, "business_context.md")
    return open(p, encoding="utf-8").read().strip() if os.path.exists(p) else ""


def _ejemplos_estaticos() -> str:
    """Todos los ejemplos del JSON (fallback cuando no hay embeddings)."""
    p = os.path.join(CONTEXTO_DIR, "training_examples.json")
    if not os.path.exists(p):
        return ""
    out = []
    for e in json.load(open(p, encoding="utf-8")):
        out.append(f"P: {e['question']}\nSQL: {e['sql']}")
    return "\n\n".join(out)


# ──────────────────────── RAG: embeddings + recuperación ────────────────────────
def _embed(texto: str):
    """Vector de 768 dims con text-embedding-004 (gratis). Lanza si falla."""
    body = json.dumps({
        "model": f"models/{_EMBED_MODEL}",
        "content": {"parts": [{"text": texto}]},
    }).encode("utf-8")
    url = _EMBED_URL.format(model=_EMBED_MODEL, key=cfg.GEMINI_API_KEY)
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode("utf-8"))
    return data["embedding"]["values"]


@st.cache_data(ttl=900, show_spinner=False)
def _recuperar_ejemplos(pregunta: str, k: int = _RAG_TOP_K):
    """Top-k ejemplos por similitud coseno (RAG). Devuelve None si no hay
    embeddings sincronizados o si algo falla -> el caller cae al fallback estático."""
    if not cfg.GEMINI_API_KEY:
        return None
    try:
        vec = _embed(pregunta)
    except Exception:
        return None
    conn = psycopg2.connect(cfg.DATABASE_URL_RO)
    try:
        conn.set_session(readonly=True, autocommit=True)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pregunta, sql FROM reporting.nl_examples "
                "WHERE embedding IS NOT NULL "
                "ORDER BY embedding <=> %s::vector LIMIT %s",
                (str(vec), int(k)),
            )
            filas = cur.fetchall()
    except Exception:
        return None
    finally:
        conn.close()
    if not filas:
        return None
    return "\n\n".join(f"P: {p}\nSQL: {s}" for p, s in filas)


def _ejemplos_para_prompt(pregunta: str) -> str:
    """RAG si está disponible; si no, todos los ejemplos estáticos."""
    rag = _recuperar_ejemplos(pregunta)
    return rag if rag else _ejemplos_estaticos()


def sync_embeddings(verbose: bool = True) -> int:
    """Carga/actualiza los embeddings de training_examples.json en
    reporting.nl_examples. Idempotente: salta los que ya están embebidos.
    Requiere DATABASE_URL (rol de ESCRITURA) y GEMINI_API_KEY.
    Devuelve cuántos ejemplos embebió en esta corrida."""
    if not cfg.GEMINI_API_KEY:
        raise RuntimeError("Falta GEMINI_API_KEY para generar embeddings.")
    write_url = os.getenv("DATABASE_URL") or os.getenv("DATABASE_URL_RW")
    if not write_url:
        raise RuntimeError("Falta DATABASE_URL (rol de escritura) para sincronizar embeddings.")
    p = os.path.join(CONTEXTO_DIR, "training_examples.json")
    ejemplos = json.load(open(p, encoding="utf-8"))
    conn = psycopg2.connect(write_url)
    n = 0
    try:
        with conn:
            with conn.cursor() as cur:
                for e in ejemplos:
                    preg, sql = e["question"], e["sql"]
                    cur.execute(
                        "SELECT embedding IS NOT NULL FROM reporting.nl_examples WHERE pregunta=%s",
                        (preg,),
                    )
                    row = cur.fetchone()
                    if row and row[0]:
                        continue
                    vec = _embed(preg)
                    cur.execute(
                        "INSERT INTO reporting.nl_examples (pregunta, sql, embedding) "
                        "VALUES (%s, %s, %s::vector) "
                        "ON CONFLICT (pregunta) DO UPDATE SET sql=EXCLUDED.sql, "
                        "embedding=EXCLUDED.embedding, actualizado=now()",
                        (preg, sql, str(vec)),
                    )
                    n += 1
                    if verbose:
                        print(f"  embebido: {preg[:60]}")
    finally:
        conn.close()
    return n


# ──────────────────────── prompts ────────────────────────
def _prompt(pregunta: str) -> str:
    return f"""Sos un asistente que traduce preguntas a UNA consulta SQL de PostgreSQL
para un dashboard de producción de una planta.

REGLAS ESTRICTAS:
- Devolvé UNA sola sentencia SELECT (o WITH ... SELECT). NUNCA INSERT/UPDATE/DELETE/DDL.
- Usá SOLO las vistas del esquema `reporting` descritas abajo. Calificá siempre con `reporting.`.
- Elegí la vista según el tema: producción / cargas / reacciones / ARE / desgomado / rendimiento / merma -> `reporting.v_produccion`;
  camiones / pesaje / portería / procedencia -> `reporting.v_camiones`; laboratorio / análisis / calidad / muestras -> `reporting.v_laboratorio`;
  tanques / stock / nivel / volumen / litros en tanque / capacidad / sensor / WeDo -> `reporting.v_tanques`;
  variación o evolución de stock de un tanque por día -> `reporting.v_tanque_variacion`.
  Usá el "Diccionario de sinónimos" del contexto para mapear las palabras de la pregunta a columnas.
- Para comparar dos períodos (ej. "más camiones en abril o en mayo") devolvé una fila por período usando `to_char(fecha,'YYYY-MM')` y `GROUP BY`, ordenado para que se vea la comparación.
- En producción, devolvé cantidades en TONELADAS (columnas `*_tn`) salvo que pidan kg o litros explícitamente.
- Si la pregunta es ambigua, elegí la interpretación más útil y agrupá por la dimensión mencionada (reactor, proceso, corriente, producto, fecha).
- "ayer" = current_date - 1, "hoy" = current_date, "este mes" = date_trunc('month', fecha)=date_trunc('month', current_date).
- "worms" / "la planta" / "la fábrica" / "la empresa" se refieren a TODA la operación: NO uses esas palabras como filtro.
- "insumos" / "materia prima" / "MP" / "lo que entró o ingresó" = camiones con `sentido='ENTRADA'` en `reporting.v_camiones`; el material es la columna `producto` (para una lista usá DISTINCT producto). "lo que salió/despachos" = `sentido='SALIDA'`.
- No inventes filtros de texto (ILIKE) salvo que la pregunta nombre un valor concreto de una columna real.
- Respondé ÚNICAMENTE con el SQL. Sin explicaciones, sin markdown, sin comillas triples.

ESQUEMA DISPONIBLE:
{_schema_context()}

CONTEXTO DE NEGOCIO:
{_doc_negocio()}

EJEMPLOS (los más parecidos a la pregunta):
{_ejemplos_para_prompt(pregunta)}

Pregunta: {pregunta}
SQL:"""


def _prompt_correccion(pregunta: str, sql_malo: str, error: str) -> str:
    return f"""La consulta SQL generada falló al ejecutarse en PostgreSQL. Corregila.

Pregunta original: {pregunta}

SQL que falló:
{sql_malo}

Error de PostgreSQL:
{error}

ESQUEMA DISPONIBLE (usá SOLO estas vistas y columnas; corregí nombres mal escritos):
{_schema_context()}

Devolvé ÚNICAMENTE el SQL corregido: UNA sola sentencia SELECT sobre el esquema `reporting`. Sin explicaciones ni markdown."""


# ──────────────────────── generación con Gemini (HTTPS directo) ────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def _modelos_disponibles():
    """Le pregunta a la API qué modelos soporta TU key (no hardcodea nombres -> a prueba
    de deprecaciones). Devuelve los que soportan generateContent."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={cfg.GEMINI_API_KEY}"
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception:
        return []
    out = []
    for m in data.get("models", []):
        if "generateContent" in m.get("supportedGenerationMethods", []):
            nombre = m.get("name", "").split("/")[-1]
            if nombre:
                out.append(nombre)
    return out


def _orden_modelos():
    """Orden de preferencia: el configurado (si existe), luego flash-lite, luego flash,
    evitando 'pro' (caro) y 'preview/exp'. Si ListModels falla, usa nombres de respaldo."""
    disp = _modelos_disponibles()
    if not disp:
        disp = ["gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-flash-latest", cfg.GEMINI_MODEL]

    def rank(m):
        s = 0
        if m == cfg.GEMINI_MODEL: s -= 100
        if "flash-lite" in m:     s -= 40
        elif "flash" in m:        s -= 30
        if "latest" in m:         s -= 5
        if "pro" in m:            s += 50
        if "preview" in m or "exp" in m: s += 20
        return s

    vistos, orden = set(), []
    for m in sorted([d for d in disp if d], key=rank):
        if m not in vistos:
            vistos.add(m)
            orden.append(m)
    return orden


def _gemini(prompt: str) -> str:
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0, "maxOutputTokens": 1024},
    }).encode("utf-8")
    sin_cuota = []
    for modelo in _orden_modelos():
        url = _GEMINI_URL.format(model=modelo, key=cfg.GEMINI_API_KEY)
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (429, 404):
                sin_cuota.append(f"{modelo}({e.code})")
                continue
            detalle = e.read().decode("utf-8", "ignore")[:300]
            raise RuntimeError(f"Gemini ({modelo}) respondió {e.code}: {detalle}")
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError):
            raise RuntimeError(f"Respuesta inesperada de Gemini: {str(data)[:200]}")
    raise RuntimeError(
        "Se agotó la cuota gratis de Gemini en todos los modelos probados "
        f"({', '.join(sin_cuota)}). Esperá unos minutos, o activá facturación "
        "en la API key (es la solución definitiva)."
    )


def _extraer_sql(texto: str) -> str:
    t = (texto or "").strip()
    m = re.search(r"```(?:sql)?\s*(.*?)```", t, re.S | re.I)
    if m:
        t = m.group(1).strip()
    t = re.sub(r"^\s*sql\s*:\s*", "", t, flags=re.I)
    return t.strip().rstrip(";").strip()


def generate_sql(pregunta: str) -> str:
    return _extraer_sql(_gemini(_prompt(pregunta)))


def _prompt_vacio(pregunta: str, sql_vacio: str) -> str:
    return f"""La siguiente consulta es válida pero devolvió 0 filas. Casi seguro tiene un
filtro innecesario o demasiado estricto. Reformulala SACANDO ese filtro de más.

PISTAS:
- "worms" / "la planta" / "la fábrica" / "la empresa" NO son un filtro: se refieren a toda la operación.
- "insumos" / "materia prima" / "MP" / "lo que entró" = camiones con sentido='ENTRADA' en reporting.v_camiones (columna `producto`).
- No uses ILIKE con palabras que no sean un valor concreto de una columna.

Pregunta: {pregunta}

SQL que devolvió 0 filas:
{sql_vacio}

ESQUEMA DISPONIBLE:
{_schema_context()}

Devolvé ÚNICAMENTE el SQL corregido: UNA sola sentencia SELECT sobre el esquema `reporting`. Sin explicaciones ni markdown."""


# ──────────────────────── orquestador con self-heal ────────────────────────
def resolver(pregunta: str, max_intentos: int = 2) -> dict:
    """Genera el SQL, lo ejecuta y se AUTOCORRIGE:
    - ante un error de Postgres reinyecta el mensaje de error (hasta `max_intentos`);
    - ante 0 filas hace UN reintento sacando filtros innecesarios (ej. el nombre de la planta).
    Devuelve {sql, df, ok, intentos:[{sql,estado,...}], error}."""
    intentos = []
    sql = generate_sql(pregunta)
    err = None
    reintento_vacio = False
    for i in range(max_intentos + 1):
        if not is_select_only(sql):
            err = "La consulta debe ser UNA sola sentencia SELECT de solo lectura sobre el esquema reporting."
            intentos.append({"sql": sql, "estado": "bloqueado", "detalle": err})
        else:
            try:
                df = run_sql_readonly(sql)
                if len(df) == 0 and not reintento_vacio and i < max_intentos:
                    reintento_vacio = True
                    intentos.append({"sql": sql, "estado": "vacio", "filas": 0})
                    try:
                        sql = _extraer_sql(_gemini(_prompt_vacio(pregunta, sql)))
                        continue
                    except Exception:
                        intentos.append({"sql": sql, "estado": "ok", "filas": 0})
                        return {"sql": sql, "df": df, "ok": True, "intentos": intentos, "error": None}
                intentos.append({"sql": sql, "estado": "ok", "filas": int(len(df))})
                return {"sql": sql, "df": df, "ok": True, "intentos": intentos, "error": None}
            except Exception as e:
                err = str(e)
                intentos.append({"sql": sql, "estado": "error", "detalle": err[:400]})
        if i >= max_intentos:
            break
        try:
            sql = _extraer_sql(_gemini(_prompt_correccion(pregunta, sql, err)))
        except Exception as e:
            err = f"No se pudo autocorregir: {e}"
            break
    return {"sql": sql, "df": None, "ok": False, "intentos": intentos, "error": err}


__all__ = [
    "generate_sql", "run_sql_readonly", "is_select_only",
    "resolver", "sync_embeddings",
]
