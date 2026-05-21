"""Guardia SQL: defensa en profundidad sobre el rol read-only.
Solo permite UNA sentencia y solo SELECT / WITH...SELECT.
Bloquea DML/DDL aunque el modelo lo genere por error."""
import re
import sqlparse

_FORBIDDEN = {
    "insert", "update", "delete", "drop", "alter", "create", "truncate",
    "grant", "revoke", "merge", "call", "do", "copy", "vacuum", "analyze",
    "comment", "reindex", "refresh", "set", "reset", "begin", "commit",
    "rollback", "savepoint", "execute", "prepare", "deallocate", "lock",
}


class UnsafeSQLError(ValueError):
    pass


def is_select_only(sql: str) -> bool:
    if not sql or not sql.strip():
        return False
    cleaned = sqlparse.format(sql, strip_comments=True).strip().rstrip(";").strip()
    if not cleaned:
        return False
    statements = [s for s in sqlparse.parse(cleaned) if str(s).strip()]
    if len(statements) != 1:
        return False  # nada de múltiples sentencias
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
