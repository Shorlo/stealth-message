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
- Claves privadas almacenadas con permisos `0600` o en Keychain; passphrase solo en memoria.
- **Salas 1:1** — exactamente un peer por sala; acceso denegado si está ocupada.
- **Salas de grupo** — múltiples peers con aprobación explícita del host.
- Descubrimiento de salas antes de conectarse (`listrooms` / `roomsinfo`).
- Movimiento de peers entre salas en caliente (`/move`).
- Desconexión forzada de peers por el host (`kick` / `/disconnect`).
- Reset de identidad: borra el keypair y genera uno nuevo (`--reset` / botón en UI).
- Shutdown graceful: se envía `bye` a todos los peers al cerrar la app.
- Cuatro clientes nativos que interoperan mediante un protocolo común (v0.8).

---

## Clientes disponibles

| Plataforma | Tecnología           | Directorio   | Estado        |
|------------|----------------------|--------------|---------------|
| Terminal   | Python 3.10+         | `cli/`       | Funcional     |
| macOS      | Swift 5.9+ / SwiftUI | `macos/`     | En desarrollo |
| Windows 11 | C# 12 / WinUI 3      | `windows/`   | Pendiente     |
| Linux      | Python 3.10+ / GTK4  | `linux/`     | Pendiente     |

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

**Manual completo:**
```bash
python -m stealth_cli --manual
```

---

## Conectarse por internet

Para conectarse fuera de la red local hay dos opciones:

**Port forwarding** — abre el puerto 8765 en tu router y dale a los peers tu IP pública.
Si tu ISP usa CG-NAT (la IP WAN del router no coincide con `curl ifconfig.me`), esta
opción no funcionará.

**Tailscale (recomendado)** — crea un túnel WireGuard entre dispositivos sin configurar
el router. Instala Tailscale en todas las máquinas, usa `tailscale status` para ver las
IPs `100.x.x.x` y conéctate con esas direcciones.

Ver el apartado "Connecting over the internet" del manual (`--manual`) para los pasos
detallados.

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

Copyright © 2026 Javier Sainz de Baranda y Goñi.

Este programa es [software libre](https://www.gnu.org/philosophy/free-sw.html): puedes
redistribuirlo y/o modificarlo bajo los términos de la
[GNU General Public License](https://www.gnu.org/licenses/gpl-3.0.html) tal como la
publica la [Free Software Foundation](https://www.fsf.org), ya sea la versión 3 de la
Licencia, o (a tu elección) cualquier versión posterior.

**Este programa se distribuye con la esperanza de que sea útil, pero SIN NINGUNA
GARANTÍA; sin siquiera la garantía implícita de COMERCIABILIDAD o IDONEIDAD PARA UN
FIN DETERMINADO.** Consulta la GNU General Public License para más detalles.

Deberías haber recibido una [copia](LICENSE) de la GNU General Public License junto con
este programa. Si no es así, visita <https://www.gnu.org/licenses/>.

Para proyectos donde los términos de la GNU General Public License impidan el uso de
este software o requieran la publicación no deseada del código fuente de productos
comerciales, puedes [solicitar una licencia especial](mailto:info@syberiancode.com?subject=stealth-message).
