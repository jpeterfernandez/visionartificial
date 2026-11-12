"""
Deteccion de chasis y personas con YOLO + tracker temporal (v6: 3 colores por hex, voto por color mas cercano).

Cambios respecto a prueba_v3:
  * Se quito por completo la deteccion de celular. yolo26m solo cuenta personas.
  * Modelos a imgsz 640 y UN fotograma cada 1 s (processing.interval_ms, 200-2000).
    El tracker se ajusto para tan pocos fotogramas (confirma con 2 aciertos y las
    cajas siguen al objeto sin retraso). La imagen en vivo sigue fluida (~25 fps).
  * Chasis vinilado: regla de COLOR por HSV (config.json > "vinyl"): naranja, azul
    y rosado (editables). El color se vota entre fotogramas para que no parpadee.
    Clic izquierdo sobre la imagen = mide el HSV de ese punto (para calibrar).
  * Las detecciones de chasis ya NO se borran por tener el centro dentro de una
    persona: solo si su caja coincide con la de una persona (el modelo la confundio).
  * Anti-duplicados: umbral de centros relativo al tamano de la caja (no en pixeles),
    personas con contencion mas alta (no se funden dos operarios juntos) y
    cross_class_iou=null ya no rompe el programa.
  * Zonas: primero se quitan duplicados entre TODAS las clases y despues se filtra
    por zona; una clase prohibida fuerte ya no deja pasar a una clase permitida debil.
  * Reglas compuestas "exclusive": las piezas de mas (aunque la zona las oculte)
    ahora vetan la regla. Umbral de contencion configurable.
  * Camara: reconexion automatica del RTSP y lectura que solo convierte los
    fotogramas que se van a mostrar. La contrasena ya no vive en el codigo.
  * Pantalla: solo se redibuja cuando hay fotograma nuevo (menos CPU).
  * Ayuda para mejorar el modelo: tecla P guarda el fotograma actual y, si se
    activa "dataset_capture", se guardan solos los fotogramas dudosos.
  * config.json antiguo (v3) se migra solo: imgsz 640, intervalo 1000 ms, tracker nuevo.

Teclas: M menu | F reglas compuestas | Z / 1-9 zona | P guardar fotograma |
        G guardar config | R normal | Q/ESC salir | clic = medir color HSV
"""

import os

# Forzar RTSP sobre TCP: evita frames corruptos / perdidos por UDP.
# Debe definirse ANTES de importar cv2.
os.environ.setdefault(
    "OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp"
)

import copy
import itertools
import json
import threading
import time
from collections import namedtuple
from urllib.parse import urlsplit

import cv2
import numpy as np
from ultralytics import YOLO

# =====================================================
# CONFIGURACION (config.json)
# =====================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

# La URL de la camara NO va en el codigo (tiene usuario y clave).
# Defínela en la variable de entorno CAMERA_IP_URL o en config.json > cameras > source.
CAMERA_URL_HELP = (
    "rtsp://admin:Cardinova2026@192.168.100.67:554/h264/ch1/main/av_stream"
)

CONFIG_VERSION = 4

DEFAULT_CONFIG = {
    "config_version": CONFIG_VERSION,
    "model": {"path": "best_v15.pt", "image_size": 640},
    "people_model": {
        "path": "yolo26m.pt",
        "image_size": 640,
        "person_confidence": 0.45,
        # Un chasis se descarta SOLO si su caja coincide con la de una persona:
        # IoU >= exclude_iou, o casi toda dentro de ella (exclude_inside) y con
        # un tamano parecido (area >= exclude_area_ratio de la persona).
        "exclude_iou": 0.55,
        "exclude_inside": 0.90,
        "exclude_area_ratio": 0.45,
    },

    # source: URL de red (str) o "env:NOMBRE_VARIABLE"
    "cameras": [
        {"name": "Camara IP - Celular", "enabled": True,
         "source": "env:CAMERA_IP_URL"},
    ],

    # Zona activa y reglas por zona.
    #   blocked: clases que NUNCA pueden salir en esa zona.
    #   allowed: si no esta vacia, SOLO esas clases pueden salir.
    # Los nombres se escriben sin el prefijo "chasis_" (ej. "base").
    "active_zone": "Doblado",
    "zones": {
        "Doblado": {
            "description": "Chasis base y cavidad hueca; no se permiten piezas viniladas.",
            "blocked": [],
            "allowed": ["chasis_base", "cavidad_hueca"],
        },
        "Estructurado": {
            "description": "Puertas y paneles estructurales; no se permiten piezas viniladas.",
            "blocked": [],
            "allowed": [
                "chasis_base",
                "puerta_inferior",
                "puerta_sup_chapa",
                "puerta_sup_panel",
            ],
        },
        "Vinilado": {
            "description": "Solo piezas viniladas.",
            "blocked": [],
            "allowed": ["chasis_vinilado"],
        },
        "Almacen": {
            "description": "Solo piezas viniladas terminadas.",
            "blocked": [],
            "allowed": ["chasis_vinilado"],
        },
    },

    # Una regla compuesta etiqueta un chasis segun las clases detectadas
    # dentro de su caja. exclusive=True exige exactamente esos componentes.
    "composite_rules": [
        {
            "name": "Chasis armado",
            "parent_class": "chasis_base",
            "required_classes": ["puerta_sup_panel", "puerta_sup_chapa"],
            "exclusive": False,
            "hide_components": True,
        },
        {
            "name": "Chasis doblado",
            "parent_class": "chasis_base",
            "required_classes": ["cavidad_hueca"],
            "exclusive": True,
            "hide_components": True,
        },
    ],

    # Se rellena automaticamente con model.names al iniciar.
    "classes": [],

    "detection": {
        "confidence_start": 0.65,   # umbral para CREAR un objeto
        "confidence_keep": 0.30,    # umbral bajo para seguir un objeto ya detectado
        "min_box_area_ratio": 0.002,
        # Una pieza cuenta como "dentro" del chasis si esta contenida en esta
        # fraccion (0-1) de su caja. Bajalo si las puertas se salen de la caja base.
        "composite_containment": 0.70,
    },
    "duplicates": {
        "same_class_iou": 0.75,
        "containment": 0.70,
        "cross_class_iou": 0.85,    # null para desactivar
        # Centros mas cerca que esta fraccion de la caja mas pequena = duplicado.
        "center_fraction": 0.12,
        # Contencion para personas (mas alta: dos operarios juntos no se funden).
        "people_containment": 0.90,
    },
    # Pensado para 1 fotograma por segundo: pocos aciertos para confirmar,
    # cajas que siguen rapido al objeto y vida larga sin detecciones.
    "tracker": {
        "match_iou": 0.30,
        "min_hits": 2,
        "max_age_s": 4.0,
        "unconfirmed_age_s": 2.5,
        "box_alpha": 0.60,
        "deadband": 0.03,
        "conf_alpha": 0.50,
        "class_decay": 0.80,
    },

    # Color del chasis vinilado. SOLO existen 3 colores; cada pixel de la caja vota
    # por el color de referencia MAS CERCANO (sin tolerancia estricta: la luz varia).
    # Se escriben en hex ("#RRGGBB") o HSV [H,S,V] (OpenCV: H 0-179, S/V 0-255).
    # "ignore_colors" = fondo (ladrillo, piso) que se descarta para no confundirlo.
    # "zones" = zonas donde se mide el color (tecla V alterna en la zona activa).
    "vinyl": {
        "enabled": True,
        "class": "chasis_vinilado",
        "zones": {"Doblado": False, "Estructurado": False,
                  "Vinilado": True, "Almacen": True},
        "colors": {
            "azul": "#454163",
            "naranja": "#FF5D6A",
            "rosado": "#FF81BD",
        },
        "ignore_colors": {
            "ladrillo": [[10, 160, 210], [12, 150, 175]],
            "piso": [[15, 70, 150], [18, 60, 120]],
        },
        "tolerance": 80.0,
        "min_saturation": 35,
        "min_value": 30,
        "min_pixel_fraction": 0.04,
        "dominance": 1.0,
        "inset": 0.25,
        "votes_decay": 0.8,
    },

    # Correccion de imagen aplicada ANTES de la inferencia.
    # Ojo: el modelo se entreno con imagenes sin tocar; mejor dejar en neutro.
    "image": {
        "brightness": 0,        # -100 .. 100
        "contrast": 1.0,        # 0.1 .. 3.0
        "gamma": 1.0,           # 0.1 .. 3.0  (>1 aclara sombras)
        "saturation": 1.0,      # 0.0 .. 3.0
        "clahe": False,         # ecualizacion local de iluminacion
        "white_balance": False, # correccion de color (gray-world)
        "apply_to_preview": False,  # mostrar tambien el ajuste en pantalla
        "show_confidence": True,    # mostrar porcentaje de confianza en etiquetas
    },

    # interval_ms: cada cuantos ms se procesa un fotograma por camara (200-2000).
    # device: null (automatico), "cpu", 0 (primera GPU)...   half: solo con GPU.
    "processing": {"interval_ms": 1000, "device": None, "half": False},

    # Guarda fotogramas dudosos (confianza entre low_conf y high_conf) para
    # reetiquetarlos y reentrenar. Apagado por defecto. Tecla P = guardar a mano.
    "dataset_capture": {
        "enabled": False,
        "folder": "capturas",
        "low_conf": 0.30,
        "high_conf": 0.65,
        "min_interval_s": 10,
        "max_files": 3000,
    },

    "display": {"window_width": 960, "window_height": 600},
}


def is_network_camera_source(source):
    if not isinstance(source, str):
        return False
    try:
        parsed = urlsplit(source)
    except ValueError:
        return False
    return parsed.scheme.lower() in {"rtsp", "rtsps", "http", "https"} and bool(parsed.hostname)


_REPLACE_KEYS = {"zones", "cameras", "classes", "colors", "ignore_colors"}
CONFIG_NEEDS_SAVE = False


def _is_legacy_default_zones(zones):
    """Detecta la configuracion abierta de Almacen/Produccion de versiones anteriores."""
    if set(zones) != {"Almacen", "Produccion"}:
        return False

    warehouse = zones["Almacen"]
    production = zones["Produccion"]
    return (
        warehouse.get("description", "") == "Almacen: aqui nunca debe aparecer 'base'."
        and production.get("description", "") == "Produccion: se permiten todas las clases."
        and warehouse.get("allowed", []) == []
        and {str(value).strip().lower().removeprefix("chasis_")
             for value in warehouse.get("blocked", [])} == {"base"}
        and production.get("allowed", []) == []
        and production.get("blocked", []) == []
    )


def deep_merge(base, over):
    for key, value in over.items():
        if (
            isinstance(value, dict)
            and isinstance(base.get(key), dict)
            and key not in _REPLACE_KEYS
        ):
            deep_merge(base[key], value)
        else:
            base[key] = value


def migrate_config(cfg, from_version):
    """Lleva un config.json antiguo a los valores que pide la v4."""
    print(
        f"AVISO: config.json version {from_version} -> {CONFIG_VERSION}: "
        "imgsz 640, 1 fotograma por segundo y tracker nuevo."
    )
    cfg["model"]["image_size"] = DEFAULT_CONFIG["model"]["image_size"]
    cfg["processing"]["interval_ms"] = DEFAULT_CONFIG["processing"]["interval_ms"]
    cfg["tracker"] = copy.deepcopy(DEFAULT_CONFIG["tracker"])
    cfg["vinyl"] = copy.deepcopy(DEFAULT_CONFIG["vinyl"])


def load_config():
    global CONFIG_NEEDS_SAVE
    cfg = copy.deepcopy(DEFAULT_CONFIG)

    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if not isinstance(loaded, dict):
                raise ValueError("el archivo no es un objeto JSON")
            file_version = int(loaded.get("config_version", 1))
            deep_merge(cfg, loaded)
            if file_version < CONFIG_VERSION:
                migrate_config(cfg, file_version)
                CONFIG_NEEDS_SAVE = True
            cfg["config_version"] = CONFIG_VERSION
        except (OSError, ValueError) as error:
            bad = CONFIG_PATH + ".bad"
            print(f"AVISO: config.json ilegible ({error}).")
            print(f"       Se guarda copia en {bad} y se usan valores por defecto.")
            try:
                os.replace(CONFIG_PATH, bad)
            except OSError as backup_error:
                print(f"AVISO: no se pudo respaldar config.json: {backup_error}")
            cfg = copy.deepcopy(DEFAULT_CONFIG)
            CONFIG_NEEDS_SAVE = True

    # La deteccion de celular ya no existe: se limpian sus claves viejas.
    for stale_key in ("phone_confidence", "phone_confirm_frames", "detect_phone"):
        cfg["people_model"].pop(stale_key, None)

    configured_cameras = cfg.get("cameras") or []
    network_cameras = []
    for camera in configured_cameras:
        source = camera.get("source") if isinstance(camera, dict) else None
        is_environment_source = isinstance(source, str) and source.startswith("env:")
        if is_environment_source or is_network_camera_source(source):
            network_cameras.append(camera)
        else:
            print("AVISO: se omitio una camara local o sin URL de red valida.")
            CONFIG_NEEDS_SAVE = True
    cfg["cameras"] = network_cameras
    if "local_camera" in cfg:
        cfg.pop("local_camera")
        CONFIG_NEEDS_SAVE = True

    # Actualizar las zonas antiguas y conservar las reglas personalizadas.
    configured_zones = cfg.get("zones") or {}
    if _is_legacy_default_zones(configured_zones):
        configured_zones = {}
        CONFIG_NEEDS_SAVE = True

    zones = copy.deepcopy(DEFAULT_CONFIG["zones"])
    for zname, z in configured_zones.items():
        z = z if isinstance(z, dict) else {}
        zones[zname] = {
            "description": z.get("description", ""),
            "blocked": list(z.get("blocked", [])),
            "allowed": list(z.get("allowed", [])),
        }
    if any(name not in configured_zones for name in DEFAULT_CONFIG["zones"]):
        CONFIG_NEEDS_SAVE = True
    cfg["zones"] = zones

    if cfg["active_zone"] not in zones:
        first = next(iter(zones))
        print(f"AVISO: zona '{cfg['active_zone']}' no existe; se usa '{first}'.")
        cfg["active_zone"] = first

    return cfg


