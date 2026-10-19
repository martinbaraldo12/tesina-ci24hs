"""
Paso 15 — Versiones de la estrategia (1 y 2, anteriores; 3, definitiva), bases de capital y volatilidad.

Versión 1 (anterior): la estrategia testeada en la tercera entrega. El presupuesto del bucket se reparte con
  peso igual entre las señales y el bot opera con cualquier edge positivo, neto de derechos y caución.
Versión 2 (anterior): presupuesto del bucket en proporción al edge y el bot descuenta medio tick por pata
  (el costo esperado de cruzar la punta) antes de decidir.
Versión 3 (definitiva del modelo): completa la versión 2 con las dos reglas del diseño de la segunda
  entrega que la versión 1 no implementaba:
    - margen de seguridad: el bot exige que el edge supere MARGEN_TICKS_V3 ticks por pata (medio tick de
      costo esperado más un colchón igual por ruido de ejecución);
    - tope de liquidez: cada orden hasta PARTICIPACION del volumen promedio por bucket de la pata CI.
  Como la 2, ejecuta primero la pata CI y después cubre en 24hs.
Se prueban además las reglas por separado y dos puntos intermedios entre la 1 y la 2 (presupuesto por
la raíz del edge, y mitad en partes iguales y mitad por edge).

Ejecución: costo pagado de 0, ½ o 1 tick por pata x demora de la pata 24hs (CI primero) de 0 a 900 s.
Escenario realista: COSTO_REALISTA_TICKS por pata y DEMORA_REALISTA_S. Impacto por tamaño (ilustrativo,
no calibrado): una orden igual al tope de liquidez paga un tick extra por pata, en proporción al tamaño.

Salidas (data/):
  versiones.csv           grilla costo x demora por versión, con atribución por especie
  versiones_impacto.csv   escenario realista con impacto por tamaño
  versiones_vida.csv      las dos patas con demora (vida útil de la señal)
  versiones_periodos.csv  resultado por rueda en los bloques de 2025 y de 2026 (control fuera de muestra)
  margen_v3.csv           barrido del margen de seguridad (capital x costo)
  robustez_v3.csv         robustez y sensibilidad de la versión 3 en el escenario realista
  spreads_grandes.csv     parte del resultado realista que viene de spreads mayores a ±0,5%
  dia_semana.csv          resultado por día de la semana (análogo del día de rebalanceo)
  horario.csv             resultado por hora y sin la primera/última hora, mañana o tarde
  ejecucion_precios.csv   cierre del bucket vs. apertura, OHLC/4 y promedio de precios del bucket siguiente
  comisiones.csv          comisiones de broker: bot que las paga sin cambiar y bot que las incorpora; equilibrio
  liquidez_v3.csv         tamaño de las órdenes de la versión 3 frente al volumen de la pata CI
  tope_exante.csv         versión 3 con el tope de liquidez calculado solo con ruedas anteriores (sin información futura)
  versiones_bloques.csv, versiones_ruedas.csv, bases_capital.csv, versiones_escala.csv,
  puente_tercera.csv, volatilidad_bloques.csv
  output/grafico8_versiones.png
"""
import glob
import importlib.util
import json
import os
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (DATA, OUT, BASE, CAPITAL, INVENTARIO_ESPECIE, LIMITE_FALTANTE, BLOQUE_LABEL, BLOQUE_ORDEN,
                    ESCENARIOS, MARGEN_TICKS_V3, COSTO_REALISTA_TICKS, DEMORA_REALISTA_S)
from ejecucion_comun import ORDEN, tick_de, patas, resumen, descontar_costo, precios_demora, caucion_sola

spec = importlib.util.spec_from_file_location("sizing", os.path.join(os.path.dirname(__file__), "05_sizing.py"))
sizing = importlib.util.module_from_spec(spec); spec.loader.exec_module(sizing)

COSTOS = [0.0, 0.5, 1.0]
DEMORAS = [0, 5, 30, 60, 300, 900]
REALISTA = (COSTO_REALISTA_TICKS, DEMORA_REALISTA_S)
BLOQUES_2025 = {"estres_2025", "calma_dic_2025"}
pd.set_option("display.width", 250)

sig_all = pd.read_parquet(f"{DATA}/spread_signal.parquet")
sig = sig_all[sig_all["escenario"] == BASE].reset_index(drop=True)
liq = pd.read_csv(f"{DATA}/liquidez_ci.csv")
TOPE = dict(zip(liq["simbolo"], liq["tope_orden"]))

# nombre, margen del bot (ticks por pata), ponderación, tope de liquidez
VERSIONES = {
    "V1": ("Versión 1 (anterior)", 0.0, "igual", False),
    "solo_edge": ("Solo presupuesto por edge", 0.0, "edge", False),
    "solo_desc": ("Solo descuenta medio tick", 0.5, "igual", False),
    "V2": ("Versión 2 (anterior)", 0.5, "edge", False),
    "raiz": ("Intermedia: raíz del edge + medio tick", 0.5, "raiz", False),
    "mixta": ("Intermedia: mitad igual, mitad edge + medio tick", 0.5, "mixta", False),
    "V3": ("Versión 3 (definitiva)", MARGEN_TICKS_V3, "edge", True),
}


def correr(margen, pond, con_tope, sg=sig, C=CAPITAL, inv=None, lim=None):
    s2 = descontar_costo(sg, margen) if margen > 0 else sg
    ev, cob = sizing.dimensionar(s2, ponderacion=pond, capital=C, tope_orden=TOPE if con_tope else None,
                                 inventario=INVENTARIO_ESPECIE * C / CAPITAL if inv is None else inv,
                                 limite=LIMITE_FALTANTE * C / CAPITAL if lim is None else lim)
    return ev.reset_index(drop=True), cob


