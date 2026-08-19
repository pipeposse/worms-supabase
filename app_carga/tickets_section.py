"""Sección Tickets: pedidos de mejora / soporte de la app.

render(USR, cat, conectar, lab_conn=None)
  cat      -> helper cacheado de app.py (query, params) -> DataFrame (NO se usa para
              la bandeja porque cachea 5 min; los tickets se leen frescos)
  conectar -> context manager de etl.db que da (conn, audit)  [escrituras]
  lab_conn -> context manager del pool de app.py [lecturas]; si falta, se usa conectar

Tablas: produccion.ticket_pedido / ticket_pedido_adjunto (fotos en bytea)
        / ticket_pedido_msg (respuestas del admin, con log de envío por mail)

Privacidad: cualquier usuario crea tickets y ve SOLO los suyos; la bandeja completa
y las respuestas exigen rol ADMIN (chequeado acá, no solo en el landing).

Mail (envío automático): SMTP con SSL. Config en st.secrets["smtp"] o variables de
entorno SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASS / TICKETS_ADMIN_EMAIL.
Para Gmail: SMTP_USER = casilla, SMTP_PASS = App Password (16 letras, se genera en
https://myaccount.google.com/apppasswords con verificación en 2 pasos activa).
Si el SMTP no está configurado o falla, el ticket/respuesta queda registrado igual
(enviado_email=false) y se ofrece un link mailto: como fallback.
"""
import os
import re
import smtplib
import urllib.parse
from contextlib import contextmanager
from email.message import EmailMessage
from email.utils import formataddr

import pandas as pd
import streamlit as st

_ESTADOS = ["ABIERTO", "EN_PROCESO", "RESUELTO", "RECHAZADO"]
_EST_ICONO = {"ABIERTO": "🔴", "EN_PROCESO": "🟡", "RESUELTO": "🟢", "RECHAZADO": "⚫"}
_EST_LABEL = {"ABIERTO": "Abierto", "EN_PROCESO": "En proceso",
              "RESUELTO": "Resuelto", "RECHAZADO": "Rechazado"}
_MAX_ADJUNTOS = 3
_MAX_MB = 4
_RE_EMAIL = re.compile(r"^[\w.+-]+@[\w-]+\.[\w.-]+$")

_PLANTILLAS = {
    "— libre —": "",
    "Resuelto": ("¡Listo! Tu pedido ya está implementado en la app. "
                 "Entrá, probalo y avisame si algo no quedó como esperabas."),
    "En proceso": ("Recibido y en marcha. Lo estoy trabajando; "
                   "te aviso por acá apenas esté disponible."),
    "Necesito más info": ("Para avanzar necesito un poco más de detalle: "
                          "¿en qué pantalla pasa y qué esperabas que hiciera? "
                          "Si podés, sumá una captura."),
    "Rechazado": ("Por ahora no lo vamos a implementar. "
                  "Gracias igual por proponerlo — cualquier duda hablamos."),
}


# ------------------------------------------------------------------ infra ---
def _reader(conectar, lab_conn, uid):
    """Context manager de lectura: pool de app.py si está, si no conexión nueva."""
    if lab_conn is not None:
        return lab_conn()

    @contextmanager
    def _cm():
        with conectar(uid) as (conn, _):
            yield conn
    return _cm()


def _df(conectar, lab_conn, uid, sql, params=None):
    with _reader(conectar, lab_conn, uid) as conn:
        return pd.read_sql(sql, conn, params=params)


def _smtp_cfg():
    cfg = {"host": None, "port": None, "user": None, "password": None, "admin_email": None}
    try:
        if hasattr(st, "secrets") and "smtp" in st.secrets:
            s = st.secrets["smtp"]
            for k in cfg:
                if s.get(k):
                    cfg[k] = str(s.get(k))
    except Exception:
        pass
    env = {"host": "SMTP_HOST", "port": "SMTP_PORT", "user": "SMTP_USER",
           "password": "SMTP_PASS", "admin_email": "TICKETS_ADMIN_EMAIL"}
    for k, v in env.items():
        if not cfg[k] and os.getenv(v):
            cfg[k] = os.getenv(v)
    cfg["host"] = cfg["host"] or "smtp.gmail.com"
    cfg["port"] = int(cfg["port"] or 465)
    cfg["admin_email"] = cfg["admin_email"] or cfg["user"]
    cfg["ok"] = bool(cfg["user"] and cfg["password"])
    return cfg


