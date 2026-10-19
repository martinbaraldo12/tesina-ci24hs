"""
Paso 13 — Supuestos de ejecución, costos por especie y latencia (escenario base de caución).

Parte de las operaciones del escenario base (data/eventos.parquet) y las vuelve a valuar con otros
supuestos. La cobertura del neto con caución se mantiene como en el escenario base.

  1) Costo por especie: slippage de medio tick (y de un tick) por pata, con el tick propio de cada
     especie y rueda (data/ticks.csv). Dos versiones del bot:
       - sin cambios: decide igual que en el escenario base y paga el costo;
       - descuenta el costo: solo opera si el edge supera el costo esperado de las dos patas.
  2) Precio de ejecución: cierre del bucket de la señal (base), primer precio del bucket siguiente y
     promedio OHLC/4 del bucket siguiente.
  3) Latencia, con los registros sin agrupar (data/eventos_precio, con la hora de cada precio):
       - entre patas: la pata CI se ejecuta al precio de la señal y la 24hs con una demora (y al revés);
       - de la señal: las dos patas se ejecutan con una demora (vida útil del edge).
  4) Mapa de dónde falla: resultado por especie y clase según costo y demora entre patas.

Las fórmulas de revaluación están en ejecucion_comun.py.

Salidas: data/ejec_*.csv, output/grafico7_mapa_falla.png
"""
import glob
import importlib.util
import os
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import DATA, OUT, BASE
from ejecucion_comun import (CLASE, ORDEN, tick_de, patas, resumen as _resumen, descontar_costo,
                             precios_demora)

spec = importlib.util.spec_from_file_location("sizing", os.path.join(os.path.dirname(__file__), "05_sizing.py"))
sizing = importlib.util.module_from_spec(spec); spec.loader.exec_module(sizing)

ev0 = pd.read_parquet(f"{DATA}/eventos.parquet")
ev0 = ev0[ev0["escenario"] == BASE].reset_index(drop=True)
cob0 = pd.read_parquet(f"{DATA}/cobertura_diaria.parquet")
cob0 = cob0[cob0["escenario"] == BASE]
sig = pd.read_parquet(f"{DATA}/spread_signal.parquet")
sig = sig[sig["escenario"] == BASE].reset_index(drop=True)
BUCKET = pd.Timedelta(minutes=15)


def resumen(nombre, df, pat, cob=cob0, **extra):
    return _resumen(nombre, df, pat, cob, **extra)


filas = []
base_pat = patas(ev0, ev0["p_ci"], ev0["p_24"])
chk = base_pat.sum() + cob0["pnl_caucion"].sum()
assert abs(chk - (ev0["pnl_bono"].sum() + cob0["pnl_caucion"].sum())) < 1e-6, "la revaluación no reproduce la base"
filas.append(resumen("Base: cierre del bucket, sin slippage", ev0, base_pat, grupo="base"))

# ---- 1) costo por especie: medio tick y un tick por pata ----
adaptivos = {}
t_ev = tick_de(ev0)
for mult, nom in [(0.5, "medio tick"), (1.0, "un tick")]:
    s = mult * t_ev
    filas.append(resumen(f"Bot sin cambios, {nom} por pata", ev0, patas(ev0, ev0["p_ci"], ev0["p_24"], s, s),
                         grupo="costo", costo_ticks=mult, bot="sin cambios"))
    # bot que descuenta el costo esperado de las dos patas antes de decidir
    ev2, cob2 = sizing.dimensionar(descontar_costo(sig, mult))
    ev2 = ev2.reset_index(drop=True)
    adaptivos[mult] = (ev2, cob2)
    s2 = mult * tick_de(ev2)
    filas.append(resumen(f"Bot que descuenta el costo, {nom} por pata", ev2,
                         patas(ev2, ev2["p_ci"], ev2["p_24"], s2, s2), cob=cob2,
                         grupo="costo", costo_ticks=mult, bot="descuenta"))

# ---- 2) precio de ejecución: bucket siguiente ----
bars = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(f"{DATA}/bars_15min/*.parquet"))], ignore_index=True)
bars["ohlc4"] = bars[["open", "high", "low", "close"]].mean(axis=1)
bx = bars.set_index(["fecha", "simbolo", "vencimiento", "bucket"])
sig_b = ev0["bucket"] + BUCKET


