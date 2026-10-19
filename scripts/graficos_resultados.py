"""Gráficos 5 a 8 de la tesina (mapa de dónde falla, robustez y versiones), con el estilo común de estilo_graficos.py.

Cada función recibe las tablas que guardan los pasos 13, 14 y 15 (ejec_mapa.csv, robustez.csv, versiones.csv y
versiones_bloques.csv), así que también se pueden regenerar sin volver a correr esos pasos:
    python scripts/graficos_resultados.py
"""
import os
import re
import sys

import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm
from matplotlib.ticker import MultipleLocator

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from estilo_graficos import (AZUL, BASE, COLOR_VERSION, DEMORA, NARANJA, NOMBRE_VERSION, T_ROTULO, T_TEXTO, TINTA,
                             TINTA2, coma, ejes, figura, formato_pct, guardar, panel)

# rótulos que se acortan igual en la tabla de la tesina y en el gráfico
ROTULO_CORTO = {"Con interés corrido de los bonos (YMCIO 9%)": "Con interés corrido de los bonos (el bot lo conoce)"}
ORDEN = ["AL30", "GD30", "YMCIO", "GGAL", "YPFD", "GLD", "KO", "SLV", "SPY"]
CLASE = {"AL30": "Soberano", "GD30": "Soberano", "YMCIO": "ON", "GGAL": "Acción", "YPFD": "Acción",
         "GLD": "CEDEAR", "KO": "CEDEAR", "SLV": "CEDEAR", "SPY": "CEDEAR"}


def mapa_falla(mapa, ruta):
    """Gráfico de la sección 8.4: resultado atribuido por especie según costo por pata y demora de la 24hs."""
    cmap = LinearSegmentedColormap.from_list("div", ["#d95926", "#f3c5b0", "#f4f3ef", "#b7d3f6", "#256abf"])
    cols, matriz = [], []
    for mult in [0.0, 0.5, 1.0]:
        for seg in [0, 30, 60, 300, 900]:
            r = mapa[(mapa["grupo"] == "mapa") & (mapa["costo_ticks"] == mult) & (mapa["demora_s"] == seg)].iloc[0]
            matriz.append([r[s] for s in ORDEN] + [r["retorno_pct"]])
            cols.append(seg)
    M = np.array(matriz).T                       # filas: especies y total; columnas: escenarios
    lim = np.nanmax(np.abs(M[:-1]))
    fig, ax = figura(3.7)
    ax.imshow(M[:-1], aspect="auto", cmap=cmap, norm=TwoSlopeNorm(vcenter=0, vmin=-lim, vmax=lim))
    for i in range(M.shape[0]):
        for j in range(M.shape[1]):
            v = 0.0 if abs(M[i, j]) < 0.005 else M[i, j]
            ax.text(j, i, coma(v), ha="center", va="center", fontsize=T_ROTULO - 0.5, color=TINTA)
    ax.set_ylim(M.shape[0] - 0.5, -0.5)
    ax.axhline(M.shape[0] - 1.5, color=TINTA2, linewidth=0.8)
    for j in [4.5, 9.5]:
        ax.axvline(j, color="white", linewidth=3)
    ax.set_yticks(range(M.shape[0]), [f"{s} ({CLASE[s]})" for s in ORDEN] + ["Total"])
    ax.set_xticks(range(M.shape[1]), [DEMORA[s] for s in cols], fontsize=T_ROTULO - 0.5)
    for k, nombre in enumerate(["Sin slippage", "Medio tick por pata", "Un tick por pata"]):
        ax.text(k * 5 + 2, -0.75, nombre, ha="center", va="bottom", fontsize=T_TEXTO, color=TINTA)
    ax.set_xlabel("Demora de la pata 24hs respecto de la CI")
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(length=0)
    guardar(fig, ruta)