def slip(ev, mult, impacto=False):
    """Slippage pagado por pata: mult ticks de la especie y, con impacto, un tick extra por cada tope de
    liquidez que ocupa la orden (proporcional al tamaño)."""
    t = tick_de(ev)
    s = mult * t
    if impacto:
        s = s + t * ev["nocional"] / ev["simbolo"].map(TOPE)
    return s


def pat(ev, clave, mult, seg, impacto=False, ambas=False):
    """Resultado de las patas: la CI a la señal (o con demora si ambas) y la 24hs `seg` segundos después."""
    s = slip(ev, mult, impacto)
    pci = precios_demora(ev, "CI", seg, clave) if ambas else ev["p_ci"].values
    return patas(ev, pci, precios_demora(ev, "24hs", seg, clave), s, s)


def diario(ev, cob, p):
    d = pd.Series(p, index=ev.index).groupby(ev["fecha"]).sum()
    c = cob.set_index("fecha")
    return (d.reindex(c.index).fillna(0) + c["pnl_caucion"]).rename("pnl").to_frame().assign(bloque=c["bloque"], d=c["d"])


corridas = {k: correr(m, p, t) for k, (_, m, p, t) in VERSIONES.items()}
ref = pd.read_csv(f"{DATA}/modeloA_resumen.csv", index_col=0).loc[BASE, "pnl_total"]
ev1, cob1 = corridas["V1"]
assert abs(ev1["pnl_bono"].sum() + cob1["pnl_caucion"].sum() - ref) < 1e-6, "la versión 1 no coincide con la base"

# ---------------- 1) grilla costo x demora (CI primero) ----------------
filas = []
for k, (nombre, *_r) in VERSIONES.items():
    ev, cob = corridas[k]
    for mult in COSTOS:
        for seg in DEMORAS:
            filas.append(resumen(nombre, ev, pat(ev, k, mult, seg), cob, version=k, costo_ticks=mult, demora_s=seg))
res = pd.DataFrame(filas)
res.to_csv(f"{DATA}/versiones.csv", index=False)
print("Resultado total (%) por versión, costo pagado y demora de la pata 24hs (CI primero):")
print(res.pivot_table(index=["version", "costo_ticks"], columns="demora_s", values="retorno_pct", sort=False).round(2))

# impacto por tamaño en el escenario realista
imp = pd.DataFrame([resumen(VERSIONES[k][0], corridas[k][0], pat(corridas[k][0], k, *REALISTA, impacto=True),
                            corridas[k][1], version=k) for k in VERSIONES])
imp.to_csv(f"{DATA}/versiones_impacto.csv", index=False)
print("\nRealista con impacto por tamaño:", dict(zip(imp.version, imp.retorno_pct.round(2))))

# vida útil de la señal: las dos patas con demora, con el costo realista
vida = pd.DataFrame([resumen(VERSIONES[k][0], corridas[k][0], pat(corridas[k][0], k, COSTO_REALISTA_TICKS, s, ambas=True),
                             corridas[k][1], version=k, demora_s=s) for k in ["V1", "V2", "V3"] for s in [0, 30, 60, 300, 900]])
vida.to_csv(f"{DATA}/versiones_vida.csv", index=False)
print("\nLas dos patas con demora (medio tick):")
print(vida.pivot_table(index="version", columns="demora_s", values="retorno_pct", sort=False).round(2))

# ---------------- 2) control fuera de muestra: bloques de 2025 vs. 2026 ----------------
per = []
for k in VERSIONES:
    ev, cob = corridas[k]
    d = diario(ev, cob, pat(ev, k, *REALISTA))
    en25 = d["bloque"].isin(BLOQUES_2025)
    per.append({"version": k, "nombre": VERSIONES[k][0], "ruedas_2025": int(en25.sum()), "ruedas_2026": int((~en25).sum()),
                "bps_2025": d.loc[en25, "pnl"].mean() / CAPITAL * 1e4, "bps_2026": d.loc[~en25, "pnl"].mean() / CAPITAL * 1e4})
per = pd.DataFrame(per)
per["rank_2025"] = per["bps_2025"].rank(ascending=False).astype(int)
per["rank_2026"] = per["bps_2026"].rank(ascending=False).astype(int)
per.to_csv(f"{DATA}/versiones_periodos.csv", index=False)
print("\nControl 2025 (elección) vs. 2026 (prueba), escenario realista, bps por rueda:")
print(per.round(2).to_string(index=False))

# ---------------- 3) por bloque y por rueda ----------------
ruedas = []
for k in ["V1", "V2", "V3"]:
    ev, cob = corridas[k]
    for (mult, seg), esc in [((0.0, 0), "ideal"), (REALISTA, "realista")]:
        r = diario(ev, cob, pat(ev, k, mult, seg)).reset_index()
        r["version"], r["escenario"] = k, esc
        ruedas.append(r)
ruedas = pd.concat(ruedas, ignore_index=True)
ruedas["ret_bps"] = ruedas["pnl"] / CAPITAL * 1e4
ruedas.to_csv(f"{DATA}/versiones_ruedas.csv", index=False)
blq = (ruedas.groupby(["escenario", "version", "bloque"])
       .agg(ruedas=("fecha", "count"), retorno_pct=("pnl", lambda x: x.sum() / CAPITAL * 100),
            bps_por_rueda=("ret_bps", "mean"), ruedas_negativas=("pnl", lambda x: int((x < 0).sum())))
       .reset_index())
