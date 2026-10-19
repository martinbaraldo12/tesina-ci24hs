"""
Sizing secuencial con reinversión de pesos (común a los dos modelos).

Operatoria del bot (definida con el operador):
  * "Tomo con títulos" (vendo CI de cartera, recompro 24hs): necesita inventario de la especie
    y GENERA pesos hoy. Tope: INVENTARIO_ESPECIE por especie (el título vuelve en T+1, o antes si
    una colocadora posterior de la misma especie recompra CI).
  * "Coloco con títulos" (compro CI, vendo 24hs): USA pesos hoy. Se financia primero con los
    pesos que generaron las tomadoras del día (en cualquier especie); si no alcanzan, el faltante
    lo cubre el operador tomando caución, hasta LIMITE_FALTANTE.
  * Simétricamente, una tomadora posterior devuelve los pesos que usó una colocadora previa.
  * El bot NO opera caución: el saldo neto de pesos al cierre del día lo cubre el operador
    (colocando si sobra, tomando si falta).

Umbral de cada operación según el saldo de pesos del bot (P) al momento de operar:
  * colocadora con P > 0 (pesos propios): compite contra caución COLOCADORA -> edge1_col
    colocadora con P <= 0 (faltante):     compite contra caución TOMADORA   -> edge1
  * tomadora con P < 0 (cubre faltante):  compite contra caución TOMADORA   -> edge2_tom
    tomadora con P >= 0 (sobrante):       compite contra caución COLOCADORA -> edge2
  Si una operación solo es rentable en el primer caso, se limita a la parte que compensa saldo.

Tamaño pedido por señal: POS_BASE del capital repartido entre las señales del bucket con peso igual
(versión 1), en proporción al edge (versiones 2 y 3) o en un punto intermedio (raíz del edge o mitad y
mitad), con tope TOPE_POSICION y, opcionalmente, un tope de liquidez por especie. Dentro de un bucket se
procesan primero las tomadoras.
"""
import os
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (DATA, OUT, CAPITAL, POS_BASE, TOPE_POSICION, INVENTARIO_ESPECIE, LIMITE_FALTANTE,
                    ESCENARIOS)


