"""
Paso 4 — Señal de arbitraje CI/24hs vs caución, para los 5 escenarios de referencia de caución.

Economía (por unidad de nocional N = Q x P_CI):
  spread = P_24hs / P_CI - 1   -> retorno de "prestar vía el bono" por d días
                                   (pago CI hoy, cobro 24hs en T+1)
  d      = días corridos hasta la liquidación de la 24hs (viernes = 3; víspera de feriado, más)
  f      = derecho de mercado por punta de la categoría (RF 0,01%; acciones y CEDEARs 0,05%)
  costos del bono = f x (2 + spread)   (compra y venta sobre el valor de cada pata)

  Dirección 1 — "coloco con títulos": compro CI, vendo 24hs y me fondeo tomando caución.
      edge1 = spread - r_tom x d/365 - f(2 + spread)
  Dirección 2 — "tomo con títulos": vendo CI (inventario), compro 24hs y coloco la plata en caución.
      edge2 = r_col x d/365 - spread - f(2 + spread)

  r_col = caución - 0,045% anual ; r_tom = caución + 0,045% anual (derechos prorrateados por plazo)
  Se opera si el edge de alguna dirección es > 0 (el margen de seguridad son los costos).
"""
import glob
import os
import sys
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (DATA, OUT, COSTO_OP, COSTO_CAUCION_ANUAL, CATEGORIA, ESCENARIOS,
                    EXCLUIR_ESPECIE_RUEDA, FREQ_MIN, dias_liquidacion)

bars = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(
    f"{DATA}/bars_15min/*.parquet"))], ignore_index=True)
bars["categoria"] = bars["simbolo"].map(CATEGORIA)

idx = ["fecha", "bloque", "simbolo", "categoria", "bucket"]
px = bars.pivot_table(index=idx, columns="vencimiento", values="close")
ne = bars.pivot_table(index=idx, columns="vencimiento", values="n_eventos")
piv = pd.concat({"p": px, "n": ne}, axis=1)
piv.columns = [f"{a}_{b}" for a, b in piv.columns]
piv = piv.reset_index().rename(columns={"p_CI": "p_ci", "p_24hs": "p_24",
                                        "n_CI": "n_ev_ci", "n_24hs": "n_ev_24"})
piv = piv.dropna(subset=["p_ci", "p_24"])

piv["d"] = piv["fecha"].map(dias_liquidacion)
piv["spread_pct"] = piv["p_24"] / piv["p_ci"] - 1
piv["tasa_implicita_anual"] = piv["spread_pct"] * 365 / piv["d"]
piv["f"] = piv["categoria"].map(COSTO_OP)
piv["costo_bono"] = piv["f"] * (2 + piv["spread_pct"])

# --- Filtros de calidad de dato (se aplican antes de generar señales) ---
#  1) post-cierre: buckets que terminan después de las 17:00 (prints posteriores a la sesión continua)
#  2) sincronía: ambas patas deben tener al menos una operación dentro del mismo bucket
#     (control de non-synchronous trading: evita comparar un precio fresco contra uno viejo)
#  3) cota de razonabilidad: |spread| > 1% (> 365% TNA en 1 día) = precio fuera de mercado
#  0) evento corporativo: especie-rueda excluida (ej. YMCIO el 29/6/2026, pago de renta y amortización)
piv["f_evento"] = [(s_, f_) in EXCLUIR_ESPECIE_RUEDA for s_, f_ in zip(piv["simbolo"], piv["fecha"])]
piv["f_postcierre"] = (piv["bucket"] + pd.Timedelta(minutes=FREQ_MIN)).dt.time > pd.Timestamp("17:00").time()
piv["f_sincronia"] = (piv["n_ev_ci"] == 0) | (piv["n_ev_24"] == 0)
piv["f_cota"] = piv["spread_pct"].abs() > 0.01
piv["valido"] = ~(piv["f_evento"] | piv["f_postcierre"] | piv["f_sincronia"] | piv["f_cota"])

n = len(piv)
ev_ = piv["f_evento"]
r1 = (~ev_ & piv["f_postcierre"]).sum()
r2 = (~ev_ & ~piv["f_postcierre"] & piv["f_sincronia"]).sum()
r3 = (~ev_ & ~piv["f_postcierre"] & ~piv["f_sincronia"] & piv["f_cota"]).sum()
print(f"Filtros (secuenciales) sobre {n} bucket-instrumento: evento corporativo -{ev_.sum()}, post-cierre -{r1}, "
      f"sincronía -{r2}, cota ±1% -{r3} -> válidos {piv['valido'].sum()}")

