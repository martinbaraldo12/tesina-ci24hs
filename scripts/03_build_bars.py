"""
Reconstruye barras OHLCV de 15 minutos a partir del polling crudo.

El export es un polling de la pantalla "hoy" por (SIMBOLO, VENCIMIENTO):
APERTURA/MAXIMO/MINIMO son estadísticas ACUMULADAS DEL DÍA (no de la ventana),
ULTIMO es el último precio operado, y VOLUMEN es el volumen acumulado del día.
La mayoría de las filas son polls idénticos (sin trade nuevo desde el poll anterior).

Metodología de reconstrucción:
  1. Deduplicar a "eventos reales" -> filas donde cambia ULTIMO o VOLUMEN
     respecto de la fila anterior de ese mismo (SIMBOLO, VENCIMIENTO).
  2. Bucketizar esos eventos a barras de 15 min (floor del timestamp).
  3. Por bucket: open=primer ULTIMO del bucket, high/low=max/min ULTIMO
     dentro del bucket, close=último ULTIMO del bucket.
  4. VOLUMEN del export está congelado en el total del día: se guarda como dato diario
     (volumen_dia), no hay volumen por bucket.
  5. Buckets sin eventos: forward-fill del close anterior (n_eventos = 0: sin operaciones).
  6. Grilla de buckets común por día (unión de todos los timestamps
     observados ese día), para que CI y 24hs de todos los instrumentos
     queden alineados en el mismo índice temporal.
"""
import os
import sys
import json
import pandas as pd
import numpy as np
from python_calamine import CalamineWorkbook

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import RAW, DATA, CATEGORIA, FREQ_MIN, OFFSET_MIN

SRC = str(RAW)
OUT_DIR = str(DATA / "bars_15min")
os.makedirs(OUT_DIR, exist_ok=True)
EV_DIR = str(DATA / "eventos_precio")          # cada cambio de precio por pata, con su hora (para latencias)
os.makedirs(EV_DIR, exist_ok=True)

with open(DATA / "manifest.json") as f:
    manifest = json.load(f)

en_bloque = [m for m in manifest if m["status"] == "en_bloque"]
CACHE = os.environ.get("TESIS_EVENTOS_CACHE")

VENC_MAP = {"Cdo": "CI", "24 hs.": "24hs"}

def load_file(fn):
    wb = CalamineWorkbook.from_path(os.path.join(SRC, fn))
    data = wb.get_sheet_by_name("Especies").to_python()
    rows = data[1:]
    df = pd.DataFrame(rows, columns=[
        "simbolo", "fecha", "vencimiento", "apertura", "maximo", "minimo",
        "ultimo", "cotizacion", "apertura2", "maximo2", "minimo2", "ultimo2",
        "variacion", "volumen", "cotizacion2",
    ])
    # COTIZACION (cols H/O, duplicadas) es el precio vivo que se mueve intradía;
    # ULTIMO/APERTURA/MAXIMO/MINIMO son el resumen congelado del día (no sirven
    # para reconstruir barras). VOLUMEN también está congelado a nivel diario.
    df = df[["simbolo", "fecha", "vencimiento", "cotizacion2", "volumen"]].copy()
    df = df.rename(columns={"cotizacion2": "ultimo"})  # "ultimo" = precio vivo (ex-COTIZACION)
    df["fecha"] = pd.to_datetime(df["fecha"])
    df["vencimiento"] = df["vencimiento"].map(VENC_MAP)
    df = df.dropna(subset=["vencimiento"])
    df = df[df["simbolo"].isin(CATEGORIA)]          # universo vigente (sin YM34O / YM43O)
    df["ultimo"] = pd.to_numeric(df["ultimo"], errors="coerce")
    df["volumen"] = pd.to_numeric(df["volumen"], errors="coerce")
    df = df.dropna(subset=["ultimo"])
    return df

def dedup_events(df):
    # VOLUMEN está congelado a nivel diario (no tiene granularidad intradía),
    # así que el único disparador real de un "evento" es el cambio de precio.
    df = df.sort_values(["simbolo", "vencimiento", "fecha"], kind="stable").reset_index(drop=True)  # respeta el orden del export dentro del mismo segundo
    grp = df.groupby(["simbolo", "vencimiento"], sort=False)
    changed = df["ultimo"].ne(grp["ultimo"].shift())
    return df[changed].reset_index(drop=True)

