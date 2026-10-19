"""Junta todas las cifras que usa la entrega en output/numeros.json (una sola fuente de verdad)."""
import json
import os
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (DATA, OUT, CAPITAL, ESCENARIOS, BLOQUE_ORDEN, BLOQUE_LABEL, INVENTARIO_ESPECIE,
                    LIMITE_FALTANTE, BASE)

D = f"{DATA}/"
man = json.load(open(D + "manifest.json"))
sig = pd.read_parquet(D + "spread_signal.parquet")
ev = pd.read_parquet(D + "eventos.parquet")
cob = pd.read_parquet(D + "cobertura_diaria.parquet")
A = pd.read_csv(D + "modeloA_resumen.csv", index_col=0)
B = pd.read_csv(D + "modeloB_resumen.csv", index_col=0)
PB = pd.read_csv(D + "modeloA_por_bloque.csv", index_col=0)
rec = pd.read_csv(D + "comparacion_AB.csv", index_col=0)
sl = pd.read_csv(D + "comparacion_slippage.csv")
var = pd.read_csv(D + "modeloA_variantes_capital.csv")
be = float(pd.read_csv(D + "breakeven_slippage.csv", index_col=0).iloc[0, 0])
cb = pd.read_csv(D + "modeloB_curvas.csv", index_col=0, parse_dates=True)

n = {"capital": CAPITAL, "inventario_especie": INVENTARIO_ESPECIE, "limite_faltante": LIMITE_FALTANTE}
enb = [m for m in man if m["status"] == "en_bloque"]
n["ruedas"] = len(enb)
n["ruedas_por_bloque"] = {b: sum(1 for m in enb if m["bloque"] == b) for b in BLOQUE_ORDEN}
n["fuera_ventana"] = sorted(m["fecha"] for m in man if m["status"] == "fuera_de_bloque")
n["vacios"] = sum(1 for m in man if m["status"] == "vacio_corrupto")
n["excluidas"] = {m["fecha"]: m["motivo"] for m in man if m["status"] == "excluida"}

base = sig[sig["escenario"] == BASE]
n["bucket_instr"] = int(len(base))
ev_ = base["f_evento"]
n["filtro_evento"] = int(ev_.sum())
n["filtro_postcierre"] = int((~ev_ & base["f_postcierre"]).sum())
n["filtro_sincronia"] = int((~ev_ & ~base["f_postcierre"] & base["f_sincronia"]).sum())
n["filtro_cota"] = int((~ev_ & ~base["f_postcierre"] & ~base["f_sincronia"] & base["f_cota"]).sum())
n["validos"] = int(base["valido"].sum())
e_sf = np.where(base["direccion_sin_filtro"] == 1, base["edge1"],
                np.where(base["direccion_sin_filtro"] == 2, base["edge2"], np.nan))
n["senales_sin_filtro"] = int((base["direccion_sin_filtro"] > 0).sum())
n["edge_media_sin_filtro_bps"] = float(np.nanmean(e_sf) * 1e4)
n["senales"] = int((base["direccion"] > 0).sum())
n["senales_dir1"] = int((base["direccion"] == 1).sum())
n["senales_dir2"] = int((base["direccion"] == 2).sum())
n["edge_mediana_bps"] = float(base.loc[base["direccion"] > 0, "edge"].median() * 1e4)
n["edge_media_bps"] = float(base.loc[base["direccion"] > 0, "edge"].mean() * 1e4)
n["candidatas"] = int((base["candidata"] > 0).sum())
n["solo_compensando"] = n["candidatas"] - n["senales"]

