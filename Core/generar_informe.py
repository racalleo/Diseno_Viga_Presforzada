"""
Memoria de cálculo en LaTeX (y PDF con Tectonic, si está instalado) del diseño completo:
predimensionamiento, sección, diseño definitivo en L/2, verificación de esfuerzos, eficiencia,
cable resultante, curvas límite, torones e iteraciones de la sección.

Uso desde el cuaderno:
    from generar_informe import generar_informe
    generar_informe(seccion, datos, torones, carpeta="Informe", iteraciones=reg.iteraciones)

Plantillas: en los bloques LaTeX, <<nombre>> se reemplaza por el valor correspondiente.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import shutil
import subprocess
from pathlib import Path

import matplotlib.pyplot as plt

from presforzado import (Datos, Seccion, Toron, comparar_predim, curvas_limite,
                         dibujar_curvas_limite, dibujar_esfuerzos, dibujar_seccion, dibujar_torones,
                         disenar, predimensionar, verificar_torones)
from iteraciones import seccion_a_dict, seccion_de_dict

FIGURAS_INFORME = ("seccion.pdf", "esfuerzos_L2.pdf", "curvas_limite.pdf", "torones_secciones.pdf",
                   "torones_elevacion.pdf")

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]


def n(x: float, dec: int = 2) -> str:
    """Número con separador de miles (espacio fino) y punto decimal."""
    return f"{x:,.{dec}f}".replace(",", r"\,")


def T(plantilla: str, **valores) -> str:
    """Reemplaza <<clave>> por su valor en la plantilla LaTeX."""
    def rep(m):
        clave = m.group(1)
        if clave not in valores:
            raise KeyError(f"Falta el valor <<{clave}>> en la plantilla.")
        return str(valores[clave])
    return re.sub(r"<<(\w+)>>", rep, plantilla)


def ok_tex(cond: bool, si="Cumple", no="No cumple") -> str:
    return r"\textcolor{verde}{" + si + "}" if cond else r"\textcolor{rojo}{\textbf{" + no + "}}"


PREAMBULO = r"""\documentclass[11pt,a4paper]{article}
\usepackage{fontspec}
\setmainfont{Cambria}
\usepackage[spanish,es-nodecimaldot,es-noshorthands]{babel}
\usepackage[margin=2.3cm]{geometry}
\usepackage{amsmath,amssymb}
\usepackage{booktabs,array,longtable}
\usepackage{graphicx}
\graphicspath{{<<figs>>}}
\usepackage{xcolor}
\usepackage{float}
\usepackage{fancyhdr}
\usepackage[hidelinks]{hyperref}
% Fuentes matemáticas a partir de los tamaños base de 10 pt (escaladas)
\DeclareFontShape{OML}{cmm}{m}{it}{<->cmmi10}{}
\DeclareFontShape{OML}{cmm}{b}{it}{<->cmmi10}{}
\DeclareFontShape{OMS}{cmsy}{m}{n}{<->cmsy10}{}
\DeclareFontShape{OMS}{cmsy}{b}{n}{<->cmsy10}{}
\DeclareFontShape{OT1}{cmr}{m}{n}{<->cmr10}{}
\DeclareFontShape{OT1}{cmr}{bx}{n}{<->cmr10}{}
\definecolor{verde}{RGB}{0,128,60}
\definecolor{rojo}{RGB}{200,30,30}
\setlength{\parindent}{0pt}
\setlength{\parskip}{6pt}
\pagestyle{fancy}\fancyhf{}
\lhead{\small Memoria de cálculo -- Viga presforzada}
\rhead{\small L = <<L>> m}
\cfoot{\thepage}
\title{\textbf{<<titulo>>}\\[4pt]\large Memoria de cálculo -- Puente de luz L = <<L>> m}
\date{<<fecha>>}
\author{}
\begin{document}
\maketitle
\thispagestyle{fancy}
\tableofcontents
\newpage
\textbf{Unidades:} kg, cm (sección), m (luz y abscisas $x$), kg/m (cargas), kg$\cdot$m (momentos), kg/cm$^2$ (esfuerzos).\\
\textbf{Convención de signos:} compresión negativa ($-$), tracción positiva ($+$). Fibra 1 = superior, fibra 2 = inferior.
Excentricidades positivas hacia abajo del centro de gravedad. Las abscisas $x$ se miden desde el apoyo izquierdo.
"""


def figura(archivo: str, ancho: str, leyenda: str) -> str:
    return T(r"""
\begin{figure}[H]
\centering
\includegraphics[width=<<ancho>>]{<<archivo>>}
\caption{<<leyenda>>}
\end{figure}
""", ancho=ancho, archivo=archivo, leyenda=leyenda)


def esfuerzos_tex(p, F0, F, e, MG, MT, esf, etiqueta=""):
    """Bloque con el desarrollo de f1 y f2 inicial/final (MG, MT en kg-cm)."""
    fi1, fi2 = esf["inicial"]
    ff1, ff2 = esf["final"]
    return T(r"""
