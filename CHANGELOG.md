# Changelog

Todos los cambios notables de este proyecto se documentan en este archivo.

El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.0.0/),
y el proyecto usa [Semantic Versioning](https://semver.org/lang/es/).

---

## [Unreleased]

### Added
- `cli/stealth_cli/network/server.py`: `StealthServer` — WebSocket host con handshake (§1), mensajes cifrados (§2), ping/pong/bye (§3), códigos de error (§4), múltiples conexiones simultáneas
- `cli/stealth_cli/network/client.py`: `StealthClient` — WebSocket joiner con handshake, envío cifrado, ping con RTT, desconexión limpia
- 21 tests de integración en `tests/test_network.py` — suite completa: 52 tests pasando
- `cli/stealth_cli/crypto/messages.py`: `encrypt` y `decrypt` (protocolo §2.1) — sign-then-encrypt, Base64 URL-safe, `SignatureError` si la firma es inválida — 10 tests nuevos
- `cli/stealth_cli/exceptions.py`: `StealthError`, `SignatureError`, `ProtocolError` con código numérico (protocolo §4)
- `cli/stealth_cli/crypto/keys.py`: `generate_keypair`, `load_private_key`, `load_public_key`, `get_fingerprint` — 21 tests pasando
- `cli/pyproject.toml` con dependencias, dev-dependencies, entry point y configuración de black/ruff/mypy/pytest
- Estructura de carpetas de `cli/stealth_cli/` con módulos vacíos: `crypto/`, `network/`, `ui/`, `exceptions.py`, `config.py`, `__main__.py`
- Tests vacíos en `cli/tests/`: `test_crypto.py`, `test_network.py`

### Changed
- Establecida la rama `test` como rama de trabajo principal; `main` solo recibe cambios via PR
- Actualizado `CLAUDE.md` raíz con regla de ramas (siempre trabajar en `test`)
- Actualizado `CONTRIBUTING.md` con instrucciones de rama de trabajo

### Added
- Estructura inicial del monorepo con directorios `cli/`, `macos/`, `windows/`, `linux/`
- Especificación del protocolo de comunicación v0.1 en `docs/protocol.md`
- CLAUDE.md raíz con arquitectura, reglas globales y pautas de trabajo
- CLAUDE.md por subproyecto con stack, estructura y convenciones específicas
- `ARCHITECTURE.md` con descripción de la arquitectura del sistema
- `SECURITY.md` con política de seguridad y reporte de vulnerabilidades
- `CONTRIBUTING.md` con guía de contribución al proyecto
- `CHANGELOG.md` (este archivo)
- `.gitignore` para Python, Swift/SPM, C#/.NET, macOS e IDEs
- `README.md` actualizado con descripción completa del proyecto

---

## [0.1.0] — por publicar

> Primera release pública cuando el CLI y al menos una app nativa estén funcionales.

### Planned
- CLI funcional (Python): crypto, network, UI terminal
- App macOS (Swift + SwiftUI): completa e integrada con Keychain
- App Linux (Python + GTK4): completa e integrada con libsecret
- App Windows (C# + WinUI 3): completa e integrada con DPAPI
