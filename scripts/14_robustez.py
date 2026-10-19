"""
Paso 14 — Robustez del research y análisis de sensibilidad (escenario base de caución).

Robustez (¿el resultado depende de una fecha, especie, período o convención?):
  - sacar un bloque por vez y una rueda por vez; peso de las 5 mejores ruedas;
  - sacar una especie por vez (se vuelve a correr el sizing: las especies compiten por el presupuesto);
  - base 360 en lugar de 365 para la caución;
  - interés corrido de los bonos: los precios de pantalla son limpios y al liquidar se suma el
    devengado, así que quien queda con el título d días cobra cupón x d/365 sobre el precio y quien lo
    presta lo pierde. Cupón anual sobre el precio: YMCIO 9% (condiciones de emisión), AL30 y GD30 0,75%;
  - con y sin viernes (y vísperas de feriado).
Sensibilidad (variaciones razonables de los supuestos):
  - filtros: cota ±0,5% / ±2% / sin cota, sin regla de sincronía, incluyendo el bucket de las 17:00;
  - sizing: % por bucket, tope por posición, inventario por especie, faltante de pesos;
  - asignación: presupuesto del bucket en proporción al edge y umbrales mínimos de edge;
  - grilla: corrida 5 y 10 minutos, y barras de 5, 10 y 30 minutos (el % por bucket se escala con el
    largo de la barra para mantener el presupuesto por hora). Se reconstruye desde los cambios de precio
    guardados (data/eventos_precio), sin volver a leer los Excel. La grilla es el análogo intradiario del día
    de rebalanceo; también se mide para la versión 3 (definitiva) en el escenario realista.

Salidas: data/robustez.csv, data/robustez_ruedas.csv, data/grilla_v3.csv, output/grafico5_robustez.png
"""
import importlib.util
import os
import shutil
import subprocess
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (DATA, OUT, BASE, CAPITAL, BLOQUE_LABEL, BLOQUE_ORDEN, FREQ_MIN, MARGEN_TICKS_V3,
                    COSTO_REALISTA_TICKS, DEMORA_REALISTA_S)
from ejecucion_comun import tick_de, patas, descontar_costo, precios_demora

AQUI = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("sizing", os.path.join(AQUI, "05_sizing.py"))
sizing = importlib.util.module_from_spec(spec); spec.loader.exec_module(sizing)

CUPON = {"YMCIO": 0.09, "AL30": 0.0075, "GD30": 0.0075}
sig0 = pd.read_parquet(f"{DATA}/spread_signal.parquet")
sig0 = sig0[sig0["escenario"] == BASE].reset_index(drop=True)
filas = []


def candidatas(sg, valido):
    c1 = (sg["edge1_col"] > 0) | (sg["edge1"] > 0)
    c2 = (sg["edge2_tom"] > 0) | (sg["edge2"] > 0)
    out = sg.copy()
    out["valido"] = valido
    out["candidata"] = np.where(valido, np.select([c1 & c2, c1, c2], [3, 1, 2], default=0), 0)
    return out


def correr(sg, ajuste=None, **kw):
    ev, cob = sizing.dimensionar(sg, **kw)
    pnl = ev["pnl_bono"].sum() + cob["pnl_caucion"].sum()
    if ajuste is not None:
        pnl += ajuste(ev).sum()
    return pnl, ev, cob


def agregar(grupo, variante, pnl, ev, nota=""):
    filas.append({"grupo": grupo, "variante": variante, "retorno_pct": pnl / CAPITAL * 100,
                  "operaciones": len(ev), "ruedas": ev["fecha"].nunique(), "nota": nota})


# ---------------- base ----------------
pnl0, ev0, cob0 = correr(sig0)
ref = pd.read_csv(f"{DATA}/modeloA_resumen.csv", index_col=0).loc[BASE, "pnl_total"]
assert abs(pnl0 - ref) < 1e-6, "la base no coincide con el Modelo A"
agregar("Base", "Escenario base", pnl0, ev0)

# ---------------- período: bloques y ruedas ----------------
dia = (ev0.groupby("fecha")["pnl_bono"].sum() + cob0.set_index("fecha")["pnl_caucion"]).fillna(0).rename("pnl").to_frame()
dia["bloque"] = cob0.set_index("fecha")["bloque"]
dia["d"] = cob0.set_index("fecha")["d"]
dia["ret_bps"] = dia["pnl"] / CAPITAL * 1e4
dia.sort_values("pnl", ascending=False).to_csv(f"{DATA}/robustez_ruedas.csv")
for b in BLOQUE_ORDEN:
    sub = dia[dia["bloque"] != b]
    filas.append({"grupo": "Período", "variante": f"Sin el bloque {BLOQUE_LABEL[b]}",
                  "retorno_pct": sub["pnl"].sum() / CAPITAL * 100, "operaciones": int((ev0["bloque"] != b).sum()),
                  "ruedas": len(sub), "retorno_por_rueda_bps": sub["ret_bps"].mean()})
