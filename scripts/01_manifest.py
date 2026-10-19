"""
Paso 1 — Manifiesto: identifica la rueda de cada archivo intradiario y la asigna a un bloque.

Lee la fecha del primer registro de cada .xlsx de la carpeta de datos crudos (el nombre del
archivo es la fecha de exportación, no la de la rueda). Clasifica cada archivo en:
  en_bloque        -> la rueda cae dentro de una de las 4 ventanas del diseño (se usa)
  fuera_de_bloque  -> rueda fuera de las ventanas (se excluye)
  vacio_corrupto   -> archivo sin registros (se excluye)
  duplicado        -> otra exportación de una rueda ya presente (se conserva la más grande)
Salida: data/manifest.json
"""
import json
import os
import sys
from python_calamine import CalamineWorkbook

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import RAW, DATA, BLOQUES, EXCLUIR_RUEDAS


def en_que_bloque(fecha):
    for nombre, (ini, fin) in BLOQUES.items():
        if ini <= fecha <= fin:
            return nombre
    return None


def fecha_de(path):
    hoja = CalamineWorkbook.from_path(path).get_sheet_by_name("Especies")
    filas = hoja.iter_rows()
    next(filas, None)                      # encabezado
    primera = next(filas, None)
    return str(primera[1])[:10] if primera and primera[1] else None


if not RAW.exists():
    sys.exit(f"No encuentro la carpeta de datos crudos: {RAW}\n"
             "Copiá ahí los .xlsx intradiarios y caucion_a3.csv (ver README).")

archivos = sorted(f for f in os.listdir(RAW) if f.lower().endswith(".xlsx"))
manifest = []
for fn in archivos:
    fecha = fecha_de(RAW / fn)
    if fecha is None:
        manifest.append({"file": fn, "fecha": None, "bloque": None, "status": "vacio_corrupto"})
        continue
    bloque = en_que_bloque(fecha)
    status = "en_bloque" if bloque else "fuera_de_bloque"
    if fecha in EXCLUIR_RUEDAS:
        status = "excluida"
    manifest.append({"file": fn, "fecha": fecha, "bloque": bloque, "status": status,
                     "motivo": EXCLUIR_RUEDAS.get(fecha), "bytes": os.path.getsize(RAW / fn)})

# si una rueda aparece en más de un archivo, se conserva el de mayor tamaño
por_fecha = {}
for m in manifest:
    if m["fecha"]:
        por_fecha.setdefault(m["fecha"], []).append(m)
for fecha, ms in por_fecha.items():
    for m in sorted(ms, key=lambda x: -x["bytes"])[1:]:
        m["status"] = "duplicado"

with open(DATA / "manifest.json", "w") as f:
    json.dump(manifest, f, indent=2, ensure_ascii=False)

usables = [m for m in manifest if m["status"] == "en_bloque"]
print(f"Archivos: {len(manifest)} | usables: {len(usables)}")
for nombre, (ini, fin) in BLOQUES.items():
    dias = sorted(m["fecha"] for m in usables if m["bloque"] == nombre)
    print(f"  {nombre} [{ini} a {fin}]: {len(dias)} ruedas")
for st in ["excluida", "fuera_de_bloque", "vacio_corrupto", "duplicado"]:
    xs = [m for m in manifest if m["status"] == st]
    if xs:
        det = sorted(m["fecha"] or m["file"] for m in xs)
        print(f"Excluidos ({st}): {len(xs)} -> {det}")
