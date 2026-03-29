# stealth-message/linux — CLAUDE.md

App nativa para Linux con GTK4. Compatible con Ubuntu, Debian, Elementary OS y derivados.
Reutiliza la lógica de crypto y network del subproyecto cli/. Plataforma prioritaria 3.
Lee también el CLAUDE.md raíz del monorepo antes de trabajar en este subproyecto.

## Stack

- **Lenguaje**: Python 3.10+
- **UI**: GTK4 via `PyGObject` — toolkit nativo de GNOME, el escritorio por defecto
  en Ubuntu y Elementary OS
- **Concurrencia**: `asyncio` integrado con el event loop de GTK via `gbulb`
- **PGP**: `pgpy` — misma librería que el CLI, sin duplicar código
- **Red**: `asyncio` + `websockets` — misma librería que el CLI
- **Claves seguras**: `SecretService` (libsecret) via `PyGObject`
- **Config**: `platformdirs`
- **Distribución**: `.deb`, Flatpak o AppImage

## Relación con cli/

Los módulos `crypto/` y `network/` de este subproyecto son **simbólicamente iguales**
a los del CLI. Opciones:

1. **Symlinks** (recomendado para desarrollo): `linux/stealth_gtk/crypto` → `../cli/stealth_cli/crypto`
2. **Paquete común** (`stealth_core/`): extraer la lógica compartida a un paquete
   interno del monorepo cuando la complejidad lo justifique.

En cualquier caso, la lógica de crypto y network se escribe y se mantiene una sola vez.

## Estructura

```
linux/
├── CLAUDE.md
├── pyproject.toml
├── stealth_gtk/
│   ├── __init__.py
│   ├── __main__.py              ← entry point: python -m stealth_gtk
│   ├── application.py           ← Gtk.Application, ciclo de vida
│   ├── config.py                ← rutas platformdirs, settings
│   ├── crypto/                  ← symlink o copia de cli/stealth_cli/crypto/
│   │   ├── keys.py
│   │   └── messages.py
│   ├── network/                 ← symlink o copia de cli/stealth_cli/network/
│   │   ├── server.py
│   │   └── client.py
│   ├── security/
│   │   └── secret_service.py    ← wrapper libsecret para guardar claves privadas
│   └── windows/
│       ├── main_window.py       ← Gtk.ApplicationWindow principal
│       ├── chat_window.py       ← ventana de conversación activa
│       ├── setup_dialog.py      ← diálogo de primer uso (generar clave PGP)
│       └── fingerprint_dialog.py ← verificación de fingerprint
└── tests/
    ├── test_crypto.py           ← mismos tests que cli/ si se usan symlinks
    └── test_ui.py
```

## Comandos de desarrollo

```bash
cd linux

# Instalar dependencias del sistema (Ubuntu/Debian)
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 libsecret-1-dev

# Entorno virtual
python3 -m venv .venv
source .venv/bin/activate

pip install -e ".[dev]"

# Ejecutar
python -m stealth_gtk

# Tests
pytest tests/ -v
```

## Convenciones de código

- Mismas convenciones Python que `cli/`: PEP 8, `black`, `ruff`, `mypy`, type hints.
- **No bloquear el hilo principal de GTK**. Toda operación I/O usa `asyncio` vía `gbulb`.
- El event loop de `gbulb` reemplaza al event loop de GTK: inicializar con
  `gbulb.install(gtk=True)` antes de `Gtk.Application.run()`.
- **Separación de capas**: las clases en `windows/` no importan directamente de
  `crypto/` ni `network/`. Toda comunicación va a través de `application.py`.
- Señales GTK para comunicación entre widgets: no usar variables globales.
- Nombres de clases: sufijo `Window` para ventanas, `Dialog` para diálogos.

## Implementación del protocolo

Igual que `cli/` — implementa `docs/protocol.md` completo usando los mismos módulos
de `crypto/` y `network/`. Ver referencias en `cli/CLAUDE.md`.

## Seguridad

- La clave privada PGP se almacena en `libsecret` (SecretService DBus API) usando
  `secret_password_store_sync` con el schema `stealth-message`.
- Si `libsecret` no está disponible, fallback a archivo cifrado en
  `platformdirs.user_config_dir("stealth-message")/keys/` con permisos `0600`.
- El campo de passphrase en GTK usa `Gtk.Entry` con `set_visibility(False)`.
  Limpiar el buffer con `entry.set_text("")` al cerrar el diálogo.

## Compatibilidad de distribuciones

| Distro         | GTK4   | PyGObject | libsecret | Notas                        |
|----------------|--------|-----------|-----------|------------------------------|
| Ubuntu 22.04+  | Sí     | Sí        | Sí        | Paquetes en apt              |
| Debian 12+     | Sí     | Sí        | Sí        | Paquetes en apt              |
| Elementary OS 7| Sí     | Sí        | Sí        | Basado en Ubuntu 22.04       |
| Ubuntu 20.04   | Parcial| Sí        | Sí        | GTK4 requiere PPA adicional  |

## Notas para Claude Code

- Al crear la `Gtk.Application`, usar un ID en formato DNS invertido:
  `com.stealthmessage.app`.
- Para el Flatpak, el manifest `.yaml` debe declarar los permisos
  `org.freedesktop.secrets` para acceder a libsecret.
- `gbulb` necesita instalarse: `pip install gbulb`. Añadirlo a las dependencias
  del `pyproject.toml` bajo `[project.optional-dependencies]` → `gui`.
- Los tests de UI pueden usar `pytest-gtk` o simplemente testear los módulos
  de crypto/network de forma aislada, sin instanciar ventanas GTK.