def precio_bucket(campo, venc, buckets, fallback):
    idx = pd.MultiIndex.from_arrays([ev0["fecha"], ev0["simbolo"], [venc] * len(ev0), buckets])
    v = bx[campo].reindex(idx).values
    return np.where(np.isnan(v), fallback, v)


for campo, nom in [("open", "primer precio del bucket siguiente"), ("ohlc4", "promedio OHLC/4 del bucket siguiente")]:
    pci = precio_bucket(campo, "CI", sig_b, ev0["p_ci"].values)
    p24 = precio_bucket(campo, "24hs", sig_b, ev0["p_24"].values)
    filas.append(resumen(f"Ejecución al {nom}", ev0, patas(ev0, pci, p24), grupo="ejecucion"))

# ---- 3) latencia con los registros sin agrupar ----
DEMORAS = [0, 5, 30, 60, 300, 900, 1800, 3600]


def precios_con_demora(venc, seg):
    return precios_demora(ev0, venc, seg, "base")


# chequeo: con demora 0 el precio de cada pata es el cierre del bucket
assert np.allclose(precios_con_demora("CI", 0), ev0["p_ci"].values)
assert np.allclose(precios_con_demora("24hs", 0), ev0["p_24"].values)

for seg in DEMORAS:
    filas.append(resumen(f"Pata 24hs con {seg}s de demora (CI a la señal)", ev0,
                         patas(ev0, ev0["p_ci"].values, precios_con_demora("24hs", seg)),
                         grupo="latencia_patas", orden="CI primero", demora_s=seg))
    filas.append(resumen(f"Pata CI con {seg}s de demora (24hs a la señal)", ev0,
                         patas(ev0, precios_con_demora("CI", seg), ev0["p_24"].values),
                         grupo="latencia_patas", orden="24hs primero", demora_s=seg))
    filas.append(resumen(f"Ambas patas con {seg}s de demora", ev0,
                         patas(ev0, precios_con_demora("CI", seg), precios_con_demora("24hs", seg)),
                         grupo="latencia_senal", demora_s=seg))

# ---- 4) mapa: costo x demora entre patas (CI primero) ----
mapa = []
for mult in [0.0, 0.5, 1.0]:
    s = mult * t_ev
    for seg in [0, 30, 60, 300, 900]:
        r = resumen("mapa", ev0, patas(ev0, ev0["p_ci"].values, precios_con_demora("24hs", seg), s, s),
                    grupo="mapa", costo_ticks=mult, demora_s=seg)
        mapa.append(r)
for mult in [0.5, 1.0]:
    ev2, cob2 = adaptivos[mult]
    s2 = mult * tick_de(ev2)
    for seg in [0, 30, 60, 300, 900]:
        p24 = precios_demora(ev2, "24hs", seg, f"adapt{mult}")
        mapa.append(resumen("mapa", ev2, patas(ev2, ev2["p_ci"].values, p24, s2, s2), cob=cob2,
                            grupo="mapa_bot_descuenta", costo_ticks=mult, demora_s=seg))
        # vida útil de la señal para el bot que descuenta: las dos patas con demora
        pci = precios_demora(ev2, "CI", seg, f"adapt{mult}")
        filas.append(resumen(f"Bot que descuenta {mult} tick: ambas patas con {seg}s de demora", ev2,
                             patas(ev2, pci, p24, s2, s2), cob=cob2, grupo="latencia_senal_bot_descuenta",
                             costo_ticks=mult, demora_s=seg))
mapa = pd.DataFrame(mapa)
mapa.to_csv(f"{DATA}/ejec_mapa.csv", index=False)

res = pd.DataFrame(filas)
res.to_csv(f"{DATA}/ejec_resultados.csv", index=False)
cols = ["escenario", "operaciones", "retorno_pct", "ops_con_perdida_pct"] + [f"clase_{c}" for c in
                                                                              ["Soberanos", "ON", "Acciones", "CEDEARs"]]
pd.set_option("display.width", 250)
print(res[cols].round(2).to_string(index=False))
print("\nMapa (retorno total %):")
print(mapa.pivot_table(index=["grupo", "costo_ticks"], columns="demora_s", values="retorno_pct").round(2))

# ---- gráfico: mapa de dónde falla por especie (estilo común: graficos_resultados.py) ----
from graficos_resultados import mapa_falla

mapa_falla(mapa, f"{OUT}/grafico7_mapa_falla.png")
print("gráfico ok")
