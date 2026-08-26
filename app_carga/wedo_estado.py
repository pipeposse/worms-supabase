# -*- coding: utf-8 -*-
"""Estado del sync de niveles WeDo — el aviso que faltó el 25/08.

Ese día venció la API key de WeDo y el sync siguió 'en verde' sin traer una
sola medición: la app mostró 32 horas los niveles congelados y una formulación
se armó con litros que no existían. Este módulo mira vw_tanque_wedo_map (que
ahora expone ultimo_status/ultimo_error por dispositivo) y pinta un banner
imposible de ignorar en las pantallas que usan niveles: armador de despachos,
informe de stock y disponibilidad de descarga."""

import pandas as pd
import streamlit as st

_TZ = "America/Argentina/Buenos_Aires"
HORAS_VIEJO = 2.0     # el sync corre cada 20 min: 2 h sin lectura = problema


def banner(cat, horas=HORAS_VIEJO):
    """Banner de alerta si los niveles WeDo están viejos o el sync falla.

    No rompe nunca: ante cualquier error propio, no muestra nada (las pantallas
    que lo llaman no dependen de esto para funcionar)."""
    try:
        w = cat("SELECT nombre_nuestro, ultima_medicion, ultimo_status, ultimo_error "
                "FROM produccion.vw_tanque_wedo_map")
        if w is None or w.empty:
            return
        _ts = pd.to_datetime(w["ultima_medicion"], errors="coerce", utc=True)
        _now = pd.Timestamp.now(tz="UTC")
        _viejo = _ts.isna() | ((_now - _ts) > pd.Timedelta(hours=float(horas)))
        _st = pd.to_numeric(w["ultimo_status"], errors="coerce")
        _con_err = w[_st.notna() & (_st != 200)]
        if not bool(_viejo.any()) and _con_err.empty:
            return
        _ult = _ts.max()
        _ult_txt = (_ult.tz_convert(_TZ).strftime("%d/%m %H:%M")
                    if pd.notna(_ult) else "nunca")
        _det = ""
        if not _con_err.empty:
            _e = _con_err["ultimo_error"].dropna()
            if not _e.empty:
                _msg = str(_e.iloc[0])
                if "expired" in _msg.lower():
                    _det = (" **Motivo: la API key de WeDo está VENCIDA** — hay que "
                            "renovarla en el portal de WeDo y actualizarla en el sistema.")
                else:
                    _det = " Motivo del sync: `%s`." % _msg[:120]
        st.error(
            "📡 **NIVELES WeDo DESACTUALIZADOS — %d de %d tanques sin medición hace más "
            "de %.0f h** (última lectura: %s). Los litros de esos tanques que ves acá "
            "**NO son los reales**: no armar formulaciones ni elegir dónde descargar con "
            "estos números sin verificar en planta.%s"
            % (int(_viejo.sum()), len(w), float(horas), _ult_txt, _det))
    except Exception:
        pass


def portada(qf, horas=HORAS_VIEJO):
    """Estado WeDo SIEMPRE visible en la página principal.

    qf = función que ejecuta un SELECT y devuelve un DataFrame (en la portada es
    _home_df, porque cat() todavía no existe en ese punto del script).
    Pinta una píldora verde cuando todo está bien y un cartel rojo gigante si la
    API key está vencida o hay tanques sin reportar — para que el 25/08 no se
    repita nunca más."""
    try:
        w = qf("SELECT nombre_nuestro, ultima_medicion, ultimo_status, ultimo_error "
               "FROM produccion.vw_tanque_wedo_map")
        if w is None or len(w) == 0:
            return
        _ts = pd.to_datetime(w["ultima_medicion"], errors="coerce", utc=True)
        _now = pd.Timestamp.now(tz="UTC")
        _viejo = _ts.isna() | ((_now - _ts) > pd.Timedelta(hours=float(horas)))
        _st = pd.to_numeric(w["ultimo_status"], errors="coerce")
        _errs = _st.notna() & (_st != 200)
        _key_venc = False
        try:
            _key_venc = bool(w[_errs]["ultimo_error"].astype(str)
                             .str.contains("expired", case=False, na=False).any())
        except Exception:
            pass
        _n_ok = int((~_viejo).sum())
        _tot = len(w)
        _ult = _ts.max()
        _ult_txt = (_ult.tz_convert(_TZ).strftime("%d/%m %H:%M")
                    if pd.notna(_ult) else "nunca")
        if not bool(_viejo.any()) and not bool(_errs.any()):
            st.markdown(
                "<div style='display:inline-block;background:#dcfce7;border:1px solid #16a34a;"
                "border-radius:999px;padding:4px 14px;margin:2px 0 8px;font-size:.85rem;"
                "color:#14532d;font-weight:700'>📡 Niveles WeDo: 🟢 API key ACTIVA · "
                "%d/%d tanques reportando · última medición %s</div>"
                % (_n_ok, _tot, _ult_txt), unsafe_allow_html=True)
            return
        if _key_venc:
            _tit = "🔴 API KEY DE WeDo VENCIDA — los niveles de tanques NO se actualizan"
            _cue = ("Renovar la key en el portal de WeDo (iot.we-do.io) y actualizarla en el "
                    "sistema. Hasta entonces, los litros que muestra la app son la última "
                    "foto vieja (%s)." % _ult_txt)
        else:
            _tit = ("🔴 Niveles WeDo DESACTUALIZADOS — %d de %d tanques sin medición hace "
                    "más de %.0f h" % (int(_viejo.sum()), _tot, float(horas)))
            _err_txt = ""
            try:
                _e = w[_errs]["ultimo_error"].dropna()
                _err_txt = (" Error del sync: %s." % str(_e.iloc[0])[:120]) if len(_e) else ""
            except Exception:
                pass
            _cue = ("Última medición: %s.%s No usar estos niveles para formular ni "
                    "descargar sin verificar en planta." % (_ult_txt, _err_txt))
        st.markdown(
            "<div style='background:#fef2f2;border:2px solid #dc2626;border-radius:12px;"
            "padding:12px 16px;margin:2px 0 10px'>"
            "<div style='color:#991b1b;font-size:1.05rem;font-weight:900'>%s</div>"
            "<div style='color:#7f1d1d;font-size:.86rem;margin-top:4px'>%s</div></div>"
            % (_tit, _cue), unsafe_allow_html=True)
    except Exception:
        pass
