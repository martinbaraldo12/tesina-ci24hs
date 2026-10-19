# Backtest arbitraje CI/24hs vs caución — BYMA (trabajo final)

Código del backtest del trabajo final de la tesina: de los Excel intradiarios a las cifras, las figuras y la
página web (`output/Backtest_CI24hs.html`), donde se puede analizar y revisar todo. Todas las cifras de la
tesina salen de los archivos que generan estos scripts.

## Correrlo sin instalar nada

**En el navegador (GitHub Codespaces).** En la página del repo: botón verde **Code > Codespaces > Create
codespace on main**. Se abre un VS Code en el navegador que instala Python y las librerías solo
(tarda unos minutos la primera vez). Cuando termina, en la terminal:

```
python run_all.py
```

Tarda entre 6 y 10 minutos. Los resultados quedan en `output/` (cifras, figuras y página web); para bajarlos,
clic derecho sobre el archivo > Download. La página `output/Backtest_CI24hs.html` se baja igual y se abre
con doble clic.

**En la nube, sin abrir nada (GitHub Actions).** Pestaña **Actions > Correr el backtest > Run workflow**
(lo pueden usar el dueño del repo y los colaboradores; cualquier otra persona puede hacer un fork y correrlo en su copia).
Corre el pipeline completo y deja todo para descargar en
**Artifacts > resultados** al final de la corrida (unos 7 minutos).

**Datos.** El repo trae la caución de A3 Mercados (pública) y, en `datos_procesados/`, la salida de los pasos 1
y 3 (barras de 15 minutos, registros de precio con su hora y ticks de las 54 ruedas). Los Excel intradiarios
de BYMADATA (el servicio pago de datos de mercado de BYMA) no se suben: si `datos_crudos/` no los tiene, `run_all.py` usa
`datos_procesados/` y saltea los pasos 1 y 3; el resto del pipeline es el mismo y da los mismos resultados.
Con los Excel en `datos_crudos/`, corre desde cero.

## Qué cambió respecto de la tercera entrega

- **Base unificada:** 54 ruedas en 6 bloques. Se sumaron calma jun-jul 2026 y una ventana de
  sep-oct 2026, y el bloque de estrés 2025 se extendió hasta el 13/10/2025 (8, 9 y 13/10).
- **Universo:** 9 especies, sin YM34O ni YM43O.
- **Ruedas excluidas:** 7/9/2026 (feriado en EE.UU., los CEDEARs no operaron en CI) y 29/6/2026 (YMCIO
  paga renta y amortización el 30/6: ese día la CI liquida con el pago y la 24hs sin él; se excluye la
  rueda para todas las especies, igual que los días de dividendo).
- **Días de liquidación con calendario de feriados:** 42 ruedas a 1 día, 11 viernes a 3 días y el jueves
  9/10/2025 a 4 días (feriado del 10/10). Spread, tasa implícita, edge y caución usan esos días.
- **Caución:** serie oficial de A3 Mercados (`caucion_a3.csv`, ticker CAARS en pesos), por plazo, con VWAP
  ponderado por monto, mínimo, máximo y última tasa. Para cada rueda se toma el plazo que liquida junto
  con la 24hs. Base sin look-ahead: VWAP de la rueda anterior. Sensibilidades: VWAP, mínimo, máximo y
  última del día. Reemplaza a la serie anterior, cuyos valores de 2025 y abril 2026 no coincidían con el
  mercado (ver `documentacion/`).
- **Costos:** solo derechos de mercado en cada punta (RF 0,01%, acciones y CEDEARs 0,05%; caución 0,045%
  anual prorrateado). La tercera entrega sumaba además una comisión igual al derecho, que una mesa no paga.
- **Sizing por zonas de pesos:** generaliza la regla de la tercera entrega para admitir dos tasas; con una
  sola tasa da exactamente lo mismo (verificado). Admite ponderación igual o por edge y un umbral de edge.
- **Orden estable** dentro de un mismo segundo, para que el cierre de cada bucket sea el último precio
  registrado; cada registro de precio se guarda con su hora (`data/eventos_precio/`).
- **Pruebas nuevas:** escalabilidad (paso 12), ejecución y latencia (13), robustez y sensibilidad (14),
  versiones de la estrategia, bases de capital, margen de seguridad, control 2025/2026, robustez y
  sensibilidad de la versión definitiva, día de la semana y horario, precio de ejecución (cierre, apertura,
  OHLC/4 y promedio de precios del bucket siguiente), comisiones de broker y liquidez de las órdenes (15).
