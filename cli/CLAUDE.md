# stealth-message/cli — CLAUDE.md

Interfaz de terminal para stealth-message. Compatible con WSL (Windows), Linux y macOS.
Lee también el CLAUDE.md raíz del monorepo antes de trabajar en este subproyecto.

## Stack

- **Lenguaje**: Python 3.10+
- **PGP**: `pgpy` — puro Python, sin dependencia de GnuPG instalado en el sistema
- **Red**: `asyncio` + `websockets`
- **UI terminal**: `rich` (renderizado) + `prompt_toolkit` (input interactivo)
- **Config y rutas**: `platformdirs` — rutas correctas en WSL, Linux y macOS
- **Empaquetado**: `pip install -e .` para desarrollo; `PyInstaller` para binario standalone

## Estructura

```
cli/
├── CLAUDE.md
├── pyproject.toml
├── requirements-dev.txt
├── stealth_cli/
│   ├── __init__.py
│   ├── __main__.py          ← entry point: python -m stealth_cli
│   ├── exceptions.py        ← excepciones propias
│   ├── config.py            ← rutas platformdirs, carga/guarda settings
│   ├── crypto/
│   │   ├── __init__.py
│   │   ├── keys.py          ← generar, importar, exportar claves PGP
│   │   └── messages.py      ← cifrar y descifrar según protocol.md §2.1
│   ├── network/
│   │   ├── __init__.py
│   │   ├── server.py        ← servidor WebSocket modo host (protocol.md §1–§4)
│   │   └── client.py        ← cliente WebSocket modo join
│   └── ui/
│       ├── __init__.py
│       ├── chat.py          ← pantalla de chat en tiempo real (rich + prompt_toolkit)
│       └── setup.py         ← wizard de primer uso: generar clave, elegir alias
└── tests/
    ├── test_crypto.py
    └── test_network.py
```

## Comandos de desarrollo

```bash
cd cli
python -m venv .venv
source .venv/bin/activate      # Linux / macOS / WSL

pip install -e ".[dev]"

# Ejecutar
python -m stealth_cli

# Tests
pytest tests/ -v

# Lint y formato
ruff check .
black .
mypy stealth_cli/
```

## Convenciones de código

- **PEP 8**. Formato con `black`. Lint con `ruff`. Tipos con `mypy`.
- **Type hints** obligatorios en todas las funciones públicas.
- **Docstrings** estilo Google en módulos, clases y funciones públicas.
- **`asyncio`** para toda operación de red. Nunca blocking I/O en el event loop.
- **Excepciones propias** en `exceptions.py`. Nunca `except: pass`.
- **`logging`** estándar. Nunca `print()` en código de producción.
- **Separación de capas**: `crypto/` y `network/` no importan nada de `ui/`.
  Las dependencias fluyen hacia arriba, nunca hacia abajo.

## Implementación del protocolo

Este subproyecto implementa `docs/protocol.md` completo.
Referencias directas por sección:

- Handshake → `network/server.py` y `network/client.py` (§1)
- Cifrado de mensaje → `crypto/messages.py` (§2.1)
- Ping/pong y bye → `network/server.py` y `network/client.py` (§3)
- Códigos de error → `exceptions.py` y módulos de network (§4)

## Seguridad

- Las claves privadas se guardan en `platformdirs.user_config_dir("stealth-message")/keys/`
  con permisos `0600`.
- La passphrase se pide en cada arranque via `prompt_toolkit` con `is_password=True`.
  Nunca se persiste en disco.
- Al mostrar el fingerprint de la clave del interlocutor, formatearlo en grupos de 4 chars
  para facilitar la verificación visual fuera de banda.

## Notas para Claude Code

- Empezar siempre por los tests de `crypto/` antes de implementar el módulo.
- El módulo `crypto/messages.py` debe aceptar y devolver `str` (texto plano / armored PGP),
  nunca `bytes` directamente en la API pública — la conversión es interna.
- `network/server.py` debe soportar múltiples conexiones simultáneas (chat de grupo futuro).
- En `ui/chat.py`, el input de `prompt_toolkit` y el output de `rich` deben coordinarse
  para que los mensajes entrantes no rompan la línea de input del usuario.
- Compatibilidad WSL: no usar rutas hardcoded; usar siempre `platformdirs`.
