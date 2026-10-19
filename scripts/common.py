"""Parámetros, rutas y utilidades compartidas por todos los scripts del pipeline."""
import os
from pathlib import Path
import pandas as pd

# ---- Rutas (relativas a la carpeta del proyecto: la que contiene /scripts) ----
BASE = Path(__file__).resolve().parent.parent
# Carpeta con los datos crudos: los .xlsx intradiarios + caucion_a3.csv.
# Se puede cambiar con la variable de entorno TESIS_DATOS_CRUDOS.
RAW = Path(os.environ.get("TESIS_DATOS_CRUDOS", BASE / "datos_crudos"))
DATA = Path(os.environ.get("TESIS_DATA_DIR", BASE / "data"))   # resultados intermedios (se regeneran)
OUT = BASE / "output"       # cifras y gráficos finales
DATA.mkdir(exist_ok=True)
OUT.mkdir(exist_ok=True)

CAPITAL = 1_000_000.0

# Costos: solo derechos de mercado (mesa de dinero, sin comisión del broker). Se pagan en cada punta
# (compra y venta) sobre el valor operado:
#   RF (bonos y ON) 0,010% · RV 0,050% · CEDEARs 0,050%
COSTO_OP = {"RF": 0.0001, "RV": 0.0005, "CEDEAR": 0.0005}

# Caución: derechos de 0,045% como TASA ANUAL prorrateada por plazo, para el colocador y para el tomador.
# Colocador cobra (tasa - 0,045%); tomador paga (tasa + 0,045%).
COSTO_CAUCION_ANUAL = 0.00045

# Universo (cuarta entrega): se dieron de baja YM34O y YM43O (casi no operaban en CI).
CATEGORIA = {
    "AL30": "RF", "GD30": "RF", "YMCIO": "RF",
    "GGAL": "RV", "YPFD": "RV",
    "GLD": "CEDEAR", "SLV": "CEDEAR", "KO": "CEDEAR", "SPY": "CEDEAR",
}

# Sizing
POS_BASE = float(os.environ.get("TESIS_POS_BASE", "0.05"))  # % del capital por bucket, repartido entre señales

# Grilla de barras (las pruebas de sensibilidad la cambian por variable de entorno)
FREQ_MIN = int(os.environ.get("TESIS_FREQ_MIN", "15"))     # largo del bucket en minutos
OFFSET_MIN = int(os.environ.get("TESIS_OFFSET_MIN", "0"))  # corrimiento de la grilla en minutos
TOPE_POSICION = 0.15 # tope por posición individual
INVENTARIO_ESPECIE = 100_000.0  # tenencia por especie disponible para "tomo con títulos"
LIMITE_FALTANTE = 1_000_000.0   # pesos netos faltantes que el operador cubre tomando caución
# Tope de liquidez: cada orden hasta esta fracción del volumen promedio por bucket de la pata CI de la especie
# (sizing por volumen de la segunda entrega; lo usan la escalabilidad y la versión 3).
PARTICIPACION = 0.10

# Versión 3 (definitiva del modelo): presupuesto del bucket por edge + margen de seguridad + tope de liquidez
# + pata CI primero. El margen de seguridad es el costo esperado de ejecución (medio tick por pata) más un
# colchón igual por ruido de ejecución: el bot solo opera si el edge supera MARGEN_TICKS_V3 ticks por pata.
MARGEN_TICKS_V3 = 1.0
# Escenario de ejecución "realista" con el que se comparan las versiones: slippage pagado por pata (ticks) y
# demora de la pata 24hs respecto de la CI (segundos).
COSTO_REALISTA_TICKS = 0.5
DEMORA_REALISTA_S = 30

# Caución: serie oficial de A3 Mercados (CAARS, caución en pesos), archivo caucion_a3.csv.
# Para cada rueda se toma la caución del plazo que corresponde (1 día; 3 los viernes; 4 si hay feriado),
# es decir la que liquida el mismo día que la pata 24hs.
# Referencias (A3 no publica tasa de apertura):
#   vwap_ant -> VWAP de la rueda anterior: la última tasa conocida al abrir (sin look-ahead). BASE.
#   vwap     -> VWAP del día (tasa promedio ponderada por monto; look-ahead)
#   minimo   -> mínimo del día (look-ahead; favorece "coloco con títulos")
#   maximo   -> máximo del día (look-ahead; favorece "tomo con títulos")
#   cierre   -> última tasa del día (look-ahead)
CAUCION_ARCHIVO = "caucion_a3.csv"
BASE = "vwap_ant"
ESCENARIOS = ["vwap_ant", "vwap", "minimo", "maximo", "cierre"]
ESCENARIO_LABEL = {
    "vwap_ant": "VWAP de la rueda anterior (sin look-ahead)",
    "vwap": "VWAP del día (look-ahead)",
    "minimo": "Mínimo del día (look-ahead)",
    "maximo": "Máximo del día (look-ahead)",
    "cierre": "Última tasa del día (look-ahead)",
}

BLOQUES = {
    "estres_2025": ("2025-09-24", "2025-10-13"),
    "calma_dic_2025": ("2025-12-09", "2025-12-19"),
    "calma_abr_2026": ("2026-04-13", "2026-04-24"),
    "calma_jun_2026": ("2026-06-22", "2026-07-03"),
    "reciente_sep_2026": ("2026-09-07", "2026-09-18"),
    "estres_sep_2026": ("2026-09-21", "2026-10-02"),
}
BLOQUE_ORDEN = list(BLOQUES)
BLOQUE_LABEL = {
    "estres_2025": "Estrés (sep-oct '25)",
    "calma_dic_2025": "Calma dic. ('25)",
    "calma_abr_2026": "Calma abr. ('26)",
    "calma_jun_2026": "Calma jun-jul ('26)",
    "reciente_sep_2026": "Reciente sep. ('26)",
    "estres_sep_2026": "Estrés sep-oct ('26)",
}
BLOQUES_ESTRES = ["estres_2025", "estres_sep_2026"]


# Feriados nacionales dentro o al borde de las ventanas (el 10/10/2025 cae dentro del bloque de estrés 2025)
FERIADOS = {"2025-10-10", "2025-12-08", "2026-04-02", "2026-04-03", "2026-06-15", "2026-10-12"}

# Ruedas que se excluyen completas
# (misma regla que los días de dividendo de GGAL: se excluye la rueda para todas las especies)
EXCLUIR_RUEDAS = {
    "2026-09-07": "Feriado en EE.UU. (Labor Day): los CEDEARs no operaron en CI",
    "2026-06-29": "YMCIO paga renta y amortización el 30/6/2026: ese día la pata CI liquida con el pago "
                  "y la 24hs sin él (17% de diferencia); se excluye la rueda para todas las especies",
}
# Especie-rueda que se excluye sola (sin casos vigentes; se deja el mecanismo)
EXCLUIR_ESPECIE_RUEDA = {}


def dias_liquidacion(fecha_str: str) -> int:
    """Días corridos entre T+0 y T+1 hábil (saltea fines de semana y feriados).
    Viernes -> lunes = 3 días; jueves 9/10/2025 -> lunes 13/10/2025 = 4 días (feriado del viernes 10)."""
    f = pd.Timestamp(fecha_str)
    sig = f + pd.Timedelta(days=1)
    while sig.weekday() >= 5 or sig.strftime("%Y-%m-%d") in FERIADOS:
        sig += pd.Timedelta(days=1)
    return (sig - f).days