def save_config(cfg, live):
    """Guarda config.json incluyendo los valores vivos del menu."""
    out = copy.deepcopy(cfg)
    out.pop("local_camera", None)
    out["active_zone"] = live["zone"]
    out["detection"]["confidence_start"] = live["confidence_start"]
    out["detection"]["confidence_keep"] = live["confidence_keep"]
    out["processing"]["interval_ms"] = live["interval_ms"]
    out["config_version"] = CONFIG_VERSION
    for key in ("brightness", "contrast", "gamma", "saturation",
                "clahe", "white_balance", "apply_to_preview", "show_confidence"):
        out["image"][key] = live[key]

    write_config_file(out)

def write_config_file(cfg):
    """Escribe config.json atomicamente para preservar el ultimo archivo valido."""
    tmp = CONFIG_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, CONFIG_PATH)
    except OSError:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError as cleanup_error:
            print(f"AVISO: no se pudo limpiar el archivo temporal {tmp}: {cleanup_error}")
        raise


CFG = load_config()
if not os.path.exists(CONFIG_PATH) or CONFIG_NEEDS_SAVE:
    write_config_file(CFG)
    print(f"Configuracion inicial creada en: {CONFIG_PATH}")

MODEL_PATH = CFG["model"]["path"]
IMAGE_SIZE = int(CFG["model"]["image_size"])
PEOPLE_MODEL_PATH = CFG["people_model"]["path"]
PEOPLE_IMAGE_SIZE = int(CFG["people_model"]["image_size"])
MIN_BOX_AREA_RATIO = CFG["detection"]["min_box_area_ratio"]

SAME_CLASS_IOU = CFG["duplicates"]["same_class_iou"]
CONTAINMENT_THR = CFG["duplicates"]["containment"]
CROSS_CLASS_IOU = CFG["duplicates"]["cross_class_iou"]

MATCH_IOU = CFG["tracker"]["match_iou"]
MIN_HITS = CFG["tracker"]["min_hits"]
MAX_AGE_S = CFG["tracker"]["max_age_s"]
UNCONFIRMED_AGE_S = CFG["tracker"]["unconfirmed_age_s"]
BOX_ALPHA = CFG["tracker"]["box_alpha"]
DEADBAND = CFG["tracker"]["deadband"]
CONF_ALPHA = CFG["tracker"]["conf_alpha"]
CLASS_DECAY = CFG["tracker"]["class_decay"]

CENTER_FRACTION = CFG["duplicates"]["center_fraction"]
PEOPLE_CONTAINMENT = CFG["duplicates"]["people_containment"]
PERSON_CONFIDENCE = CFG["people_model"]["person_confidence"]
COMPOSITE_CONTAINMENT = CFG["detection"]["composite_containment"]

# Opciones extra de model.predict (GPU / media precision) segun config.json
PREDICT_EXTRA = {}
_device = CFG["processing"].get("device")
if _device not in (None, "", "auto"):
    PREDICT_EXTRA["device"] = _device
if CFG["processing"].get("half"):
    PREDICT_EXTRA["half"] = True

# =====================================================
# CARGAR MODELO YOLO
# =====================================================

print("Cargando modelo YOLO...")

def resolve_model_path(path):
    if os.path.isabs(path) or os.path.exists(path):
        return path
    return os.path.join(BASE_DIR, path)


MODEL_PATH = resolve_model_path(MODEL_PATH)
PEOPLE_MODEL_PATH = resolve_model_path(PEOPLE_MODEL_PATH)
model = YOLO(MODEL_PATH)

print(f"Modelo de chasis cargado: {MODEL_PATH}")
people_model = YOLO(PEOPLE_MODEL_PATH)
print(f"Modelo de personas cargado: {PEOPLE_MODEL_PATH}")


def class_id_for_name(yolo_model, class_name):
    names = yolo_model.names
    items = names.items() if isinstance(names, dict) else enumerate(names)
    for class_id, name in items:
        if str(name).strip().lower() == class_name:
            return int(class_id)
    raise ValueError(
        f"El modelo {PEOPLE_MODEL_PATH} no contiene la clase requerida "
        f"'{class_name}'. Clases: {names}"
    )


PERSON_CLASS_ID = class_id_for_name(people_model, "person")
print("Clase habilitada en el modelo de personas: person.")

# =====================================================
# ZONAS: QUE CLASES PUEDEN APARECER DONDE
# =====================================================


def norm_class(name):
    n = str(name).strip().lower()
    return n[len("chasis_"):] if n.startswith("chasis_") else n


def build_zone_rules(cfg):
    rules = {}
    for zname, z in cfg["zones"].items():
        allowed = {norm_class(c) for c in z["allowed"]}
        blocked = {norm_class(c) for c in z["blocked"]}
        rules[zname] = (allowed or None, blocked)
    return rules


def zone_class_status(cfg, zone_name, cls_name):
    zone = cfg["zones"][zone_name]
    normalized = norm_class(cls_name)
    blocked = {norm_class(value) for value in zone["blocked"]}
    allowed = {norm_class(value) for value in zone["allowed"]}
    if normalized in blocked:
        return "BLOCKED"
    if allowed and normalized not in allowed:
        return "EXCLUDED"
    if normalized in allowed:
        return "ALLOWED"
    return "NO RULE"


def set_zone_class_rule(cfg, zone_name, cls_name, status):
    """Aplica una regla de clase y zona. status es allow, block o none."""
    if status not in {"allow", "block", "none"}:
        raise ValueError(f"Estado de regla no valido: {status}")
    zone = cfg["zones"].get(zone_name)
    if zone is None:
        return False

    normalized = norm_class(cls_name)
    has_allowlist = bool(zone["allowed"])
    for key in ("allowed", "blocked"):
        zone[key] = [
            value for value in zone[key]
            if norm_class(value) != normalized
        ]
    if status == "allow" and has_allowlist:
        zone["allowed"].append(cls_name)
    elif status == "block":
        zone["blocked"].append(cls_name)
    return True


ZONE_RULES_LOCK = threading.RLock()


def class_allowed(cls_name, zone_name):
    n = norm_class(cls_name)
    with ZONE_RULES_LOCK:
        allowed, blocked = ZONE_RULES[zone_name]
        if n in blocked:
            return False
        if allowed is not None and n not in allowed:
            return False
        return True


# Sincronizar la lista de clases del modelo con config.json
_names = model.names
MODEL_CLASSES = (
    [_names[i] for i in sorted(_names)]
    if isinstance(_names, dict) else list(_names)
)
classes_changed = CFG["classes"] != MODEL_CLASSES
CFG["classes"] = MODEL_CLASSES

ZONE_RULES = build_zone_rules(CFG)
ZONE_NAMES = list(CFG["zones"])

# Avisar de nombres de clase mal escritos en las zonas
_known = {norm_class(c) for c in MODEL_CLASSES}
for _zname, _z in CFG["zones"].items():
    for _c in _z["allowed"] + _z["blocked"]:
        if norm_class(_c) not in _known:
            print(
                f"AVISO: zona '{_zname}' menciona la clase '{_c}', "
                f"que no existe en el modelo. Clases: {sorted(_known)}"
            )

if norm_class(CFG["vinyl"].get("class", "chasis_vinilado")) not in _known:
    print(
        f"AVISO: vinyl.class '{CFG['vinyl'].get('class')}' no existe en el modelo; "
        "no se identificara el color."
    )

# =====================================================
# AJUSTES EN VIVO (los que toca el menu)
# =====================================================

LIVE_LIMITS = {
    "confidence_start": (0.05, 0.99),
    "confidence_keep": (0.05, 0.99),
    "brightness": (-100, 100),
    "contrast": (0.1, 3.0),
    "gamma": (0.1, 3.0),
    "saturation": (0.0, 3.0),
    "interval_ms": (200, 2000),
}


def live_from_cfg(cfg, zone=None):
    return {
        "zone": zone or cfg["active_zone"],
        "confidence_start": cfg["detection"]["confidence_start"],
        "confidence_keep": cfg["detection"]["confidence_keep"],
        "interval_ms": cfg["processing"]["interval_ms"],
        "brightness": cfg["image"]["brightness"],
        "contrast": cfg["image"]["contrast"],
        "gamma": cfg["image"]["gamma"],
        "saturation": cfg["image"]["saturation"],
        "clahe": bool(cfg["image"]["clahe"]),
        "white_balance": bool(cfg["image"]["white_balance"]),
        "apply_to_preview": bool(cfg["image"]["apply_to_preview"]),
        "show_confidence": bool(cfg["image"].get("show_confidence", True)),
    }


class LiveSettings:
    def __init__(self, values):
        self._lock = threading.Lock()
        self._d = dict(values)
        self.dirty = False

    def snapshot(self):
        with self._lock:
            return dict(self._d)

    def get(self, key):
        with self._lock:
            return self._d[key]

    def set(self, key, value):
        with self._lock:
            if key in LIVE_LIMITS:
                lo, hi = LIVE_LIMITS[key]
                value = min(max(value, lo), hi)
            if self._d.get(key) != value:
                self._d[key] = value
                self.dirty = True
            # La confianza de mantener nunca puede superar la de crear
            if self._d["confidence_keep"] > self._d["confidence_start"]:
                self._d["confidence_keep"] = self._d["confidence_start"]

    def mark_dirty(self):
        with self._lock:
            self.dirty = True

    def reset_normal(self, defaults):
        """Vuelve a los valores de fabrica (la zona NO se toca)."""
        with self._lock:
            zone = self._d["zone"]
            self._d = dict(defaults)
            self._d["zone"] = zone
            self.dirty = True


FACTORY_LIVE = live_from_cfg(DEFAULT_CONFIG)
SETTINGS = LiveSettings(live_from_cfg(CFG))

# Primera ejecucion o clases nuevas: dejar config.json listo para editar
if not os.path.exists(CONFIG_PATH) or classes_changed or CONFIG_NEEDS_SAVE:
    save_config(CFG, SETTINGS.snapshot())
    print(f"config.json actualizado en: {CONFIG_PATH}")
    print(f"Clases del modelo: {MODEL_CLASSES}")

# =====================================================
# CORRECCION DE IMAGEN (iluminacion / color)
# =====================================================


def gray_world(img):
    """Balance de blancos simple: iguala la media de los tres canales."""
    means = np.array(cv2.mean(img)[:3], dtype=np.float32)
    gain = means.mean() / np.maximum(means, 1.0)
    out = img.astype(np.float32) * gain
    return np.clip(out, 0, 255).astype(np.uint8)


_clahe_local = threading.local()


def _get_clahe():
    clahe = getattr(_clahe_local, "obj", None)
    if clahe is None:
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        _clahe_local.obj = clahe
    return clahe


def adjust_image(frame, live):
    """Aplica solo los pasos que no estan en su valor neutro."""
    img = frame

    if live["white_balance"]:
        img = gray_world(img)

    if live["clahe"]:
        lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
        l_ch, a_ch, b_ch = cv2.split(lab)
        l_ch = _get_clahe().apply(l_ch)
        img = cv2.cvtColor(cv2.merge((l_ch, a_ch, b_ch)), cv2.COLOR_LAB2BGR)

    if abs(live["contrast"] - 1.0) > 1e-3 or live["brightness"] != 0:
        img = cv2.convertScaleAbs(
            img, alpha=live["contrast"], beta=live["brightness"]
        )

    if abs(live["gamma"] - 1.0) > 1e-3:
        table = (np.arange(256) / 255.0) ** (1.0 / live["gamma"]) * 255.0
        img = cv2.LUT(img, np.clip(table, 0, 255).astype(np.uint8))

    if abs(live["saturation"] - 1.0) > 1e-3:
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[..., 1] = np.clip(hsv[..., 1] * live["saturation"], 0, 255)
        img = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

    return img


# =====================================================
# COLOR DEL CHASIS VINILADO (regla por HSV)
# =====================================================
#
# Cada color de referencia es un HSV [H, S, V] (OpenCV: H 0-179, S/V 0-255) y
# vive en config.json > vinyl > colors. Para calibrar: clic izquierdo sobre el
# vinilo en la ventana de la camara y copia el HSV que se imprime.
#
# Regla: dentro de la caja del chasis (sin los bordes) se ignoran pixeles
# grises/oscuros, cada pixel restante vota por el color de referencia mas
# cercano (si esta dentro de la tolerancia) y gana el color que cubre al menos
# min_pixel_fraction de la caja y supera en `dominance` veces al segundo.
# Si no hay un ganador claro, el color queda sin identificar (None).


def is_vinyl_class(cls_name):
    return norm_class(cls_name) == VINYL_CLASS_NORM


def hex_to_hsv(text):
    """'#RRGGBB' -> (H, S, V) de OpenCV."""
    text = text.strip().lstrip("#")
    r, g, b = (int(text[i:i + 2], 16) for i in (0, 2, 4))
    h, s, v = cv2.cvtColor(np.uint8([[[b, g, r]]]), cv2.COLOR_BGR2HSV)[0, 0]
    return int(h), int(s), int(v)


