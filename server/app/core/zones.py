from typing import Optional, Set

from app.db.models.user import User


PRODUCTION_ZONES = {
    "DOBLADO",
    "ARMADO_ESTRUCTURAL",
    "VINILADO",
    "ALMACEN",
}


def allowed_zones_for_user(user: User) -> Optional[Set[str]]:
    if user.role.upper() == "ADMIN":
        return None
    return set(user.allowed_zones or [])


def user_can_access_zone(user: User, zone: Optional[str]) -> bool:
    zones = allowed_zones_for_user(user)
    return zones is None or (zone is not None and zone in zones)