def _enviar_mail(dest, asunto, cuerpo, adjuntos=None, reply_to=None):
    """adjuntos: lista de (nombre, mime, bytes). Devuelve (ok, error_str)."""
    cfg = _smtp_cfg()
    if not cfg["ok"]:
        return False, "SMTP sin configurar (SMTP_USER / SMTP_PASS)"
    try:
        msg = EmailMessage()
        msg["From"] = formataddr(("Tickets · App WORMS", cfg["user"]))
        msg["To"] = dest
        msg["Subject"] = asunto
        if reply_to:
            msg["Reply-To"] = reply_to
        msg.set_content(cuerpo)
        for nom, mime, data in (adjuntos or []):
            mt, _, sub = (mime or "application/octet-stream").partition("/")
            msg.add_attachment(data, maintype=mt or "application",
                               subtype=sub or "octet-stream", filename=nom or "adjunto")
        with smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=20) as s:
            s.login(cfg["user"], cfg["password"])
            s.send_message(msg)
        return True, None
    except Exception as e:
        return False, str(e)


def _mailto(dest, asunto, cuerpo):
    q = urllib.parse.urlencode({"subject": asunto, "body": cuerpo})
    return f"mailto:{dest}?{q}"


def _chip(estado):
    return f"{_EST_ICONO.get(estado,'⚪')} {_EST_LABEL.get(estado, estado)}"


# ---------------------------------------------------------------- usuario ---
def _form_nuevo(USR, conectar):
    st.markdown("Contá qué necesitás — una mejora, algo que no funciona o un pedido "
                "nuevo. El administrador lo ve al instante y te responde **a tu mail**.")
    with st.form("tk_nuevo", clear_on_submit=True):
        c1, c2 = st.columns([2, 1])
        titulo = c1.text_input("Pedido (resumen corto) *",
                               placeholder='Ej: "Quiero agregar la opción de desgomar AFE-L"')
        email = c2.text_input("Tu mail *", value=st.session_state.get("tk_email_mem", ""),
                              placeholder="nombre@empresa.com")
        descripcion = st.text_area("Detalle (opcional)", height=120,
                                   placeholder="Qué esperás que haga, en qué pantalla, con qué producto…")
        files = st.file_uploader(
            f"Fotos / capturas (opcional, hasta {_MAX_ADJUNTOS} de {_MAX_MB} MB)",
            type=["png", "jpg", "jpeg", "webp"], accept_multiple_files=True)
        enviado = st.form_submit_button("🎫 Enviar ticket", type="primary",
                                        use_container_width=True)
    if not enviado:
        return
    email = (email or "").strip().lower()
    if not (titulo or "").strip():
        st.error("Falta el resumen del pedido."); return
    if not _RE_EMAIL.match(email):
        st.error("Mail inválido — lo necesito para poder responderte."); return
    files = files or []
    if len(files) > _MAX_ADJUNTOS:
        st.error(f"Máximo {_MAX_ADJUNTOS} adjuntos."); return
    for f in files:
        if f.size > _MAX_MB * 1024 * 1024:
            st.error(f"«{f.name}» pesa más de {_MAX_MB} MB."); return
    st.session_state["tk_email_mem"] = email

    adj = [(f.name, f.type or "image/png", f.getvalue()) for f in files]
    with conectar(USR["id_usuario"]) as (conn, _):
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO produccion.ticket_pedido (id_usuario, nombre, email, titulo, descripcion) "
                "VALUES (%s,%s,%s,%s,%s) RETURNING id_ticket, codigo",
                (USR["id_usuario"], USR.get("nombre_full") or USR.get("nombre"),
                 email, titulo.strip(), (descripcion or "").strip() or None))
            id_tk, codigo = cur.fetchone()
            for nom, mime, data in adj:
                cur.execute(
                    "INSERT INTO produccion.ticket_pedido_adjunto (id_ticket, nombre_archivo, mime, datos) "
                    "VALUES (%s,%s,%s,%s)", (id_tk, nom, mime, data))

    # Aviso automático al admin
    cfg = _smtp_cfg()
    if cfg["admin_email"]:
        cuerpo = (f"Nuevo ticket {codigo}\n\n"
                  f"De: {USR.get('nombre_full') or USR.get('nombre')} <{email}>\n"
                  f"Pedido: {titulo.strip()}\n\n"
                  f"{(descripcion or '').strip() or '(sin detalle)'}\n\n"
                  f"Adjuntos: {len(adj)}\n"
                  f"— Entrá a la app → Tickets → Administrar para responderlo.")
        ok, err = _enviar_mail(cfg["admin_email"], f"🎫 [{codigo}] {titulo.strip()}",
                               cuerpo, adjuntos=adj, reply_to=email)
        if ok:
            with conectar(USR["id_usuario"]) as (conn, _):
                with conn.cursor() as cur:
                    cur.execute("UPDATE produccion.ticket_pedido SET notif_admin_ok=true "
                                "WHERE id_ticket=%s", (id_tk,))
    st.success(f"✅ Ticket **{codigo}** creado. Te va a llegar la respuesta a **{email}**.")
    st.balloons()


