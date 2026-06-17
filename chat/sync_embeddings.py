"""Sincroniza los embeddings de training_examples.json en reporting.nl_examples.

Idempotente: solo embebe los ejemplos que falten. Corré esto UNA vez (y cada vez
que agregues ejemplos nuevos al JSON) para activar el RAG semántico del chat.

Requiere en el entorno (o en .env / st.secrets que carga etl.config):
  - GEMINI_API_KEY
  - DATABASE_URL   (rol de ESCRITURA; no el read-only)

Uso:
    python -m chat.sync_embeddings
"""
import sys

from .engine import sync_embeddings


def main():
    try:
        n = sync_embeddings(verbose=True)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    if n == 0:
        print("Nada que hacer: todos los ejemplos ya estaban embebidos.")
    else:
        print(f"Listo: {n} ejemplo(s) embebido(s). El chat ya usa RAG semántico.")


if __name__ == "__main__":
    main()
