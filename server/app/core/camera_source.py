from urllib.parse import urlsplit


SUPPORTED_CAMERA_SCHEMES = {"rtsp", "rtsps", "http", "https"}


def normalize_camera_source(source: str) -> str:
    normalized = source.strip()
    parsed = urlsplit(normalized)
    if parsed.scheme.lower() not in SUPPORTED_CAMERA_SCHEMES or not parsed.hostname:
        raise ValueError("La fuente debe ser una URL RTSP, RTSPS, HTTP o HTTPS de una cámara de red.")
    return normalized


def is_network_camera_source(source: str) -> bool:
    try:
        normalize_camera_source(source)
    except ValueError:
        return False
    return True
