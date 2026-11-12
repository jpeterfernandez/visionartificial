import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from sqlalchemy.engine import make_url

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from app.core.config import settings


def main() -> int:
    parser = argparse.ArgumentParser(description="Restaura un respaldo PostgreSQL a una base destino")
    parser.add_argument("backup_file", type=Path)
    parser.add_argument("--target-database", required=True, help="Base destino vacía; nunca se limpia automáticamente")
    args = parser.parse_args()

    restore_executable = shutil.which("pg_restore")
    if not restore_executable:
        parser.error("No se encontró pg_restore en PATH")
    if not args.backup_file.is_file():
        parser.error("No existe el archivo de respaldo indicado")

    database_url = make_url(settings.DATABASE_URL)
    if not database_url.drivername.startswith("postgresql"):
        parser.error("La restauración configurada requiere PostgreSQL")

    command = [restore_executable, "--exit-on-error", "--no-owner", "--dbname", args.target_database]
    if database_url.host:
        command.extend(["--host", database_url.host])
    if database_url.port:
        command.extend(["--port", str(database_url.port)])
    if database_url.username:
        command.extend(["--username", database_url.username])
    command.append(str(args.backup_file))

    environment = os.environ.copy()
    if database_url.password:
        environment["PGPASSWORD"] = database_url.password
    try:
        subprocess.run(command, check=True, env=environment)
    except subprocess.CalledProcessError as error:
        print(f"pg_restore finalizó con código {error.returncode}; la base destino puede quedar parcial", file=sys.stderr)
        return error.returncode

    print(f"Respaldo restaurado en la base destino: {args.target_database}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
