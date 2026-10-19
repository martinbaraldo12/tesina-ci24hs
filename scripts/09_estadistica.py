"""
Paso 9 — Inferencia estadística.

Unidad de análisis: instrumento-día (mediana de los buckets válidos de la rueda), para no tratar
como independientes observaciones intradiarias autocorrelacionadas. Errores estándar agrupados
(cluster) por rueda, porque todos los instrumentos de un mismo día comparten la caución.

  A. Efecto viernes: ¿el spread escala con los días de financiamiento (1 vs 3)?
  B. Traslado (pass-through) de la caución a la tasa implícita, por clase de instrumento.
  C. Brecha tasa implícita − caución por clase y bloque (¿distinta de cero?).
  D. Efecto régimen sobre el resultado diario de la estrategia: estrés vs. calma de diciembre
     (niveles de caución similares) y regresión con caución y viernes como controles.
Además: granularidad de precios (tick) por clase.
"""
import json
import os
import sys
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from scipy import stats

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import DATA, OUT, CAPITAL, BLOQUE_ORDEN, BLOQUE_LABEL, BLOQUES_ESTRES, BASE

CLASE = {"AL30": "Soberanos", "GD30": "Soberanos", "YMCIO": "ON", "YM43O": "ON", "YM34O": "ON",
         "GGAL": "Acciones", "YPFD": "Acciones", "GLD": "CEDEARs", "SLV": "CEDEARs", "KO": "CEDEARs",
         "SPY": "CEDEARs"}
CLASES = ["Soberanos", "ON", "Acciones", "CEDEARs"]
rng = np.random.default_rng(42)
res = {}

sig = pd.read_parquet(DATA / "spread_signal.parquet")
s = sig[(sig["escenario"] == BASE) & sig["valido"]].copy()
s["clase"] = s["simbolo"].map(CLASE)
cau = pd.read_csv(DATA / "caucion_diaria.csv").set_index("fecha")

# ---- panel instrumento-día ----
p = s.groupby(["fecha", "bloque", "simbolo", "clase", "d"]).agg(
    spread=("spread_pct", "median"), n=("spread_pct", "size"),
    precio=("p_ci", "median")).reset_index()
p = p[p["n"] >= 3]                                  # al menos 3 buckets válidos en la rueda
p["caucion"] = p["fecha"].map(cau[BASE])
p["impl"] = p["spread"] * 365 / p["d"]               # tasa implícita (TNA)
p["brecha"] = p["impl"] - p["caucion"]
p["spread_bps"] = p["spread"] * 1e4
p["viernes"] = (p["d"] > 1).astype(int)          # plazo largo: viernes o víspera de feriado
p.to_csv(DATA / "panel_instrumento_dia.csv", index=False)
print(f"Panel: {len(p)} instrumento-día, {p['fecha'].nunique()} ruedas")


def cl(model_formula, df):
    return smf.ols(model_formula, data=df).fit(cov_type="cluster", cov_kwds={"groups": pd.factorize(df["fecha"])[0]})


# ---- tick: tasa implícita equivalente a 1 tick de spread en 1 día ----
tk = pd.read_csv(DATA / "ticks.csv")
tk["clase"] = tk["simbolo"].map(CLASE)
res["tick_tna_1dia"] = tk.groupby("clase")["tna_1tick_1dia_pct"].median().reindex(CLASES).round(1).to_dict()

# ---- A. Efecto viernes ----
A = []
for c in CLASES:
    g = p[p["clase"] == c]
    v, o = g.loc[g["viernes"] == 1, "spread_bps"], g.loc[g["viernes"] == 0, "spread_bps"]
    m = cl("spread_bps ~ viernes + C(simbolo)", g)
    A.append({"clase": c, "spread_lun_jue_bps": o.mean(), "spread_viernes_bps": v.mean(),
              "ratio": v.mean() / o.mean() if o.mean() else np.nan,
              "dif_bps": m.params["viernes"], "p_valor": m.pvalues["viernes"],
              "p_mann_whitney": stats.mannwhitneyu(v, o, alternative="greater").pvalue})