blq["orden"] = blq["bloque"].map({b: i for i, b in enumerate(BLOQUE_ORDEN)})
blq = blq.sort_values(["escenario", "version", "orden"]).drop(columns="orden")
blq["label"] = blq["bloque"].map(BLOQUE_LABEL)
blq.to_csv(f"{DATA}/versiones_bloques.csv", index=False)
print("\nPor bloque (bps por rueda):")
print(blq.pivot_table(index="label", columns=["escenario", "version"], values="bps_por_rueda", sort=False).round(1))
piv = ruedas.pivot_table(index=["escenario", "fecha"], columns="version", values="pnl")
for esc in ["ideal", "realista"]:
    p = piv.loc[esc]
    print(f"{esc}: V3 > V1 en {(p['V3'] > p['V1']).sum()} ruedas; V3 > V2 en {(p['V3'] > p['V2']).sum()} de {len(p)}")


# ---------------- 4) bases de capital ----------------
def recursos(ev):
    """Recorre las operaciones en el orden del sizing y mide el inventario afuera por especie y el saldo
    de pesos del bot (+ generados por tomadoras, - usados por colocadoras) a lo largo de cada rueda."""
    max_esp = {s: 0.0 for s in ORDEN}
    max_simul, falt_max, sobr_max, diarios = 0.0, 0.0, 0.0, []
    for _, g in ev.groupby("fecha", sort=True):
        afuera = {s: 0.0 for s in ORDEN}
        P, max_dia = 0.0, 0.0
        for s, dirn, q in zip(g["simbolo"], g["direccion"], g["nocional"]):
            afuera[s] += q if dirn == 2 else -q
            P += q if dirn == 2 else -q
            max_esp[s] = max(max_esp[s], afuera[s])
            max_dia = max(max_dia, sum(max(v, 0.0) for v in afuera.values()))
            falt_max, sobr_max = max(falt_max, -P), max(sobr_max, P)
        diarios.append(max_dia)
        max_simul = max(max_simul, max_dia)
    return {"inventario_requerido": sum(max_esp.values()), "inventario_max_simultaneo": max_simul,
            "inventario_medio_diario": float(np.mean(diarios)), "faltante_max": falt_max, "sobrante_max": sobr_max}


dias_caucion = int(cob1["d"].sum())          # días corridos de financiamiento que cubre la muestra
n_ruedas = len(cob1)
bases = []
for k in ["V1", "V2", "V3"]:
    ev, cob = corridas[k]
    rec = recursos(ev)
    # sensibilidad de la cobertura: cuánto cambia el resultado si el operador cubre el neto 1 pp peor
    rec["cobertura_1pp_pct"] = (cob["neto_cierre"].abs() * cob["d"]).sum() / 365 * 0.01 / CAPITAL * 100
    rec["orden_media"] = ev["nocional"].mean()
    rec["orden_media_slv_ymcio"] = ev.loc[ev["simbolo"].isin(["SLV", "YMCIO"]), "nocional"].mean()
    rec["operaciones"] = len(ev)
    rec.update({f"ops_{s}": int((ev["simbolo"] == s).sum()) for s in ORDEN})
    for esc, (mult, seg) in [("ideal", (0.0, 0)), ("realista", REALISTA)]:
        pnl = pat(ev, k, mult, seg).sum() + cob["pnl_caucion"].sum()
        denominadores = {
            "Capital nominal del modelo (1.000.000)": CAPITAL,
            "Inventario que necesita (máximo por especie, sumado)": rec["inventario_requerido"],
            "Recursos usados: inventario + faltante máximo de pesos": rec["inventario_requerido"] + rec["faltante_max"],
            "Recursos asignados: inventario 900.000 + línea de pesos 1.000.000":
                INVENTARIO_ESPECIE * len(ORDEN) + LIMITE_FALTANTE,
        }
        for base_nom, den in denominadores.items():
            r = pnl / den * 100
            bases.append({"version": k, "escenario": esc, "base": base_nom, "monto_base": den, "pnl": pnl,
                          "retorno_pct": r, "tna_equivalente_pct": r * 365 / dias_caucion,
                          "bps_por_rueda": pnl / den * 1e4 / n_ruedas, **rec,
                          "nocional_por_rueda": ev["nocional"].sum() / n_ruedas,
                          "dias_caucion": dias_caucion, "ruedas": n_ruedas})
bases = pd.DataFrame(bases)
bases.to_csv(f"{DATA}/bases_capital.csv", index=False)
print(f"\nBases de capital ({n_ruedas} ruedas, {dias_caucion} días de caución):")
print(bases[["version", "escenario", "base", "monto_base", "retorno_pct", "tna_equivalente_pct"]].round(2).to_string(index=False))
print(bases.drop_duplicates("version")[["version", "operaciones", "inventario_requerido", "inventario_max_simultaneo",
                                         "inventario_medio_diario", "faltante_max", "sobrante_max", "orden_media",
                                         "orden_media_slv_ymcio"]].round(0).to_string(index=False))

# ---------------- 5) escalabilidad con límite de liquidez, costo, demora e impacto ----------------
escala = []
for k in ["V1", "V2", "V3"]:
    _, m, pond, _t = VERSIONES[k]
    for C in [1e6, 5e6, 10e6, 50e6, 100e6]:
        ev, cob = correr(m, pond, True, C=C)          # con el tope de liquidez para las tres versiones
        clave = f"esc_{k}_{C:.0f}"
        for esc, mult, seg, impacto in [("ideal", 0.0, 0, False), ("realista", *REALISTA, False), ("realista_impacto", *REALISTA, True)]:
            pnl = pat(ev, clave, mult, seg, impacto).sum() + cob["pnl_caucion"].sum()
            escala.append({"version": k, "escenario": esc, "capital": C, "operaciones": len(ev), "pnl": pnl,
                           "retorno_pct": pnl / C * 100})
