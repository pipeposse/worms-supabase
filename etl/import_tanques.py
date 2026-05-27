"""
import_tanques.py — carga tanques.xlsx a produccion como dim_tanque + dim_tanque_producto.
Mapea los nombres de productos (texto libre, desprolijo) a los códigos del catálogo dim_producto, por id.
Dry-run por defecto: imprime el mapeo y genera el SQL (no escribe en la base por sí mismo).
"""
import argparse, re
import pandas as pd

PROD_ID = {
    'AFE-AL':32,'AFE-G':30,'AFE-P':33,'AFE-S':1,'AFE-SG':2,
    'AG-A':3,'AG-B':4,'AG-C':5,'AG-D':6,'AG-E':7,'AG-PES':52,'AGUA-PROC':1466,
    'ARE-A':10,'ARE-A-ANIMAL':42,'ARE-B':41,
    'BORRA-A':14,'BORRA-ANIMAL':50,'BORRA-B':15,'BORRA-PES':51,
    'EMULSION':25,'FONDO-TK':56,'FUEL':24,'GLICERINA':53,'GLICERINA-FE':54,
    'POLIGLICEROL':18,'SEBO-A-1RA':43,'SEBO-A-2DA':45,'SEBO-B-1RA':44,'SEBO-B-2DA':46,
    'SEBO-C-2DA':47,'TCO':34,
}
ABBR = {
    'Plataforma 1 (BPV)':'BPV','Plataforma 2 (BPN)':'BPN','Exportación':'EXP',
    'Piletas (acopio)':'PIL','Piletas - bachas (Acopio)':'PILB','Reactores (Acopio)':'RXA',
    'Reactores (Proceso)':'RXP','Consumibles Reactores':'CONS','Bachas (acopio)':'BAA','Bachas (proceso)':'BAP',
}

def extract_codes(cell):
    if cell is None: return []
    s = str(cell).strip()
    if s.lower() in ('', '-', 'nan', 'none'): return []
    S = s.upper().replace('°', ' ')
    out = []
    def add(c):
        if c in PROD_ID and c not in out: out.append(c)
    for m in re.finditer(r'AFE\s*\(([^)]*)\)', S):              # AFE(S/G/SG/AL/TCO)
        for part in re.split(r'[/,]', m.group(1)):
            part = part.strip()
            if part == 'TCO': add('TCO')
            elif part in ('SG','S','G','AL','P'): add('AFE-'+part)
    for m in re.finditer(r'AG\s*\(([^)]*)\)', S):                # AG(A/C/E), AG (B/C/D)
        for part in re.split(r'[/,]', m.group(1)):
            part = part.strip()
            if part in ('A','B','C','D','E'): add('AG-'+part)
            elif 'PES' in part: add('AG-PES')
    for m in re.finditer(r'\bAG\s*-?\s*([ABCDE])\b', S):         # AG-D, AG - C
        add('AG-'+m.group(1))
    if re.search(r'\bAG\s*[-(]?\s*PES', S): add('AG-PES')
    if 'ARE' in S:                                              # ARE vegetal B / animal
        if 'AN' in S: add('ARE-A-ANIMAL')
        if re.search(r'\(V\)|\bV\b|-\s*B|\bB\b', S): add('ARE-B')
    if 'SEBO' in S: add('SEBO-C-2DA')                           # "Sebo 2°C"
    if 'GLICERINA' in S: add('GLICERINA')
    if 'FUEL' in S: add('FUEL')
    if 'EMULSI' in S: add('EMULSION')
    if 'BORRA ANIMAL' in S: add('BORRA-ANIMAL')
    if re.search(r'\bAGUA\b', S): add('AGUA-PROC')
    if re.search(r'\bTCO\b', S): add('TCO')
    return out

def slug(s):
    s = re.sub(r'[^A-Za-z0-9]+', '-', str(s).strip()).strip('-').upper()
    return s