\textbf{Etapa inicial (F\textsubscript{0} + M\textsubscript{G})<<et>>:}
\begin{align*}
f_1 &= -\frac{F_0}{A} + \frac{F_0\,e}{S_1} - \frac{M_G}{S_1}
= -\frac{<<F0>>}{<<A>>} + \frac{(<<F0>>)(<<e>>)}{<<S1>>} - \frac{<<MG>>}{<<S1>>} = \textbf{<<fi1>>}\ \text{kg/cm}^2\\
f_2 &= -\frac{F_0}{A} - \frac{F_0\,e}{S_2} + \frac{M_G}{S_2}
= -\frac{<<F0>>}{<<A>>} - \frac{(<<F0>>)(<<e>>)}{<<S2>>} + \frac{<<MG>>}{<<S2>>} = \textbf{<<fi2>>}\ \text{kg/cm}^2
\end{align*}
\textbf{Etapa final (F + M\textsubscript{T})<<et>>:}
\begin{align*}
f_1 &= -\frac{F}{A} + \frac{F\,e}{S_1} - \frac{M_T}{S_1}
= -\frac{<<F>>}{<<A>>} + \frac{(<<F>>)(<<e>>)}{<<S1>>} - \frac{<<MT>>}{<<S1>>} = \textbf{<<ff1>>}\ \text{kg/cm}^2\\
f_2 &= -\frac{F}{A} - \frac{F\,e}{S_2} + \frac{M_T}{S_2}
= -\frac{<<F>>}{<<A>>} - \frac{(<<F>>)(<<e>>)}{<<S2>>} + \frac{<<MT>>}{<<S2>>} = \textbf{<<ff2>>}\ \text{kg/cm}^2
\end{align*}
""", et=etiqueta, F0=n(F0), F=n(F), A=n(p.A), e=n(e), S1=n(p.S1), S2=n(p.S2), MG=n(MG, 0),
             MT=n(MT, 0), fi1=n(fi1), fi2=n(fi2), ff1=n(ff1), ff2=n(ff2))


def _tex(txt: str) -> str:
    return txt.replace("_", r"\_").replace("₁", "$_1$").replace("₂", "$_2$").replace("²", "$^2$")


class _P:
    """Propiedades guardadas en el registro (para esfuerzos_tex)."""
    def __init__(self, d):
        self.__dict__.update(d)


def capitulo_iteraciones(its: list[dict], seccion: Seccion, datos: Datos, carpeta: Path, add) -> int | None:
    """Agrega el capítulo de iteraciones; devuelve el número de la iteración adoptada (o None)."""
    from presforzado import dibujar_seccion as _dib

    geo_actual = seccion_a_dict(seccion)["poligonos"]
    adoptada = next((it for it in reversed(its) if it["cumple"]), None)
    n_ad = adoptada["n"] if adoptada else None
    if adoptada and adoptada["seccion"]["poligonos"] != geo_actual:
        aviso = (r"\textcolor{rojo}{\textbf{Atención:}} la sección de los capítulos siguientes no coincide con la "
                 r"última iteración que cumple del registro (guarde la sección actual).")
    else:
        aviso = ""

    # figuras
    for it in its:
        fig, ax = plt.subplots(figsize=(5.2, 5.6))
        _dib(seccion_de_dict(it["seccion"]), ax=ax, titulo="")
        fig.savefig(carpeta / f"iteracion_{it['n']}.pdf", bbox_inches="tight")
        plt.close(fig)

    def celda(it, etapa, j):
        v = it["esfuerzos"][etapa][j]
        ok = it["verificacion"][f"{etapa}_{j + 1}"]
        return n(v) if ok else r"\textcolor{rojo}{\textbf{" + n(v) + "}}"

    filas1 = "\n".join(
        f"{it['n']} & {_tex(it['seccion']['nombre'])} & {n(it['prop']['A'], 0)} & {n(it['qG'], 1)} & "
        f"{it['Q']:.3f} & {ok_tex(it['cumple'], 'Adoptada' if it is adoptada else 'Cumple')} \\\\" for it in its)
    filas2 = "\n".join(
        f"{it['n']} & {'R' if it['restringida'] else 'NR'} & {n(it['F0'], 0)} & {n(it['F'], 0)} & {n(it['e'])} & "
        f"{celda(it, 'inicial', 0)} & {celda(it, 'inicial', 1)} & {celda(it, 'final', 0)} & {celda(it, 'final', 1)} \\\\"
        for it in its)
    li, lf = its[-1]["limites"]["inicial"], its[-1]["limites"]["final"]
    add(T(r"""
\section{Iteraciones de la sección transversal}
Se partió de la sección T obtenida del predimensionamiento y se modificó la sección hasta cumplir los esfuerzos
admisibles de $f_1$ y $f_2$ en las etapas inicial y final. En cada iteración se recalcularon con el peso propio real
($q_G = A\,\gamma_c$) los momentos, el presfuerzo $F_0$, $F$, la excentricidad $e$, los esfuerzos y la eficiencia $Q$.
Se registraron <<nit>> iteraciones. <<aviso>>

\begin{center}\small
\begin{tabular}{clrrcl}
\toprule
N.\textsuperscript{o} & Sección [cm] & $A$ [cm$^2$] & $q_G$ [kg/m] & $Q$ & Estado \\
\midrule
<<filas1>>
\bottomrule
\end{tabular}
\end{center}

\begin{center}\small\setlength{\tabcolsep}{4.5pt}
\begin{tabular}{ccrrrrrrr}
\toprule
& & & & & \multicolumn{2}{c}{Inicial [kg/cm$^2$]} & \multicolumn{2}{c}{Final [kg/cm$^2$]} \\
\cmidrule(lr){6-7}\cmidrule(lr){8-9}
N.\textsuperscript{o} & Exc. & $F_0$ [kg] & $F$ [kg] & $e$ [cm] & $f_1$ & $f_2$ & $f_1$ & $f_2$ \\
\midrule
<<filas2>>
\bottomrule
\end{tabular}
\end{center}
Exc.: NR = excentricidad no restringida, R = restringida. Admisibles: inicial $<<ci>> \le f \le 0$, final
$<<cf>> \le f \le 0$ kg/cm$^2$. Los valores en \textcolor{rojo}{\textbf{rojo}} no cumplen.
""", nit=len(its), aviso=aviso, filas1=filas1, filas2=filas2, ci=n(li["comp"]), cf=n(lf["comp"])))

    for it in its:
        pr = _P(it["prop"])
        MG, MT = it["MG"] * 100, it["MT"] * 100
        if it["restringida"]:
            caso = T(r"""Como $e = <<enr>>$ cm $> e_{max} = <<emax>>$ cm, la excentricidad es \textbf{restringida}:
$F = \dfrac{M_T}{e_{max} + k_1} = <<F>>$ kg, $F_0 = \alpha F = <<F0>>$ kg, $e = e_{max} = <<e>>$ cm.""",
                     enr=n(it["e_no_restr"]), emax=n(it["emax"]), F=n(it["F"]), F0=n(it["F0"]), e=n(it["e"]))
        else:
            caso = T(r"""Como $e = <<e>>$ cm $\le e_{max} = <<emax>>$ cm, la excentricidad es \textbf{no restringida}:
$F = <<F>>$ kg, $F_0 = <<F0>>$ kg.""", e=n(it["e"]), emax=n(it["emax"]), F=n(it["F"]), F0=n(it["F0"]))
        if it["cumple"]:
            conclusion = (r"\textcolor{verde}{\textbf{Cumple}} con los esfuerzos admisibles"
                          + (r" $\Rightarrow$ \textbf{sección adoptada}." if it is adoptada else "."))
        else:
            conclusion = (r"\textcolor{rojo}{\textbf{No cumple}}:\begin{itemize}" +
                          "".join(r"\item " + _tex(m).replace("<", "$<$").replace(">", "$>$")
                                  for m in it["motivos"]) +
                          r"\end{itemize}Se descarta y se modifica la sección.")
        add(T(r"""
