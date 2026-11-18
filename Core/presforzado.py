"""
Diseño de vigas de hormigón presforzado (simplemente apoyadas).

Flujo:  predimensionamiento -> sección (dibujada por el usuario) -> diseño definitivo en L/2
        -> verificación de esfuerzos (tracción = 0) -> eficiencia Q -> cable resultante
        -> curvas límite -> torones (modo manual).

Unidades:  fuerzas en kg, longitudes de sección en cm, luz y abscisas x en m,
           cargas distribuidas en kg/m, momentos en kg-m, esfuerzos en kg/cm².
Convención de signos de esfuerzos: COMPRESIÓN NEGATIVA, tracción positiva.
Excentricidades: positivas HACIA ABAJO del centro de gravedad.

Geometría: la sección se define como una lista de polígonos (coordenadas x, y en cm,
con y = 0 en la fibra inferior). Cada polígono puede ser macizo o hueco (para cajones).
Los polígonos macizos NO deben superponerse entre sí.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Polygon as MplPolygon


# ---------------------------------------------------------------------------
# 1. GEOMETRÍA
# ---------------------------------------------------------------------------

@dataclass
class Poligono:
    puntos: list[tuple[float, float]]
    hueco: bool = False

    def contiene(self, x: float, y: float) -> bool:
        """Punto dentro del polígono (algoritmo del rayo)."""
        dentro = False
        pts = self.puntos
        n = len(pts)
        for i in range(n):
            x0, y0 = pts[i]
            x1, y1 = pts[(i + 1) % n]
            if (y0 > y) != (y1 > y):
                xc = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
                if x < xc:
                    dentro = not dentro
        return dentro


@dataclass
class Cota:
    """
    Cota (dimensión) entre dos puntos p1 y p2 de la sección [cm].
    tipo = 'h' (horizontal) o 'v' (vertical).
    offset: separación de la línea de cota respecto al punto más exterior
            (+ arriba / derecha, − abajo / izquierda; 0 = cota interior).
    """
    p1: tuple[float, float]
    p2: tuple[float, float]
    tipo: str
    offset: float
    texto: str


def cota(p1, p2, tipo: str, offset: float, texto: str) -> Cota:
    """Atajo para definir cotas propias en secciones libres."""
    if tipo not in ("h", "v"):
        raise ValueError("tipo debe ser 'h' (horizontal) o 'v' (vertical).")
    return Cota(tuple(map(float, p1)), tuple(map(float, p2)), tipo, float(offset), texto)


@dataclass
class Seccion:
    poligonos: list[Poligono]
    nombre: str = "Sección"
    # (opcional) rectángulos (nombre, b, h, y_base) para la tabla de propiedades por partes
    partes: list | None = None
    # (opcional) ancho de alma, para comparar con la recomendación bw = 16-20 cm
    bw: float | None = None
    # cotas de las variables que definen la sección (si está vacía se acota ancho total y h)
    cotas: list[Cota] = field(default_factory=list)

    # --- propiedades calculadas -------------------------------------------
    def _integrales(self):
        """Devuelve (A, Qx, Ixx) respecto al eje y = 0 (fórmulas de Green)."""
        A = Qx = Ixx = 0.0
        for pol in self.poligonos:
            pts = pol.puntos
            a = q = i = 0.0
            n = len(pts)
            for k in range(n):
                x0, y0 = pts[k]
                x1, y1 = pts[(k + 1) % n]
                cr = x0 * y1 - x1 * y0
                a += cr
                q += (y0 + y1) * cr
                i += (y0 * y0 + y0 * y1 + y1 * y1) * cr
            a /= 2.0
            q /= 6.0
            i /= 12.0
            if a < 0:  # polígono definido en sentido horario
                a, q, i = -a, -q, -i
            s = -1.0 if pol.hueco else 1.0
            A += s * a
            Qx += s * q
            Ixx += s * i
        return A, Qx, Ixx

    @property
    def y_min(self) -> float:
        return min(y for p in self.poligonos if not p.hueco for _, y in p.puntos)

    @property
    def y_max(self) -> float:
        return max(y for p in self.poligonos if not p.hueco for _, y in p.puntos)

    def contiene(self, x: float, y: float) -> bool:
        """True si el punto (x, y) está dentro del hormigón (no en un hueco)."""
        en_macizo = any(p.contiene(x, y) for p in self.poligonos if not p.hueco)
        en_hueco = any(p.contiene(x, y) for p in self.poligonos if p.hueco)
        return en_macizo and not en_hueco

    def propiedades(self) -> "Propiedades":
        A, Qx, Ixx = self._integrales()
        if A <= 0:
            raise ValueError("El área de la sección es nula o negativa. Revise los polígonos.")
        yc = Qx / A
        I = Ixx - A * yc ** 2
        h = self.y_max - self.y_min
        c1 = self.y_max - yc     # centroide -> fibra superior (1)
        c2 = yc - self.y_min     # centroide -> fibra inferior (2)
        return Propiedades(A=A, h=h, yc=yc, c1=c1, c2=c2, I=I)


@dataclass
class Propiedades:
    A: float
    h: float
    yc: float
    c1: float
    c2: float
    I: float

    @property
    def S1(self):  # módulo resistente fibra superior
        return self.I / self.c1

    @property
    def S2(self):  # módulo resistente fibra inferior
        return self.I / self.c2

    @property
    def r2(self):  # radio de giro al cuadrado
        return self.I / self.A

    @property
    def k1(self):  # núcleo superior (sobre el c.g.)
        return self.I / (self.A * self.c2)

    @property
    def k2(self):  # núcleo inferior (bajo el c.g.)
        return self.I / (self.A * self.c1)


# --- Constructores de secciones típicas (simétricas respecto a x = 0) -------

def rectangulo(x0: float, y0: float, b: float, h: float, hueco: bool = False) -> Poligono:
    """Rectángulo con esquina inferior izquierda en (x0, y0)."""
    return Poligono([(x0, y0), (x0 + b, y0), (x0 + b, y0 + h), (x0, y0 + h)], hueco)


def poligono(puntos, hueco: bool = False) -> Poligono:
    """Polígono libre: lista de (x, y) en cm, en orden (horario o antihorario)."""
    return Poligono([tuple(map(float, p)) for p in puntos], hueco)


def seccion_T(B: float, t: float, bw: float, h: float) -> Seccion:
    """Viga T: ala de ancho B y espesor t, alma de ancho bw, altura total h."""
    pts = [(-bw / 2, 0), (bw / 2, 0), (bw / 2, h - t), (B / 2, h - t), (B / 2, h),
           (-B / 2, h), (-B / 2, h - t), (-bw / 2, h - t)]
    partes = [("Ala", B, t, h - t), ("Alma", bw, h - t, 0)]
    o = 0.07 * max(B, h)
    yw = (h - t) * 0.9
    cotas = [Cota((-B / 2, h), (B / 2, h), "h", o, f"B = {B:g}"),
             Cota((B / 2, h - t), (B / 2, h), "v", o, f"t = {t:g}"),
             Cota((-bw / 2, yw), (bw / 2, yw), "h", 0, f"bw = {bw:g}"),
             Cota((-bw / 2, 0), (-B / 2, h), "v", -o, f"h = {h:g}")]
    return Seccion([Poligono(pts)], f"T  (B={B:g}, t={t:g}, bw={bw:g}, h={h:g})", partes, bw, cotas)


def seccion_I(bs: float, ts: float, bw: float, bi: float, ti: float, h: float,
              cs_b: float = 0, cs_h: float = 0, ci_b: float = 0, ci_h: float = 0) -> Seccion:
    """
    Viga I:  bs, ts = ancho y espesor del ala superior
             bi, ti = ancho y espesor del ala inferior
             bw     = ancho del alma, h = altura total
             cs_b, cs_h = cartela superior (ancho horizontal, alto vertical), opcional
             ci_b, ci_h = cartela inferior, opcional
    """
    pts = [(-bi / 2, 0), (bi / 2, 0), (bi / 2, ti), (bw / 2 + ci_b, ti), (bw / 2, ti + ci_h),
           (bw / 2, h - ts - cs_h), (bw / 2 + cs_b, h - ts), (bs / 2, h - ts), (bs / 2, h),
           (-bs / 2, h), (-bs / 2, h - ts), (-bw / 2 - cs_b, h - ts), (-bw / 2, h - ts - cs_h),
           (-bw / 2, ti + ci_h), (-bw / 2 - ci_b, ti), (-bi / 2, ti)]
    # eliminar puntos repetidos consecutivos (cuando no hay cartelas)
    limpio = [pts[0]]
    for p in pts[1:]:
        if p != limpio[-1]:
            limpio.append(p)
    partes = None
    if not (cs_b or cs_h or ci_b or ci_h):
        partes = [("Ala superior", bs, ts, h - ts), ("Alma", bw, h - ts - ti, ti),
                  ("Ala inferior", bi, ti, 0)]
    o = 0.07 * max(bs, bi, h)
    yw = h - ts - cs_h - 0.1 * (h - ts - ti)
    hay_cartelas = bool(cs_b or cs_h or ci_b or ci_h)
    cotas = [Cota((-bs / 2, h), (bs / 2, h), "h", o, f"bs = {bs:g}"),
             Cota((bs / 2, h - ts), (bs / 2, h), "v", o, f"ts = {ts:g}"),
             Cota((-bw / 2, yw), (bw / 2, yw), "h", 0, f"bw = {bw:g}"),
             Cota((-bi / 2, 0), (bi / 2, 0), "h", -o, f"bi = {bi:g}"),
             Cota((bi / 2, 0), (bi / 2, ti), "v", o, f"ti = {ti:g}"),
             Cota((-bi / 2, 0), (-bs / 2, h), "v", -(2 if hay_cartelas else 1) * o, f"h = {h:g}")]
    if cs_b or cs_h:   # cartela superior (se acota la del lado izquierdo)
        a, b = (-bw / 2 - cs_b, h - ts), (-bw / 2, h - ts - cs_h)
        if cs_b:
            cotas.append(Cota(a, b, "h", -0.5 * o, f"cs_b = {cs_b:g}"))
        if cs_h:
            cotas.append(Cota(a, b, "v", -0.5 * o, f"cs_h = {cs_h:g}"))
    if ci_b or ci_h:   # cartela inferior (lado izquierdo)
        a, b = (-bw / 2 - ci_b, ti), (-bw / 2, ti + ci_h)
        if ci_b:
            cotas.append(Cota(a, b, "h", 0.5 * o, f"ci_b = {ci_b:g}"))
        if ci_h:
            cotas.append(Cota(a, b, "v", -0.5 * o, f"ci_h = {ci_h:g}"))
    return Seccion([Poligono(limpio)],
                   f"I  (bs={bs:g}, ts={ts:g}, bw={bw:g}, bi={bi:g}, ti={ti:g}, h={h:g})", partes, bw, cotas)


def seccion_cajon(B: float, h: float, ts: float, ti: float, tw: float,
                  Bi: float | None = None) -> Seccion:
    """
    Cajón de una celda.  B = ancho superior, Bi = ancho inferior (por defecto = B),
    ts, ti = espesores de losa superior e inferior, tw = espesor de almas.
    (Almas verticales; para formas más complejas use polígonos libres.)
    """
    Bi = B if Bi is None else Bi
    ext = rectangulo(-Bi / 2, 0, Bi, h - ts)              # parte inferior
    losa = rectangulo(-B / 2, h - ts, B, ts)              # losa superior
    hueco = rectangulo(-Bi / 2 + tw, ti, Bi - 2 * tw, h - ts - ti, hueco=True)
    o = 0.07 * max(B, Bi, h)
    ym = (ti + h - ts) / 2
    cotas = [Cota((-B / 2, h), (B / 2, h), "h", o, f"B = {B:g}"),
             Cota((-Bi / 2, 0), (Bi / 2, 0), "h", -o, f"Bi = {Bi:g}"),
             Cota((B / 2, h - ts), (B / 2, h), "v", o, f"ts = {ts:g}"),
             Cota((Bi / 4, 0), (Bi / 4, ti), "v", 0, f"ti = {ti:g}"),
             Cota((-Bi / 2, ym), (-Bi / 2 + tw, ym), "h", 0, f"tw = {tw:g}"),
             Cota((-Bi / 2, 0), (-B / 2, h), "v", -o, f"h = {h:g}")]
    return Seccion([ext, losa, hueco], f"Cajón  (B={B:g}, Bi={Bi:g}, h={h:g}, ts={ts:g}, ti={ti:g}, tw={tw:g})",
                   None, tw, cotas)


# ---------------------------------------------------------------------------
# 2. DATOS
# ---------------------------------------------------------------------------

@dataclass
class Datos:
    L: float                 # luz [m]
    fc: float                # f'c [kg/cm²]
    perdidas: float          # pérdidas de presfuerzo [%]
    d2: float                # fibra inferior -> cable resultante en L/2 [cm]
    q_losa: float            # [kg/m]
    q_acera: float           # [kg/m]
    q_parantes: float        # [kg/m]
    q_asfalto: float         # [kg/m]
    q_L: float               # carga viva [kg/m]
    gamma_c: float = 2400.0  # peso específico del hormigón [kg/m³]
    fci_factor: float = 0.70  # f'ci = 0.70 f'c
    # --- predimensionamiento ---
    qG_asumido: float = 1000.0  # peso propio asumido para el predimensionamiento [kg/m]
    k_L: float = 16.0           # h = L/k   (16 < k < 22, vigas simplemente apoyadas)
    k_M: float = 0.40           # h = k·√M  (0.38 < k < 0.43; h en cm, M en kg-m)
    es_puente: bool = True      # aplica h = L/25 + 10 cm (puentes de 20 m a 40 m)

    @property
    def qD(self) -> float:
        return self.q_losa + self.q_acera + self.q_parantes + self.q_asfalto


def momento(q: float, L: float, x: float) -> float:
    """Momento de viga simplemente apoyada con carga uniforme: M(x) = q·x·(L−x)/2 [kg-m]."""
    return q * x * (L - x) / 2


# ---------------------------------------------------------------------------
# 3. PREDIMENSIONAMIENTO
# ---------------------------------------------------------------------------

@dataclass
class Predim:
    qT: float
    MG: float
    MT: float
    ML: float
    relacion: float                 # MG/MT
    criterios: list                 # (nombre, fórmula, h [cm])
    h_prom: float
    fc_adm: float                   # 0.45 f'c
    Ac_caso1: float                 # 4·ML/(fc·h)
    Ac_caso2: float                 # 3·MT/(fc·h)
    Ac_req: float
    caso: str
    avisos: list = field(default_factory=list)


def predimensionar(d: Datos) -> Predim:
    L = d.L
    qT = d.qD + d.qG_asumido + d.q_L
    MG = momento(d.qG_asumido, L, L / 2)
    MT = momento(qT, L, L / 2)
    ML = MT - MG
    avisos = []

    crit = [("h = L/k", f"L/{d.k_L:g}", L * 100 / d.k_L)]
    if not 16 <= d.k_L <= 22:
        avisos.append(f"k = {d.k_L:g} está fuera del rango 16 < k < 22 para vigas simplemente apoyadas "
                      "(para cubiertas con sección T se usa 30 < k < 40).")
    if d.es_puente:
        crit.append(("h = L/25 + 10 cm", f"{L:g}/25 + 0.10", L * 100 / 25 + 10))
        if not 20 <= L <= 40:
            avisos.append(f"El criterio L/25 + 10 cm es para puentes de 20 m a 40 m (L = {L:g} m).")
    crit.append(("h = k·√M", f"{d.k_M:g}·√{MT:,.0f}", d.k_M * math.sqrt(MT)))
    if not 0.38 <= d.k_M <= 0.43:
        avisos.append(f"k = {d.k_M:g} está fuera del rango 0.38 < k < 0.43 del criterio h = k·√M.")
    crit.append(("h = 0.07·L", f"0.07·{L:g}", 0.07 * L * 100))
    h_prom = sum(c[2] for c in crit) / len(crit)

    fc = 0.45 * d.fc
    Ac1 = 4 * ML * 100 / (fc * h_prom)
    Ac2 = 3 * MT * 100 / (fc * h_prom)
    rel = MG / MT
    if rel < 0.20:
        caso, Ac = "M_G/M_T < 0.20 → A_c = 4·M_L/(f_c·h)", Ac1
    elif rel > 0.30:
        caso, Ac = "M_G/M_T > 0.30 → A_c = 3·M_T/(f_c·h)", Ac2
    else:
        caso, Ac = "0.20 ≤ M_G/M_T ≤ 0.30 → se adopta el mayor de ambos casos", max(Ac1, Ac2)
    return Predim(qT, MG, MT, ML, rel, crit, h_prom, fc, Ac1, Ac2, Ac, caso, avisos)


def comparar_predim(pre: Predim, seccion: Seccion) -> list:
    """Compara la sección dibujada con las recomendaciones. Devuelve filas (ítem, recomendado, adoptado, estado)."""
    p = seccion.propiedades()
    filas = []
    dif = (p.h - pre.h_prom) / pre.h_prom * 100
    filas.append(("Altura h", f"{pre.h_prom:.1f} cm", f"{p.h:.1f} cm",
                  f"{'✓' if abs(dif) <= 15 else '⚠'} {dif:+.1f} % respecto al promedio"))
    filas.append(("Área de hormigón A_c", f"≥ {pre.Ac_req:,.0f} cm²", f"{p.A:,.0f} cm²",
                  "✓ suficiente" if p.A >= pre.Ac_req else "⚠ menor que la requerida"))
    if seccion.bw is not None:
        ok = 16 <= seccion.bw <= 20
        filas.append(("Ancho de alma b_w", "16 a 20 cm", f"{seccion.bw:g} cm",
                      "✓ dentro del rango" if ok else "⚠ fuera del rango recomendado"))
    else:
        filas.append(("Ancho de alma b_w", "16 a 20 cm", "—", "no verificable en polígono libre"))
    return filas


@dataclass
class TPredim:
    """Sección T inicial obtenida del predimensionamiento (iteración 1)."""
    seccion: Seccion
    h: float          # altura adoptada (promedio redondeado) [cm]
    t: float          # espesor del ala [cm]
    bw: float         # ancho del alma [cm]
    B_calc: float     # ancho del ala calculado [cm]
    B: float          # ancho del ala adoptado (redondeado hacia arriba) [cm]
    redondeo_h: float


def seccion_T_predim(pre: Predim, t: float = 16.0, bw: float = 16.0, redondeo_h: float = 5.0) -> TPredim:
    """
    T inicial a partir del predimensionamiento:
        h = promedio de criterios redondeado a `redondeo_h` cm
        B = [A_c,req − (h − t)·b_w] / t   (redondeado hacia arriba al cm; mínimo b_w)
    """
    h = round(pre.h_prom / redondeo_h) * redondeo_h
    B_calc = (pre.Ac_req - (h - t) * bw) / t
    B = max(math.ceil(B_calc - 1e-9), bw)
    sec = seccion_T(B, t, bw, h)
    sec.nombre = f"T  (B={B:g}, t={t:g}, bw={bw:g}, h={h:g})"
    return TPredim(sec, h, t, bw, B_calc, B, redondeo_h)


def obtener_cargas(usar_json: bool, ruta: str, manual: dict) -> tuple[dict, str]:
    """
    Cargas para `Datos`: de `ruta` (cargas.json generado por Cargas.ipynb) si usar_json es True
    y el archivo existe; si no, los valores de `manual` (claves L, q_losa, q_acera, q_parantes,
    q_asfalto, q_L). Devuelve (cargas, texto que explica el origen).
    """
    import json
    import os
    claves = ("L", "q_losa", "q_acera", "q_parantes", "q_asfalto", "q_L")
    if usar_json:
        if os.path.exists(ruta):
            with open(ruta, encoding="utf-8") as f:
                js = json.load(f)
            faltan = [k for k in claves if k not in js]
            if faltan:
                raise ValueError(f"El archivo {ruta} no tiene: {', '.join(faltan)}. Vuelva a ejecutar Cargas.ipynb.")
            fecha = js.get("fecha", "")
            return ({k: float(js[k]) for k in claves},
                    f"Cargas leídas de **{ruta}** (generado por `Cargas.ipynb`{', ' + fecha if fecha else ''}).")
        origen = (f"⚠ No se encontró **{ruta}**: ejecute primero `Cargas.ipynb`. "
                  "Se usan los **valores manuales**.")
    else:
        origen = "Cargas ingresadas **manualmente** (`usar_json = False`)."
    return {k: float(manual[k]) for k in claves}, origen


# ---------------------------------------------------------------------------
# 4. DISEÑO DEFINITIVO (centro de la luz)
# ---------------------------------------------------------------------------

@dataclass
class Resultado:
    datos: Datos
    prop: Propiedades
    x: float = 0.0           # sección de diseño (centro de la luz) [m]
    qG: float = 0.0
    qD: float = 0.0
    qT: float = 0.0
    MG: float = 0.0
    MT: float = 0.0
    alpha: float = 0.0
    emax: float = 0.0
    e_no_restr: float = 0.0
    restringida: bool = False
    F: float = 0.0
    F0: float = 0.0
    e: float = 0.0
    esfuerzos: dict = field(default_factory=dict)
    limites: dict = field(default_factory=dict)
    verificacion: dict = field(default_factory=dict)
    Q: float = 0.0
    Q_r2: float = 0.0
    Q_estado: str = ""

    @property
    def cumple(self) -> bool:
        return all(self.verificacion.values())

    # --- funciones a lo largo de la viga (x en m desde el apoyo izquierdo) ---
    def MG_x(self, x):
        return momento(self.qG, self.datos.L, np.asarray(x, dtype=float))

    def MT_x(self, x):
        return momento(self.qT, self.datos.L, np.asarray(x, dtype=float))

    def forma(self, x):
        """f(x) = 4x(L−x)/L²  (1 en el centro de la luz, 0 en los apoyos)."""
        L = self.datos.L
        x = np.asarray(x, dtype=float)
        return 4 * x * (L - x) / L ** 2

    def e_cable(self, x):
        """Excentricidad del cable resultante parabólico (0 en apoyos, e en L/2) [cm]."""
        return self.e * self.forma(x)

    def e_lim_inicial(self, x):
        """Curva límite etapa inicial: e ≤ k2 + M_G(x)/F0  (f1 = 0) [cm]."""
        return self.prop.k2 + self.MG_x(x) * 100 / self.F0

    def e_lim_final(self, x):
        """Curva límite etapa final: e ≥ M_T(x)/F − k1  (f2 = 0) [cm]."""
        return self.MT_x(x) * 100 / self.F - self.prop.k1

    @property
    def k_parabola(self):
        """k de la parábola y = k·X² del cable resultante (X desde el centro, en m) [1/m]."""
        return (self.e / 100) / (self.datos.L / 2) ** 2

    @property
    def angulo_salida(self):
        """Ángulo de salida en el apoyo α = k·L [rad]."""
        return self.k_parabola * self.datos.L


TOL = 1e-6  # tolerancia numérica [kg/cm², cm]


def _limpiar(x):
    return 0.0 if abs(x) < TOL else x


def esfuerzos_seccion(p: Propiedades, F0, F, e, MG_kgcm, MT_kgcm):
    """Esfuerzos (compresión −) en fibras 1 (sup.) y 2 (inf.) para etapas inicial y final."""
    fi1 = _limpiar(-F0 / p.A + F0 * e / p.S1 - MG_kgcm / p.S1)
    fi2 = _limpiar(-F0 / p.A - F0 * e / p.S2 + MG_kgcm / p.S2)
    ff1 = _limpiar(-F / p.A + F * e / p.S1 - MT_kgcm / p.S1)
    ff2 = _limpiar(-F / p.A - F * e / p.S2 + MT_kgcm / p.S2)
    return {"inicial": (fi1, fi2), "final": (ff1, ff2)}


def verificar(esf: dict, limites: dict) -> dict:
    v = {}
    for etapa in ("inicial", "final"):
        lim = limites[etapa]
        for fibra, f in zip(("1", "2"), esf[etapa]):
            v[(etapa, fibra)] = lim["comp"] - TOL <= f <= lim["trac"] + TOL
    return v


def disenar(seccion: Seccion, d: Datos) -> Resultado:
    """Diseño definitivo (F0, F, e) en el centro de la luz y verificación de esfuerzos."""
    p = seccion.propiedades()
    r = Resultado(datos=d, prop=p, x=d.L / 2)

    # --- Cargas y momentos ----------------------------------------------------
    r.qG = p.A * 1e-4 * d.gamma_c                     # kg/m
    r.qD = d.qD
    r.qT = r.qD + r.qG + d.q_L
    r.MG = momento(r.qG, d.L, r.x)                    # kg-m  (= qG L²/8)
    r.MT = momento(r.qT, d.L, r.x)
    MG = r.MG * 100                                   # kg-cm
    MT = r.MT * 100

    # --- Presfuerzo ---------------------------------------------------------
    r.alpha = round(100 / (100 - d.perdidas), 3)
    r.emax = p.c2 - d.d2
    a = r.alpha

    F = (a * MT - MG) / (a * (p.k1 + p.k2))
    F0 = a * F
    e = MG / F0 + p.k2
    r.e_no_restr = e
    if e <= r.emax:
        r.restringida = False
    else:
        r.restringida = True
        F = MT / (r.emax + p.k1)
        F0 = a * F
        e = r.emax
    r.F, r.F0, r.e = F, F0, e

    # --- Esfuerzos y admisibles (tracción = 0) ------------------------------
    r.esfuerzos = esfuerzos_seccion(p, F0, F, e, MG, MT)
    fci = d.fci_factor * d.fc
    r.limites = {
        "inicial": {"fci": fci, "comp": -0.60 * fci, "trac": 0.0},
        "final": {"fc": d.fc, "comp": -0.45 * d.fc, "trac": 0.0},
    }
    r.verificacion = verificar(r.esfuerzos, r.limites)

    # --- Eficiencia ---------------------------------------------------------
    r.Q = (p.k1 + p.k2) / p.h
    r.Q_r2 = p.r2 / (p.c1 * p.c2)
    if r.Q < 0.45:
        r.Q_estado = "SECCIÓN PESADA (Q < 0.45)"
    elif r.Q > 0.55:
        r.Q_estado = "SECCIÓN DEMASIADO ESBELTA (Q > 0.55)"
    else:
        r.Q_estado = "DISEÑO EFICIENTE (0.45 ≤ Q ≤ 0.55, óptimo Q = 0.50)"
    return r


# ---------------------------------------------------------------------------
# 5. CABLE RESULTANTE Y CURVAS LÍMITE
# ---------------------------------------------------------------------------

@dataclass
class CurvasLimite:
    caso: str                     # 'tangentes' | 'holgura' | 'se cortan'
    holgura_centro: float         # e_ini − e_fin en L/2 [cm]
    xA: float | None
    xB: float | None
    cable_entre_curvas: bool
    x_falla: list                 # abscisas donde el cable sale de la zona
    descripcion: str


def curvas_limite(res: Resultado, n: int = 401) -> CurvasLimite:
    p, L = res.prop, res.datos.L
    xs = np.linspace(0, L, n)
    ei, ef, ec = res.e_lim_inicial(xs), res.e_lim_final(xs), res.e_cable(xs)
    hol = float(res.e_lim_inicial(L / 2) - res.e_lim_final(L / 2))
    xA = xB = None
    if abs(hol) <= 1e-6:
        caso = "tangentes"
        desc = ("Las curvas límite son tangentes en el centro de la luz: el cable resultante debe pasar "
                "obligatoriamente por el punto de tangencia (e = {:.2f} cm).".format(res.e))
    elif hol > 0:
        caso = "holgura"
        desc = ("Las curvas límite no se cortan: existe una zona admisible para el cable en toda la luz "
                "(holgura en L/2 = {:.2f} cm).".format(hol))
    else:
        caso = "se cortan"
        # Δ(x) = (k1 + k2) − f(x)·(M_T/F − M_G/F0)·100  ->  Δ = 0
        fstar = (p.k1 + p.k2) / ((res.MT / res.F - res.MG / res.F0) * 100)
        raiz = math.sqrt(max(0.0, 1 - fstar))
        xA, xB = L / 2 * (1 - raiz), L / 2 * (1 + raiz)
        desc = ("Las curvas límite se cortan en A (x = {:.2f} m) y B (x = {:.2f} m). Entre A y B no existe "
                "posición del cable sin tracciones: (I) seguir la curva inicial → tracciones en etapa final, "
                "requiere armadura no presforzada; (II) ubicarlo entre las curvas → tracciones en ambas etapas; "
                "(III) seguir la curva final → tracciones en etapa inicial. "
                "Se recomienda cambiar la sección aumentando su altura.").format(xA, xB)
    fuera = (ec < ef - 1e-6) | (ec > ei + 1e-6)
    return CurvasLimite(caso, hol, xA, xB, not fuera.any(), [float(x) for x in xs[fuera]], desc)


# ---------------------------------------------------------------------------
# 6. TORONES (modo manual)
# ---------------------------------------------------------------------------

@dataclass
class Toron:
    """Posición de un torón (cm; y medido desde la fibra inferior)."""
    x_centro: float
    y_centro: float
    x_apoyo: float
    y_apoyo: float


def toron(x_centro, y_centro, x_apoyo=None, y_apoyo=None) -> Toron:
    """Atajo: si no se da x_apoyo, el torón no se desvía en planta."""
    return Toron(float(x_centro), float(y_centro),
                 float(x_centro if x_apoyo is None else x_apoyo), float(y_apoyo))


@dataclass
class ResultadoTorones:
    n: int
    y_res_centro: float           # ordenada media de los torones en L/2 [cm]
    y_res_apoyo: float
    e_res_centro: float           # excentricidad de la resultante en L/2 [cm]
    e_res_apoyo: float
    dif_centro: float             # e_res_centro − e (diseño)
    dif_apoyo: float              # e_res_apoyo − 0
    tolerancia: float
    detalle: list                 # por torón: dict(i, e_c, e_a, k, alpha_deg, dentro)

    @property
    def resultante_ok(self) -> bool:
        return abs(self.dif_centro) <= self.tolerancia and abs(self.dif_apoyo) <= self.tolerancia

    @property
    def dentro_ok(self) -> bool:
        return all(t["dentro"] for t in self.detalle)

    @property
    def cumple(self) -> bool:
        return self.resultante_ok and self.dentro_ok


def verificar_torones(seccion: Seccion, res: Resultado, torones: list[Toron],
                      tolerancia: float = 0.5, n_muestras: int = 41) -> ResultadoTorones:
    """
    Todos los torones llevan la misma fuerza (F/n), por lo que la resultante está en el
    promedio de sus posiciones. Cada torón sigue la parábola y = y_c + k·X² (vértice en L/2).
    """
    if not torones:
        raise ValueError("Defina al menos un torón.")
    p, L = res.prop, res.datos.L
    n = len(torones)
    yc_med = sum(t.y_centro for t in torones) / n
    ya_med = sum(t.y_apoyo for t in torones) / n
    e_c, e_a = p.yc - yc_med, p.yc - ya_med
    det = []
    for i, t in enumerate(torones, start=1):
        k = (t.y_apoyo - t.y_centro) / 100 / (L / 2) ** 2          # 1/m
        dentro = True
        for s in np.linspace(0, 1, n_muestras):                     # s = (X/(L/2))²
            x = t.x_centro + (t.x_apoyo - t.x_centro) * s
            y = t.y_centro + (t.y_apoyo - t.y_centro) * s
            if not seccion.contiene(x, y):
                dentro = False
                break
        det.append(dict(i=i, t=t, e_c=p.yc - t.y_centro, e_a=p.yc - t.y_apoyo, k=k,
                        alpha_deg=math.degrees(k * L), alpha_rad=k * L, dentro=dentro))
    return ResultadoTorones(n, yc_med, ya_med, e_c, e_a, e_c - res.e, e_a, tolerancia, det)


# ---------------------------------------------------------------------------
# 7. GRÁFICOS
# ---------------------------------------------------------------------------

COLOR_COTA = "#1f3b73"


def _dibujar_cotas(ax, cotas: list[Cota], S: float):
    """Dibuja las cotas y devuelve los límites ocupados (xmin, xmax, ymin, ymax)."""
    gap, sobre = 0.012 * S, 0.02 * S          # separación al objeto y prolongación
    ancho_car = 0.021 * S                      # ancho aproximado de un carácter (para límites)
    xs, ys = [], []
    kw_lin = dict(color=COLOR_COTA, lw=0.7, zorder=6)
    kw_txt = dict(color=COLOR_COTA, fontsize=8, zorder=6)
    for c in cotas:
        (x1, y1), (x2, y2) = c.p1, c.p2
        if c.tipo == "h":
            yd = (max(y1, y2) if c.offset >= 0 else min(y1, y2)) + c.offset
            s = 1 if c.offset >= 0 else -1
            if c.offset != 0:
                for x, y in ((x1, y1), (x2, y2)):
                    ax.plot([x, x], [y + s * gap, yd + s * sobre], **kw_lin)
            ax.annotate("", (x1, yd), (x2, yd), zorder=6,
                        arrowprops=dict(arrowstyle="<|-|>", color=COLOR_COTA, lw=0.8,
                                        mutation_scale=7, shrinkA=0, shrinkB=0))
            largo = len(c.texto) * ancho_car
            if abs(x2 - x1) >= 1.1 * largo:     # texto centrado sobre la línea
                ax.text((x1 + x2) / 2, yd + s * 0.008 * S, c.texto, ha="center",
                        va="bottom" if s > 0 else "top", **kw_txt)
                xs += [x1, x2]
            else:                               # cota corta: texto al costado
                xt = max(x1, x2) + 0.015 * S
                ax.text(xt, yd, c.texto, ha="left", va="center", **kw_txt)
                xs += [x1, x2, xt + largo]
            ys += [yd + s * (sobre + 0.03 * S), y1, y2]
        else:
            xd = (max(x1, x2) if c.offset >= 0 else min(x1, x2)) + c.offset
            s = 1 if c.offset >= 0 else -1
            if c.offset != 0:
                for x, y in ((x1, y1), (x2, y2)):
                    ax.plot([x + s * gap, xd + s * sobre], [y, y], **kw_lin)
            ax.annotate("", (xd, y1), (xd, y2), zorder=6,
                        arrowprops=dict(arrowstyle="<|-|>", color=COLOR_COTA, lw=0.8,
                                        mutation_scale=7, shrinkA=0, shrinkB=0))
            largo = len(c.texto) * ancho_car
            ym = (y1 + y2) / 2
            if abs(y2 - y1) >= 1.1 * largo:     # texto vertical a lo largo de la cota
                ax.text(xd + s * 0.01 * S, ym, c.texto, rotation=90, ha="left" if s > 0 else "right",
                        va="center", **kw_txt)
                xs += [xd + s * (sobre + 0.04 * S)]
            else:                               # cota corta: texto horizontal al costado
                xt = xd + (0.015 * S if s > 0 or c.offset == 0 else -0.015 * S)
                ha = "left" if (s > 0 or c.offset == 0) else "right"
                ax.text(xt, ym, c.texto, ha=ha, va="center", **kw_txt)
                xs += [xt + (largo if ha == "left" else -largo)]
            xs += [x1, x2, xd]
            ys += [y1, y2]
    if not xs:
        return 0, 0, 0, 0
    return min(xs), max(xs), min(ys), max(ys)


def dibujar_seccion(seccion: Seccion, res: Resultado | None = None, ax=None,
                    torones: list[Toron] | None = None, posicion: str = "centro",
                    titulo: str | None = None):
    """
    Dibuja la sección. Si se pasa el resultado, muestra c.g., núcleo y cable resultante.
    Con `torones`, dibuja su posición en el centro de la luz o en el apoyo (`posicion`).
    """
    p = seccion.propiedades()
    if ax is None:
        _, ax = plt.subplots(figsize=(7, 7))
    for pol in seccion.poligonos:
        ax.add_patch(MplPolygon(pol.puntos, closed=True,
                                facecolor="white" if pol.hueco else "#c9d6e3",
                                edgecolor="black", lw=1.2, zorder=3 if pol.hueco else 2))
    xs = [x for pol in seccion.poligonos for x, _ in pol.puntos]
    xmin, xmax = min(xs), max(xs)
    ancho = xmax - xmin
    S = max(ancho, p.h)
    pad = 0.25 * S

    # --- cotas de las variables de la sección ---------------------------------
    cotas = seccion.cotas or [
        Cota((xmin, seccion.y_min), (xmax, seccion.y_min), "h", -0.07 * S, f"b = {ancho:g}"),
        Cota((xmin, seccion.y_min), (xmin, seccion.y_max), "v", -0.07 * S, f"h = {p.h:g}")]
    cx0, cx1, cy0, cy1 = _dibujar_cotas(ax, cotas, S)
    x_txt = max(xmax, cx1) + 0.02 * S          # etiquetas a la derecha, fuera de las cotas

    ax.axhline(p.yc, color="tab:red", ls="--", lw=1, zorder=4,
               label=f"c.g.: c₁={p.c1:.2f}, c₂={p.c2:.2f} cm")
    ax.text(x_txt, p.yc, " c.g.", color="tab:red", va="bottom", fontsize=9)
    ax.plot([0, 0], [p.yc - p.k2, p.yc + p.k1], color="tab:purple", lw=3, zorder=5,
            label=f"núcleo: k₁={p.k1:.2f}, k₂={p.k2:.2f} cm")
    if res is not None:
        e_pos = res.e if posicion == "centro" else 0.0
        ax.plot(0, p.yc - e_pos, "X", ms=11, color="tab:orange", zorder=7, mec="black",
                label=f"cable resultante: e={e_pos:.2f} cm")
        if posicion == "centro":
            ax.axhline(p.yc - res.emax, color="tab:orange", ls=":", lw=1, zorder=4,
                       label=f"e_max = {res.emax:.2f} cm")
            ax.text(x_txt, p.yc - res.emax, " e_max", color="tab:orange", va="bottom", fontsize=9)
    if torones:
        for i, t in enumerate(torones, start=1):
            x, y = (t.x_centro, t.y_centro) if posicion == "centro" else (t.x_apoyo, t.y_apoyo)
            dentro = seccion.contiene(x, y)
            ax.plot(x, y, "o", ms=7, color="black" if dentro else "red", zorder=8)
            ax.annotate(str(i), (x, y), textcoords="offset points", xytext=(5, 3), fontsize=8,
                        color="black" if dentro else "red", zorder=9)
    ax.set_xlim(min(xmin, cx0) - 0.08 * S, x_txt + 0.16 * S)
    ax.set_ylim(min(seccion.y_min, cy0) - 0.06 * S, max(seccion.y_max, cy1) + 0.06 * S)
    ax.set_aspect("equal")
    ax.set_xlabel("x [cm]  (cotas en cm)")
    ax.set_ylabel("y [cm]")
    ax.set_title(seccion.nombre if titulo is None else titulo)
    ax.grid(alpha=0.3)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.1), fontsize=8, ncol=2)
    return ax


def dibujar_esfuerzos(res: Resultado, esfuerzos: dict | None = None,
                      verificacion: dict | None = None, titulo: str = ""):
    """Diagramas de esfuerzos inicial y final con límites admisibles (por defecto, en L/2)."""
    p = res.prop
    esfuerzos = res.esfuerzos if esfuerzos is None else esfuerzos
    verificacion = res.verificacion if verificacion is None else verificacion
    fig, axs = plt.subplots(1, 2, figsize=(11, 5), sharey=True)
    for ax, etapa, tit in zip(axs, ("inicial", "final"),
                              ("Etapa inicial (F₀ + M_G)", "Etapa final (F + M_T)")):
        f1, f2 = esfuerzos[etapa]
        lim = res.limites[etapa]
        ytop, ybot = p.c1, -p.c2
        ax.fill_betweenx([ybot, ytop], 0, [f2, f1], alpha=0.35, color="tab:blue")
        ax.plot([f2, f1], [ybot, ytop], color="tab:blue", lw=2)
        ax.axvline(0, color="tab:green", lw=1.5, label="tracción adm = 0")
        ax.axvline(lim["comp"], color="tab:red", ls="--", lw=1, label=f"comp. adm = {lim['comp']:.1f}")
        ax.axhline(0, color="gray", ls=":", lw=1)
        for f, y, nom, fibra in ((f1, ytop, "f₁", "1"), (f2, ybot, "f₂", "2")):
            ok = verificacion[(etapa, fibra)]
            ax.annotate(f"{nom} = {f:.2f} {'✓' if ok else '✗'}", (f, y),
                        textcoords="offset points", xytext=(5, 5 if y > 0 else -15),
                        color="black" if ok else "red", fontsize=10, fontweight="bold")
        lo = min(f1, f2, lim["comp"], 0)
        hi = max(f1, f2, 0)
        margen = 0.25 * (hi - lo)
        ax.set_xlim(lo - margen, hi + margen)
        ax.set_ylim(ybot - 0.1 * p.h, ytop + 0.1 * p.h)
        ax.set_title(tit)
        ax.set_xlabel("esfuerzo [kg/cm²]   (compresión −)")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8, loc="center left")
    axs[0].set_ylabel("distancia al c.g. [cm]")
    if titulo:
        fig.suptitle(titulo)
    fig.tight_layout()
    return fig


def dibujar_curvas_limite(res: Resultado, x_marca: float | None = None,
                          torones: list[Toron] | None = None, ax=None, n: int = 401):
    """
    Elevación de la viga: núcleo central, curvas límite inicial y final, cable resultante
    parabólico y (opcional) cada torón. Ordenadas = distancia al c.g. [cm] (positivo hacia arriba).
    """
    p, L = res.prop, res.datos.L
    xs = np.linspace(0, L, n)
    ei, ef, ec = res.e_lim_inicial(xs), res.e_lim_final(xs), res.e_cable(xs)
    cl = curvas_limite(res, n)
    if ax is None:
        fig, ax = plt.subplots(figsize=(12, 6))
    else:
        fig = ax.figure
    ax.axhspan(-p.c2, p.c1, color="#eef2f6", zorder=0)
    ax.axhline(p.c1, color="black", lw=1.2)
    ax.axhline(-p.c2, color="black", lw=1.2)
    ax.axhline(0, color="tab:red", ls="--", lw=1, label="c.g.")
    ax.axhline(p.k1, color="tab:purple", ls="-.", lw=1, label=f"recta k₁ = {p.k1:.2f} cm")
    ax.axhline(-p.k2, color="tab:purple", ls="-.", lw=1, label=f"recta k₂ = {p.k2:.2f} cm")
    ax.axhline(-res.emax, color="tab:orange", ls=":", lw=1, label=f"e_max = {res.emax:.2f} cm")
    ax.fill_between(xs, -ef, -ei, where=ei >= ef, color="tab:green", alpha=0.18,
                    label="zona sin tracciones")
    ax.plot(xs, -ei, color="tab:blue", lw=2, label="curva límite inicial: k₂ + M_G/F₀")
    ax.plot(xs, -ef, color="tab:red", lw=2, label="curva límite final: M_T/F − k₁")
    if torones:
        for i, t in enumerate(torones, start=1):
            yt = t.y_centro + (t.y_apoyo - t.y_centro) * (1 - res.forma(xs))
            ax.plot(xs, yt - p.yc, color="gray", lw=0.8, alpha=0.8,
                    label="torones" if i == 1 else None)
            ax.annotate(str(i), (0, t.y_apoyo - p.yc), textcoords="offset points",
                        xytext=(-12, -3), fontsize=7, color="gray")
    ax.plot(xs, -ec, color="tab:orange", lw=3, label=f"cable resultante (e = {res.e:.2f} cm en L/2)")
    if cl.caso == "se cortan":
        for nom, xp in (("A", cl.xA), ("B", cl.xB)):
            yp = -float(res.e_lim_inicial(xp))
            ax.plot(xp, yp, "ks", ms=7, zorder=9)
            ax.annotate(nom, (xp, yp), textcoords="offset points", xytext=(5, 5), fontweight="bold")
    elif cl.caso == "tangentes":
        ax.plot(L / 2, -res.e, "ko", ms=7, zorder=9)
        ax.annotate("tangencia", (L / 2, -res.e), textcoords="offset points", xytext=(6, -14))
    if x_marca is not None:
        ax.axvline(x_marca, color="black", lw=1.2, ls="--")
        ax.plot(x_marca, -float(res.e_cable(x_marca)), "o", color="black", ms=8, zorder=10)
        ax.annotate(f"x = {x_marca:.2f} m", (x_marca, p.c1), textcoords="offset points",
                    xytext=(4, -14), fontsize=9)
    ax.set_xlim(0, L)
    ax.set_ylim(-p.c2 - 0.12 * p.h, p.c1 + 0.12 * p.h)
    ax.set_xlabel("x [m] (desde el apoyo izquierdo)")
    ax.set_ylabel("distancia al c.g. [cm]  (+ arriba)")
    ax.set_title("Curvas límite y trazado del cable resultante")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=3)
    fig.tight_layout()
    return fig


def dibujar_torones(seccion: Seccion, res: Resultado, torones: list[Toron]):
    """Secciones transversales en el centro de la luz y en el apoyo con los torones numerados."""
    fig, axs = plt.subplots(1, 2, figsize=(13, 7))
    dibujar_seccion(seccion, res, ax=axs[0], torones=torones, posicion="centro",
                    titulo="Torones en el centro de la luz (L/2)")
    dibujar_seccion(seccion, res, ax=axs[1], torones=torones, posicion="apoyo",
                    titulo="Torones en el apoyo (x = 0)")
    fig.tight_layout()
    return fig
