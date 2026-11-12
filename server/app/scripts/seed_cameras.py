import sys
import os
import json

# Add parent directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from app.db.session import SessionLocal
from app.db.models.system_setting import SystemSetting


def seed_initial_cameras_and_settings():
    db = SessionLocal()
    try:
        # Ya NO se crean cámaras ficticias/automáticas con índices 0, 1 o 2.
        # Solo se registrarán las cámaras que el usuario agregue manualmente desde la interfaz o API.


        # Initial class to stage mapping setting
        mapping = {
            "chasis_base": "DOBLADO",
            "cavidad_hueca": "DOBLADO",
            "puerta_sup_panel": "ARMADO_ESTRUCTURAL",
            "puerta_sup_chapa": "ARMADO_ESTRUCTURAL",
            "puerta_inferior": "ARMADO_ESTRUCTURAL",
            "vinilo_frontal": "VINILADO",
            "vinilo_lateral": "VINILADO",
        }
        
        setting = db.query(SystemSetting).filter(SystemSetting.key == "class_stage_mapping").first()
        if not setting:
            db.add(SystemSetting(
                key="class_stage_mapping",
                value=json.dumps(mapping),
                description="Mapeo de clases de visión YOLO a etapas productivas"
            ))
            print("[+] Configuración 'class_stage_mapping' registrada.")

        db.commit()
        print("[+] Inicialización completada con éxito.")
    except Exception as e:
        db.rollback()
        print(f"[-] Error en inicialización: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_initial_cameras_and_settings()