\subsection{Iteración <<n>>: <<nombre>>}
\begin{minipage}[c]{0.42\textwidth}
\centering\includegraphics[width=\linewidth]{iteracion_<<n>>.pdf}
\end{minipage}\hfill
\begin{minipage}[c]{0.54\textwidth}\small
\begin{tabular}{lr}
\toprule
$A$ & <<A>> cm$^2$ \\
$c_1$ / $c_2$ & <<c1>> / <<c2>> cm \\
$I$ & <<I>> cm$^4$ \\
$k_1$ / $k_2$ & <<k1>> / <<k2>> cm \\
$q_G = A\,\gamma_c$ & <<qG>> kg/m \\
$M_G$ / $M_T$ & <<MGm>> / <<MTm>> kg$\cdot$m \\
$e_{max} = c_2 - d_2$ & <<emax>> cm \\
$Q = (k_1 + k_2)/h$ & <<Q>> \\
\bottomrule
\end{tabular}
\end{minipage}

<<caso>>
<<esf>>
<<conclusion>> Eficiencia: <<Qest>>.
""", n=it["n"], nombre=_tex(it["seccion"]["nombre"]), A=n(pr.A), c1=n(pr.c1), c2=n(pr.c2), I=n(pr.I, 0),
              k1=n(pr.k1), k2=n(pr.k2), qG=n(it["qG"]), MGm=n(it["MG"]), MTm=n(it["MT"]), emax=n(it["emax"]),
              Q=f"{it['Q']:.3f}", caso=caso,
              esf=esfuerzos_tex(pr, it["F0"], it["F"], it["e"], MG, MT,
                                {k: tuple(v) for k, v in it["esfuerzos"].items()}),
              conclusion=conclusion, Qest=_tex(it["Q_estado"]).replace("<", "$<$").replace(">", "$>$")
              .replace("≤", r"$\le$")))
    return n_ad


def generar_informe(seccion: Seccion, datos: Datos, torones: list[Toron] | None = None,
                    partes=None, carpeta="Informe",
                    titulo="Diseño de viga de hormigón presforzado", tolerancia: float = 0.5,
                    compilar=True, iteraciones: list[dict] | None = None,
                    carpeta_figuras="Figuras") -> Path:
    carpeta = Path(carpeta)
    carpeta.mkdir(exist_ok=True)
    figdir = Path(carpeta_figuras)                # todas las figuras en la carpeta de trabajo/Figuras
    figdir.mkdir(exist_ok=True)
    for viejo in [*figdir.glob("iteracion_*.pdf"), *(figdir / f for f in FIGURAS_INFORME)]:
        if viejo.exists():                        # borra solo las figuras del informe de la vez anterior
            viejo.unlink()
    ruta_figs = os.path.relpath(figdir.resolve(), carpeta.resolve()).replace("\\", "/") + "/"
    if partes is None:
        partes = getattr(seccion, "partes", None)
    d = datos
    pre = predimensionar(d)
    comp = comparar_predim(pre, seccion)
    r = disenar(seccion, d)
    p = r.prop
    cl = curvas_limite(r)
    rt = verificar_torones(seccion, r, torones, tolerancia) if torones else None
    L = d.L
    MG, MT = r.MG * 100, r.MT * 100
    li, lf = r.limites["inicial"], r.limites["final"]

    # ------------------------------------------------------------------ figuras
    def guardar(fig, nombre):
        fig.savefig(figdir / nombre, bbox_inches="tight")
        plt.close(fig)

    fig, ax = plt.subplots(figsize=(6.5, 7))
    dibujar_seccion(seccion, r, ax=ax, titulo="")
    guardar(fig, "seccion.pdf")
    guardar(dibujar_esfuerzos(r), "esfuerzos_L2.pdf")
    guardar(dibujar_curvas_limite(r), "curvas_limite.pdf")
    if rt is not None:
        guardar(dibujar_torones(seccion, r, torones), "torones_secciones.pdf")
        guardar(dibujar_curvas_limite(r, torones=torones), "torones_elevacion.pdf")

    hoy = dt.date.today()
    partes_doc = [T(PREAMBULO, L=n(L, 1), titulo=titulo, figs=ruta_figs,
                    fecha=f"{hoy.day} de {MESES[hoy.month - 1]} de {hoy.year}")]
    add = partes_doc.append

    # ------------------------------------------------------------- 1. datos
    add(T(r"""
