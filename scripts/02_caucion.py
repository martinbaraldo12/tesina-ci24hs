"""
Paso 2 — Caución diaria (serie oficial de A3 Mercados).

Lee caucion_a3.csv: caución en pesos (ticker CAARS) de A3 Mercados, una fila por rueda y plazo, con
  fecha;plazo;liquidacion;vwap;minimo;maximo;ultima;monto   (tasas en % TNA; monto en pesos)
El VWAP es la tasa promedio ponderada por monto que publica A3 (tasaPP).

Para cada rueda se toma la caución que liquida el mismo día que la pata 24hs: plazo 1 de lunes a jueves,
3 los viernes y 4 en la víspera de un feriado (ej. jueves 9/10/2025). Así la tasa y el spread se miden
sobre los mismos días de financiamiento.

Referencias por rueda (A3 no publica tasa de apertura):
  vwap_ant -> VWAP de la caución de la rueda anterior, la que vence el día de hoy: la última tasa conocida
              al abrir (sin look-ahead). Escenario base.
  vwap     -> VWAP del día (look-ahead)
  minimo   -> mínimo del día (look-ahead; favorece "coloco con títulos")
  maximo   -> máximo del día (look-ahead; favorece "tomo con títulos")
  cierre   -> última tasa del día (look-ahead)
Salida: data/caucion_diaria.csv
"""
import os
import sys
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import RAW, DATA, CAUCION_ARCHIVO, dias_liquidacion

a3 = pd.read_csv(RAW / CAUCION_ARCHIVO, sep=";", dtype={"plazo": str})
for c in ["vwap", "minimo", "maximo", "ultima"]:
    a3[c] = a3[c].astype(float) / 100.0
a3 = a3.sort_values(["fecha", "plazo"]).reset_index(drop=True)

filas = []
for fecha in sorted(a3["fecha"].unique()):
    d = dias_liquidacion(fecha)
    liq = (pd.Timestamp(fecha) + pd.Timedelta(days=d)).strftime("%Y-%m-%d")
    hoy = a3[(a3["fecha"] == fecha) & (a3["liquidacion"] == liq)]
    if hoy.empty:
        continue                                   # no hubo caución con ese plazo ese día
    x = hoy.iloc[0]
    # caución de la rueda anterior que vence hoy (la última tasa conocida al abrir)
    prev = a3[(a3["fecha"] < fecha) & (a3["liquidacion"] == fecha)].sort_values("fecha")
    filas.append({"fecha": fecha, "plazo_caucion": int(x["plazo"]), "vwap": x["vwap"], "minimo": x["minimo"],
                  "maximo": x["maximo"], "cierre": x["ultima"], "monto": x["monto"],
                  "vwap_ant": prev["vwap"].iloc[-1] if len(prev) else float("nan"),
                  "fecha_ant": prev["fecha"].iloc[-1] if len(prev) else None})

df = pd.DataFrame(filas)
df.to_csv(DATA / "caucion_diaria.csv", index=False)
cols = ["vwap_ant", "vwap", "minimo", "maximo", "cierre"]
print((df.set_index("fecha")[cols] * 100).round(2).tail(20).to_string())
print(f"\n{len(df)} ruedas de caución A3 cargadas (de {a3['fecha'].nunique()} fechas del archivo); "
      f"{df['vwap_ant'].isna().sum()} sin rueda anterior.")
