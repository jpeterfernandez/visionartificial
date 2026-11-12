import argparse
from getpass import getpass
import sys
import os

# Add parent directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from app.db.session import SessionLocal
from app.db.models.user import User
from app.core.security import hash_password


def create_admin(username: str, password: str, full_name: str = "Administrador Cardinova"):
    if len(password) < 12:
        raise ValueError("La contraseña del administrador debe tener al menos 12 caracteres")

    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.username == username).first()
        if existing:
            print(f"[!] El usuario '{username}' ya existe. Actualizando contraseña y rol...")
            existing.hashed_password = hash_password(password)
            existing.role = "ADMIN"
            existing.is_active = True
            existing.full_name = full_name
            db.commit()
            print(f"[+] Usuario '{username}' actualizado como ADMIN.")
            return

        admin_user = User(
            username=username,
            full_name=full_name,
            hashed_password=hash_password(password),
            role="ADMIN",
            is_active=True
        )
        db.add(admin_user)
        db.commit()
        print(f"[+] Usuario ADMIN '{username}' creado exitosamente.")
    except Exception as e:
        db.rollback()
        print(f"[-] Error al crear usuario: {e}")
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Crear usuario administrador de Cardinova")
    parser.add_argument("--username", required=True, help="Nombre de usuario")
    parser.add_argument("--password", help="Contraseña segura (si se omite, se solicita de forma privada)")
    parser.add_argument("--name", default="Administrador Cardinova", help="Nombre completo")
    args = parser.parse_args()

    password = args.password or getpass("Contraseña del administrador (mínimo 12 caracteres): ")
    create_admin(args.username, password, args.name)
