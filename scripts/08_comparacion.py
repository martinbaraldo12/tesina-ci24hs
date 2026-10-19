"""Reconciliación Modelo A (pandas) vs Modelo B (VectorBT) y chequeo analítico del slippage."""
import os
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import DATA, OUT, CAPITAL, ESCENARIOS, BASE

D = f"{DATA}/"
A = pd.read_csv(D + "modeloA_resumen.csv", index_col=0)
B = pd.read_csv(D + "modeloB_resumen.csv", index_col=0)
ca = pd.read_csv(D + "modeloA_curvas.csv", index_col=0, parse_dates=True)
cb = pd.read_csv(D + "modeloB_curvas.csv", index_col=0, parse_dates=True)
ev = pd.read_parquet(D + "eventos.parquet")
cob = pd.read_parquet(D + "cobertura_diaria.parquet")

filas = []
for esc in ESCENARIOS:
    a_path = ca[esc].dropna().reindex(cb.index).ffill().fillna(CAPITAL)
    filas.append({
        "escenario": esc, "retorno_A_pct": A.loc[esc, "retorno_pct"], "retorno_B_pct": B.loc[esc, "retorno_pct"],
        "pnl_A": A.loc[esc, "pnl_total"], "pnl_B": B.loc[esc, "pnl_total"],
        "dif_pnl_total": B.loc[esc, "pnl_total"] - A.loc[esc, "pnl_total"],
        "dif_max_curva": (a_path - cb[esc]).abs().max(),
        "eventos": int(A.loc[esc, "eventos"]), "ordenes_B": int(B.loc[esc, "ordenes"]),
    })
rec = pd.DataFrame(filas).set_index("escenario")
print("=== Reconciliación A vs B ===")
print(rec.to_string(float_format=lambda x: f"{x:,.6f}"))
rec.to_csv(D + "comparacion_AB.csv")

# --- Slippage: fórmula exacta vs motor ---
e = ev[ev["escenario"] == BASE]
c = cob[cob["escenario"] == BASE]
sp, f, N = e["spread_pct"], e["f"], e["nocional"]
S = pd.read_csv(D + "modeloB_slippage.csv")
filas = []
for _, row in S.iterrows():
    s = row["slippage_bps"] / 1e4
    tomo = N * ((1 - s) * (1 - f) - (1 + sp) * (1 + s) * (1 + f))
    coloco = N * ((1 + sp) * (1 - s) * (1 - f) - (1 + s) * (1 + f))
    patas = np.where(e["direccion"] == 2, tomo, coloco)
    total = patas.sum() + c["pnl_caucion"].sum()
    # resultado de cada operación si se cubriera sola con caución (para medir cuántas pierden)
    solo = patas + np.where(e["direccion"] == 2, N * e["r_col"] * e["d"] / 365, -N * e["r_tom"] * e["d"] / 365)
    filas.append({"slippage_bps": row["slippage_bps"], "retorno_motor_pct": row["retorno_pct"],
                  "retorno_formula_pct": total / CAPITAL * 100,
                  "operaciones_con_perdida_pct": (solo < 0).mean() * 100,
                  "max_dd_diario_pct": row["max_dd_diario_pct"]})
sl = pd.DataFrame(filas)
x, y = sl["slippage_bps"].values, sl["retorno_motor_pct"].values
pend = (y[-1] - y[-2]) / (x[-1] - x[-2])
be = x[-1] - y[-1] / pend
print("\n=== Slippage: motor vs fórmula exacta ===")
print(sl.round(4).to_string(index=False))
print(f"\nSlippage de equilibrio (retorno 0): {be:.2f} bps por pata")
sl.to_csv(D + "comparacion_slippage.csv", index=False)
pd.Series({"breakeven_bps": be}).to_csv(D + "breakeven_slippage.csv")
