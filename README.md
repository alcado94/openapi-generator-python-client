# OpenAPI Modular CLI

**Herramienta CLI genérica** para convertir **cualquier especificación OpenAPI 3.x compatible** en un conjunto de distribuciones Python con instalación selectiva por `tag` mediante extras. **Este repositorio contiene exclusivamente el generador**: no incorpora SDKs de cliente pregenerados para empresas o APIs concretas.

- Recibe una especificación YAML o JSON, nombre de distribución y directorio de salida.
- Descubre `tags` y comprueba su compatibilidad como nombres de extras.
- Filtra operaciones y componentes por `tag`, de forma determinista.
- Ejecuta el generador oficial `python` de OpenAPI Generator (transporte `urllib3`).
- Construye un metapaquete con extras `[tag]` y `[all]`, paquetes por `tag` y núcleo genérico.
- Genera un `Client` padre con carga diferida de módulos y autenticación HTTP Basic / OAuth2 `client_credentials`.
- No utiliza los valores de `tokenUrl` de la especificación para la autenticación: se proporcionan al inicializar el cliente **generado**.

## Requisitos

- Python **3.11+** y pip.
- `openapi-generator-cli` en `PATH` para `generate` real. Instálalo según [la documentación oficial](https://openapi-generator.tech/docs/installation/). El comando de inspección no lo requiere.
- La CLI incluye PyYAML; el runtime del SDK generado incorpora HTTPX para solicitar tokens.
- OpenAPI 3.0 o 3.1, referencias locales a `#/components/...` y todas las operaciones etiquetadas.

## Instalar la herramienta

```bash
python -m pip install -e .
openapi-modular --help
```

Sin instalación editable, también funciona con `PYTHONPATH=src python -m openapi_modular_cli`.

## 1. Inspección

```bash
openapi-modular inspect --spec /ruta/a/openapi.yaml
```

Muestra JSON con los `tags` que se convertirán en extras y las opciones de seguridad detectadas por dominio.

## 2. Generación

```bash
openapi-modular generate \
  --spec /ruta/a/openapi.yaml \
  --name mi-api-sdk \
  --module mi_api_sdk \
  --package-version 1.0.0 \
  --output ./dist-sdk
```

`--name` define el nombre público de instalación; **no está fijado en el código del generador**. `--module` es opcional (se deduce de `--name`). El generador creará automáticamente un extra por cada tag de la especificación. El directorio de salida debe estar vacío o no existir, para evitar borrados accidentales.

Si la especificación tiene `Users` y `Catalogs`, el resultado permitiría publicar los wheels y luego instalar:

```bash
pip install 'mi-api-sdk[users]'
pip install 'mi-api-sdk[catalogs]'
pip install 'mi-api-sdk[users,catalogs]'
pip install 'mi-api-sdk[all]'
```

Esos **nombres son ilustrativos y se generan en la salida**; no se empaqueta un SDK de muestra en este proyecto.

### Vista previa sin OpenAPI Generator

```bash
openapi-modular generate \
  --spec /ruta/a/openapi.yaml \
  --name mi-api-sdk \
  --output ./previsualizacion \
  --scaffold-only
```

La vista previa escribe metadatos, paquetes de soporte y especificaciones filtradas, **pero NO genera APIs HTTP**; la salida **no es un SDK instalable/usable**. Úsala únicamente para estudiar el layout y los extras.

## 3. Publicar los paquetes resultantes

El generador no publica automáticamente. Hay que construir **y publicar todas las distribuciones**, incluidas `-core` y las de los tags, en el mismo índice PyPI o índice interno. Para uso local, primero genera los wheels (`python -m build` en cada carpeta de `packages/`) y después instálalos desde un directorio compartido de wheels con `pip --find-links`.

Ejemplo conceptual, una vez publicados los paquetes generados:

```python
import os
from mi_api_sdk import Client

with Client.oauth2(
    host=os.environ["API_HOST"],
    token_url=os.environ["TOKEN_URL"],
    client_id=os.environ["CLIENT_ID"],
    client_secret=os.environ["CLIENT_SECRET"],
    scope=os.environ.get("SCOPE", ""),
) as client:
    # El nombre/método real depende del tag y operationId OpenAPI.
    respuesta = client.users.get_users()
```

Para Basic: `Client.basic(host=..., username=..., password=...)`.

## Uso automatizado

El comando **no solicita credenciales**, no contacta con los servidores de la API y no necesita cuentas SaaS. Solo ejecuta OpenAPI Generator para crear código local. Las credenciales se suministran cuando se utiliza el SDK resultante, normalmente desde variables de entorno de la aplicación consumidora.

## Alcance de v0.1

| Función | Estado |
|---|---|
| CLI reutilizable, parámetros por invocación | Implementado |
| Inspección y normalización de tags | Implementado |
| Filtro local de operaciones y referencias a componentes | Implementado |
| Un paquete instalable por tag | Implementado a nivel de orquestación; requiere OpenAPI Generator externo |
| Metapaquete `[tag]` y `[all]` | Implementado |
| Cliente padre por entry points | Implementado |
| Basic + OAuth2 client_credentials y caché del token | Implementado |
| Cliente síncrono con `urllib3` | Implementado |
| Async / `httpx`, `httpx2` | Previsto, no implementado |
| Referencias externas, discriminadores complejos | No soportados en el filtro de v0.1 |
| Integración con ejecutable oficial real | **Pendiente de validación** en un entorno con OpenAPI Generator |

La tool valida los `securitySchemes` que usan las operaciones, y acepta únicamente Basic y OAuth2 `clientCredentials`; la autenticación combinada AND se rechaza. Si se necesita otro esquema, habrá que extender el runtime/validador.

## Documentación

- [Plan técnico de implementación](PLAN_TECNICO.md)
- [Diagrama de arquitectura](docs/arquitectura.svg)
- [Diagrama de secuencia OAuth2](docs/secuencia.svg)

## Pruebas

```bash
python -m pip install -e '.[test]'
python -m pytest -q
```

El test de integración usa un **ejecutable simulado** que imita la estructura de salida esperada de OpenAPI Generator. No sustituye la validación con el binario real sobre especificaciones complejas.
