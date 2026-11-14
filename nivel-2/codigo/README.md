# Nivel 2 — Un recorrido para cada vehículo

Código que genera `nivel-2/rutas.json`. Sólo usa la biblioteca estándar de Python 3.8 o posterior; no requiere instalar paquetes.

## Archivos de entrada

Los archivos recibidos no están en el repositorio. Para correr el código, colocarlos así:

```
nivel-1/catalogo.json
nivel-1/padron.csv
nivel-2/pedidos.json
nivel-2/siracusa.osm
nivel-2/flota.json
nivel-2/operacion.json
```

## Uso

Desde la raíz del repositorio:

```
python nivel-2/codigo/planificar.py     # escribe nivel-2/rutas.json
python nivel-2/codigo/validar.py        # verifica el plan y muestra los kilómetros
```

`planificar.py` acepta `--iter N` (por defecto 5000), `--semilla S` (por defecto 1) y `--salida RUTA`. Con los valores por defecto el resultado es reproducible.

## Qué hace cada archivo

- `datos.py`: lee los archivos y arma el grafo dirigido del mapa. Cada `way` es una arista con su `distancia_m`. Respeta `oneway` (`yes`, `-1`, `no`) y descarta `access=no`. El tiempo de cada arista es `ceil(distancia_m * 3.6 / velocidad)`, con la velocidad según `highway`, y se suman segundos enteros. Entre dos puntos toma el camino de menor distancia dirigida y, si hay empate, el de menor tiempo: es un Dijkstra con clave `(distancia, tiempo)`. Además verifica que cada domicilio esté en el padrón y calcula los kg y m3 de cada pedido con el catálogo.
- `planificar.py`: resuelve el problema de ruteo con ventanas horarias y capacidades.
  - Restricciones: una salida por vehículo y vuelta al depósito. La salida es posterior a `desde` y el regreso anterior a `hasta`. Cada descarga se hace completa dentro de la franja del cliente y se puede esperar antes de iniciarla. Las descargas se hacen una a la vez y la carga respeta los kg y m3 del vehículo.
  - Objetivo: la menor distancia total, incluidas las salidas y los regresos.
  - Método: inserción con arrepentimiento, luego búsqueda de vecindario grande (destruir y reparar) con recocido simulado, y al final una mejora local (reubicar, 2-opt e intercambio).
  - Cada camioneta sale lo más tarde posible sin cambiar su primer inicio de descarga.
- `validar.py`: vuelve a recorrer el plan tramo por tramo sobre el mapa y comprueba el formato, que cada pedido aparezca una sola vez, los horarios, las franjas y las capacidades.

## Resultado

| Vehículo | Pedidos | Distancia | Carga |
|---|---|---|---|
| V1 | 27 | 21.912 m | 280,64 kg / 1,29 m3 |
| V2 | 27 | 20.007 m | 298,64 kg / 1,30 m3 |
| V3 | 26 | 19.683 m | 525,40 kg / 1,83 m3 |
| **Total** | **80** | **61.602 m** | |

Con 8 semillas distintas, el mejor valor encontrado fue siempre 61.602 m (en 6 de las 8 corridas).
