"""worms_supabase / etl / db.py · PostgreSQL Supabase + login + admin + anulación."""
from contextlib import contextmanager
import hashlib, json
import psycopg2
from .config import DATABASE_URL


def hash_pin(pin):
    return hashlib.sha256(str(pin).encode("utf-8")).hexdigest()


@contextmanager
def conectar(id_usuario):
    if not DATABASE_URL:
        raise RuntimeError("Falta DATABASE_URL en .env")
    if id_usuario is None:
        raise RuntimeError("Sesión sin login. No se permite escribir.")
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute("SET search_path TO produccion, public")
            cur.execute("SELECT set_config('app.user_id', %s, false)", (str(id_usuario),))
        yield conn, _Audit(conn, id_usuario)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def login(nombre, pin):
    if not nombre or not pin or not DATABASE_URL:
        return None
    h = hash_pin(pin)
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute("SET search_path TO produccion, public")
            cur.execute(
                "SELECT id_usuario, nombre, nombre_full, rol, sector, sectores "
                "FROM dim_usuario WHERE nombre=%s AND pin_hash=%s AND activo=TRUE",
                (nombre.strip(), h)
            )
            row = cur.fetchone()
            if not row:
                return None
            cur.execute("UPDATE dim_usuario SET ultimo_login=NOW() WHERE id_usuario=%s", (row[0],))
            conn.commit()
            return {"id_usuario": row[0], "nombre": row[1], "nombre_full": row[2],
                    "rol": row[3], "sector": row[4], "sectores": row[5] or []}
    finally:
        conn.close()


def _es_admin(conn, id_usuario):
    with conn.cursor() as cur:
        cur.execute("SELECT rol FROM dim_usuario WHERE id_usuario=%s", (id_usuario,))
        r = cur.fetchone()
    return bool(r and r[0] == "ADMIN")


def _rol_de(conn, id_usuario):
    with conn.cursor() as cur:
        cur.execute("SELECT rol FROM dim_usuario WHERE id_usuario=%s", (id_usuario,))
        r = cur.fetchone()
    return r[0] if r else None


def crear_usuario(id_usuario_admin, nombre, nombre_full, pin, rol="OPERADOR", sector=None):
    h = hash_pin(pin)
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute("SET search_path TO produccion, public")
        if not _es_admin(conn, id_usuario_admin):
            raise PermissionError("Solo ADMIN puede crear usuarios")
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO dim_usuario(nombre,nombre_full,pin_hash,rol,sector) "
                "VALUES (%s,%s,%s,%s,%s) RETURNING id_usuario",
                (nombre.strip(), nombre_full, h, rol, sector)
            )
            new_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO aud_eventos(id_usuario,operacion,tabla,pk_valor,cambios) "
                "VALUES (%s,'I','dim_usuario',%s,%s::jsonb)",
                (id_usuario_admin, str(new_id),
                 json.dumps({"alta": nombre, "rol": rol, "sector": sector}))
            )
            conn.commit()
            return new_id
    finally:
        conn.close()


def _admin_update(id_usuario_admin, id_usuario_target, sql, args, audit_diff):
    if id_usuario_admin == id_usuario_target and "activo" in audit_diff:
        raise PermissionError("No te podés desactivar a vos mismo")
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute("SET search_path TO produccion, public")
        if not _es_admin(conn, id_usuario_admin):
            raise PermissionError("Solo ADMIN puede modificar usuarios")
        with conn.cursor() as cur:
            cur.execute(sql, args)
            cur.execute(
                "INSERT INTO aud_eventos(id_usuario,operacion,tabla,pk_valor,cambios) "
                "VALUES (%s,'U','dim_usuario',%s,%s::jsonb)",
                (id_usuario_admin, str(id_usuario_target), json.dumps(audit_diff))
            )
            conn.commit()
    finally:
        conn.close()


def reset_pin(id_usuario_admin, id_usuario_target, pin_nuevo):
    h = hash_pin(pin_nuevo)
    _admin_update(id_usuario_admin, id_usuario_target,
        "UPDATE dim_usuario SET pin_hash=%s WHERE id_usuario=%s",
        (h, id_usuario_target), {"reset_pin": True})


def cambiar_rol(id_usuario_admin, id_usuario_target, rol_nuevo):
    if rol_nuevo not in ("OPERADOR","SUPERVISOR","ADMIN"):
        raise ValueError("Rol inválido")
    _admin_update(id_usuario_admin, id_usuario_target,
        "UPDATE dim_usuario SET rol=%s WHERE id_usuario=%s",
        (rol_nuevo, id_usuario_target), {"rol_nuevo": rol_nuevo})


