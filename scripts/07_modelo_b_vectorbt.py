"""
Modelo B — simulación con el motor de órdenes de VectorBT (Portfolio.from_orders).

Representación:
  * Cada especie tiene dos columnas-activo: su pata CI y su pata 24hs. Cada operación es un swap
    de MISMAS unidades Q = nocional / P_CI:
      coloco con títulos: compra Q en CI, vende Q en 24hs.
      tomo con títulos:   vende Q en CI, compra Q en 24hs.
    Las dos patas son el mismo título, así que se valúan al mismo precio de referencia: la
    posición neta de la especie vale 0 y el resultado del spread queda realizado en caja.
    La unidad "vendida" en una pata es entrega de inventario propio, no un short.
  * El bot no opera caución. La cobertura del operador sobre el neto de pesos de cada rueda se
    representa con dos activos sintéticos cuyo índice crece a la tasa neta del día:
      CAU_COL (colocadora, tasa - 0,045% anual) si sobran pesos;
      CAU_TOM (tomadora,   tasa + 0,045% anual) si faltan.
    Se abren en el último bucket de la rueda y se cancelan en el primero de la siguiente; se
    valúan al valor de rescate, así el interés se reconoce al cierre de la rueda.
  * Costos del título: `fees` del motor sobre el valor de cada orden.
  * Una sola bolsa de capital (cash_sharing). VectorBT ejecuta las dos patas en el mismo instante
    y no modela la liquidación T+0/T+1, así que los pesos que en la realidad cobra una tomadora
    hoy no aparecen en su caja: se usa un colchón de caja que no altera el resultado (el
    rendimiento se mide sobre el capital de 1.000.000).
"""
import glob
import os
import sys
import numpy as np
import pandas as pd
import vectorbt as vbt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (DATA, OUT, CAPITAL, COSTO_OP, CATEGORIA, ESCENARIOS, INVENTARIO_ESPECIE,
                    LIMITE_FALTANTE, BASE)

COLCHON = CAPITAL
INIT = CAPITAL + COLCHON

bars = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(
    f"{DATA}/bars_15min/*.parquet"))], ignore_index=True)
ev_all = pd.read_parquet(f"{DATA}/eventos.parquet")
cob_all = pd.read_parquet(f"{DATA}/cobertura_diaria.parquet")

simbolos = sorted(bars["simbolo"].unique())
fechas = sorted(bars["fecha"].unique())
# fila final para liquidar la última cobertura: próximo día hábil tras la última rueda,
# a la hora del primer bucket (las ventanas del diseño no tienen feriados)
_primer = bars.loc[bars["fecha"] == fechas[-1], "bucket"].min()
TERMINAL = pd.Timestamp(fechas[-1]) + pd.offsets.BDay(1) + (_primer - _primer.normalize())
index = pd.DatetimeIndex(sorted(bars["bucket"].unique())).append(pd.DatetimeIndex([TERMINAL]))
dia = pd.Series(index.strftime("%Y-%m-%d"), index=index)
k_de = dia.map({f: i for i, f in enumerate(fechas)}).fillna(len(fechas)).astype(int).values
primer_bucket = {k: index[np.argmax(k_de == k)] for k in range(len(fechas) + 1)}
ultimo_bucket = {k: index[len(k_de) - 1 - np.argmax(k_de[::-1] == k)] for k in range(len(fechas))}

leg_px = bars.pivot_table(index="bucket", columns=["simbolo", "vencimiento"], values="close")
leg_px = leg_px.reindex(index).ffill().bfill()
cols_bono = [f"{s}|{v}" for s in simbolos for v in ["CI", "24hs"]]
price_bono = pd.DataFrame({f"{s}|{v}": leg_px[(s, v)] for s in simbolos for v in ["CI", "24hs"]})
ref_bono = pd.DataFrame({f"{s}|{v}": leg_px[(s, "CI")] for s in simbolos for v in ["CI", "24hs"]})
columnas = cols_bono + ["CAU_COL", "CAU_TOM"]