\section{Datos de diseño}
\begin{center}
\begin{tabular}{llr}
\toprule
Parámetro & Símbolo & Valor \\
\midrule
Luz de cálculo (simplemente apoyada) & $L$ & <<L>> m \\
Resistencia del hormigón & $f'_c$ & <<fc>> kg/cm$^2$ \\
Resistencia en la transferencia ($f'_{ci} = <<fcif>>\,f'_c$) & $f'_{ci}$ & <<fci>> kg/cm$^2$ \\
Peso específico del hormigón & $\gamma_c$ & <<gc>> kg/m$^3$ \\
Pérdidas de presfuerzo & -- & <<perd>> \% \\
Fibra inferior al cable resultante (en $L/2$) & $d_2$ & <<d2>> cm \\
\midrule
Losa & $q_{losa}$ & <<ql>> kg/m \\
Acera & $q_{acera}$ & <<qa>> kg/m \\
Postes y pasamanos & $q_{parantes}$ & <<qp>> kg/m \\
Carpeta asfáltica & $q_{asfalto}$ & <<qas>> kg/m \\
Carga viva & $q_L$ & <<qL>> kg/m \\
\midrule
Peso propio asumido (predimensionamiento) & $q_{G,asum}$ & <<qGa>> kg/m \\
Coeficiente $h = L/k$ & $k_L$ & <<kL>> \\
Coeficiente $h = k\sqrt{M}$ & $k_M$ & <<kM>> \\
\bottomrule
\end{tabular}
\end{center}
""", L=n(L), fc=n(d.fc), fcif=f"{d.fci_factor:.2f}", fci=n(li["fci"]), gc=n(d.gamma_c, 0),
          perd=n(d.perdidas, 1), d2=n(d.d2), ql=n(d.q_losa), qa=n(d.q_acera), qp=n(d.q_parantes),
          qas=n(d.q_asfalto), qL=n(d.q_L), qGa=n(d.qG_asumido), kL=f"{d.k_L:g}", kM=f"{d.k_M:g}"))

    # ------------------------------------------------- 2. predimensionamiento
    filas_h = []
    for nom, _, h in pre.criterios:
        if nom == "h = L/k":
            fx = T(r"$h = \dfrac{L}{k} = \dfrac{<<L>>\ \text{cm}}{<<k>>}$", L=n(L * 100, 0), k=f"{d.k_L:g}")
        elif nom.startswith("h = L/25"):
            fx = T(r"$h = \dfrac{L}{25} + 10 = \dfrac{<<L>>}{25} + 10$", L=n(L * 100, 0))
        elif nom.startswith("h = k"):
            fx = T(r"$h = k\sqrt{M_T} = <<k>>\sqrt{<<M>>}$", k=f"{d.k_M:g}", M=n(pre.MT))
        else:
            fx = T(r"$h = 0.07\,L = 0.07\,(<<L>>)$", L=n(L * 100, 0))
        filas_h.append(f"{fx} & {n(h)} cm \\\\")
    if pre.relacion < 0.20:
        caso_tex = r"Como $M_G/M_T < 0.20$, se usa $A_c = 4 M_L / (f_c\,h)$."
    elif pre.relacion > 0.30:
        caso_tex = r"Como $M_G/M_T > 0.30$, se usa $A_c = 3 M_T / (f_c\,h)$."
    else:
        caso_tex = (r"Como $0.20 \le M_G/M_T \le 0.30$ (entre ambos casos), se adopta el mayor de las dos "
                    r"expresiones.")
    avisos = ""
    if pre.avisos:
        avisos = r"\textbf{Observaciones:}\begin{itemize}" + "".join(
            r"\item " + a.replace("<", r"$<$").replace(">", r"$>$").replace("·", r"$\cdot$")
            .replace("√", r"$\sqrt{}$") for a in pre.avisos) + r"\end{itemize}"
    add(T(r"""
\section{Predimensionamiento de la sección}
Para el predimensionamiento se asume el peso propio $q_{G,asum} = <<qGa>>$ kg/m:
\begin{align*}
q_T &= q_D + q_{G,asum} + q_L = <<qD>> + <<qGa>> + <<qL>> = <<qT>>\ \text{kg/m}\\
M_G &= \frac{q_{G,asum} L^2}{8} = \frac{(<<qGa>>)(<<L>>)^2}{8} = <<MG>>\ \text{kg}\cdot\text{m}\\
M_T &= \frac{q_T L^2}{8} = \frac{(<<qT>>)(<<L>>)^2}{8} = <<MT>>\ \text{kg}\cdot\text{m}
\end{align*}

\subsection{Altura}
\begin{center}
\renewcommand{\arraystretch}{1.9}
\begin{tabular}{lr}
\toprule
Criterio & $h$ \\
\midrule
<<filas>>
\midrule
\textbf{Promedio (altura recomendada)} & \textbf{<<hprom>> cm} \\
\bottomrule
\end{tabular}
\end{center}
<<avisos>>

\subsection{Área de hormigón requerida}
Con $f_c = 0.45\,f'_c = 0.45\,(<<fcc>>) = <<fca>>$ kg/cm$^2$, $h = <<hprom>>$ cm, $M_L = M_T - M_G = <<ML>>$ kg$\cdot$m
y $M_G/M_T = <<rel>>$:
\begin{align*}
A_{c,1} &= \frac{4\,M_L}{f_c\,h} = \frac{4\,(<<ML>>\times10^2)}{(<<fca>>)(<<hprom>>)} = <<Ac1>>\ \text{cm}^2 \\
A_{c,2} &= \frac{3\,M_T}{f_c\,h} = \frac{3\,(<<MT>>\times10^2)}{(<<fca>>)(<<hprom>>)} = <<Ac2>>\ \text{cm}^2
\end{align*}
<<caso>> \quad $\Rightarrow\ A_{c,req} = \textbf{<<Acr>>}$ cm$^2$.

\subsection{Recomendaciones para el dibujo de la sección}
\begin{itemize}
\item Altura: $h \approx <<hprom>>$ cm.
\item Área de hormigón: $A_c \ge <<Acr>>$ cm$^2$.
\item Ancho de alma: $b_w = 16$ a $20$ cm (el menor posible). Donde existan mayores compresiones debe disponerse mayor sección de hormigón.
\end{itemize}
""", qGa=n(d.qG_asumido), qD=n(d.qD), qL=n(d.q_L), qT=n(pre.qT), L=n(L, 1), MG=n(pre.MG), MT=n(pre.MT),
          filas="\n".join(filas_h), hprom=n(pre.h_prom), avisos=avisos, fcc=n(d.fc), fca=n(pre.fc_adm),
          ML=n(pre.ML), rel=f"{pre.relacion:.3f}", Ac1=n(pre.Ac_caso1), Ac2=n(pre.Ac_caso2),
          caso=caso_tex, Acr=n(pre.Ac_req)))

    # ------------------------------------------------- 2b. iteraciones
    n_adoptada = None
    if iteraciones:
        n_adoptada = capitulo_iteraciones(iteraciones, seccion, d, figdir, add)

    # ------------------------------------------------------- 3. sección
    filas_c = []
    for item, rec, adop, est_ in comp:
        bueno = est_.startswith("✓")
        txt = est_.lstrip("✓⚠ ").replace("%", r"\%")
        filas_c.append(f"{item.replace('A_c', '$A_c$').replace('b_w', '$b_w$')} & {rec.replace('≥', '$\\ge$').replace('cm²', 'cm$^2$')} & "
                       f"{adop.replace('cm²', 'cm$^2$')} & {ok_tex(bueno, txt, txt)} \\\\")
    add(T(r"""
