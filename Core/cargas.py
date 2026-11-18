"""
Cargas muertas sobre la viga presforzada a partir de la SECCIÓN TRANSVERSAL DEL PUENTE.

Se dibuja el tablero (losa, carpeta asfáltica, aceras con alivianamiento, postes y pasamanos)
y se calculan las cargas por metro que recibe UNA viga:

    q_losa     = e_losa · S · γc                       (ancho cooperante S = separación de vigas)
    q_asfalto  = e_asf  · S · γasf                       (ancho cooperante S)
    q_acera    = n_aceras · A_neta · γc / n_vigas      (A_neta = área bruta − alivianamientos)
    q_parantes = n_lados · (N_postes · V_poste · γc + n_barras · L · A_barra · γc) / L / n_vigas
                 con N_postes = número de postes que entran en L, incluidos el inicial y el final.

NO incluye el peso propio de las vigas: ese es el q_G asumido del predimensionamiento,
hasta que se define la sección real. La carga viva q_L es un dato.

Unidades: dimensiones de la sección transversal en cm, luz L en m, pesos específicos en kg/m³,
cargas en kg/m.  (En el desarrollo, las dimensiones se muestran en m.)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as MplPolygon

from presforzado import Cota, Poligono, Seccion, _dibujar_cotas, cota

COLOR_HORMIGON = "#c9d6e3"
COLOR_ASFALTO = "#4d4d4d"
COLOR_BARANDA = "#9fb4c7"
ANCHO_FIG = 7.5                  # ancho común de todas las figuras [pulgadas]


# ---------------------------------------------------------------------------
# 1. ELEMENTOS DEL TABLERO
# ---------------------------------------------------------------------------

@dataclass
class Hueco:
    """Alivianamiento de la acera (coordenadas locales de la acera, en cm)."""
    poligono: Poligono
    x0: float          # inicio horizontal (desde el borde exterior de la acera)
    x1: float          # fin horizontal
    y0: float          # inicio vertical (desde la cara superior de la losa)
    y1: float          # fin vertical
    texto_b: str
    texto_h: str


def hueco_rect(x: float, y: float, b: float, h: float) -> Hueco:
    """Alivianamiento rectangular de b × h con esquina inferior exterior en (x, y)."""
    pol = Poligono([(x, y), (x + b, y), (x + b, y + h), (x, y + h)], hueco=True)
    return Hueco(pol, x, x + b, y, y + h, f"{b:g}", f"{h:g}")


def hueco_circ(xc: float, yc: float, d: float, n: int = 48) -> Hueco:
    """Alivianamiento circular (tubo) de diámetro d con centro en (xc, yc)."""
    r = d / 2
    pts = [(xc + r * math.cos(2 * math.pi * k / n), yc + r * math.sin(2 * math.pi * k / n))
           for k in range(n)]
    return Hueco(Poligono(pts, hueco=True), xc - r, xc + r, yc - r, yc + r, f"⌀{d:g}", f"⌀{d:g}")


@dataclass
class Acera:
    """
    Acera dibujada en coordenadas locales: x = 0 en el borde EXTERIOR del tablero,
    x crece hacia la calzada; y = 0 sobre la cara superior de la losa.
    """
    contorno: list[tuple[float, float]]
    huecos: list[Hueco] = field(default_factory=list)

    @property
    def ancho(self) -> float:
        return max(x for x, _ in self.contorno) - min(x for x, _ in self.contorno)

    @property
    def alto(self) -> float:
        return max(y for _, y in self.contorno) - min(y for _, y in self.contorno)

    @property
    def area_bruta(self) -> float:
        return Seccion([Poligono(self.contorno)]).propiedades().A

    @property
    def area_huecos(self) -> float:
        return sum(Seccion([Poligono(h.poligono.puntos)]).propiedades().A for h in self.huecos)

    @property
    def area_neta(self) -> float:
        return self.area_bruta - self.area_huecos


def acera_rectangular(ancho: float, alto: float, huecos: list[Hueco] | None = None) -> Acera:
    """Acera rectangular de ancho × alto [cm] con alivianamientos opcionales."""
    return Acera([(0, 0), (ancho, 0), (ancho, alto), (0, alto)], list(huecos or []))


def acera_poligono(puntos, huecos: list[Hueco] | None = None) -> Acera:
    """Acera de forma libre (por ejemplo con bordillo), en coordenadas locales [cm]."""
    return Acera([tuple(map(float, p)) for p in puntos], list(huecos or []))


@dataclass
class Poste:
    """Poste (parante) de hormigón: b en el corte transversal, c a lo largo del puente, H de alto [cm]."""
    b: float = 25.0
    c: float = 25.0
    H: float = 90.0
    separacion: float = 250.0     # separación entre postes a lo largo del puente [cm]
    retiro: float = 0.0           # distancia del borde exterior de la acera a la cara exterior del poste [cm]

    @property
    def volumen(self) -> float:   # m³
        return self.b * self.c * self.H / 1e6


@dataclass
class Pasamano:
    """Barandas horizontales de hormigón de b × h [cm], centradas en el eje del poste."""
    b: float = 20.0
    h: float = 20.0
    alturas: tuple[float, ...] = (35.0, 75.0)   # altura del centro de cada barra sobre la acera [cm]

    @property
    def n_barras(self) -> int:
        return len(self.alturas)

    @property
    def area(self) -> float:      # m²
        return self.b * self.h / 1e4


@dataclass
class Tablero:
    """Sección transversal del puente (sin vigas)."""
    L: float = 35.0               # luz del puente [m]
    n_vigas: int = 4
    S: float = 250.0              # separación entre ejes de vigas [cm]
    voladizo: float = 125.0       # solo para el dibujo (el ancho del tablero no interviene) [cm]
    e_losa: float = 20.0          # [cm]
    e_asfalto: float = 5.0        # [cm]
    acera: Acera = field(default_factory=lambda: acera_rectangular(
        90, 20, [hueco_rect(20, 5, 50, 10)]))
    poste: Poste = field(default_factory=Poste)
    pasamano: Pasamano = field(default_factory=Pasamano)
    n_aceras: int = 2             # aceras a ambos lados
    n_lados_baranda: int = 2      # barandas a ambos lados
    gamma_c: float = 2400.0       # hormigón [kg/m³]
    gamma_asf: float = 2300.0     # asfalto [kg/m³]
    bw_dibujo: float = 20.0       # solo para el esquema de las vigas en el dibujo [cm]

    @property
    def ancho_losa(self) -> float:
        return (self.n_vigas - 1) * self.S + 2 * self.voladizo

    @property
    def ancho_calzada(self) -> float:
        return self.ancho_losa - self.n_aceras * self.acera.ancho

    @property
    def ejes_vigas(self) -> list[float]:
        return [self.voladizo + i * self.S for i in range(self.n_vigas)]


# ---------------------------------------------------------------------------
# 2. CÁLCULO DE CARGAS
# ---------------------------------------------------------------------------

@dataclass
class Cargas:
    tablero: Tablero
    q_losa: float
    q_asfalto: float
    q_acera: float
    q_parantes: float
    N_postes: int
    ultimo_tramo: float           # distancia entre los dos últimos postes [m]
    W_postes: float               # peso de los postes de UN lado [kg]
    W_barandas: float             # peso de las barandas de UN lado [kg]

    @property
    def qD(self) -> float:
        return self.q_losa + self.q_asfalto + self.q_acera + self.q_parantes

    def como_dict(self) -> dict:
        """Para pasar directo a presforzado.Datos(**cargas.como_dict(), ...)."""
        return dict(q_losa=round(self.q_losa, 2), q_acera=round(self.q_acera, 2),
                    q_parantes=round(self.q_parantes, 2), q_asfalto=round(self.q_asfalto, 2))

    def guardar_json(self, q_L: float, ruta: str = "Datos/cargas.json") -> str:
        """Guarda L y las cargas por viga para que las lea el cuaderno de diseño."""
        import datetime as _dt
        import json as _json
        contenido = dict(L=self.tablero.L, **self.como_dict(), q_L=round(q_L, 2),
                         qD=round(self.qD, 2), n_vigas=self.tablero.n_vigas,
                         fecha=_dt.datetime.now().strftime("%Y-%m-%d %H:%M"))
        import os as _os
        _os.makedirs(_os.path.dirname(ruta) or ".", exist_ok=True)
        with open(ruta, "w", encoding="utf-8") as f:
            _json.dump(contenido, f, indent=2, ensure_ascii=False)
        return ruta


def numero_postes(L: float, separacion_cm: float) -> int:
    """Postes que entran en L con la separación dada, contando el inicial y el final."""
    return math.ceil(L / (separacion_cm / 100) - 1e-9) + 1


def calcular_cargas(t: Tablero) -> Cargas:
    S, gc = t.S / 100, t.gamma_c
    q_losa = (t.e_losa / 100) * S * gc
    q_asf = (t.e_asfalto / 100) * S * t.gamma_asf
    q_acera = t.n_aceras * (t.acera.area_neta / 1e4) * gc / t.n_vigas

    N = numero_postes(t.L, t.poste.separacion)
    W_p = N * t.poste.volumen * gc
    W_b = t.pasamano.n_barras * t.L * t.pasamano.area * gc
    q_par = t.n_lados_baranda * (W_p + W_b) / t.L / t.n_vigas
    ultimo = t.L - (N - 2) * t.poste.separacion / 100
    return Cargas(t, q_losa, q_asf, q_acera, q_par, N, ultimo, W_p, W_b)


# ---------------------------------------------------------------------------
# 3. DESARROLLO (markdown con LaTeX, para el cuaderno)
# ---------------------------------------------------------------------------

def _m(x_cm: float) -> str:
    return f"{x_cm / 100:.2f}"


def _ctx(c: Cargas):
    t = c.tablero
    return t, t.acera, _m(t.S), f"{t.gamma_c:,.0f}"


def md_geometria(c: Cargas) -> str:
    t, a, S, _ = _ctx(c)
    return rf"""
