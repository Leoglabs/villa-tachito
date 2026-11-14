"""Planificador de recorridos del nivel 2 (VRP con ventanas horarias y capacidades).

Uso:  python codigo/planificar.py [--iter N] [--semilla S]
Escribe nivel-2/rutas.json.

Modelo:
- Un viaje por vehículo: sale del depósito no antes de `desde`, vuelve no después de `hasta`.
- Cada pedido se descarga completo dentro de su franja: inicio >= franja.desde y
  inicio + descarga_segundos <= franja.hasta. Se puede esperar antes de descargar.
- La carga del viaje (kg y m3 del catálogo, por cantidad) no supera la del vehículo.
- Objetivo: minimizar la distancia total (incluye salidas y regresos).

Método: inserción con arrepentimiento (regret) para la solución inicial y luego
búsqueda de vecindario grande (destruir y reparar) con recocido simulado, más una
mejora local final (reubicar / intercambiar / 2-opt). Todo es determinístico
para una semilla dada.
"""

import argparse
import json
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import datos  # noqa: E402


class Problema:
    def __init__(self):
        self.operacion, self.flota, self.pedidos, self.D, self.T = datos.cargar_todo()
        self.n = len(self.pedidos)
        # índice 0 = depósito; i = pedidos[i-1]
        self.a = [0] + [p["desde_s"] for p in self.pedidos]
        self.b = [0] + [p["hasta_s"] for p in self.pedidos]
        self.s = [0] + [p["descarga_segundos"] for p in self.pedidos]
        self.kg = [0.0] + [p["kg"] for p in self.pedidos]
        self.m3 = [0.0] + [p["m3"] for p in self.pedidos]
        self.v_desde = [datos.hms_a_seg(v["desde"]) for v in self.flota]
        self.v_hasta = [datos.hms_a_seg(v["hasta"]) for v in self.flota]
        self.v_kg = [v["capacidad_kg"] for v in self.flota]
        self.v_m3 = [v["capacidad_m3"] for v in self.flota]

    # ---------- evaluación de una ruta ----------
    def tiempos(self, v, ruta):
        """Inicio más temprano E y más tardío L de cada parada de [0]+ruta+[0]."""
        seq = [0] + ruta + [0]
        m = len(seq)
        T, s = self.T, self.s
        E = [0] * m
        E[0] = self.v_desde[v]
        for k in range(1, m - 1):
            c = seq[k]
            E[k] = max(E[k - 1] + s[seq[k - 1]] + T[seq[k - 1]][c], self.a[c])
        E[m - 1] = E[m - 2] + s[seq[m - 2]] + T[seq[m - 2]][0]
        L = [0] * m
        L[m - 1] = self.v_hasta[v]
        for k in range(m - 2, 0, -1):
            c = seq[k]
            L[k] = min(self.b[c] - s[c], L[k + 1] - T[c][seq[k + 1]] - s[c])
        L[0] = L[1] - T[0][seq[1]] if m > 2 else self.v_hasta[v]
        return seq, E, L

    def factible(self, v, ruta):
        if sum(self.kg[c] for c in ruta) > self.v_kg[v] + 1e-9:
            return False
        if sum(self.m3[c] for c in ruta) > self.v_m3[v] + 1e-9:
            return False
        _, E, L = self.tiempos(v, ruta)
        return all(e <= l for e, l in zip(E, L))

    def distancia(self, ruta):
        seq = [0] + ruta + [0]
        return sum(self.D[seq[k]][seq[k + 1]] for k in range(len(seq) - 1))

    def total(self, rutas):
        return sum(self.distancia(r) for r in rutas)

    # ---------- inserción ----------
    def mejores_inserciones(self, rutas, info, c):
        """Lista de (costo, v, pos) factibles para insertar el pedido c."""
        D, T, s = self.D, self.T, self.s
        out = []
        for v, ruta in enumerate(rutas):
            seq, E, L, kg, m3 = info[v]
            if kg + self.kg[c] > self.v_kg[v] + 1e-9 or m3 + self.m3[c] > self.v_m3[v] + 1e-9:
                continue
            for k in range(len(seq) - 1):
                i, j = seq[k], seq[k + 1]
                llegada = E[k] + s[i] + T[i][c]
                inicio = max(llegada, self.a[c])
                if inicio > self.b[c] - s[c]:
                    continue
                if inicio + s[c] + T[c][j] > L[k + 1]:
                    continue
                out.append((D[i][c] + D[c][j] - D[i][j], v, k))
        return out

    def info_ruta(self, v, ruta):
        seq, E, L = self.tiempos(v, ruta)
        return (seq, E, L, sum(self.kg[c] for c in ruta), sum(self.m3[c] for c in ruta))

    def reparar(self, rutas, pendientes, rng, ruido=0.0):
        """Inserción con arrepentimiento-2. Devuelve False si algún pedido no entra."""
        info = [self.info_ruta(v, r) for v, r in enumerate(rutas)]
        pendientes = list(pendientes)
        while pendientes:
            elegido = None
            for c in pendientes:
                ops = self.mejores_inserciones(rutas, info, c)
                if not ops:
                    return False
                ops.sort()
                costo = ops[0][0] * (1 + ruido * rng.random())
                # regret: diferencia con la mejor inserción en otro vehículo
                otro = next((o[0] for o in ops if o[1] != ops[0][1]), costo + 10**6)
                regret = otro - ops[0][0]
                clave = (-regret, costo)
                if elegido is None or clave < elegido[0]:
                    elegido = (clave, c, ops[0])
            _, c, (_, v, k) = elegido
            rutas[v].insert(k, c)
            info[v] = self.info_ruta(v, rutas[v])
            pendientes.remove(c)
        return True

    # ---------- destrucción ----------
    def quitar(self, rutas, q, rng):
        modo = rng.random()
        todos = [c for r in rutas for c in r]
        if modo < 0.4:  # relacionados: cercanos en espacio y horario
            semilla = rng.choice(todos)
            rel = sorted(todos, key=lambda c: self.D[semilla][c] + self.D[c][semilla]
                         + 3 * abs(self.a[c] - self.a[semilla]))
            quitados = rel[:q]
        elif modo < 0.7:  # peores: mayor ahorro al quitarlos
            costos = []
            for r in rutas:
                seq = [0] + r + [0]
                for k in range(1, len(seq) - 1):
                    i, c, j = seq[k - 1], seq[k], seq[k + 1]
                    costos.append((self.D[i][c] + self.D[c][j] - self.D[i][j], c))
            costos.sort(reverse=True)
            pool = [c for _, c in costos]
            quitados = []
            while len(quitados) < q:
                idx = int(len(pool) * rng.random() ** 3)
                quitados.append(pool.pop(idx))
        else:  # al azar
            quitados = rng.sample(todos, q)
        qs = set(quitados)
        return [[c for c in r if c not in qs] for r in rutas], quitados

    # ---------- mejora local ----------
    def mejora_local(self, rutas):
        mejoro = True
        while mejoro:
            mejoro = False
            # reubicar un pedido
            for v in range(len(rutas)):
                for k in range(len(rutas[v])):
                    c = rutas[v][k]
                    base = rutas[v][:k] + rutas[v][k + 1:]
                    ahorro = self.distancia(rutas[v]) - self.distancia(base)
                    mejor = None
                    for w in range(len(rutas)):
                        dest = base if w == v else rutas[w]
                        for pos in range(len(dest) + 1):
                            nueva = dest[:pos] + [c] + dest[pos:]
                            delta = self.distancia(nueva) - self.distancia(dest) - ahorro
                            if delta < 0 and (mejor is None or delta < mejor[0]) and self.factible(w, nueva):
                                mejor = (delta, w, nueva)
                    if mejor:
                        _, w, nueva = mejor
                        rutas[v] = base
                        rutas[w] = nueva
                        mejoro = True
                        break
                if mejoro:
                    break
            if mejoro:
                continue
            # 2-opt dentro de cada ruta
            for v in range(len(rutas)):
                r = rutas[v]
                for i in range(len(r)):
                    for j in range(i + 1, len(r)):
                        nueva = r[:i] + r[i:j + 1][::-1] + r[j + 1:]
                        if self.distancia(nueva) < self.distancia(r) and self.factible(v, nueva):
                            rutas[v] = nueva
                            mejoro = True
                            break
                    if mejoro:
                        break
                if mejoro:
                    break
            if mejoro:
                continue
            # intercambiar dos pedidos entre rutas
            for v in range(len(rutas)):
                for w in range(v + 1, len(rutas)):
                    for i in range(len(rutas[v])):
                        for j in range(len(rutas[w])):
                            rv = rutas[v][:]
                            rw = rutas[w][:]
                            rv[i], rw[j] = rw[j], rv[i]
                            delta = (self.distancia(rv) + self.distancia(rw)
                                     - self.distancia(rutas[v]) - self.distancia(rutas[w]))
                            if delta < 0 and self.factible(v, rv) and self.factible(w, rw):
                                rutas[v], rutas[w] = rv, rw
                                mejoro = True
                                break
                        if mejoro:
                            break
                    if mejoro:
                        break
                if mejoro:
                    break
        return rutas

    # ---------- búsqueda ----------
    def resolver(self, iteraciones, semilla, log=True):
        rng = random.Random(semilla)
        rutas = [[] for _ in self.flota]
        orden = sorted(range(1, self.n + 1), key=lambda c: self.a[c])
        if not self.reparar(rutas, orden, rng):
            raise RuntimeError("no se encontró una solución inicial factible")
        actual = [r[:] for r in rutas]
        costo_actual = self.total(actual)
        mejor, costo_mejor = [r[:] for r in actual], costo_actual
        temp0 = 0.02 * costo_actual
        for it in range(iteraciones):
            temp = temp0 * (1 - it / iteraciones) + 1e-9
            q = rng.randint(3, 15)
            cand, quitados = self.quitar(actual, q, rng)
            rng.shuffle(quitados)
            if not self.reparar(cand, quitados, rng, ruido=0.15):
                continue
            costo = self.total(cand)
            if costo < costo_actual or rng.random() < math.exp((costo_actual - costo) / temp):
                actual, costo_actual = cand, costo
                if costo < costo_mejor:
                    mejor, costo_mejor = [r[:] for r in cand], costo
                    if log:
                        print(f"  it {it}: {costo_mejor} m", flush=True)
        mejor = self.mejora_local(mejor)
        return mejor, self.total(mejor)

    # ---------- salida ----------
    def armar_plan(self, rutas):
        filas = []
        for v, ruta in enumerate(rutas):
            vid = self.flota[v]["vehiculo"]
            if not ruta:
                h = datos.seg_a_hms(self.v_desde[v])
                filas.append({"vehiculo": vid, "salida": h, "paradas": [], "regreso": h})
                continue
            seq, E, _ = self.tiempos(v, ruta)
            # salir lo más tarde posible sin cambiar el primer inicio (evita esperar en la calle)
            salida = max(self.v_desde[v], E[1] - self.T[0][seq[1]])
            paradas = [{"pedido": self.pedidos[c - 1]["pedido"], "inicio": datos.seg_a_hms(E[k + 1])}
                       for k, c in enumerate(ruta)]
            filas.append({"vehiculo": vid, "salida": datos.seg_a_hms(salida),
                          "paradas": paradas, "regreso": datos.seg_a_hms(E[-1])})
        return {"rutas": filas}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--iter", type=int, default=5000)
    ap.add_argument("--semilla", type=int, default=1)
    ap.add_argument("--salida", default=os.path.join(datos.NIVEL2, "rutas.json"))
    args = ap.parse_args()
    prob = Problema()
    rutas, costo = prob.resolver(args.iter, args.semilla)
    assert all(prob.factible(v, r) for v, r in enumerate(rutas))
    assert sorted(c for r in rutas for c in r) == list(range(1, prob.n + 1))
    plan = prob.armar_plan(rutas)
    with open(args.salida, "w", encoding="utf-8", newline="\n") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"distancia total: {costo} m -> {args.salida}")


if __name__ == "__main__":
    main()