def build_bars_for_day(df, fecha):
    # grilla común de buckets: unión de todos los timestamps floor(15min) del día
    off = pd.Timedelta(minutes=OFFSET_MIN)
    df["bucket"] = (df["fecha"] - off).dt.floor(f"{FREQ_MIN}min") + off
    all_buckets = pd.Index(sorted(df["bucket"].unique()))

    # volumen: solo existe como total diario (congelado) -> no hay bucket-level volume.
    vol_diario = df.groupby(["simbolo", "vencimiento"])["volumen"].last()

    out_rows = []
    for (simbolo, venc), g in df.groupby(["simbolo", "vencimiento"], sort=False):
        g = g.sort_values("fecha", kind="stable")
        agg = g.groupby("bucket").agg(
            open=("ultimo", "first"),
            high=("ultimo", "max"),
            low=("ultimo", "min"),
            close=("ultimo", "last"),
            n_eventos=("ultimo", "size"),     # cambios de precio dentro del bucket
            t_ultimo=("fecha", "last"),       # hora del último precio operado en el bucket
        )
        agg = agg.reindex(all_buckets)
        agg["n_eventos"] = agg["n_eventos"].fillna(0).astype(int)
        # forward-fill close/open/high/low donde no hubo evento (precio no se movió)
        agg["close"] = agg["close"].ffill()
        no_event = agg["open"].isna()
        agg.loc[no_event, "open"] = agg["close"].shift()[no_event]
        agg.loc[no_event, "high"] = agg.loc[no_event, "close"]
        agg.loc[no_event, "low"] = agg.loc[no_event, "close"]
        agg["open"] = agg["open"].fillna(agg["close"])
        agg["simbolo"] = simbolo
        agg["vencimiento"] = venc
        agg["fecha"] = fecha
        agg["volumen_dia"] = vol_diario.get((simbolo, venc), float("nan"))
        agg = agg.reset_index().rename(columns={"index": "bucket"})
        out_rows.append(agg)

    return pd.concat(out_rows, ignore_index=True)

def ticks_del_dia(raw, fecha):
    """Tick empírico: menor salto entre precios distintos operados en la rueda, por especie y pata."""
    filas = []
    for (s, v), g in raw.groupby(["simbolo", "vencimiento"]):
        u = np.unique(g["ultimo"].values)
        if len(u) > 3:
            dif = np.diff(u)
            filas.append({"fecha": fecha, "simbolo": s, "vencimiento": v, "precio": float(np.median(u)),
                          "tick": float(dif[dif > 1e-9].min())})
    return filas


summary, ticks = [], []
for m in en_bloque:
    fn, fecha, bloque = m["file"], m["fecha"], m["bloque"]
    if CACHE:
        # modo rápido (pruebas de grilla): se parte de los cambios de precio ya guardados, sin leer los Excel
        events = pd.read_parquet(os.path.join(CACHE, f"{fecha}.parquet")).rename(
            columns={"hora": "fecha", "precio": "ultimo"})
        events["volumen"] = float("nan")
        raw = events
    else:
        raw = load_file(fn)
        ticks += ticks_del_dia(raw, fecha)
        events = dedup_events(raw)
        events[["simbolo", "vencimiento", "fecha", "ultimo"]].rename(columns={"fecha": "hora", "ultimo": "precio"}) \
            .to_parquet(os.path.join(EV_DIR, f"{fecha}.parquet"), index=False)
    bars = build_bars_for_day(events, fecha)
    bars["bloque"] = bloque
    out_path = os.path.join(OUT_DIR, f"{fecha}.parquet")
    bars.to_parquet(out_path, index=False)
    n_inst = bars["simbolo"].nunique()
    n_buckets = bars["bucket"].nunique()
    summary.append({"fecha": fecha, "bloque": bloque, "raw_rows": len(raw),
                     "eventos": len(events), "n_instrumentos": n_inst, "n_buckets": n_buckets,
                     "bar_rows": len(bars)})
    print(f"{fecha} [{bloque}]: raw={len(raw)} eventos={len(events)} "
          f"instrumentos={n_inst} buckets={n_buckets} bar_rows={len(bars)}")

pd.DataFrame(summary).to_csv(DATA / "build_bars_summary.csv", index=False)
if CACHE:
    sys.exit(0)
# tick por especie y rueda (mínimo entre las dos patas) y su equivalente en tasa implícita a 1 día
t = pd.DataFrame(ticks).groupby(["fecha", "simbolo"]).agg(precio=("precio", "median"), tick=("tick", "min")).reset_index()
t["bps_por_tick"] = t["tick"] / t["precio"] * 1e4
t["tna_1tick_1dia_pct"] = t["bps_por_tick"] / 1e4 * 365 * 100
t.to_csv(DATA / "ticks.csv", index=False)
print("\nListo.")