- Vigas: $n = {t.n_vigas}$, separación $S = {S}$ m → **ancho tributario de cada viga $= {S}$ m**
- El ancho total del tablero no interviene en las cargas (en el dibujo es solo ilustrativo).
"""


def md_losa(c: Cargas) -> str:
    t, a, S, gc = _ctx(c)
    return rf"""
$$q_{{losa}} = e_{{losa}}\cdot S \cdot \gamma_c = ({_m(t.e_losa)})({S})({gc}) = \mathbf{{{c.q_losa:,.2f}\ kg/m}}$$
"""


def md_asfalto(c: Cargas) -> str:
    t, a, S, gc = _ctx(c)
    return rf"""
$$q_{{asf}} = e_{{asf}}\cdot S \cdot \gamma_{{asf}} = ({_m(t.e_asfalto)})({S})({t.gamma_asf:,.0f}) = \mathbf{{{c.q_asfalto:,.2f}\ kg/m}}$$
"""


def md_acera(c: Cargas) -> str:
    t, a, S, gc = _ctx(c)
    filas_h = "\n".join(
        f"| {i} | {h.x0:g} – {h.x1:g} | {h.y0:g} – {h.y1:g} | "
        f"{Seccion([Poligono(h.poligono.puntos)]).propiedades().A:,.2f} |"
        for i, h in enumerate(a.huecos, start=1)) or "| — | — | — | 0.00 |"
    return rf"""
