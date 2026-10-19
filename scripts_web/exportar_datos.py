"""Exporta los datos que necesita la página web del backtest (JSON compacto).

Con el pipeline ya corrido toma:
  - las barras CI/24hs de cada bucket-instrumento con sus filtros de calidad (paso 4);
  - la caución A3 de cada rueda en sus cinco referencias y los días de liquidación;
  - el tick de cada especie y rueda (para el costo en ticks) y el tope de liquidez por especie (paso 12);
  - el precio de la pata 24hs 5 s, 30 s, 1 min, 5 min y 15 min después del fin de cada bucket, con los
    registros sin agrupar (para la demora entre patas con la CI primero, paso 13);
  - los resultados de Python con los que la página valida su propio motor.
"""
import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "scripts"))
from common import (CATEGORIA, BLOQUE_ORDEN, BLOQUE_LABEL, COSTO_OP, COSTO_CAUCION_ANUAL,  # noqa: E402
                    POS_BASE, TOPE_POSICION, INVENTARIO_ESPECIE, LIMITE_FALTANTE, CAPITAL, ESCENARIOS, BASE as ESC_BASE)
from ejecucion_comun import tick_de, precio_en, BUCKET  # noqa: E402

D = BASE / "data"
destino = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE / "output" / "web_datos.json"
DEMORAS = [5, 30, 60, 300, 900]

sig = pd.read_parquet(D / "spread_signal.parquet")
base = sig[sig["escenario"] == ESC_BASE].copy()

simbolos = sorted(base["simbolo"].unique())
fechas = sorted(base["fecha"].unique())
si = {s: i for i, s in enumerate(simbolos)}
fi = {f: i for i, f in enumerate(fechas)}

# cierre de la rueda = último bucket con barras (incluye el de las 17:00), como en el Modelo A
b = pd.concat([pd.read_parquet(f, columns=["fecha", "bucket"]) for f in glob.glob(str(D / "bars_15min/*.parquet"))])
cierre = b.groupby("fecha")["bucket"].max()

cau = {esc: sig[sig["escenario"] == esc].groupby("fecha")["caucion"].first() for esc in ESCENARIOS}
filas_f = []
for f in fechas:
    g = base[base["fecha"] == f].iloc[0]
    t = cierre.loc[f]
    filas_f.append([f, BLOQUE_ORDEN.index(g["bloque"]), int(g["d"])] + [float(cau[e][f]) for e in ESCENARIOS]
                   + [t.hour * 60 + t.minute])

# tick por rueda y especie (fracción del precio), con el mismo criterio que el paso 13
grid = pd.DataFrame([(f, s) for f in fechas for s in simbolos], columns=["fecha", "simbolo"])
grid["tick"] = tick_de(grid).values
ticks = [[float(grid.loc[(grid.fecha == f) & (grid.simbolo == s), "tick"].iloc[0]) for s in simbolos] for f in fechas]

base = base.sort_values(["fecha", "bucket", "simbolo"])
filas = []
for r in base.itertuples(index=False):
    flags = (1 if r.f_postcierre else 0) | (2 if r.f_sincronia else 0) | (4 if r.f_cota else 0)
    fin = (r.bucket + BUCKET).to_datetime64()
    dem = [float(precio_en(r.fecha, r.simbolo, "24hs", fin + np.timedelta64(s, "s"))) for s in DEMORAS]
    filas.extend([fi[r.fecha], r.bucket.hour * 60 + r.bucket.minute, si[r.simbolo],
                  float(r.p_ci), float(r.p_24), flags] + dem)
ANCHO = 6 + len(DEMORAS)

liq = pd.read_csv(D / "liquidez_ci.csv").set_index("simbolo")
tope_liq = [float(liq.loc[s, "tope_orden"]) for s in simbolos]

# ---------------- resultados de Python para validar ----------------
res = pd.read_csv(D / "modeloA_resumen.csv").set_index("escenario")
var = pd.read_csv(D / "modeloA_variantes_capital.csv")
sl = pd.read_csv(D / "comparacion_slippage.csv")
be = pd.read_csv(D / "breakeven_slippage.csv", index_col=0).iloc[0, 0]
ej = pd.read_csv(D / "ejec_resultados.csv").set_index("escenario")
rb = pd.read_csv(D / "robustez.csv").set_index("variante")
vs = pd.read_csv(D / "versiones.csv")
es = pd.read_csv(D / "escalabilidad.csv")
vimp = pd.read_csv(D / "versiones_impacto.csv").set_index("version")
vesc = pd.read_csv(D / "versiones_escala.csv")


def fila(nombre, params, retorno, ops=None):
    return {"nombre": nombre, "p": params, "retorno_pct": float(retorno),
            "operaciones": None if ops is None or pd.isna(ops) else int(ops)}


def vsel(version, costo, demora):
    x = vs[(vs.version == version) & (vs.costo_ticks == costo) & (vs.demora_s == demora)].iloc[0]
    return x["retorno_pct"], x["operaciones"]


INF = 1e15
val = []
for e in ESCENARIOS:
    val.append(fila(f"Caución: {e}", {"escenario": e}, res.loc[e, "retorno_pct"], res.loc[e, "eventos"]))
vp = [{"reinversion": False}, {"limFrac": 0}, None, {"invFrac": 0.2}, {"invFrac": INF, "limFrac": INF}]
vn = ["Regla anterior (sin reinversión)", "Solo pesos del bot", None, "Inventario 200k por especie", "Sin límites"]
for i, (p, n) in enumerate(zip(vp, vn)):
    if p:
        val.append(fila(n, p, var.loc[i, "retorno_pct"], var.loc[i, "operaciones"]))