top5 = dia["pnl"].nlargest(5)
sub = dia.drop(top5.index)
filas.append({"grupo": "Período", "variante": "Sin las 5 mejores ruedas", "retorno_pct": sub["pnl"].sum() / CAPITAL * 100,
              "ruedas": len(sub), "retorno_por_rueda_bps": sub["ret_bps"].mean(),
              "nota": f"las 5 mejores explican {top5.sum() / dia['pnl'].sum() * 100:.1f}% del resultado"})
loo = [(dia["pnl"].sum() - v) / CAPITAL * 100 for v in dia["pnl"]]
filas.append({"grupo": "Período", "variante": "Sacando una rueda por vez (mínimo)", "retorno_pct": min(loo),
              "ruedas": len(dia) - 1, "nota": f"máximo {max(loo):.2f}%"})

# ---------------- especies ----------------
for s in ["AL30", "GD30", "YMCIO", "GGAL", "YPFD", "GLD", "KO", "SLV", "SPY"]:
    pnl, ev, _ = correr(sig0[sig0["simbolo"] != s].reset_index(drop=True))
    agregar("Especies", f"Sin {s}", pnl, ev)

# ---------------- convenciones ----------------
sg = sig0.copy()
for col in ["r_col", "r_tom"]:
    sg[col] = sg[col] * 365 / 360
sg["edge1"] = sg["spread_pct"] - sg["r_tom"] * sg["d"] / 365 - sg["costo_bono"]
sg["edge2"] = sg["r_col"] * sg["d"] / 365 - sg["spread_pct"] - sg["costo_bono"]
sg["edge1_col"] = sg["spread_pct"] - sg["r_col"] * sg["d"] / 365 - sg["costo_bono"]
sg["edge2_tom"] = sg["r_tom"] * sg["d"] / 365 - sg["spread_pct"] - sg["costo_bono"]
pnl, ev, _ = correr(candidatas(sg, sig0["valido"]))
agregar("Convenciones", "Caución en base 360", pnl, ev)

sg = sig0.copy()
dev = sg["simbolo"].map(CUPON).fillna(0.0) * sg["d"] / 365       # devengado del período sobre el precio
sg["edge1"] += dev; sg["edge1_col"] += dev                        # coloco: queda con el título y cobra el devengado
sg["edge2"] -= dev; sg["edge2_tom"] -= dev                        # tomo: presta el título y lo pierde
ajuste = lambda ev: np.where(ev["direccion"] == 1, 1, -1) * ev["nocional"] * ev["simbolo"].map(CUPON).fillna(0.0) * ev["d"] / 365
pnl, ev, _ = correr(candidatas(sg, sig0["valido"]), ajuste=ajuste)
agregar("Convenciones", "Con interés corrido de los bonos (YMCIO 9%)", pnl, ev)
pnl_b, ev_b, _ = correr(sig0, ajuste=ajuste)
agregar("Convenciones", "Interés corrido solo en el resultado (bot sin cambios)", pnl_b, ev_b)

# ---------------- viernes ----------------
sub = dia[dia["d"] == 1]
filas.append({"grupo": "Viernes", "variante": "Sin viernes ni vísperas de feriado", "retorno_pct": sub["pnl"].sum() / CAPITAL * 100,
              "ruedas": len(sub), "retorno_por_rueda_bps": sub["ret_bps"].mean(),
              "nota": f"viernes: {dia.loc[dia['d'] > 1, 'ret_bps'].mean():.1f} bps por rueda; resto: {sub['ret_bps'].mean():.1f}"})

# ---------------- filtros ----------------
f_ev, f_post, f_sinc = sig0["f_evento"], sig0["f_postcierre"], sig0["f_sincronia"]
for nombre, valido in [
        ("Cota ±0,5%", ~(f_ev | f_post | f_sinc | (sig0["spread_pct"].abs() > 0.005))),
        ("Cota ±2%", ~(f_ev | f_post | f_sinc | (sig0["spread_pct"].abs() > 0.02))),
        ("Sin cota", ~(f_ev | f_post | f_sinc)),
        ("Sin regla de sincronía", ~(f_ev | f_post | sig0["f_cota"])),
        ("Incluyendo el bucket de las 17:00", ~(f_ev | f_sinc | sig0["f_cota"]))]:
    pnl, ev, _ = correr(candidatas(sig0, valido))
    agregar("Filtros", nombre, pnl, ev)

# ---------------- sizing ----------------
for nombre, kw, pos, tope in [
        ("2,5% del capital por bucket", {}, 0.025, None), ("10% del capital por bucket", {}, 0.10, None),
        ("Tope por posición 10%", {}, None, 0.10), ("Tope por posición 25%", {}, None, 0.25),
        ("Inventario 50k por especie", dict(inventario=50_000.0), None, None),
        ("Inventario 200k por especie", dict(inventario=200_000.0), None, None),
        ("Inventario sin límite", dict(inventario=1e15), None, None),
        ("Sin faltante cubierto con caución", dict(limite=0.0), None, None),
        ("Faltante hasta 500k", dict(limite=500_000.0), None, None)]:
    pb, tp = sizing.POS_BASE, sizing.TOPE_POSICION
    if pos is not None: sizing.POS_BASE = pos
    if tope is not None: sizing.TOPE_POSICION = tope
    pnl, ev, _ = correr(sig0, **kw)
    sizing.POS_BASE, sizing.TOPE_POSICION = pb, tp
    agregar("Sizing", nombre, pnl, ev)