def sql_lit(v):
    if v is None or (isinstance(v, float) and pd.isna(v)): return 'NULL'
    if isinstance(v, bool): return 'TRUE' if v else 'FALSE'
    if isinstance(v, (int, float)): return repr(v)
    return "'" + str(v).replace("'", "''") + "'"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--xlsx', required=True)
    ap.add_argument('--out', default='import_tanques.sql')
    a = ap.parse_args()
    df = pd.read_excel(a.xlsx, sheet_name='Tanques WORMS', header=0)
    df.columns = [str(c).replace('\n',' ').strip() for c in df.columns]
    df = df.rename(columns={
        'Sector':'sector','Tanque':'tanque','Posee radar':'radar',
        'Variación de nivel':'variacion','Método medición':'metodo',
        'Producto de mayor probab.':'prod_ppal','Otros productos que puede almacenar':'otros'})
    df = df[df['sector'].notna() & df['tanque'].notna()]
    df = df[~df['tanque'].astype(str).str.contains('Fuera de uso', case=False, na=False)]

    rows, links, rep = [], [], []
    usados = set()
    for _, r in df.iterrows():
        sector = str(r['sector']).strip()
        nombre = str(r['tanque']).strip()
        abbr = ABBR.get(sector, 'TQ')
        codigo = f"{abbr}-{slug(nombre)}"
        n = 2
        base = codigo
        while codigo in usados:
            codigo = f"{base}-{n}"; n += 1
        usados.add(codigo)
        radar = str(r['radar']).strip().lower().startswith('s')
        variacion = str(r['variacion']).strip().upper() if pd.notna(r['variacion']) else None
        metodo = str(r['metodo']).strip() if pd.notna(r['metodo']) and str(r['metodo']).strip() != '-' else None
        cap = None
        mcap = re.search(r'(\d{4,6})\s*L', nombre)
        if mcap: cap = float(mcap.group(1))
        ppal_codes = extract_codes(r['prod_ppal'])
        otros_codes = extract_codes(r['otros'])
        all_codes = list(dict.fromkeys(ppal_codes + otros_codes))
        ppal_id = PROD_ID[ppal_codes[0]] if len(ppal_codes) == 1 else None
        rows.append({
            'codigo':codigo,'nombre':nombre,'sector':sector,'radar':radar,'variacion':variacion,
            'metodo':metodo,'cap':cap,'ppal_id':ppal_id,
            'ppal_txt':(str(r['prod_ppal']).strip() if pd.notna(r['prod_ppal']) else None),
            'otros_txt':(str(r['otros']).strip() if pd.notna(r['otros']) else None)})
        for c in all_codes:
            links.append((codigo, PROD_ID[c], c in ppal_codes))
        rep.append((codigo, nombre[:26], sector[:18], ppal_codes[0] if len(ppal_codes)==1 else ('—' if not ppal_codes else 'multi'),
                    ",".join(all_codes) or '—'))

    # ---- dry-run ----
    print(f"=== DRY-RUN tanques · {len(rows)} tanques · {len(links)} vínculos tanque-producto ===")
    print("{:<22} {:<27} {:<19} {:<8} {}".format('codigo','nombre','sector','ppal','productos(ids)'))
    for x in rep:
        print("{:<22} {:<27} {:<19} {:<8} {}".format(*x))
    sin_ppal = [x for x in rows if x['ppal_id'] is None]
    print(f"\nTanques sin producto principal único (multi/ambiguo, queda en texto): {len(sin_ppal)}")

    # ---- SQL ----
    out = ["-- Tanques WORMS (idempotente)."]
    cols = "codigo,nombre,sector,posee_radar,variacion_nivel,metodo_medicion,capacidad_litros,id_producto_principal,producto_principal_txt,otros_productos_txt"
    for x in rows:
        vals = ",".join([
            sql_lit(x['codigo']), sql_lit(x['nombre']), sql_lit(x['sector']),
            sql_lit(x['radar']), sql_lit(x['variacion']), sql_lit(x['metodo']),
            sql_lit(x['cap']), (str(x['ppal_id']) if x['ppal_id'] else 'NULL'),
            sql_lit(x['ppal_txt']), sql_lit(x['otros_txt'])])
        out.append(f"INSERT INTO produccion.dim_tanque ({cols}) VALUES ({vals}) ON CONFLICT (codigo) DO NOTHING;")
    for codigo, pid, esp in links:
        out.append(
            "INSERT INTO produccion.dim_tanque_producto (id_tanque,id_producto,es_principal) "
            f"SELECT t.id_tanque,{pid},{ 'TRUE' if esp else 'FALSE'} FROM produccion.dim_tanque t WHERE t.codigo={sql_lit(codigo)} "
            "ON CONFLICT (id_tanque,id_producto) DO NOTHING;")
    open(a.out,'w',encoding='utf-8').write("\n".join(out))
    print(f"\nSQL -> {a.out} ({sum(len(o) for o in out):,} chars, {len(out)} sentencias)")

if __name__ == '__main__':
    main()
