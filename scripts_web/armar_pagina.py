"""Arma la página web del backtest (un solo .html con datos y motor adentro).

Uso:  python scripts_web/armar_pagina.py [destino.html]
Requiere haber corrido el pipeline (run_all.py) para tener data/spread_signal.parquet.
"""
import subprocess
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
BASE = AQUI.parent
destino = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE / "output" / "Backtest_CI24hs.html"
datos = destino.with_suffix(".datos.json")

subprocess.run([sys.executable, str(AQUI / "exportar_datos.py"), str(datos)], check=True)
html = (AQUI / "pagina.html").read_text(encoding="utf8")
html = html.replace("__MOTOR__", (AQUI / "motor.js").read_text(encoding="utf8"))
html = html.replace("__DATOS__", datos.read_text(encoding="utf8"))
datos.unlink()
destino.write_text(html, encoding="utf8")
print(f"{destino}: {destino.stat().st_size / 1024:.0f} KB")
