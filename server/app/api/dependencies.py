from typing import Generator, Optional
from fastapi import Depends, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models.user import User
from app.core.security import decode_access_token
from app.core.exceptions import UnauthorizedException, ForbiddenException
from app.repositories.user_repository import UserRepository

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> User:
    if not token:
        raise UnauthorizedException("No se proporcionó token de autenticación")

    payload = decode_access_token(token)
    if not payload:
        raise UnauthorizedException("Token inválido o expirado")

    username: str = payload.get("sub")
    if not username:
        raise UnauthorizedException("Token sin identificador de usuario")

    repo = UserRepository(db)
    user = repo.get_by_username(username)
    if not user:
        raise UnauthorizedException("Usuario no encontrado")

    if not user.is_active:
        raise UnauthorizedException("Usuario inactivo")

    return user


def require_role(required_role: str):
    """
    Role hierarchy:
    ADMIN > OPERATOR > VIEWER
    """
    def role_checker(current_user: User = Depends(get_current_user)) -> User:
        user_role = current_user.role.upper()
        if user_role == "ADMIN":
            return current_user

        if required_role == "OPERATOR" and user_role in ["ADMIN", "OPERATOR"]:
            return current_user

        if required_role == "VIEWER" and user_role in ["ADMIN", "OPERATOR", "VIEWER"]:
            return current_user

        raise ForbiddenException(f"Se requiere rol {required_role} para realizar esta acción")

    return role_checker
