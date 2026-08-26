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