\section{Sección transversal adoptada}
Sección: \textbf{<<nombre>>}, de altura total $h = <<h>>$ cm.<<it>>
<<fig>>
\begin{center}
\begin{tabular}{llll}
\toprule
Ítem & Recomendado & Adoptado & Observación \\
\midrule
<<filas>>
\bottomrule
\end{tabular}
\end{center}
""", nombre=seccion.nombre.replace("_", " "), h=n(p.h, 1),
          it=(f" Corresponde a la \\textbf{{iteración {n_adoptada}}} del registro." if n_adoptada else ""),
          fig=figura("seccion.pdf", r"0.6\textwidth",
                     r"Sección transversal: c.g., núcleo central ($k_1$, $k_2$), $e_{max}$ y cable resultante en $L/2$."),
          filas="\n".join(filas_c)))

    # ------------------------------------------------- 4. propiedades
    if partes:
        filas, sA, sAy, sI0, sAd2 = [], 0, 0, 0, 0
        for nom, b, h, yb in partes:
            A = b * h
            y = yb + h / 2
            I0 = b * h ** 3 / 12
            dd = y - p.yc
            filas.append(f"{nom} & {n(b,1)} & {n(h,1)} & {n(A)} & {n(y)} & {n(A*y)} & "
                         f"{n(I0)} & {n(dd)} & {n(A*dd**2)} \\\\")
            sA += A; sAy += A * y; sI0 += I0; sAd2 += A * dd ** 2
        tabla_partes = T(r"""
Las propiedades se obtienen por partes, con $y$ medido desde la fibra inferior:
\begin{center}\footnotesize\setlength{\tabcolsep}{4pt}
\begin{tabular}{lrrrrrrrr}
\toprule
Parte & $b$ [cm] & $h$ [cm] & $A_i$ [cm$^2$] & $y_i$ [cm] & $A_i y_i$ [cm$^3$] & $I_{0,i}$ [cm$^4$] & $d_i$ [cm] & $A_i d_i^2$ [cm$^4$] \\
\midrule
<<filas>>
\midrule
$\Sigma$ & & & <<sA>> & & <<sAy>> & <<sI0>> & & <<sAd2>> \\
\bottomrule
\end{tabular}
\end{center}
\begin{align*}
\bar y &= \frac{\Sigma A_i y_i}{\Sigma A_i} = \frac{<<sAy>>}{<<sA>>} = <<yc>>\ \text{cm} \\
I &= \Sigma I_{0,i} + \Sigma A_i d_i^2 = <<sI0>> + <<sAd2>> = <<I>>\ \text{cm}^4
\end{align*}
""", filas="\n".join(filas), sA=n(sA), sAy=n(sAy), sI0=n(sI0), sAd2=n(sAd2), yc=n(p.yc), I=n(p.I))
    else:
        tabla_partes = (r"Las propiedades se calcularon integrando sobre los polígonos que definen la sección "
                        r"(fórmulas de Green), con $y$ medido desde la fibra inferior.")
    add(T(r"""
\section{Propiedades mecánicas}
<<tabla>>
\begin{align*}
c_1 &= h - \bar y = <<c1>>\ \text{cm} & c_2 &= \bar y = <<c2>>\ \text{cm}\\
S_1 &= \frac{I}{c_1} = <<S1>>\ \text{cm}^3 & S_2 &= \frac{I}{c_2} = <<S2>>\ \text{cm}^3\\
k_1 &= \frac{I}{A\,c_2} = <<k1>>\ \text{cm} & k_2 &= \frac{I}{A\,c_1} = <<k2>>\ \text{cm}\\
r^2 &= \frac{I}{A} = <<r2>>\ \text{cm}^2 & A &= <<A>>\ \text{cm}^2
\end{align*}
""", tabla=tabla_partes, c1=n(p.c1), c2=n(p.c2), S1=n(p.S1), S2=n(p.S2), k1=n(p.k1), k2=n(p.k2),
          r2=n(p.r2), A=n(p.A)))

    # ------------------------------------------------- 5. cargas y momentos
    add(T(r"""
\section{Cargas y momentos en el centro de la luz}
El momento en una sección cualquiera es $M(x) = q\,x\,(L-x)/2$; en $x = L/2$ resulta $M = q L^2/8$.
\begin{align*}
q_G &= A\,\gamma_c = (<<A>>\times10^{-4}\ \text{m}^2)(<<gc>>\ \text{kg/m}^3) = <<qG>>\ \text{kg/m}\\
q_D &= q_{losa} + q_{acera} + q_{parantes} + q_{asfalto} = <<ql>> + <<qa>> + <<qp>> + <<qas>> = <<qD>>\ \text{kg/m}\\
q_T &= q_D + q_G + q_L = <<qD>> + <<qG>> + <<qL>> = <<qT>>\ \text{kg/m}\\
M_G &= \frac{q_G L^2}{8} = \frac{(<<qG>>)(<<L>>)^2}{8} = <<MG>>\ \text{kg}\cdot\text{m}\\
M_T &= \frac{q_T L^2}{8} = \frac{(<<qT>>)(<<L>>)^2}{8} = <<MT>>\ \text{kg}\cdot\text{m}
\qquad \frac{M_G}{M_T} = <<rel>>
\end{align*}
""", A=n(p.A), gc=n(d.gamma_c, 0), qG=n(r.qG), ql=n(d.q_losa), qa=n(d.q_acera), qp=n(d.q_parantes),
          qas=n(d.q_asfalto), qD=n(r.qD), qL=n(d.q_L), qT=n(r.qT), L=n(L, 1), MG=n(r.MG), MT=n(r.MT),
          rel=f"{r.MG / r.MT:.2f}"))

    # ------------------------------------------------- 6. diseño F0, F, e
    a = r.alpha
    F_nr = (a * MT - MG) / (a * (p.k1 + p.k2))
    if r.restringida:
        decision = T(r"""
Como $e = <<enr>>$ cm $> e_{max} = <<emax>>$ cm, la altura no permite ubicar la excentricidad calculada
(\textbf{caso dos: excentricidad restringida}). Se fija $e = e_{max}$ y se impone $f_2 = 0$ en la etapa final:
\begin{align*}
F &= \frac{M_T}{e_{max} + k_1} = \frac{<<MT>>}{<<emax>> + <<k1>>} = \textbf{<<F>>\ kg}\\
F_0 &= \alpha F = <<a>>\,(<<F>>) = \textbf{<<F0>>\ kg}\\
e &= e_{max} = \textbf{<<e>>\ cm}
\end{align*}
""", enr=n(r.e_no_restr), emax=n(r.emax), MT=n(MT, 0), k1=n(p.k1), F=n(r.F), a=f"{a:.3f}",
                     F0=n(r.F0), e=n(r.e))
    else:
        decision = T(r"""
Como $e = <<e>>$ cm $\le e_{max} = <<emax>>$ cm, la altura permite ubicar la excentricidad calculada
(\textbf{caso uno: excentricidad no restringida}) y se adoptan los valores anteriores.
""", e=n(r.e), emax=n(r.emax))
    add(T(r"""
