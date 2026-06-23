"""Autenticacion y gestion de usuarios para la app GAPRE.

Usa PBKDF2-HMAC-SHA256 (libreria estandar, sin dependencias extra).
Los usuarios viven en gapre.app_usuarios.
"""
import base64
import hashlib
import hmac
import os

import streamlit as st

import db

_ITERS = 200_000


# ---------------------------------------------------------------------------
# Hash de contrasenas
# ---------------------------------------------------------------------------
def hash_password(password, salt=None):
    if salt is None:
        salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERS)
    return base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()


def verify_password(password, stored):
    try:
        salt_b64, _ = stored.split("$", 1)
        salt = base64.b64decode(salt_b64)
        return hmac.compare_digest(hash_password(password, salt), stored)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Consultas de usuarios
# ---------------------------------------------------------------------------
def contar_usuarios():
    return db.q("select count(*) c from gapre.app_usuarios")[0]["c"]


def listar_usuarios():
    return db.q("select id, username, nombre, rol, activo, last_login "
                "from gapre.app_usuarios order by username")


def crear_usuario(username, password, nombre, rol="operador"):
    db.execute(
        "insert into gapre.app_usuarios (username, pass_hash, nombre, rol) "
        "values (%s, %s, %s, %s)",
        [username.strip().lower(), hash_password(password), nombre or None, rol],
    )


def set_password(user_id, password):
    db.execute("update gapre.app_usuarios set pass_hash=%s where id=%s",
               [hash_password(password), user_id])


def set_activo(user_id, activo):
    db.execute("update gapre.app_usuarios set activo=%s where id=%s", [activo, user_id])


def _get_user(username):
    rows = db.q("select * from gapre.app_usuarios where username=%s",
                [username.strip().lower()])
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# Pantallas
# ---------------------------------------------------------------------------
def _bootstrap_primer_admin():
    st.subheader("Crear primer administrador")
    st.caption("No hay usuarios todavia. Crea la cuenta de administrador inicial.")
    with st.form("bootstrap"):
        u = st.text_input("Usuario")
        n = st.text_input("Nombre")
        p1 = st.text_input("Contrasena", type="password")
        p2 = st.text_input("Repetir contrasena", type="password")
        ok = st.form_submit_button("Crear administrador", type="primary")
    if ok:
        if not u or not p1:
            st.error("Usuario y contrasena son obligatorios.")
        elif p1 != p2:
            st.error("Las contrasenas no coinciden.")
        else:
            crear_usuario(u, p1, n, rol="admin")
            st.success("Administrador creado. Ya podes iniciar sesion.")
            st.rerun()


def _login_form():
    st.subheader("Iniciar sesion")
    with st.form("login"):
        u = st.text_input("Usuario")
        p = st.text_input("Contrasena", type="password")
        ok = st.form_submit_button("Entrar", type="primary")
    if ok:
        user = _get_user(u)
        if user and user["activo"] and verify_password(p, user["pass_hash"]):
            db.execute("update gapre.app_usuarios set last_login=now() where id=%s",
                       [user["id"]])
            st.session_state["user"] = {
                "id": user["id"], "username": user["username"],
                "nombre": user["nombre"], "rol": user["rol"],
            }
            st.rerun()
        else:
            st.error("Usuario o contrasena invalidos (o usuario inactivo).")


def require_login():
    """Bloquea la app hasta que haya sesion. Devuelve el dict del usuario."""
    if st.session_state.get("user"):
        return st.session_state["user"]

    st.title("GAPRE - Canal 2")
    if contar_usuarios() == 0:
        _bootstrap_primer_admin()
    else:
        _login_form()
    st.stop()


def boton_logout():
    u = st.session_state.get("user", {})
    with st.sidebar:
        st.markdown(f"**{u.get('nombre') or u.get('username')}**  \n`{u.get('rol')}`")
        if st.button("Cerrar sesion", use_container_width=True):
            st.session_state.pop("user", None)
            st.rerun()


def panel_usuarios():
    """Gestion de usuarios - solo admin."""
    u = st.session_state.get("user", {})
    if u.get("rol") != "admin":
        return
    with st.sidebar.expander("Usuarios (admin)"):
        usuarios = listar_usuarios()

        st.markdown("**Crear usuario**")
        nu = st.text_input("Usuario nuevo", key="cu_user")
        nn = st.text_input("Nombre", key="cu_nombre")
        npw = st.text_input("Contrasena", type="password", key="cu_pass")
        nrol = st.selectbox("Rol", ["operador", "admin"], key="cu_rol")
        if st.button("Crear usuario", key="cu_btn", use_container_width=True):
            if not nu or not npw:
                st.error("Usuario y contrasena obligatorios.")
            else:
                try:
                    crear_usuario(nu, npw, nn, nrol)
                    st.success(f"Usuario {nu} creado.")
                    st.rerun()
                except Exception as e:
                    st.error(f"No se pudo crear: {e}")

        st.divider()
        st.markdown("**Usuarios existentes**")
        for row in usuarios:
            estado = "[on]" if row["activo"] else "[off]"
            st.write(f"{estado} {row['username']} - {row['rol']}")

        st.divider()
        st.markdown("**Administrar usuario**")
        opciones = {r["username"]: r for r in usuarios}
        sel = st.selectbox("Elegir usuario", list(opciones.keys()), key="adm_sel")
        if sel:
            row = opciones[sel]
            es_yo = row["username"] == u["username"]
            nueva = st.text_input("Nueva contrasena", type="password", key="adm_pw")
            if st.button("Cambiar contrasena", key="adm_pw_btn", use_container_width=True):
                if nueva:
                    set_password(row["id"], nueva)
                    st.success("Contrasena actualizada.")
                else:
                    st.error("Ingresa una contrasena.")
            if not es_yo:
                txt = "Desactivar" if row["activo"] else "Activar"
                if st.button(txt, key="adm_tg_btn", use_container_width=True):
                    set_activo(row["id"], not row["activo"])
                    st.rerun()
            else:
                st.caption("No podes desactivar tu propia cuenta.")