| Alivianamiento | x [cm] | y [cm] | Área [cm²] |
|---|---|---|---|
{filas_h}

- $A_{{bruta}} = {a.area_bruta:,.2f}$ cm²
- $A_{{huecos}} = {a.area_huecos:,.2f}$ cm²
- $A_{{neta}} = {a.area_bruta:,.2f} - {a.area_huecos:,.2f} = {a.area_neta:,.2f}$ cm² $= {a.area_neta / 1e4:.4f}$ m²

$$q_{{acera}} = \frac{{n_{{aceras}}\cdot A_{{neta}}\cdot\gamma_c}}{{n_{{vigas}}}} = \frac{{({t.n_aceras})({a.area_neta / 1e4:.4f})({gc})}}{{{t.n_vigas}}} = \mathbf{{{c.q_acera:,.2f}\ kg/m}}$$
"""


def md_parantes(c: Cargas) -> str:
    t, a, S, gc = _ctx(c)
    return rf"""
**a) Postes** — sección $({_m(t.poste.b)} \times {_m(t.poste.c)})$ m, altura ${_m(t.poste.H)}$ m, cada $s = {_m(t.poste.separacion)}$ m

- Número de postes por lado (incluye el inicial y el final):

$$N = \left\lceil \frac{{L}}{{s}} \right\rceil + 1 = \left\lceil \frac{{{t.L:g}}}{{{_m(t.poste.separacion)}}} \right\rceil + 1 = {c.N_postes}$$

