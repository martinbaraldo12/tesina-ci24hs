"""
Paso 12 — Escalabilidad: el mismo bot con más monto (escenario base de caución).

Se escalan en la misma proporción el capital, el inventario por especie (10% del capital) y el faltante
de pesos que cubre el operador (100% del capital). Dos versiones:

  A) Sin límite de liquidez: el backtest supone que siempre se ejecuta al precio observado, cualquiera
     sea el tamaño. Sirve de referencia: el resultado en % no debería cambiar.
  B) Con límite de liquidez: cada orden no puede superar una fracción (PARTICIPACION) del volumen
     promedio por bucket de la pata CI de esa especie, que es la pata más fina. El volumen diario sale
     del campo VOLUMEN del export (total del día en nominales); se pasa a pesos con el precio de la pata
     (los bonos y ON cotizan cada 100 de valor nominal) y se toma la mediana de la muestra por especie.

La mediana de la muestra incluye ruedas posteriores a cada operación: usarla para fijar el tope es un supuesto
simplificador. Para medirlo, se guarda también un tope sin información futura: para cada rueda, la mediana del
volumen diario CI de hasta VENTANA_EXANTE ruedas anteriores de la muestra (entre bloques, las últimas del bloque
anterior). La primera rueda de la muestra no tiene historia y usa su propio volumen (única excepción).

Salidas: data/escalabilidad.csv, data/liquidez_ci.csv, data/liquidez_ci_diaria.csv
"""
import glob
import importlib.util
import os
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import DATA, BASE, CATEGORIA, PARTICIPACION

spec = importlib.util.spec_from_file_location("sizing", os.path.join(os.path.dirname(__file__), "05_sizing.py"))
sizing = importlib.util.module_from_spec(spec); spec.loader.exec_module(sizing)

CAPITALES = [1e6, 5e6, 10e6, 50e6, 100e6, 500e6]
INV_FRAC, LIM_FRAC = 0.10, 1.00        # inventario por especie y faltante, como fracción del capital
# PARTICIPACION (common.py): máximo de una orden como fracción del volumen promedio por bucket de la pata CI

# ---- liquidez de la pata CI por especie ----
bars = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(f"{DATA}/bars_15min/*.parquet"))], ignore_index=True)
bars = bars[(bars["vencimiento"] == "CI") & bars["simbolo"].isin(CATEGORIA)]
dia = bars.groupby(["fecha", "simbolo"]).agg(vol_nominal=("volumen_dia", "last"), precio=("close", "median"),
                                             buckets=("bucket", "nunique")).reset_index()
dia["factor"] = np.where(dia["simbolo"].map(CATEGORIA) == "RF", 100.0, 1.0)
dia["vol_pesos"] = dia["vol_nominal"] * dia["precio"] / dia["factor"]
liq = dia.groupby("simbolo").agg(vol_diario_ci_mediana=("vol_pesos", "median"),
                                 buckets_por_rueda=("buckets", "median")).reset_index()
liq["vol_por_bucket"] = liq["vol_diario_ci_mediana"] / liq["buckets_por_rueda"]
liq["tope_orden"] = PARTICIPACION * liq["vol_por_bucket"]
liq.to_csv(f"{DATA}/liquidez_ci.csv", index=False)
print("Liquidez de la pata CI (pesos):")
print(liq.assign(**{c: (liq[c] / 1e6).round(2) for c in ["vol_diario_ci_mediana", "vol_por_bucket", "tope_orden"]})
      .to_string(index=False))
tope = dict(zip(liq["simbolo"], liq["tope_orden"]))

# ---- tope sin información futura (lo usa el paso 15) ----
VENTANA_EXANTE = 5
dia = dia.sort_values(["simbolo", "fecha"]).reset_index(drop=True)
dia["vol_prev_mediana"] = dia.groupby("simbolo")["vol_pesos"].transform(
    lambda x: x.shift(1).rolling(VENTANA_EXANTE, min_periods=1).median())
dia["sin_historia"] = dia["vol_prev_mediana"].isna()
dia.loc[dia["sin_historia"], "vol_prev_mediana"] = dia.loc[dia["sin_historia"], "vol_pesos"]
dia["tope_exante"] = PARTICIPACION * dia["vol_prev_mediana"] / dia["simbolo"].map(liq.set_index("simbolo")["buckets_por_rueda"])
dia["tope_muestra"] = dia["simbolo"].map(tope)
dia.to_csv(f"{DATA}/liquidez_ci_diaria.csv", index=False)
print("\nTope sin información futura / tope con la mediana de la muestra (mediana por especie):")
print((dia["tope_exante"] / dia["tope_muestra"]).groupby(dia["simbolo"]).median().round(2).to_string())

sig = pd.read_parquet(f"{DATA}/spread_signal.parquet")
sb = sig[sig["escenario"] == BASE]
filas = []
for version, tp in [("A) sin límite de liquidez", None), (f"B) orden <= {PARTICIPACION:.0%} del volumen CI por bucket", tope)]:
    for C in CAPITALES:
        ev, cob = sizing.dimensionar(sb, inventario=INV_FRAC * C, limite=LIM_FRAC * C, capital=C, tope_orden=tp)
        pnl = ev["pnl_bono"].sum() + cob["pnl_caucion"].sum()
        part = ev["nocional"] / ev["simbolo"].map(liq.set_index("simbolo")["vol_por_bucket"])
        filas.append({"version": version, "capital": C, "operaciones": len(ev), "pnl": pnl,
                      "retorno_pct": pnl / C * 100, "nocional_operado": ev["nocional"].sum(),
                      "participacion_media_pct": part.mean() * 100, "participacion_max_pct": part.max() * 100,
                      "compensado_pct": cob["compensado"].sum() / cob["pesos_tomadoras"].sum() * 100})
res = pd.DataFrame(filas)
res.to_csv(f"{DATA}/escalabilidad.csv", index=False)
print("\nEscalabilidad (escenario base):")
print(res.assign(capital=(res["capital"] / 1e6).map(lambda v: f"{v:g}M"), pnl=res["pnl"].round(0),
                 nocional_operado=(res["nocional_operado"] / 1e6).round(1))
      .round(2).to_string(index=False))
