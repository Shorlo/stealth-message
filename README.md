# stealth-message

Chat cifrado end-to-end con claves PGP. Sin servidores centrales. Sin cuentas. Sin metadatos de contenido.

---

## Qué es

`stealth-message` permite a dos o más personas comunicarse de forma privada mediante
cifrado OpenPGP (RFC 4880). Los mensajes nunca pasan por un servidor relay: uno de los
participantes actúa como **host** (levanta un servidor WebSocket) y el resto se conectan
directamente a él.

**Lo que el servidor no puede ver porque no existe.**

---

## Características

- Cifrado end-to-end RSA-4096 + AES-256: solo el destinatario puede leer el mensaje.
- Firma digital en cada mensaje: identidad del emisor verificable criptográficamente.
- Sin servidor central: modelo peer-to-peer directo (host + peers).
- Sin cuentas ni registro: la identidad es la clave PGP.
- Claves privadas almacenadas con permisos `0600`; passphrase solo en memoria.
- **Salas 1:1** — exactamente un peer por sala; acceso denegado si está ocupada.
- **Salas de grupo** — múltiples peers con aprobación explícita del host.
- Descubrimiento de salas: los peers ven la lista de salas disponibles antes de unirse.
- Movimiento de peers entre salas en caliente con `/move`.
- Cuatro clientes nativos que interoperan mediante un protocolo común.

---

## Clientes disponibles

| Plataforma | Tecnología           | Directorio   | Estado        |
|------------|----------------------|--------------|---------------|
| Terminal   | Python 3.10+         | `cli/`       | Funcional     |
| macOS      | Swift 5.9+ / SwiftUI | `macos/`     | En desarrollo |
| Windows 11 | C# 12 / WinUI 3      | `windows/`   | En desarrollo |
| Linux      | Python 3.10+ / GTK4  | `linux/`     | En desarrollo |

Todos los clientes implementan el mismo protocolo (`docs/protocol.md`) y pueden
comunicarse entre sí independientemente de la plataforma.

---

## Inicio rápido (CLI)

```bash
cd cli
python -m venv .venv
source .venv/bin/activate
pip install -e .
python -m stealth_cli
```

La primera vez se ejecuta el asistente de configuración: elige un alias y una passphrase.
Se genera un par de claves RSA-4096 y se muestra tu fingerprint.

**Host:**
```bash
python -m stealth_cli --host               # puerto por defecto 8765
python -m stealth_cli --host --rooms a,b   # múltiples salas
```

**Join:**
```bash
python -m stealth_cli --join ALICE_IP:8765 --room a
# El prefijo ws:// se añade automáticamente si se omite
```

---

## Arquitectura

Ver [ARCHITECTURE.md](ARCHITECTURE.md) para la descripción completa del sistema,
las capas de cada subproyecto y las decisiones de diseño.

El protocolo de comunicación está especificado en [docs/protocol.md](docs/protocol.md).
Este documento es la fuente de verdad: si hay contradicción entre el código y el protocolo,
el protocolo manda.

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
