from app.db import models
from app.db.base import Base
from app.db.session import engine


def initialize_database() -> None:
    Base.metadata.create_all(bind=engine)
    print("[+] Tablas de Cardinova creadas o ya existentes.")


if __name__ == "__main__":
    initialize_database()
