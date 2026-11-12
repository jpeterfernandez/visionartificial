"""
Clasificación de color de vinilo en chasis terminados.

Lógica portada directamente desde prueba_v3.py:
- Analiza los píxeles HSV dentro del bounding box de una detección.
- Compara contra tres tonos de referencia (naranja, azul, rosado).
- Devuelve el nombre del color o None si no hay suficiente color saturado.

Se usa en ALMACÉN para saber cuántas máquinas hay de cada color.
"""

from typing import Optional, Tuple
import cv2
import numpy as np

# Nombres de colores en el mismo orden que las referencias HSV
VINYL_COLOR_NAMES: Tuple[str, ...] = ("naranja", "azul", "rosado")

# Valores HSV de OpenCV (H: 0-179, S/V: 0-255) para cada color de referencia.
# Tomados directamente de prueba_v3.py — calibrados para los vinilos de Cardinova.
VINYL_COLOR_HSV = np.array(
    ((1, 174, 251), (122, 171, 115), (158, 156, 255)),
    dtype=np.int16,
)

# Distancia máxima en el espacio HSV ponderado para aceptar un match
VINYL_COLOR_MAX_DISTANCE: float = 20.0


def classify_vinyl_color(
    frame: np.ndarray,
    bbox: Tuple[int, int, int, int],
) -> Optional[str]:
    """
    Clasifica el color del vinilo dentro del bounding box dado.

    Args:
        frame: imagen BGR (numpy array, como la decodificada por cv2).
        bbox:  (x1, y1, x2, y2) en píxeles.

    Returns:
        Nombre del color ("naranja", "azul" o "rosado") o None si no se
        puede determinar (recorte inválido, sin píxeles saturados, o ningún
        píxel dentro de la tolerancia de distancia).
    """
    frame_h, frame_w = frame.shape[:2]
    x1 = max(0, min(frame_w, int(bbox[0])))
    y1 = max(0, min(frame_h, int(bbox[1])))
    x2 = max(0, min(frame_w, int(bbox[2])))
    y2 = max(0, min(frame_h, int(bbox[3])))

    if x2 <= x1 or y2 <= y1:
        return None

    # Inset del 15% para evitar los bordes del recuadre donde el fondo
    # contamina el análisis de color.
    width, height = x2 - x1, y2 - y1
    inset_x = int(width * 0.15)
    inset_y = int(height * 0.15)
    if width > 2 * inset_x and height > 2 * inset_y:
        x1 += inset_x
        x2 -= inset_x
        y1 += inset_y
        y2 -= inset_y

    roi = frame[y1:y2, x1:x2]
    if roi.size == 0:
        return None

    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    pixels = hsv.reshape(-1, 3)

    # Solo píxeles con saturación y brillo mínimos (descarta blancos/grises)
    colored_pixels = pixels[(pixels[:, 1] >= 60) & (pixels[:, 2] >= 40)]
    if colored_pixels.size == 0:
        return None

    # Calcular distancia a cada color de referencia en espacio HSV ponderado.
    # El canal H es circular (0-179), por eso se usa el mínimo entre la
    # diferencia directa y la complementaria, multiplicado por 2 para
    # equiparar escala con S y V.
    references = VINYL_COLOR_HSV[np.newaxis, :, :]  # (1, 3 colores, 3 canales)

    hue_delta = np.abs(
        colored_pixels[:, np.newaxis, 0].astype(np.int16) - references[:, :, 0]
    )
    hue_delta = np.minimum(hue_delta, 180 - hue_delta) * 2

    saturation_delta = (
        colored_pixels[:, np.newaxis, 1].astype(np.int16) - references[:, :, 1]
    )
    value_delta = (
        colored_pixels[:, np.newaxis, 2].astype(np.int16) - references[:, :, 2]
    )

    # S y V tienen menor peso que H para que el tono domine la clasificación
    distances = np.sqrt(
        hue_delta ** 2
        + (saturation_delta * 0.25) ** 2
        + (value_delta * 0.10) ** 2
    )

    closest = np.argmin(distances, axis=1)
    within_tolerance = np.min(distances, axis=1) <= VINYL_COLOR_MAX_DISTANCE

    if not np.any(within_tolerance):
        return None

    color_counts = np.bincount(
        closest[within_tolerance],
        minlength=len(VINYL_COLOR_NAMES),
    )
    return VINYL_COLOR_NAMES[int(np.argmax(color_counts))]
