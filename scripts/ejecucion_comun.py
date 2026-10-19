"""
Utilidades de ejecución compartidas por los pasos 13 (ejecución y latencia) y 15 (versiones de la estrategia).

  - tick de cada especie y rueda, en fracción del precio (data/ticks.csv);
  - revaluación de las patas del título con slippage por pata y con precios distintos a los de la señal;
  - caución de cada operación como si se cubriera sola (para atribuir el resultado por especie);
  - precio de cada pata N segundos después del fin del bucket, con los registros sin agrupar
    (data/eventos_precio, con la hora de cada precio);
  - bot que descuenta un costo esperado antes de decidir (edges netos de c ticks por pata).

Resultado de cada operación (q = nocional / precio CI de la señal; s = slippage por pata; f = derechos):
  coloco (compro CI, vendo 24hs): q [P24 (1 - s)(1 - f) - Pci (1 + s)(1 + f)]
  tomo   (vendo CI, compro 24hs): q [Pci (1 - s)(1 - f) - P24 (1 + s)(1 + f)]
"""
import glob
import os
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import DATA, CAPITAL

CLASE = {"AL30": "Soberanos", "GD30": "Soberanos", "YMCIO": "ON", "GGAL": "Acciones", "YPFD": "Acciones",
         "GLD": "CEDEARs", "SLV": "CEDEARs", "KO": "CEDEARs", "SPY": "CEDEARs"}
ORDEN = ["AL30", "GD30", "YMCIO", "GGAL", "YPFD", "GLD", "KO", "SLV", "SPY"]
CLASES = ["Soberanos", "ON", "Acciones", "CEDEARs"]
BUCKET = pd.Timedelta(minutes=15)

# ---- tick por especie y rueda, en fracción del precio ----
_tk = pd.read_csv(f"{DATA}/ticks.csv")
_tk["tick_frac"] = _tk["tick"] / _tk["precio"]
_tick = _tk.set_index(["fecha", "simbolo"])["tick_frac"]
_tick_med = _tk.groupby("simbolo")["tick_frac"].median()


def tick_de(df):
    """Tick (fracción del precio) de la especie y rueda de cada fila de df."""
    t = pd.Series([_tick.get((f, s), np.nan) for f, s in zip(df["fecha"], df["simbolo"])], index=df.index)
    return t.fillna(df["simbolo"].map(_tick_med))


def patas(df, pci, p24, s_ci=0.0, s_24=0.0):
    """Resultado de las patas del título de cada operación de df con los precios y slippages dados."""
    q = df["nocional"] / df["p_ci"]
    f = df["f"]
    coloco = q * (p24 * (1 - s_24) * (1 - f) - pci * (1 + s_ci) * (1 + f))
    tomo = q * (pci * (1 - s_ci) * (1 - f) - p24 * (1 + s_24) * (1 + f))
    return np.where(df["direccion"] == 1, coloco, tomo)


def caucion_sola(df):
    """Caución de cada operación como si se cubriera sola (tomo coloca los pesos; coloco los toma)."""
    return np.where(df["direccion"] == 2, df["nocional"] * df["r_col"] * df["d"] / 365,
                    -df["nocional"] * df["r_tom"] * df["d"] / 365)


def resumen(nombre, df, pat, cob, **extra):
    """Fila de resultados: total con la cobertura real del neto, y atribución por especie y clase."""
    tot = pat.sum() + cob["pnl_caucion"].sum()
    sola = pd.Series(pat + caucion_sola(df), index=df.index)
    por_esp = sola.groupby(df["simbolo"]).sum() / CAPITAL * 100
    fila = {"escenario": nombre, **extra, "operaciones": len(df), "retorno_pct": tot / CAPITAL * 100,
            "ops_con_perdida_pct": (sola < 0).mean() * 100}
    for s in ORDEN:
        fila[s] = por_esp.get(s, 0.0)
    for c in CLASES:
        fila["clase_" + c] = sum(por_esp.get(s, 0.0) for s in ORDEN if CLASE[s] == c)
    return fila


def descontar_costo(sig, mult):
    """Señal de un bot que solo opera si el edge supera el costo esperado de las dos patas
    (mult ticks por pata): se restan 2 x mult x tick a los cuatro edges y se recalcula la candidata."""
    sg = sig.copy()
    c = 2 * mult * tick_de(sg)
    for col in ["edge1", "edge2", "edge1_col", "edge2_tom"]:
        sg[col] = sg[col] - c
    c1 = (sg["edge1_col"] > 0) | (sg["edge1"] > 0)
    c2 = (sg["edge2_tom"] > 0) | (sg["edge2"] > 0)
    sg["candidata"] = np.where(sg["valido"], np.select([c1 & c2, c1, c2], [3, 1, 2], default=0), 0)
    return sg


# ---- latencia: registros de precio sin agrupar ----
_eventos = None


def _cargar_eventos():
    global _eventos
    if _eventos is None:
        _eventos = {}
        for fn in sorted(glob.glob(f"{DATA}/eventos_precio/*.parquet")):
            e = pd.read_parquet(fn)          # en el orden del export (el mismo que usan las barras)
            for (s, v), g in e.groupby(["simbolo", "vencimiento"]):
                _eventos[(os.path.basename(fn)[:10], s, v)] = (g["hora"].values, g["precio"].values)
    return _eventos


def precio_en(fecha, simbolo, venc, t):
    """Último precio operado de la pata antes del instante t (el bucket de las 10:30 cierra antes de las 10:45:00)."""
    horas, precios = _cargar_eventos()[(fecha, simbolo, venc)]
    i = np.searchsorted(horas, np.datetime64(t), side="left") - 1
    return precios[max(i, 0)]


_cache = {}


def precios_demora(df, venc, seg, clave, largo_min=15):
    """Precio de la pata `venc` `seg` segundos después del fin del bucket de cada operación de df.
    `clave` identifica a df en la caché (df distintos deben usar claves distintas); `largo_min` es el
    largo del bucket en minutos (15 salvo en las pruebas de grilla)."""
    key = (clave, venc, seg, largo_min)
    if key not in _cache:
        T = (df["bucket"] + pd.Timedelta(minutes=largo_min)).values
        dt = np.timedelta64(int(seg), "s")
        _cache[key] = np.array([precio_en(f, s, venc, t + dt) for f, s, t in zip(df["fecha"], df["simbolo"], T)])
    return _cache[key]
