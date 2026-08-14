# -*- coding: utf-8 -*-
"""Brief de Dirección · extracción de datos.

Una sola función `cargar(cat, semana)` devuelve el dict que consume el
renderizador. Todo sale de las vistas `produccion.v_brief_*` para que la
pestaña de la app, el PDF semanal y cualquier consulta manual den el mismo
número. No hay lógica de negocio acá: las bandas de calidad, los compromisos
y los desvíos ya vienen resueltos por la base.
"""
from datetime import date, timedelta


def semana_cerrada(hoy=None):
    """Último lunes de una semana ISO ya terminada (lunes a domingo)."""
    hoy = hoy or date.today()
    lunes_actual = hoy - timedelta(days=hoy.weekday())
    return lunes_actual - timedelta(days=7)


def semanas_disponibles(cat=None, n=26):
    """Las últimas n semanas ISO ya cerradas. Se generan por calendario en vez de
    consultar la base: preguntarle a v_brief_flujo_semana obliga a recorrer toda
    la portería sólo para llenar un desplegable."""
    base = semana_cerrada()
    return [(base - timedelta(weeks=i)).isoformat() for i in range(n)]


def _recs(df):
    return [] if df is None or df.empty else df.to_dict("records")


def cargar(cat, semana):
    """semana = lunes ISO en 'YYYY-MM-DD'. Devuelve el dict del brief."""
    sem = str(semana)
    fin = (date.fromisoformat(sem) + timedelta(days=6)).isoformat()
    desde12 = (date.fromisoformat(sem) - timedelta(weeks=11)).isoformat()
    desde9 = (date.fromisoformat(sem) - timedelta(weeks=8)).isoformat()
    mes0 = (date.fromisoformat(sem).replace(day=1) - timedelta(days=124)).replace(day=1).isoformat()

    D = {"semana_ini": sem, "semana_fin": fin, "emitido": date.today().isoformat()}
    D["semana_iso"] = cat("SELECT to_char(%s::date,'IYYY-\"S\"IW') AS s", (sem,))["s"][0]

    D["flujo"] = _recs(cat(
        "SELECT semana::text, flujo, round(sum(tn),1) AS tn, sum(tickets) AS tk, "
        "  round(sum(tn) FILTER (WHERE familia='AFE'),1) AS tn_afe, "
        "  round(100*sum(tn_lab)/nullif(sum(tn),0),0) AS cob "
        "FROM produccion.v_brief_flujo_semana "
        "WHERE semana BETWEEN %s AND %s AND flujo IN ('ENTRADA','SALIDA') "
        "GROUP BY 1,2", (desde12, sem)))

    D["afe_banda"] = _recs(cat(
        "SELECT semana::text, banda, tickets, round(tn,1) AS tn, "
        "  round(s_prom,0) AS s, round(p_prom,0) AS p, round(acidez_prom,2) AS ac "
        "FROM produccion.v_brief_afe_banda_semana WHERE semana BETWEEN %s AND %s",
        (desde12, sem)))

    D["reacciones"] = _recs(cat(
        "SELECT semana::text, sum(reacciones) AS n, round(sum(tn_producidas),1) AS tn, "
        "  round(sum(tn_formula),1) AS tn_form, round(avg(rendimiento_pct),1) AS rend, "
        "  round(avg(utilizacion_pct),1) AS uti, round(avg(ciclo_h),1) AS ciclo_h, "
        "  round(avg(ciclo_prog_h),1) AS prog_h, round(avg(desvio_h),1) AS desvio_h, "
        "  sum(n_tiempos_confiables) AS n_conf "
        "FROM produccion.v_brief_reacciones_semana WHERE semana BETWEEN %s AND %s GROUP BY 1",
        (desde12, sem)))

    # familias que realmente viven en tanque; el resto es pasaje sin stock
    # familias con tanque propio, como literal SQL: `cat` cachea por parámetros y
    # una lista de Python no siempre es hasheable del lado de Streamlit.
    FAM = "('AFE','AG','ARE','BORRA','SEBO','GLICERINA','ACIDO','AGUA','EMULSION','FONDO_TK')"
    D["desvio_familia"] = _recs(cat(
        "SELECT semana::text, familia, round(stock_ini_t,1) AS ini, round(prod_t,1) AS prod, "
        "  round(ext_in_t,1) AS e_in, round(ext_out_t,1) AS e_out, round(interno_t,1) AS int_t, "
        "  round(stock_proy_t,1) AS proy, round(stock_real_t,1) AS real_t, round(desvio_t,1) AS desvio "
        "FROM produccion.v_desvio_stock_semanal "
        "WHERE semana IN (%s, (%s::date - 7)) AND familia IN " + FAM, (sem, sem)))

    D["desvio_pool"] = _recs(cat(
        "SELECT semana::text, round(sum(stock_ini_t),1) AS ini, round(sum(prod_t),1) AS prod, "
        "  round(sum(ext_in_t),1) AS e_in, round(sum(ext_out_t),1) AS e_out, "
        "  round(sum(interno_t),1) AS int_t, "
        "  round(sum(stock_ini_t)+sum(prod_t)+sum(ext_in_t)-sum(ext_out_t)-sum(interno_t),1) AS proy, "
        "  round(sum(stock_real_t),1) AS real_t, "
        "  round(sum(stock_real_t)-(sum(stock_ini_t)+sum(prod_t)+sum(ext_in_t)"
        "        -sum(ext_out_t)-sum(interno_t)),1) AS desvio "
        "FROM produccion.v_desvio_stock_semanal "
        "WHERE semana BETWEEN %s AND %s AND familia IN ('AFE','AG') GROUP BY 1", (desde9, sem)))

    # el stock es SIEMPRE la foto de hoy: es una medición, no una serie histórica
    D["stock"] = _recs(cat(
        "SELECT producto, banda, tanques, round(tn,1) AS tn, "
        "  round(tn_comp_despacho,1) AS c_desp, round(tn_comp_vencido,1) AS c_venc, "
        "  round(tn_libre,1) AS libre, tanques_sobrecomprometidos AS sobre, "
        "  round(horas_peor_medicion,0) AS h, round(s_pond,0) AS s, round(p_pond,0) AS p "
        "FROM produccion.v_brief_stock_calidad WHERE tn > 0"))
    # bandas de AFE-S sin stock: se muestran igual, en cero (que falten es la noticia)
    _hay = {(r["producto"], r["banda"]) for r in D["stock"]}
    for b in ("A", "B", "C", "D"):
        if ("AFE-S", b) not in _hay:
            D["stock"].append({"producto": "AFE-S", "banda": b, "tanques": 0, "tn": 0.0,
                               "c_desp": 0.0, "c_venc": 0.0, "libre": 0.0, "sobre": 0,
                               "h": None, "s": None, "p": None})

    D["despachos"] = _recs(cat(
        "SELECT id_despacho AS id, titulo, destino, producto, fecha_despacho::text AS fecha, "
        "  estado, n_contenedores AS cont, round(tn_total,1) AS tn, round(pct_cubierto,0) AS cub, "
        "  fuera_spec AS fs, n_lineas_exceden_stock AS exc, round(acidez_pond,2) AS ac, "
        "  round(azufre_pond,0) AS s, round(fosforo_pond,0) AS p, aprob_direccion AS aprob "
        "FROM produccion.v_despacho_resumen WHERE fecha_despacho >= %s ORDER BY fecha_despacho", (sem,)))

    D["meses"] = _recs(cat(
        "WITH m AS (SELECT mes, flujo, round(sum(tn),1) tn, "
        "     round(sum(tn) FILTER (WHERE familia='AFE'),1) afe, "
        "     round(100*sum(tn_lab)/nullif(sum(tn),0),0) cob "
        "   FROM produccion.v_brief_flujo_semana WHERE mes >= %s AND flujo IN ('ENTRADA','SALIDA') "
        "   GROUP BY 1,2), "
        "r AS (SELECT mes, sum(reacciones) n, round(sum(tn_producidas),1) tn "
        "   FROM produccion.v_brief_reacciones_semana WHERE mes >= %s GROUP BY 1), "
        "d AS (SELECT mes, sum(despachos) n, round(sum(tn),1) tn, sum(n_fuera_spec) fs "
        "   FROM produccion.v_brief_despachos_semana WHERE mes >= %s GROUP BY 1) "
        "SELECT to_char(e.mes,'YYYY-MM') AS mes, e.tn AS ing, e.afe, e.cob, s.tn AS sal, "
        "  r.n AS reac_n, r.tn AS reac_tn, d.n AS desp_n, d.tn AS desp_tn, d.fs AS desp_fs "
        "FROM (SELECT * FROM m WHERE flujo='ENTRADA') e "
        "LEFT JOIN (SELECT * FROM m WHERE flujo='SALIDA') s ON s.mes=e.mes "
        "LEFT JOIN r ON r.mes=e.mes LEFT JOIN d ON d.mes=e.mes ORDER BY 1",
        (mes0, mes0, mes0)))

    liq = cat(
        "SELECT mes_txt, dia, round(tn::numeric,1) AS tn FROM produccion.v_brief_liquidos_dia "
        "WHERE mes >= %s ORDER BY mes_txt, dia", (mes0,))
    D["liquidos"] = []
    if liq is not None and not liq.empty:
        for m, g in liq.groupby("mes_txt", sort=True):
            dias = [[int(r.dia), float(r.tn)] for r in g.itertuples()]
            D["liquidos"].append({"mes": m, "tn": round(sum(d[1] for d in dias), 1),
                                  "ult": max(d[0] for d in dias), "dias": dias})
        D["liquidos"] = D["liquidos"][-4:]

    D["cobertura_libro"] = _recs(cat(
        "SELECT sector, tanques, round(mov_fisico_kl,1) AS fis, round(mov_libro_kl,1) AS libro, "
        "  round(cobertura_pct,0) AS cob, round(no_explicado_neto_kl,1) AS no_expl "
        "FROM produccion.v_cobertura_libro_semanal WHERE semana = %s", (sem,)))

    D["confianza"] = _recs(cat(
        "SELECT sector, tanques, round(kl_medidos,1) AS kl, round(horas_peor_medicion,0) AS h "
        "FROM produccion.v_dir_stock_confianza"))

    D["comp_prod"] = _recs(cat(
        "SELECT producto, rol, estado_batch AS estado, vencido, round(tn::numeric,1) AS tn "
        "FROM produccion.v_brief_compromiso_produccion ORDER BY tn DESC"))

    D["proveedores"] = _recs(cat(
        "WITH b AS (SELECT proveedor, banda, tn, semana FROM produccion.v_brief_porteria "
        "  WHERE familia='AFE' AND flujo='ENTRADA' AND semana BETWEEN %s AND %s) "
        "SELECT coalesce(proveedor,'—') AS prov, round(sum(tn),1) AS tn_tot, "
        "  round(sum(tn) FILTER (WHERE semana=%s),1) AS tn_sem, "
        "  round(100*sum(tn) FILTER (WHERE banda IN ('A','B'))/nullif(sum(tn),0),0) AS pct_ab, "
        "  round(100*sum(tn) FILTER (WHERE banda='D')/nullif(sum(tn),0),0) AS pct_d, "
        "  round(100*sum(tn) FILTER (WHERE banda IN ('A','B') AND semana > (%s::date-21))"
        "        /nullif(sum(tn) FILTER (WHERE semana > (%s::date-21)),0),0) AS pct_ab3 "
        "FROM b GROUP BY 1 HAVING sum(tn) > 100 ORDER BY 2 DESC LIMIT 8",
        (desde9, sem, sem, sem, sem)))

    # normaliza tipos (Decimal -> float) para que el renderizador no se entere
    def _f(v):
        try:
            return float(v)
        except Exception:
            return v
    for k, v in D.items():
        if isinstance(v, list):
            for row in v:
                for kk, vv in list(row.items()):
                    if vv is not None and hasattr(vv, "__float__") and not isinstance(vv, bool):
                        row[kk] = _f(vv)
    return D