- **Modelo definitivo: versión 3.** Presupuesto del bucket en proporción al edge, margen de seguridad de un
  tick por pata (`MARGEN_TICKS_V3`: medio tick de costo esperado + medio de colchón), cada orden hasta el 10%
  del volumen promedio por bucket de la pata CI (`PARTICIPACION`) y la pata CI primero. Las versiones 1
  (peso igual, sin margen; la de la tercera entrega) y 2 (peso por edge, margen de medio tick) quedan como
  versiones anteriores.
- **Página web** actualizada al modelo definitivo (paso 16).

## 1. Estructura de la carpeta

```
CI24hs_backtest/
├── run_all.py            <- corre todo en orden
├── requirements.txt      <- librerías de Python
├── scripts/              <- pasos del pipeline + common.py (parámetros) + ejecucion_comun.py
├── scripts_web/          <- página web: exportar datos, motor JS, plantilla y armado
├── documentacion/        <- datos de la comparación de fuentes de caución
├── datos_procesados/     <- salida de los pasos 1 y 3 (se usa si no están los Excel)
├── datos_crudos/         <- ACÁ van los datos
│   ├── series_intradiarias_*.xlsx   (todos los Excel intradiarios; no vienen en el repo)
│   └── caucion_a3.csv               (caución oficial de A3 Mercados; viene en el repo)
├── .devcontainer/        <- configuración de GitHub Codespaces
└── .github/workflows/    <- botón "Correr el backtest" de GitHub Actions
```

Al correr se crean `data/` (resultados intermedios, CSV y parquet) y `output/` (cifras, figuras y página web).

## 2. Instalación (una sola vez)

Python 3.11 o 3.12 (python.org; en Windows tildá "Add Python to PATH"). En la carpeta `CI24hs_backtest`:

