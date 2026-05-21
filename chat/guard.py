"""Guardia SQL (sin dependencias externas): defensa en profundidad sobre el rol
read-only. Solo permite UNA sentencia y solo SELECT / WITH...SELECT."""
import re

_FORBIDDEN = {
    "insert", "update", "delete", "drop", "alter", "create", "truncate",
    "grant", "revoke", "merge", "call", "do", "copy", "vacuum", "analyze",
    "comment", "reindex", "refresh", "set", "reset", "begin", "commit",
    "rollback", "savepoint", "execute", "prepare", "deallocate", "lock",
}


class UnsafeSQLError(ValueError):
    pass


def _strip_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)   # /* ... */
    sql = re.sub(r"--[^\n]*", " ", sql)                # -- ...
    return sql


def is_select_only(sql: str) -> bool:
    if not sql or not sql.strip():
        return False
    cleaned = _strip_comments(sql).strip().rstrip(";").strip()
    if not cleaned:
        return False
    # una sola sentencia: no puede quedar ';' en el medio
    if ";" in cleaned:
        return False
    first = cleaned.lstrip().split(None, 1)[0].lower()
    if first not in ("select", "with"):
        return False
    lowered = cleaned.lower()
    for kw in _FORBIDDEN:
        if re.search(rf"(^|[\s(]){kw}([\s(]|$)", lowered):
            return False
    return True


def assert_safe(sql: str) -> str:
    if not is_select_only(sql):
        raise UnsafeSQLError("Consulta bloqueada: solo se permiten SELECT de lectura.")
    return sql
