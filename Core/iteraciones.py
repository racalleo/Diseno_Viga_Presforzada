"""
Registro de iteraciones de la sección transversal.

Cada vez que el usuario guarda una iteración se agrega al archivo `iteraciones.json`:
la geometría completa de la sección (para volver a dibujarla en el informe), los datos con
que se calculó y todos los resultados hasta la eficiencia Q.

Uso desde el cuaderno:
    reg = Registro("Iteraciones/iteraciones.json")
    reg.guardar(seccion, datos, res)     # agrega la iteración actual
    reg.borrar(3)                        # borra la iteración 3 (renumera)
    reg.nuevo()                          # vacía el registro (nuevo diseño)
    reg.resumen_md()                     # tabla resumen (markdown)
"""

from __future__ import annotations

import datetime as dt
import json
import os
from dataclasses import asdict


from presforzado import Cota, Datos, Poligono, Resultado, Seccion

ETIQUETA_FIBRA = {("inicial", "1"): "f₁ inicial", ("inicial", "2"): "f₂ inicial",
                  ("final", "1"): "f₁ final", ("final", "2"): "f₂ final"}


# ---------------------------------------------------------------------------
# Conversión sección <-> diccionario
# ---------------------------------------------------------------------------

def seccion_a_dict(s: Seccion) -> dict:
    return dict(
        nombre=s.nombre, bw=s.bw,
        partes=[list(p) for p in s.partes] if s.partes else None,
        poligonos=[dict(puntos=[list(map(float, pt)) for pt in p.puntos], hueco=p.hueco) for p in s.poligonos],
        cotas=[dict(p1=list(c.p1), p2=list(c.p2), tipo=c.tipo, offset=c.offset, texto=c.texto) for c in s.cotas],
    )


def seccion_de_dict(d: dict) -> Seccion:
    return Seccion(
        poligonos=[Poligono([tuple(pt) for pt in p["puntos"]], p["hueco"]) for p in d["poligonos"]],
        nombre=d["nombre"],
        partes=[tuple(p) for p in d["partes"]] if d.get("partes") else None,
        bw=d.get("bw"),
        cotas=[Cota(tuple(c["p1"]), tuple(c["p2"]), c["tipo"], c["offset"], c["texto"]) for c in d.get("cotas", [])],
    )


# ---------------------------------------------------------------------------
# Veredicto
# ---------------------------------------------------------------------------

def motivos(res: Resultado) -> list[str]:
    """Explicación de cada esfuerzo que no cumple (vacía si la sección cumple)."""
    salida = []
    for etapa in ("inicial", "final"):
        lim = res.limites[etapa]
        for fibra, f in zip(("1", "2"), res.esfuerzos[etapa]):
            if res.verificacion[(etapa, fibra)]:
                continue
            nombre = ETIQUETA_FIBRA[(etapa, fibra)]
            if f < lim["comp"]:
                salida.append(f"{nombre} = {f:.2f} kg/cm² < {lim['comp']:.2f} kg/cm² "
                              f"(excede la compresión admisible)")
            else:
                salida.append(f"{nombre} = {f:.2f} kg/cm² > {lim['trac']:.2f} kg/cm² (tracción no permitida)")
    return salida


def veredicto_md(res: Resultado) -> str:
    q_ok = 0.45 <= res.Q <= 0.55
    if res.cumple:
        txt = "### ✓ La sección CUMPLE con los esfuerzos admisibles de f₁ y f₂."
    else:
        txt = ("### ✗ La sección NO CUMPLE\n\n" + "\n".join(f"- {m}" for m in motivos(res)) +
               "\n\n**Modifique la sección (paso 3) y vuelva a ejecutar.**")
    return txt + f"\n\nEficiencia: $Q$ = {res.Q:.3f} → {'✓' if q_ok else '⚠'} {res.Q_estado}"


# ---------------------------------------------------------------------------
# Registro
# ---------------------------------------------------------------------------

def _datos_dict(d: Datos) -> dict:
    return {k: (float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v)
            for k, v in asdict(d).items()}


def iteracion_de(seccion: Seccion, datos: Datos, res: Resultado) -> dict:
    """Diccionario con todo lo calculado para una sección (hasta Q)."""
    p = res.prop
    return dict(
        fecha=dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        seccion=seccion_a_dict(seccion),
        datos=_datos_dict(datos),
        prop=dict(A=p.A, h=p.h, yc=p.yc, c1=p.c1, c2=p.c2, I=p.I, S1=p.S1, S2=p.S2,
                  k1=p.k1, k2=p.k2, r2=p.r2),
        qG=res.qG, qD=res.qD, qT=res.qT, MG=res.MG, MT=res.MT,
        alpha=res.alpha, emax=res.emax, e_no_restr=res.e_no_restr, restringida=res.restringida,
        F=res.F, F0=res.F0, e=res.e,
        esfuerzos={k: list(v) for k, v in res.esfuerzos.items()},
        limites=res.limites,
        verificacion={f"{et}_{fi}": ok for (et, fi), ok in res.verificacion.items()},
        cumple=res.cumple, motivos=motivos(res),
        Q=res.Q, Q_r2=res.Q_r2, Q_estado=res.Q_estado,
    )