**Windows**
```
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

**Mac / Linux**
```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```


## 3. Correr

```
python run_all.py            # todo (unos 11 minutos con los Excel; unos 6 con datos_procesados/)
python run_all.py --desde 4  # retoma desde el paso 4 sin volver a leer los Excel
```

Si algo falla, el script dice en qué paso y cómo retomar. Después de correr con los Excel,
`python run_all.py --exportar-procesados` actualiza `datos_procesados/`.

| Paso | Script | Qué hace |
|---|---|---|
| 1 | 01_manifest.py | Rueda de cada Excel, bloque y exclusiones |
| 2 | 02_caucion.py | Caución A3 del plazo que liquida con la 24hs (5 referencias) |
| 3 | 03_build_bars.py | Barras de 15 min desde COTIZACIÓN y registros de precio con su hora |
| 4 | 04_spread_signal.py | Spread, filtros de calidad y los cuatro edges por referencia de caución |
| 5 | 05_sizing.py | Sizing por zonas: inventario, reinversión de pesos, neto a cubrir |
| 6–8 | 06/07/08 | Modelo A (pandas), Modelo B (VectorBT) y reconciliación |
| 9 | 09_estadistica.py | Efecto viernes, traslado de la caución, brecha, régimen |
| 10–11 | 10_numeros.py, 11_charts.py | numeros.json y Figuras 1, 2, 3, 4 y 6 de la tesina (`output/grafico*.png`) |
| 12 | 12_escalabilidad.py | Capital de 1 M a 500 M, con y sin límite de liquidez; volumen diario de la pata CI y tope con las ruedas anteriores |
| 13 | 13_ejecucion.py | Costo en ticks, bucket siguiente, latencia, mapa de falla (Figura 7) |
| 14 | 14_robustez.py | Robustez y sensibilidad de la versión 1 (Figura 5) y grilla y frecuencia de barras de la versión 3; unos 3 minutos |
| 15 | 15_versiones.py | Versiones 1, 2 y 3, mezclas, margen, control 2025/2026, robustez V3, spreads grandes, escala, día de la semana y horario, precio de ejecución, comisiones, liquidez y tope sin información futura (Figura 8) |
| 16 | scripts_web/armar_pagina.py | Página web `output/Backtest_CI24hs.html` |
| — | estilo_graficos.py, graficos_resultados.py | Estilo común de todas las figuras (letra, tamaños, colores y ancho de 15 cm) y Figuras 5, 7 y 8; `python scripts/graficos_resultados.py` los regenera sin volver a correr los pasos 13 a 15 |

### Dónde está cada consigna de la cuarta entrega

| Consigna | Archivos de `data/` | Sección de la tesina |
|---|---|---|
| Robustez del research | robustez.csv, robustez_ruedas.csv, robustez_v3.csv, versiones_periodos.csv, versiones_bloques.csv | 5 (versión 3: 5.7), 11.5–11.7 |
| Análisis de sensibilidad | robustez.csv, robustez_v3.csv, grilla_v3.csv, dia_semana.csv, horario.csv, margen_v3.csv | 6 (día y horario: 6.6; versión 3: 6.7), 11.3 |
| Supuestos de ejecución | ejecucion_precios.csv, ejec_resultados.csv | 7 (precio de ejecución: 7.3) |
| Costos de transacción | ejec_resultados.csv, comisiones.csv, liquidez_ci.csv, liquidez_v3.csv | 8 (comisiones: 8.5; liquidez: 8.6) |
| Escalabilidad | escalabilidad.csv, versiones_escala.csv | 9, 11.8 |
| Latencia de ejecución | ejec_resultados.csv, versiones_vida.csv | 10 (versión 3: 10.4) |
| Evaluación crítica y conclusiones | todos | 12 y 13 |

El tope de liquidez de la versión 3 (10% del volumen promedio por bucket de la pata CI) usa la mediana del
volumen diario de toda la muestra para decidir el tamaño de cada orden: es un supuesto simplificador, porque al
operar solo se conocen las ruedas anteriores. `data/tope_exante.csv` repite la versión 3 con el tope calculado con
las cinco ruedas anteriores (sección 9.3 de la tesina): el resultado cambia 0,21 puntos o menos en el escenario realista.
En el escenario realista solo se demora la pata 24hs (30 segundos); la pata CI se ejecuta al precio de la señal.

La estrategia está pensada para una mesa de dinero: el backtest solo considera derechos de mercado, y con
comisiones de broker la estrategia es menos rentable (sección 8.5 de la tesina).

No hay VWAP intradiario: el export no trae el volumen de cada operación. Como aproximación se usa el
promedio simple de los precios registrados en el bucket (cada cambio de precio pesa igual).

Resultados esperados (caución: VWAP de la rueda anterior; "realista" = medio tick por pata y 30 segundos
entre patas, CI primero):

- **Versión 3 (definitiva): +12,23% en el escenario realista**; +16,33% sin costos de ejecución; +9,71% con
  un tick por pata.
- Versión 1 (anterior): +8,391% sin costos de ejecución, igual en el Modelo A y el Modelo B; +4,22% realista.
- Versión 2 (anterior): +11,21% realista.

**Actualizar la caución:** `caucion_a3.csv` se bajó de la API pública de A3 Mercados
(https://api.marketdata.mae.com.ar/api/mercado/titulo/historicocauciones, la misma que usa
https://marketdata.mae.com.ar/cauciones/historico), filtrando CAARS en pesos con plazo de 1 a 5 días.
Columnas: fecha;plazo;liquidacion;vwap;minimo;maximo;ultima;monto (tasas en % TNA).

## 4. Parámetros

Todos en `scripts/common.py`: capital, costos por punta, costo de caución, presupuesto por bucket (5%),
tope por posición (15%), inventario por especie (100k), faltante de pesos que cubre el operador (1M),
bloques, feriados, exclusiones, referencias de caución y reglas de la versión 3 (margen de seguridad,
tope de liquidez y escenario realista). Cambiás el valor y corrés `python run_all.py --desde 4`.

## 5. Página web (sin instalar nada)

`output/Backtest_CI24hs.html` corre el mismo backtest en el navegador: se abre con doble clic, en la
versión 3 y el escenario realista. Los parámetros se cambian con controles: referencia de caución, reparto
del presupuesto (igual, raíz, mitad o por edge), margen de seguridad del bot, edge mínimo, slippage pagado
en ticks y en bps, impacto por tamaño, demora de la pata 24hs, capital y tope de liquidez, inventario y
faltante, presupuesto por bucket y derechos. El margen que asume el bot y el costo que se paga son controles
separados. Trae adentro las barras procesadas, la caución, los ticks, el tope de liquidez y el precio de la
pata 24hs con demoras de 5 s a 15 min, y un motor en JavaScript que replica el pipeline. Al abrirse
verifica 42 configuraciones contra Python.
Para regenerarla: `python scripts_web/armar_pagina.py` (también lo hace `run_all.py`).
