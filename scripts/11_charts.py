"""Gráficos 1 a 4 de la tesina y el gráfico de fuentes de caución (estilo común en estilo_graficos.py)."""
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import DATA, OUT as _OUT, BASE as BASE_ESC
from estilo_graficos import (AZUL, CELESTE, COLOR_CLASE, GRIS, T_ROTULO, TENUE, TINTA, TINTA2, BASE, coma, ejes,
                             figura, formato_pct, guardar, miles)

OUT = f"{_OUT}/"
DOC = Path(__file__).resolve().parent.parent / "documentacion"
N = json.load(open(OUT + "numeros.json"))
BLOQUES = N["bloques"]
ROT2 = [b["label"].replace(" (", "\n(") for b in BLOQUES]      # rótulo del bloque en dos líneas


def separadores(ax, limites, total, y_texto):
    """Líneas entre bloques y nombre de cada bloque arriba del gráfico (gráficos rueda por rueda)."""
    ini = 0
    for b, fin in zip(BLOQUES, limites):
        if fin < total:
            ax.axvline(fin + 0.5, color=BASE, linewidth=0.8, linestyle="--")
        rot = b["label"].replace(" (", "\n(")
        if b["ruedas"] <= 5:                      # bloque angosto: el nombre en dos líneas para que no se pise con el vecino
            rot = rot.replace(" ", "\n", 1)
        ax.text((ini + fin) / 2 + 0.5, y_texto, rot, ha="center", va="bottom",
                fontsize=T_ROTULO, color=TINTA2, linespacing=1.05)
        ini = fin


# ---------- 0. Tasa implícita de los soberanos frente a las dos series de caución (sección 3.5) ----------
g0 = pd.read_csv(DOC / "datos_grafico_caucion.csv")
orden_bl = [b["bloque"] for b in BLOQUES]
g0["i"] = np.arange(1, len(g0) + 1)
fig, ax = figura(3.3)
for k, (bl, d) in enumerate(g0.groupby("bloque", sort=False)):
    assert bl == orden_bl[k]
    ax.plot(d["i"], d["old"] * 100, color=GRIS, linestyle="--", linewidth=1.3, marker="o", markersize=2.5,
            label="Caución de la serie anterior (descartada)" if k == 0 else None)
    ax.plot(d["i"], d["vwap"] * 100, color=TINTA, linewidth=1.5, label="Caución de A3 (VWAP del día)" if k == 0 else None)
    ax.plot(d["i"], d["impl"] * 100, color=AZUL, linewidth=1.5, marker="o", markersize=2.5,
            label="Tasa implícita CI/24hs de los soberanos (AL30 y GD30)" if k == 0 else None)
ax.set_ylim(0, 62)
ax.yaxis.set_major_formatter(formato_pct(0))
ax.set_ylabel("TNA")
ax.set_xticks([1, 10, 20, 30, 40, 50])
ax.set_xlabel(f"Rueda (orden cronológico, {len(g0)} ruedas en {len(BLOQUES)} bloques)")
ejes(ax)
separadores(ax, np.cumsum([b["ruedas"] for b in BLOQUES]), len(g0), 62)
h, l = ax.get_legend_handles_labels()
ax.legend([h[2], h[1], h[0]], [l[2], l[1], l[0]], loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=2,
          handlelength=2.2, columnspacing=1.2)
guardar(fig, OUT + "grafico1_fuentes_caucion.png")

# ---------- 1. Curva de capital diaria (escenario base, versión 1) ----------
vals = np.array([c["valor"] for c in N["curva_diaria"]])
x = np.arange(1, len(vals) + 1)
fig, ax = figura(3.0)
ax.plot(np.r_[0, x], np.r_[1_000_000, vals], color=AZUL, linewidth=1.8, marker="o", markersize=2.5)
ax.yaxis.set_major_formatter(lambda v, _: miles(v))
ax.set_xlabel(f"Rueda (orden cronológico, {len(vals)} ruedas en {len(BLOQUES)} bloques)")
ax.set_ylabel("Capital ($)")
ejes(ax)
ax.set_ylim(995_000, vals[-1] + 12_000)
separadores(ax, np.cumsum([b["ruedas"] for b in BLOQUES]), len(vals), vals[-1] + 12_000)
ax.annotate(f"{miles(vals[-1])}\n(+{coma(N['escenarios'][BASE_ESC]['retorno_pct'])}%)", xy=(x[-1], vals[-1]),
            xytext=(0, -10), textcoords="offset points", ha="center", va="top", fontsize=T_ROTULO, color=TINTA)
guardar(fig, OUT + "grafico2_curva_capital.png")

