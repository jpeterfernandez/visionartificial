import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.engine import make_url

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from app.core.config import settings


def main() -> int:
    parser = argparse.ArgumentParser(description="Crea un respaldo PostgreSQL en formato custom")
    parser.add_argument("--output-dir", type=Path, default=Path(settings.STORAGE_DIR) / "backups")
    args = parser.parse_args()

    dump_executable = shutil.which("pg_dump")
    if not dump_executable:
        parser.error("No se encontró pg_dump en PATH")

    database_url = make_url(settings.DATABASE_URL)
    if not database_url.drivername.startswith("postgresql"):
        parser.error("El respaldo configurado requiere PostgreSQL")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_file = args.output_dir / f"cardinova-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.dump"
    command = [dump_executable, "--format=custom", "--file", str(output_file)]
    if database_url.host:
        command.extend(["--host", database_url.host])
    if database_url.port:
        command.extend(["--port", str(database_url.port)])
    if database_url.username:
        command.extend(["--username", database_url.username])
    command.extend(["--dbname", database_url.database or ""])

    environment = os.environ.copy()
    if database_url.password:
        environment["PGPASSWORD"] = database_url.password
    try:
        subprocess.run(command, check=True, env=environment)
    except subprocess.CalledProcessError as error:
        output_file.unlink(missing_ok=True)
        print(f"pg_dump finalizó con código {error.returncode}", file=sys.stderr)
        return error.returncode

    print(f"Respaldo creado: {output_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