escala = pd.DataFrame(escala)
escala.to_csv(f"{DATA}/versiones_escala.csv", index=False)
print("\nEscalabilidad con orden <= tope de liquidez (retorno %):")
print(escala.pivot_table(index="capital", columns=["escenario", "version"], values="retorno_pct").round(2))

# ---------------- 6) margen de seguridad de la versión 3 ----------------
margen = []
for C in [1e6, 10e6, 100e6]:
    for mg in [0.5, 1.0, 1.5, 2.0, 3.0]:
        ev, cob = correr(mg, "edge", True, C=C)
        clave = f"mg_{mg}_{C:.0f}"
        for cnom, mult, impacto in [("medio tick", 0.5, False), ("medio tick + impacto", 0.5, True), ("un tick", 1.0, False)]:
            pnl = pat(ev, clave, mult, DEMORA_REALISTA_S, impacto).sum() + cob["pnl_caucion"].sum()
            margen.append({"capital": C, "margen_ticks": mg, "costo": cnom, "operaciones": len(ev), "retorno_pct": pnl / C * 100})
margen = pd.DataFrame(margen)
margen.to_csv(f"{DATA}/margen_v3.csv", index=False)
print("\nMargen de seguridad (ticks por pata) — retorno %:")
print(margen.pivot_table(index=["capital", "costo"], columns="margen_ticks", values="retorno_pct", sort=False).round(2))

# ---------------- 7) robustez y sensibilidad de la versión 3 (escenario realista) ----------------
_, M3, P3, T3 = VERSIONES["V3"]
ev3, cob3 = corridas["V3"]
d3 = diario(ev3, cob3, pat(ev3, "V3", *REALISTA))
base3 = d3["pnl"].sum() / CAPITAL * 100
rob = [{"grupo": "Base", "variante": "Versión 3, escenario realista", "retorno_pct": base3, "ruedas": len(d3),
        "bps_por_rueda": d3["pnl"].mean() / CAPITAL * 1e4}]
for bl in BLOQUE_ORDEN:
    sub = d3[d3["bloque"] != bl]
    rob.append({"grupo": "Período", "variante": f"Sin el bloque {BLOQUE_LABEL[bl]}", "retorno_pct": sub["pnl"].sum() / CAPITAL * 100,
                "ruedas": len(sub), "bps_por_rueda": sub["pnl"].mean() / CAPITAL * 1e4})
sub = d3.drop(d3["pnl"].nlargest(5).index)
rob.append({"grupo": "Período", "variante": "Sin las 5 mejores ruedas", "retorno_pct": sub["pnl"].sum() / CAPITAL * 100,
            "ruedas": len(sub), "bps_por_rueda": sub["pnl"].mean() / CAPITAL * 1e4})
sub = d3[d3["d"] == 1]
rob.append({"grupo": "Período", "variante": "Sin viernes ni vísperas de feriado", "retorno_pct": sub["pnl"].sum() / CAPITAL * 100,
            "ruedas": len(sub), "bps_por_rueda": sub["pnl"].mean() / CAPITAL * 1e4})
una = [(d3["pnl"].sum() - x) / CAPITAL * 100 for x in d3["pnl"]]
rob.append({"grupo": "Período", "variante": "Sacando una rueda por vez (mínimo)", "retorno_pct": min(una), "ruedas": len(d3) - 1,
            "bps_por_rueda": np.nan, "nota": f"máximo {max(una):.2f}%"})
rob.append({"grupo": "Período", "variante": "Ruedas negativas", "retorno_pct": np.nan, "ruedas": int((d3["pnl"] < 0).sum()),
            "bps_por_rueda": d3["pnl"].min() / CAPITAL * 1e4})


def rob_corrida(grupo, variante, sg, **kw):
    ev, cob = correr(M3, P3, T3, sg=sg, **kw)
    d = diario(ev, cob, pat(ev, f"rob_{variante}", *REALISTA))
    rob.append({"grupo": grupo, "variante": variante, "retorno_pct": d["pnl"].sum() / CAPITAL * 100, "ruedas": len(d),
                "bps_por_rueda": d["pnl"].mean() / CAPITAL * 1e4, "operaciones": len(ev)})


for s in ORDEN:
    rob_corrida("Especies", f"Sin {s}", sig[sig["simbolo"] != s])
for esc in ESCENARIOS:
    if esc != BASE:
        rob_corrida("Caución", f"Caución: {esc}", sig_all[sig_all["escenario"] == esc].reset_index(drop=True))


def con_filtros(valido):
    t = sig.copy()
    t["valido"] = valido
    c1 = (t["edge1_col"] > 0) | (t["edge1"] > 0)
    c2 = (t["edge2_tom"] > 0) | (t["edge2"] > 0)
    t["candidata"] = np.where(valido, np.select([c1 & c2, c1, c2], [3, 1, 2], default=0), 0)
    return t


