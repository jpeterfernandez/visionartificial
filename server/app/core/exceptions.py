from fastapi import HTTPException, status


class CardinovaException(HTTPException):
    def __init__(self, status_code: int, detail: str):
        super().__init__(status_code=status_code, detail=detail)


class NotFoundException(CardinovaException):
    def __init__(self, detail: str = "Recurso no encontrado"):
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


class UnauthorizedException(CardinovaException):
    def __init__(self, detail: str = "Credenciales incorrectas o token no válido"):
        super().__init__(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


class ForbiddenException(CardinovaException):
    def __init__(self, detail: str = "No posee permisos suficientes para esta operación"):
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


class ModelNotLoadedException(CardinovaException):
    def __init__(self, detail: str = "El modelo YOLO no se encuentra cargado o no está disponible"):
        super().__init__(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail)


class BadRequestException(CardinovaException):
    def __init__(self, detail: str = "Solicitud inválida"):
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)