A = pd.DataFrame(A)
print("\n=== A. Efecto viernes (spread en bps; cluster por rueda) ===")
print(A.round(4).to_string(index=False))

# ---- B. Traslado de la caución a la tasa implícita ----
B = []
for c in CLASES + ["Todas"]:
    g = p if c == "Todas" else p[p["clase"] == c]
    m = cl("impl ~ caucion + C(simbolo)", g)
    ci = m.conf_int().loc["caucion"]
    B.append({"clase": c, "beta": m.params["caucion"], "ic95_inf": ci[0], "ic95_sup": ci[1],
              "p_beta_0": m.pvalues["caucion"],
              "p_beta_1": 2 * stats.t.sf(abs((m.params["caucion"] - 1) / m.bse["caucion"]), m.df_resid),
              "obs": int(m.nobs)})
B = pd.DataFrame(B)
# robustez del traslado en soberanos (la medición más limpia: tick ~4% TNA)
g = p[p["clase"] == "Soberanos"]
rob = []
for nombre, d in [("Todos los días", g), ("Solo lunes a jueves", g[g["viernes"] == 0]),
                  ("Solo AL30", g[g["simbolo"] == "AL30"]), ("Solo GD30", g[g["simbolo"] == "GD30"])]:
    m = cl("impl ~ caucion" + (" + C(simbolo)" if d["simbolo"].nunique() > 1 else ""), d)
    rob.append({"especificacion": nombre, "beta": m.params["caucion"],
                "ic95_inf": m.conf_int().loc["caucion"][0], "ic95_sup": m.conf_int().loc["caucion"][1]})
res["B_robustez_soberanos"] = rob
sob = g[g["viernes"] == 0].groupby("bloque").agg(spread_bps=("spread_bps", "mean"), caucion=("caucion", "mean"))
sob["caucion_dia_bps"] = sob["caucion"] / 365 * 1e4
res["soberanos_lun_jue"] = {BLOQUE_LABEL[b]: sob.loc[b].to_dict() for b in BLOQUE_ORDEN}
print("\n=== B. Traslado caución -> tasa implícita (beta=1 traslado pleno, 0 nulo) ===")
print(B.round(3).to_string(index=False))

# ---- C. Brecha por clase y bloque ----
C = []
for c in CLASES:
    for b in BLOQUE_ORDEN:
        g = p[(p["clase"] == c) & (p["bloque"] == b)]
        if g["fecha"].nunique() < 3:
            continue
        m = cl("brecha ~ 1", g)
        diaria = g.groupby("fecha")["brecha"].mean()
        C.append({"clase": c, "bloque": BLOQUE_LABEL[b], "impl_media": g["impl"].mean(),
                  "caucion": g["caucion"].mean(), "brecha": m.params["Intercept"],
                  "ic95_inf": m.conf_int().loc["Intercept"][0], "ic95_sup": m.conf_int().loc["Intercept"][1],
                  "p_valor": m.pvalues["Intercept"], "p_wilcoxon": stats.wilcoxon(diaria).pvalue,
                  "ruedas": diaria.size})
C = pd.DataFrame(C)
print("\n=== C. Brecha tasa implícita - caución (TNA), por clase y bloque ===")
print(C.round(4).to_string(index=False))

# ---- D. Régimen: resultado diario de la estrategia ----
ev = pd.read_parquet(DATA / "eventos.parquet")
cob = pd.read_parquet(DATA / "cobertura_diaria.parquet")
e = ev[ev["escenario"] == BASE]; cb = cob[cob["escenario"] == BASE].set_index("fecha")
dia = (e.groupby("fecha")["pnl_bono"].sum() + cb["pnl_caucion"]).rename("pnl").to_frame()
dia["ret_bps"] = dia["pnl"] / CAPITAL * 1e4
dia["bloque"] = cb["bloque"]; dia["d"] = cb["d"]; dia["viernes"] = (dia["d"] > 1).astype(int)
dia["caucion"] = dia.index.map(cau[BASE])
dia["estres"] = dia["bloque"].isin(BLOQUES_ESTRES).astype(int)
dia = dia.reset_index()