ok_base = ~(sig["f_evento"] | sig["f_postcierre"] | sig["f_sincronia"])
rob_corrida("Filtros", "Cota ±0,5%", con_filtros(ok_base & (sig["spread_pct"].abs() <= 0.005)))
rob_corrida("Filtros", "Sin cota", con_filtros(ok_base))
rob_corrida("Filtros", "Sin regla de sincronía", con_filtros(~(sig["f_evento"] | sig["f_postcierre"] | sig["f_cota"])))
rob_corrida("Filtros", "Incluyendo el bucket de las 17:00", con_filtros(~(sig["f_evento"] | sig["f_sincronia"] | sig["f_cota"])))
rob_corrida("Sizing", "Inventario 50k por especie", sig, inv=50_000.0)
rob_corrida("Sizing", "Inventario 200k por especie", sig, inv=200_000.0)
rob_corrida("Sizing", "Sin faltante cubierto con caución", sig, lim=0.0)
rob = pd.DataFrame(rob)
rob["dif_vs_base_pp"] = rob["retorno_pct"] - base3

# dependencia de los spreads grandes (|spread| > 0,5%, más de ~180% TNA a un día): qué parte del resultado
# realista explican y cuánto queda si se los excluye con la cota de ±0,5%
grandes = []
for k in ["V1", "V2", "V3"]:
    _, m, pond, tp = VERSIONES[k]
    ev, cob = corridas[k]
    pa = pat(ev, k, *REALISTA)
    atrib = pa + caucion_sola(ev)
    g = ev["spread_pct"].abs() > 0.005
    ev_c, cob_c = correr(m, pond, tp, sg=con_filtros(ok_base & (sig["spread_pct"].abs() <= 0.005)))
    tot_c = pat(ev_c, f"cota_{k}", *REALISTA).sum() + cob_c["pnl_caucion"].sum()
    grandes.append({"version": k, "operaciones": len(ev), "ops_spread_grande": int(g.sum()),
                    "pct_ops_grandes": g.mean() * 100, "pct_resultado_grandes": atrib[g].sum() / atrib.sum() * 100,
                    "bps_por_peso_grandes": atrib[g].sum() / ev.loc[g, "nocional"].sum() * 1e4,
                    "bps_por_peso_resto": atrib[~g].sum() / ev.loc[~g, "nocional"].sum() * 1e4,
                    "retorno_realista_pct": (pa.sum() + cob["pnl_caucion"].sum()) / CAPITAL * 100,
                    "retorno_realista_cota05_pct": tot_c / CAPITAL * 100,
                    **{f"grandes_{s}": atrib[g & (ev["simbolo"] == s)].sum() / CAPITAL * 100 for s in ORDEN}})
grandes = pd.DataFrame(grandes)
grandes.to_csv(f"{DATA}/spreads_grandes.csv", index=False)
print("\nDependencia de los spreads grandes (escenario realista):")
print(grandes.round(2).to_string(index=False))
rob.to_csv(f"{DATA}/robustez_v3.csv", index=False)
print("\nRobustez de la versión 3 (escenario realista):")
print(rob.round(2).to_string(index=False))

# ---------------- 8) puente con la tercera entrega: costos de esa entrega sobre la base actual ----------------
def con_costos_tercera(sg):
    """Señal con los costos de la tercera entrega: derecho + una comisión igual (el doble por punta) y
    caución con 0,09% anual por lado en lugar de 0,045%."""
    t = sg.copy()
    t["f"] = 2 * t["f"]
    t["costo_bono"] = t["f"] * (2 + t["spread_pct"])
    t["r_col"] = t["caucion"] - 0.0009
    t["r_tom"] = t["caucion"] + 0.0009
    dd, s_ = t["d"] / 365, t["spread_pct"]
    t["edge1"] = s_ - t["r_tom"] * dd - t["costo_bono"]
    t["edge2"] = t["r_col"] * dd - s_ - t["costo_bono"]
    t["edge1_col"] = s_ - t["r_col"] * dd - t["costo_bono"]
    t["edge2_tom"] = t["r_tom"] * dd - s_ - t["costo_bono"]
    c1 = (t["edge1_col"] > 0) | (t["edge1"] > 0)
    c2 = (t["edge2_tom"] > 0) | (t["edge2"] > 0)
    t["candidata"] = np.where(t["valido"], np.select([c1 & c2, c1, c2], [3, 1, 2], default=0), 0)
    return t


evT, cobT = sizing.dimensionar(con_costos_tercera(sig))
bloques_3ra = ["estres_2025", "calma_dic_2025", "calma_abr_2026", "reciente_sep_2026"]
dia1 = (ev1.groupby("fecha")["pnl_bono"].sum() + cob1.set_index("fecha")["pnl_caucion"]).fillna(0)
en_3ra = cob1.set_index("fecha")["bloque"].isin(bloques_3ra)
puente = pd.DataFrame([
    {"variante": "Base de esta entrega (54 ruedas, derechos de mercado)", "retorno_pct": dia1.sum() / CAPITAL * 100,
     "ruedas": len(dia1), "operaciones": len(ev1)},
    {"variante": "Misma base con los costos de la tercera entrega", "ruedas": len(dia1), "operaciones": len(evT),
     "retorno_pct": (evT["pnl_bono"].sum() + cobT["pnl_caucion"].sum()) / CAPITAL * 100},
    {"variante": "Base de esta entrega, solo los cuatro bloques de la tercera", "ruedas": int(en_3ra.sum()),
     "operaciones": int(ev1["bloque"].isin(bloques_3ra).sum()), "retorno_pct": dia1[en_3ra].sum() / CAPITAL * 100},
])
puente["bps_por_rueda"] = puente["retorno_pct"] * 100 / puente["ruedas"]
puente.to_csv(f"{DATA}/puente_tercera.csv", index=False)
print("\nPuente con la tercera entrega:")
print(puente.round(3).to_string(index=False))

