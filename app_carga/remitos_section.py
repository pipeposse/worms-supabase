"""Remitos — digitalización por foto con IA + match contra tickets de balanza.

Carga por lote: la operaria arrastra una o muchas fotos (carpeta entera). Cada foto
se lee con IA (Claude si hay ANTHROPIC_API_KEY, si no Gemini), se detectan duplicados
por N° único de remito (contra la base Y dentro del mismo lote), se matchea el ticket
de balanza y se sube todo con un botón. Al final queda un informe de lo subido.
La foto NO se almacena: solo los datos.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
from datetime import date, datetime

import pandas as pd
import psycopg2
import requests
import streamlit as st

from etl.config import DATABASE_URL

# ------------------------------------------------------------------ extracción

_PROMPT = """Sos un digitalizador de remitos de una planta industrial argentina.
Extraé los datos del remito de la foto y devolvé SOLO un JSON válido (sin markdown) con estas claves:

{
  "emisor": "razón social de quien EMITE el remito (el proveedor, no Worms)",
  "emisor_cuit": "CUIT del emisor con guiones o null",
  "nro_remito": "IDENTIFICADOR ÚNICO del remito: punto de venta + '-' + número, ej '00004-00016352'. Buscalo arriba junto a 'REMITO N°'. Transcribí TODOS los dígitos de ambas partes, es el dato más importante del documento.",
  "fecha_remito": "fecha del remito en formato YYYY-MM-DD o null",
  "producto": "producto trasladado o null",
  "bruto_kg": número o null,
  "tara_kg": número o null,
  "neto_kg": número o null (si la cantidad está en TN convertí a kg),
  "lugar_entrega": "lugar de entrega/domicilio destino o null",
  "transportista": "razón social del transportista o null",
  "patente_chasis": "patente del chasis/camión sin espacios o null",
  "patente_acoplado": "patente del acoplado/trailer sin espacios o null",
  "chofer": "apellido y nombre del chofer o null",
  "chofer_dni": "DNI del chofer solo dígitos o null",
  "ticket": "número de ticket si el remito lo menciona (ej 'Ticket: 4962') o null",
  "observaciones": "observaciones/precintos/análisis relevantes o null",
  "campos_dudosos": ["lista de claves cuya lectura no es 100% segura"]
}