for r in sl.itertuples():
    if r.slippage_bps > 0:
        val.append(fila(f"Slippage {r.slippage_bps:g} bps por pata", {"slippageBps": r.slippage_bps}, r.retorno_motor_pct))
for t, n in [(0.5, "medio tick"), (1.0, "un tick")]:
    x = ej.loc[f"Bot sin cambios, {n} por pata"]
    val.append(fila(f"Bot sin cambios, {n} por pata", {"ticks": t}, x["retorno_pct"], x["operaciones"]))
    x = ej.loc[f"Bot que descuenta el costo, {n} por pata"]
    val.append(fila(f"Bot que descuenta {n}", {"ticks": t, "margenTicks": t}, x["retorno_pct"], x["operaciones"]))
for seg in [30, 300]:
    x = ej.loc[f"Pata 24hs con {seg}s de demora (CI a la señal)"]
    val.append(fila(f"Pata 24hs {seg} s después de la CI", {"demora": seg}, x["retorno_pct"], x["operaciones"]))
for nombre, p in [("Presupuesto del bucket en proporción al edge", {"ponderacion": "edge"}),
                  ("Solo señales con edge > 5 bps", {"umbralBps": 5}),
                  ("Sin cota", {"filtroCota": False}),
                  ("Sin regla de sincronía", {"filtroSincronia": False}),
                  ("Incluyendo el bucket de las 17:00", {"filtroPostcierre": False}),
                  ("Inventario 50k por especie", {"invFrac": 0.05}),
                  ("10% del capital por bucket", {"posBase": 0.10})]:
    val.append(fila(nombre, p, rb.loc[nombre, "retorno_pct"], rb.loc[nombre, "operaciones"]))
VER = {"V1": {}, "V2": {"ponderacion": "edge", "margenTicks": 0.5},
       "V3": {"ponderacion": "edge", "margenTicks": 1.0, "topeLiquidez": True},
       "raiz": {"ponderacion": "raiz", "margenTicks": 0.5}, "mixta": {"ponderacion": "mixta", "margenTicks": 0.5}}
NOMV = {"V1": "Versión 1 (anterior)", "V2": "Versión 2 (anterior)", "V3": "Versión 3 (definitiva)",
        "raiz": "Intermedia: raíz del edge", "mixta": "Intermedia: mitad igual, mitad edge"}
for k in ["V3", "V2", "V1"]:
    for c, d in [(0.0, 0), (0.5, 30), (1.0, 30)]:
        r_, o_ = vsel(k, c, d)
        val.append(fila(f"{NOMV[k]}: {'sin costos' if c == 0 else ('medio tick' if c == 0.5 else 'un tick')}"
                        f"{', 30 s entre patas' if d else ''}", {**VER[k], "ticks": c, "demora": d}, r_, o_))
for k in ["raiz", "mixta"]:
    r_, o_ = vsel(k, 0.5, 30)
    val.append(fila(f"{NOMV[k]}: medio tick, 30 s", {**VER[k], "ticks": 0.5, "demora": 30}, r_, o_))
for k in ["V3", "V1"]:
    val.append(fila(f"{NOMV[k]}: medio tick, 30 s e impacto por tamaño", {**VER[k], "ticks": 0.5, "demora": 30, "impacto": True},
                    vimp.loc[k, "retorno_pct"], vimp.loc[k, "operaciones"]))
x = vesc[(vesc.version == "V3") & (vesc.escenario == "realista_impacto") & (vesc.capital == 100e6)].iloc[0]
val.append(fila("Versión 3: 100 M, medio tick, 30 s e impacto", {**VER["V3"], "ticks": 0.5, "demora": 30, "impacto": True,
                                                                  "capital": 100e6}, x["retorno_pct"], x["operaciones"]))
for C in [10e6, 100e6]:
    x = es[(es.capital == C) & es.version.str.startswith("B")].iloc[0]
    val.append(fila(f"Capital {C / 1e6:g}M con límite de liquidez", {"capital": C, "topeLiquidez": True},
                    x["retorno_pct"], x["operaciones"]))

datos = {
    "simbolos": [[s, CATEGORIA[s]] for s in simbolos],
    "bloques": [[k, BLOQUE_LABEL[k]] for k in BLOQUE_ORDEN],
    "escenarios": ESCENARIOS,
    # [fecha, bloque, d, caución vwap_ant, vwap, mínimo, máximo, cierre, cierre de rueda (min)]
    "fechas": filas_f,
    "ticks": ticks,                       # [rueda][especie] tick como fracción del precio
    "topeLiquidez": tope_liq,             # [especie] 10% del volumen CI medio por bucket, en pesos
    "demoras": DEMORAS,
    "ancho": ANCHO,
    # planas de a ANCHO: [rueda, bucket (min), especie, p_ci, p_24, filtros, p_24 a +5s, +30s, +1m, +5m, +15m]
    "filas": filas,
    "parametros": {"capital": CAPITAL, "costo_op": COSTO_OP, "costo_caucion": COSTO_CAUCION_ANUAL,
                   "pos_base": POS_BASE, "tope": TOPE_POSICION, "inv_frac": INVENTARIO_ESPECIE / CAPITAL,
                   "lim_frac": LIMITE_FALTANTE / CAPITAL, "escenario": ESC_BASE},
    "ref": {"validacion": val, "breakeven_bps": float(be)},
}
destino.write_text(json.dumps(datos, separators=(",", ":"), ensure_ascii=False))
print(f"{destino}: {destino.stat().st_size/1024:.0f} KB, {len(filas)//ANCHO} filas, {len(fechas)} ruedas, "
      f"{len(val)} configuraciones de validación")