# ---------------- 9) volatilidad y caución por bloque ----------------
bars = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(f"{DATA}/bars_15min/*.parquet"))], ignore_index=True)
b = bars[bars["vencimiento"] == "24hs"].sort_values(["simbolo", "fecha", "bucket"])
b = b.assign(r=np.log(b["close"]).groupby([b["simbolo"], b["fecha"]]).diff())
vol = b.groupby(["bloque", "simbolo", "fecha"])["r"].apply(lambda r: np.sqrt((r ** 2).sum()) * 100).reset_index()
vol = vol.groupby(["bloque", "simbolo"])["r"].mean().unstack()[ORDEN]
cd = pd.read_csv(f"{DATA}/caucion_diaria.csv")
mf = {x["fecha"]: x["bloque"] for x in json.load(open(f"{DATA}/manifest.json")) if x["status"] == "en_bloque"}
cd["bloque"] = cd["fecha"].map(mf)
cd = cd.dropna(subset=["bloque"]).assign(rango=lambda x: x["maximo"] - x["minimo"])
cau = cd.groupby("bloque").agg(caucion_media_pct=("vwap", "mean"), caucion_desvio_pp=("vwap", "std"),
                                rango_intradiario_pp=("rango", "mean")) * 100
vb = vol.join(cau).reindex(BLOQUE_ORDEN)
vb.insert(0, "label", [BLOQUE_LABEL[x] for x in vb.index])
vb.to_csv(f"{DATA}/volatilidad_bloques.csv")
print("\nVolatilidad realizada intradiaria (% diario, pata 24hs) y caución por bloque:")
print(vb.round(2).to_string())

# ---------------- 10) sensibilidad al día de la semana y al horario ----------------
# Análogo intradiario del "día de rebalanceo": ¿el resultado depende del día de la semana o de la hora en que
# el bot opera?
DIA_NOM = {0: "Lunes", 1: "Martes", 2: "Miércoles", 3: "Jueves", 4: "Viernes"}
semana = []
for k, esc, (mult, seg) in [("V1", "ideal", (0.0, 0)), ("V1", "realista", REALISTA), ("V3", "realista", REALISTA)]:
    ev, cob = corridas[k]
    d = diario(ev, cob, pat(ev, k, mult, seg)).reset_index()
    d["dow"] = pd.to_datetime(d["fecha"]).dt.dayofweek
    tot = d["pnl"].sum()
    for dw, g in d.groupby("dow"):
        semana.append({"version": k, "escenario": esc, "dia": DIA_NOM[dw], "ruedas": len(g),
                       "bps_por_rueda": g["pnl"].mean() / CAPITAL * 1e4,
                       "bps_por_dia_caucion": (g["pnl"] / g["d"]).mean() / CAPITAL * 1e4,
                       "ruedas_negativas": int((g["pnl"] < 0).sum()),
                       "retorno_sin_ese_dia_pct": (tot - g["pnl"].sum()) / CAPITAL * 100,
                       "bps_por_rueda_sin_ese_dia": (tot - g["pnl"].sum()) / (len(d) - len(g)) / CAPITAL * 1e4})
semana = pd.DataFrame(semana)
semana.to_csv(f"{DATA}/dia_semana.csv", index=False)
print("\nPor día de la semana (bps del capital por rueda):")
print(semana.pivot_table(index="dia", columns=["version", "escenario"], values="bps_por_rueda", sort=False).round(1))

hora = []
for k in ["V1", "V3"]:
    ev, cob = corridas[k]
    at = pat(ev, k, *REALISTA) + caucion_sola(ev)
    h = ev["bucket"].dt.hour
    for hh, g in pd.Series(at, index=ev.index).groupby(h):
        hora.append({"version": k, "tipo": "atribución", "variante": f"{hh}:{'30' if hh == 10 else '00'}–{hh + 1}:00",
                     "operaciones": int((h == hh).sum()), "retorno_pct": g.sum() / CAPITAL * 100,
                     "bps_por_peso": g.sum() / ev.loc[h == hh, "nocional"].sum() * 1e4})
t_bucket = sig["bucket"].dt.hour * 60 + sig["bucket"].dt.minute
for nom, mask in [("Sin la primera hora (10:30 a 11:30)", t_bucket >= 11 * 60 + 30),
                  ("Sin la última hora (16:00 a 17:00)", t_bucket < 16 * 60),
                  ("Solo hasta las 13:30", t_bucket < 13 * 60 + 30),
                  ("Solo desde las 13:30", t_bucket >= 13 * 60 + 30)]:
    sg2 = sig.copy()
    sg2["valido"] = sg2["valido"] & mask
    sg2["candidata"] = np.where(sg2["valido"], sg2["candidata"], 0)
    for k in ["V1", "V3"]:
        _, m, pond, tp = VERSIONES[k]
        ev, cob = correr(m, pond, tp, sg=sg2)
        tot = pat(ev, f"hora_{k}_{nom}", *REALISTA).sum() + cob["pnl_caucion"].sum()
        hora.append({"version": k, "tipo": "ventana", "variante": nom, "operaciones": len(ev), "retorno_pct": tot / CAPITAL * 100})
hora = pd.DataFrame(hora)
hora.to_csv(f"{DATA}/horario.csv", index=False)
print("\nPor horario (escenario realista):")
print(hora.round(2).to_string(index=False))