def dimensionar(sig_esc: pd.DataFrame, inventario=INVENTARIO_ESPECIE, limite=LIMITE_FALTANTE,
                reinversion=True, capital=CAPITAL, tope_orden=None, ponderacion="igual", umbral_edge=0.0,
                pos_base=None):
    """Devuelve (eventos, cobertura_diaria). Si reinversion=False, reproduce la regla anterior
    (capacidad bruta: la suma de nocionales del día no puede superar el capital).
    tope_orden: dict especie -> máximo en pesos por orden (límite de liquidez; None = sin límite), o
    dict (fecha, especie) -> máximo, para un tope que cambia por rueda."""
    if not reinversion:
        return _regla_anterior(sig_esc)
    c = sig_esc[sig_esc["candidata"] > 0].sort_values(["fecha", "bucket", "simbolo"]).copy()
    # mejor edge disponible de la señal (para el umbral y para ponderar por edge)
    e1 = np.maximum(c["edge1"], c["edge1_col"]); e2 = np.maximum(c["edge2"], c["edge2_tom"])
    c["edge_cand"] = np.select([c["candidata"] == 1, c["candidata"] == 2], [e1, e2], default=np.maximum(e1, e2))
    if umbral_edge > 0:
        c = c[c["edge_cand"] > umbral_edge].copy()
    c["n"] = c.groupby(["fecha", "bucket"])["simbolo"].transform("count")
    if ponderacion == "edge":       # el presupuesto del bucket se reparte en proporción al edge de cada señal
        peso = c["edge_cand"] / c.groupby(["fecha", "bucket"])["edge_cand"].transform("sum")
    elif ponderacion == "raiz":     # punto intermedio: en proporción a la raíz del edge
        r_ = np.sqrt(c["edge_cand"].clip(lower=0))
        peso = r_ / r_.groupby([c["fecha"], c["bucket"]]).transform("sum")
    elif ponderacion == "mixta":    # punto intermedio: mitad en partes iguales, mitad en proporción al edge
        peso = 0.5 / c["n"] + 0.5 * c["edge_cand"] / c.groupby(["fecha", "bucket"])["edge_cand"].transform("sum")
    else:                           # peso igual entre las señales del bucket
        peso = 1.0 / c["n"]
    c["pedido"] = np.minimum((POS_BASE if pos_base is None else pos_base) * peso, TOPE_POSICION) * capital
    if tope_orden is not None:
        if tope_orden and isinstance(next(iter(tope_orden)), tuple):     # tope por (fecha, especie)
            tp = pd.Series([tope_orden.get(k, np.inf) for k in zip(c["fecha"], c["simbolo"])], index=c.index)
        else:                                                              # tope fijo por especie
            tp = c["simbolo"].map(tope_orden).fillna(np.inf)
        c["pedido"] = np.minimum(c["pedido"], tp)
    c["orden"] = np.select([c["candidata"] == 2, c["candidata"] == 3], [0, 1], default=2)  # tomadoras primero
    c = c.sort_values(["fecha", "bucket", "orden", "simbolo"])

    filas, dias = [], []
    for fecha, gd in c.groupby("fecha", sort=True):
        afuera = {}      # inventario afuera por especie (+ tomo, - coloco)
        P = 0.0          # saldo de pesos del bot en el día (+ generados por tomadoras)
        usado = 0.0      # solo regla anterior
        tomo_tot = coloco_tot = 0.0
        for _, x in gd.iterrows():
            k, N = x["simbolo"], x["pedido"]
            if not reinversion:
                if x["direccion"] == 0:
                    continue
                q = min(N, max(CAPITAL - usado, 0.0)); usado += q
                dirn = x["direccion"]
            else:
                # Cada dirección tiene dos zonas según el saldo de pesos P del bot:
                #  tomo:   zona A = devolver pesos que usó una colocadora (evita caución tomadora, edge2_tom);
                #          zona B = pesos que sobran y se colocan (caución colocadora, edge2).
                #  coloco: zona A = usar pesos de tomadoras (costo de oportunidad colocadora, edge1_col);
                #          zona B = faltante que cubre el operador tomando caución (edge1).
                # Primero se usa la zona A; la B solo si la A se agotó y su edge es positivo.
                # Con una sola tasa de caución esto es idéntico a la regla de la tercera entrega.
                dirn = x["candidata"]
                if dirn == 3:                  # rentable en las dos direcciones (solo caución favorable)
                    dirn = 2 if P >= 0 else 1  # se extiende el neto del lado en que ya está
                if dirn == 2:                  # tomo con títulos
                    disp = max(inventario - afuera.get(k, 0.0), 0.0)
                    zona_a = min(max(-P, 0.0), disp)
                    qa = min(N, zona_a) if x["edge2_tom"] > 0 else 0.0
                    ok_b = x["edge2"] > 0 and (qa >= zona_a - 1e-9)
                    q = qa + (min(N - qa, disp - qa) if ok_b else 0.0)
                else:                          # coloco con títulos
                    disp = max(P + limite, 0.0)
                    zona_a = min(max(P, 0.0), disp)
                    qa = min(N, zona_a) if x["edge1_col"] > 0 else 0.0
                    ok_b = x["edge1"] > 0 and (qa >= zona_a - 1e-9)
                    q = qa + (min(N - qa, disp - qa) if ok_b else 0.0)
            if q <= 1e-6:
                continue
            P_antes = P
            if dirn == 2:
                afuera[k] = afuera.get(k, 0.0) + q; P += q; tomo_tot += q
            else:
                afuera[k] = afuera.get(k, 0.0) - q; P -= q; coloco_tot += q
            filas.append({**x.to_dict(), "direccion_op": dirn, "nocional": q, "P_antes": P_antes})
        dias.append({"fecha": fecha, "bloque": gd["bloque"].iloc[0], "d": gd["d"].iloc[0],
                     "r_col": gd["r_col"].iloc[0], "r_tom": gd["r_tom"].iloc[0],
                     "pesos_tomadoras": tomo_tot, "pesos_colocadoras": coloco_tot,
                     "neto_cierre": tomo_tot - coloco_tot})
    ev = pd.DataFrame(filas)
    ev["direccion"] = ev["direccion_op"]
    ev = ev.drop(columns=["direccion_op", "orden", "n", "edge_cand"])
    # Resultado de las patas del título (sin caución): tomo = -N(s + f(2+s)); coloco = N(s - f(2+s))
    s, f = ev["spread_pct"], ev["f"]
    ev["pnl_bono"] = np.where(ev["direccion"] == 2, -ev["nocional"] * (s + f * (2 + s)),
                              ev["nocional"] * (s - f * (2 + s)))
    cob = pd.DataFrame(dias)
    # Cobertura del operador sobre el neto del día (caución colocadora si sobra, tomadora si falta)
    cob["pnl_caucion"] = np.where(cob["neto_cierre"] > 0,
                                  cob["neto_cierre"] * cob["r_col"] * cob["d"] / 365,
                                  cob["neto_cierre"] * cob["r_tom"] * cob["d"] / 365)
    cob["compensado"] = np.minimum(cob["pesos_tomadoras"], cob["pesos_colocadoras"])
    return ev.reset_index(drop=True), cob