def cambiar_sector(id_usuario_admin, id_usuario_target, sector_nuevo):
    _admin_update(id_usuario_admin, id_usuario_target,
        "UPDATE dim_usuario SET sector=%s WHERE id_usuario=%s",
        (sector_nuevo, id_usuario_target), {"sector_nuevo": sector_nuevo})


def cambiar_sectores(id_usuario_admin, id_usuario_target, sectores_lista):
    """Asigna la lista de sectores accesibles a un usuario (multi-sector).
    Si la lista está vacía, el usuario tiene acceso a todos."""
    if sectores_lista is None:
        sectores_lista = []
    _admin_update(id_usuario_admin, id_usuario_target,
        "UPDATE dim_usuario SET sectores=%s::jsonb WHERE id_usuario=%s",
        (json.dumps(sectores_lista), id_usuario_target),
        {"sectores_nuevos": sectores_lista})


def set_activo(id_usuario_admin, id_usuario_target, activo):
    _admin_update(id_usuario_admin, id_usuario_target,
        "UPDATE dim_usuario SET activo=%s WHERE id_usuario=%s",
        (activo, id_usuario_target), {"activo": activo})


def cambiar_mi_pin(id_usuario, pin_actual, pin_nuevo):
    h_act = hash_pin(pin_actual); h_new = hash_pin(pin_nuevo)
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute("SET search_path TO produccion, public")
            cur.execute("SELECT 1 FROM dim_usuario WHERE id_usuario=%s AND pin_hash=%s",
                        (id_usuario, h_act))
            if cur.fetchone() is None:
                raise PermissionError("PIN actual incorrecto")
            cur.execute("UPDATE dim_usuario SET pin_hash=%s WHERE id_usuario=%s",
                        (h_new, id_usuario))
            cur.execute(
                "INSERT INTO aud_eventos(id_usuario,operacion,tabla,pk_valor,cambios) "
                "VALUES (%s,'U','dim_usuario',%s,%s::jsonb)",
                (id_usuario, str(id_usuario), json.dumps({"cambio_pin_propio": True}))
            )
            conn.commit()
    finally:
        conn.close()


# =========================================================================
#                       ANULACIÓN DE REGISTROS
# =========================================================================
TABLAS_ANULABLES = {
    "fact_batch_proceso": "id_batch",
}

# Ventana de tiempo (horas) en la que un OPERADOR puede anular sus propias cargas.
VENTANA_OPERADOR_HORAS    = 24
VENTANA_SUPERVISOR_DIAS   = 7
# ADMIN: sin límite


def listar_mis_cargas(id_usuario, rol, dias_atras=7):
    """Lista cargas de producción. OPERADOR ve solo las suyas."""
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute("SET search_path TO produccion, public")
            filtro_user = "" if rol in ("SUPERVISOR","ADMIN") else " AND id_usuario_carga = %s "
            params_b = [dias_atras] + ([id_usuario] if rol == "OPERADOR" else [])
            params_e = [dias_atras] + ([id_usuario] if rol == "OPERADOR" else [])

            cur.execute(f"""
                SELECT
                    CASE WHEN b.tipo_operacion='RECUPERACION' THEN 'recuperacion'
                         ELSE 'produccion' END AS tipo,
                    b.id_batch AS id, b.fecha, b.sector,
                    p.codigo_producto AS detalle, b.kg_obtenido AS valor,
                    b.anulado, b.creado_en, u.nombre AS cargado_por
                FROM fact_batch_proceso b
                JOIN dim_producto p ON p.id_producto = b.id_producto_obtenido
                JOIN dim_usuario u  ON u.id_usuario  = b.id_usuario_carga
                WHERE b.creado_en >= NOW() - INTERVAL '%s days'
                {filtro_user}
                ORDER BY b.creado_en DESC
            """, params_b)
            rows_b = cur.fetchall()

            todas = rows_b
            todas.sort(key=lambda r: r[7], reverse=True)
            return todas
    finally:
        conn.close()


def puede_anular(rol, propio, creado_en):
    """Devuelve (bool, motivo). Reglas por rol y ventana temporal."""
    from datetime import datetime, timezone
    ahora = datetime.now(timezone.utc)
    delta_horas = (ahora - creado_en).total_seconds() / 3600 if creado_en else 999_999
    if rol == "ADMIN":
        return (True, "ADMIN sin límite")
    if rol == "SUPERVISOR":
        if delta_horas <= VENTANA_SUPERVISOR_DIAS * 24:
            return (True, f"SUPERVISOR · dentro de {VENTANA_SUPERVISOR_DIAS} días")
        return (False, f"Supera {VENTANA_SUPERVISOR_DIAS} días — solo ADMIN")
    if rol == "OPERADOR":
        if not propio:
            return (False, "OPERADOR solo anula sus propias cargas")
        if delta_horas <= VENTANA_OPERADOR_HORAS:
            return (True, f"OPERADOR · dentro de {VENTANA_OPERADOR_HORAS} h")
        return (False, f"Supera {VENTANA_OPERADOR_HORAS} h — pedile a un supervisor")
    return (False, "Rol desconocido")