\section{Diseño definitivo: fuerzas de presfuerzo y excentricidad}
Condiciones de diseño en el centro de la luz: $f_1 = 0$ en la etapa inicial ($F_0 + M_G$) y $f_2 = 0$ en la etapa final ($F + M_T$).
\begin{align*}
\alpha &= \frac{100}{100 - \%\text{pérdidas}} = \frac{100}{100 - <<perd>>} = <<a>> &
e_{max} &= c_2 - d_2 = <<c2>> - <<d2>> = <<emax>>\ \text{cm}
\end{align*}
\subsection{Excentricidad no restringida}
\begin{align*}
F &= \frac{\alpha M_T - M_G}{\alpha\,(k_1 + k_2)} = \frac{<<a>>\,(<<MT>>) - <<MG>>}{<<a>>\,(<<k1>> + <<k2>>)} = <<Fnr>>\ \text{kg}\\
F_0 &= \alpha F = <<a>>\,(<<Fnr>>) = <<F0nr>>\ \text{kg}\\
e &= \frac{M_G}{F_0} + k_2 = \frac{<<MG>>}{<<F0nr>>} + <<k2>> = <<enr>>\ \text{cm}
\end{align*}
\subsection{Verificación de la excentricidad}
<<decision>>
\begin{center}
\begin{tabular}{lr}
\toprule
Fuerza de presfuerzo inicial $F_0$ & \textbf{<<F0>> kg} \\
Fuerza de presfuerzo final $F$ & \textbf{<<F>> kg} \\
Excentricidad del cable resultante en $L/2$, $e$ & \textbf{<<e>> cm} \\
Caso & <<tipo>> \\
\bottomrule
\end{tabular}
\end{center}
""", perd=n(d.perdidas, 1), a=f"{a:.3f}", c2=n(p.c2), d2=n(d.d2), emax=n(r.emax), MT=n(MT, 0),
          MG=n(MG, 0), k1=n(p.k1), k2=n(p.k2), Fnr=n(F_nr), F0nr=n(a * F_nr), enr=n(r.e_no_restr),
          decision=decision, F0=n(r.F0), F=n(r.F), e=n(r.e),
          tipo="Restringida" if r.restringida else "No restringida"))

    # ------------------------------------------------- 7-8. análisis y verificación L/2
    def tabla_verif(esf, ver):
        filas = []
        for etapa, lim in (("inicial", li), ("final", lf)):
            for fibra, nombre in (("1", "1 (sup.)"), ("2", "2 (inf.)")):
                f = esf[etapa][int(fibra) - 1]
                filas.append(f"{etapa.capitalize()} & {nombre} & {n(f)} & {n(lim['comp'])} & 0.00 & "
                             f"{ok_tex(ver[(etapa, fibra)])} \\\\")
        return T(r"""
\begin{center}
\begin{tabular}{llrrrl}
\toprule
Etapa & Fibra & $f$ [kg/cm$^2$] & $f_{c,adm}$ & $f_{t,adm}$ & Estado \\
\midrule
<<filas>>
\bottomrule
\end{tabular}
\end{center}
""", filas="\n".join(filas))

    add(r"\section{Análisis de la sección en el centro de la luz}" +
        esfuerzos_tex(p, r.F0, r.F, r.e, MG, MT, r.esfuerzos))
    add(T(r"""
\section{Verificación de esfuerzos admisibles}
\begin{align*}
\text{Inicial:}\quad & f_{c,adm} = -0.60\,f'_{ci} = -0.60\,(<<fci>>) = <<ci>>\ \text{kg/cm}^2 & & f_{t,adm} = 0\\
\text{Final:}\quad & f_{c,adm} = -0.45\,f'_c = -0.45\,(<<fc>>) = <<cf>>\ \text{kg/cm}^2 & & f_{t,adm} = 0
\end{align*}
<<tabla>>
<<estado>>
<<fig>>
""", fci=n(li["fci"]), ci=n(li["comp"]), fc=n(d.fc), cf=n(lf["comp"]),
          tabla=tabla_verif(r.esfuerzos, r.verificacion),
          estado=ok_tex(r.cumple, r"\textbf{En el centro de la luz la sección cumple con todos los esfuerzos admisibles.}",
                        "En el centro de la luz la sección NO cumple: debe rediseñarse (normalmente aumentando la altura)."),
          fig=figura("esfuerzos_L2.pdf", r"\textwidth", r"Distribución de esfuerzos en $L/2$ con los límites admisibles.")))

    # ------------------------------------------------- 9. eficiencia
    if r.Q < 0.45:
        q_txt = r"Sección pesada ($Q < 0.45$)"
    elif r.Q > 0.55:
        q_txt = r"Sección demasiado esbelta ($Q > 0.55$)"
    else:
        q_txt = r"Diseño eficiente ($0.45 \le Q \le 0.55$, óptimo $Q = 0.50$)"
    add(T(r"""
\section{Eficiencia de la sección}
\[
Q = \frac{k_1 + k_2}{h} = \frac{<<k1>> + <<k2>>}{<<h>>} = \textbf{<<Q>>}
\qquad
Q = \frac{r^2}{c_1\,c_2} = \frac{<<r2>>}{(<<c1>>)(<<c2>>)} = <<Q2>>
\]
Criterio: $Q = 0.50$ diseño eficiente; $Q < 0.45$ sección pesada; $Q > 0.55$ sección demasiado esbelta.
Resultado: \textbf{<<txt>>}.
""", k1=n(p.k1), k2=n(p.k2), h=n(p.h), Q=f"{r.Q:.3f}", r2=n(p.r2), c1=n(p.c1), c2=n(p.c2),
          Q2=f"{r.Q_r2:.3f}", txt=q_txt))

    # ------------------------------------------------- 10. cable y curvas límite
    if cl.caso == "tangentes":
        caso_tex = (r"Las curvas límite son \textbf{tangentes} en el centro de la luz: el cable resultante debe "
                    r"pasar obligatoriamente por el punto de tangencia ($e = " + n(r.e) + r"$ cm).")
    elif cl.caso == "holgura":
        caso_tex = (r"Las curvas límite \textbf{no se cortan}: existe una zona admisible a lo largo de toda la luz. "
                    r"Holgura en $L/2$: $e_{ini} - e_{fin} = " + n(cl.holgura_centro) + r"$ cm.")
    else:
        caso_tex = (r"Las curvas límite \textbf{se cortan} en A ($x = " + n(cl.xA) + r"$ m) y B ($x = " + n(cl.xB) +
                    r"$ m). Entre A y B no existe posición del cable sin tracciones: (I) si sigue la curva inicial "
                    r"habrá tracciones en la etapa final (requiere refuerzo no presforzado calculado con el momento "
                    r"entre ambas curvas); (II) entre las curvas habrá tracciones en ambas etapas; (III) si sigue la "
                    r"curva final habrá tracciones en la etapa inicial. \textbf{Se recomienda aumentar la altura de la sección.}")
    add(T(r"""