def _regla_anterior(sig_esc):
    """Regla de la versión previa: cada operación se cubre sola con caución y la suma bruta de
    nocionales del día no puede superar el capital (escala proporcional dentro del bucket)."""
    ev = sig_esc[sig_esc["direccion"] > 0].sort_values(["fecha", "bucket", "simbolo"]).copy()
    ev["n"] = ev.groupby(["fecha", "bucket"])["simbolo"].transform("count")
    ev["pedido"] = np.minimum(POS_BASE / ev["n"], TOPE_POSICION) * CAPITAL
    ev["nocional"] = 0.0
    for _, g in ev.groupby("fecha", sort=False):
        usado = 0.0
        for _, gb in g.groupby("bucket", sort=True):
            pedido = gb["pedido"].sum()
            esc = min(1.0, max(CAPITAL - usado, 0.0) / pedido)
            ev.loc[gb.index, "nocional"] = gb["pedido"] * esc
            usado += pedido * esc
    ev = ev[ev["nocional"] > 1e-6].reset_index(drop=True)
    return ev, None


if __name__ == "__main__":
    sig = pd.read_parquet(f"{DATA}/spread_signal.parquet")
    evs, cobs = [], []
    for esc in ESCENARIOS:
        ev, cob = dimensionar(sig[sig["escenario"] == esc])
        ev["escenario"] = esc; cob["escenario"] = esc
        evs.append(ev); cobs.append(cob)
        comp = cob["compensado"].sum() / cob["pesos_tomadoras"].sum() * 100
        print(f"[{esc}] operaciones {len(ev)} (tomo {int((ev.direccion==2).sum())} / coloco "
              f"{int((ev.direccion==1).sum())}) | pesos de tomadoras {cob.pesos_tomadoras.sum()/1e6:.1f}M, "
              f"compensados por el bot {comp:.1f}% | neto medio cubierto con caución "
              f"{cob.neto_cierre.abs().mean()/1e3:,.0f}k | resultado "
              f"{(ev.pnl_bono.sum() + cob.pnl_caucion.sum())/CAPITAL*100:.3f}%")
    eventos = pd.concat(evs, ignore_index=True)
    cobertura = pd.concat(cobs, ignore_index=True)
    eventos.to_parquet(f"{DATA}/eventos.parquet", index=False)
    cobertura.to_parquet(f"{DATA}/cobertura_diaria.parquet", index=False)
    # copias legibles en Excel (separador ; y coma decimal)
    cols = ["escenario", "fecha", "bloque", "bucket", "simbolo", "direccion", "nocional", "p_ci",
            "p_24", "spread_pct", "tasa_implicita_anual", "caucion", "edge1", "edge2", "P_antes", "pnl_bono"]
    eventos[cols].assign(direccion=eventos["direccion"].map({1: "coloco", 2: "tomo"})).to_csv(
        f"{DATA}/operaciones.csv", index=False, sep=";", decimal=",")
    cobertura.to_csv(f"{DATA}/cobertura_diaria.csv", index=False, sep=";", decimal=",")
