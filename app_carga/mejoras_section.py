"""Sección "Mejoras y resolución de problemas" (soporte de la plataforma).

OJO: no confundir con los tickets de balanza/portería de planta. Acá se piden
cambios en la app: algo que no funciona, algo que falta, una duda de uso.

render(USR, cat, conectar, lab_conn=None)
  cat      -> helper cacheado de app.py (no se usa: la bandeja se lee fresca)
  conectar -> context manager de etl.db que da (conn, audit)  [escrituras]
  lab_conn -> context manager del pool de app.py [lecturas]; si falta, usa conectar

Tablas: produccion.ticket_pedido (codigo SOL-####, tipo, prioridad, estado)
        / ticket_pedido_adjunto (fotos en bytea) / ticket_pedido_msg (respuestas)

Privacidad: cualquier usuario crea solicitudes y ve SOLO las suyas; la bandeja
completa y las respuestas exigen rol ADMIN (chequeado acá, no solo en el landing).

Mail (envío automático): SMTP con SSL. Config en st.secrets["smtp"] o variables de
entorno SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASS / TICKETS_ADMIN_EMAIL.
Para Gmail: SMTP_USER = casilla, SMTP_PASS = App Password (16 letras, se genera en
https://myaccount.google.com/apppasswords con verificación en 2 pasos activa).
Si el SMTP no está configurado o falla, la solicitud/respuesta queda registrada
igual (enviado_email=false) y se ofrece un link mailto: como fallback.
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

TITULO = "🛠️ Mejoras y resolución de problemas"

_ESTADOS = ["ABIERTO", "EN_PROCESO", "RESUELTO", "RECHAZADO"]
_EST_ICONO = {"ABIERTO": "🔴", "EN_PROCESO": "🟡", "RESUELTO": "🟢", "RECHAZADO": "⚫"}
_EST_LABEL = {"ABIERTO": "Abierto", "EN_PROCESO": "En proceso",
              "RESUELTO": "Resuelto", "RECHAZADO": "Rechazado"}

_TIPOS = ["PROBLEMA", "MEJORA", "CONSULTA"]
_TIPO_LABEL = {"PROBLEMA": "🐞 Algo no funciona",
               "MEJORA": "✨ Falta / quiero agregar algo",
               "CONSULTA": "❓ Duda de uso"}
_TIPO_CORTO = {"PROBLEMA": "🐞 Problema", "MEJORA": "✨ Mejora", "CONSULTA": "❓ Consulta"}

_PRIOS = ["BAJA", "MEDIA", "ALTA", "BLOQUEANTE"]
_PRIO_LABEL = {
    "BAJA": "🟢 Baja — estaría bueno, no me frena",
    "MEDIA": "🔵 Media — me hace perder tiempo todos los días",
    "ALTA": "🟠 Alta — me traba tareas del turno",
    "BLOQUEANTE": "🔴 Bloqueante — no puedo trabajar / se pierden datos",
}
_PRIO_CORTO = {"BAJA": "🟢 Baja", "MEDIA": "🔵 Media",
               "ALTA": "🟠 Alta", "BLOQUEANTE": "🔴 Bloqueante"}

_MAX_ADJUNTOS = 3
_MAX_MB = 4
_RE_EMAIL = re.compile(r"^[\w.+-]+@[\w-]+\.[\w.-]+$")

_SQL_PRIO_RANK = ("CASE coalesce(t.prioridad_admin, t.prioridad) "
                  "WHEN 'BLOQUEANTE' THEN 0 WHEN 'ALTA' THEN 1 "
                  "WHEN 'MEDIA' THEN 2 ELSE 3 END")

_PLANTILLAS = {
    "— libre —": "",
    "Resuelto": ("¡Listo! Ya está implementado en la app. "
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
        msg["From"] = formataddr(("Soporte App WORMS", cfg["user"]))
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


def _prio_efectiva(r):
    return r.get("prioridad_admin") or r.get("prioridad") or "MEDIA"


# ---------------------------------------------------------------- usuario ---
def _form_nuevo(USR, conectar):
    st.markdown("Contá qué necesitás **de la plataforma**: algo que no anda, algo que "
                "falta o una duda de uso. Lo veo al instante y te respondo **a tu mail**.")
    st.caption("⚠️ Esto no es para tickets de balanza/portería — es soporte de la app.")
    with st.form("mj_nuevo", clear_on_submit=True):
        c1, c2 = st.columns([2, 1])
        titulo = c1.text_input("¿Qué necesitás? (resumen corto) *",
                               placeholder='Ej: "Quiero agregar la opción de desgomar AFE-L"')
        email = c2.text_input("Tu mail *", value=st.session_state.get("mj_email_mem", ""),
                              placeholder="nombre@empresa.com")
        c3, c4 = st.columns(2)
        tipo = c3.selectbox("Tipo *", _TIPOS, index=1,
                            format_func=lambda t: _TIPO_LABEL[t])
        prioridad = c4.selectbox("¿Qué tan importante es? *", _PRIOS, index=1,
                                 format_func=lambda p: _PRIO_LABEL[p])
        descripcion = st.text_area("Detalle (opcional)", height=120,
                                   placeholder="Qué esperás que haga, en qué pantalla, con qué producto…")
        files = st.file_uploader(
            f"Fotos / capturas (opcional, hasta {_MAX_ADJUNTOS} de {_MAX_MB} MB)",
            type=["png", "jpg", "jpeg", "webp"], accept_multiple_files=True)
        enviado = st.form_submit_button("📨 Enviar solicitud", type="primary",
                                        use_container_width=True)
    if not enviado:
        return
    email = (email or "").strip().lower()
    if not (titulo or "").strip():
        st.error("Falta el resumen de lo que necesitás."); return
    if not _RE_EMAIL.match(email):
        st.error("Mail inválido — lo necesito para poder responderte."); return
    files = files or []
    if len(files) > _MAX_ADJUNTOS:
        st.error(f"Máximo {_MAX_ADJUNTOS} adjuntos."); return
    for f in files:
        if f.size > _MAX_MB * 1024 * 1024:
            st.error(f"«{f.name}» pesa más de {_MAX_MB} MB."); return
    st.session_state["mj_email_mem"] = email

    adj = [(f.name, f.type or "image/png", f.getvalue()) for f in files]
    with conectar(USR["id_usuario"]) as (conn, _):
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO produccion.ticket_pedido "
                "(id_usuario, nombre, email, titulo, descripcion, tipo, prioridad) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id_ticket, codigo",
                (USR["id_usuario"], USR.get("nombre_full") or USR.get("nombre"),
                 email, titulo.strip(), (descripcion or "").strip() or None,
                 tipo, prioridad))
            id_tk, codigo = cur.fetchone()
            for nom, mime, data in adj:
                cur.execute(
                    "INSERT INTO produccion.ticket_pedido_adjunto (id_ticket, nombre_archivo, mime, datos) "
                    "VALUES (%s,%s,%s,%s)", (id_tk, nom, mime, data))

    # Aviso automático al admin
    cfg = _smtp_cfg()
    if cfg["admin_email"]:
        cuerpo = (f"Nueva solicitud {codigo}\n\n"
                  f"De: {USR.get('nombre_full') or USR.get('nombre')} <{email}>\n"
                  f"Tipo: {_TIPO_CORTO[tipo]}   ·   Importancia: {_PRIO_CORTO[prioridad]}\n"
                  f"Pedido: {titulo.strip()}\n\n"
                  f"{(descripcion or '').strip() or '(sin detalle)'}\n\n"
                  f"Adjuntos: {len(adj)}\n"
                  f"— Entrá a la app → Mejoras y resolución de problemas → Administrar.")
        prefijo = "🔴 " if prioridad == "BLOQUEANTE" else ("🟠 " if prioridad == "ALTA" else "")
        ok, err = _enviar_mail(cfg["admin_email"],
                               f"{prefijo}[{codigo}] {titulo.strip()}",
                               cuerpo, adjuntos=adj, reply_to=email)
        if ok:
            with conectar(USR["id_usuario"]) as (conn, _):
                with conn.cursor() as cur:
                    cur.execute("UPDATE produccion.ticket_pedido SET notif_admin_ok=true "
                                "WHERE id_ticket=%s", (id_tk,))
    st.success(f"✅ Solicitud **{codigo}** enviada. Te llega la respuesta a **{email}**.")
    st.balloons()


def _mis_pedidos(USR, conectar, lab_conn):
    df = _df(conectar, lab_conn, USR["id_usuario"],
             "SELECT t.id_ticket, t.codigo, t.creado_ts, t.titulo, t.descripcion, t.estado, "
             "       t.tipo, t.prioridad, t.prioridad_admin, t.email, t.resuelto_ts, "
             "       (SELECT count(*) FROM produccion.ticket_pedido_adjunto a WHERE a.id_ticket=t.id_ticket) adjuntos "
             "FROM produccion.ticket_pedido t WHERE t.id_usuario=%s "
             f"ORDER BY (t.estado IN ('RESUELTO','RECHAZADO')), {_SQL_PRIO_RANK}, t.creado_ts DESC "
             "LIMIT 100", (USR["id_usuario"],))
    if df.empty:
        st.info("Todavía no enviaste ninguna solicitud."); return
    abiertos = int((~df["estado"].isin(["RESUELTO", "RECHAZADO"])).sum())
    st.caption(f"**{len(df)}** solicitudes · **{abiertos}** sin resolver")
    for _, r in df.iterrows():
        with st.expander(f"{_chip(r['estado'])} · **{r['codigo']}** · {r['titulo']} · "
                         f"{_PRIO_CORTO.get(_prio_efectiva(r),'')} · "
                         f"{pd.to_datetime(r['creado_ts']).strftime('%d/%m %H:%M')}"):
            st.caption(f"{_TIPO_CORTO.get(r['tipo'], r['tipo'])} · importancia "
                       f"{_PRIO_CORTO.get(_prio_efectiva(r), '')}")
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
        st.error("⛔ Solo el administrador puede ver las solicitudes de todos."); return
    uid = USR["id_usuario"]
    cfg = _smtp_cfg()
    if not cfg["ok"]:
        st.warning("📭 **SMTP sin configurar** — las respuestas se guardan pero no salen "
                   "por mail automático (queda el fallback *mailto*). Definí `SMTP_USER` y "
                   "`SMTP_PASS` (App Password de Gmail) en el entorno o en "
                   "`.streamlit/secrets.toml` → `[smtp]`.")

    df = _df(conectar, lab_conn, uid,
             "SELECT t.*, coalesce(t.prioridad_admin, t.prioridad) prio_efectiva, "
             "       (SELECT count(*) FROM produccion.ticket_pedido_adjunto a "
             "             WHERE a.id_ticket=t.id_ticket) adjuntos, "
             "       (SELECT count(*) FROM produccion.ticket_pedido_msg m "
             "             WHERE m.id_ticket=t.id_ticket AND m.autor='ADMIN') respuestas "
             "FROM produccion.ticket_pedido t "
             f"ORDER BY (t.estado IN ('RESUELTO','RECHAZADO')), {_SQL_PRIO_RANK}, t.creado_ts DESC "
             "LIMIT 500")
    if df.empty:
        st.info("No hay solicitudes todavía."); return

    pend = df[df["estado"].isin(["ABIERTO", "EN_PROCESO"])]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🔴 Bloqueantes", int((pend["prio_efectiva"] == "BLOQUEANTE").sum()),
              help="Pendientes que impiden trabajar")
    c2.metric("🟠 Altas", int((pend["prio_efectiva"] == "ALTA").sum()))
    c3.metric("📥 Pendientes", len(pend))
    c4.metric("🟢 Resueltas", int((df["estado"] == "RESUELTO").sum()))

    f1, f2 = st.columns([2, 1])
    filtro = f1.segmented_control("Ver", ["Pendientes", "Todas"] + [_EST_LABEL[e] for e in _ESTADOS],
                                  default="Pendientes", key="mj_adm_filtro")
    f_prio = f2.multiselect("Importancia", _PRIOS, format_func=lambda p: _PRIO_CORTO[p],
                            key="mj_adm_prio")
    dfv = df
    if filtro == "Pendientes":
        dfv = df[df["estado"].isin(["ABIERTO", "EN_PROCESO"])]
    elif filtro in _EST_LABEL.values():
        est = [k for k, v in _EST_LABEL.items() if v == filtro][0]
        dfv = df[df["estado"] == est]
    if f_prio:
        dfv = dfv[dfv["prio_efectiva"].isin(f_prio)]
    if dfv.empty:
        st.info("Nada por acá. 🎉"); return

    opts = dfv.apply(lambda r: f"{_PRIO_CORTO.get(r['prio_efectiva'],'')} {_chip(r['estado'])} "
                               f"{r['codigo']} · {r['titulo'][:55]} · {r['nombre'] or r['email']}",
                     axis=1).tolist()
    sel = st.selectbox("Solicitud", opts, key="mj_adm_sel")
    r = dfv.iloc[opts.index(sel)]
    id_tk = int(r["id_ticket"])

    with st.container(border=True):
        st.markdown(f"### {r['codigo']} — {r['titulo']}")
        st.caption(f"{_chip(r['estado'])} · {_TIPO_CORTO.get(r['tipo'], r['tipo'])} · "
                   f"importancia {_PRIO_CORTO.get(r['prio_efectiva'],'')}"
                   + (f" *(el usuario puso {_PRIO_CORTO.get(r['prioridad'],'')})*"
                      if r["prioridad_admin"] and r["prioridad_admin"] != r["prioridad"] else "")
                   + f" · 👤 **{r['nombre'] or '—'}** · 📧 {r['email']} · "
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
                                           key=f"mj_dl_{id_tk}_{i}")

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
    plant = st.selectbox("Plantilla", list(_PLANTILLAS), key=f"mj_pl_{id_tk}")
    cuerpo = st.text_area("Respuesta", value=_PLANTILLAS[plant], height=110,
                          key=f"mj_resp_{id_tk}_{plant}")
    cc1, cc2, cc3, cc4 = st.columns([1.1, 1.1, .8, 1.2])
    nuevo_estado = cc1.selectbox("Estado", _ESTADOS, index=_ESTADOS.index(r["estado"]),
                                 format_func=lambda e: _chip(e), key=f"mj_est_{id_tk}")
    nueva_prio = cc2.selectbox("Importancia (mi criterio)", _PRIOS,
                               index=_PRIOS.index(r["prio_efectiva"]),
                               format_func=lambda p: _PRIO_CORTO[p], key=f"mj_prio_{id_tk}")
    por_mail = cc3.toggle("Mail", value=True, key=f"mj_mail_{id_tk}",
                          help=f"Sale de {cfg['user'] or '(SMTP sin configurar)'} a {r['email']}")
    if cc4.button("💾 Guardar y responder", type="primary", use_container_width=True,
                  key=f"mj_go_{id_tk}"):
        cuerpo = (cuerpo or "").strip()
        if por_mail and not cuerpo:
            st.error("Escribí la respuesta antes de enviarla."); st.stop()
        ok_mail = False
        if por_mail and cuerpo:
            asunto = f"[{r['codigo']}] {r['titulo']}"
            if nuevo_estado == "RESUELTO":
                asunto = f"✅ Resuelto · {asunto}"
            pie = (f"\n\n—\nSolicitud {r['codigo']} · estado: {_EST_LABEL[nuevo_estado]}\n"
                   "Respondé este mail o creá otra solicitud desde la app.")
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
                    "UPDATE produccion.ticket_pedido SET estado=%s, prioridad_admin=%s, "
                    "actualizado_ts=now(), "
                    "resuelto_ts = CASE WHEN %s IN ('RESUELTO','RECHAZADO') THEN now() ELSE NULL END "
                    "WHERE id_ticket=%s", (nuevo_estado, nueva_prio, nuevo_estado, id_tk))
        st.toast(("📧 Enviado a " + r["email"] + " · " if ok_mail else "Guardado · ")
                 + f"estado → {_chip(nuevo_estado)}", icon="✅")
        st.rerun()


# ------------------------------------------------------------------ main ----
def render(USR, cat, conectar, lab_conn=None):
    st.title(TITULO)
    st.caption("Soporte de la plataforma — no confundir con los tickets de balanza/portería.")
    es_admin = USR.get("rol") == "ADMIN"
    if es_admin:
        n_pend, n_bloq = 0, 0
        try:
            _k = _df(conectar, lab_conn, USR["id_usuario"],
                     "SELECT count(*) n, count(*) FILTER (WHERE coalesce(prioridad_admin,prioridad)"
                     "='BLOQUEANTE') bloq FROM produccion.ticket_pedido "
                     "WHERE estado IN ('ABIERTO','EN_PROCESO')").iloc[0]
            n_pend, n_bloq = int(_k["n"]), int(_k["bloq"])
        except Exception:
            pass
        lbl = f"🛠️ Administrar ({n_pend})" + (f" 🔴{n_bloq}" if n_bloq else "")
        t_adm, t_new, t_mios = st.tabs([lbl, "➕ Nueva solicitud", "📋 Mis solicitudes"])
        with t_adm:
            _admin(USR, cat, conectar, lab_conn)
    else:
        t_new, t_mios = st.tabs(["➕ Nueva solicitud", "📋 Mis solicitudes"])
    with t_new:
        _form_nuevo(USR, conectar)
    with t_mios:
        _mis_pedidos(USR, conectar, lab_conn)