def robustez(res, ruta):
    """Gráfico de la sección 6: cada variante de la versión 1 frente a su base sin costos de ejecución."""
    base_pct = float((res["retorno_pct"] - res["dif_vs_base_pp"]).iloc[0])
    g = res[~res["grupo"].isin(["Base", "Período", "Viernes"])].copy()     # mismas 54 ruedas que la base
    def rotulo(r):
        v = ROTULO_CORTO.get(r["variante"], r["variante"])
        v = re.sub(r"(\d+)k\b", lambda m: f"{int(m.group(1)) * 1000:,}".replace(",", "."), v)
        if r["grupo"] == "Grilla":
            pct_bucket = float(re.search(r"([\d.]+)%$", r["nota"]).group(1))
            v = re.sub(r"^Grilla c", "C", v) + f" ({coma(pct_bucket)}% por bucket)"
        return f"{r['grupo']} · {v}"
    g["etiqueta"] = g.apply(rotulo, axis=1)
    fig, ax = figura(0.165 * len(g) + 0.7)
    y = np.arange(len(g))[::-1]
    colores = np.where(g["retorno_pct"] >= base_pct, AZUL, NARANJA)
    ax.barh(y, g["retorno_pct"] - base_pct, left=base_pct, color=colores, height=0.62)
    ax.axvline(base_pct, color=TINTA2, linewidth=1)
    for yi, v in zip(y, g["retorno_pct"]):
        ax.text(v + (0.08 if v >= base_pct else -0.08), yi, f"{coma(v)}%", va="center",
                ha="left" if v >= base_pct else "right", fontsize=T_ROTULO - 0.5, color=TINTA)
    ax.set_yticks(y, g["etiqueta"])
    ax.set_ylim(-0.7, len(g) - 0.3)
    ax.xaxis.set_major_formatter(formato_pct(0))
    ax.set_xlim(g["retorno_pct"].min() - 1.4, g["retorno_pct"].max() + 1.3)
    ax.set_xlabel(f"Resultado sobre el capital, 54 ruedas (base: {coma(base_pct)}%)")
    ejes(ax, grilla="x")
    ax.spines["left"].set_visible(False)
    guardar(fig, ruta)


def versiones(res, blq, demoras, bloques, rotulos, ruta):
    """Gráfico de la sección 11.4: resultado de cada versión según costo y demora, y por bloque."""
    fig, (a1, a2) = figura(5.6, nrows=2, gridspec_kw={"height_ratios": [1.15, 1]})
    xs = np.arange(len(demoras))
    for k in ["V1", "V2", "V3"]:
        for mult, ls, mk, lbl in [(0.5, "-", "o", "medio tick"), (1.0, ":", "^", "un tick")]:
            y = [res[(res.version == k) & (res.costo_ticks == mult) & (res.demora_s == s)]["retorno_pct"].iloc[0] for s in demoras]
            a1.plot(xs, y, color=COLOR_VERSION[k], linestyle=ls, marker=mk, markersize=3,
                    linewidth=1.8 if k == "V3" else 1.3, label=f"{NOMBRE_VERSION[k]}, {lbl} por pata")
    a1.axhline(0, color=BASE, linewidth=0.8)
    a1.set_xticks(xs, [DEMORA[s] for s in demoras])
    a1.set_xlabel("Demora de la pata 24hs (la CI se ejecuta al precio de la señal)")
    a1.set_ylabel("Resultado sobre el capital (54 ruedas)")
    a1.yaxis.set_major_locator(MultipleLocator(2))          # marcas enteras: el formato de 0 decimales no redondea 2,5 a "2%"
    a1.yaxis.set_major_formatter(formato_pct(0))
    a1.legend(ncol=2, loc="upper center", bbox_to_anchor=(0.5, -0.24), columnspacing=1.2)
    panel(a1, "A", "Resultado total según el costo pagado por pata y la demora")
    ejes(a1)
    r_ = blq[blq["escenario"] == "realista"]
    xb = np.arange(len(bloques))
    w = 0.27
    for j, k in enumerate(["V1", "V2", "V3"]):
        v = [r_[(r_.version == k) & (r_.bloque == x)]["bps_por_rueda"].iloc[0] for x in bloques]
        a2.bar(xb + (j - 1) * w, v, width=w * 0.95, color=COLOR_VERSION[k], label=NOMBRE_VERSION[k])
        for x0, vv in zip(xb + (j - 1) * w, v):
            a2.text(x0, vv + 0.4, coma(vv, 1), ha="center", va="bottom", fontsize=T_ROTULO - 0.5, color=TINTA)
    a2.set_xticks(xb, [rotulos[x].replace(" (", "\n(") for x in bloques])
    a2.set_ylabel("bps del capital por rueda")
    a2.set_ylim(0, r_["bps_por_rueda"].max() * 1.15)
    a2.legend(ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.3))
    panel(a2, "B", "Resultado por rueda de cada bloque, con medio tick por pata y 30 s entre patas")
    ejes(a2)
    guardar(fig, ruta)


if __name__ == "__main__":
    from common import BLOQUE_LABEL, BLOQUE_ORDEN, DATA, OUT
    mapa_falla(pd.read_csv(f"{DATA}/ejec_mapa.csv"), f"{OUT}/grafico7_mapa_falla.png")
    robustez(pd.read_csv(f"{DATA}/robustez.csv"), f"{OUT}/grafico5_robustez.png")
    versiones(pd.read_csv(f"{DATA}/versiones.csv"), pd.read_csv(f"{DATA}/versiones_bloques.csv"),
              [0, 5, 30, 60, 300, 900], BLOQUE_ORDEN, BLOQUE_LABEL, f"{OUT}/grafico8_versiones.png")
    print("gráficos 5 a 8 ok")