# ---------------- 11) precio de ejecución: cierre, apertura, OHLC/4 y promedio de operaciones ----------------
# No hay VWAP intradiario: el export no trae el volumen de cada operación. Como aproximación se usa el promedio
# simple de los precios registrados en el bucket (cada cambio de precio pesa igual). Si en el bucket siguiente
# una pata no registra cambios, se valúa al cierre del bucket de la señal (su último precio).
bars = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(f"{DATA}/bars_15min/*.parquet"))], ignore_index=True)
bars["ohlc4"] = bars[["open", "high", "low", "close"]].mean(axis=1)
evp = []
for fn in sorted(glob.glob(f"{DATA}/eventos_precio/*.parquet")):
    e = pd.read_parquet(fn)
    e["fecha"] = os.path.basename(fn)[:10]
    e["bucket"] = e["hora"].dt.floor("15min")
    evp.append(e.groupby(["fecha", "simbolo", "vencimiento", "bucket"])["precio"].mean().rename("promedio").reset_index())
prom = pd.concat(evp, ignore_index=True).set_index(["fecha", "simbolo", "vencimiento", "bucket"])["promedio"]
bx = bars.set_index(["fecha", "simbolo", "vencimiento", "bucket"])


def precio_siguiente(ev, campo, venc):
    idx = pd.MultiIndex.from_arrays([ev["fecha"], ev["simbolo"], [venc] * len(ev), ev["bucket"] + pd.Timedelta(minutes=15)])
    serie = prom if campo == "promedio" else bx[campo]
    v = serie.reindex(idx).values
    return v


ejec = []
for k in ["V1", "V3"]:
    ev, cob = corridas[k]
    base_ci, base_24 = ev["p_ci"].values, ev["p_24"].values
    variantes = {"Cierre del bucket de la señal (base)": (base_ci, base_24)}
    for campo, nom in [("open", "primer precio"), ("ohlc4", "promedio OHLC/4"), ("promedio", "promedio de las operaciones")]:
        ci_n, p24_n = precio_siguiente(ev, campo, "CI"), precio_siguiente(ev, campo, "24hs")
        variantes[f"Las dos patas al {nom} del bucket siguiente"] = (ci_n, p24_n)
    variantes["CI a la señal, 24hs al promedio de las operaciones del bucket siguiente"] = (base_ci, precio_siguiente(ev, "promedio", "24hs"))
    for nom, (pci, p24) in variantes.items():
        falta = np.isnan(pci) | np.isnan(p24)
        pci2, p242 = np.where(np.isnan(pci), base_ci, pci), np.where(np.isnan(p24), base_24, p24)
        for mult in [0.0, COSTO_REALISTA_TICKS]:
            s = mult * tick_de(ev)
            p = patas(ev, pci2, p242, s, s)
            ejec.append({"version": k, "variante": nom, "costo_ticks": mult, "operaciones": len(ev),
                         "sin_precio_siguiente_pct": falta.mean() * 100, "retorno_pct": (p.sum() + cob["pnl_caucion"].sum()) / CAPITAL * 100,
                         "ops_con_perdida_pct": ((p + caucion_sola(ev)) < 0).mean() * 100})
ejec = pd.DataFrame(ejec)
ejec.to_csv(f"{DATA}/ejecucion_precios.csv", index=False)
print("\nPrecio de ejecución (retorno %):")
print(ejec.pivot_table(index="variante", columns=["version", "costo_ticks"], values="retorno_pct", sort=False).round(2))


# ---------------- 12) comisiones de broker ----------------
def con_costos(sg, f_nuevo, costo_caucion=None):
    """Señal recalculada con otro costo por punta (f) y, opcionalmente, otro costo anual de caución."""
    t = sg.copy()
    t["f"] = f_nuevo
    t["costo_bono"] = t["f"] * (2 + t["spread_pct"])
    if costo_caucion is not None:
        t["r_col"] = t["caucion"] - costo_caucion
        t["r_tom"] = t["caucion"] + costo_caucion
    dd, s_ = t["d"] / 365, t["spread_pct"]
    t["edge1"] = s_ - t["r_tom"] * dd - t["costo_bono"]
    t["edge2"] = t["r_col"] * dd - s_ - t["costo_bono"]
    t["edge1_col"] = s_ - t["r_col"] * dd - t["costo_bono"]
    t["edge2_tom"] = t["r_tom"] * dd - s_ - t["costo_bono"]
    c1 = (t["edge1_col"] > 0) | (t["edge1"] > 0)
    c2 = (t["edge2_tom"] > 0) | (t["edge2"] > 0)
    t["candidata"] = np.where(t["valido"], np.select([c1 & c2, c1, c2], [3, 1, 2], default=0), 0)
    return t


def con_comision_pagada(ev, k, extra):
    e2 = ev.copy()
    e2["f"] = e2["f"] + extra
    return pat(e2, k, *REALISTA).sum()


comis = []
for nom, extra_fn in [("Sin comisión (mesa de dinero)", lambda f: 0.0 * f), ("Comisión igual al derecho de mercado", lambda f: f),
                      ("Comisión de 0,10% por punta", lambda f: 0.0010 + 0.0 * f), ("Comisión de 0,25% por punta", lambda f: 0.0025 + 0.0 * f),
                      ("Comisión de 0,50% por punta", lambda f: 0.0050 + 0.0 * f)]:
    for k in ["V1", "V3"]:
        _, m, pond, tp = VERSIONES[k]
        ev, cob = corridas[k]
        sin_cambios = con_comision_pagada(ev, k, extra_fn(ev["f"])) + cob["pnl_caucion"].sum()
        ev2, cob2 = correr(m, pond, tp, sg=con_costos(sig, sig["f"] + extra_fn(sig["f"])))
        incorpora = pat(ev2, f"com_{k}_{nom}", *REALISTA).sum() + cob2["pnl_caucion"].sum()
        comis.append({"version": k, "variante": nom, "bot_sin_cambios_pct": sin_cambios / CAPITAL * 100,
                      "bot_incorpora_pct": incorpora / CAPITAL * 100, "operaciones_incorpora": len(ev2)})