- Último tramo entre postes $= {c.ultimo_tramo:.2f}$ m
- Volumen de un poste: $V = ({_m(t.poste.b)})({_m(t.poste.c)})({_m(t.poste.H)}) = {t.poste.volumen:.4f}$ m³
- Peso de los postes de un lado: $W_{{postes}} = N\,V\,\gamma_c = ({c.N_postes})({t.poste.volumen:.4f})({gc}) = {c.W_postes:,.2f}$ kg

**b) Pasamanos** — {t.pasamano.n_barras} barras de $({_m(t.pasamano.b)} \times {_m(t.pasamano.h)})$ m a lo largo de $L$

- Área de una barra: $A_b = ({_m(t.pasamano.b)})({_m(t.pasamano.h)}) = {t.pasamano.area:.4f}$ m²
- Peso de los pasamanos de un lado: $W_{{barandas}} = n_b\,L\,A_b\,\gamma_c = ({t.pasamano.n_barras})({t.L:g})({t.pasamano.area:.4f})({gc}) = {c.W_barandas:,.2f}$ kg

**c) Carga por viga**

$$q_{{parantes}} = \frac{{n_{{lados}}\,(W_{{postes}} + W_{{barandas}})}}{{L\cdot n_{{vigas}}}} = \frac{{{t.n_lados_baranda}\,({c.W_postes:,.2f} + {c.W_barandas:,.2f})}}{{({t.L:g})({t.n_vigas})}} = \mathbf{{{c.q_parantes:,.2f}\ kg/m}}$$
"""


def md_resumen(c: Cargas) -> str:
    return rf"""