\section{Diseño del cable resultante}
$F_0$, $F$ y $e$ se calcularon en el centro de la luz por ser la zona crítica en vigas simplemente apoyadas.
El cable resultante es una parábola que pasa por la excentricidad $e$ en el centro de la luz y por el centro
de gravedad de la sección en los apoyos.

\subsection{Trayectoria parabólica}
Con origen en el centro de la luz ($X = x - L/2$) y $y$ medido hacia arriba desde el punto más bajo del cable:
\begin{align*}
y &= k\,X^2, \qquad k = \frac{e}{(L/2)^2} = \frac{<<em>>\ \text{m}}{(<<L2>>\ \text{m})^2} = <<k>>\ \text{m}^{-1}\\
e(x) &= e\,\frac{4\,x\,(L-x)}{L^2} \quad \text{(excentricidad respecto al c.g.)}\\
\alpha &= k\,L = (<<k>>)(<<L>>) = <<arad>>\ \text{rad} = <<adeg>>^\circ \quad \text{(ángulo de salida en el apoyo)}
\end{align*}

\subsection{Curvas límite}
A partir del c.g. se trazan las rectas del núcleo central ($k_1$ hacia arriba y $k_2$ hacia abajo). Con $F_0$ y $F$ constantes:
\begin{align*}
\text{Etapa inicial } (f_1 = 0):\quad & e_{ini}(x) = k_2 + \frac{M_G(x)}{F_0} \qquad \text{(desde la recta de } k_2 \text{ hacia abajo)}\\
\text{Etapa final } (f_2 = 0):\quad & e_{fin}(x) = \frac{M_T(x)}{F} - k_1 \qquad \text{(desde la recta de } k_1 \text{ hacia abajo)}
\end{align*}
Si el cable cumple $e_{fin}(x) \le e(x) \le e_{ini}(x)$, los esfuerzos en las fibras extremas son de compresión en ambas etapas.
En el centro de la luz: $e_{ini} = <<k2>> + \dfrac{<<MG>>}{<<F0>>} = <<eiL2>>$ cm y
$e_{fin} = \dfrac{<<MT>>}{<<F>>} - <<k1>> = <<efL2>>$ cm.

<<caso>>

Verificación del cable a lo largo de toda la luz (401 secciones): <<entre>>
<<fig>>
""", em=n(r.e / 100, 4), L2=n(L / 2, 2), k=f"{r.k_parabola:.6f}", L=n(L, 2), arad=f"{r.angulo_salida:.4f}",
          adeg=f"{r.angulo_salida * 57.29578:.2f}", k2=n(p.k2), k1=n(p.k1), MG=n(MG, 0), MT=n(MT, 0),
          F0=n(r.F0), F=n(r.F), eiL2=n(float(r.e_lim_inicial(L / 2))), efL2=n(float(r.e_lim_final(L / 2))),
          caso=caso_tex,
          entre=ok_tex(cl.cable_entre_curvas, r"\textbf{el cable resultante queda entre las curvas límite en toda la viga.}",
                       r"el cable resultante sale de la zona admisible."),
          fig=figura("curvas_limite.pdf", r"\textwidth", "Curvas límite inicial y final y trazado del cable resultante.")))

    # ------------------------------------------------- torones
    if rt is not None:
        filas_t = []
        for t in rt.detalle:
            tt = t["t"]
            filas_t.append(f"{t['i']} & {n(tt.x_centro,1)} & {n(tt.y_centro)} & {n(t['e_c'])} & {n(tt.x_apoyo,1)} & "
                           f"{n(tt.y_apoyo)} & {n(t['e_a'])} & {t['k']:.6f} & {t['alpha_deg']:.2f} & "
                           f"{ok_tex(t['dentro'], 'Sí', 'No')} \\\\")
        if rt.n <= 8:   # suma desarrollada; con muchos torones solo el total
            sum_c = " + ".join(n(t["t"].y_centro) for t in rt.detalle)
            sum_a = " + ".join(n(t["t"].y_apoyo) for t in rt.detalle)
        else:
            sum_c = n(sum(t["t"].y_centro for t in rt.detalle))
            sum_a = n(sum(t["t"].y_apoyo for t in rt.detalle))
        add(T(r"""
\section{Número y posición de los torones}
Se disponen \textbf{$n = <<n>>$ torones}. Todos llevan la misma fuerza ($F/n$), por lo que la resultante se ubica
en el promedio de sus posiciones y debe coincidir con el cable resultante: en $L/2$ a $y = \bar y - e = <<yobj>>$ cm
y en los apoyos en el c.g., $y = \bar y = <<yc>>$ cm. Cada torón sigue la parábola $y_i = y_{i,c} + k_i X^2$ con
$k_i = (y_{i,a} - y_{i,c})/(L/2)^2$ y ángulo de salida $\alpha_i = k_i L$.

\begin{center}\footnotesize\setlength{\tabcolsep}{3.5pt}
\begin{tabular}{rrrrrrrrrl}
\toprule
 & \multicolumn{3}{c}{Centro de la luz} & \multicolumn{3}{c}{Apoyo} & & & \\
Torón & $x$ [cm] & $y$ [cm] & $e$ [cm] & $x$ [cm] & $y$ [cm] & $e$ [cm] & $k_i$ [m$^{-1}$] & $\alpha_i$ [$^\circ$] & Dentro \\
\midrule
<<filas>>
\bottomrule
\end{tabular}
\end{center}