n["escenarios"] = {}
for esc in ESCENARIOS:
    c = cob[cob["escenario"] == esc]
    n["escenarios"][esc] = {
        "retorno_pct": float(A.loc[esc, "retorno_pct"]), "pnl": float(A.loc[esc, "pnl_total"]),
        "pnl_bono": float(A.loc[esc, "pnl_bono"]), "pnl_caucion": float(A.loc[esc, "pnl_caucion"]),
        "eventos": int(A.loc[esc, "eventos"]), "dir1": int(A.loc[esc, "dir1"]), "dir2": int(A.loc[esc, "dir2"]),
        "edge_pond_bps": float(A.loc[esc, "edge_pond_bps"]),
        "compensado_pct": float(A.loc[esc, "compensado_pct"]),
        "neto_medio_abs": float(A.loc[esc, "neto_medio_abs"]),
        "caucion_bruta": float(c["pesos_tomadoras"].sum() + c["pesos_colocadoras"].sum()),
        "caucion_neta": float(c["neto_cierre"].abs().sum()),
        "dias_positivos": int(B.loc[esc, "dias_positivos"]),
        "dd_intradiario_pct": float(B.loc[esc, "max_dd_intradiario_pct"]),
        "dd_diario_pct": float(B.loc[esc, "max_dd_diario_pct"]),
        "retorno_B_pct": float(B.loc[esc, "retorno_pct"]), "ordenes_B": int(B.loc[esc, "ordenes"]),
        "dif_pnl": float(rec.loc[esc, "dif_pnl_total"]), "dif_curva": float(rec.loc[esc, "dif_max_curva"]),
        "max_inventario_afuera": float(B.loc[esc, "max_inventario_afuera"]),
        "max_faltante_pesos": float(B.loc[esc, "max_faltante_pesos"]),
    }
n["no_ejecutadas"] = n["candidatas"] - n["escenarios"][BASE]["eventos"]
eb = ev[ev["escenario"] == BASE]
ambas = eb.groupby(["fecha", "simbolo"])["direccion"].nunique().eq(2)
n["inst_dia_con_ops"] = int(ambas.size)
n["inst_dia_ambas_dir"] = int(ambas.sum())

cau = pd.read_csv(D + "caucion_diaria.csv")
vb = base[base["valido"]].merge(cau[["fecha", BASE]], on="fecha")
bloques = []
for b in BLOQUE_ORDEN:
    v = vb[vb["bloque"] == b]
    ruedas = n["ruedas_por_bloque"][b]
    r = PB.loc[b]
    bloques.append({
        "bloque": b, "label": BLOQUE_LABEL[b], "ruedas": ruedas,
        "retorno_pct": float(r["retorno_pct"]), "retorno_por_rueda_bps": float(r["retorno_pct"]) / ruedas * 100,
        "ops_tomo": int(r["ops_tomo"]), "ops_coloco": int(r["ops_coloco"]),
        "compensado_pct": float(r["compensado_pct"]), "neto_medio_abs": float(r["neto_medio_abs"]),
        "tasa_impl_tna_pct": float(v["tasa_implicita_anual"].mean() * 100),
        "tasa_impl_tna_mediana_pct": float(v["tasa_implicita_anual"].median() * 100),
        "caucion_tna_pct": float(v[BASE].mean() * 100),
    })
n["bloques"] = bloques

inst = pd.read_csv(D + "modeloA_por_instrumento_base.csv")
n["instrumentos"] = inst.round(4).to_dict(orient="records")
n["atribucion_standalone_pct"] = float(inst["retorno_pct"].sum())
n["variantes_capital"] = var.round(4).to_dict(orient="records")
n["slippage"] = sl.round(6).to_dict(orient="records")
n["breakeven_bps"] = be

v = cb[BASE].iloc[:-1]
diaria = v.groupby(v.index.strftime("%Y-%m-%d")).last()
n["curva_diaria"] = [{"fecha": f, "valor": float(x)} for f, x in diaria.items()]
n["version_anterior_retorno_pct"] = 10.66

json.dump(n, open(f"{OUT}/numeros.json", "w"), indent=2, ensure_ascii=False)
E = n["escenarios"][BASE]
print({k: round(E[k], 3) for k in ["retorno_pct", "eventos", "compensado_pct", "neto_medio_abs",
                                   "caucion_bruta", "caucion_neta", "dias_positivos"]})
print("candidatas", n["candidatas"], "no ejecutadas", n["no_ejecutadas"], "atribución standalone",
      round(n["atribucion_standalone_pct"], 4))
print(pd.DataFrame(bloques)[["label", "retorno_pct", "retorno_por_rueda_bps", "ops_tomo", "ops_coloco",
                            "compensado_pct", "neto_medio_abs"]].round(2).to_string(index=False))