# ---------------- asignación ----------------
pnl, ev, _ = correr(sig0, ponderacion="edge")
agregar("Asignación", "Presupuesto del bucket en proporción al edge", pnl, ev)
for u in [2, 5, 10]:
    pnl, ev, _ = correr(sig0, umbral_edge=u / 1e4)
    agregar("Asignación", f"Solo señales con edge > {u} bps", pnl, ev)

# ---------------- grilla y frecuencia ----------------
# La grilla es el análogo intradiario del día de rebalanceo: cambia el instante en que el bot evalúa la señal.
# Se mide para la versión 1 (escenario sin costos, como el resto de esta sección) y para la versión 3
# (definitiva) en el escenario realista, con el tope de liquidez escalado al largo de la barra.
TMP = os.path.join(DATA, "_grillas")
liq = pd.read_csv(f"{DATA}/liquidez_ci.csv")
TOPE = dict(zip(liq["simbolo"], liq["tope_orden"]))
grilla_v3 = []
for nombre, freq, off in [("Grilla base (15 minutos)", 15, 0), ("Grilla corrida 5 minutos", 15, 5), ("Grilla corrida 10 minutos", 15, 10),
                          ("Barras de 5 minutos", 5, 0), ("Barras de 10 minutos", 10, 0),
                          ("Barras de 30 minutos", 30, 0)]:
    d = os.path.join(TMP, f"f{freq}_o{off}")
    shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
    for fn in ["manifest.json", "caucion_diaria.csv"]:
        shutil.copy(os.path.join(DATA, fn), d)
    env = dict(os.environ, TESIS_DATA_DIR=d, TESIS_EVENTOS_CACHE=os.path.join(DATA, "eventos_precio"),
               TESIS_FREQ_MIN=str(freq), TESIS_OFFSET_MIN=str(off), TESIS_POS_BASE=str(0.05 * freq / 15))
    for paso in ["03_build_bars.py", "04_spread_signal.py", "05_sizing.py"]:
        subprocess.run([sys.executable, os.path.join(AQUI, paso)], env=env, check=True, stdout=subprocess.DEVNULL)
    e = pd.read_parquet(os.path.join(d, "eventos.parquet")); c = pd.read_parquet(os.path.join(d, "cobertura_diaria.parquet"))
    e, c = e[e["escenario"] == BASE], c[c["escenario"] == BASE]
    if freq != 15 or off != 0:
        agregar("Grilla", nombre, e["pnl_bono"].sum() + c["pnl_caucion"].sum(), e,
                nota=f"% por bucket {0.05 * freq / 15 * 100:.2f}%")
    # versión 3 en la misma grilla
    sg = pd.read_parquet(os.path.join(d, "spread_signal.parquet"))
    sg = sg[sg["escenario"] == BASE].reset_index(drop=True)
    e3, c3 = sizing.dimensionar(descontar_costo(sg, MARGEN_TICKS_V3), ponderacion="edge", pos_base=0.05 * freq / 15,
                                tope_orden={k: v * freq / 15 for k, v in TOPE.items()})
    e3 = e3.reset_index(drop=True)
    s3 = COSTO_REALISTA_TICKS * tick_de(e3)
    p24 = precios_demora(e3, "24hs", DEMORA_REALISTA_S, f"grilla_{freq}_{off}", largo_min=freq)
    pnl3 = patas(e3, e3["p_ci"].values, p24, s3, s3).sum() + c3["pnl_caucion"].sum()
    grilla_v3.append({"variante": nombre, "freq_min": freq, "offset_min": off, "operaciones": len(e3),
                      "retorno_pct": pnl3 / CAPITAL * 100, "pct_por_bucket": 0.05 * freq / 15 * 100})
shutil.rmtree(TMP, ignore_errors=True)
grilla_v3 = pd.DataFrame(grilla_v3)
grilla_v3["dif_vs_base_pp"] = grilla_v3["retorno_pct"] - grilla_v3.loc[grilla_v3["variante"] == "Grilla base (15 minutos)", "retorno_pct"].iloc[0]
grilla_v3.to_csv(f"{DATA}/grilla_v3.csv", index=False)
print("Versión 3 (realista) según la grilla:")
print(grilla_v3.round(2).to_string(index=False))

res = pd.DataFrame(filas)
res["dif_vs_base_pp"] = res["retorno_pct"] - pnl0 / CAPITAL * 100
res.to_csv(f"{DATA}/robustez.csv", index=False)
pd.set_option("display.width", 220); pd.set_option("display.max_colwidth", 60)
print(res[["grupo", "variante", "retorno_pct", "dif_vs_base_pp", "operaciones", "ruedas", "nota"]].round(2).to_string(index=False))

# ---------------- gráfico (estilo común: graficos_resultados.py) ----------------
from graficos_resultados import robustez as grafico_robustez

grafico_robustez(res, f"{OUT}/grafico5_robustez.png")
print("gráfico ok")
