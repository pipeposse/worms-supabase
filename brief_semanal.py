# -*- coding: utf-8 -*-
"""Generador headless del Brief semanal de Dirección.

Corre sin Streamlit: arma el mismo HTML que la pestaña de la app (mismo módulo
`brief_dir`, mismas vistas `produccion.v_brief_*`), lo imprime a PDF con el
Chrome que ya está instalado y —si hay SMTP configurado— lo manda por mail.

    python brief_semanal.py                # semana cerrada, guarda en ./briefs
    python brief_semanal.py --semana 2026-08-03
    python brief_semanal.py --salida "D:/informes"
    python brief_semanal.py --sin-pdf      # sólo HTML

Variables de entorno (todas opcionales salvo DATABASE_URL, que ya usa la app):
    DATABASE_URL     conexión a Supabase (se lee del .env del proyecto)
    BRIEF_DIR        carpeta de salida por defecto
    BRIEF_MAIL_TO    destinatarios separados por coma; si falta, no manda mail
    BRIEF_MAIL_FROM  remitente
    SMTP_HOST        p.ej. smtp.gmail.com
    SMTP_PORT        587
    SMTP_USER / SMTP_PASS   credenciales (en Gmail, contraseña de aplicación)

Pensado para una tarea programada de Windows los lunes a la mañana.
"""
import argparse
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ / "app_carga"))


def _env_desde_dotenv():
    f = RAIZ / ".env"
    if not f.exists():
        return
    for linea in f.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        k, v = linea.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _cat_factory(conn):
    """Emula el helper `cat(sql, params)` de la app: devuelve un DataFrame."""
    import pandas as pd

    def cat(sql, params=None):
        return pd.read_sql(sql, conn, params=params)
    return cat


def _chrome():
    """Primer Chrome/Edge/Chromium que exista en esta máquina."""
    candidatos = [
        os.environ.get("CHROME_PATH"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        "/usr/bin/google-chrome", "/usr/bin/chromium", "/opt/pw-browsers/chromium",
    ]
    for c in candidatos:
        if c and Path(c).exists():
            return c
    return None


def a_pdf(html_path, pdf_path):
    exe = _chrome()
    if not exe:
        print("· sin Chrome/Edge a mano: queda sólo el HTML "
              "(abrilo y usá Imprimir → Guardar como PDF)")
        return False
    cmd = [exe, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
           f"--print-to-pdf={pdf_path}", Path(html_path).resolve().as_uri()]
    r = subprocess.run(cmd, capture_output=True, timeout=180)
    if r.returncode != 0 or not Path(pdf_path).exists():
        print("· Chrome no pudo imprimir el PDF:", r.stderr.decode(errors="ignore")[:300])
        return False
    return True


def mandar_mail(asunto, cuerpo, adjuntos):
    to = os.environ.get("BRIEF_MAIL_TO", "").strip()
    host = os.environ.get("SMTP_HOST", "").strip()
    if not to or not host:
        print("· sin BRIEF_MAIL_TO/SMTP_HOST: no mando mail")
        return False
    import smtplib
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["Subject"] = asunto
    msg["From"] = os.environ.get("BRIEF_MAIL_FROM") or os.environ.get("SMTP_USER", "")
    msg["To"] = to
    msg.set_content(cuerpo)
    for a in adjuntos:
        p = Path(a)
        if not p.exists():
            continue
        tipo = "pdf" if p.suffix == ".pdf" else "html"
        msg.add_attachment(p.read_bytes(), maintype="application",
                           subtype=tipo, filename=p.name)
    with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", 587)), timeout=60) as s:
        s.starttls()
        u, w = os.environ.get("SMTP_USER"), os.environ.get("SMTP_PASS")
        if u and w:
            s.login(u, w)
        s.send_message(msg)
    print("· mail enviado a", to)
    return True


def main():
    _env_desde_dotenv()
    ap = argparse.ArgumentParser(description="Brief semanal de Dirección · WORMS")
    ap.add_argument("--semana", help="lunes ISO YYYY-MM-DD; por defecto, la última semana cerrada")
    ap.add_argument("--salida", default=os.environ.get("BRIEF_DIR") or str(RAIZ / "briefs"))
    ap.add_argument("--sin-pdf", action="store_true")
    ap.add_argument("--sin-mail", action="store_true")
    args = ap.parse_args()

    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("Falta DATABASE_URL (revisá el .env del proyecto).")

    import psycopg2
    from brief_dir import construir
    from brief_dir.datos import semana_cerrada

    sem = args.semana or semana_cerrada().isoformat()
    out = Path(args.salida)
    out.mkdir(parents=True, exist_ok=True)

    conn = psycopg2.connect(url)
    try:
        html, D = construir(_cat_factory(conn), sem)
    finally:
        conn.close()

    nombre = f"brief_worms_{D['semana_iso']}"
    fh = out / f"{nombre}.html"
    fh.write_text(html, encoding="utf-8")
    print("·", fh)

    adjuntos = [fh]
    if not args.sin_pdf:
        fp = out / f"{nombre}.pdf"
        if a_pdf(fh, fp):
            print("·", fp)
            adjuntos = [fp, fh]

    if not args.sin_mail:
        ini, fin = D["semana_ini"], D["semana_fin"]
        mandar_mail(
            f"WORMS · Brief de Dirección · semana {D['semana_iso']}",
            f"Brief de la semana {D['semana_iso']} ({ini} al {fin}).\n"
            f"Generado automáticamente el {date.today().isoformat()}.\n\n"
            "Adjunto el PDF de 5 páginas. El mismo informe está en la app, "
            "en Dirección → Brief semanal.\n",
            adjuntos)


if __name__ == "__main__":
    main()
