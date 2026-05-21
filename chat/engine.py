"""Motor liviano del chat: Gemini (google-generativeai) traduce la pregunta a SQL,
que se ejecuta SIEMPRE con el rol read-only (ai_readonly) y se valida con el guardia
SELECT-only. Sin Vanna ni ChromaDB → liviano y robusto en Streamlit Cloud."""
import os
import json
import re

import pandas as pd
import psycopg2
import streamlit as st

from . import config_chat as cfg
from .guard import assert_safe, is_select_only

CONTEXTO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "contexto")


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


# ──────────────────────── generación con Gemini ────────────────────────
@st.cache_resource(show_spinner=False)
def _model():
    import google.generativeai as genai
    genai.configure(api_key=cfg.GEMINI_API_KEY)
    return genai.GenerativeModel(cfg.GEMINI_MODEL)


def _extraer_sql(texto: str) -> str:
    t = (texto or "").strip()
    m = re.search(r"```(?:sql)?\s*(.*?)```", t, re.S | re.I)
    if m:
        t = m.group(1).strip()
    t = re.sub(r"^\s*sql\s*:\s*", "", t, flags=re.I)
    return t.strip().rstrip(";").strip()


def generate_sql(pregunta: str) -> str:
    resp = _model().generate_content(_prompt(pregunta))
    return _extraer_sql(getattr(resp, "text", ""))


__all__ = ["generate_sql", "run_sql_readonly", "is_select_only"]
