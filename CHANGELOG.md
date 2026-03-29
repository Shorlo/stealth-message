# Changelog

Todos los cambios notables de este proyecto se documentan en este archivo.

El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.0.0/),
y el proyecto usa [Semantic Versioning](https://semver.org/lang/es/).

---

## [Unreleased]

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