def build_vinyl_tables(vinyl_cfg):
    names, hsv, ignore = [], [], []

    def add(group, is_ignore):
        for name, value in (group or {}).items():
            if isinstance(value, str):
                triplets = [value]
            elif value and isinstance(value[0], (list, tuple, str)):
                triplets = value
            else:
                triplets = [value]
            for t in triplets:
                try:
                    h, s, v = hex_to_hsv(t) if isinstance(t, str) else (int(p) for p in t)
                except (TypeError, ValueError, IndexError):
                    print(f"AVISO: color '{name}' invalido en config.json; se ignora.")
                    continue
                names.append(str(name))
                hsv.append((h, s, v))
                ignore.append(is_ignore)

    add(vinyl_cfg.get("colors"), False)
    add(vinyl_cfg.get("ignore_colors"), True)
    return (tuple(names), np.array(hsv, dtype=np.int16).reshape(-1, 3),
            np.array(ignore, dtype=bool))


VINYL_CFG = CFG["vinyl"]
VINYL_ENABLED = bool(VINYL_CFG.get("enabled", True))
VINYL_CLASS_NORM = norm_class(VINYL_CFG.get("class", "chasis_vinilado"))
VINYL_REF_NAMES, VINYL_COLOR_HSV, VINYL_REF_IGNORE = build_vinyl_tables(VINYL_CFG)
VINYL_COLOR_NAMES = tuple(dict.fromkeys(
    n for n, ign in zip(VINYL_REF_NAMES, VINYL_REF_IGNORE) if not ign
))
VINYL_TOLERANCE = float(VINYL_CFG.get("tolerance", 25.0))
VINYL_MIN_SATURATION = int(VINYL_CFG.get("min_saturation", 60))
VINYL_MIN_VALUE = int(VINYL_CFG.get("min_value", 40))
VINYL_MIN_FRACTION = float(VINYL_CFG.get("min_pixel_fraction", 0.05))
VINYL_DOMINANCE = float(VINYL_CFG.get("dominance", 1.3))
VINYL_INSET = float(VINYL_CFG.get("inset", 0.25))
VINYL_VOTES_DECAY = float(VINYL_CFG.get("votes_decay", 0.8))
VINYL_BOX_BGR = {
    "azul": (255, 120, 40),
    "naranja": (106, 93, 255),
    "rosado": (189, 129, 255),
}


def vinyl_enabled_in(zone_name):
    """True si en esta zona se mide el color del vinilo."""
    return VINYL_ENABLED and bool(VINYL_CFG.get("zones", {}).get(zone_name, False))


if VINYL_ENABLED and not VINYL_COLOR_NAMES:
    print("AVISO: vinyl.colors esta vacio; no se identificara el color.")


def vinyl_distances(pixels):
    """Distancia HSV de cada pixel (N,3) a cada color de referencia -> (N, colores).

    El tono pesa mucho; saturacion y brillo poco (cambian con la luz).
    """
    pixels = pixels.astype(np.int16)
    refs = VINYL_COLOR_HSV[np.newaxis, :, :]
    hue_delta = np.abs(pixels[:, np.newaxis, 0] - refs[:, :, 0])
    hue_delta = np.minimum(hue_delta, 180 - hue_delta) * 2
    saturation_delta = pixels[:, np.newaxis, 1] - refs[:, :, 1]
    value_delta = pixels[:, np.newaxis, 2] - refs[:, :, 2]
    return np.sqrt(
        hue_delta.astype(np.float32) ** 2
        + (saturation_delta.astype(np.float32) * 0.25) ** 2
        + (value_delta.astype(np.float32) * 0.10) ** 2
    )


def nearest_vinyl_color(hsv_triplet):
    """(nombre, distancia) de la referencia mas cercana (marca FONDO si es fondo)."""
    if len(VINYL_REF_NAMES) == 0:
        return None, None
    distances = vinyl_distances(np.array([hsv_triplet], dtype=np.int16))[0]
    index = int(np.argmin(distances))
    tag = " (FONDO)" if VINYL_REF_IGNORE[index] else ""
    return VINYL_REF_NAMES[index] + tag, float(distances[index])


def classify_vinyl_color(frame, box):
    """Devuelve el nombre del color del vinilo dentro de `box`, o None."""
    if not VINYL_COLOR_NAMES:
        return None
    frame_h, frame_w = frame.shape[:2]
    x1 = max(0, min(frame_w, int(box[0])))
    y1 = max(0, min(frame_h, int(box[1])))
    x2 = max(0, min(frame_w, int(box[2])))
    y2 = max(0, min(frame_h, int(box[3])))
    if x2 <= x1 or y2 <= y1:
        return None
    w, h = x2 - x1, y2 - y1
    ix, iy = int(w * VINYL_INSET), int(h * VINYL_INSET)
    if w > 2 * ix and h > 2 * iy:
        x1, x2, y1, y2 = x1 + ix, x2 - ix, y1 + iy, y2 - iy
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        return None

    step = max(1, max(crop.shape[:2]) // 160)
    crop = np.ascontiguousarray(crop[::step, ::step])
    pixels = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV).reshape(-1, 3)
    total = len(pixels)
    colored = pixels[
        (pixels[:, 1] >= VINYL_MIN_SATURATION) & (pixels[:, 2] >= VINYL_MIN_VALUE)
    ]
    if len(colored) == 0:
        return None

    distances = vinyl_distances(colored)
    closest = np.argmin(distances, axis=1)
    within = distances[np.arange(len(colored)), closest] <= VINYL_TOLERANCE
    # Pixeles cuyo vecino mas cercano es ladrillo/piso: se descartan.
    valid = within & ~VINYL_REF_IGNORE[closest]
    if not np.any(valid):
        return None

    ref_hits = np.bincount(closest[valid], minlength=len(VINYL_REF_NAMES))
    counts = {name: 0 for name in VINYL_COLOR_NAMES}
    for ref_index, hits in enumerate(ref_hits):
        if hits and not VINYL_REF_IGNORE[ref_index]:
            counts[VINYL_REF_NAMES[ref_index]] += int(hits)

    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    best_name, best = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0
    if best < VINYL_MIN_FRACTION * total:
        return None
    if second and best < VINYL_DOMINANCE * second:
        return None
    return best_name


# =====================================================
# GEOMETRIA Y REGLAS ANTI-DUPLICADOS
# =====================================================

Det = namedtuple("Det", ["box", "cls", "conf", "color"], defaults=[None])
DisplayDetection = namedtuple(
    "DisplayDetection", ["box", "label", "class_name", "color", "confidence"],
    defaults=[None],
)


def box_metrics(a, b):
    """Devuelve (IoU, inter/area_a, inter/area_b)."""
    ix1 = max(a[0], b[0])
    iy1 = max(a[1], b[1])
    ix2 = min(a[2], b[2])
    iy2 = min(a[3], b[3])

    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)

    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])

    union = area_a + area_b - inter

    iou = inter / union if union > 0 else 0.0
    ioa_a = inter / area_a if area_a > 0 else 0.0
    ioa_b = inter / area_b if area_b > 0 else 0.0

    return iou, ioa_a, ioa_b


def box_area(box):
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def exclude_detections_matching_people(detections, people, people_cfg):
    """Descarta detecciones que en realidad son una persona.

    Antes se borraba todo lo que tuviera el centro dentro de una persona, y eso
    eliminaba maquinas reales con un operario trabajando encima. Ahora solo se
    descarta si la caja coincide con la de la persona (IoU alto) o si queda casi
    toda dentro de ella y tiene un tamano parecido.
    """
    if not people:
        return list(detections)

    iou_limit = people_cfg["exclude_iou"]
    inside_limit = people_cfg["exclude_inside"]
    ratio_limit = people_cfg["exclude_area_ratio"]
    kept = []
    for detection in detections:
        detection_area = box_area(detection.box)
        is_person = False
        for person in people:
            iou, inside_detection, _ = box_metrics(detection.box, person.box)
            person_area = box_area(person.box)
            area_ratio = detection_area / person_area if person_area > 0 else 0.0
            if iou >= iou_limit or (
                inside_detection >= inside_limit and area_ratio >= ratio_limit
            ):
                is_person = True
                break
        if not is_person:
            kept.append(detection)
    return kept


def build_people_detections(person_tracks, show_confidence=True):
    """Convierte los tracks de personas en detecciones para dibujar."""
    people = []
    for track in person_tracks:
        label = "Persona"
        if show_confidence:
            label += f" {track.conf * 100:.0f}%"
        people.append(
            DisplayDetection(
                tuple(map(int, track.box)),
                label,
                "person",
                None,
                track.conf,
            )
        )
    return people


def extract_people(result, person_class_id, person_confidence):
    """Saca las personas del resultado de yolo26m."""
    people = []
    if result.boxes is None:
        return people
    for box in result.boxes:
        if int(box.cls[0]) != person_class_id:
            continue
        confidence = float(box.conf[0])
        if confidence >= person_confidence:
            people.append(Det(tuple(box.xyxy[0].tolist()), "person", confidence))
    return people


def apply_composite_rules(detections, rules, show_confidence=True,
                          context=(), containment=0.70):
    """Etiqueta chasis compuestos y oculta sus piezas, conservando otras maquinas.

    context: detecciones del fotograma que la zona NO deja mostrar. Solo sirven
    para vetar reglas "exclusive": si dentro del chasis hay piezas de mas (aunque
    la zona las oculte), no es un chasis compuesto exactamente por las pedidas.
    """
    result = list(detections)
    hidden_indices = set()
    for parent_index, parent in enumerate(detections):
        parent_class = norm_class(parent.class_name)
        for rule in rules:
            if norm_class(rule.get("parent_class", "")) != parent_class:
                continue

            required = [norm_class(value) for value in rule.get("required_classes", [])]
            if not required or parent_class in required:
                continue

            contained_classes = []
            for child_index, child in enumerate(detections):
                if child_index == parent_index:
                    continue
                child_class = norm_class(child.class_name)
                if child_class == parent_class:
                    continue
                _, child_containment, _ = box_metrics(child.box, parent.box)
                if child_containment >= containment:
                    contained_classes.append(child_class)

            required_counts = {name: required.count(name) for name in set(required)}
            contained_counts = {
                name: contained_classes.count(name)
                for name in set(contained_classes)
            }
            has_required = all(
                contained_counts.get(name, 0) >= count
                for name, count in required_counts.items()
            )
            if not has_required:
                continue

            if bool(rule.get("exclusive", False)):
                all_classes = list(contained_classes)
                for child in context:
                    child_class = norm_class(child.class_name)
                    if child_class == parent_class:
                        continue
                    _, child_containment, _ = box_metrics(child.box, parent.box)
                    if child_containment >= containment:
                        all_classes.append(child_class)
                all_counts = {
                    name: all_classes.count(name) for name in set(all_classes)
                }
                if all_counts != required_counts:
                    continue

            name = str(rule.get("name", "")).strip()
            if not name:
                continue
            label = name
            if show_confidence and parent.confidence is not None:
                label += f" {parent.confidence * 100:.0f}%"
            result[parent_index] = parent._replace(label=label)
            if rule.get("hide_components", True):
                for child_index, child in enumerate(detections):
                    if child_index == parent_index:
                        continue
                    if str(child.class_name).lower().startswith("chasis_"):
                        continue
                    _, child_containment, _ = box_metrics(child.box, parent.box)
                    if child_containment >= containment:
                        hidden_indices.add(child_index)
            break
    return [
        detection for index, detection in enumerate(result)
        if index not in hidden_indices
    ]


def track_match_score(track, detection):
    iou, _, _ = box_metrics(track.box, detection.box)
    if iou >= MATCH_IOU:
        return iou
    if track.cls != detection.cls:
        return None

    track_width = max(track.box[2] - track.box[0], 1.0)
    track_height = max(track.box[3] - track.box[1], 1.0)
    detection_width = max(detection.box[2] - detection.box[0], 1.0)
    detection_height = max(detection.box[3] - detection.box[1], 1.0)
    max_center_distance = 0.25 * min(
        track_width, track_height, detection_width, detection_height
    )
    track_center = (
        (track.box[0] + track.box[2]) / 2,
        (track.box[1] + track.box[3]) / 2,
    )
    detection_center = (
        (detection.box[0] + detection.box[2]) / 2,
        (detection.box[1] + detection.box[3]) / 2,
    )
    center_distance = (
        (track_center[0] - detection_center[0]) ** 2
        + (track_center[1] - detection_center[1]) ** 2
    ) ** 0.5
    return iou if center_distance <= max_center_distance else None


DUP_CHASSIS = {
    "same_iou": SAME_CLASS_IOU,
    "containment": CONTAINMENT_THR,
    "cross_iou": CROSS_CLASS_IOU,
    "center_fraction": CENTER_FRACTION,
}
# Personas: contencion alta (dos operarios juntos son dos) y sin regla entre clases.
DUP_PEOPLE = {
    "same_iou": SAME_CLASS_IOU,
    "containment": PEOPLE_CONTAINMENT,
    "cross_iou": None,
    "center_fraction": CENTER_FRACTION,
}


