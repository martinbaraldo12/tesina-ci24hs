"""
Corre el pipeline completo en orden.

    python run_all.py            # todo, desde el paso 1
    python run_all.py --desde 4  # retoma desde el paso 4 (ej. sin volver a leer los Excel)

Si datos_crudos/ no tiene los Excel intradiarios, usa los datos procesados de datos_procesados/ (la salida de
los pasos 1 y 3 sobre esos Excel) y corre todo lo demás. Con --exportar-procesados, al terminar copia la salida
de los pasos 1 y 3 a datos_procesados/ (para actualizarla después de correr con los Excel).
"""
import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
PASOS = [
    ("01_manifest.py", "Identifica la rueda de cada archivo y la asigna a un bloque"),
    ("02_caucion.py", "Carga la caución diaria"),
    ("03_build_bars.py", "Reconstruye las barras de 15 minutos (el paso más lento: lee todos los Excel)"),
    ("04_spread_signal.py", "Calcula spread, filtros de calidad y señales"),
    ("05_sizing.py", "Dimensiona las operaciones (inventario, reinversión de pesos, neto a cubrir)"),
    ("06_modelo_a_pandas.py", "Modelo A (pandas)"),
    ("07_modelo_b_vectorbt.py", "Modelo B (VectorBT) + sensibilidad a slippage"),
    ("08_comparacion.py", "Reconciliación A vs B"),
    ("09_estadistica.py", "Tests de significancia estadística"),
    ("10_numeros.py", "Junta las cifras finales en output/numeros.json"),
    ("11_charts.py", "Genera los gráficos en output/"),
    ("12_escalabilidad.py", "Escalabilidad: más monto, con y sin límite de liquidez de la pata CI"),
    ("13_ejecucion.py", "Ejecución, costo por especie, latencia y mapa de dónde falla"),
    ("14_robustez.py", "Robustez y sensibilidad (período, especies, convenciones, filtros, sizing, grilla)"),
    ("15_versiones.py", "Versiones 1 y 2 (anteriores) y 3 (definitiva), bases de capital, robustez de la V3"),
    ("../scripts_web/armar_pagina.py", "Página web del backtest (output/Backtest_CI24hs.html)"),
]

ap = argparse.ArgumentParser()
ap.add_argument("--desde", type=int, default=1, help="número de paso desde el que arrancar (1-16)")
ap.add_argument("--exportar-procesados", action="store_true",
                help="al terminar, copia la salida de los pasos 1 y 3 a datos_procesados/")
args = ap.parse_args()

RAW = Path(os.environ.get("TESIS_DATOS_CRUDOS", BASE / "datos_crudos"))
DATA = Path(os.environ.get("TESIS_DATA_DIR", BASE / "data"))
PROC = BASE / "datos_procesados"
# salida de los pasos 1 (manifest) y 3 (barras, registros de precio con su hora y ticks)
SALIDA_PASOS_1_Y_3 = ["manifest.json", "build_bars_summary.csv", "ticks.csv", "bars_15min", "eventos_precio"]


def copiar(origen, destino):
    destino.mkdir(parents=True, exist_ok=True)
    for nombre in SALIDA_PASOS_1_Y_3:
        o = origen / nombre
        if o.is_dir():
            shutil.copytree(o, destino / nombre, dirs_exist_ok=True)
        elif o.exists():
            shutil.copy2(o, destino / nombre)


saltar = set()
hay_excel = RAW.exists() and any(f.suffix.lower() == ".xlsx" for f in RAW.iterdir())
if not hay_excel and args.desde <= 3:
    if not (PROC / "manifest.json").exists():
        sys.exit(f"No hay Excel intradiarios en {RAW} ni datos procesados en {PROC}. Ver README.")
    print("No hay Excel intradiarios en datos_crudos/: se usan los datos procesados de datos_procesados/ "
          "(salida de los pasos 1 y 3) y se saltean esos dos pasos.")
    copiar(PROC, DATA)
    saltar = {1, 3}

t0 = time.time()
for i, (script, desc) in enumerate(PASOS, start=1):
    if i < args.desde:
        continue
    if i in saltar:
        print(f"\nPaso {i}/{len(PASOS)} — {script}: se usa datos_procesados/")
        continue
    print(f"\n{'=' * 80}\nPaso {i}/{len(PASOS)} — {script}: {desc}\n{'=' * 80}", flush=True)
    t = time.time()
    r = subprocess.run([sys.executable, str(BASE / "scripts" / script)], cwd=BASE)
    if r.returncode != 0:
        sys.exit(f"\nFalló el paso {i} ({script}). Revisá el error de arriba; "
                 f"después podés retomar con: python run_all.py --desde {i}")
    print(f"-> paso {i} ok ({time.time() - t:.0f} s)")

if args.exportar_procesados:
    copiar(DATA, PROC)
    print(f"Salida de los pasos 1 y 3 copiada a {PROC}.")

print(f"\nListo en {time.time() - t0:.0f} s. Resultados en data/ y output/.")
