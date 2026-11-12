# Cardinova - Backend API & Visión Artificial

Sistema REST desarrollado con **FastAPI**, **SQLAlchemy 2.0**, **PostgreSQL** y **Ultralytics YOLOv8** para el seguimiento y control de las etapas de producción en Cardinova.

## 1. Requisitos Previos

- Python 3.11+ (Entorno actual: Python 3.13 en `.venv`)
- PostgreSQL 15+ ejecutándose (actualmente en contenedor Docker `postgres_contenedor`, puerto 5432).
- Modelo YOLO entrenado `best.pt` en la raíz del servidor (`server/best.pt`).

## 2. Configuración del Entorno (.env)

Copia `.env.example` a `.env`:
```bash
cp .env.example .env
```

Parámetros clave:
- `DATABASE_URL`: Conexión PostgreSQL (ej. `postgresql+psycopg://admin:admin@localhost:5432/cardinova_core_platform`)
- `SECRET_KEY`: Clave para firma de tokens JWT.
- `ODOO_ENCRYPTION_KEY`: Clave independiente para cifrar credenciales Odoo guardadas en PostgreSQL; obligatoria fuera de desarrollo.
- `YOLO_MODEL_PATH`: Ruta al archivo de pesos del modelo (`best.pt`).
- `YOLO_IMG_SIZE` y `YOLO_STREAM_IMG_SIZE`: resolución para capturas/imágenes y video en vivo; el stream usa 224 px por defecto para reducir carga.
- `YOLO_DEVICE`: `auto` usa CPU cuando no hay una GPU CUDA compatible, incluido el caso ARM CPU-only.
- `ODOO_BASE_URL`, `ODOO_DATABASE`, `ODOO_USERNAME`, `ODOO_API_KEY`: Parámetros de integración con Odoo ERP.

### Equipos de bajos recursos y ARM

- Empieza con `YOLO_DEVICE=auto`, `YOLO_IMG_SIZE=320` y `YOLO_STREAM_IMG_SIZE=224`; si pierde objetos pequeños, sube la resolución del stream a 320 o 416.
- El backend limita PyTorch a un máximo de 2 hilos para dejar más recursos disponibles al resto del equipo; en **Configuración > Recursos YOLO** puedes bajarlo a 1.
- Las transmisiones limitan tanto la inferencia como la salida a 1–10 FPS por cámara (5 FPS por defecto), conservando el frame más reciente. Los frames enviados se reducen a un máximo de 960 px de ancho, se codifican una sola vez por frame para clientes compartidos y usan calidad JPEG 65.
- ARM necesita una instalación de PyTorch/Ultralytics compatible con la arquitectura y el sistema operativo de destino. La ruta CPU es compatible en el código, pero el rendimiento debe medirse en el dispositivo real antes del despliegue.
- Para más velocidad, mide primero la precisión del modelo en escenas reales. Exportar a ONNX/NCNN o usar cuantización puede reducir recursos, pero requiere validar que no empeoren la detección de máquinas y colores.

## 3. Base de Datos

Las tablas se crean y gestionan directamente con **SQLAlchemy** en la inicialización del backend y en los scripts del proyecto. No se usa Alembic en esta versión.

Los administradores asignan zonas a cada usuario desde **Usuarios**. ADMIN tiene alcance global; OPERATOR y VIEWER solo acceden a sus zonas asignadas. Las cuentas preexistentes deben configurarse antes de volver a consultar datos.

## 4. Inicialización de Datos

Para crear el usuario administrador inicial y registrar el mapeo de clases YOLO a etapas:
```bash
# Crear o actualizar usuario administrador con una contraseña elegida para el entorno
python app/scripts/create_admin.py --username admin --password "CAMBIA_ESTA_CONTRASENA"

# Registrar el mapeo inicial de clases. Este script no crea cámaras.
python app/scripts/seed_cameras.py
```

Las cámaras solo se registran cuando un administrador las agrega explícitamente desde la interfaz o la API.

## 5. Clasificación configurable de chasis

En **Configuración > Reglas de detección por zona**, un administrador puede definir cómo agrupar y nombrar cada máquina:

- La clase principal (ancla) identifica el chasis; solo se asocian componentes cuyo centro cae dentro de su caja.
- Las clases requeridas deben estar todas presentes. La lista de alternativas requiere al menos una coincidencia.
- Una regla sin clases adicionales clasifica el ancla por sí sola. Si varias reglas coinciden, se aplica primero la que tenga mayor prioridad en la lista.
- El nombre configurado se incluye en las clasificaciones, eventos y resultados de inferencia; la etapa seleccionada conserva los códigos de producción existentes.

Los valores iniciales clasifican `chasis_base` con `cavidad_hueca` como “Chasis doblado”, `chasis_base` con cualquiera de las clases de puerta como “Chasis estructurado” y `chasis_vinilado` de forma individual. La configuración se guarda en `system_settings` bajo `ZONE_DETECTION_CONFIG`; las instalaciones con una configuración antigua de zonas reciben estas reglas iniciales automáticamente.

### Conteo de almacén y transmisiones compartidas

- En la zona `ALMACEN`, las detecciones actualizan el conteo y los colores del snapshot de inventario; no crean filas históricas de detecciones ni eventos de producción.
- Los clientes que ven la misma cámara comparten una sola captura física y un solo hilo de inferencia dentro del proceso del backend. Se entrega a cada cliente el frame más reciente, y la captura se cierra al desconectarse el último cliente.
- El monitor de conexión y las capturas periódicas evitan abrir otra conexión física mientras esa cámara tiene una transmisión activa.

## 6. Ejecución del Servidor

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

- Documentación interactiva Swagger: [http://localhost:8000/docs](http://localhost:8000/docs)
- Documentación ReDoc: [http://localhost:8000/redoc](http://localhost:8000/redoc)
- Endpoint de verificación de salud: `GET http://localhost:8000/api/v1/health`

## 7. Trasladar a otra PC Windows y acceder por la red local

En la PC de desarrollo, desde la raíz del proyecto, ejecuta `.\preparar-paquete.ps1`. Se genera `Paquete-Cardinova.zip`, con el backend, los pesos `best.pt` y la interfaz compilada. El paquete no incluye `.env`, credenciales, Python, PostgreSQL ni dependencias instaladas.

En la PC destino:

1. Extrae el ZIP en una carpeta local y ejecuta `Iniciar-Cardinova.bat` como administrador. Necesita conexión a Internet y `winget` (App Installer).
2. El instalador descarga Python 3.11 y PostgreSQL 17. En el instalador de PostgreSQL configura y recuerda la contraseña de `postgres`.
3. Cuando la configuración lo solicite, escribe esa contraseña y crea la contraseña del usuario `admin` (mínimo 12 caracteres). El instalador crea la base `cardinova`, las tablas y una clave privada local.
4. Al terminar, usa la URL `http://<IP-del-servidor>:8000` desde las otras PCs conectadas a la misma red. La PC servidor debe permanecer encendida y `Iniciar-Cardinova.bat` abierto.

El puerto 8000 se habilita solo para conexiones de la subred local; PostgreSQL permanece accesible únicamente desde el equipo servidor. La instalación usa PyTorch CPU para evitar los paquetes CUDA de varios GB; descarga dependencias y pesos, por lo que requiere conexión y puede tardar. No se requiere Node.js en la PC destino. El equipo debe tener recursos suficientes para ejecutar YOLO.

El acceso es HTTP sin cifrado, pensado para una red local confiable; no reenvíes el puerto del router ni lo expongas directamente a Internet. Si la PC destino no tiene Internet, primero se debe preparar un instalador offline de Python/PostgreSQL y descargar previamente las dependencias; ese escenario no está incluido en el ZIP.

## 8. Pruebas Automatizadas

```bash
pytest -v Blocked_tests
```

## 9. Respaldo y Restauración

`pg_dump` y `pg_restore` deben estar instalados y disponibles en `PATH`.

```bash
python app/scripts/backup_database.py
python app/scripts/restore_database.py storage/backups/cardinova-AAAAmmddTHHMMSSZ.dump --target-database cardinova_restore
```

La restauración no borra objetos y debe apuntar a una base destino vacía. Verifica los respaldos con restauraciones periódicas antes de depender de ellos. Para revisar candidatos de retención sin borrar nada:

```bash
python app/scripts/prune_backups.py --older-than-days 90
```

Solo añade `--delete` después de confirmar la política de retención y que existe un respaldo válido.