# ---------- 2. Tasa implícita por clase (IC 95%) frente a la caución, por bloque ----------
ST = json.load(open(OUT + "estadistica.json"))
C2 = ST["C_brecha"]
off = {"Soberanos": -0.27, "ON": -0.09, "Acciones": 0.09, "CEDEARs": 0.27}
xi = np.arange(len(BLOQUES))
fig, ax = figura(3.3)
for i, b in enumerate(BLOQUES):
    cau_b = [r for r in C2 if r["bloque"] == b["label"]][0]["caucion"] * 100
    ax.plot([i - 0.4, i + 0.4], [cau_b, cau_b], color=TINTA, linewidth=2, solid_capstyle="butt",
            label="Caución base (VWAP de la rueda anterior)" if i == 0 else None)
    for c in COLOR_CLASE:
        r = [r for r in C2 if r["bloque"] == b["label"] and r["clase"] == c]
        if not r:
            continue
        r = r[0]
        y = r["impl_media"] * 100
        lo, hi = (r["ic95_inf"] + r["caucion"]) * 100, (r["ic95_sup"] + r["caucion"]) * 100
        ax.errorbar(i + off[c], y, yerr=[[y - lo], [hi - y]], fmt="o", color=COLOR_CLASE[c], markersize=4,
                    elinewidth=1.4, capsize=0, label=c if i == 0 else None)
ax.axhline(0, color=BASE, linewidth=0.8)
ax.set_xticks(xi, ROT2)
ax.set_ylabel("TNA")
ax.yaxis.set_major_formatter(formato_pct(0))
ejes(ax)
ax.legend(ncol=5, loc="upper center", bbox_to_anchor=(0.5, -0.2), handletextpad=0.3, columnspacing=1.0)
guardar(fig, OUT + "grafico4_tasa_vs_caucion.png")

# ---------- 3. Pesos de tomadoras: compensados por el bot o cubiertos con caución ----------
cob = pd.read_parquet(f"{DATA}/cobertura_diaria.parquet")
cob = cob[cob["escenario"] == BASE_ESC]
bot, resto = [], []
for b in BLOQUES:
    cb = cob[cob["bloque"] == b["bloque"]]
    bot.append(cb["compensado"].sum() / 1e6)
    resto.append((cb["pesos_tomadoras"].sum() - cb["compensado"].sum()) / 1e6)
fig, ax = figura(3.0)
ax.bar(xi, bot, 0.5, color=AZUL, label="Compensados por colocadoras del bot")
ax.bar(xi, resto, 0.5, bottom=bot, color=CELESTE, label="No compensados: los coloca el operador en caución")
for i, b in enumerate(BLOQUES):
    ax.text(xi[i], bot[i] + resto[i] + 0.15, f"{b['compensado_pct']:.0f}% compensado", ha="center", va="bottom",
            fontsize=T_ROTULO, color=TINTA)
ax.set_xticks(xi, ROT2)
ax.set_ylabel("Millones de pesos")
ejes(ax)
ax.set_ylim(0, max(a + b for a, b in zip(bot, resto)) * 1.15)
ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.22), ncol=2, columnspacing=1.2)
guardar(fig, OUT + "grafico3_compensacion.png")

# ---------- 4. Sensibilidad a un slippage uniforme por pata ----------
S = N["slippage"]
sx = [s["slippage_bps"] for s in S]
sy = [s["retorno_motor_pct"] for s in S]
sp = [s["operaciones_con_perdida_pct"] for s in S]
xs = np.arange(len(sx))
fig, ax = figura(3.0)
barras = ax.bar(xs, sy, 0.5, color=AZUL)
for r, v, p in zip(barras, sy, sp):
    ax.text(r.get_x() + r.get_width() / 2, v + 0.1, f"{coma(v)}%", ha="center", va="bottom", fontsize=T_ROTULO, color=TINTA)
ax.set_xticks(xs, [f"{int(v)} {'bp' if int(v) == 1 else 'bps'} por pata\n{coma(p, 1)}% de operaciones\ncon pérdida"
                   for v, p in zip(sx, sp)], fontsize=T_ROTULO - 0.5)   # con 15 cm de ancho, los rótulos no entran a 8 pt
ax.axhline(0, color=BASE, linewidth=0.8)
ax.set_ylabel(f"Resultado sobre el capital ({N['ruedas']} ruedas)")
ax.yaxis.set_major_formatter(formato_pct(0))
ejes(ax)
ax.set_ylim(0, max(sy) * 1.15)
guardar(fig, OUT + "grafico6_slippage.png")
print("ok")
