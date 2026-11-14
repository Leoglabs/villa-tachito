"""Carga de datos del nivel 2 y cálculo de tramos sobre el mapa.

Reglas aplicadas (operacion.json):
- Cada <way> del OSM es una arista entre dos nodos con su `distancia_m`.
- oneway=yes: sólo del primer nodo al segundo; oneway=-1: sólo del segundo
  al primero; oneway=no: ambos sentidos. Las aristas con access=no se descartan.
- Tiempo de arista: ceil(distancia_m * 3.6 / velocidad_kmh) segundos enteros,
  con la velocidad según el tipo de `highway`.
- Recorrido entre dos puntos: menor distancia dirigida; a igual distancia,
  menor tiempo (Dijkstra con clave lexicográfica (distancia, tiempo)).
"""

import csv
import heapq
import json
import os
import xml.etree.ElementTree as ET

NIVEL2 = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
NIVEL1 = os.path.normpath(os.path.join(NIVEL2, "..", "nivel-1"))


def leer_json(ruta):
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)


def hms_a_seg(hms):
    h, m, s = (int(x) for x in hms.split(":"))
    return h * 3600 + m * 60 + s


def seg_a_hms(seg):
    if not 0 <= seg < 24 * 3600:
        raise ValueError(f"hora fuera de la jornada: {seg}")
    return f"{seg // 3600:02d}:{seg % 3600 // 60:02d}:{seg % 60:02d}"


def tiempo_arista(distancia_m, velocidad_kmh):
    # ceil(d * 3.6 / v) en aritmética entera exacta: d*36 / (10*v)
    return -(-distancia_m * 36 // (10 * velocidad_kmh))


def cargar_grafo(ruta_osm, velocidades):
    """Devuelve {nodo: [(vecino, distancia_m, segundos), ...]} con aristas dirigidas."""
    ady = {}
    for way in ET.parse(ruta_osm).getroot().iter("way"):
        nds = [int(nd.get("ref")) for nd in way.iter("nd")]
        tags = {t.get("k"): t.get("v") for t in way.iter("tag")}
        if tags.get("access") == "no":
            continue
        if len(nds) != 2:
            raise ValueError(f"way {way.get('id')} con {len(nds)} nodos")
        a, b = nds
        dist = int(tags["distancia_m"])
        seg = tiempo_arista(dist, velocidades[tags["highway"]])
        sentido = tags.get("oneway", "no")
        if sentido in ("no", "yes"):
            ady.setdefault(a, []).append((b, dist, seg))
        if sentido in ("no", "-1"):
            ady.setdefault(b, []).append((a, dist, seg))
    return ady


def dijkstra(ady, origen):
    """Menor (distancia, tiempo) desde `origen` a todos los nodos alcanzables."""
    mejor = {origen: (0, 0)}
    cola = [(0, 0, origen)]
    while cola:
        d, t, u = heapq.heappop(cola)
        if (d, t) != mejor[u]:
            continue
        for v, dd, tt in ady.get(u, ()):
            cand = (d + dd, t + tt)
            if v not in mejor or cand < mejor[v]:
                mejor[v] = cand
                heapq.heappush(cola, (cand[0], cand[1], v))
    return mejor


def cargar_todo():
    """Lee los archivos recibidos y arma las matrices de tramos entre puntos de interés."""
    operacion = leer_json(os.path.join(NIVEL2, "operacion.json"))
    flota = leer_json(os.path.join(NIVEL2, "flota.json"))
    pedidos = leer_json(os.path.join(NIVEL2, "pedidos.json"))
    catalogo = {c["producto"]: c for c in leer_json(os.path.join(NIVEL1, "catalogo.json"))}
    with open(os.path.join(NIVEL1, "padron.csv"), encoding="utf-8") as f:
        padron = {(r["calle"], int(r["altura"]), int(r["nodo"])) for r in csv.DictReader(f)}

    for p in pedidos:
        d = p["direccion"]
        if (d["calle"], d["altura"], d["nodo"]) not in padron:
            raise ValueError(f"{p['pedido']}: domicilio fuera del padrón")
        p["kg"] = round(sum(catalogo[i["producto"]]["kg"] * i["cantidad"] for i in p["items"]), 4)
        p["m3"] = round(sum(catalogo[i["producto"]]["m3"] * i["cantidad"] for i in p["items"]), 6)
        p["desde_s"] = hms_a_seg(p["franja"]["desde"])
        p["hasta_s"] = hms_a_seg(p["franja"]["hasta"])

    ady = cargar_grafo(os.path.join(NIVEL2, "siracusa.osm"), operacion["velocidades_kmh"])

    # Puntos: índice 0 = depósito, índice k = pedidos[k-1]
    nodos = [operacion["deposito"]] + [p["direccion"]["nodo"] for p in pedidos]
    n = len(nodos)
    dist = [[0] * n for _ in range(n)]
    seg = [[0] * n for _ in range(n)]
    for i, origen in enumerate(nodos):
        res = dijkstra(ady, origen)
        for j, destino in enumerate(nodos):
            if destino not in res:
                raise ValueError(f"nodo {destino} inalcanzable desde {origen}")
            dist[i][j], seg[i][j] = res[destino]
    return operacion, flota, pedidos, dist, seg