def suppress_duplicates(items, params=None):
    """
    Suprime detecciones redundantes con criterios diferenciados por caso:

    - Misma clase, centros muy cercanos (menos de center_fraction de la caja
      mas pequena): siempre duplicado. Es relativo al tamano, no en pixeles.
    - Misma clase, IoU >= same_iou: mismo objeto detectado dos veces.
    - Misma clase, contencion >= containment: una caja casi dentro de la otra.
    - Distinta clase, IoU >= cross_iou (si no es None): superposicion casi
      total entre clases distintas -> duplicado.

    En todos los casos se conserva la deteccion de mayor confianza (el
    ordenamiento descendente garantiza que la primera en 'kept' es la mejor).
    """
    p = params or DUP_CHASSIS
    ordered = sorted(items, key=lambda d: d.conf, reverse=True)
    kept = []

    for cand in ordered:
        duplicate = False
        cand_w = max(cand.box[2] - cand.box[0], 1.0)
        cand_h = max(cand.box[3] - cand.box[1], 1.0)
        cand_cx = (cand.box[0] + cand.box[2]) / 2
        cand_cy = (cand.box[1] + cand.box[3]) / 2

        for ref in kept:
            iou, ioa_cand, ioa_ref = box_metrics(cand.box, ref.box)

            if cand.cls == ref.cls:
                ref_w = max(ref.box[2] - ref.box[0], 1.0)
                ref_h = max(ref.box[3] - ref.box[1], 1.0)
                ref_cx = (ref.box[0] + ref.box[2]) / 2
                ref_cy = (ref.box[1] + ref.box[3]) / 2
                dist_sq = (cand_cx - ref_cx) ** 2 + (cand_cy - ref_cy) ** 2
                limit = p["center_fraction"] * min(cand_w, cand_h, ref_w, ref_h)

                if dist_sq < limit * limit:
                    duplicate = True
                    break
                if iou >= p["same_iou"]:
                    duplicate = True
                    break
                if max(ioa_cand, ioa_ref) >= p["containment"]:
                    duplicate = True
                    break
            else:
                cross = p["cross_iou"]
                if cross is not None and iou >= cross:
                    duplicate = True
                    break

        if not duplicate:
            kept.append(cand)

    return kept

# =====================================================
# TRACKER TEMPORAL (ESTABILIZA CAJAS, CLASES Y COLOR)
# =====================================================


class Track:
    _ids = itertools.count(1)

    def __init__(self, box, cls, conf, now, color=None):
        self.id = next(Track._ids)

        self.box = [float(v) for v in box]
        self.class_scores = {cls: conf}
        self.color_scores = {}
        if color is not None:
            self.color_scores[color] = 1.0
        self._conf = conf
        self.hits = 1
        self.last_seen = now

    @property
    def cls(self):
        # Clase por voto ponderado con memoria: evita saltos de clase.
        return max(self.class_scores, key=self.class_scores.get)

    @property
    def color(self):
        # Color del vinilo por voto entre fotogramas; None si nunca se identifico.
        if not self.color_scores:
            return None
        return max(self.color_scores, key=self.color_scores.get)

    @property
    def conf(self):
        return self._conf

    @property
    def confirmed(self):
        return self.hits >= MIN_HITS

    def update(self, box, cls, conf, now, color=None):
        w = max(self.box[2] - self.box[0], 1.0)
        h = max(self.box[3] - self.box[1], 1.0)

        dx = max(abs(box[0] - self.box[0]), abs(box[2] - self.box[2]))
        dy = max(abs(box[1] - self.box[1]), abs(box[3] - self.box[3]))

        # Zona muerta: si el cambio es minimo (ruido), la caja NO se mueve.
        if dx > DEADBAND * w or dy > DEADBAND * h:
            self.box = [
                BOX_ALPHA * n + (1.0 - BOX_ALPHA) * o
                for n, o in zip(box, self.box)
            ]

        self._conf = CONF_ALPHA * conf + (1.0 - CONF_ALPHA) * self._conf

        for k in self.class_scores:
            self.class_scores[k] *= CLASS_DECAY
        self.class_scores[cls] = self.class_scores.get(cls, 0.0) + conf

        # Solo se vota cuando hubo un color claro: un fotograma dudoso no borra
        # lo que ya se sabia.
        if color is not None:
            for k in self.color_scores:
                self.color_scores[k] *= VINYL_VOTES_DECAY
            self.color_scores[color] = self.color_scores.get(color, 0.0) + 1.0

        self.hits += 1
        self.last_seen = now


class Tracker:
    def __init__(self, dup_params=None):
        self.tracks = []
        self.dup_params = dup_params

    def update(self, detections, now, conf_start, interval_s=0.0):
        # Emparejar detecciones con tracks por IoU (greedy, mayor IoU primero)
        pairs = []
        for ti, track in enumerate(self.tracks):
            for di, det in enumerate(detections):
                match_score = track_match_score(track, det)
                if match_score is not None:
                    pairs.append((match_score, ti, di))

        pairs.sort(reverse=True)

        used_tracks = set()
        used_dets = set()

        for iou, ti, di in pairs:
            if ti in used_tracks or di in used_dets:
                continue

            det = detections[di]
            self.tracks[ti].update(det.box, det.cls, det.conf, now, det.color)
            used_tracks.add(ti)
            used_dets.add(di)

        # Detecciones sin track: solo nace uno si la confianza es alta
        for di, det in enumerate(detections):
            if di in used_dets:
                continue
            if det.conf >= conf_start:
                self.tracks.append(Track(det.box, det.cls, det.conf, now, det.color))

        # Con intervalos largos entre fotogramas, la vida de un track debe
        # cubrir varios ciclos o parpadeara.
        grace = 2.5 * interval_s
        alive = []
        for track in self.tracks:
            base = MAX_AGE_S if track.confirmed else UNCONFIRMED_AGE_S
            if now - track.last_seen <= max(base, grace):
                alive.append(track)
        self.tracks = alive

        confirmed = [track for track in self.tracks if track.confirmed]
        unique_confirmed = suppress_duplicates(confirmed, self.dup_params)
        keep_ids = {track.id for track in unique_confirmed}
        self.tracks = [
            track for track in self.tracks
            if not track.confirmed or track.id in keep_ids
        ]
        return unique_confirmed

# =====================================================
# ESTADO DE LAS CAMARAS
# =====================================================


def new_camera_state(source):
    return {
        "source": source,
        "cap": None,
        "latest_frame": None,
        "frame_id": 0,
        "last_processed_id": -1,
        "last_infer_t": 0.0,
        "last_capture_t": 0.0,
        "detections": [],
        "blocked_count": 0,
        "inference_ms": 0.0,
        "last_updated": None,
        "connected": False,
        "error": None,
        "tracker": Tracker(),
        "people_tracker": Tracker(DUP_PEOPLE),
        "people_detections": [],
        "probe": None,
    }


def resolve_source(source):
    """Resuelve URLs de red o la referencia 'env:VARIABLE'."""
    if isinstance(source, str) and source.startswith("env:"):
        var = source[4:]
        value = os.environ.get(var)
        if not value:
            print(f"AVISO: la variable de entorno {var} no esta definida.")
            print(CAMERA_URL_HELP)
        return value or None
    if not isinstance(source, str):
        return None
    if not is_network_camera_source(source):
        return None
    return source


def build_cameras(cfg):
    result = {}
    for cam in cfg["cameras"]:
        if not cam.get("enabled", True):
            continue
        source = resolve_source(cam["source"])
        if source is None:
            print(f"AVISO: camara '{cam['name']}' sin fuente valida; se omite.")
            continue
        result[cam["name"]] = new_camera_state(source)
    return result


cameras = build_cameras(CFG)

lock = threading.Lock()
stop_event = threading.Event()
zone_generation = 0


def reset_camera_results(state, full=False):
    """Descarta trackers y resultados de una camara (cambio de zona o de reglas)."""
    state["tracker"] = Tracker()
    state["people_tracker"] = Tracker(DUP_PEOPLE)
    state["detections"] = []
    state["people_detections"] = []
    state["blocked_count"] = 0
    state["last_updated"] = None
    if full:
        state["last_processed_id"] = -1
        state["last_infer_t"] = 0.0


def apply_class_rule(zone_name, class_name, status):
    global ZONE_RULES
    with lock, ZONE_RULES_LOCK:
        if not set_zone_class_rule(CFG, zone_name, class_name, status):
            return False
        ZONE_RULES = build_zone_rules(CFG)
        if zone_name == SETTINGS.get("zone"):
            for state in cameras.values():
                reset_camera_results(state)
    SETTINGS.mark_dirty()
    return True


def change_zone(zone_name):
    """Cambia de zona y reinicia los trackers (descarta objetos de la anterior)."""
    global zone_generation
    if zone_name not in ZONE_RULES:
        return
    with lock:
        if zone_name == SETTINGS.get("zone"):
            return
        SETTINGS.set("zone", zone_name)
        zone_generation += 1
        for state in cameras.values():
            reset_camera_results(state, full=True)
    print(f"Zona activa: {zone_name}")


def publish_camera_detections(
    state, zone_name, generation, detections, blocked, elapsed, live, interval_s,
    person_detections=(), context=()
):
    with lock:
        if zone_generation != generation or SETTINGS.get("zone") != zone_name:
            return False

        now = time.time()
        stable_people = state["people_tracker"].update(
            person_detections,
            now,
            CFG["people_model"]["person_confidence"],
            interval_s,
        )
        stable = state["tracker"].update(
            detections, now, live["confidence_start"], interval_s
        )

        show_confidence = live.get("show_confidence", True)
        new_detections = []
        for track in stable:
            if not class_allowed(track.cls, zone_name):
                continue
            display_name = track.cls.replace("chasis_", "")
            vinyl_color = None
            if vinyl_enabled_in(zone_name) and is_vinyl_class(track.cls):
                vinyl_color = track.color
                display_name += f" [{vinyl_color or 'color ?'}]"
            x1, y1, x2, y2 = map(int, track.box)
            if show_confidence:
                label = f"{display_name} {track.conf * 100:.0f}%"
            else:
                label = display_name
            new_detections.append(
                DisplayDetection(
                    (x1, y1, x2, y2),
                    label,
                    track.cls,
                    vinyl_color,
                    track.conf,
                )
            )

        state["detections"] = apply_composite_rules(
            new_detections,
            CFG.get("composite_rules", []),
            show_confidence,
            context,
            COMPOSITE_CONTAINMENT,
        )
        state["people_detections"] = build_people_detections(
            stable_people, show_confidence
        )
        state["blocked_count"] = blocked
        state["inference_ms"] = elapsed
        state["last_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
        return True


# =====================================================
# GUARDAR FOTOGRAMAS (para reetiquetar y reentrenar)
# =====================================================


def save_training_frame(frame, camera_name, tag):
    """Guarda un fotograma SIN dibujos en la carpeta de capturas."""
    folder = os.path.join(BASE_DIR, CFG["dataset_capture"]["folder"])
    try:
        os.makedirs(folder, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        millis = int((time.time() % 1) * 1000)
        safe_name = "".join(c if c.isalnum() else "_" for c in camera_name)
        path = os.path.join(folder, f"{safe_name}_{stamp}_{millis:03d}_{tag}.jpg")
        if cv2.imwrite(path, frame, [cv2.IMWRITE_JPEG_QUALITY, 92]):
            return path
    except OSError as error:
        print(f"AVISO: no se pudo guardar el fotograma: {error}")
    return None


def dataset_folder_full():
    folder = os.path.join(BASE_DIR, CFG["dataset_capture"]["folder"])
    limit = int(CFG["dataset_capture"].get("max_files", 3000))
    try:
        return len(os.listdir(folder)) >= limit
    except OSError:
        return False


# =====================================================
# MEDIR COLOR CON UN CLIC (calibracion del vinilo)
# =====================================================


def camera_mouse_callback(event, x, y, flags, camera_name):
    if event != cv2.EVENT_LBUTTONDOWN:
        return

    radius = 4
    with lock:
        state = cameras[camera_name]
        frame = state["latest_frame"]
        if frame is None:
            return
        frame_h, frame_w = frame.shape[:2]
        px = min(max(int(x), 0), frame_w - 1)
        py = min(max(int(y), 0), frame_h - 1)
        patch = frame[
            max(0, py - radius):py + radius + 1,
            max(0, px - radius):px + radius + 1,
        ].copy()

    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV).reshape(-1, 3)
    h, s, v = (int(value) for value in np.median(hsv, axis=0))
    name, distance = nearest_vinyl_color((h, s, v))
    text = f"Clic ({px},{py}) HSV=[{h}, {s}, {v}]"
    if name is not None:
        verdict = "OK" if distance <= VINYL_TOLERANCE else "FUERA de tolerancia"
        text += f" -> mas cercano: {name} (dist {distance:.1f}, {verdict})"
    print(text)
    with lock:
        cameras[camera_name]["probe"] = (text, time.time())


# =====================================================
# ABRIR CAMARAS
# =====================================================


def open_capture(source):
    """Abre una fuente de video; devuelve el VideoCapture o None si falla."""
    if source.lower().startswith(("rtsp://", "rtsps://")):
        cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG)
        if not cap.isOpened():
            cap.release()
            cap = cv2.VideoCapture(source)
    else:
        cap = cv2.VideoCapture(source)

    if not cap.isOpened():
        cap.release()
        return None

    # Buffer minimo en todas las fuentes: menos latencia / frames viejos
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return cap


def open_cameras():
    for name, state in cameras.items():
        print(f"\nAbriendo: {name}")

        cap = open_capture(state["source"])
        if cap is None:
            print(f"ERROR: No se pudo abrir {name}.")
            continue

        with lock:
            state["cap"] = cap
            state["connected"] = True
            state["error"] = None

        print(f"Camara abierta: {name}")

# =====================================================
# HILO DE CAPTURA PARA CADA CAMARA
# =====================================================

