"""Verificación independiente de nivel-2/rutas.json.

Uso:  python codigo/validar.py [ruta_a_rutas.json]

Recalcula cada tramo sobre el mapa (datos.dijkstra) y comprueba:
formato exacto, un registro por vehículo, cada pedido una sola vez, horarios de la
flota, llegada antes de cada inicio, descarga completa dentro de la franja,
sin descargas superpuestas, regreso coherente y capacidades en kg y m3.
Imprime la distancia total y el detalle por vehículo.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import datos  # noqa: E402


def main():
    ruta = sys.argv[1] if len(sys.argv) > 1 else os.path.join(datos.NIVEL2, "rutas.json")
    with open(ruta, encoding="utf-8") as f:
        plan = json.load(f)

    operacion = datos.leer_json(os.path.join(datos.NIVEL2, "operacion.json"))
    flota = {v["vehiculo"]: v for v in datos.leer_json(os.path.join(datos.NIVEL2, "flota.json"))}
    catalogo = {c["producto"]: c for c in datos.leer_json(os.path.join(datos.NIVEL1, "catalogo.json"))}
    pedidos = {p["pedido"]: p for p in datos.leer_json(os.path.join(datos.NIVEL2, "pedidos.json"))}
    ady = datos.cargar_grafo(os.path.join(datos.NIVEL2, "siracusa.osm"), operacion["velocidades_kmh"])
    deposito = operacion["deposito"]
    cache = {}

    def tramo(u, v):
        if u not in cache:
            cache[u] = datos.dijkstra(ady, u)
        return cache[u][v]  # (metros, segundos)

    errores = []
    assert list(plan) == ["rutas"], "el objeto debe tener sólo la clave 'rutas'"
    vistos = []
    assert sorted(r["vehiculo"] for r in plan["rutas"]) == sorted(flota), "una fila por vehículo"
    total = 0
    for r in plan["rutas"]:
        assert list(r) == ["vehiculo", "salida", "paradas", "regreso"], r["vehiculo"]
        v = flota[r["vehiculo"]]
        t = datos.hms_a_seg(r["salida"])
        if t < datos.hms_a_seg(v["desde"]):
            errores.append(f"{r['vehiculo']}: sale antes de {v['desde']}")
        nodo, dist, kg, m3 = deposito, 0, 0.0, 0.0
        for p in r["paradas"]:
            assert list(p) == ["pedido", "inicio"]
            ped = pedidos[p["pedido"]]
            vistos.append(p["pedido"])
            d, s = tramo(nodo, ped["direccion"]["nodo"])
            dist += d
            llegada = t + s
            inicio = datos.hms_a_seg(p["inicio"])
            fin = inicio + ped["descarga_segundos"]
            if inicio < llegada:
                errores.append(f"{p['pedido']}: inicio {p['inicio']} antes de llegar ({datos.seg_a_hms(llegada)})")
            if inicio < datos.hms_a_seg(ped["franja"]["desde"]) or fin > datos.hms_a_seg(ped["franja"]["hasta"]):
                errores.append(f"{p['pedido']}: descarga fuera de franja")
            kg += sum(catalogo[i["producto"]]["kg"] * i["cantidad"] for i in ped["items"])
            m3 += sum(catalogo[i["producto"]]["m3"] * i["cantidad"] for i in ped["items"])
            t, nodo = fin, ped["direccion"]["nodo"]
        d, s = tramo(nodo, deposito)
        dist += d
        llegada = t + s
        regreso = datos.hms_a_seg(r["regreso"])
        if regreso != llegada:
            errores.append(f"{r['vehiculo']}: regreso declarado {r['regreso']} vs calculado {datos.seg_a_hms(llegada)}")
        if regreso > datos.hms_a_seg(v["hasta"]):
            errores.append(f"{r['vehiculo']}: vuelve después de {v['hasta']}")
        if kg > v["capacidad_kg"] + 1e-9 or m3 > v["capacidad_m3"] + 1e-9:
            errores.append(f"{r['vehiculo']}: excede capacidad ({kg:.2f} kg, {m3:.4f} m3)")
        total += dist
        print(f"{r['vehiculo']}: {len(r['paradas'])} pedidos, {dist} m, {kg:.2f}/{v['capacidad_kg']} kg, "
              f"{m3:.4f}/{v['capacidad_m3']} m3, {r['salida']}-{r['regreso']}")

    if sorted(vistos) != sorted(pedidos):
        errores.append("faltan o se repiten pedidos")
    print(f"distancia total: {total} m")
    if errores:
        print("ERRORES:")
        for e in errores:
            print(" -", e)
        sys.exit(1)
    print("OK: el plan cumple todas las condiciones verificadas")


if __name__ == "__main__":
    main()