def _mis_tickets(USR, conectar, lab_conn):
    df = _df(conectar, lab_conn, USR["id_usuario"],
             "SELECT t.id_ticket, t.codigo, t.creado_ts, t.titulo, t.descripcion, t.estado, "
             "       t.email, t.resuelto_ts, "
             "       (SELECT count(*) FROM produccion.ticket_pedido_adjunto a WHERE a.id_ticket=t.id_ticket) adjuntos "
             "FROM produccion.ticket_pedido t WHERE t.id_usuario=%s "
             "ORDER BY t.creado_ts DESC LIMIT 100", (USR["id_usuario"],))
    if df.empty:
        st.info("Todavía no creaste ningún ticket."); return
    abiertos = int((~df["estado"].isin(["RESUELTO", "RECHAZADO"])).sum())
    st.caption(f"**{len(df)}** tickets · **{abiertos}** sin resolver")
    for _, r in df.iterrows():
        with st.expander(f"{_chip(r['estado'])} · **{r['codigo']}** · {r['titulo']} "
                         f"· {pd.to_datetime(r['creado_ts']).strftime('%d/%m %H:%M')}"):
            if r["descripcion"]:
                st.write(r["descripcion"])
            if r["adjuntos"]:
                st.caption(f"📎 {int(r['adjuntos'])} adjunto(s)")
            msgs = _df(conectar, lab_conn, USR["id_usuario"],
                       "SELECT autor, cuerpo, enviado_email, creado_ts "
                       "FROM produccion.ticket_pedido_msg WHERE id_ticket=%s ORDER BY creado_ts",
                       (int(r["id_ticket"]),))
            for _, m in msgs.iterrows():
                quien = "🛠️ Administrador" if m["autor"] == "ADMIN" else "👤 Vos"
                mail_ic = " · 📧 enviado a tu mail" if m["enviado_email"] else ""
                st.markdown(f"> **{quien}** · {pd.to_datetime(m['creado_ts']).strftime('%d/%m %H:%M')}{mail_ic}\n>\n> {m['cuerpo']}")