# Fotogramas por segundo que se convierten para mostrar en pantalla. El resto se
# descarta con grab() (se decodifica lo minimo para no acumular retraso).
DISPLAY_FPS = 25.0
RECONNECT_AFTER_FAILURES = 30
RECONNECT_MAX_WAIT_S = 15.0


def reconnect_camera(name, state, old_cap):
    """Reabre la camara con espera creciente. Devuelve el nuevo cap o None."""
    old_cap.release()
    wait = 1.0
    while not stop_event.is_set():
        print(f"Reconectando: {name} ...")
        cap = open_capture(state["source"])
        if cap is not None:
            with lock:
                state["cap"] = cap
                state["connected"] = True
                state["error"] = None
            print(f"Camara reconectada: {name}")
            return cap
        stop_event.wait(wait)
        wait = min(wait * 2, RECONNECT_MAX_WAIT_S)
    return None


def capture_loop(name):
    state = cameras[name]
    cap = state["cap"]

    if cap is None:
        return

    failures = 0
    last_retrieve = 0.0
    frame_period = 1.0 / DISPLAY_FPS

    while not stop_event.is_set():
        frame = None
        if cap.grab():
            now = time.time()
            if now - last_retrieve < frame_period:
                failures = 0
                continue
            ok, frame = cap.retrieve()
            if ok and frame is not None:
                last_retrieve = now
            else:
                frame = None

        if frame is None:
            failures += 1

            if failures >= RECONNECT_AFTER_FAILURES:
                with lock:
                    state["connected"] = False
                    state["error"] = "Sin imagen de la camara"
                cap = reconnect_camera(name, state, cap)
                if cap is None:
                    return
                failures = 0
                continue

            time.sleep(0.05)
            continue

        failures = 0

        with lock:
            state["latest_frame"] = frame
            state["frame_id"] += 1
            state["connected"] = True
            state["error"] = None

# =====================================================
# HILO DE INFERENCIA YOLO
# =====================================================


def inference_loop():
    # Un solo hilo usa los modelos compartidos.
    capture_cfg = CFG["dataset_capture"]

    while not stop_event.is_set():

        processed_any = False
        live = SETTINGS.snapshot()
        interval_s = live["interval_ms"] / 1000.0

        for name, state in cameras.items():

            now = time.time()

            with lock:
                zone = SETTINGS.get("zone")
                generation = zone_generation
                if state["latest_frame"] is None:
                    continue

                if state["frame_id"] == state["last_processed_id"]:
                    continue

                # Intervalo configurado: se salta el fotograma si es pronto
                if interval_s > 0 and now - state["last_infer_t"] < interval_s:
                    continue

                frame = state["latest_frame"].copy()
                state["last_processed_id"] = state["frame_id"]
                state["last_infer_t"] = now

            processed_any = True
            start = time.perf_counter()

            try:
                # El color del vinilo se mide en la imagen ORIGINAL; los ajustes
                # de brillo/gamma/etc. solo se aplican a lo que ve el modelo.
                source_frame = frame
                model_frame = adjust_image(frame, live)

                frame_h, frame_w = model_frame.shape[:2]
                min_area = MIN_BOX_AREA_RATIO * frame_w * frame_h

                # Se infiere con el umbral BAJO; el alto solo crea objetos.
                result = model.predict(
                    source=model_frame,
                    imgsz=IMAGE_SIZE,
                    conf=live["confidence_keep"],
                    iou=0.60,
                    agnostic_nms=False,
                    verbose=False,
                    **PREDICT_EXTRA
                )[0]

                people_result = people_model.predict(
                    source=model_frame,
                    imgsz=PEOPLE_IMAGE_SIZE,
                    conf=PERSON_CONFIDENCE,
                    iou=0.60,
                    classes=[PERSON_CLASS_ID],
                    verbose=False,
                    **PREDICT_EXTRA
                )[0]

                candidates = []
                if result.boxes is not None:
                    for box in result.boxes:
                        x1, y1, x2, y2 = box.xyxy[0].tolist()

                        if (x2 - x1) * (y2 - y1) < min_area:
                            continue

                        candidates.append(
                            Det(
                                (x1, y1, x2, y2),
                                model.names[int(box.cls[0])],
                                float(box.conf[0]),
                            )
                        )

                raw_people = extract_people(
                    people_result, PERSON_CLASS_ID, PERSON_CONFIDENCE
                )

                # 1) fuera lo que en realidad es una persona
                candidates = exclude_detections_matching_people(
                    candidates, raw_people, CFG["people_model"]
                )
                # 2) duplicados entre TODAS las clases (antes de filtrar por zona:
                #    una clase prohibida fuerte tapa a una permitida debil)
                all_clean = suppress_duplicates(candidates)

                # 3) filtro por zona
                clean = []
                blocked_dets = []
                for det in all_clean:
                    if class_allowed(det.cls, zone):
                        clean.append(det)
                    else:
                        blocked_dets.append(det)

                # 4) el color solo se mide en los chasis vinilados que quedan
                if vinyl_enabled_in(zone):
                    clean = [
                        det._replace(
                            color=classify_vinyl_color(source_frame, det.box)
                        ) if is_vinyl_class(det.cls) else det
                        for det in clean
                    ]

                # Piezas que la zona oculta: solo sirven para vetar reglas exclusivas
                context = [
                    DisplayDetection(tuple(det.box), det.cls, det.cls, None, det.conf)
                    for det in blocked_dets
                    if det.conf >= live["confidence_start"]
                ]
                clean_people = suppress_duplicates(raw_people, DUP_PEOPLE)

                # Fotogramas dudosos para reetiquetar (apagado por defecto)
                if (
                    capture_cfg.get("enabled")
                    and now - state["last_capture_t"] >= capture_cfg["min_interval_s"]
                ):
                    uncertain = [
                        det for det in all_clean
                        if capture_cfg["low_conf"] <= det.conf < capture_cfg["high_conf"]
                    ]
                    if uncertain and not dataset_folder_full():
                        if save_training_frame(source_frame, name, "dudoso"):
                            state["last_capture_t"] = now

                elapsed = (time.perf_counter() - start) * 1000

                publish_camera_detections(
                    state,
                    zone,
                    generation,
                    clean,
                    len(blocked_dets),
                    elapsed,
                    live,
                    interval_s,
                    clean_people,
                    context,
                )

            except Exception as error:
                print(f"Error YOLO en {name}: {error}")
                time.sleep(0.05)

        if not processed_any:
            time.sleep(0.02)

# =====================================================
# DIBUJAR RESULTADOS
# =====================================================


def put_text(frame, text, y, color=(0, 255, 255)):
    cv2.putText(
        frame, text, (15, y), cv2.FONT_HERSHEY_SIMPLEX,
        0.65, color, 2, cv2.LINE_AA
    )


def summarize_detections(detections_by_camera):
    detections = [
        detection
        for camera_detections in detections_by_camera.values()
        for detection in camera_detections
    ]
    machines = [
        detection
        for detection in detections
        if detection.class_name.startswith("chasis_")
    ]
    vinyls = [
        detection for detection in detections
        if is_vinyl_class(detection.class_name)
    ]
    color_counts = {
        color: sum(detection.color == color for detection in vinyls)
        for color in VINYL_COLOR_NAMES
    }
    color_counts["sin identificar"] = len(vinyls) - sum(color_counts.values())
    return {
        "total_detections": len(detections),
        "machine_count": len(machines),
        "vinyl_count": len(vinyls),
        "color_counts": color_counts,
    }


def draw_summary_panel(camera_snapshots):
    detections_by_camera = {
        name: snapshot["detections"]
        for name, snapshot in camera_snapshots.items()
    }
    summary = summarize_detections(detections_by_camera)
    person_count = sum(
        len(snapshot.get("people", []))
        for snapshot in camera_snapshots.values()
    )
    panel_height = max(260, 215 + 30 * len(camera_snapshots))
    panel = np.full((panel_height, 760, 3), (28, 35, 44), np.uint8)

    def line(text, y, scale, color, thickness=1):
        cv2.putText(
            panel, text, (22, y), cv2.FONT_HERSHEY_SIMPLEX,
            scale, color, thickness, cv2.LINE_AA
        )

    line("RESUMEN DE DETECCIONES", 32, 0.72, (126, 231, 205), 2)
    line(f"Maquinas visibles ahora: {summary['machine_count']}",
         70, 0.58, (240, 244, 246))
    colors_text = " | ".join(
        f"{color}: {count}"
        for color, count in summary["color_counts"].items()
    )
    line(f"Vinilados ({summary['vinyl_count']}) por color: {colors_text}",
         102, 0.46, (213, 221, 226))
    line(f"Detecciones visibles ahora: {summary['total_detections']}",
         134, 0.52, (240, 244, 246))
    line(f"Personas visibles ahora (suma de camaras): {person_count}",
         166, 0.52, (106, 205, 255))

    y = 202
    for name, snapshot in camera_snapshots.items():
        status = "Live" if snapshot["connected"] else "SIN SENAL"
        updated = snapshot["last_updated"] or "Sin inferencias"
        text = (
            f"{name}: {status} | Personas: {len(snapshot.get('people', []))} "
            f"| {updated}"
        )
        line(text[:100], y, 0.42, (185, 198, 207))
        y += 30

    cv2.imshow("Resumen de detecciones", panel)


def draw_overlay(frame, name, detections, inference_ms, connected,
                 zone, blocked_count, dirty, people=(), probe_text=None,
                 interval_ms=None):

    for detection in detections:
        x1, y1, x2, y2 = detection.box
        label = detection.label
        box_color = VINYL_BOX_BGR.get(detection.color, (0, 255, 0))

        cv2.rectangle(frame, (x1, y1), (x2, y2), box_color, 2)

        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.65
        thickness = 2

        (tw, th), baseline = cv2.getTextSize(
            label, font, font_scale, thickness
        )

        text_y = max(y1, th + baseline + 8)

        cv2.rectangle(
            frame,
            (x1, text_y - th - baseline - 8),
            (x1 + tw + 8, text_y),
            box_color,
            -1
        )

        cv2.putText(
            frame, label, (x1 + 4, text_y - 5), font,
            font_scale, (0, 0, 0), thickness, cv2.LINE_AA
        )

    for person in people:
        x1, y1, x2, y2 = person.box
        label = person.label
        color = (255, 190, 60)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        font = cv2.FONT_HERSHEY_SIMPLEX
        (text_width, text_height), baseline = cv2.getTextSize(
            label, font, 0.55, 2
        )
        text_y = max(y1, text_height + baseline + 8)
        cv2.rectangle(
            frame,
            (x1, text_y - text_height - baseline - 8),
            (x1 + text_width + 8, text_y),
            color,
            -1,
        )
        cv2.putText(
            frame, label, (x1 + 4, text_y - 5), font,
            0.55, (0, 0, 0), 2, cv2.LINE_AA
        )

    status = "Live" if connected else "SIN SENAL"

    put_text(frame, f"{name} | {status}", 28,
             (0, 255, 255) if connected else (0, 0, 255))
    speed = f"YOLO: {inference_ms:.0f} ms"
    if interval_ms:
        speed += f" | 1 fotograma cada {interval_ms / 1000:.1f} s"
    put_text(frame, speed, 58)
    put_text(frame, f"Detecciones: {len(detections)}", 88)

    zone_txt = f"Zona: {zone}"
    if blocked_count:
        zone_txt += f" (bloqueadas: {blocked_count})"
    zone_txt += " | color " + ("ON" if vinyl_enabled_in(zone) else "OFF")
    put_text(frame, zone_txt, 118, (255, 200, 0))

    hint = "M: menu | V: color | P: foto | clic: medir"
    if dirty:
        hint += " | cambios sin guardar (G)"
    put_text(frame, hint, 148, (200, 200, 200))

    if probe_text:
        cv2.putText(
            frame, probe_text, (15, frame.shape[0] - 16),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2, cv2.LINE_AA
        )

    return frame

# =====================================================
# MENU DE AJUSTES (tecla M)
# =====================================================