def correr(esc: str, slippage: float = 0.0, verbose: bool = True):
    ev = ev_all[ev_all["escenario"] == esc].copy()
    cob = cob_all[cob_all["escenario"] == esc].set_index("fecha").reindex(fechas)

    # índices de caución (tasa neta del día y días de liquidación)
    fac_col = 1 + cob["r_col"].values * cob["d"].values / 365
    fac_tom = 1 + cob["r_tom"].values * cob["d"].values / 365
    P_col = np.concatenate([[1.0], np.cumprod(fac_col)])
    P_tom = np.concatenate([[1.0], np.cumprod(fac_tom)])
    k_next = np.minimum(k_de + 1, len(fechas))
    price = pd.concat([price_bono, pd.DataFrame({"CAU_COL": P_col[k_de], "CAU_TOM": P_tom[k_de]},
                                                index=index)], axis=1)[columnas]
    close = pd.concat([ref_bono, pd.DataFrame({"CAU_COL": P_col[k_next], "CAU_TOM": P_tom[k_next]},
                                              index=index)], axis=1)[columnas]

    size = pd.DataFrame(0.0, index=index, columns=columnas)
    q = (ev["nocional"] / ev["p_ci"]).values
    sg = np.where(ev["direccion"] == 1, 1.0, -1.0)      # signo en la pata CI (coloco compra CI)
    for b, sim, qq, s_ in zip(ev["bucket"], ev["simbolo"], q, sg):
        size.at[b, f"{sim}|CI"] += s_ * qq
        size.at[b, f"{sim}|24hs"] -= s_ * qq
    # cobertura del neto: abre al cierre de la rueda k, cancela al abrir la rueda k+1
    for k, f in enumerate(fechas):
        neto = cob.loc[f, "neto_cierre"]
        if abs(neto) < 1e-9:
            continue
        col, P = ("CAU_COL", P_col) if neto > 0 else ("CAU_TOM", P_tom)
        u = abs(neto) / P[k]
        sgn = 1.0 if neto > 0 else -1.0                   # colocar = comprar; tomar = vender
        size.at[ultimo_bucket[k], col] += sgn * u
        size.at[primer_bucket[k + 1], col] -= sgn * u
    size = size.where(size.abs() > 1e-12)

    fees = np.array([COSTO_OP[CATEGORIA[c.split("|")[0]]] for c in cols_bono] + [0.0, 0.0])
    slip = np.array([slippage] * len(cols_bono) + [0.0, 0.0])
    pf = vbt.Portfolio.from_orders(
        close=close, size=size, size_type="amount", direction="both", price=price,
        fees=fees[None, :], slippage=slip[None, :], init_cash=INIT, cash_sharing=True,
        group_by=True, call_seq="auto", allow_partial=False, raise_reject=True, freq="15min")

    pos = pf.assets()
    valor = pf.value() - COLCHON
    diario = valor.iloc[:-1].groupby(dia.iloc[:-1].values).last()
    out = {
        "escenario": esc, "slippage_bps": slippage * 1e4,
        "retorno_pct": (valor.iloc[-1] / CAPITAL - 1) * 100,
        "pnl_total": valor.iloc[-1] - CAPITAL,
        "max_dd_intradiario_pct": (valor / valor.cummax() - 1).min() * 100,
        "max_dd_diario_pct": (diario / diario.cummax() - 1).min() * 100,
        "dias_positivos": int((diario.diff().fillna(diario.iloc[0] - CAPITAL) > 0).sum()),
        "ordenes": int(pf.orders.count()), "ordenes_esperadas": int(size.notna().sum().sum()),
        "max_posicion_neta": max(abs(pos[f"{s}|CI"] + pos[f"{s}|24hs"]).max() for s in simbolos),
        "caucion_abierta_final": float(pos[["CAU_COL", "CAU_TOM"]].iloc[-1].abs().max()),
    }
    if slippage == 0:
        # verificación independiente de los límites, desde el registro de órdenes del motor
        o = pf.orders.records_readable
        o = o[o["Column"].str.endswith("|CI")].copy()
        o["especie"] = o["Column"].str.split("|").str[0]
        o["fecha"] = o["Timestamp"].dt.strftime("%Y-%m-%d")
        o["afuera"] = np.where(o["Side"] == "Sell", 1, -1) * o["Size"] * o["Price"]  # tomo = vende CI
        # dentro de un mismo bucket el bot procesa primero las tomadoras (venta de CI)
        o["orden"] = np.where(o["Side"] == "Sell", 0, 1)
        o = o.sort_values(["Timestamp", "orden"], kind="stable")
        out["max_inventario_afuera"] = o.groupby(["fecha", "especie"])["afuera"].cumsum().max()
        out["max_faltante_pesos"] = -o.groupby("fecha")["afuera"].cumsum().min()
    if verbose:
        print(f"[{esc} | slippage {slippage*1e4:.0f} bps] retorno {out['retorno_pct']:.3f}% | "
              f"DD intradiario {out['max_dd_intradiario_pct']:.3f}% / diario {out['max_dd_diario_pct']:.3f}% | "
              f"órdenes {out['ordenes']}/{out['ordenes_esperadas']} | posición neta máx {out['max_posicion_neta']:.1e} | "
              f"caución abierta final {out['caucion_abierta_final']:.1e}"
              + (f" | inventario afuera máx {out['max_inventario_afuera']:,.0f} | faltante máx {out['max_faltante_pesos']:,.0f}"
                 if slippage == 0 else ""))
    return out, valor, pf


if __name__ == "__main__":
    res, curvas = [], {}
    for esc in ESCENARIOS:
        o, v, pf = correr(esc)
        res.append(o); curvas[esc] = v
        if esc == BASE:
            pf.orders.records_readable.to_csv(f"{DATA}/modeloB_ordenes_base.csv", index=False)
    pd.DataFrame(res).set_index("escenario").to_csv(f"{DATA}/modeloB_resumen.csv")
    pd.DataFrame(curvas).to_csv(f"{DATA}/modeloB_curvas.csv")
    print("\n--- Sensibilidad a slippage (escenario base: VWAP de la rueda anterior) ---")
    sens = [correr(BASE, slippage=s)[0] for s in [0.0, 0.0001, 0.0002, 0.0003, 0.0005]]
    pd.DataFrame(sens).to_csv(f"{DATA}/modeloB_slippage.csv", index=False)