# ------------------------------------------------------------------ admin ---
def _admin(USR, cat, conectar, lab_conn):
    if USR.get("rol") != "ADMIN":
        st.error("⛔ Solo el administrador puede ver los tickets de todos."); return
    uid = USR["id_usuario"]
    cfg = _smtp_cfg()
    if not cfg["ok"]:
        st.warning("📭 **SMTP sin configurar** — las respuestas se guardan pero no salen "
                   "por mail automático (queda el fallback *mailto*). Definí `SMTP_USER` y "
                   "`SMTP_PASS` (App Password de Gmail) en el entorno o en "
                   "`.streamlit/secrets.toml` → `[smtp]`.")

    df = _df(conectar, lab_conn, uid,
             "SELECT t.*, (SELECT count(*) FROM produccion.ticket_pedido_adjunto a "
             "             WHERE a.id_ticket=t.id_ticket) adjuntos, "
             "       (SELECT count(*) FROM produccion.ticket_pedido_msg m "
             "             WHERE m.id_ticket=t.id_ticket AND m.autor='ADMIN') respuestas "
             "FROM produccion.ticket_pedido t ORDER BY t.creado_ts DESC LIMIT 500")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🔴 Abiertos", int((df["estado"] == "ABIERTO").sum()))
    c2.metric("🟡 En proceso", int((df["estado"] == "EN_PROCESO").sum()))
    c3.metric("🟢 Resueltos", int((df["estado"] == "RESUELTO").sum()))
    c4.metric("⚫ Rechazados", int((df["estado"] == "RECHAZADO").sum()))
    filtro = st.segmented_control("Ver", ["Pendientes", "Todos"] + [_EST_LABEL[e] for e in _ESTADOS],
                                  default="Pendientes", key="tk_adm_filtro")
    dfv = df
    if filtro == "Pendientes":
        dfv = df[df["estado"].isin(["ABIERTO", "EN_PROCESO"])]
    elif filtro in _EST_LABEL.values():
        est = [k for k, v in _EST_LABEL.items() if v == filtro][0]
        dfv = df[df["estado"] == est]
    if dfv.empty:
        st.info("Nada por acá. 🎉"); return

    opts = dfv.apply(lambda r: f"{_chip(r['estado'])} {r['codigo']} · {r['titulo'][:60]} "
                               f"· {r['nombre'] or r['email']}", axis=1).tolist()
    sel = st.selectbox("Ticket", opts, key="tk_adm_sel")
    r = dfv.iloc[opts.index(sel)]
    id_tk = int(r["id_ticket"])

    with st.container(border=True):
        st.markdown(f"### {r['codigo']} — {r['titulo']}")
        st.caption(f"{_chip(r['estado'])} · 👤 **{r['nombre'] or '—'}** · 📧 {r['email']} · "
                   f"🕒 {pd.to_datetime(r['creado_ts']).strftime('%d/%m/%Y %H:%M')}"
                   + (" · ⚠️ aviso por mail NO salió" if not r["notif_admin_ok"] else ""))
        if r["descripcion"]:
            st.write(r["descripcion"])
        if int(r["adjuntos"]):
            adjs = _df(conectar, lab_conn, uid,
                       "SELECT nombre_archivo, mime, datos FROM produccion.ticket_pedido_adjunto "
                       "WHERE id_ticket=%s ORDER BY id_adjunto", (id_tk,))
            cols = st.columns(min(len(adjs), 3))
            for i, (_, a) in enumerate(adjs.iterrows()):
                with cols[i % len(cols)]:
                    try:
                        st.image(bytes(a["datos"]), caption=a["nombre_archivo"],
                                 use_container_width=True)
                    except Exception:
                        st.download_button(f"⬇️ {a['nombre_archivo']}", bytes(a["datos"]),
                                           file_name=a["nombre_archivo"] or "adjunto",
                                           key=f"tk_dl_{id_tk}_{i}")

        msgs = _df(conectar, lab_conn, uid,
                   "SELECT autor, cuerpo, enviado_email, creado_ts "
                   "FROM produccion.ticket_pedido_msg WHERE id_ticket=%s ORDER BY creado_ts", (id_tk,))
        if not msgs.empty:
            st.markdown("**Conversación**")
            for _, m in msgs.iterrows():
                ic = "📧" if m["enviado_email"] else "📝"
                st.markdown(f"> {ic} **{'Admin' if m['autor']=='ADMIN' else 'Usuario'}** · "
                            f"{pd.to_datetime(m['creado_ts']).strftime('%d/%m %H:%M')}\n>\n> {m['cuerpo']}")

    st.markdown("#### ✉️ Responder")
    plant = st.selectbox("Plantilla", list(_PLANTILLAS), key=f"tk_pl_{id_tk}")
    cuerpo = st.text_area("Respuesta", value=_PLANTILLAS[plant], height=110,
                          key=f"tk_resp_{id_tk}_{plant}")
    cc1, cc2, cc3 = st.columns([1.2, 1, 1.2])
    nuevo_estado = cc1.selectbox("Nuevo estado", _ESTADOS,
                                 index=_ESTADOS.index(r["estado"]),
                                 format_func=lambda e: _chip(e), key=f"tk_est_{id_tk}")
    por_mail = cc2.toggle("Enviar por mail", value=True, key=f"tk_mail_{id_tk}",
                          help=f"Sale de {cfg['user'] or '(SMTP sin configurar)'} a {r['email']}")
    if cc3.button("💾 Guardar y responder", type="primary", use_container_width=True,
                  key=f"tk_go_{id_tk}"):
        cuerpo = (cuerpo or "").strip()
        if por_mail and not cuerpo:
            st.error("Escribí la respuesta antes de enviarla."); st.stop()
        ok_mail = False
        if por_mail and cuerpo:
            asunto = f"[{r['codigo']}] {r['titulo']}"
            if nuevo_estado == "RESUELTO":
                asunto = f"✅ Resuelto · {asunto}"
            pie = (f"\n\n—\nTicket {r['codigo']} · estado: {_EST_LABEL[nuevo_estado]}\n"
                   "Respondé este mail o creá otro ticket desde la app.")
            ok_mail, err = _enviar_mail(r["email"], asunto, cuerpo + pie,
                                        reply_to=cfg["admin_email"])
            if not ok_mail:
                st.warning(f"No salió el mail ({err}). La respuesta quedó guardada; "
                           f"[✉️ abrir en tu correo]({_mailto(r['email'], asunto, cuerpo + pie)})")
        with conectar(uid) as (conn, _):
            with conn.cursor() as cur:
                if cuerpo:
                    cur.execute(
                        "INSERT INTO produccion.ticket_pedido_msg (id_ticket, autor, id_usuario, cuerpo, enviado_email) "
                        "VALUES (%s,'ADMIN',%s,%s,%s)", (id_tk, uid, cuerpo, ok_mail))
                cur.execute(
                    "UPDATE produccion.ticket_pedido SET estado=%s, actualizado_ts=now(), "
                    "resuelto_ts = CASE WHEN %s IN ('RESUELTO','RECHAZADO') THEN now() ELSE NULL END "
                    "WHERE id_ticket=%s", (nuevo_estado, nuevo_estado, id_tk))
        st.toast(("📧 Enviado a " + r["email"] + " · " if ok_mail else "Guardado · ")
                 + f"estado → {_chip(nuevo_estado)}", icon="✅")
        st.rerun()


# ------------------------------------------------------------------ main ----
def render(USR, cat, conectar, lab_conn=None):
    st.title("🎫 Tickets")
    es_admin = USR.get("rol") == "ADMIN"
    if es_admin:
        n_abiertos = 0
        try:
            n_abiertos = int(_df(conectar, lab_conn, USR["id_usuario"],
                                 "SELECT count(*) n FROM produccion.ticket_pedido "
                                 "WHERE estado IN ('ABIERTO','EN_PROCESO')").iloc[0]["n"])
        except Exception:
            pass
        t_adm, t_new, t_mios = st.tabs([f"🛠️ Administrar ({n_abiertos})",
                                        "➕ Nuevo pedido", "📋 Mis pedidos"])
        with t_adm:
            _admin(USR, cat, conectar, lab_conn)
    else:
        t_new, t_mios = st.tabs(["➕ Nuevo pedido", "📋 Mis pedidos"])
    with t_new:
        _form_nuevo(USR, conectar)
    with t_mios:
        _mis_tickets(USR, conectar, lab_conn)