class AdminMenu:
    WIN = "Ajustes"
    WIDTH = 1040
    HEIGHT = 980          # más alto para acomodar los 4 toggles sin solapamiento
    CLASS_ROW_HEIGHT = 32
    CLASS_LIST_TOP = 620  # baja para dejar espacio a la sección 02 ampliada
    CLASS_VISIBLE = 9
    SETTINGS_TOP = 256
    SETTINGS_ROW_HEIGHT = 38
    SLIDER_WIDTH = 208
    TOGGLES_TOP = 418     # primera fila de toggles (justo bajo los sliders)
    TOGGLE_ROW_H = 40     # altura de cada fila de toggles
    TOGGLE_BTN_W = 310    # ancho de cada botón toggle
    SECTION02_BOTTOM = 510  # borde inferior del card de sección 02
    SECTION03_TOP = 522     # borde superior del card de sección 03
    RULE_BUTTONS = (
        ("allow", "PERMITIR", 704, (62, 120, 87)),
        ("block", "BLOQUEAR", 810, (82, 77, 134)),
        ("none", "QUITAR", 916, (70, 79, 91)),
    )
    # (key, label) — posición calculada dinámicamente en draw()
    TOGGLE_BUTTONS = (
        ("clahe",            "CLAHE"),
        ("white_balance",    "BALANCE BLANCOS"),
        ("apply_to_preview", "AJUSTE EN VISTA"),
        ("show_confidence",  "MOSTRAR CONFIANZA"),
    )
    ZONE_BUTTONS = []
    COMPOSITE_RULE_VISIBLE = 6
    COMPOSITE_CLASS_VISIBLE = 12

    # (etiqueta, clave, valor minimo, valor maximo, paso, formato)
    CONTROLS = [
        ("Confianza crear", "confidence_start", 0.05, 0.99, 0.01, "percent"),
        ("Confianza mantener", "confidence_keep", 0.05, 0.99, 0.01, "percent"),
        ("Brillo", "brightness", -100, 100, 1, "integer"),
        ("Contraste", "contrast", 0.1, 3.0, 0.05, "decimal"),
        ("Gamma", "gamma", 0.1, 3.0, 0.05, "decimal"),
        ("Saturacion", "saturation", 0.0, 3.0, 0.05, "decimal"),
        ("Intervalo", "interval_ms", 200, 2000, 100, "milliseconds"),
    ]

    def __init__(self, settings):
        self.settings = settings
        self.is_open = False
        self._building = False
        self.edit_zone = settings.get("zone")
        self.class_index = 0
        self.class_offset = 0
        self.dragging_control = None
        self.selected_control = None
        self.ZONE_BUTTONS = []
        self.RULE_HITBOXES = []
        self.TOGGLE_HITBOXES = []
        self.show_composite_rules = False
        self.composite_name = ""
        self.composite_name_active = False
        self.composite_parent = MODEL_CLASSES[0] if MODEL_CLASSES else ""
        self.composite_children = set()
        self.composite_exclusive = True
        self.composite_hide_components = True
        self.composite_class_role = "parent"
        self.composite_class_offset = 0
        self.composite_rule_offset = 0
        self.composite_edit_index = None
        self.COMPOSITE_RULE_HITBOXES = []
        self.COMPOSITE_RULE_PAGE_HITBOXES = []
        self.COMPOSITE_CLASS_HITBOXES = []
        self.COMPOSITE_ROLE_HITBOXES = []
        self.COMPOSITE_ACTION_HITBOXES = []
        self.COMPOSITE_EXCLUSIVE_HITBOX = None
        self.COMPOSITE_HIDE_HITBOX = None
        self.COMPOSITE_NAME_HITBOX = None

    def open(self):
        if self.is_open:
            return
        cv2.namedWindow(self.WIN, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(self.WIN, self.WIDTH, self.HEIGHT)
        cv2.setMouseCallback(self.WIN, self._on_mouse)
        self.is_open = True

    def close(self):
        if self.is_open:
            cv2.destroyWindow(self.WIN)
            self.is_open = False

    def toggle(self):
        self.close() if self.is_open else self.open()

    @staticmethod
    def _format_control_value(value, format_name):
        if format_name == "percent":
            return f"{value * 100:.0f}%"
        if format_name == "milliseconds":
            return f"{value:.0f} ms"
        if format_name == "decimal":
            return f"{value:.2f}"
        return f"{value:.0f}"

    def _control_geometry(self, index):
        row, column = divmod(index, 2)
        column_left = 24 + column * 496
        y = self.SETTINGS_TOP + row * self.SETTINGS_ROW_HEIGHT
        label_x = column_left + 8
        track_x1 = column_left + 174
        track_x2 = track_x1 + self.SLIDER_WIDTH
        value_x = track_x2 + 12
        return label_x, y, track_x1, track_x2, value_x

    def _set_control_from_x(self, index, x):
        _, _, x1, x2, _ = self._control_geometry(index)
        _, key, minimum, maximum, step, _ = self.CONTROLS[index]
        ratio = min(max((x - x1) / (x2 - x1), 0.0), 1.0)
        value = minimum + ratio * (maximum - minimum)
        value = minimum + round((value - minimum) / step) * step
        self.settings.set(key, round(min(max(value, minimum), maximum), 4))

    def _select_class(self, offset):
        if not MODEL_CLASSES:
            return
        self.class_index = (self.class_index + offset) % len(MODEL_CLASSES)
        if self.class_index < self.class_offset:
            self.class_offset = self.class_index
        elif self.class_index >= self.class_offset + self.CLASS_VISIBLE:
            self.class_offset = self.class_index - self.CLASS_VISIBLE + 1

    def _set_rule(self, status):
        if not MODEL_CLASSES:
            return
        apply_class_rule(
            self.edit_zone, MODEL_CLASSES[self.class_index], status
        )

    def _new_composite_rule(self):
        self.composite_name = ""
        self.composite_name_active = True
        self.composite_parent = MODEL_CLASSES[0] if MODEL_CLASSES else ""
        self.composite_children = set()
        self.composite_exclusive = True
        self.composite_hide_components = True
        self.composite_class_role = "parent"
        self.composite_edit_index = None

    def _load_composite_rule(self, index):
        rules = CFG.get("composite_rules", [])
        if not 0 <= index < len(rules):
            return
        rule = rules[index]
        self.composite_name = str(rule.get("name", ""))
        self.composite_parent = str(rule.get("parent_class", ""))
        self.composite_children = set(rule.get("required_classes", []))
        self.composite_exclusive = bool(rule.get("exclusive", False))
        self.composite_hide_components = bool(rule.get("hide_components", True))
        self.composite_class_role = "children"
        self.composite_edit_index = index
        self.composite_name_active = False

    def _save_composite_rule(self):
        name = self.composite_name.strip()
        if not name or not self.composite_parent or not self.composite_children:
            print("AVISO: indica un nombre, una clase base y al menos un componente.")
            return False
        if (
            self.composite_parent not in MODEL_CLASSES
            or not self.composite_children.issubset(MODEL_CLASSES)
            or self.composite_parent in self.composite_children
        ):
            print("AVISO: las clases de la regla deben existir y ser distintas.")
            return False

        rule = {
            "name": name,
            "parent_class": self.composite_parent,
            "required_classes": [
                class_name for class_name in MODEL_CLASSES
                if class_name in self.composite_children
            ],
            "exclusive": self.composite_exclusive,
            "hide_components": self.composite_hide_components,
        }
        with lock:
            rules = CFG.setdefault("composite_rules", [])
            if self.composite_edit_index is not None and (
                self.composite_edit_index < len(rules)
            ):
                rules[self.composite_edit_index] = rule
                saved_index = self.composite_edit_index
            else:
                rules.append(rule)
                saved_index = len(rules) - 1
            for state in cameras.values():
                state["detections"] = []
        if not (
            self.composite_rule_offset <= saved_index
            < self.composite_rule_offset + self.COMPOSITE_RULE_VISIBLE
        ):
            self.composite_rule_offset = min(
                saved_index,
                max(0, len(CFG["composite_rules"]) - self.COMPOSITE_RULE_VISIBLE),
            )
        self.composite_edit_index = saved_index
        self.composite_name_active = False
        self.settings.mark_dirty()
        print(f"Regla compuesta guardada: {name}. Pulsa G para guardar config.json.")
        return True

    def _delete_composite_rule(self):
        if self.composite_edit_index is None:
            return
        with lock:
            rules = CFG.get("composite_rules", [])
            if not 0 <= self.composite_edit_index < len(rules):
                return
            removed = rules.pop(self.composite_edit_index)
            for state in cameras.values():
                state["detections"] = []
        self.composite_edit_index = None
        self.composite_rule_offset = min(
            self.composite_rule_offset,
            max(0, len(CFG.get("composite_rules", [])) - self.COMPOSITE_RULE_VISIBLE),
        )
        self.settings.mark_dirty()
        print(f"Regla compuesta eliminada: {removed.get('name', '')}. Pulsa G para guardar.")

    def _on_mouse(self, *event_data):
        event, x, y = event_data[:3]
        flags = event_data[3] if len(event_data) > 3 else 0
        if event == cv2.EVENT_LBUTTONUP:
            self.dragging_control = None
            return
        if event == cv2.EVENT_MOUSEMOVE:
            if self.dragging_control is not None and flags & cv2.EVENT_FLAG_LBUTTON:
                self._set_control_from_x(self.dragging_control, x)
            return
        if event != cv2.EVENT_LBUTTONDOWN:
            return
        self.dragging_control = None

        if self.show_composite_rules:
            if self.COMPOSITE_NAME_HITBOX and self._inside(
                x, y, self.COMPOSITE_NAME_HITBOX
            ):
                self.composite_name_active = True
                return
            self.composite_name_active = False
            for index, bounds in self.COMPOSITE_RULE_HITBOXES:
                if self._inside(x, y, bounds):
                    self._load_composite_rule(index)
                    return
            for direction, bounds in self.COMPOSITE_RULE_PAGE_HITBOXES:
                if self._inside(x, y, bounds):
                    self._scroll_composite_rules(direction)
                    return
            for role, bounds in self.COMPOSITE_ROLE_HITBOXES:
                if self._inside(x, y, bounds):
                    self.composite_class_role = role
                    return
            for class_name, bounds in self.COMPOSITE_CLASS_HITBOXES:
                if self._inside(x, y, bounds):
                    if self.composite_class_role == "parent":
                        self.composite_parent = class_name
                        self.composite_children.discard(class_name)
                    elif class_name == self.composite_parent:
                        print("AVISO: la clase base no puede ser tambien un componente.")
                    elif class_name in self.composite_children:
                        self.composite_children.remove(class_name)
                    else:
                        self.composite_children.add(class_name)
                    return
            if self.COMPOSITE_EXCLUSIVE_HITBOX and self._inside(
                x, y, self.COMPOSITE_EXCLUSIVE_HITBOX
            ):
                self.composite_exclusive = not self.composite_exclusive
                return
            if self.COMPOSITE_HIDE_HITBOX and self._inside(
                x, y, self.COMPOSITE_HIDE_HITBOX
            ):
                self.composite_hide_components = not self.composite_hide_components
                return
            for action, bounds in self.COMPOSITE_ACTION_HITBOXES:
                if self._inside(x, y, bounds):
                    if action == "new":
                        self._new_composite_rule()
                    elif action == "save":
                        self._save_composite_rule()
                    elif action == "delete":
                        self._delete_composite_rule()
                    elif action == "back":
                        self.show_composite_rules = False
                    return
            self.composite_name_active = False
            return

        for zone_name, x1, y1, x2, y2 in self.ZONE_BUTTONS:
            if x1 <= x <= x2 and y1 <= y <= y2:
                self.edit_zone = zone_name
                change_zone(zone_name)
                return

        for key, x1, y1, x2, y2 in self.TOGGLE_HITBOXES:
            if x1 <= x <= x2 and y1 <= y <= y2:
                enabled = not self.settings.get(key)
                self.settings.set(key, enabled)
                return

        for index in range(len(self.CONTROLS)):
            _, control_y, x1, x2, _ = self._control_geometry(index)
            if control_y - 10 <= y <= control_y + 26 and x1 - 8 <= x <= x2 + 8:
                self.dragging_control = index
                self.selected_control = index
                self._set_control_from_x(index, x)
                return

        for zone_name, button, x1, y1, x2, y2 in self.RULE_HITBOXES:
            if x1 <= x <= x2 and y1 <= y <= y2:
                self.edit_zone = zone_name
                row = (y1 - self.CLASS_LIST_TOP) // self.CLASS_ROW_HEIGHT
                class_index = self.class_offset + row
                if class_index < len(MODEL_CLASSES):
                    self.class_index = class_index
                    apply_class_rule(zone_name, MODEL_CLASSES[class_index], button)
                return

        row = (y - self.CLASS_LIST_TOP) // self.CLASS_ROW_HEIGHT
        index = self.class_offset + row
        if 0 <= row < self.CLASS_VISIBLE and index < len(MODEL_CLASSES):
            self.class_index = index

    @staticmethod
    def _inside(x, y, bounds):
        x1, y1, x2, y2 = bounds
        return x1 <= x <= x2 and y1 <= y <= y2

    def _scroll_composite_rules(self, direction):
        rules = CFG.get("composite_rules", [])
        self.composite_rule_offset = min(
            max(self.composite_rule_offset + direction, 0),
            max(0, len(rules) - self.COMPOSITE_RULE_VISIBLE),
        )

    def handle_key(self, key):
        if not self.is_open:
            return False
        if self.show_composite_rules:
            if self.composite_name_active:
                if key in (8, 127):
                    self.composite_name = self.composite_name[:-1]
                elif key == 13:
                    self._save_composite_rule()
                elif 32 <= key <= 126 and len(self.composite_name) < 60:
                    self.composite_name += chr(key)
                return True
            if key == ord("f"):
                self.show_composite_rules = False
            elif key == ord("n"):
                self._new_composite_rule()
            elif key == ord("s"):
                self._save_composite_rule()
            elif key in (ord("]"), ord("k")):
                self.composite_class_offset = min(
                    self.composite_class_offset + 1,
                    max(0, len(MODEL_CLASSES) - self.COMPOSITE_CLASS_VISIBLE),
                )
            elif key in (ord("["), ord("j")):
                self.composite_class_offset = max(0, self.composite_class_offset - 1)
            elif key == ord(","):
                self._scroll_composite_rules(-1)
            elif key == ord("."):
                self._scroll_composite_rules(1)
            else:
                return False
            return True
        if key == ord("f"):
            self.show_composite_rules = True
            self._new_composite_rule()
            return True
        if key == ord("a"):
            self._set_rule("allow")
        elif key == ord("b"):
            self._set_rule("block")
        elif key == ord("n"):
            self._set_rule("none")
        elif key == ord("]"):
            self._select_class(1)
        elif key == ord("["):
            self._select_class(-1)
        elif key == ord("k"):
            self._select_class(1)
        elif key == ord("j"):
            self._select_class(-1)
        elif key in (ord("+"), ord("=")):
            self._nudge_selected_control(1)
        elif key == ord("-"):
            self._nudge_selected_control(-1)
        else:
            return False
        return True

    def _nudge_selected_control(self, direction):
        if self.selected_control is None:
            return
        _, key, minimum, maximum, step, _ = self.CONTROLS[self.selected_control]
        self.settings.set(
            key,
            min(max(self.settings.get(key) + direction * step, minimum), maximum),
        )

    def draw(self, dirty):
        if not self.is_open:
            return
        panel = np.full((self.HEIGHT, self.WIDTH, 3), (23, 28, 37), np.uint8)
        if self.show_composite_rules:
            self._draw_composite_rules(panel, dirty)
            cv2.imshow(self.WIN, panel)
            return
        cv2.rectangle(panel, (0, 0), (self.WIDTH, 78), (34, 43, 55), -1)
        cv2.rectangle(panel, (0, 77), (self.WIDTH, 80), (54, 194, 169), -1)
        title = "REGLAS DE DETECCION"
        if dirty:
            title += "  |  CAMBIOS SIN GUARDAR"
        cv2.putText(
            panel, title, (24, 35), cv2.FONT_HERSHEY_SIMPLEX,
            0.72, (126, 231, 205), 2, cv2.LINE_AA
        )
        cv2.putText(
            panel,
            "F: reglas compuestas | Ajusta imagen y reglas por zona.",
            (24, 62), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
            (205, 215, 224), 1, cv2.LINE_AA
        )

        live = self.settings.snapshot()
        self._draw_card(panel, (18, 91, self.WIDTH - 18, 205))
        self._draw_section_title(panel, "01  ZONAS", (30, 111))
        cv2.putText(
            panel, f"ACTIVA: {live['zone']}", (810, 111),
            cv2.FONT_HERSHEY_SIMPLEX, 0.43, (126, 231, 205), 1, cv2.LINE_AA
        )
        self.ZONE_BUTTONS = []
        zone_names = ZONE_NAMES[:8]
        button_width = 238
        for index, zone_name in enumerate(zone_names):
            row, column = divmod(index, 4)
            x1 = 30 + column * 247
            y1 = 121 + row * 39
            x2, y2 = x1 + button_width, y1 + 31
            selected = zone_name == self.edit_zone
            active = zone_name == live["zone"]
            fill = (49, 83, 75) if selected else (36, 44, 55)
            cv2.rectangle(panel, (x1, y1), (x2, y2), fill, -1)
            cv2.rectangle(
                panel, (x1, y1), (x2, y2),
                (72, 196, 160) if selected else (61, 75, 89), 1
            )
            cv2.putText(
                panel, zone_name, (x1 + 11, y1 + 21),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                (236, 243, 244), 1, cv2.LINE_AA
            )
            if active:
                cv2.circle(panel, (x2 - 13, y1 + 15), 4, (92, 218, 164), -1, cv2.LINE_AA)
            self.ZONE_BUTTONS.append((zone_name, x1, y1, x2, y2))

        self._draw_card(panel, (18, 216, self.WIDTH - 18, self.SECTION02_BOTTOM))
        self._draw_section_title(panel, "02  AJUSTES DE IMAGEN Y DETECCION", (30, 238))
        for index, control in enumerate(self.CONTROLS):
            label, key, minimum, maximum = control[:4]
            format_name = control[5]
            label_x, y, x1, x2, value_x = self._control_geometry(index)
            value = live[key]
            ratio = (value - minimum) / (maximum - minimum)
            knob_x = int(x1 + ratio * (x2 - x1))
            center_y = y + 15
            cv2.putText(
                panel, label, (label_x, y + 19), cv2.FONT_HERSHEY_SIMPLEX,
                0.39, (202, 212, 221), 1, cv2.LINE_AA
            )
            cv2.line(panel, (x1, center_y), (x2, center_y), (58, 72, 84), 4, cv2.LINE_AA)
            cv2.line(panel, (x1, center_y), (knob_x, center_y), (63, 193, 159), 4, cv2.LINE_AA)
            cv2.circle(panel, (knob_x, center_y), 7, (29, 37, 46), -1, cv2.LINE_AA)
            cv2.circle(panel, (knob_x, center_y), 5, (126, 231, 205), -1, cv2.LINE_AA)
            cv2.putText(
                panel, self._format_control_value(value, format_name),
                (value_x, y + 19), cv2.FONT_HERSHEY_SIMPLEX,
                0.39, (126, 231, 205), 1, cv2.LINE_AA
            )

        # --- Toggles: 3 columnas × 2 filas, con separador visual ---
        cv2.line(
            panel,
            (30, self.TOGGLES_TOP - 10),
            (self.WIDTH - 30, self.TOGGLES_TOP - 10),
            (47, 59, 71), 1
        )
        self.TOGGLE_HITBOXES = []
        col_xs = tuple(
            30 + column * (self.TOGGLE_BTN_W + 16)
            for column in range(3)
        )
        for t_index, (key, label) in enumerate(self.TOGGLE_BUTTONS):
            row, col = divmod(t_index, 3)
            bx1 = col_xs[col]
            by1 = self.TOGGLES_TOP + row * self.TOGGLE_ROW_H
            bx2 = bx1 + self.TOGGLE_BTN_W
            by2 = by1 + self.TOGGLE_ROW_H - 6
            enabled = bool(live[key])
            fill    = (44, 82, 71)    if enabled else (36, 44, 55)
            outline = (72, 196, 160)  if enabled else (61, 75, 89)
            cv2.rectangle(panel, (bx1, by1), (bx2, by2), fill, -1)
            cv2.rectangle(panel, (bx1, by1), (bx2, by2), outline, 1)
            # indicador circular
            dot_color = (92, 218, 164) if enabled else (109, 124, 137)
            cv2.circle(panel, (bx1 + 18, by1 + 17), 6, dot_color, -1, cv2.LINE_AA)
            cv2.putText(
                panel, label, (bx1 + 34, by1 + 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.40, (229, 236, 239), 1, cv2.LINE_AA
            )
            self.TOGGLE_HITBOXES.append((key, bx1, by1, bx2, by2))

        top = self.CLASS_LIST_TOP
        self._draw_card(panel, (18, self.SECTION03_TOP, self.WIDTH - 18, self.HEIGHT - 49))
        self._draw_section_title(panel, f"03  CLASES DE {self.edit_zone.upper()}", (30, self.SECTION03_TOP + 27))
        description = CFG["zones"][self.edit_zone]["description"]
        cv2.putText(
            panel, description[:115], (30, self.SECTION03_TOP + 49),
            cv2.FONT_HERSHEY_SIMPLEX, 0.38, (165, 181, 193), 1, cv2.LINE_AA
        )
        cv2.putText(
            panel, "CLASE", (34, top - 7),
            cv2.FONT_HERSHEY_SIMPLEX, 0.36, (133, 153, 167), 1, cv2.LINE_AA
        )
        cv2.putText(
            panel, "ESTADO", (445, top - 7),
            cv2.FONT_HERSHEY_SIMPLEX, 0.36, (133, 153, 167), 1, cv2.LINE_AA
        )
        for _, label, x1, _ in self.RULE_BUTTONS:
            cv2.putText(
                panel, label, (x1 + 7, top - 7),
                cv2.FONT_HERSHEY_SIMPLEX, 0.32, (133, 153, 167), 1, cv2.LINE_AA
            )

        self.RULE_HITBOXES = []
        visible_classes = MODEL_CLASSES[
            self.class_offset:self.class_offset + self.CLASS_VISIBLE
        ]
        for row, class_name in enumerate(visible_classes):
            y1 = top + row * self.CLASS_ROW_HEIGHT
            y2 = y1 + self.CLASS_ROW_HEIGHT - 2
            selected = class_name == MODEL_CLASSES[self.class_index]
            if selected:
                cv2.rectangle(panel, (24, y1), (self.WIDTH - 24, y2), (39, 54, 62), -1)
                cv2.rectangle(panel, (24, y1), (27, y2), (72, 196, 160), -1)
            elif row % 2 == 0:
                cv2.rectangle(panel, (24, y1), (self.WIDTH - 24, y2), (28, 35, 44), -1)
            cv2.rectangle(
                panel, (24, y2), (self.WIDTH - 24, y2 + 1), (46, 56, 67), -1
            )
            status = zone_class_status(CFG, self.edit_zone, class_name)
            status_color = {
                "ALLOWED": (103, 220, 157),
                "BLOCKED": (129, 127, 243),
                "EXCLUDED": (88, 179, 235),
                "NO RULE": (165, 178, 188),
            }[status]
            cv2.putText(
                panel, class_name[:48], (38, y1 + 21),
                cv2.FONT_HERSHEY_SIMPLEX, 0.42,
                (231, 238, 241), 1, cv2.LINE_AA
            )
            cv2.putText(
                panel, status.replace("_", " "), (445, y1 + 21),
                cv2.FONT_HERSHEY_SIMPLEX, 0.37, status_color, 1, cv2.LINE_AA
            )
            for rule, label, x1, color in self.RULE_BUTTONS:
                x2 = x1 + 98
                cv2.rectangle(panel, (x1, y1 + 3), (x2, y2 - 3), color, -1)
                cv2.rectangle(panel, (x1, y1 + 3), (x2, y2 - 3), color, 1)
                cv2.putText(
                    panel, label, (x1 + 8, y1 + 19),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.31,
                    (242, 246, 247), 1, cv2.LINE_AA
                )
                self.RULE_HITBOXES.append((self.edit_zone, rule, x1, y1, x2, y2))

        footer_y = self.HEIGHT - 22
        cv2.putText(
            panel,
            "ARRASTRA barras | +/- ajuste fino | A/B/N regla | J/K clase | G guardar",
            (24, footer_y), cv2.FONT_HERSHEY_SIMPLEX, 0.37,
            (177, 193, 204), 1, cv2.LINE_AA
        )
        if len(MODEL_CLASSES) > self.CLASS_VISIBLE:
            scroll = (
                f"{self.class_offset + 1}-"
                f"{min(self.class_offset + self.CLASS_VISIBLE, len(MODEL_CLASSES))}"
                f" de {len(MODEL_CLASSES)}"
            )
            cv2.putText(
                panel, scroll, (900, self.SECTION03_TOP + 49), cv2.FONT_HERSHEY_SIMPLEX,
                0.36, (133, 153, 167), 1, cv2.LINE_AA
            )
        cv2.imshow(self.WIN, panel)

    def _draw_composite_rules(self, panel, dirty):
            cv2.rectangle(panel, (0, 0), (self.WIDTH, 78), (34, 43, 55), -1)
            cv2.rectangle(panel, (0, 77), (self.WIDTH, 80), (54, 194, 169), -1)
            title = "REGLAS COMPUESTAS"
            if dirty:
                title += "  |  CAMBIOS SIN GUARDAR"
            cv2.putText(
                panel, title, (24, 35), cv2.FONT_HERSHEY_SIMPLEX,
                0.72, (126, 231, 205), 2, cv2.LINE_AA
            )
            cv2.putText(
                panel,
                "Etiqueta una clase base segun las clases detectadas dentro de su caja.",
                (24, 62), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                (205, 215, 224), 1, cv2.LINE_AA
            )

            self._draw_card(panel, (18, 91, self.WIDTH - 18, 384))
            self._draw_section_title(panel, "REGLAS GUARDADAS (clic para editar)", (30, 118))
            self.COMPOSITE_RULE_HITBOXES = []
            self.COMPOSITE_RULE_PAGE_HITBOXES = []
            rules = CFG.get("composite_rules", [])
            visible_rules = rules[
                self.composite_rule_offset:
                self.composite_rule_offset + self.COMPOSITE_RULE_VISIBLE
            ]
            for row, rule in enumerate(visible_rules):
                index = self.composite_rule_offset + row
                y1 = 132 + row * 38
                y2 = y1 + 33
                if index == self.composite_edit_index:
                    cv2.rectangle(panel, (28, y1), (self.WIDTH - 28, y2), (39, 54, 62), -1)
                components = ", ".join(rule.get("required_classes", []))
                condition = "exactos" if rule.get("exclusive", False) else "minimo"
                hidden = "oculta piezas" if rule.get("hide_components", True) else "muestra piezas"
                text = (
                    f"{rule.get('name', '')}: {rule.get('parent_class', '')} "
                    f"+ [{components}] ({condition}; {hidden})"
                )
                cv2.putText(
                    panel, text[:125], (38, y1 + 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.39, (231, 238, 241), 1, cv2.LINE_AA
                )
                self.COMPOSITE_RULE_HITBOXES.append(
                    (index, (28, y1, self.WIDTH - 28, y2))
                )
            if len(rules) > self.COMPOSITE_RULE_VISIBLE:
                cv2.putText(
                    panel,
                    f"{self.composite_rule_offset + 1}-"
                    f"{min(self.composite_rule_offset + self.COMPOSITE_RULE_VISIBLE, len(rules))}"
                    f" / {len(rules)}",
                    (746, 118), cv2.FONT_HERSHEY_SIMPLEX, 0.36,
                    (133, 153, 167), 1, cv2.LINE_AA
                )
                for direction, label, bounds in (
                    (-1, "<", (870, 98, 912, 125)),
                    (1, ">", (920, 98, 962, 125)),
                ):
                    cv2.rectangle(panel, bounds[:2], bounds[2:], (36, 44, 55), -1)
                    cv2.rectangle(panel, bounds[:2], bounds[2:], (61, 75, 89), 1)
                    cv2.putText(
                        panel, label, (bounds[0] + 15, bounds[1] + 19),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.42, (229, 236, 239), 1, cv2.LINE_AA
                    )
                    self.COMPOSITE_RULE_PAGE_HITBOXES.append((direction, bounds))

            self._draw_card(panel, (18, 396, self.WIDTH - 18, self.HEIGHT - 48))
            self._draw_section_title(panel, "CREAR O EDITAR REGLA", (30, 425))
            self.COMPOSITE_NAME_HITBOX = (30, 440, self.WIDTH - 30, 480)
            name_color = (72, 196, 160) if self.composite_name_active else (61, 75, 89)
            cv2.rectangle(panel, (30, 440), (self.WIDTH - 30, 480), (28, 35, 44), -1)
            cv2.rectangle(panel, (30, 440), (self.WIDTH - 30, 480), name_color, 1)
            name_text = self.composite_name or "Haz clic aqui y escribe el nombre de salida"
            cv2.putText(
                panel, name_text[:100], (42, 466), cv2.FONT_HERSHEY_SIMPLEX,
                0.48, (231, 238, 241), 1, cv2.LINE_AA
            )
            parent_text = f"Clase base seleccionada: {self.composite_parent or 'ninguna'}"
            cv2.putText(
                panel, parent_text, (32, 508), cv2.FONT_HERSHEY_SIMPLEX,
                0.43, (205, 215, 224), 1, cv2.LINE_AA
            )

            self.COMPOSITE_ROLE_HITBOXES = []
            for role, label, bounds in (
                ("parent", "SELECCIONAR BASE", (30, 520, 260, 554)),
                ("children", "SELECCIONAR COMPONENTES", (270, 520, 580, 554)),
            ):
                selected = self.composite_class_role == role
                fill = (49, 83, 75) if selected else (36, 44, 55)
                cv2.rectangle(panel, bounds[:2], bounds[2:], fill, -1)
                cv2.rectangle(
                    panel, bounds[:2], bounds[2:],
                    (72, 196, 160) if selected else (61, 75, 89), 1
                )
                cv2.putText(
                    panel, label, (bounds[0] + 10, bounds[1] + 23),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.36, (236, 243, 244), 1, cv2.LINE_AA
                )
                self.COMPOSITE_ROLE_HITBOXES.append((role, bounds))
            cv2.putText(
                panel, "Haz clic en clases para elegir la base o marcar componentes.",
                (600, 542), cv2.FONT_HERSHEY_SIMPLEX, 0.36,
                (165, 181, 193), 1, cv2.LINE_AA
            )

            cv2.putText(
                panel, "CLASES DEL MODELO ( [ / ] para desplazarse )",
                (32, 580), cv2.FONT_HERSHEY_SIMPLEX, 0.38,
                (133, 153, 167), 1, cv2.LINE_AA
            )
            self.COMPOSITE_CLASS_HITBOXES = []
            visible_classes = MODEL_CLASSES[
                self.composite_class_offset:
                self.composite_class_offset + self.COMPOSITE_CLASS_VISIBLE
            ]
            for row, class_name in enumerate(visible_classes):
                column, local_row = divmod(row, 6)
                x1 = 32 + column * 490
                y1 = 592 + local_row * 36
                bounds = (x1, y1, x1 + 470, y1 + 31)
                selected = (
                    class_name == self.composite_parent
                    or class_name in self.composite_children
                )
                fill = (39, 54, 62) if selected else (28, 35, 44)
                cv2.rectangle(panel, bounds[:2], bounds[2:], fill, -1)
                cv2.rectangle(
                    panel, bounds[:2], bounds[2:],
                    (72, 196, 160) if selected else (46, 56, 67), 1
                )
                marker = (
                    "[BASE]" if class_name == self.composite_parent
                    else "[x]" if class_name in self.composite_children
                    else "[ ]"
                )
                cv2.putText(
                    panel, f"{marker} {class_name}"[:58], (x1 + 9, y1 + 21),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.39, (231, 238, 241), 1, cv2.LINE_AA
                )
                self.COMPOSITE_CLASS_HITBOXES.append((class_name, bounds))

            self.COMPOSITE_EXCLUSIVE_HITBOX = (30, 818, 550, 850)
            exclusive_label = (
                "SOLO ESTOS COMPONENTES (sin otras clases)"
                if self.composite_exclusive else "PERMITIR otros componentes dentro del chasis"
            )
            cv2.rectangle(
                panel, self.COMPOSITE_EXCLUSIVE_HITBOX[:2],
                self.COMPOSITE_EXCLUSIVE_HITBOX[2:],
                (44, 82, 71) if self.composite_exclusive else (36, 44, 55), -1
            )
            cv2.rectangle(
                panel, self.COMPOSITE_EXCLUSIVE_HITBOX[:2],
                self.COMPOSITE_EXCLUSIVE_HITBOX[2:],
                (72, 196, 160), 1
            )
            cv2.putText(
                panel, exclusive_label, (42, 839),
                cv2.FONT_HERSHEY_SIMPLEX, 0.39, (229, 236, 239), 1, cv2.LINE_AA
            )

            self.COMPOSITE_HIDE_HITBOX = (30, 855, 650, 887)
            hide_label = (
                "OCULTAR detecciones interiores (conservar otras maquinas)"
                if self.composite_hide_components
                else "MOSTRAR tambien las detecciones interiores"
            )
            cv2.rectangle(
                panel, self.COMPOSITE_HIDE_HITBOX[:2],
                self.COMPOSITE_HIDE_HITBOX[2:],
                (44, 82, 71) if self.composite_hide_components else (36, 44, 55), -1
            )
            cv2.rectangle(
                panel, self.COMPOSITE_HIDE_HITBOX[:2],
                self.COMPOSITE_HIDE_HITBOX[2:],
                (72, 196, 160), 1
            )
            cv2.putText(
                panel, hide_label, (42, 876),
                cv2.FONT_HERSHEY_SIMPLEX, 0.39, (229, 236, 239), 1, cv2.LINE_AA
            )

            self.COMPOSITE_ACTION_HITBOXES = []
            actions = (
                ("new", "NUEVA", (30, 895, 180, 937)),
                ("save", "GUARDAR REGLA", (195, 895, 390, 937)),
                ("delete", "ELIMINAR", (405, 895, 555, 937)),
                ("back", "VOLVER", (840, 895, 1010, 937)),
            )
            for action, label, bounds in actions:
                cv2.rectangle(panel, bounds[:2], bounds[2:], (36, 44, 55), -1)
                cv2.rectangle(panel, bounds[:2], bounds[2:], (61, 75, 89), 1)
                cv2.putText(
                    panel, label, (bounds[0] + 12, bounds[1] + 27),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.40, (229, 236, 239), 1, cv2.LINE_AA
                )
                self.COMPOSITE_ACTION_HITBOXES.append((action, bounds))
            cv2.putText(
                panel, "Escribe el nombre y pulsa GUARDAR REGLA. G guarda config.json.",
                (30, 948), cv2.FONT_HERSHEY_SIMPLEX, 0.38,
                (177, 193, 204), 1, cv2.LINE_AA
            )

    @staticmethod
    def _draw_card(panel, bounds):
        x1, y1, x2, y2 = bounds
        cv2.rectangle(panel, (x1, y1), (x2, y2), (30, 37, 47), -1)
        cv2.rectangle(panel, (x1, y1), (x2, y2), (47, 59, 71), 1)

    @staticmethod
    def _draw_section_title(panel, title, origin):
        cv2.putText(
            panel, title, origin, cv2.FONT_HERSHEY_SIMPLEX,
            0.48, (126, 231, 205), 1, cv2.LINE_AA
        )

# =====================================================
# PROGRAMA PRINCIPAL
# =====================================================


def main():
    capture_threads = []
    inference_thread = None
    menu = AdminMenu(SETTINGS)

    try:
        open_cameras()

        available = [
            name for name, state in cameras.items()
            if state["cap"] is not None
        ]

        if not available:
            raise RuntimeError(
                "No se pudo abrir ninguna camara. "
                "Verifica config.json (cameras) y la URL IP (CAMERA_IP_URL)."
            )

        for name in available:
            thread = threading.Thread(
                target=capture_loop, args=(name,), daemon=True
            )
            thread.start()
            capture_threads.append(thread)

        inference_thread = threading.Thread(target=inference_loop, daemon=True)
        inference_thread.start()

        win_w = CFG["display"]["window_width"]
        win_h = CFG["display"]["window_height"]
        for name in available:
            cv2.namedWindow(name, cv2.WINDOW_NORMAL)
            cv2.resizeWindow(name, win_w, win_h)
            cv2.setMouseCallback(name, camera_mouse_callback, name)

        cv2.namedWindow("Resumen de detecciones", cv2.WINDOW_NORMAL)
        cv2.resizeWindow("Resumen de detecciones", 760, 300)

        print("\nDeteccion iniciada.")
        print(f"Zona activa: {SETTINGS.get('zone')}")
        print(
            f"YOLO chasis: {os.path.basename(MODEL_PATH)} (imgsz {IMAGE_SIZE}) | "
            f"YOLO personas: {os.path.basename(PEOPLE_MODEL_PATH)} | "
            f"1 fotograma cada {SETTINGS.get('interval_ms') / 1000:.1f} s"
        )
        print(
            "M menu | F reglas compuestas | Z/1-9 zona | A/B/N regla de clase | "
            "[ ] cambiar clase | P guardar fotograma | G guardar config | "
            "V color en zona | R normal | Q/ESC salir | clic = medir color HSV"
        )

        shown = {}                # ultimo (frame_id, conectado) dibujado por camara
        last_summary_t = 0.0

        while True:
            live = SETTINGS.snapshot()
            camera_snapshots = {}

            for name in available:

                with lock:
                    state = cameras[name]
                    frame_id = state["frame_id"]
                    frame = state["latest_frame"]
                    detections = list(state["detections"])
                    people = list(state["people_detections"])
                    inference_ms = state["inference_ms"]
                    connected = state["connected"]
                    blocked_count = state["blocked_count"]
                    probe = state["probe"]
                    camera_snapshots[name] = {
                        "detections": detections,
                        "people": people,
                        "connected": connected,
                        "last_updated": state["last_updated"],
                    }

                    # Solo se copia el fotograma si hay uno nuevo (o cambio el estado)
                    fresh = (
                        frame is not None
                        and shown.get(name) != (frame_id, connected)
                    )
                    if fresh:
                        frame = frame.copy()

                if not fresh:
                    continue
                shown[name] = (frame_id, connected)

                if live["apply_to_preview"]:
                    frame = adjust_image(frame, live)

                probe_text = None
                if probe is not None and time.time() - probe[1] < 10:
                    probe_text = probe[0]

                frame = draw_overlay(
                    frame, name, detections, inference_ms, connected,
                    live["zone"], blocked_count, SETTINGS.dirty, people,
                    probe_text, live["interval_ms"]
                )

                cv2.imshow(name, frame)

            if time.time() - last_summary_t >= 0.5:
                draw_summary_panel(camera_snapshots)
                last_summary_t = time.time()
            menu.draw(SETTINGS.dirty)

            key = cv2.waitKey(10) & 0xFF
            typing_composite_name = (
                menu.is_open
                and menu.show_composite_rules
                and menu.composite_name_active
            )
            if not typing_composite_name and ord("A") <= key <= ord("Z"):
                key += ord("a") - ord("A")

            if typing_composite_name:
                if key == 27:
                    menu.composite_name_active = False
                else:
                    menu.handle_key(key)
                continue

            if key == ord("q") or key == 27:
                break
            elif key == ord("m"):
                menu.toggle()
            elif menu.handle_key(key):
                pass
            elif key == ord("z"):
                i = ZONE_NAMES.index(SETTINGS.get("zone"))
                change_zone(ZONE_NAMES[(i + 1) % len(ZONE_NAMES)])
            elif ord("1") <= key <= ord("9"):
                idx = key - ord("1")
                if idx < len(ZONE_NAMES):
                    change_zone(ZONE_NAMES[idx])
            elif key == ord("v"):
                z = SETTINGS.get("zone")
                with lock:
                    zones_v = VINYL_CFG.setdefault("zones", {})
                    zones_v[z] = not zones_v.get(z, False)
                    for state in cameras.values():
                        reset_camera_results(state)
                SETTINGS.mark_dirty()
                print(f"Color de vinilo en '{z}': "
                      f"{'ACTIVADO' if zones_v[z] else 'DESACTIVADO'} (G para guardar)")
            elif key == ord("g"):
                save_config(CFG, SETTINGS.snapshot())
                SETTINGS.dirty = False
                print("Configuracion guardada en config.json")
            elif key == ord("p"):
                for name in available:
                    with lock:
                        frame = cameras[name]["latest_frame"]
                        frame = None if frame is None else frame.copy()
                    if frame is not None:
                        path = save_training_frame(frame, name, "manual")
                        if path:
                            print(f"Fotograma guardado: {path}")
            elif key == ord("r"):
                SETTINGS.reset_normal(FACTORY_LIVE)
                print("Ajustes restablecidos a valores normales.")

    finally:
        print("\nCerrando camaras y procesos...")

        if SETTINGS.dirty:
            print("AVISO: hubo cambios sin guardar (tecla G la proxima vez).")

        stop_event.set()

        for thread in capture_threads:
            thread.join(timeout=2)

        if inference_thread is not None:
            inference_thread.join(timeout=2)

        for state in cameras.values():
            cap = state["cap"]

            if cap is not None:
                cap.release()

        cv2.destroyAllWindows()

        print("Programa finalizado.")


if __name__ == "__main__":
    main()