class Registro:
    def __init__(self, ruta: str = "Iteraciones/iteraciones.json"):
        self.ruta = ruta
        self.iteraciones: list[dict] = []
        if os.path.exists(ruta):
            with open(ruta, encoding="utf-8") as f:
                self.iteraciones = json.load(f)

    # --- persistencia ---------------------------------------------------------
    def _escribir(self):
        for i, it in enumerate(self.iteraciones, start=1):
            it["n"] = i
        os.makedirs(os.path.dirname(self.ruta) or ".", exist_ok=True)
        with open(self.ruta, "w", encoding="utf-8") as f:
            json.dump(self.iteraciones, f, indent=1, ensure_ascii=False)

    def buscar(self, seccion: Seccion, datos: Datos) -> int | None:
        """Número de la iteración guardada con la misma sección y los mismos datos (o None)."""
        g, dd = seccion_a_dict(seccion), _datos_dict(datos)
        for it in self.iteraciones:
            if it["seccion"]["poligonos"] == g["poligonos"] and it["datos"] == dd:
                return it["n"]
        return None

    def guardar(self, seccion: Seccion, datos: Datos, res: Resultado) -> str:
        n = self.buscar(seccion, datos)
        if n is not None:
            return f"⚠ Esta sección ya está guardada como iteración {n}; no se duplicó."
        self.iteraciones.append(iteracion_de(seccion, datos, res))
        self._escribir()
        it = self.iteraciones[-1]
        return f"✓ Guardada como iteración {it['n']} ({'cumple' if it['cumple'] else 'no cumple'})."

    def borrar(self, n: int) -> str:
        if not 1 <= n <= len(self.iteraciones):
            return f"⚠ No existe la iteración {n}."
        self.iteraciones.pop(n - 1)
        self._escribir()
        return f"✓ Iteración {n} borrada; las demás se renumeraron."

    def nuevo(self) -> str:
        self.iteraciones = []
        self._escribir()
        return "✓ Registro vaciado: la próxima iteración guardada será la 1."

    # --- consultas -----------------------------------------------------------
    @property
    def adoptada(self) -> dict | None:
        """Última iteración guardada que cumple."""
        return next((it for it in reversed(self.iteraciones) if it["cumple"]), None)

    def avisos_datos(self, datos: Datos) -> list[str]:
        """Iteraciones calculadas con datos distintos a los actuales."""
        dd = _datos_dict(datos)
        distintas = []
        for it in self.iteraciones:
            dif = [k for k in dd if it["datos"].get(k) != dd[k]]
            if dif:
                distintas.append(f"{it['n']} ({', '.join(dif)})")
        if not distintas:
            return []
        return ["Las iteraciones " + "; ".join(distintas) + " se calcularon con datos distintos a los actuales. "
                "Si cambió el problema, use `reg.nuevo()` para empezar un registro nuevo."]

    # --- tabla resumen -------------------------------------------------------
    def resumen_md(self) -> str:
        if not self.iteraciones:
            return "*Aún no hay iteraciones guardadas.*"
        cab = ("| N° | Sección | A [cm²] | q_G [kg/m] | Excentricidad | F₀ [kg] | F [kg] | e [cm] | "
               "f₁ ini | f₂ ini | f₁ fin | f₂ fin | Q | Estado |\n|" + "---|" * 14)
        filas = []
        ad = self.adoptada
        for it in self.iteraciones:
            v = it["verificacion"]
            fi, ff = it["esfuerzos"]["inicial"], it["esfuerzos"]["final"]

            def f(val, clave):
                return f"{val:.2f}" if v[clave] else f"**{val:.2f}** ✗"
            estado = "✓ Cumple" if it["cumple"] else "✗ No cumple"
            if ad is not None and it is ad:
                estado += " · **adoptada**"
            filas.append(
                f"| {it['n']} | {it['seccion']['nombre']} | {it['prop']['A']:,.0f} | {it['qG']:,.1f} | "
                f"{'Restringida' if it['restringida'] else 'No restringida'} | {it['F0']:,.0f} | {it['F']:,.0f} | "
                f"{it['e']:.2f} | {f(fi[0], 'inicial_1')} | {f(fi[1], 'inicial_2')} | {f(ff[0], 'final_1')} | "
                f"{f(ff[1], 'final_2')} | {it['Q']:.3f} | {estado} |")
        lim = self.iteraciones[-1]["limites"]
        pie = (f"\n\nAdmisibles: inicial {lim['inicial']['comp']:.2f} ≤ f ≤ 0 · final {lim['final']['comp']:.2f} ≤ f ≤ 0 "
               "[kg/cm²]. Valores en **negrita ✗** no cumplen.")
        return cab + "\n" + "\n".join(filas) + pie


# ---------------------------------------------------------------------------
# Gráfico comparativo
# ---------------------------------------------------------------------------