Reglas:
- El destinatario suele ser WORMS ARGENTINA S.A. (CUIT 30-71201396-2): NO es el emisor.
- Números argentinos: el punto puede ser separador de miles. 28.040 kg = 28040.
- Si un dato no está en el remito usá null. No inventes.
- Si el N° de remito no se lee con total certeza, incluí "nro_remito" en campos_dudosos.
- Patentes formato AAA999 o AA999AA."""

_ANTH_URL = "https://api.anthropic.com/v1/messages"
_GEM_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"


def _api_keys():
    anth = os.getenv("ANTHROPIC_API_KEY")
    gem = os.getenv("GEMINI_API_KEY")
    if not gem:
        try:
            from chat import config_chat as _cfg
            gem = _cfg.GEMINI_API_KEY
        except Exception:
            pass
    return anth, gem


def _preparar_imagen(raw: bytes) -> tuple[bytes, str]:
    """Reduce la foto (celular ~3MB) a JPEG <=1600px para abaratar/acelerar la extracción."""
    try:
        from PIL import Image, ImageOps
        img = Image.open(io.BytesIO(raw))
        img = ImageOps.exif_transpose(img)
        img.thumbnail((1600, 1600))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=85)
        return buf.getvalue(), "image/jpeg"
    except Exception:
        return raw, "image/jpeg"


def _parse_json(texto: str) -> dict:
    m = re.search(r"\{.*\}", texto, re.DOTALL)
    if not m:
        raise ValueError(f"La IA no devolvió JSON: {texto[:200]}")
    return json.loads(m.group(0))


def _extraer_claude(b64: str, mime: str, key: str) -> dict:
    modelo = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")
    r = requests.post(
        _ANTH_URL,
        headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={"model": modelo, "max_tokens": 1500,
              "messages": [{"role": "user", "content": [
                  {"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}},
                  {"type": "text", "text": _PROMPT}]}]},
        timeout=90)
    r.raise_for_status()
    return _parse_json(r.json()["content"][0]["text"])


def _extraer_gemini(b64: str, mime: str, key: str) -> dict:
    modelo = os.getenv("GEMINI_VISION_MODEL", "gemini-2.5-flash")
    r = requests.post(
        _GEM_URL.format(model=modelo, key=key),
        json={"contents": [{"parts": [
                  {"inline_data": {"mime_type": mime, "data": b64}},
                  {"text": _PROMPT}]}],
              "generationConfig": {"response_mime_type": "application/json",
                                   "temperature": 0}},
        timeout=90)
    r.raise_for_status()
    return _parse_json(r.json()["candidates"][0]["content"]["parts"][0]["text"])


def extraer_remito(raw: bytes) -> dict:
    img, mime = _preparar_imagen(raw)
    b64 = base64.b64encode(img).decode()
    anth, gem = _api_keys()
    if anth:
        try:
            return _extraer_claude(b64, mime, anth)
        except Exception:
            if not gem:
                raise
    if gem:
        return _extraer_gemini(b64, mime, gem)
    raise RuntimeError("No hay ANTHROPIC_API_KEY ni GEMINI_API_KEY configuradas.")


# ------------------------------------------------------------------ datos

def _norm_remito(nro: str | None) -> str | None:
    """'00004-00016352' -> '4-16352' (igual que produccion.fn_norm_remito)."""
    if not nro:
        return None
    partes = re.sub(r"[^0-9-]", "", str(nro)).split("-")
    partes = [p for p in partes if p != ""]
    if not partes:
        return None
    return "-".join((p.lstrip("0") or "0") for p in partes)


def _read_df(sql: str, params=None) -> pd.DataFrame:
    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("SET search_path TO produccion, public")
        return pd.read_sql(sql, conn, params=params)


def _remito_en_base(norm: str | None) -> dict | None:
    """Si el remito ya existe devuelve info del registro existente."""
    if not norm:
        return None
    df = _read_df(
        "SELECT id, emisor, nro_remito, creado_en::date AS fecha_carga, cargado_por "
        "FROM produccion.fact_remito WHERE nro_remito_norm=%s AND estado<>'ANULADO' "
        "ORDER BY id LIMIT 1", (norm,))
    return None if df.empty else df.iloc[0].to_dict()


def _buscar_tickets(datos: dict) -> pd.DataFrame:
    """Candidatos de balanza: 1° por nro de remito, 2° por patente ±30 días."""
    norm = _norm_remito(datos.get("nro_remito"))
    base = ("SELECT transaccion, fecha_e, comprnum1, comprnum2, producto, procedencia, "
            "patcha, patacopl, abs(pesoneto) AS neto_balanza "
            "FROM produccion.transacciones WHERE comprobtip='REM' ")
    if norm:
        df = _read_df(base + "AND (produccion.fn_norm_remito(comprnum2)=%s "
                             "OR produccion.fn_norm_remito(comprnum1)=%s) "
                             "ORDER BY transaccion DESC LIMIT 5", (norm, norm))
        if not df.empty:
            df["match"] = "N° remito"
            return df
    pats = [p for p in (datos.get("patente_chasis"), datos.get("patente_acoplado")) if p]
    if pats:
        df = _read_df(base + "AND (upper(replace(patcha,' ',''))=ANY(%s) "
                             "OR upper(replace(patacopl,' ',''))=ANY(%s)) "
                             "AND to_date(nullif(fecha_e,''),'DD/MM/YYYY') "
                             "BETWEEN current_date-30 AND current_date "
                             "ORDER BY transaccion DESC LIMIT 5",
                      ([p.upper().replace(" ", "") for p in pats],) * 2)
        if not df.empty:
            df["match"] = "Patente"
            return df
    return pd.DataFrame()


_CRITICOS = {"nro_remito", "neto_kg", "emisor"}


def _clasificar(item: dict, norms_lote: dict) -> None:
    """Asigna item['estado'] y item['motivo'] según dedup/completitud/match."""
    d = item.get("datos") or {}
    norm = _norm_remito(d.get("nro_remito"))
    item["norm"] = norm
    if item.get("error"):
        item["estado"], item["motivo"] = "ERROR", item["error"]
        return
    if item.get("guardado"):
        item["estado"], item["motivo"] = "SUBIDO", f"id {item['guardado']}"
        return
    dup = _remito_en_base(norm)
    if dup:
        item["estado"] = "DUPLICADO"
        item["motivo"] = (f"Ya cargado el {dup['fecha_carga']} por {dup['cargado_por']} "
                          f"(id {dup['id']}, {dup['emisor']})")
        return
    if norm and norm in norms_lote:
        item["estado"] = "DUPLICADO"
        item["motivo"] = f"Repetido en este lote (misma foto que «{norms_lote[norm]}»)"
        return
    if norm:
        norms_lote[norm] = item["name"]
    dudosos = set(d.get("campos_dudosos") or []) & _CRITICOS
    if not d.get("nro_remito") or not d.get("emisor") or not d.get("neto_kg"):
        item["estado"], item["motivo"] = "REVISAR", "Faltan datos obligatorios (emisor / N° / neto)"
        return
    if dudosos:
        item["estado"], item["motivo"] = "REVISAR", "Lectura dudosa de: " + ", ".join(sorted(dudosos))
        return
    if item.get("ticket_sel"):
        item["estado"], item["motivo"] = "LISTO", f"Ticket #{item['ticket_sel']}"
    else:
        item["estado"], item["motivo"] = "SIN_TICKET", "No hay ticket de balanza que coincida"


_BADGE = {"LISTO": "✅ Listo", "SIN_TICKET": "🎫 Sin ticket", "REVISAR": "⚠️ Revisar",
          "DUPLICADO": "🔁 Duplicado", "ERROR": "❌ Error", "SUBIDO": "☁️ Subido"}


def _f(v):
    return None if v in ("", "null", None, 0, 0.0) or (isinstance(v, float) and v == 0) else v


def _insert_remito(cur, usr, datos: dict, ticket, diferencia) -> int:
    cur.execute(
        """INSERT INTO produccion.fact_remito
           (emisor, emisor_cuit, nro_remito, fecha_remito, producto,
            bruto_kg, tara_kg, neto_kg, lugar_entrega, transportista,
            patente_chasis, patente_acoplado, chofer, chofer_dni,
            observaciones, ticket_balanza, diferencia_kg, estado,
            raw_json, cargado_por)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           RETURNING id""",
        (datos.get("emisor"), _f(datos.get("emisor_cuit")), datos.get("nro_remito"),
         datos.get("fecha_remito"), _f(datos.get("producto")),
         _f(datos.get("bruto_kg")), _f(datos.get("tara_kg")), datos.get("neto_kg"),
         _f(datos.get("lugar_entrega")), _f(datos.get("transportista")),
         _f(datos.get("patente_chasis")), _f(datos.get("patente_acoplado")),
         _f(datos.get("chofer")), _f(datos.get("chofer_dni")), _f(datos.get("observaciones")),
         ticket, diferencia,
         "CONFIRMADO" if ticket else "SIN_TICKET",
         json.dumps(datos, ensure_ascii=False, default=str),
         usr.get("nombre")))
    return cur.fetchone()[0]


def _fila_informe(it, d, resultado, detalle):
    return {"foto": it["name"], "nro_remito": d.get("nro_remito"),
            "fecha": d.get("fecha_remito"), "emisor": d.get("emisor"),
            "producto": d.get("producto"), "neto_kg": d.get("neto_kg"),
            "ticket_balanza": it.get("ticket_sel"), "dif_kg": it.get("dif_kg"),
            "resultado": resultado, "detalle": detalle}


def _subir_lote(conectar, usr, items):
    """Inserta cada item con savepoint (un duplicado no tumba el resto). Devuelve informe."""
    informe = []
    with conectar(usr["id_usuario"]) as (conn, _aud):
        with conn.cursor() as cur:
            for it in items:
                d = {k: v for k, v in (it["datos"] or {}).items() if k != "campos_dudosos"}
                cur.execute("SAVEPOINT sp_rem")
                try:
                    rid = _insert_remito(cur, usr, d, it.get("ticket_sel"), it.get("dif_kg"))
                    cur.execute("RELEASE SAVEPOINT sp_rem")
                    it["guardado"] = rid
                    informe.append(_fila_informe(it, d, "SUBIDO", f"id {rid}"))
                except psycopg2.errors.UniqueViolation:
                    cur.execute("ROLLBACK TO SAVEPOINT sp_rem")
                    it["estado"], it["motivo"] = "DUPLICADO", "Ya existía en la base"
                    informe.append(_fila_informe(it, d, "OMITIDO_DUPLICADO",
                                                 "El N° de remito ya estaba cargado"))
                except Exception as e:
                    cur.execute("ROLLBACK TO SAVEPOINT sp_rem")
                    informe.append(_fila_informe(it, d, "ERROR", str(e)[:200]))
    return informe


# ------------------------------------------------------------------ UI

def _card_revision(item: dict, h: str):
    """Formulario editable de un remito. Los widgets actualizan item['datos'] en vivo."""
    datos = item["datos"]
    cimg, cform = st.columns([1, 2])
    with cimg:
        st.image(item["raw"], use_container_width=True)
        dud = datos.get("campos_dudosos") or []
        if dud:
            st.warning("Lectura dudosa: " + ", ".join(dud))
    with cform:
        c1, c2, c3 = st.columns(3)
        datos["emisor"] = c1.text_input("Emisor *", datos.get("emisor") or "", key=f"em_{h}")
        datos["nro_remito"] = c2.text_input("N° remito (ID único) *", datos.get("nro_remito") or "", key=f"nr_{h}")
        _fch = datos.get("fecha_remito")
        try:
            _fch = datetime.strptime(str(_fch), "%Y-%m-%d").date() if _fch else date.today()
        except Exception:
            _fch = date.today()
        datos["fecha_remito"] = c3.date_input("Fecha", _fch, key=f"fe_{h}", format="DD/MM/YYYY")

        c4, c5, c6 = st.columns(3)
        datos["bruto_kg"] = c4.number_input("Bruto (kg)", value=float(datos.get("bruto_kg") or 0), step=10.0, key=f"br_{h}")
        datos["tara_kg"] = c5.number_input("Tara (kg)", value=float(datos.get("tara_kg") or 0), step=10.0, key=f"ta_{h}")
        datos["neto_kg"] = c6.number_input("Neto (kg) *", value=float(datos.get("neto_kg") or 0), step=10.0, key=f"ne_{h}")

        c7, c8 = st.columns(2)
        datos["producto"] = c7.text_input("Producto", datos.get("producto") or "", key=f"pr_{h}")
        datos["emisor_cuit"] = c8.text_input("CUIT emisor", datos.get("emisor_cuit") or "", key=f"cu_{h}")

        with st.expander("Transporte y otros datos"):
            d1, d2, d3 = st.columns(3)
            datos["transportista"] = d1.text_input("Transportista", datos.get("transportista") or "", key=f"tr_{h}")
            datos["patente_chasis"] = d2.text_input("Patente chasis", datos.get("patente_chasis") or "", key=f"pc_{h}")
            datos["patente_acoplado"] = d3.text_input("Patente acoplado", datos.get("patente_acoplado") or "", key=f"pa_{h}")
            d4, d5, d6 = st.columns(3)
            datos["chofer"] = d4.text_input("Chofer", datos.get("chofer") or "", key=f"ch_{h}")
            datos["chofer_dni"] = d5.text_input("DNI chofer", datos.get("chofer_dni") or "", key=f"dn_{h}")
            datos["lugar_entrega"] = d6.text_input("Lugar entrega", datos.get("lugar_entrega") or "", key=f"lu_{h}")
            datos["observaciones"] = st.text_input("Observaciones", datos.get("observaciones") or "", key=f"ob_{h}")
            datos["ticket"] = st.text_input("Ticket del proveedor (impreso en el remito)",
                                            str(datos.get("ticket") or ""), key=f"tp_{h}")

        # ---- ticket de balanza ----
        cand = item.get("cand")
        if cand is None:
            try:
                cand = _buscar_tickets(datos)
            except Exception as e:
                cand = pd.DataFrame()
                st.warning(f"No se pudo buscar tickets: {e}")
            item["cand"] = cand
        if cand is not None and not cand.empty:
            ops = {f"#{int(r.transaccion)} · {r.fecha_e} · {r.procedencia} · "
                   f"{r.neto_balanza:,.0f} kg · {r.patcha} ({r.match})": int(r.transaccion)
                   for r in cand.itertuples()}
            etiquetas = list(ops) + ["Sin ticket"]
            idx_def = 0 if item.get("ticket_sel") else len(etiquetas) - 1
            sel = st.radio("🎫 Ticket de balanza WORMS", etiquetas, index=min(idx_def, len(etiquetas)-1), key=f"tk_{h}")
            item["ticket_sel"] = ops.get(sel)
            if item["ticket_sel"]:
                neto_bal = float(cand.loc[cand.transaccion == item["ticket_sel"], "neto_balanza"].iloc[0])
                dif = float(datos["neto_kg"] or 0) - neto_bal
                pct = 100 * dif / neto_bal if neto_bal else 0
                item["dif_kg"] = dif
                (st.success if abs(pct) <= 2 else st.warning)(
                    f"Remito {datos['neto_kg']:,.0f} kg vs balanza {neto_bal:,.0f} kg → "
                    f"diferencia {dif:+,.0f} kg ({pct:+.2f}%)")
            else:
                item["dif_kg"] = None
        else:
            item["ticket_sel"], item["dif_kg"] = None, None
            st.info("Sin ticket de balanza coincidente (se puede vincular después desde Historial).")


def render(USR, conectar):
    st.subheader("📸 Remitos — digitalización por foto")
    tab_carga, tab_hist = st.tabs(["📥 Cargar remitos", "📋 Historial y control"])

    ss = st.session_state
    ss.setdefault("rem_cache", {})     # hash foto -> item
    ss.setdefault("rem_informe", None)

    # ================= CARGA =================
    with tab_carga:
        st.caption("Arrastrá una foto o **la carpeta entera** (seleccioná todas las imágenes). "
                   "Se lee cada remito, se detectan duplicados por N° único y subís todo junto. "
                   "Las fotos no se almacenan.")
        fotos = st.file_uploader("Fotos de remitos", type=["jpg", "jpeg", "png", "webp"],
                                 accept_multiple_files=True, key="rem_up")
        cam = st.camera_input("…o sacá la foto acá", key="rem_cam",
                              label_visibility="collapsed") if st.toggle(
            "📷 Usar cámara", key="rem_usar_cam") else None
        archivos = list(fotos or [])
        if cam:
            archivos.append(cam)

        # --- extracción (cache por hash: una foto se procesa una sola vez) ---
        items, hs = [], []
        pend = [(f, hashlib.sha1(f.getvalue()).hexdigest()[:16]) for f in archivos]
        nuevos = [(f, h) for f, h in pend if h not in ss.rem_cache]
        if nuevos:
            barra = st.progress(0.0, text="Leyendo remitos…")
            for i, (f, h) in enumerate(nuevos):
                barra.progress((i) / len(nuevos), text=f"🤖 Leyendo {f.name} ({i+1}/{len(nuevos)})…")
                it = {"name": f.name, "raw": f.getvalue(), "datos": None, "error": None,
                      "cand": None, "ticket_sel": None, "dif_kg": None, "guardado": None}
                try:
                    it["datos"] = extraer_remito(it["raw"])
                except Exception as e:
                    it["error"] = str(e)[:200]
                ss.rem_cache[h] = it
            barra.progress(1.0, text="Listo")
            barra.empty()

        for f, h in pend:
            items.append(ss.rem_cache[h]); hs.append(h)

        # pre-seleccionar ticket automático (mejor candidato por N° remito)
        for it in items:
            if it["datos"] and it["cand"] is None and not it["guardado"]:
                try:
                    it["cand"] = _buscar_tickets(it["datos"])
                except Exception:
                    it["cand"] = pd.DataFrame()
                if not it["cand"].empty and it["cand"].iloc[0]["match"] == "N° remito":
                    it["ticket_sel"] = int(it["cand"].iloc[0]["transaccion"])
                    neto_bal = float(it["cand"].iloc[0]["neto_balanza"])
                    it["dif_kg"] = float(it["datos"].get("neto_kg") or 0) - neto_bal

        # clasificar (dedup base + lote)
        norms_lote = {}
        for it in items:
            _clasificar(it, norms_lote)

        if items:
            # --- resumen del lote ---
            df_res = pd.DataFrame([{
                "Foto": it["name"], "Estado": _BADGE.get(it["estado"], it["estado"]),
                "N° remito": (it["datos"] or {}).get("nro_remito"),
                "Fecha": (it["datos"] or {}).get("fecha_remito"),
                "Emisor": (it["datos"] or {}).get("emisor"),
                "Producto": (it["datos"] or {}).get("producto"),
                "Neto kg": (it["datos"] or {}).get("neto_kg"),
                "Ticket prov.": (it["datos"] or {}).get("ticket"),
                "Ticket balanza": it.get("ticket_sel"),
                "Dif kg": None if it.get("dif_kg") is None else round(it["dif_kg"]),
                "Motivo": it.get("motivo"),
            } for it in items])
            st.dataframe(df_res, use_container_width=True, hide_index=True)
            st.caption("**Ticket prov.** = número impreso en el remito del proveedor · "
                       "**Ticket balanza** = pesada en nuestra balanza (transacción WORMS) con la que se compara el neto.")

            n_listo = sum(1 for it in items if it["estado"] in ("LISTO", "SIN_TICKET"))
            n_dup = sum(1 for it in items if it["estado"] == "DUPLICADO")
            n_rev = sum(1 for it in items if it["estado"] == "REVISAR")
            if n_dup:
                st.warning(f"🔁 {n_dup} remito(s) duplicado(s): NO se van a subir (mirá el motivo en la tabla).")
            if n_rev:
                st.info(f"⚠️ {n_rev} remito(s) necesitan revisión manual abajo antes de subir.")

            if n_listo and st.button(f"☁️ Subir {n_listo} remito(s) a la base", type="primary", key="rem_bulk"):
                a_subir = [it for it in items if it["estado"] in ("LISTO", "SIN_TICKET")]
                try:
                    informe = _subir_lote(conectar, USR, a_subir)
                    ss.rem_informe = {"cuando": datetime.now().strftime("%d/%m/%Y %H:%M"),
                                      "filas": informe}
                    st.rerun()
                except Exception as e:
                    st.error(f"No se pudo subir el lote: {e}")

            # --- revisión individual ---
            st.markdown("---")
            for it, h in zip(items, hs):
                icono = _BADGE.get(it["estado"], it["estado"])
                with st.expander(f"{icono} — {it['name']} · {(it['datos'] or {}).get('nro_remito') or 's/n'}",
                                 expanded=(it["estado"] == "REVISAR")):
                    if it["estado"] == "SUBIDO":
                        st.success(f"Ya subido ({it['motivo']}).")
                        continue
                    if it["estado"] == "ERROR":
                        st.error(it["motivo"])
                        st.image(it["raw"], width=350)
                        continue
                    if it["estado"] == "DUPLICADO":
                        st.error(f"🔁 {it['motivo']}. No se sube de nuevo.")
                    _card_revision(it, h)
                    if it["estado"] != "DUPLICADO":
                        d = it["datos"]
                        ok = bool(d.get("emisor") and d.get("nro_remito") and d.get("neto_kg"))
                        if st.button("💾 Subir este remito", key=f"sv_{h}", disabled=not ok):
                            inf = _subir_lote(conectar, USR, [it])
                            ss.rem_informe = {"cuando": datetime.now().strftime("%d/%m/%Y %H:%M"),
                                              "filas": (ss.rem_informe or {}).get("filas", []) + inf}
                            st.rerun()

        # ================= INFORME DE CARGA =================
        if ss.rem_informe:
            st.markdown("---")
            st.markdown(f"### 📄 Informe de carga — {ss.rem_informe['cuando']}")
            df_inf = pd.DataFrame(ss.rem_informe["filas"])
            subidos = df_inf[df_inf.resultado == "SUBIDO"]
            omitidos = df_inf[df_inf.resultado == "OMITIDO_DUPLICADO"]
            errores = df_inf[df_inf.resultado == "ERROR"]
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("✅ Subidos", len(subidos))
            k2.metric("🔁 Duplicados omitidos", len(omitidos))
            k3.metric("❌ Errores", len(errores))
            k4.metric("TN subidas", f"{pd.to_numeric(subidos['neto_kg'], errors='coerce').sum()/1000:,.2f}")
            st.dataframe(df_inf, use_container_width=True, hide_index=True)
            st.download_button("⬇️ Descargar informe (CSV)",
                               df_inf.to_csv(index=False).encode("utf-8-sig"),
                               f"informe_remitos_{date.today()}.csv", "text/csv")
            if st.button("🧹 Nueva carga (limpiar)", key="rem_reset"):
                ss.rem_cache = {}
                ss.rem_informe = None
                st.rerun()

    # ================= HISTORIAL =================
    with tab_hist:
        c1, c2 = st.columns(2)
        f_desde = c1.date_input("Desde", date.today().replace(day=1), key="rh_d", format="DD/MM/YYYY")
        f_hasta = c2.date_input("Hasta", date.today(), key="rh_h", format="DD/MM/YYYY")
        try:
            df = _read_df(
                "SELECT id, fecha_remito, emisor, nro_remito, producto, neto_remito_kg, "
                "ticket, neto_balanza_kg, diferencia_kg, diferencia_pct, patcha, "
                "estado, cargado_por, creado_en::date AS fecha_carga "
                "FROM produccion.v_remito_vs_balanza "
                "WHERE fecha_remito BETWEEN %s AND %s ORDER BY id DESC",
                (f_desde, f_hasta))
        except Exception as e:
            st.error(f"No se pudo leer el historial: {e}")
            return
        if df.empty:
            st.info("Sin remitos en el período.")
            return

        # ---- filtros interactivos ----
        for col in ("neto_remito_kg", "neto_balanza_kg", "diferencia_kg", "diferencia_pct"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        fc1, fc2, fc3, fc4 = st.columns(4)
        f_emisor = fc1.multiselect("Emisor", sorted(df["emisor"].dropna().unique()), key="rh_em")
        f_prod = fc2.multiselect("Producto", sorted(df["producto"].dropna().unique()), key="rh_pr")
        f_ticket = fc3.selectbox("Ticket balanza", ["Todos", "Con ticket", "Sin ticket"], key="rh_tkf")
        f_estado = fc4.multiselect("Estado", sorted(df["estado"].dropna().unique()), key="rh_es")
        fc5, fc6, fc7 = st.columns([2, 1, 1])
        f_busca = fc5.text_input("🔎 Buscar N° remito / patente / cargado por", key="rh_q")
        f_difmin = fc6.number_input("Dif. mínima ±%", 0.0, 100.0, 0.0, 0.5, key="rh_difmin",
                                    help="Mostrar solo remitos cuya diferencia contra balanza supere este %")
        f_orden = fc7.selectbox("Ordenar por", ["Más reciente", "Mayor diferencia", "Mayor neto"], key="rh_ord")

        if f_emisor:
            df = df[df["emisor"].isin(f_emisor)]
        if f_prod:
            df = df[df["producto"].isin(f_prod)]
        if f_estado:
            df = df[df["estado"].isin(f_estado)]
        if f_ticket == "Con ticket":
            df = df[df["ticket"].notna()]
        elif f_ticket == "Sin ticket":
            df = df[df["ticket"].isna()]
        if f_difmin > 0:
            df = df[df["diferencia_pct"].abs() >= f_difmin]
        if f_busca.strip():
            q = f_busca.strip().lower()
            df = df[df.apply(lambda r: q in str(r["nro_remito"]).lower()
                             or q in str(r["patcha"]).lower()
                             or q in str(r["cargado_por"]).lower(), axis=1)]
        if f_orden == "Mayor diferencia":
            df = df.reindex(df["diferencia_pct"].abs().sort_values(ascending=False).index)
        elif f_orden == "Mayor neto":
            df = df.sort_values("neto_remito_kg", ascending=False)

        if df.empty:
            st.info("Ningún remito cumple los filtros.")
            return

        # ---- KPIs ----
        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("Remitos", len(df))
        k2.metric("TN remito", f"{df['neto_remito_kg'].sum()/1000:,.2f}")
        k3.metric("TN balanza", f"{df['neto_balanza_kg'].sum()/1000:,.2f}")
        _dif_tot = df["diferencia_kg"].sum()
        k4.metric("Dif. total (kg)", f"{_dif_tot:+,.0f}")
        k5.metric("Sin ticket", int(df["ticket"].isna().sum()))

        # ---- gráficos ----
        g1, g2 = st.tabs(["📊 TN por emisor", "📅 TN por día"])
        with g1:
            por_emisor = (df.groupby("emisor")["neto_remito_kg"].sum() / 1000).round(2).sort_values(ascending=False)
            st.bar_chart(por_emisor, use_container_width=True)
        with g2:
            por_dia = (df.groupby("fecha_remito")["neto_remito_kg"].sum() / 1000).round(2).sort_index()
            st.bar_chart(por_dia, use_container_width=True)

        # ---- tabla ----
        df_show = df.rename(columns={
            "fecha_remito": "Fecha", "emisor": "Emisor", "nro_remito": "N° remito",
            "producto": "Producto", "neto_remito_kg": "Neto remito (kg)",
            "ticket": "Ticket balanza", "neto_balanza_kg": "Neto balanza (kg)",
            "diferencia_kg": "Dif (kg)", "diferencia_pct": "Dif %", "patcha": "Patente",
            "estado": "Estado", "cargado_por": "Cargado por", "fecha_carga": "Fecha carga"})
        st.dataframe(
            df_show, use_container_width=True, hide_index=True,
            column_config={
                "Neto remito (kg)": st.column_config.NumberColumn(format="%,.0f"),
                "Neto balanza (kg)": st.column_config.NumberColumn(format="%,.0f"),
                "Dif (kg)": st.column_config.NumberColumn(format="%,.0f"),
                "Dif %": st.column_config.NumberColumn(format="%.2f%%"),
            })
        st.download_button("⬇️ CSV (con filtros aplicados)",
                           df_show.to_csv(index=False).encode("utf-8-sig"),
                           f"remitos_{f_desde}_{f_hasta}.csv", "text/csv")

        if USR.get("rol") in ("ADMIN", "SUPERVISOR"):
            with st.expander("🔗 Vincular / anular"):
                rid = st.number_input("ID remito", min_value=1, step=1, key="rh_id")
                cta, ctb = st.columns(2)
                tk = cta.number_input("Ticket balanza", min_value=0, step=1, key="rh_tk")
                if cta.button("Vincular ticket", key="rh_btn_tk") and tk:
                    try:
                        with conectar(USR["id_usuario"]) as (conn, _a):
                            with conn.cursor() as cur:
                                cur.execute(
                                    "UPDATE produccion.fact_remito SET ticket_balanza=%s, "
                                    "estado='CONFIRMADO', diferencia_kg=neto_kg-(SELECT abs(pesoneto) "
                                    "FROM produccion.transacciones WHERE transaccion=%s) "
                                    "WHERE id=%s", (int(tk), int(tk), int(rid)))
                        st.success("Vinculado."); st.rerun()
                    except Exception as e:
                        st.error(f"No se pudo vincular: {e}")
                if ctb.button("🗑️ Anular remito", key="rh_btn_an"):
                    try:
                        with conectar(USR["id_usuario"]) as (conn, _a):
                            with conn.cursor() as cur:
                                cur.execute("UPDATE produccion.fact_remito SET estado='ANULADO' "
                                            "WHERE id=%s", (int(rid),))
                        st.success("Anulado."); st.rerun()
                    except Exception as e:
                        st.error(f"No se pudo anular: {e}")