| Carga | kg/m |
|---|---|
| $q_{{losa}}$ | {c.q_losa:,.2f} |
| $q_{{acera}}$ | {c.q_acera:,.2f} |
| $q_{{parantes}}$ | {c.q_parantes:,.2f} |
| $q_{{asfalto}}$ | {c.q_asfalto:,.2f} |
| **$q_D$** | **{c.qD:,.2f}** |
"""


def desarrollo_md(c: Cargas) -> str:
    return ("**Geometría del tablero**\n" + md_geometria(c) +
            "\n**1. Losa** (área tributaria: ancho $S$)\n" + md_losa(c) +
            "\n**2. Carpeta asfáltica** (área tributaria: ancho $S$)\n" + md_asfalto(c) +
            "\n**3. Aceras con alivianamiento**\n" + md_acera(c) +
            "\n**4. Postes y pasamanos**\n" + md_parantes(c) +
            "\n**Resumen de cargas muertas por viga** (sin el peso propio de la viga)\n" + md_resumen(c))


# ---------------------------------------------------------------------------
# 4. DIBUJO
# ---------------------------------------------------------------------------

def _poly(ax, pts, fc, z=2, ec="black", lw=1.0, ls="-"):
    ax.add_patch(MplPolygon(pts, closed=True, facecolor=fc, edgecolor=ec, lw=lw, ls=ls, zorder=z))


def _rect(x, y, b, h):
    return [(x, y), (x + b, y), (x + b, y + h), (x, y + h)]


def _geometria(t: Tablero):
    """Devuelve las piezas del tablero en coordenadas globales (x desde el borde izquierdo de la losa,
    y = 0 en la cara inferior de la losa)."""
    W, el, a = t.ancho_losa, t.e_losa, t.acera
    piezas = {"losa": _rect(0, 0, W, el), "asfalto": _rect(a.ancho, el, t.ancho_calzada, t.e_asfalto),
              "aceras": [], "huecos": [], "postes": [], "barras": []}
    for lado in (+1, -1):                      # +1 izquierda (x local hacia la derecha), −1 derecha
        x0 = 0 if lado > 0 else W
        g = lambda p: (x0 + lado * p[0], el + p[1])
        piezas["aceras"].append([g(p) for p in a.contorno])
        piezas["huecos"] += [[g(p) for p in h.poligono.puntos] for h in a.huecos]
        po, pa = t.poste, t.pasamano
        xp = po.retiro                          # cara exterior del poste (local)
        piezas["postes"].append([g(p) for p in _rect(xp, a.alto, po.b, po.H)])
        xe = xp + po.b / 2
        for yb in pa.alturas:
            piezas["barras"].append([g(p) for p in _rect(xe - pa.b / 2, a.alto + yb - pa.h / 2, pa.b, pa.h)])
    return piezas


CAPAS = ("losa", "asfalto", "aceras", "baranda")
COLOR_NUEVO = "#d9480f"          # borde de la capa que se acaba de agregar


def _dibujar_tablero(ax, t: Tablero, vigas: bool = True, capas=CAPAS, resaltar: str | None = None):
    g = _geometria(t)

    def borde(capa):
        return dict(ec=COLOR_NUEVO, lw=2.0) if capa == resaltar else {}

    if "losa" in capas:
        _poly(ax, g["losa"], COLOR_HORMIGON, **borde("losa"))
    if "asfalto" in capas:
        _poly(ax, g["asfalto"], COLOR_ASFALTO, z=3, **borde("asfalto"))
    if "aceras" in capas:
        for p in g["aceras"]:
            _poly(ax, p, COLOR_HORMIGON, z=3, **borde("aceras"))
        for p in g["huecos"]:
            _poly(ax, p, "white", z=4, lw=0.8)
    if "baranda" in capas:
        for p in g["postes"]:
            _poly(ax, p, COLOR_HORMIGON, z=3, **borde("baranda"))
        for p in g["barras"]:
            _poly(ax, p, COLOR_BARANDA, z=4, **borde("baranda"))
    if vigas:                                   # esquema de las vigas (no se incluyen en las cargas)
        hv = 0.25 * t.S
        for xv in t.ejes_vigas:
            _poly(ax, _rect(xv - t.bw_dibujo / 2, -hv, t.bw_dibujo, hv), "none", z=1,
                  ec="gray", lw=0.9, ls="--")
            ax.plot([xv, xv], [-hv * 1.1, t.e_losa + t.e_asfalto + 15], color="gray",
                    lw=0.6, ls="-.", zorder=1)
        ax.text(t.ejes_vigas[0] + t.bw_dibujo, -0.6 * hv, "vigas (no incluidas)", fontsize=8,
                color="gray", va="center")


def dibujar_tablero(t: Tablero, capas=CAPAS, resaltar: str | None = None, solo_detalle: bool = False):
    """
    Corte transversal completo y (si hay aceras) el detalle acotado de la acera y la baranda.
    `capas`: qué elementos dibujar ("losa", "asfalto", "aceras", "baranda"), para ir armando
    el tablero paso a paso; `resaltar`: capa recién agregada (se dibuja con borde naranja).
    `solo_detalle`: dibuja solo el detalle acotado de la acera, poste y pasamanos.
    """
    capas = tuple(capas)
    con_detalle = "aceras" in capas
    if solo_detalle and con_detalle:
        fig, ax2 = plt.subplots(figsize=(ANCHO_FIG, 6.5 if "baranda" in capas else 3.3))
    elif con_detalle:
        alto2 = 1.35 if "baranda" in capas else 0.7       # el detalle sin baranda es más bajo
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(ANCHO_FIG, 3.0 + 3.0 * alto2),
                                       gridspec_kw=dict(height_ratios=[1, alto2]))
    else:
        fig, ax1 = plt.subplots(figsize=(ANCHO_FIG, 2.9))
    W, el, a, po, pa = t.ancho_losa, t.e_losa, t.acera, t.poste, t.pasamano
    hay_acera, hay_bar, hay_asf = "aceras" in capas, "baranda" in capas, "asfalto" in capas

    if not solo_detalle:
        # --- (a) corte transversal completo --------------------------------------
        _dibujar_tablero(ax1, t, capas=capas, resaltar=resaltar)
        Sg = W * 0.55                                       # escala de las cotas
        hv = 0.25 * t.S
        ejes = t.ejes_vigas
        cts = [cota((0, -hv), (W, -hv), "h", -0.10 * Sg, f"ancho losa = {W:g}"),
               cota((0, -hv), (ejes[0], -hv), "h", -0.03 * Sg, f"v = {t.voladizo:g}"),
               cota((ejes[-1], -hv), (W, -hv), "h", -0.03 * Sg, f"v = {t.voladizo:g}")]
        cts += [cota((ejes[i], -hv), (ejes[i + 1], -hv), "h", -0.03 * Sg, f"S = {t.S:g}")
                for i in range(t.n_vigas - 1)]
        if hay_bar:
            ytop = el + a.alto + po.H
        elif hay_acera:
            ytop = el + a.alto
        else:
            ytop = el + (t.e_asfalto if hay_asf else 0)
        if hay_acera:
            cts += [cota((0, ytop), (a.ancho, ytop), "h", 0.04 * Sg, f"a = {a.ancho:g}"),
                    cota((a.ancho, ytop), (W - a.ancho, ytop), "h", 0.04 * Sg, f"calzada = {t.ancho_calzada:g}"),
                    cota((W - a.ancho, ytop), (W, ytop), "h", 0.04 * Sg, f"a = {a.ancho:g}")]
        elif hay_asf:
            cts.append(cota((a.ancho, ytop), (W - a.ancho, ytop), "h", 0.04 * Sg, f"calzada = {t.ancho_calzada:g}"))
        if not con_detalle:                                 # espesores en la vista general
            cts.append(cota((W, 0), (W, el), "v", 0.03 * Sg, f"e losa = {t.e_losa:g}"))
            if hay_asf:
                cts.append(cota((W - a.ancho, el), (W - a.ancho, el + t.e_asfalto), "v", 0.03 * Sg,
                                f"e asf = {t.e_asfalto:g}"))
        cx0, cx1, cy0, cy1 = _dibujar_cotas(ax1, cts, Sg)
        ax1.set_xlim(min(-0.03 * W, cx0), max(1.03 * W, cx1))
        ax1.set_ylim(cy0 - 0.03 * Sg, max(cy1, ytop) + 0.04 * Sg)
        ax1.set_aspect("equal")
        ax1.set_title(f"Sección transversal del puente  (L = {t.L:g} m, {t.n_vigas} vigas)", fontsize=10.5)
        ax1.set_xlabel("x [cm]  (cotas en cm)")
        ax1.grid(alpha=0.25)
    if not con_detalle:
        fig.tight_layout()
        return fig

    # --- (b) detalle de la acera izquierda, poste y pasamanos ---------------
    _dibujar_tablero(ax2, t, vigas=False, capas=capas, resaltar=resaltar)
    xr = a.ancho + 60                                   # límite derecho del detalle
    Sd = max(xr, el + a.alto + po.H)
    ys = el                                             # cara superior de la losa
    cts = []
    # alivianamientos: cadena horizontal bajo la acera y vertical a la derecha
    xs = sorted({0.0, a.ancho, *[v for h in a.huecos for v in (h.x0, h.x1)]})
    cts += [cota((xs[i], ys), (xs[i + 1], ys), "h", -0.07 * Sd, f"{xs[i + 1] - xs[i]:g}")
            for i in range(len(xs) - 1)]
    if a.huecos:
        h0 = a.huecos[0]
        yv = sorted({0.0, a.alto, h0.y0, h0.y1})
        cts += [cota((a.ancho, ys + yv[i]), (a.ancho, ys + yv[i + 1]), "v", 0.05 * Sd, f"{yv[i + 1] - yv[i]:g}")
                for i in range(len(yv) - 1)]
    cts += [cota((a.ancho, ys), (a.ancho, ys + a.alto), "v", 0.16 * Sd, f"alto acera = {a.alto:g}"),
            cota((0, ys), (a.ancho, ys), "h", -0.16 * Sd, f"ancho acera = {a.ancho:g}"),
            cota((0, 0), (0, el), "v", -0.06 * Sd, f"e losa = {t.e_losa:g}")]
    if hay_asf:
        cts.append(cota((xr - 10, el), (xr - 10, el + t.e_asfalto), "v", 0.0, f"e asf = {t.e_asfalto:g}"))
    yp = ys + a.alto
    if hay_bar:
        cts += [cota((po.retiro, yp + po.H), (po.retiro + po.b, yp + po.H), "h", 0.05 * Sd, f"b poste = {po.b:g}"),
                cota((po.retiro, yp), (po.retiro, yp + po.H), "v", -0.06 * Sd, f"H = {po.H:g}")]
        if po.retiro > 0:
            cts.append(cota((0, yp), (po.retiro, yp), "h", 0.0, f"{po.retiro:g}"))
        # pasamanos: alturas (cadena a la derecha del poste) y sección de una barra
        xe = po.retiro + po.b / 2
        yb = sorted({0.0, *pa.alturas})
        xcad = po.retiro + po.b + 0.12 * Sd
        cts += [cota((xcad, yp + yb[i]), (xcad, yp + yb[i + 1]), "v", 0.0, f"{yb[i + 1] - yb[i]:g}")
                for i in range(len(yb) - 1)]
        ytb = yp + pa.alturas[-1] + pa.h / 2
        cts.append(cota((xe - pa.b / 2, ytb), (xe + pa.b / 2, ytb), "h", 0.0,
                        f"barra {pa.b:g}×{pa.h:g}"))
    cx0, cx1, cy0, cy1 = _dibujar_cotas(ax2, cts, Sd)
    ytope = yp + (po.H if hay_bar else 0)
    ax2.set_xlim(min(-0.05 * Sd, cx0) - 0.04 * Sd, max(xr, cx1) + 0.02 * Sd)
    ax2.set_ylim(min(-0.02 * Sd, cy0) - 0.04 * Sd, max(ytope, cy1) + 0.05 * Sd)
    ax2.set_aspect("equal")
    ax2.set_title("Detalle: acera con alivianamiento" +
                  (f", poste ({po.b:g}×{po.c:g}×{po.H:g}) y pasamanos ({pa.n_barras} barras)" if hay_bar else ""),
                  fontsize=10.5)
    ax2.set_xlabel("x [cm]  (cotas en cm)")
    ax2.grid(alpha=0.25)
    fig.tight_layout()
    return fig


def dibujar_tributario(t: Tablero, capas=("losa", "asfalto"), resaltar: str | None = None):
    """
    Franja de losa (y asfalto) que carga UNA viga interior: ancho tributario S centrado en su eje.
    Las franjas vecinas se dibujan atenuadas solo como referencia.
    """
    S, el, ea = t.S, t.e_losa, t.e_asfalto
    hay_asf = "asfalto" in capas
    fig, ax = plt.subplots(figsize=(ANCHO_FIG, 2.9))
    x0, x1 = -S / 2, S / 2
    ext = 1.18 * S                                       # se ven las vigas vecinas
    hv = 0.30 * S                                        # alto del esquema de viga

    def borde(capa):
        return dict(ec=COLOR_NUEVO, lw=2.2) if capa == resaltar else dict(ec="black", lw=1.2)

    # losa y asfalto vecinos (atenuados)
    for xa, xb in ((-ext, x0), (x1, ext)):
        _poly(ax, _rect(xa, 0, xb - xa, el), COLOR_HORMIGON, z=1, ec="#9aa7b4", lw=0.6)
        if hay_asf:
            _poly(ax, _rect(xa, el, xb - xa, ea), "#9a9a9a", z=1, ec="#9aa7b4", lw=0.6)
    for xb in (-ext, ext):                               # líneas de corte
        ax.plot([xb, xb], [-3, el + (ea if hay_asf else 0) + 3], color="gray", lw=0.8, ls=(0, (4, 2)))
    # franja tributaria
    ax.add_patch(MplPolygon(_rect(x0, 0, S, el), closed=True, facecolor=COLOR_HORMIGON, hatch="///",
                            zorder=3, **borde("losa")))
    if hay_asf:
        ax.add_patch(MplPolygon(_rect(x0, el, S, ea), closed=True, facecolor=COLOR_ASFALTO, zorder=3,
                                **borde("asfalto")))
    # vigas: la de cálculo y las vecinas (esquema)
    for xv, alfa in ((0, 1.0), (-S, 0.45), (S, 0.45)):
        if abs(xv) > ext + 1:
            continue
        ax.add_patch(MplPolygon(_rect(xv - t.bw_dibujo / 2, -hv, t.bw_dibujo, hv), closed=True,
                                facecolor="none", edgecolor="gray", lw=0.9, ls="--", alpha=alfa, zorder=2))
        ax.plot([xv, xv], [-hv * 1.05, el + ea + 0.06 * S], color="gray", lw=0.7, ls="-.", alpha=alfa)
    ax.text(t.bw_dibujo, -0.55 * hv, " viga en estudio", fontsize=8.5, color="dimgray", va="center")
    for xv in (-S, S):
        if abs(xv) <= ext:
            ax.text(xv + t.bw_dibujo / 2, -0.55 * hv, " viga vecina", fontsize=8, color="gray", va="center")

    Sg = 2 * ext * 0.55
    ytop = el + (ea if hay_asf else 0)
    cts = [cota((x0, ytop), (x1, ytop), "h", 0.10 * Sg, f"ancho tributario S = {S:g}"),
           cota((x0, ytop), (0, ytop), "h", 0.04 * Sg, f"S/2 = {S / 2:g}"),
           cota((0, ytop), (x1, ytop), "h", 0.04 * Sg, f"S/2 = {S / 2:g}"),
           cota((-S, -hv), (0, -hv), "h", -0.05 * Sg, f"S = {S:g}"),
           cota((0, -hv), (S, -hv), "h", -0.05 * Sg, f"S = {S:g}"),
           cota((ext, 0), (ext, el), "v", 0.03 * Sg, f"e losa = {el:g}")]
    if hay_asf:
        cts.append(cota((-ext, el), (-ext, el + ea), "v", -0.03 * Sg, f"e asf = {ea:g}"))   # lado izquierdo
    cx0, cx1, cy0, cy1 = _dibujar_cotas(ax, cts, Sg)
    ax.set_xlim(min(-ext, cx0) - 0.03 * Sg, max(ext, cx1) + 0.03 * Sg)
    ax.set_ylim(cy0 - 0.03 * Sg, cy1 + 0.03 * Sg)
    ax.set_aspect("equal")
    que = "losa y carpeta asfáltica" if hay_asf else "losa"
    ax.set_title(f"Área tributaria de una viga: {que}  (S = {S / 100:.2f} m)", fontsize=10.5)
    ax.set_xlabel("x desde el eje de la viga [cm]  (cotas en cm)")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    return fig


def dibujar_baranda(c: Cargas):
    """Elevación longitudinal de la baranda: postes en L (incluidos inicial y final) y pasamanos."""
    t = c.tablero
    po, pa = t.poste, t.pasamano
    fig, ax = plt.subplots(figsize=(ANCHO_FIG, 2.3))
    H = po.H / 100
    for i in range(c.N_postes):
        x = min(i * po.separacion / 100, t.L)
        ax.add_patch(MplPolygon(_rect(x - po.c / 200, 0, po.c / 100, H), closed=True,
                                facecolor=COLOR_HORMIGON, edgecolor="black", lw=0.8, zorder=3))
    for yb in pa.alturas:
        ax.add_patch(MplPolygon(_rect(0, (yb - pa.h / 2) / 100, t.L, pa.h / 100), closed=True,
                                facecolor=COLOR_BARANDA, edgecolor="black", lw=0.6, zorder=2))
    ax.plot([0, t.L], [0, 0], color="black", lw=1.5)
    ax.set_xlim(-0.5, t.L + 0.5)
    ax.set_ylim(-0.35, H + 0.35)
    ax.set_xlabel("x [m]")
    ax.set_ylabel("[m]")
    ax.set_title(f"Baranda en elevación: {c.N_postes} postes por lado cada {po.separacion / 100:.2f} m "
                 f"(último tramo {c.ultimo_tramo:.2f} m)\n{pa.n_barras} pasamanos de {t.L:g} m", fontsize=10.5)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# 5. EJEMPLO
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os
    import matplotlib
    matplotlib.use("Agg")

    # Ejemplo de uso
    tablero = Tablero(
        L=35.0, n_vigas=4, S=250, voladizo=125, e_losa=20, e_asfalto=5,
        acera=acera_rectangular(90, 20, [hueco_rect(20, 5, 50, 10)]),
        poste=Poste(b=25, c=25, H=90, separacion=250),
        pasamano=Pasamano(b=20, h=20, alturas=(35, 75)),
    )
    c = calcular_cargas(tablero)
    print(desarrollo_md(c))
    os.makedirs("Figuras", exist_ok=True)
    dibujar_tablero(tablero).savefig("Figuras/cargas_seccion_tablero.png", dpi=150, bbox_inches="tight")
    dibujar_baranda(c).savefig("Figuras/cargas_baranda_elevacion.png", dpi=150, bbox_inches="tight")
    print("Figuras guardadas en la carpeta Figuras/")
