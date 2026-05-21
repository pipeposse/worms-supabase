"""Motor liviano del chat: traduce la pregunta a SQL con Gemini (vía HTTPS directo,
urllib de la stdlib — SIN dependencias nuevas) y la ejecuta SIEMPRE con el rol
read-only (ai_readonly), validada por el guardia SELECT-only."""
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


def _ejemplos() -> str:
    p = os.path.join(CONTEXTO_DIR, "training_examples.json")
    if not os.path.exists(p):
        return ""
    out = []
    for e in json.load(open(p, encoding="utf-8")):
        out.append(f"P: {e['question']}\nSQL: {e['sql']}")
    return "\n\n".join(out)


def _prompt(pregunta: str) -> str:
    return f"""Sos un asistente que traduce preguntas a UNA consulta SQL de PostgreSQL
para un dashboard de producción de una planta.

REGLAS ESTRICTAS:
- Devolvé UNA sola sentencia SELECT (o WITH ... SELECT). NUNCA INSERT/UPDATE/DELETE/DDL.
- Usá SOLO las vistas del esquema `reporting` descritas abajo. Calificá siempre con `reporting.`.
- "ayer" = current_date - 1, "hoy" = current_date, "este mes" = date_trunc('month', fecha)=date_trunc('month', current_date).
- Respondé ÚNICAMENTE con el SQL. Sin explicaciones, sin markdown, sin ```.

ESQUEMA DISPONIBLE:
{_schema_context()}

CONTEXTO DE NEGOCIO:
{_doc_negocio()}

EJEMPLOS:
{_ejemplos()}

Pregunta: {pregunta}
SQL:"""


# ──────────────────────── generación con Gemini (HTTPS directo) ────────────────────────
def _gemini(prompt: str) -> str:
    url = _GEMINI_URL.format(model=cfg.GEMINI_MODEL, key=cfg.GEMINI_API_KEY)
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0, "maxOutputTokens": 1024},
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detalle = e.read().decode("utf-8", "ignore")[:300]
        raise RuntimeError(f"Gemini respondió {e.code}: {detalle}")
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        raise RuntimeError(f"Respuesta inesperada de Gemini: {str(data)[:300]}")


def _extraer_sql(texto: str) -> str:
    t = (texto or "").strip()
    m = re.search(r"```(?:sql)?\s*(.*?)```", t, re.S | re.I)
    if m:
        t = m.group(1).strip()
    t = re.sub(r"^\s*sql\s*:\s*", "", t, flags=re.I)
    return t.strip().rstrip(";").strip()


def generate_sql(pregunta: str) -> str:
    return _extraer_sql(_gemini(_prompt(pregunta)))


__all__ = ["generate_sql", "run_sql_readonly", "is_select_only"]