# comisión por punta que lleva a cero el resultado del bot sin cambios
for k in ["V1", "V3"]:
    ev, cob = corridas[k]
    lo, hi = 0.0, 0.02
    for _ in range(50):
        mid = (lo + hi) / 2
        if con_comision_pagada(ev, k, mid) + cob["pnl_caucion"].sum() > 0:
            lo = mid
        else:
            hi = mid
    comis.append({"version": k, "variante": "Comisión de equilibrio (bot sin cambios)", "comision_equilibrio_bps": (lo + hi) / 2 * 1e4})
comis = pd.DataFrame(comis)
comis.to_csv(f"{DATA}/comisiones.csv", index=False)
print("\nComisiones (escenario realista):")
print(comis.round(3).to_string(index=False))

# ---------------- 13) liquidez de los activos frente a las órdenes de la versión 3 ----------------
ev3c = corridas["V3"][0]
volb = dict(zip(liq["simbolo"], liq["vol_por_bucket"]))
volc = dict(zip(liq["simbolo"], liq["vol_diario_ci_mediana"]))
liq3 = []
for s in ORDEN:
    g = ev3c[ev3c["simbolo"] == s]
    part = g["nocional"] / volb[s] * 100
    liq3.append({"simbolo": s, "vol_diario_ci": volc[s], "vol_por_bucket": volb[s],
                 "registros_ci_por_bucket": float(g["n_ev_ci"].median()), "operaciones": len(g),
                 "orden_media": g["nocional"].mean(), "orden_max": g["nocional"].max(),
                 "participacion_media_pct": part.mean(), "participacion_max_pct": part.max()})
liq3 = pd.DataFrame(liq3)
liq3.to_csv(f"{DATA}/liquidez_v3.csv", index=False)
print("\nLiquidez frente a las órdenes de la versión 3 (1 millón):")
print(liq3.round(2).to_string(index=False))

# ---------------- 14) tope de liquidez sin información futura ----------------
# El tope de la versión 3 usa la mediana del volumen diario CI de toda la muestra, que no se conoce al operar.
# Acá el bot decide el tamaño con un tope calculado solo con las ruedas anteriores (paso 12,
# data/liquidez_ci_diaria.csv). El impacto por tamaño se sigue midiendo contra la liquidez media de la muestra
# (TOPE), así que lo único que cambia es la información con la que el bot dimensiona la orden.
ld = pd.read_csv(f"{DATA}/liquidez_ci_diaria.csv")
TOPE_EXANTE = {(f, s_): t for f, s_, t in zip(ld["fecha"], ld["simbolo"], ld["tope_exante"])}
_, m3, p3, _ = VERSIONES["V3"]
s3 = descontar_costo(sig, m3)
exante = []
for C in [1e6, 5e6, 10e6, 50e6, 100e6]:
    for nombre, tp in [("Mediana de la muestra", TOPE), ("Ruedas anteriores", TOPE_EXANTE)]:
        ev, cob = sizing.dimensionar(s3, ponderacion=p3, capital=C, tope_orden=tp,
                                     inventario=INVENTARIO_ESPECIE * C / CAPITAL, limite=LIMITE_FALTANTE * C / CAPITAL)
        ev = ev.reset_index(drop=True)
        tope_fila = (ev["simbolo"].map(TOPE) if nombre.startswith("Mediana")
                     else pd.Series([TOPE_EXANTE[k] for k in zip(ev["fecha"], ev["simbolo"])], index=ev.index))
        en_tope = (ev["nocional"] >= tope_fila * (1 - 1e-9)).mean() * 100
        clave = f"exante_{nombre}_{C:.0f}"
        fila = {"capital": C, "tope": nombre, "operaciones": len(ev), "ordenes_en_tope_pct": en_tope}
        for esc, mult, seg, impacto in [("ideal", 0.0, 0, False), ("realista", *REALISTA, False), ("realista_impacto", *REALISTA, True)]:
            fila[esc] = (pat(ev, clave, mult, seg, impacto).sum() + cob["pnl_caucion"].sum()) / C * 100
        exante.append(fila)
exante = pd.DataFrame(exante)
chk = exante[exante["tope"] == "Mediana de la muestra"].set_index("capital")
ref_esc = escala[escala["version"] == "V3"].pivot_table(index="capital", columns="escenario", values="retorno_pct")
assert np.allclose(chk[["ideal", "realista", "realista_impacto"]].values, ref_esc.loc[chk.index, ["ideal", "realista", "realista_impacto"]].values), \
    "la versión 3 con el tope de la muestra no coincide con la escalabilidad"
exante.to_csv(f"{DATA}/tope_exante.csv", index=False)
print("\nVersión 3 con tope de liquidez sin información futura (retorno %):")
print(exante.round(2).to_string(index=False))


# ---------------- gráfico (estilo común: graficos_resultados.py) ----------------
from graficos_resultados import versiones as grafico_versiones

grafico_versiones(res, blq, DEMORAS, BLOQUE_ORDEN, BLOQUE_LABEL, f"{OUT}/grafico8_versiones.png")
print("gráfico ok")