def anular_registro(id_usuario, tabla, pk_valor, motivo):
    """Anula un registro. Verifica permisos por rol/tiempo. Audita el evento."""
    if tabla not in TABLAS_ANULABLES:
        raise ValueError(f"Tabla {tabla} no es anulable")
    if not motivo or len(motivo.strip()) < 5:
        raise ValueError("El motivo es obligatorio (min 5 caracteres)")
    pk_col = TABLAS_ANULABLES[tabla]
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute("SET search_path TO produccion, public")
            # Obtener el registro original (creador, fecha, anulado actual)
            cur.execute(f"SELECT id_usuario_carga, creado_en, anulado FROM {tabla} WHERE {pk_col}=%s",
                        (pk_valor,))
            r = cur.fetchone()
            if not r:
                raise ValueError(f"Registro #{pk_valor} no encontrado en {tabla}")
            id_creador, creado_en, ya_anulado = r
            if ya_anulado:
                raise ValueError("Ese registro ya está anulado")
            rol = _rol_de(conn, id_usuario)
            propio = (id_creador == id_usuario)
            ok, motivo_check = puede_anular(rol, propio, creado_en)
            if not ok:
                raise PermissionError(f"No podés anular este registro: {motivo_check}")
            cur.execute(f"""
                UPDATE {tabla}
                SET anulado=TRUE, motivo_anulacion=%s,
                    id_usuario_anula=%s, anulado_en=NOW()
                WHERE {pk_col}=%s
            """, (motivo.strip(), id_usuario, pk_valor))
            cur.execute(
                "INSERT INTO aud_eventos(id_usuario,operacion,tabla,pk_valor,cambios) "
                "VALUES (%s,'U',%s,%s,%s::jsonb)",
                (id_usuario, tabla, str(pk_valor),
                 json.dumps({"anular": True, "motivo": motivo.strip(),
                             "regla_aplicada": motivo_check}))
            )
            conn.commit()
    finally:
        conn.close()


# =========================================================================
class _Audit:
    def __init__(self, conn, id_usuario):
        self.conn = conn
        self.id_usuario = id_usuario
    def log(self, operacion, tabla, pk_valor, cambios):
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO aud_eventos(id_usuario, operacion, tabla, pk_valor, cambios) "
                "VALUES (%s, %s, %s, %s, %s::jsonb)",
                (self.id_usuario, operacion[:1].upper(), tabla,
                 str(pk_valor) if pk_valor is not None else None,
                 json.dumps(cambios, ensure_ascii=False, default=str)),
            )
    def insert(self, tabla, pk, valores): self.log("I", tabla, pk, valores)
    def update(self, tabla, pk, antes, despues): self.log("U", tabla, pk, {"antes":antes,"despues":despues})
    def delete(self, tabla, pk, valores): self.log("D", tabla, pk, valores)


def producto_id(conn, codigo):
    if not codigo: return None
    with conn.cursor() as cur:
        cur.execute("SELECT id_producto FROM dim_producto WHERE codigo_producto=%s",(codigo,))
        r = cur.fetchone()
    return r[0] if r else None


def parametro_info(conn, codigo):
    if not codigo: return None
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id_parametro, unidad, rango_min, rango_max "
            "FROM dim_parametro_lab WHERE codigo_parametro=%s", (codigo,))
        r = cur.fetchone()
    return None if not r else {"id_parametro": r[0], "unidad": r[1], "rango_min": r[2], "rango_max": r[3]}


def convertir(conn, valor, origen, destino, contexto="GLOBAL"):
    if origen == destino or valor is None: return valor
    with conn.cursor() as cur:
        cur.execute(
            "SELECT factor FROM ref_conversion_unidades "
            "WHERE unidad_origen=%s AND unidad_destino=%s "
            "AND contexto IN (%s,'GLOBAL') "
            "AND (vigente_hasta IS NULL OR vigente_hasta >= CURRENT_DATE) "
            "AND vigente_desde <= CURRENT_DATE "
            "ORDER BY (contexto=%s) DESC, vigente_desde DESC LIMIT 1",
        (origen, destino, contexto, contexto))
        r = cur.fetchone()
    return None if r is None else float(valor) * float(r[0])
