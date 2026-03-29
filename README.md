# stealth-message

Chat cifrado end-to-end con claves PGP. Sin servidores centrales. Sin cuentas. Sin metadatos de contenido.

---

## Qué es

`stealth-message` permite a dos o más personas comunicarse de forma privada mediante
cifrado OpenPGP (RFC 4880). Los mensajes nunca pasan por un servidor relay: uno de los
participantes actúa como host (levanta un servidor WebSocket) y el resto se conectan
directamente a él.

**Lo que el servidor no puede ver porque no existe.**

---

## Características

- Cifrado end-to-end con claves PGP: solo el destinatario puede leer el mensaje.
- Firma digital: cada mensaje está firmado; la identidad del emisor es verificable.
- Sin servidor central: modelo peer-to-peer directo.
- Sin cuentas ni registro: la identidad es la clave PGP.
- Claves privadas almacenadas en el almacén seguro del SO (Keychain, DPAPI, libsecret).
- Cuatro clientes nativos que interoperan entre sí mediante un protocolo común.

---

## Clientes disponibles

| Plataforma | Tecnología           | Directorio   | Estado        |
|------------|----------------------|--------------|---------------|
| Terminal   | Python 3.10+         | `cli/`       | En desarrollo |
| macOS      | Swift 5.9+ / SwiftUI | `macos/`     | En desarrollo |
| Windows 11 | C# 12 / WinUI 3      | `windows/`   | En desarrollo |
| Linux      | Python 3.10+ / GTK4  | `linux/`     | En desarrollo |

Todos los clientes implementan el mismo protocolo (`docs/protocol.md`) y pueden
comunicarse entre sí independientemente de la plataforma.

---

## Arquitectura

Ver [ARCHITECTURE.md](ARCHITECTURE.md) para la descripción completa del sistema,
las capas de cada subproyecto y las decisiones de diseño.

El protocolo de comunicación está especificado en [docs/protocol.md](docs/protocol.md).
Este documento es la fuente de verdad: si hay contradicción entre el código y el protocolo,
el protocolo manda.

---

## Empezar a desarrollar

Cada subproyecto tiene su propio entorno de desarrollo. Consulta el `CLAUDE.md`
correspondiente para instrucciones detalladas:

- [cli/CLAUDE.md](cli/CLAUDE.md) — Python, asyncio, websockets, pgpy
- [macos/CLAUDE.md](macos/CLAUDE.md) — Swift, SwiftUI, SPM
- [windows/CLAUDE.md](windows/CLAUDE.md) — C#, .NET 8, WinUI 3
- [linux/CLAUDE.md](linux/CLAUDE.md) — Python, GTK4, PyGObject

---

## Seguridad

Ver [SECURITY.md](SECURITY.md) para la política de seguridad completa y el proceso
de reporte de vulnerabilidades.

**No abrir issues públicos para vulnerabilidades de seguridad.**

---

## Contribuir

Ver [CONTRIBUTING.md](CONTRIBUTING.md) para la guía de contribución, estándares
de código y proceso de pull request.

---

## Changelog

Ver [CHANGELOG.md](CHANGELOG.md) para el historial de cambios del proyecto.

---

## Licencia

*(Por definir)*
