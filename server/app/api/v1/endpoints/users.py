from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies import require_role
from app.core.exceptions import BadRequestException, NotFoundException
from app.core.security import hash_password
from app.core.zones import PRODUCTION_ZONES
from app.db.models.user import User
from app.db.session import get_db
from app.repositories.user_repository import UserRepository
from app.repositories.audit_repository import record_audit
from app.repositories.camera_repository import CameraRepository
from app.schemas.user import UserCreate, UserResponse, UserUpdate

router = APIRouter(prefix="/users", tags=["Administración de usuarios"])


def _validated_zones(db: Session, role: str, zones: List[str], is_active: bool) -> List[str]:
    if role == "ADMIN":
        return []
    available = PRODUCTION_ZONES | {camera.zone for camera in CameraRepository(db).get_all()}
    invalid = set(zones) - available
    if invalid:
        raise BadRequestException(f"Zonas desconocidas: {', '.join(sorted(invalid))}")
    if is_active and not zones:
        raise BadRequestException("Asigne al menos una zona a cada usuario activo que no sea ADMIN")
    return sorted(set(zones))


@router.get("", response_model=List[UserResponse])
def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("ADMIN")),
):
    return UserRepository(db).get_all(skip=skip, limit=limit)


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("ADMIN")),
):
    repository = UserRepository(db)
    if repository.get_by_username(payload.username):
        raise BadRequestException("El nombre de usuario ya está registrado")

    allowed_zones = _validated_zones(db, payload.role, payload.allowed_zones, payload.is_active)
    user = User(
        username=payload.username,
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        role=payload.role,
        allowed_zones=allowed_zones,
        is_active=payload.is_active,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(user)
    db.flush()
    record_audit(db, _admin, "user.created", "user", str(user.id), {"role": user.role})
    db.commit()
    db.refresh(user)
    return user


@router.patch("/{user_id}", response_model=UserResponse)
def update_user(
    payload: UserUpdate,
    user_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("ADMIN")),
):
    repository = UserRepository(db)
    user = repository.get_by_id(user_id)
    if not user:
        raise NotFoundException(f"Usuario #{user_id} no encontrado")

    changes = payload.model_dump(exclude_unset=True)
    next_role = changes.get("role", user.role)
    next_active = changes.get("is_active", user.is_active)
    next_zones = changes.get("allowed_zones", user.allowed_zones or [])
    is_removing_active_admin = user.role == "ADMIN" and user.is_active and (
        next_role != "ADMIN" or not next_active
    )
    if is_removing_active_admin:
        active_admins = db.query(User).filter(User.role == "ADMIN", User.is_active.is_(True)).count()
        if active_admins <= 1:
            raise BadRequestException("No se puede desactivar ni cambiar el rol del último administrador activo")

    if "allowed_zones" in changes or "role" in changes or "is_active" in changes:
        changes["allowed_zones"] = _validated_zones(db, next_role, next_zones, next_active)

    password = changes.pop("password", None)
    for field, value in changes.items():
        setattr(user, field, value)
    if password:
        user.hashed_password = hash_password(password)
    user.updated_at = datetime.now(timezone.utc)
    changed_fields = sorted([*changes, *( ["password"] if password else [])])
    record_audit(
        db,
        _admin,
        "user.updated",
        "user",
        str(user.id),
        {"changed_fields": changed_fields},
    )
    return repository.update(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("ADMIN")),
):
    repository = UserRepository(db)
    user = repository.get_by_id(user_id)
    if not user:
        raise NotFoundException(f"Usuario #{user_id} no encontrado")
    if user.id == admin.id:
        raise BadRequestException("No puedes eliminar tu propia cuenta")
    if user.role == "ADMIN" and user.is_active:
        active_admins = db.query(User).filter(User.role == "ADMIN", User.is_active.is_(True)).count()
        if active_admins <= 1:
            raise BadRequestException("No se puede eliminar el último administrador activo")

    record_audit(db, admin, "user.deleted", "user", str(user.id), {"username": user.username})
    repository.delete(user)
    return None
