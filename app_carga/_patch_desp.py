# -*- coding: utf-8 -*-
"""Reescribe el motor de sugerencia de mezcla de despachos_section.py."""
import io, sys

P = "/sessions/rcw-01duz4x8r2fsqbh4zqfsidro/mnt/dashboard produccion/worms_supabase/app_carga/despachos_section.py"
s = io.open(P, encoding="utf-8").read()

# ---------------------------------------------------------------- 1) firma + docstring
OLD_SIG = '''def _sugerir(tks, prod_cod, litros_obj, spec, prods=None, l_base=None, maximizar=False,
             min_l=MIN_L_DESPACHO):
    """Propone la carga respetando la formulación: primero el componente base, después los AFE.

    Con maximizar=True busca el MÁXIMO de componente base (AG-E) que sigue cumpliendo la
    especificación: el AG-E es más barato que el AFE-S, así que conviene la mayor participación
    posible. La búsqueda es binaria sobre los litros de base; en cada punto se completa el
    objetivo con los AFE (AFE-S primero, mejor margen primero) y se evalúa la mezcla ponderada
    por kg, igual que el panel de specs. La masa sin laboratorio no se puede evaluar y queda
    afuera del promedio (el panel ya lo avisa).
    """'''
NEW_SIG = '''def _sugerir(tks, prod_cod, litros_obj, spec, prods=None, l_base=None, maximizar=False,
             min_l=MIN_L_DESPACHO, tol=0.0):
    """Propone la carga respetando la formulación: primero el componente base, después los AFE.

    Dos palancas compiten por el MISMO margen de spec y no se pueden maximizar a la vez:

    * los litros de componente base (AG-E), que es el más barato, y
    * la cantidad de AFE-S FEO que se logra colocar (el AFE-S bueno escasea y hay que
      reservarlo para los próximos despachos).

    Con maximizar=True se busca por bisección el máximo de base que la spec tolera; con
    l_base se fija a mano. Fijado el base, el resto se completa gastando el AFE-S de PEOR
    calidad primero: por cada tanque feo se toma, por bisección, el máximo de litros que
    deja el remanente todavía cerrable con los tanques buenos que quedan libres.

    tol es la fracción de desvío admitida sobre la spec (TOL_DESVIO = 10%): el mismo margen
    que el panel de Cumplimiento registra como desvío tolerado. Gastarlo es una decisión de
    negocio — mover stock feo — y queda asentado, no es un error silencioso.

    Los promedios son ponderados por kg (no por litros). La masa sin laboratorio no se puede
    evaluar y queda afuera del promedio (el panel ya lo avisa).
    """'''
assert s.count(OLD_SIG) == 1, "firma"
s = s.replace(OLD_SIG, NEW_SIG)

# ---------------------------------------------------------------- 2) cuerpo del motor
lin = s.split("\n")
i0 = [k for k, l in enumerate(lin) if l.startswith("    def _armar_mezcla(")]
assert len(i0) == 1, i0
i1 = [k for k, l in enumerate(lin) if l == "    return pd.DataFrame(out), msg"]
assert len(i1) == 1, i1
i0, i1 = i0[0], i1[0]