# --- Caución: cinco referencias (VWAP de la rueda anterior = base; VWAP, mínimo, máximo y última del día) ---
cau = pd.read_csv(f"{DATA}/caucion_diaria.csv")
REF = list(ESCENARIOS)
piv = piv.merge(cau[["fecha", "plazo_caucion"] + REF], on="fecha", how="left")
assert piv[REF].notna().all().all(), "falta caución para alguna rueda"

# Chequeo: el plazo de la caución de A3 de cada rueda coincide con los días hasta la liquidación de la 24hs
mismatch = (piv.drop_duplicates("fecha")["d"].values != piv.drop_duplicates("fecha")["plazo_caucion"].values).sum()
print(f"Chequeo días de liquidación vs plazo de la caución A3: {mismatch} discrepancias")
assert mismatch == 0, "el plazo de la caución no coincide con los días de liquidación"

out = []
for esc in ESCENARIOS:
    t = piv.copy()
    t["escenario"] = esc
    t["caucion"] = t[esc]
    t["r_col"] = t["caucion"] - COSTO_CAUCION_ANUAL
    t["r_tom"] = t["caucion"] + COSTO_CAUCION_ANUAL
    # Standalone (el neto se cubre con caución): coloco vs caución tomadora, tomo vs colocadora
    t["edge1"] = t["spread_pct"] - t["r_tom"] * t["d"] / 365 - t["costo_bono"]
    t["edge2"] = t["r_col"] * t["d"] / 365 - t["spread_pct"] - t["costo_bono"]
    # Compensando saldo del bot: coloco con pesos de tomadoras (costo de oportunidad = colocadora);
    # tomo para cubrir pesos faltantes (evita tomar caución = tomadora)
    t["edge1_col"] = t["spread_pct"] - t["r_col"] * t["d"] / 365 - t["costo_bono"]
    t["edge2_tom"] = t["r_tom"] * t["d"] / 365 - t["spread_pct"] - t["costo_bono"]
    # Candidata: la dirección es rentable en alguna de sus dos zonas (compensando saldo o extendiendo
    # el neto). Con una sola tasa (r_col < r_tom) nunca son rentables las dos direcciones a la vez;
    # con la caución favorable (r_col > r_tom) sí puede pasar: se marca 3 y el sizing elige según el saldo.
    c1 = (t["edge1_col"] > 0) | (t["edge1"] > 0)
    c2 = (t["edge2_tom"] > 0) | (t["edge2"] > 0)
    t["candidata"] = np.select([c1 & c2, c1, c2], [3, 1, 2], default=0)
    # dirección "sin filtro" (solo para documentar el efecto de los filtros)
    t["direccion_sin_filtro"] = np.select([t["edge1"] > 0, t["edge2"] > 0], [1, 2], default=0)
    t["direccion"] = np.where(t["valido"], t["direccion_sin_filtro"], 0)
    t["candidata"] = np.where(t["valido"], t["candidata"], 0)
    t["edge"] = np.where(t["direccion"] == 1, t["edge1"],
                         np.where(t["direccion"] == 2, t["edge2"], np.nan))
    out.append(t)

sig = pd.concat(out, ignore_index=True)
sig = sig.drop(columns=REF + ["plazo_caucion"])
sig.to_parquet(f"{DATA}/spread_signal.parquet", index=False)

print(f"\nBucket-instrumento evaluados por escenario: {len(piv)}")
sf = sig.assign(edge_sf=np.where(sig["direccion_sin_filtro"] == 1, sig["edge1"],
                                 np.where(sig["direccion_sin_filtro"] == 2, sig["edge2"], np.nan)))
print("SIN filtros de calidad:")
print(sf.groupby("escenario").agg(
    señales=("direccion_sin_filtro", lambda x: (x > 0).sum()),
    edge_medio_bps=("edge_sf", lambda x: x.mean() * 1e4),
    edge_mediana_bps=("edge_sf", lambda x: x.median() * 1e4)).reindex(ESCENARIOS).round(2))
print("CON filtros de calidad:")
res = sig.groupby("escenario").agg(
    dir1=("direccion", lambda x: (x == 1).sum()),
    dir2=("direccion", lambda x: (x == 2).sum()),
    pct_activo=("direccion", lambda x: (x > 0).mean() * 100),
    edge_medio_bps=("edge", lambda x: x.mean() * 1e4),
    edge_mediana_bps=("edge", lambda x: x.median() * 1e4),
).reindex(ESCENARIOS)
print(res.round(2))