x, y = dia.loc[dia.bloque == "estres_2025", "ret_bps"].values, dia.loc[dia.bloque == "calma_dic_2025", "ret_bps"].values
obs = x.mean() - y.mean()
todo = np.r_[x, y]
perm = np.array([(lambda z: z[:len(x)].mean() - z[len(x):].mean())(rng.permutation(todo)) for _ in range(20000)])
D1 = {"media_estres_bps": x.mean(), "media_dic_bps": y.mean(), "dif_bps": obs,
      "p_welch": stats.ttest_ind(x, y, equal_var=False).pvalue,
      "p_mann_whitney": stats.mannwhitneyu(x, y).pvalue,
      "p_permutacion": (np.abs(perm) >= abs(obs)).mean(),
      "caucion_estres": dia.loc[dia.bloque == "estres_2025", "caucion"].mean(),
      "caucion_dic": dia.loc[dia.bloque == "calma_dic_2025", "caucion"].mean()}

def par(b_estres, b_calma):
    x = dia.loc[dia.bloque == b_estres, "ret_bps"].values
    y = dia.loc[dia.bloque == b_calma, "ret_bps"].values
    if len(x) < 3 or len(y) < 3:
        return None
    obs = x.mean() - y.mean(); todo = np.r_[x, y]
    perm = np.array([(lambda z: z[:len(x)].mean() - z[len(x):].mean())(rng.permutation(todo)) for _ in range(20000)])
    return {"estres": b_estres, "calma": b_calma, "ruedas_estres": len(x), "ruedas_calma": len(y),
            "media_estres_bps": x.mean(), "media_calma_bps": y.mean(), "dif_bps": obs,
            "p_welch": stats.ttest_ind(x, y, equal_var=False).pvalue,
            "p_mann_whitney": stats.mannwhitneyu(x, y).pvalue,
            "p_permutacion": (np.abs(perm) >= abs(obs)).mean(),
            "caucion_estres": dia.loc[dia.bloque == b_estres, "caucion"].mean(),
            "caucion_calma": dia.loc[dia.bloque == b_calma, "caucion"].mean()}
D1b = par("estres_sep_2026", "reciente_sep_2026")
print("\n=== D1b. Resultado diario: estrés sep-oct 2026 vs. reciente sep 2026 ===")
print(D1b)
print("\n=== D1. Resultado diario: estrés vs. calma dic. (caución similar) ===")
print({k: round(v, 4) for k, v in D1.items()})

m = smf.ols("ret_bps ~ caucion + estres + viernes", data=dia).fit(cov_type="HAC", cov_kwds={"maxlags": 1})
D2 = pd.DataFrame({"coef": m.params, "ee": m.bse, "p_valor": m.pvalues,
                   "ic95_inf": m.conf_int()[0], "ic95_sup": m.conf_int()[1]})
print("\n=== D2. ret_bps = a + b*caucion + c*estres + d*viernes (Newey-West, 1 rezago) ===")
print(D2.round(4).to_string()); print(f"R2 = {m.rsquared:.3f}, n = {int(m.nobs)}")

# ---- guardar ----
res.update({"A_viernes": A.to_dict(orient="records"), "B_traslado": B.to_dict(orient="records"),
            "C_brecha": C.to_dict(orient="records"), "D1_estres_vs_dic": D1, "D1b_estres26_vs_sep26": D1b,
            "D2_regresion": D2.reset_index().rename(columns={"index": "variable"}).to_dict(orient="records"),
            "D2_r2": m.rsquared, "D2_n": int(m.nobs)})
json.dump(res, open(OUT / "estadistica.json", "w"), indent=2, ensure_ascii=False, default=float)
