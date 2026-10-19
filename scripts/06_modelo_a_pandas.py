"""
Modelo A — implementación directa en pandas (fórmulas cerradas).

Resultado = Σ resultado de las patas del título por operación
          + cobertura del operador sobre el neto diario de pesos (caución colocadora o tomadora).
Capital sin reinversión de ganancias: valor = capital inicial + resultado acumulado.
Además corre variantes de la regla de capital para la tabla de sensibilidad.
"""
import os
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import DATA, OUT, CAPITAL, ESCENARIOS, BLOQUE_ORDEN, BASE
from importlib import import_module
dimensionar = import_module("05_sizing").dimensionar

ev = pd.read_parquet(f"{DATA}/eventos.parquet")
cob = pd.read_parquet(f"{DATA}/cobertura_diaria.parquet")
import glob
_b = pd.concat([pd.read_parquet(f, columns=["fecha", "bucket"]) for f in
                glob.glob(f"{DATA}/bars_15min/*.parquet")])
CIERRE_RUEDA = _b.groupby("fecha")["bucket"].max()   # la cobertura se registra al cierre de la rueda

resumen, curvas = [], []
for esc in ESCENARIOS:
    e = ev[ev["escenario"] == esc]
    c = cob[cob["escenario"] == esc].set_index("fecha")
    # curva: resultado de patas por bucket + caución del neto al último bucket de cada rueda
    por_bucket = e.groupby("bucket")["pnl_bono"].sum()
    cau = pd.Series(c["pnl_caucion"].values, index=CIERRE_RUEDA.loc[c.index].values)
    flujo = por_bucket.add(cau, fill_value=0).sort_index()
    valor = CAPITAL + flujo.cumsum()
    diario = e.groupby("fecha")["pnl_bono"].sum() + c["pnl_caucion"]
    total = e["pnl_bono"].sum() + c["pnl_caucion"].sum()
    resumen.append({
        "escenario": esc, "eventos": len(e),
        "dir1": int((e["direccion"] == 1).sum()), "dir2": int((e["direccion"] == 2).sum()),
        "pnl_bono": e["pnl_bono"].sum(), "pnl_caucion": c["pnl_caucion"].sum(),
        "pnl_total": total, "retorno_pct": total / CAPITAL * 100,
        "edge_pond_bps": total / e["nocional"].sum() * 1e4,
        "pesos_tomadoras": c["pesos_tomadoras"].sum(), "compensado": c["compensado"].sum(),
        "compensado_pct": c["compensado"].sum() / c["pesos_tomadoras"].sum() * 100,
        "neto_medio_abs": c["neto_cierre"].abs().mean(),
        "max_dd_pct": (valor / valor.cummax() - 1).min() * 100,
        "dias_positivos": int((diario > 0).sum()), "dias": int(diario.size),
    })
    curvas.append(valor.rename(esc))

res = pd.DataFrame(resumen).set_index("escenario")
print("=== MODELO A (pandas) ===")
print(res.round(3).T.to_string())

# ---- desgloses del escenario base ----
e = ev[ev["escenario"] == BASE].copy()
c = cob[cob["escenario"] == BASE]
bloques = []
for b in BLOQUE_ORDEN:
    eb, cb = e[e["bloque"] == b], c[c["bloque"] == b]
    bloques.append({"bloque": b,
        "pnl_bono_tomo": eb.loc[eb.direccion == 2, "pnl_bono"].sum(),
        "pnl_bono_coloco": eb.loc[eb.direccion == 1, "pnl_bono"].sum(),
        "pnl_caucion": cb["pnl_caucion"].sum(),
        "retorno_pct": (eb["pnl_bono"].sum() + cb["pnl_caucion"].sum()) / CAPITAL * 100,
        "ops_tomo": int((eb.direccion == 2).sum()), "ops_coloco": int((eb.direccion == 1).sum()),
        "pesos_tomadoras": cb["pesos_tomadoras"].sum(), "compensado": cb["compensado"].sum(),
        "neto_medio_abs": cb["neto_cierre"].abs().mean()})
pb = pd.DataFrame(bloques).set_index("bloque")
pb["compensado_pct"] = pb["compensado"] / pb["pesos_tomadoras"] * 100
print("\n--- Por bloque (escenario base) ---"); print(pb.round(2).to_string())

# atribución por instrumento: patas + caución de cada operación "como si" se cubriera sola
# (la compensación entre especies no es atribuible a una sola especie)
e["edge_standalone"] = np.where(e["direccion"] == 2, e["edge2"], e["edge1"])
pi = e.groupby("simbolo").agg(eventos=("nocional", "size"),
    dir1=("direccion", lambda x: (x == 1).sum()), dir2=("direccion", lambda x: (x == 2).sum()),
    edge_mediana_bps=("edge_standalone", lambda x: x.median() * 1e4),
    retorno_pct=("nocional", lambda x: (x * e.loc[x.index, "edge_standalone"]).sum() / CAPITAL * 100),
).sort_values("retorno_pct", ascending=False)
print("\n--- Por instrumento (escenario base, atribución standalone) ---"); print(pi.round(3).to_string())

# ---- sensibilidad a la regla de capital (escenario base) ----
sig = pd.read_parquet(f"{DATA}/spread_signal.parquet")
sb = sig[sig["escenario"] == BASE]
variantes = []
for nombre, kw in [("Regla anterior: capacidad bruta 100% del capital, sin compensar", dict(reinversion=False)),
                   ("Solo pesos del bot (sin faltante cubierto con caución)", dict(limite=0.0)),
                   ("Base: 100k por especie, faltante hasta 1M", dict()),
                   ("200k por especie, faltante hasta 1M", dict(inventario=200_000.0)),
                   ("Sin límites (cota superior)", dict(inventario=1e15, limite=1e15))]:
    ve, vc = dimensionar(sb, **kw)
    if kw.get("reinversion") is False:
        tot = (ve["nocional"] * ve["edge"]).sum(); comp = 0.0
    else:
        tot = ve["pnl_bono"].sum() + vc["pnl_caucion"].sum()
        comp = vc["compensado"].sum() / vc["pesos_tomadoras"].sum() * 100
    variantes.append({"variante": nombre, "operaciones": len(ve), "retorno_pct": tot / CAPITAL * 100,
                      "compensado_pct": comp})
var = pd.DataFrame(variantes)
print("\n--- Sensibilidad a la regla de capital ---"); print(var.round(3).to_string(index=False))

res.to_csv(f"{DATA}/modeloA_resumen.csv")
pb.to_csv(f"{DATA}/modeloA_por_bloque.csv")
pi.to_csv(f"{DATA}/modeloA_por_instrumento_base.csv")
var.to_csv(f"{DATA}/modeloA_variantes_capital.csv", index=False)
pd.concat(curvas, axis=1, sort=True).to_csv(f"{DATA}/modeloA_curvas.csv")
