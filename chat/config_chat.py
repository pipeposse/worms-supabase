"""Config del chat. Reusa el cargador de etl.config (que ya vuelca .env y
st.secrets a os.environ) y lee solo lo que necesita el chat."""
import os

# importar etl.config dispara _load_dotenv() + _load_streamlit_secrets()
try:
    from etl import config as _etl_config  # noqa: F401
except Exception:
    pass

GEMINI_API_KEY  = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL    = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

# Rol Postgres SOLO LECTURA (ai_readonly). NUNCA el DATABASE_URL de escritura.
DATABASE_URL_RO = os.getenv("DATABASE_URL_RO")

# Statement timeout (ms) para cada consulta del chat.
STATEMENT_TIMEOUT_MS = int(os.getenv("CHAT_STATEMENT_TIMEOUT_MS", "15000"))

# Roles que pueden usar el chat.
ROLES_PERMITIDOS = {"SUPERVISOR", "ADMIN"}


def faltantes():
    """Devuelve la lista de secretos que faltan para que el chat funcione."""
    miss = []
    if not GEMINI_API_KEY:
        miss.append("GEMINI_API_KEY")
    if not DATABASE_URL_RO:
        miss.append("DATABASE_URL_RO")
    return miss