NUEVO = '''    def _cumple(lineas, _tol=0.0):
        """Promedios ponderados por kg de la masa medida vs los máximos de la spec.

        _tol es la fracción de desvío admitida (0 = spec estricta).
        """
        for c, lim in (("acidez", spec["acidez"]), ("agua_sedimento", spec["ays"]),
                       ("azufre", spec["azufre"]), ("fosforo", spec["fosforo"])):
            if not lim:
                continue
            num = den = 0.0
            for r, lts in lineas:
                if pd.isna(r[c]):
                    continue
                _dn = float(r["densidad"]) if pd.notna(r.get("densidad")) else 0.91
                kg = lts * _dn
                num += float(r[c]) * kg
                den += kg
            if den > 0 and num / den > float(lim) * (1.0 + _tol) + 1e-9:
                return False
        return True

    def _armar_mezcla(lb):
        """[(fila, litros)] con el base primero y el resto de MEJOR a peor.

        Es la COTA DE FACTIBILIDAD: la mejor mezcla alcanzable. Sirve para decidir cuánto
        base entra, no para armar la carga final (esa la arma _diluir).
        """
        out, acum = [], 0.0
        if formulado and lb > 0:
            out.append((rb, float(lb)))
            acum = float(lb)
        for i in d.index:
            r = d.loc[i]
            if acum >= litros_obj:
                break
            toma = min(float(r["litros_actual"]), litros_obj - acum)
            if toma < min_l * 0.2:
                continue
            out.append((r, toma))
            acum += toma
        return out, acum

    def _relleno(lineas, falta, excluir):
        """Completa 'falta' litros con los MEJORES tanques libres.

        Es el oráculo del llenado peor-primero: responde "si cargo este tanque feo, ¿me
        queda con qué rescatar la mezcla?".
        """
        out = list(lineas)
        f = float(falta)
        for i in d.index:
            if f <= 0.5:
                break
            if i in excluir:
                continue
            r = d.loc[i]
            t = min(float(r["litros_actual"]), f)
            if t < min_l * 0.2:
                continue
            out.append((r, t))
            f -= t
        return out

    def _diluir(lb, _tol):
        """Arma la carga gastando el AFE-S de PEOR calidad primero.

        Recorre los diluyentes de peor a mejor y a cada uno le toma, por bisección, el
        máximo de litros que deja el remanente todavía cerrable con los buenos libres.
        (La lógica anterior cargaba primero los k mejores hasta que la spec cerraba, y por
        eso los tanques feos se quedaban sistemáticamente sin entrar.)
        """
        lineas, acum, usados = [], 0.0, set()
        if formulado and lb > 0:
            lineas.append((rb, float(lb)))
            acum = float(lb)
        for i in d_peor.index:
            if acum >= litros_obj - 0.5:
                break
            r = d.loc[i]
            tope = min(float(r["litros_actual"]), litros_obj - acum)
            if tope < min_l * 0.2:
                continue
            ex = set(usados)
            ex.add(i)
            _resto = litros_obj - acum
            lo, hi = 0.0, tope
            if _cumple(_relleno(lineas + [(r, tope)], _resto - tope, ex), _tol):
                lo = tope                                   # entra entero
            elif _cumple(_relleno(lineas, _resto, ex), _tol):
                for _ in range(22):                         # entra parcial: cuánto aguanta
                    mid = (lo + hi) / 2.0
                    if _cumple(_relleno(lineas + [(r, mid)], _resto - mid, ex), _tol):
                        lo = mid
                    else:
                        hi = mid
            toma = float(int(lo // 10) * 10)                # redondeo abajo: margen, no exceso
            if toma >= min_l * 0.2:
                lineas.append((r, toma))
                acum += toma
                usados.add(i)
        if acum < litros_obj - 0.5:                         # completar con los buenos
            lineas = _relleno(lineas, litros_obj - acum, usados)
            acum = sum(l for _, l in lineas)
        return lineas, acum

    notas = []
    lb = 0.0
    if formulado:
        if maximizar:
            tope = min(hay, float(litros_obj))
            if tope <= 0:
                notas.append("el tanque de %s (%s) no tiene stock medido: no se puede maximizar, "
                             "poné los litros a mano" % (base_cod, rb["nombre"]))
            elif _cumple(_armar_mezcla(tope)[0], tol):
                lb = tope
                notas.append("entra TODO el stock de %s (%s L) y la mezcla sigue en spec"
                             % (base_cod, "{:,.0f}".format(tope)))
            elif not _cumple(_armar_mezcla(0.0)[0], tol):
                notas.append("ni siquiera sin %s la mezcla cumple la spec con estos AFE: "
                             "cambiá los tanques diluyentes" % base_cod)
            else:
                lo, hi = 0.0, tope
                for _ in range(30):
                    mid = (lo + hi) / 2.0
                    if _cumple(_armar_mezcla(mid)[0], tol):
                        lo = mid
                    else:
                        hi = mid
                lb = float(int(lo // 10) * 10)  # redondeo hacia abajo: margen, no exceso
        else:
            lb = float(l_base) if l_base else (min(hay, litros_obj) if hay > 0 else 0.0)
            lb = max(0.0, min(lb, float(litros_obj)))
            if lb <= 0 and not l_base:
                notas.append("el tanque de %s (%s) está sin medición: poné los litros a mano"
                             % (base_cod, rb["nombre"]))
            elif hay > 0 and lb > hay + 0.5:
                notas.append("%s tiene %s L y se piden %s L"
                             % (rb["nombre"], "{:,.0f}".format(hay), "{:,.0f}".format(lb)))

    if d.empty:
        lineas, acum = _armar_mezcla(lb)
    else:
        lineas, acum = _diluir(lb, tol)
    if not lineas:
        return pd.DataFrame(), "No se pudo armar una mezcla con el stock disponible."
    out = [_linea(r, lts) for r, lts in lineas]
    falta = litros_obj - acum

    _dil = [(r, lts) for r, lts in lineas
            if str(r.get("producto_principal", "")).strip().upper() in cod_dil]
    _ldil = sum(lts for _, lts in _dil)
    _feo = sum(lts for r, lts in _dil if _score(r) > 1.0)
    _cal = (sum(_score(r) * lts for r, lts in _dil) / _ldil) if _ldil else 0.0

    msg = "Propuesta con %d tanque(s) — %s L." % (len(out), "{:,.0f}".format(acum))
    if formulado and maximizar:
        msg += (" Máximo %s que cumple la spec: %s L (%.1f%% de la carga)."
                % (base_cod, "{:,.0f}".format(lb), (100.0 * lb / acum if acum else 0.0)))
    elif formulado:
        msg += " La primera línea es el componente %s; el resto son AFE (primero AFE-S)." % base_cod
    if _ldil > 0:
        msg += (" Diluyentes: se gasta primero el de PEOR calidad — entran %s L que sueltos "
                "estarían fuera de spec (calidad media usada %.2f, donde 1,00 = el límite; "
                "cuanto más alto, más stock feo se colocó)."
                % ("{:,.0f}".format(_feo), _cal))
    if tol > 0:
        msg += (" Se habilitó hasta %.0f%% de desvío sobre la spec: el panel de Cumplimiento "
                "de abajo muestra y registra el desvío real." % (tol * 100.0))
    if not _cumple(lineas, tol):
        msg += " ⚠️ Ni así cierra la spec con el stock disponible: revisá los tanques"
        msg += (" o bajá los litros de %s." % base_cod) if formulado else "."
    if falta > 1:
        msg += " Faltan %s L: no alcanza el stock." % "{:,.0f}".format(falta)
    if notas:
        msg += " Ojo: " + "; ".join(notas) + "."
    return pd.DataFrame(out), msg


def _tradeoff(tks, prod_cod, litros_obj, spec, prods=None, tol=0.0, pasos=8,
              min_l=MIN_L_DESPACHO):
    """Simula el canje entre litros de componente base y AFE-S feo colocado.

    Devuelve una fila por nivel de base: cuánto AFE fuera de spec entra, qué calidad media
    de AFE se consume y dónde quedan los parámetros finales. Los dos objetivos compiten por
    el mismo margen, así que la tabla es la que decide, no la intuición.
    """
    fam = _familia(prod_cod, prods)
    if len(fam) < 2:
        return pd.DataFrame()
    up = tks["producto_principal"].astype(str).str.strip().str.upper()
    b = tks[up == fam[0]]
    if b.empty:
        return pd.DataFrame()
    hay = float(b["litros_actual"].fillna(0).max())
    tope = min(hay, float(litros_obj))
    if tope <= 0:
        return pd.DataFrame()

    def _sc(r):
        rr = []
        for c, lim in (("acidez", spec["acidez"]), ("agua_sedimento", spec["ays"]),
                       ("azufre", spec["azufre"]), ("fosforo", spec["fosforo"])):
            if lim and pd.notna(r[c]):
                rr.append(float(r[c]) / float(lim))
        return max(rr) if rr else 0.90

    _cols = ["etq", "producto_principal", "densidad", "acidez", "agua_sedimento",
             "azufre", "fosforo"]
    filas = []
    for k in range(1, int(pasos) + 1):
        lb = float(int((tope * k / float(pasos)) // 10) * 10)
        if lb <= 0:
            continue
        sug, _m = _sugerir(tks, prod_cod, litros_obj, spec, prods, lb,
                           maximizar=False, min_l=min_l, tol=tol)
        if sug.empty:
            continue
        m = sug[["Tanque", "Litros"]].merge(tks[_cols], left_on="Tanque", right_on="etq",
                                            how="left")
        m["_kg"] = m["Litros"] * m["densidad"].fillna(0.91)
        prom, ok = {}, True
        for c, lim in (("acidez", spec["acidez"]), ("agua_sedimento", spec["ays"]),
                       ("azufre", spec["azufre"]), ("fosforo", spec["fosforo"])):
            _v = m[pd.notna(m[c])]
            _kg = float(_v["_kg"].sum())
            prom[c] = (float((_v[c] * _v["_kg"]).sum()) / _kg) if _kg > 0 else None
            if lim and prom[c] is not None and prom[c] > float(lim) * (1.0 + tol) + 1e-9:
                ok = False
        _tot = float(m["Litros"].sum())
        if _tot < float(litros_obj) - 1.0:
            ok = False
        _d = m[m["producto_principal"].astype(str).str.strip().str.upper() != fam[0]].copy()
        _ld = float(_d["Litros"].sum())
        _feo, _cal = 0.0, 0.0
        if _ld > 0:
            _d["_s"] = _d.apply(_sc, axis=1)
            _feo = float(_d[_d["_s"] > 1.0]["Litros"].sum())
            _cal = float((_d["_s"] * _d["Litros"]).sum() / _ld)
        filas.append({
            "%s (L)" % fam[0]: round(lb, 0),
            "%s (%%)" % fam[0]: round(100.0 * lb / _tot, 1) if _tot else 0.0,
            "AFE feo (L)": round(_feo, 0),
            "Calidad AFE usada": round(_cal, 2),
            "Acidez %": round(prom["acidez"], 2) if prom["acidez"] is not None else None,
            "AyS %": round(prom["agua_sedimento"], 2) if prom["agua_sedimento"] is not None else None,
            "Azufre ppm": round(prom["azufre"], 1) if prom["azufre"] is not None else None,
            "Fósforo ppm": round(prom["fosforo"], 1) if prom["fosforo"] is not None else None,
            "Tanques": int(len(m)),
            "Cierra": "✅" if ok else "❌",
        })
    return pd.DataFrame(filas)'''

lin[i0:i1 + 1] = NUEVO.split("\n")
s = "\n".join(lin)
io.open(P, "w", encoding="utf-8").write(s)
print("ok bytes=%d" % len(s))
