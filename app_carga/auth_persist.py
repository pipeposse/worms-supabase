"""worms_supabase / app_carga / auth_persist.py
Sesión persistente vía cookie firmada (HMAC-SHA256). Requiere Streamlit >= 1.37.

- Al loguear: se emite un token id_usuario|expiración firmado y se guarda en cookie.
- Al abrir la app sin sesión: se valida la cookie y se restaura el usuario desde la DB
  (solo si sigue activo). Sobrevive bloqueo del celular, recarga y cierre del navegador.
- Logout: borra la cookie.

Config opcional por variable de entorno / .env:
  WORMS_SESSION_DIAS    días de validez (default 30)
  WORMS_SESSION_SECRET  secreto de firma (default: derivado de DATABASE_URL)
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time

import psycopg2
import streamlit as st
import streamlit.components.v1 as components

from etl.config import DATABASE_URL

COOKIE = "worms_session"
DIAS_SESION = int(os.getenv("WORMS_SESSION_DIAS", "30"))


def _secret() -> bytes:
    s = os.getenv("WORMS_SESSION_SECRET") or (DATABASE_URL or "worms-dev")
    return hashlib.sha256(("worms|" + s).encode("utf-8")).digest()


def make_token(id_usuario: int, dias: int = DIAS_SESION) -> str:
    payload = f"{id_usuario}|{int(time.time()) + dias * 86400}"
    sig = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(payload.encode()).decode() + "." + sig


def validar_token(tok: str) -> int | None:
    try:
        b64, sig = tok.split(".", 1)
        payload = base64.urlsafe_b64decode(b64.encode()).decode()
        esperado = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(esperado, sig):
            return None
        id_u, exp = payload.split("|")
        if time.time() > int(exp):
            return None
        return int(id_u)
    except Exception:
        return None


def usuario_por_id(id_usuario: int) -> dict | None:
    """Carga el usuario desde la DB. None si no existe o está desactivado."""
    if not DATABASE_URL:
        return None
    try:
        conn = psycopg2.connect(DATABASE_URL)
        try:
            with conn.cursor() as cur:
                cur.execute("SET search_path TO produccion, public")
                cur.execute(
                    "SELECT id_usuario, nombre, nombre_full, rol, sector, sectores "
                    "FROM dim_usuario WHERE id_usuario=%s AND activo=TRUE",
                    (id_usuario,),
                )
                row = cur.fetchone()
            if not row:
                return None
            return {"id_usuario": row[0], "nombre": row[1], "nombre_full": row[2],
                    "rol": row[3], "sector": row[4], "sectores": row[5] or []}
        finally:
            conn.close()
    except Exception:
        return None


def set_cookie(token: str, dias: int = DIAS_SESION) -> None:
    components.html(
        f"""<script>
        try {{
          const c = "{COOKIE}={token}; max-age={dias * 86400}; path=/; SameSite=Lax";
          try {{ parent.document.cookie = c; }} catch (e) {{ document.cookie = c; }}
        }} catch (e) {{}}
        </script>""",
        height=0,
    )


def clear_cookie() -> None:
    components.html(
        f"""<script>
        try {{
          const c = "{COOKIE}=; max-age=0; path=/; SameSite=Lax";
          try {{ parent.document.cookie = c; }} catch (e) {{ document.cookie = c; }}
        }} catch (e) {{}}
        </script>""",
        height=0,
    )


def restaurar_sesion() -> dict | None:
    """Lee la cookie del request actual y devuelve el usuario si el token es válido."""
    try:
        tok = st.context.cookies.get(COOKIE)
    except Exception:
        return None
    if not tok:
        return None
    id_u = validar_token(tok)
    if id_u is None:
        return None
    return usuario_por_id(id_u)
