"""worms_supabase / chat · Consultas en lenguaje natural (solo lectura) sobre el esquema reporting.

Aislado del resto de la app. Usa un rol Postgres READ-ONLY (ai_readonly) distinto
del DATABASE_URL de escritura, así no puede modificar nada bajo ninguna circunstancia.
"""
from .page import render

__all__ = ["render"]