\textbf{Resultante en el centro de la luz:}
\begin{align*}
\bar y_c &= \frac{\Sigma y_{i,c}}{n} = \frac{<<sumc>>}{<<n>>} = <<ymc>>\ \text{cm}\\
e_{res} &= \bar y - \bar y_c = <<yc>> - <<ymc>> = <<erc>>\ \text{cm}
\qquad (\text{diseño: } e = <<e>>\ \text{cm},\ \Delta = <<dc>>\ \text{cm})
\end{align*}
\textbf{Resultante en el apoyo:}
\begin{align*}
\bar y_a &= \frac{\Sigma y_{i,a}}{n} = \frac{<<suma>>}{<<n>>} = <<yma>>\ \text{cm}\\
e_{res} &= \bar y - \bar y_a = <<yc>> - <<yma>> = <<era>>\ \text{cm}
\qquad (\text{debe ser } 0,\ \Delta = <<da>>\ \text{cm})
\end{align*}
Tolerancia adoptada: $\pm <<tol>>$ cm. Resultante: <<rok>>. Torones dentro del hormigón en toda la luz: <<dok>>.
<<fig1>>
<<fig2>>
""", n=rt.n, yobj=n(p.yc - r.e), yc=n(p.yc), filas="\n".join(filas_t), sumc=sum_c, suma=sum_a,
              ymc=n(rt.y_res_centro), yma=n(rt.y_res_apoyo), erc=n(rt.e_res_centro), era=n(rt.e_res_apoyo),
              e=n(r.e), dc=n(rt.dif_centro, 3), da=n(rt.dif_apoyo, 3), tol=n(rt.tolerancia, 2),
              rok=ok_tex(rt.resultante_ok, "coincide con el cable resultante", "NO coincide con el cable resultante"),
              dok=ok_tex(rt.dentro_ok, "sí", "no"),
              fig1=figura("torones_secciones.pdf", r"\textwidth", "Posición de los torones en el centro de la luz y en el apoyo."),
              fig2=figura("torones_elevacion.pdf", r"\textwidth", "Trayectoria de los torones y del cable resultante entre las curvas límite.")))

    # ------------------------------------------------- conclusión
    checks = [
        ("Esfuerzos admisibles en $L/2$ (tracción = 0)", r.cumple, True),
        ("Cable resultante entre las curvas límite en toda la luz", cl.cable_entre_curvas, True),
    ]
    if rt is not None:
        checks.append(("Resultante de los torones coincide con el cable resultante", rt.resultante_ok, True))
        checks.append(("Torones dentro del hormigón", rt.dentro_ok, True))
    checks.append(("Eficiencia $0.45 \\le Q \\le 0.55$ (criterio de economía)", 0.45 <= r.Q <= 0.55, False))
    checks.append(("Área de hormigón $\\ge A_{c,req}$ (predimensionamiento)", p.A >= pre.Ac_req, False))
    valido = all(c for _, c, oblig in checks if oblig)
    filas = "\n".join(f"{nom} & {'Obligatoria' if ob else 'Recomendación'} & {ok_tex(c)} \\\\" for nom, c, ob in checks)
    add(T(r"""
\section{Conclusión}
\begin{center}
\begin{tabular}{>{\raggedright\arraybackslash}p{9cm}ll}
\toprule
Verificación & Tipo & Estado \\
\midrule
<<filas>>
\bottomrule
\end{tabular}
\end{center}
\begin{itemize}
\item Sección adoptada: <<nombre>>, $h = <<h>>$ cm, $A = <<A>>$ cm$^2$ ($q_G = <<qG>>$ kg/m).
\item Presfuerzo: $F_0 = <<F0>>$ kg, $F = <<F>>$ kg, excentricidad <<tipo>> $e = <<e>>$ cm en $L/2$.
\item Cable resultante parabólico $y = <<k>>\,X^2$ (m), ángulo de salida $\alpha = <<adeg>>^\circ$.<<tor>>
\end{itemize}
\begin{center}\Large <<veredicto>>\end{center}
\end{document}
""", filas=filas, nombre=seccion.nombre.replace("_", " "), h=n(p.h, 1), A=n(p.A), qG=n(r.qG), F0=n(r.F0),
          F=n(r.F), tipo="restringida" if r.restringida else "no restringida", e=n(r.e),
          k=f"{r.k_parabola:.6f}", adeg=f"{r.angulo_salida * 57.29578:.2f}",
          tor=(f"\n\\item Torones: $n = {rt.n}$." if rt is not None else ""),
          veredicto=ok_tex(valido, r"\textbf{DISEÑO VÁLIDO}", r"DISEÑO NO VÁLIDO: rediseñar")))

    ruta_tex = carpeta / "Informe_Viga_Presforzada.tex"
    ruta_tex.write_text("\n".join(partes_doc), encoding="utf-8")
    print(f"LaTeX generado: {ruta_tex.as_posix()}")
    if compilar:
        compilar_pdf(ruta_tex)
    return ruta_tex


def compilar_pdf(ruta_tex: Path) -> Path | None:
    """Compila el .tex a PDF con Tectonic (dos pasadas internas para el índice)."""
    ruta_tex = Path(ruta_tex)
    if not shutil.which("tectonic"):
        print("Tectonic no está instalado: compile el .tex con XeLaTeX (p. ej. en Overleaf).")
        return None
    proc = subprocess.run(["tectonic", ruta_tex.name], cwd=ruta_tex.parent,
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    pdf = ruta_tex.with_suffix(".pdf")
    if proc.returncode == 0 and pdf.exists():
        print(f"PDF generado:   {pdf.as_posix()}")
        return pdf
    errores = [l for l in (proc.stdout + proc.stderr).splitlines()
               if l.startswith("error") or l.startswith("!")]
    print("No se pudo compilar el PDF. Errores de LaTeX:")
    print("\n".join(errores[:10]) or proc.stderr[-2000:])
    return None


if __name__ == "__main__":
    import matplotlib
    matplotlib.use("Agg")
    from presforzado import seccion_I, toron

    datos = Datos(L=35.0, fc=420.0, perdidas=18.0, d2=17.0,
                  q_losa=1200.0, q_acera=210.0, q_parantes=103.5, q_asfalto=287.5, q_L=800.0)
    seccion = seccion_I(bs=45, ts=16, bw=16, bi=70, ti=21, h=220)
    torones = [toron(-4, 7, y_apoyo=57.2), toron(4, 7, y_apoyo=57.2),
               toron(-4, 17, y_apoyo=97.2), toron(4, 17, y_apoyo=97.2),
               toron(-4, 27, y_apoyo=137.2), toron(4, 27, y_apoyo=137.2)]
    generar_informe(seccion, datos, torones)
