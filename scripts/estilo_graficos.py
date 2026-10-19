"""Estilo común de todos los gráficos de la tesina.

Todos los gráficos usan la misma letra (Calibri, o Carlito, su equivalente libre), los mismos tamaños y colores,
y se generan con el mismo ancho con que se insertan en el Word (15 cm, el ancho de texto), así el texto se ve del mismo tamaño en
todos. No llevan título adentro: el título va arriba de la figura en el documento ("Figura N.") y la fuente, abajo.
"""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from matplotlib import font_manager

ANCHO = 15 / 2.54                # pulgadas (15 cm, el ancho de texto con márgenes de 3 cm): el ancho con que se inserta cada figura en la tesina
DPI = 200

AZUL, CELESTE, NARANJA, VERDE, AMARILLO, GRIS = "#2a78d6", "#86b6ef", "#eb6834", "#1baf7a", "#eda100", "#9a9890"
TINTA, TINTA2, TENUE, GRILLA, BASE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"

COLOR_VERSION = {"V1": NARANJA, "V2": GRIS, "V3": AZUL}
NOMBRE_VERSION = {"V1": "Versión 1 (anterior)", "V2": "Versión 2 (anterior)", "V3": "Versión 3 (definitiva)"}
COLOR_CLASE = {"Soberanos": AZUL, "ON": NARANJA, "Acciones": VERDE, "CEDEARs": AMARILLO}
DEMORA = {0: "0", 5: "5 s", 30: "30 s", 60: "1 min", 300: "5 min", 900: "15 min", 1800: "30 min", 3600: "60 min"}

T_TEXTO, T_EJES, T_ROTULO = 8.5, 8, 7.5   # texto general y leyendas; números de los ejes; rótulos sobre los datos


def _fuente():
    disponibles = {f.name for f in font_manager.fontManager.ttflist}
    for nombre in ["Calibri", "Carlito"]:
        if nombre in disponibles:
            return nombre
    return "DejaVu Sans"


plt.rcParams.update({
    "font.family": _fuente(), "font.size": T_TEXTO, "axes.labelsize": T_TEXTO, "axes.titlesize": T_TEXTO,
    "axes.titleweight": "normal", "axes.titlelocation": "left", "legend.fontsize": T_TEXTO, "legend.frameon": False,
    "xtick.labelsize": T_EJES, "ytick.labelsize": T_EJES, "text.color": TINTA, "axes.labelcolor": TINTA2,
    "xtick.color": TINTA2, "ytick.color": TINTA2, "axes.edgecolor": BASE, "axes.spines.top": False,
    "axes.spines.right": False, "figure.facecolor": "white", "axes.facecolor": "white", "savefig.facecolor": "white",
    "figure.dpi": DPI, "savefig.dpi": DPI, "axes.unicode_minus": True,
})


def coma(v, d=2):
    """Número con coma decimal y signo menos tipográfico."""
    return f"{v:.{d}f}".replace(".", ",").replace("-", "−")


def miles(v):
    return f"{v:,.0f}".replace(",", ".")


def formato_pct(d=0):
    return mticker.FuncFormatter(lambda v, _: f"{coma(v, d)}%")


def figura(alto, **kw):
    return plt.subplots(figsize=(ANCHO, alto), **kw)


def ejes(ax, grilla="y"):
    """Ejes limpios: sin bordes superior y derecho, grilla tenue en el eje de los valores."""
    for lado in ["top", "right"]:
        ax.spines[lado].set_visible(False)
    if grilla == "y":
        ax.spines["left"].set_visible(False)
    elif grilla == "x":
        ax.spines["bottom"].set_visible(False)
    if grilla:
        ax.grid(axis=grilla, color=GRILLA, linewidth=0.6)
    ax.set_axisbelow(True)
    ax.tick_params(length=0)


def panel(ax, letra, texto):
    """Rótulo de panel en los gráficos de dos paneles (A, B), en el mismo estilo en todos."""
    ax.set_title(f"{letra}. {texto}", loc="left", fontsize=T_TEXTO, color=TINTA, pad=6)


def guardar(fig, ruta):
    fig.tight_layout()
    fig.savefig(ruta)
    plt.close(fig)
