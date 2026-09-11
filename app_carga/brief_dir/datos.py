# -*- coding: utf-8 -*-
"""Brief de Dirección · extracción de datos.

Una sola función `cargar(cat, semana)` devuelve el dict que consume el
renderizador. Todo sale de las vistas `produccion.v_brief_*` para que la
pestaña de la app, el PDF semanal y cualquier consulta manual den el mismo
número. No hay lógica de negocio acá: las categorías de calidad, los compromisos
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
    """records() convirtiendo Decimal→float: psycopg2 devuelve numeric como
    Decimal y los gráficos multiplican por float (TypeError si se mezclan)."""
    if df is None or df.empty:
        return []
    from decimal import Decimal
    filas = df.to_dict("records")
    for f in filas:
        for k, v in f.items():
            if isinstance(v, Decimal):
                f[k] = float(v)
    return filas


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

    D["afe_categoria"] = _recs(cat(
        "SELECT semana::text, categoria, tickets, round(tn,1) AS tn, "
        "  round(s_prom,0) AS s, round(p_prom,0) AS p, round(acidez_prom,2) AS ac "
        "FROM produccion.v_brief_afe_categoria_semana WHERE semana BETWEEN %s AND %s",
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
        "SELECT producto, categoria, tanques, round(tn,1) AS tn, "
        "  round(tn_comp_despacho,1) AS c_desp, round(tn_comp_vencido,1) AS c_venc, "
        "  round(tn_libre,1) AS libre, tanques_sobrecomprometidos AS sobre, "
        "  round(horas_peor_medicion,0) AS h, round(s_pond,0) AS s, round(p_pond,0) AS p "
        "FROM produccion.v_brief_stock_calidad WHERE tn > 0"))
    # categorías de AFE-S sin stock: se muestran igual, en cero (que falten es la noticia)
    _hay = {(r["producto"], r["categoria"]) for r in D["stock"]}
    for b in ("A", "B", "C", "D"):
        if ("AFE-S", b) not in _hay:
            D["stock"].append({"producto": "AFE-S", "categoria": b, "tanques": 0, "tn": 0.0,
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
        # foto al cierre: si el brief se regenera días después, los datos diarios
        # posteriores al fin de la semana informada no entran
        liq = liq[(liq["mes_txt"] < fin[:7])
                  | ((liq["mes_txt"] == fin[:7]) & (liq["dia"] <= int(fin[8:10])))]
    if liq is not None and not liq.empty:
        for m, g in liq.groupby("mes_txt", sort=True):
            dias = [[int(r.dia), float(r.tn)] for r in g.itertuples()]
            D["liquidos"].append({"mes": m, "tn": round(sum(d[1] for d in dias), 1),
                                  "ult": max(d[0] for d in dias), "dias": dias})
        D["liquidos"] = D["liquidos"][-4:]

    D["reacciones_tipo"] = _recs(cat(
        "SELECT semana::text, tipo_proceso AS tipo, reacciones AS n, round(tn_producidas,1) AS tn, "
        "  round(rendimiento_pct,0) AS rend, round(utilizacion_pct,0) AS uti "
        "FROM produccion.v_brief_reacciones_semana WHERE semana BETWEEN %s AND %s",
        (desde12, sem)))

    D["afe_categoria_mes"] = _recs(cat(
        "SELECT to_char(mes,'YYYY-MM') AS mes, categoria, round(sum(tn),1) AS tn "
        "FROM produccion.v_brief_afe_categoria_semana WHERE mes >= %s GROUP BY 1,2", (mes0,)))

    D["mezcla"] = _recs(cat(
        "SELECT producto, round(tn,1) AS tn, round(parte,4) AS parte "
        "FROM produccion.v_brief_mezcla_despacho"))
    if not D["mezcla"]:
        # sin despachos recientes, la mezcla histórica típica: AFE-S diluyendo AG-C
        D["mezcla"] = [{"producto": "AFE-S", "tn": 0.0, "parte": 0.94}]

    D["desvio_producto"] = _recs(cat(
        "SELECT codigo_producto AS cod, round(stock_ini_t,1) AS ini, round(prod_t,1) AS prod, "
        "  round(ext_in_t,1) AS e_in, round(ext_out_t,1) AS e_out, round(interno_t,1) AS intr, "
        "  round(stock_proy_t,1) AS unico, round(stock_real_t,1) AS medido, "
        "  round(desvio_t,1) AS desvio "
        "FROM produccion.v_desvio_stock_producto "
        "WHERE semana = %s AND (abs(coalesce(desvio_t,0)) > 1 OR coalesce(stock_real_t,0) > 5) "
        "  AND codigo_producto IN (SELECT DISTINCT producto "
        "                          FROM produccion.v_brief_stock_tanque)", (sem,)))

    D["balance_afe"] = _recs(cat(
        "SELECT semana::text, round(stock_inicial,1) AS ini, round(ingresos,1) AS ing, "
        "  round(producido,1) AS prod, round(consumido_reactores,1) AS cons, "
        "  round(despachado,1) AS desp, n_despachos AS nd, round(stock_esperado,1) AS esp, "
        "  round(stock_medido,1) AS med, round(desvio,1) AS desvio "
        "FROM produccion.v_brief_balance_afe WHERE semana BETWEEN %s AND %s", (desde12, sem)))

    D["etapas"] = _recs(cat(
        "SELECT tipo_proceso AS tipo, etapa, sum(n) AS n, "
        "  round(avg(real_h)::numeric,1) AS real, round(avg(prog_h)::numeric,1) AS prog, "
        "  round(avg(target_h)::numeric,1) AS target, round(avg(desvio_h)::numeric,1) AS desvio, "
        "  sum(dentro_rango) AS dentro, sum(sospecha_click) AS clicks, "
        "  sum(tiempos_invalidos) AS invalidos "
        "FROM produccion.v_brief_etapa_semana WHERE semana >= (%s::date - 56) "
        "GROUP BY 1,2 ORDER BY 1, CASE etapa WHEN 'REACCION' THEN 1 WHEN 'REPOSANDO' THEN 2 "
        "  ELSE 3 END", (sem,)))

    D["insumos"] = _recs(cat(
        "SELECT semana::text, insumo, round(teorico::numeric,1) AS teorico, unidad, "
        "  round(registrado::numeric,1) AS real, round(pct_sobre_teorico::numeric,0) AS pct "
        "FROM produccion.v_brief_insumo_control "
        "WHERE semana BETWEEN %s AND %s AND (teorico > 0 OR registrado > 0)", (desde9, sem)))

    D["despacho_ef"] = _recs(cat(
        "SELECT e.id_despacho AS id, e.titulo, e.destino, e.fecha_despacho::text AS fecha, "
        "  e.estado, e.n_contenedores AS cont, round(e.ocupacion_pct,0) AS ocup, "
        "  round(e.tn_total::numeric,1) AS tn, "
        "  round((SELECT sum(l.tn) FROM produccion.v_despacho_linea l "
        "         WHERE l.id_despacho = e.id_despacho)::numeric,1) AS tn_plan, "
        "  round((SELECT sum(t.kg) FILTER (WHERE NOT coalesce(t.sin_pesada,false))/1000.0 "
        "         FROM produccion.fact_despacho_ticket t "
        "         WHERE t.id_despacho = e.id_despacho)::numeric,1) AS tn_ticket, "
        "  round(e.tn_por_contenedor,2) AS tn_cont, e.tanques_usados AS tq, "
        "  e.tickets_cargados AS tk, "
        "  round(e.acidez_pond,2) AS acidez, round(e.azufre_pond,1) AS azufre, "
        "  round(e.fosforo_pond,1) AS fosforo, round(d.spec_acidez_max,2) AS lim_ac, "
        "  round(e.spec_azufre_max,0) AS lim_s, round(e.spec_fosforo_max,0) AS lim_p, "
        "  round(e.margen_azufre_pct,1) AS mg_s, round(e.margen_fosforo_pct,1) AS mg_p, "
        "  round(e.margen_pct,1) AS mg, e.dias_anticipacion AS antic, "
        "  e.n_lineas_exceden_stock AS exc, e.fuera_spec AS fs, e.aprob_direccion AS ap "
        "FROM produccion.v_brief_despacho_eficiencia e "
        "JOIN produccion.fact_despacho d USING (id_despacho) "
        "WHERE e.fecha_despacho >= (%s::date - 38) "
        "ORDER BY e.fecha_despacho", (sem,)))
    # foto al cierre: despachos posteriores a la semana informada no entran acá
    # (los futuros salen de "despachos", que alimenta compromisos y proyecciones)
    D["despacho_ef"] = [r for r in D["despacho_ef"] if str(r["fecha"])[:10] <= fin]

    # lab por batch: inicial (acidez cargada al armar el batch) y final (análisis del batch)
    D["lab_batches"] = _recs(cat(
        "SELECT p.ident, p.tipo_proceso AS tipo, p.fecha::text AS fecha, "
        "  round((p.real_kg/1000)::numeric,1) AS tn, l.fuente_lab AS fuente, "
        "  round((fb.parametros_proceso->>'acidez_pct')::numeric,2) AS acidez_ini, "
        "  round(l.acidez_pct::numeric,2) AS acidez, round(l.agua_pct::numeric,2) AS agua, "
        "  round(l.sedimentos_pct::numeric,2) AS sed, "
        "  round(l.azufre_ppm::numeric,0) AS s, round(l.fosforo_ppm::numeric,0) AS p, "
        "  produccion.fn_categoria_afe(l.azufre_ppm, l.fosforo_ppm) AS categoria "
        "FROM produccion.v_perf_reaccion p "
        "JOIN produccion.fact_batch_proceso fb ON fb.id_batch = p.id_batch "
        "LEFT JOIN produccion.v_reaccion_lab_final l ON l.id_batch = p.id_batch "
        "WHERE p.fecha >= (%s::date - 45) AND p.real_kg IS NOT NULL "
        "ORDER BY p.fecha, p.ident", (sem,)))
    D["lab_batches"] = [r for r in D["lab_batches"] if str(r["fecha"])[:10] <= fin]

    # calidad del MP que entra por portería (proxy del inicial de S y P: aún no se mide
    # por batch; ponderado por kg, últimos 45 días)
    D["mp_porteria"] = _recs(cat(
        "SELECT CASE WHEN producto ILIKE '%%SG%%' THEN 'AFE-SG' ELSE 'AG' END AS mp, "
        "  count(*) AS tk, count(*) FILTER (WHERE s_ppm IS NOT NULL) AS con_lab, "
        "  round(sum(tn)::numeric,0) AS tn, "
        "  round((sum(kg*s_ppm)/nullif(sum(kg) FILTER (WHERE s_ppm IS NOT NULL),0))::numeric,0) AS s, "
        "  round((sum(kg*p_ppm)/nullif(sum(kg) FILTER (WHERE p_ppm IS NOT NULL),0))::numeric,0) AS p, "
        "  round((sum(kg*acidez_pct)/nullif(sum(kg) FILTER (WHERE acidez_pct IS NOT NULL),0))::numeric,1) AS acidez "
        "FROM produccion.v_brief_porteria "
        "WHERE flujo = 'ENTRADA' AND fecha >= (%s::date - 45) "
        "  AND (producto ILIKE '%%SG%%' OR (familia = 'AG' AND producto NOT ILIKE 'AG-A%%')) "
        "GROUP BY 1", (sem,)))

    # metas del mes fijadas por dirección (editables en la app)
    _mm = _recs(cat(
        "SELECT to_char(mes,'YYYY-MM') AS mes, despachos_tn, fuera_spec_max_pct, "
        "  desgomado_tn, desgomado_ab_pct, are_tn, are_acidez_max, nota "
        "FROM produccion.meta_mensual "
        "WHERE mes = date_trunc('month', %s::date)::date", (sem,)))
    D["meta_mes"] = _mm[0] if _mm else None

    # calidad del registro de tiempos por etapa (últimas 4 semanas)
    D["etapa_calidad"] = _recs(cat(
        "SELECT etapa, count(*) AS n, "
        "  count(*) FILTER (WHERE sospecha_click AND real_h >= 0) AS clicks, "
        "  count(*) FILTER (WHERE real_h < 0) AS negativos, "
        "  count(*) FILTER (WHERE NOT sospecha_click AND real_h >= 0) AS ok, "
        "  round(avg(real_h) FILTER (WHERE NOT sospecha_click AND real_h >= 0)::numeric,1) AS h_ok, "
        "  round(avg(prog_h)::numeric,1) AS h_prog "
        "FROM produccion.v_perf_reaccion_etapa WHERE fecha >= (%s::date - 28) "
        "GROUP BY etapa", (sem,)))

    D["prod_mes"] = _recs(cat(
        "SELECT to_char(date_trunc('month',fecha::timestamp),'YYYY-MM') AS mes, tipo_proceso AS tipo, "
        "  count(*) AS n, round((sum(real_kg)/1000)::numeric,1) AS tn, "
        "  round((sum(formula_kg)/1000)::numeric,1) AS tn_form, "
        "  round(avg(utilizacion_pct)::numeric,0) AS uti, "
        "  max(extract(day from fecha)::int) AS ult "
        "FROM produccion.v_perf_reaccion WHERE fecha >= %s GROUP BY 1,2 ORDER BY 1,2", (mes0,)))

    # carga_p = horas de cronograma ANTERIORES a la etapa de reacción (la "carga"):
    # el prog_total_h del view suma las 5 etapas del cronograma (carga · reacción · reposo ·
    # decantación · acopio final); para que la tabla cierre por fila, el ciclo se arma como
    # reacción + reposo + (decantación+acopio) y la carga queda con la espera.
    D["batches"] = _recs(cat(
        "SELECT p.ident, p.tipo_proceso AS tipo, p.reactor, p.fecha::date::text AS fecha, "
        "  round(p.espera_arranque_h::numeric,1) AS espera, "
        "  round(p.prog_reaccion_h::numeric,1) AS reac_p, round(p.reaccion_h::numeric,1) AS reac_r, "
        "  round(p.prog_reposo_h::numeric,1) AS repo_p, round(p.reposo_h::numeric,1) AS repo_r, "
        "  round(p.prog_decantacion_h::numeric,1) AS dec_p, round(p.decantacion_h::numeric,1) AS dec_r, "
        "  round(p.prog_total_h::numeric,1) AS tot_p, round(p.ciclo_proceso_h::numeric,1) AS tot_r, "
        "  round(cr.prog_pre::numeric,1) AS carga_p, "
        "  round((p.formula_kg/1000)::numeric,1) AS tn_form, "
        "  round((p.real_kg/1000)::numeric,1) AS tn_real, "
        "  p.tiempos_confiables AS conf "
        "FROM produccion.v_perf_reaccion p "
        "LEFT JOIN LATERAL ("
        "  WITH et AS ("
        "    SELECT (s.value->>'Duración (h)')::numeric AS h, "
        "           lower(s.value->>'Etapa') AS nom, s.ordinality AS ord "
        "    FROM produccion.fact_batch_proceso fb "
        "    CROSS JOIN LATERAL jsonb_array_elements("
        "      CASE WHEN jsonb_typeof(fb.parametros_proceso->'cronograma')='array' "
        "           THEN fb.parametros_proceso->'cronograma' ELSE '[]'::jsonb END) "
        "      WITH ORDINALITY s(value, ordinality) "
        "    WHERE fb.id_batch = p.id_batch) "
        "  SELECT coalesce(sum(h) FILTER (WHERE ord < "
        "    (SELECT min(ord) FROM et WHERE nom LIKE '%%reacci%%')),0) AS prog_pre FROM et"
        ") cr ON true "
        "WHERE p.fecha BETWEEN %s AND %s ORDER BY p.fecha", (sem, fin)))

    _ag = cat(
        "SELECT round(coalesce(sum(l.tn),0)::numeric,1) AS tn "
        "FROM produccion.v_despacho_linea l "
        "JOIN produccion.fact_despacho d ON d.id_despacho = l.id_despacho "
        "WHERE l.producto_codigo = 'AG-E' AND d.fecha_despacho BETWEEN %s AND %s", (sem, fin))
    D["ag_e_despachado"] = float(_ag["tn"][0]) if _ag is not None and not _ag.empty else 0.0

    _pdia = cat(
        "SELECT tipo_proceso AS tipo, "
        "  to_char(date_trunc('month',fecha::timestamp),'YYYY-MM') AS mes_txt, "
        "  extract(day from fecha)::int AS dia, round((sum(real_kg)/1000)::numeric,3) AS tn "
        "FROM produccion.v_perf_reaccion "
        "WHERE fecha >= (date_trunc('month', %s::date) - interval '1 month')::date "
        "  AND real_kg IS NOT NULL GROUP BY 1,2,3 ORDER BY 1,2,3", (sem,))
    D["produccion_dia_tipo"] = {}
    if _pdia is not None and not _pdia.empty:
        _pdia = _pdia[(_pdia["mes_txt"] < fin[:7])
                      | ((_pdia["mes_txt"] == fin[:7]) & (_pdia["dia"] <= int(fin[8:10])))]
    if _pdia is not None and not _pdia.empty:
        for (t, m), g in _pdia.groupby(["tipo", "mes_txt"], sort=True):
            dias = [[int(r.dia), float(r.tn)] for r in g.itertuples()]
            D["produccion_dia_tipo"].setdefault(t, []).append(
                {"mes": m, "tn": round(sum(x[1] for x in dias), 1),
                 "ult": max(x[0] for x in dias), "dias": dias})

    # qué categoría de AFE-S entrega el desgomado, por mes (lab final de cada batch)
    _dcm = cat(
        "SELECT to_char(date_trunc('month', p.fecha::timestamp),'YYYY-MM') AS mes_txt, "
        "  coalesce(produccion.fn_categoria_afe(l.azufre_ppm, l.fosforo_ppm),'SIN LAB') AS categoria, "
        "  round((sum(p.real_kg)/1000)::numeric,1) AS tn "
        "FROM produccion.v_perf_reaccion p "
        "LEFT JOIN produccion.v_reaccion_lab_final l ON l.id_batch = p.id_batch "
        "WHERE p.tipo_proceso = 'DESGOMADO_ACUOSO' AND p.real_kg IS NOT NULL "
        "  AND p.fecha >= (date_trunc('month', %s::date) - interval '1 month')::date "
        "GROUP BY 1,2 ORDER BY 1,2", (sem,))
    D["desgomado_cat"] = []
    if _dcm is not None and not _dcm.empty:
        for m, g in _dcm.groupby("mes_txt", sort=True):
            D["desgomado_cat"].append(
                {"mes": m, "cats": {r.categoria: float(r.tn) for r in g.itertuples()}})

    # reparto semanal de horas de reactor entre desgomado y ARE
    D["reactor_horas"] = _recs(cat(
        "SELECT date_trunc('week', p.fecha::timestamp)::date::text AS semana, "
        "  p.tipo_proceso AS tipo, count(*) AS n, "
        "  round((sum(p.real_kg)/1000)::numeric,1) AS tn, "
        "  round(sum(coalesce(p.ciclo_proceso_h, p.prog_total_h))::numeric,0) AS horas "
        "FROM produccion.v_perf_reaccion p "
        "WHERE p.fecha >= (date_trunc('week', %s::timestamp) - interval '28 days')::date "
        "  AND p.real_kg IS NOT NULL "
        "GROUP BY 1,2 ORDER BY 1,2", (sem,)))

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
        "WITH b AS (SELECT proveedor, categoria, tn, semana FROM produccion.v_brief_porteria "
        "  WHERE familia='AFE' AND flujo='ENTRADA' AND semana BETWEEN %s AND %s) "
        "SELECT coalesce(proveedor,'—') AS prov, round(sum(tn),1) AS tn_tot, "
        "  round(sum(tn) FILTER (WHERE semana=%s),1) AS tn_sem, "
        "  round(100*sum(tn) FILTER (WHERE categoria IN ('A','B'))/nullif(sum(tn),0),0) AS pct_ab, "
        "  round(100*sum(tn) FILTER (WHERE categoria='D')/nullif(sum(tn),0),0) AS pct_d, "
        "  round(100*sum(tn) FILTER (WHERE categoria IN ('A','B') AND semana > (%s::date-21))"
        "        /nullif(sum(tn) FILTER (WHERE semana > (%s::date-21)),0),0) AS pct_ab3 "
        "FROM b GROUP BY 1 HAVING sum(tn) > 100 ORDER BY 2 DESC LIMIT 8",
        (desde9, sem, sem, sem, sem)))

    # salidas de báscula de la familia AFE en la semana, por producto: ventas
    # directas o movimientos internos hacia afuera del predio. La vista del stock
    # las clasifica como "interno" pero no las descuenta del proyectado, así que
    # acá se registran como salida para que la fila cierre con la física.
    D["sal_afe"] = _recs(cat(
        "SELECT produccion.fn_cod_producto_porteria(producto) AS cod, "
        "  round(sum(tn)::numeric,1) AS tn, count(*) AS camiones "
        "FROM produccion.v_brief_porteria "
        "WHERE flujo = 'SALIDA' AND familia = 'AFE' AND fecha BETWEEN %s AND %s "
        "GROUP BY 1", (sem, fin)))

    # ¿cuánto del desvío de AFE-S es medición y no faltante? Serie por corte semanal
    # del stock medido SIN rótulo de producto en tanques cuyo último rótulo fue AFE-S
    # (el radar midió, nadie asignó el producto: el balance no lo cuenta como AFE-S).
    D["med_rotulo"] = _recs(cat(
        "WITH cortes AS (SELECT generate_series(%s::date - 21, %s::date + 7, "
        "                interval '7 days')::timestamp AS t), "
        "snap AS (SELECT c.t, s.id_tanque, s.kg, s.id_producto "
        "  FROM cortes c CROSS JOIN LATERAL ("
        "    SELECT DISTINCT ON (fs.id_tanque) fs.id_tanque, fs.kg, fs.id_producto "
        "    FROM produccion.fact_stock_tanque fs "
        "    WHERE fs.medido_en < c.t AND coalesce(fs.kg,0) >= 0 "
        "    ORDER BY fs.id_tanque, fs.medido_en DESC, fs.id_stock DESC) s), "
        "cls AS (SELECT sp.t, sp.id_tanque, sp.kg FROM snap sp "
        "  WHERE sp.id_producto IS NULL AND sp.kg > 500 AND "
        "    (SELECT upper(btrim(dp.codigo_producto)) "
        "     FROM produccion.fact_stock_tanque f2 "
        "     JOIN produccion.dim_producto dp ON dp.id_producto = f2.id_producto "
        "     WHERE f2.id_tanque = sp.id_tanque AND f2.medido_en < sp.t "
        "     ORDER BY f2.medido_en DESC, f2.id_stock DESC LIMIT 1) = 'AFE-S') "
        "SELECT c.t::date::text AS corte, "
        "  round(coalesce(sum(g.kg)/1000.0, 0), 1) AS sr_tn, count(g.id_tanque) AS sr_tq "
        "FROM cortes c LEFT JOIN cls g ON g.t = c.t "
        "GROUP BY 1 ORDER BY 1", (sem, sem)))

    # frescura de las lecturas usadas en el corte de ESTA semana (tanques rotulados AFE-S)
    D["med_frescura"] = _recs(cat(
        "WITH corte AS (SELECT (%s::date + 7)::timestamp AS t), "
        "afes AS (SELECT s.* FROM corte c CROSS JOIN LATERAL ("
        "    SELECT DISTINCT ON (fs.id_tanque) fs.id_tanque, fs.kg, fs.id_producto, "
        "           fs.medido_en "
        "    FROM produccion.fact_stock_tanque fs "
        "    WHERE fs.medido_en < c.t AND coalesce(fs.kg,0) >= 0 "
        "    ORDER BY fs.id_tanque, fs.medido_en DESC, fs.id_stock DESC) s "
        "  JOIN produccion.dim_producto dp ON dp.id_producto = s.id_producto "
        "  WHERE upper(btrim(dp.codigo_producto)) = 'AFE-S') "
        "SELECT round((sum(a.kg * extract(epoch FROM c.t - a.medido_en)/3600.0) "
        "        / nullif(sum(a.kg),0))::numeric, 0) AS h_pond, "
        "  round(max(extract(epoch FROM c.t - a.medido_en)/3600.0)::numeric, 0) AS h_max, "
        "  count(*) AS n_tq, round((sum(a.kg)/1000.0)::numeric, 1) AS tn "
        "FROM afes a, corte c", (sem,)))

    # la fila AFE-S del stock único se corrige con el balance (despachos como salida)
    _b = next((r for r in D.get("balance_afe", []) if r["semana"] == sem), None)
    if _b:
        for r in D.get("desvio_producto", []):
            if r.get("cod") == "AFE-S":
                r.update({"ini": _b["ini"], "prod": _b["prod"], "e_in": _b["ing"],
                          "e_out": _b["desp"], "intr": _b["cons"], "unico": _b["esp"],
                          "medido": _b["med"], "desvio": _b["desvio"], "fix": True})
    for r in D.get("desvio_producto", []):
        # AG-E: la salida real son sus líneas de despacho (la mezcla que lo produce
        # no se registra como entrada; el único negativo queda explicado en el texto).
        # Con la salida corregida se recalculan único y desvío para que la fila cierre.
        if r.get("cod") == "AG-E":
            try:
                _u = round(float(r["ini"] or 0) + float(r["prod"] or 0)
                           + float(r["e_in"] or 0) - float(D.get("ag_e_despachado", 0.0)), 1)
                r.update({"e_out": D.get("ag_e_despachado", 0.0), "unico": _u,
                          "desvio": round(float(r["medido"] or 0) - _u, 1), "fixd": True})
            except Exception:
                r.update({"e_out": D.get("ag_e_despachado", 0.0), "fixd": True})
    # AFE que salió por báscula (venta directa / mov. interno): se suma a salidas
    # y se descuenta del único. AFE-S no: su fila ya viene armada del balance.
    _sal_afe = {r["cod"]: r for r in D.get("sal_afe", []) if r.get("cod")}
    for r in D.get("desvio_producto", []):
        _s = _sal_afe.get(r.get("cod"))
        if _s and r.get("cod") != "AFE-S" and not r.get("fix"):
            try:
                _u = round(float(r["unico"] or 0) - float(_s["tn"] or 0), 1)
                r.update({"e_out": round(float(r["e_out"] or 0) + float(_s["tn"] or 0), 1),
                          "unico": _u, "desvio": round(float(r["medido"] or 0) - _u, 1),
                          "fixs": True})
            except Exception:
                pass
    # TRAZABILIDAD: la columna interno de la vista no es la que usa stock_proy
    # (mezcla movimientos planificados y ejecutados según el producto). Para que
    # CADA fila cierre exacto — inicial + producido + ingresos − salidas − uso
    # interno = stock único — el uso interno se deriva como residual de la propia
    # fila. En AFE-S coincide con el consumo de reactores del balance.
    for r in D.get("desvio_producto", []):
        try:
            _d = round(float(r["ini"] or 0) + float(r["prod"] or 0) + float(r["e_in"] or 0)
                       - float(r["e_out"] or 0) - float(r["unico"] or 0), 1)
            r["intr"] = _d if abs(_d) >= 0.15 else 0.0
        except Exception:
            pass

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
