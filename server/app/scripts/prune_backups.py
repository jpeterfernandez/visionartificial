import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from app.core.config import settings


def main() -> int:
    parser = argparse.ArgumentParser(description="Lista o elimina respaldos antiguos")
    parser.add_argument("--directory", type=Path, default=Path(settings.STORAGE_DIR) / "backups")
    parser.add_argument("--older-than-days", type=int, required=True)
    parser.add_argument("--delete", action="store_true", help="Ejecuta la eliminación; por defecto solo muestra candidatos")
    args = parser.parse_args()
    if args.older_than_days < 1:
        parser.error("--older-than-days debe ser positivo")

    cutoff = datetime.now(timezone.utc) - timedelta(days=args.older_than_days)
    candidates = [
        path for path in args.directory.glob("cardinova-*.dump")
        if datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) < cutoff
    ]
    for path in candidates:
        if args.delete:
            path.unlink()
            print(f"Eliminado: {path}")
        else:
            print(f"Candidato (sin borrar): {path}")
    print(f"Total: {len(candidates)} respaldo(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
