# Arquitectura de stealth-message

## Visión general

`stealth-message` es una aplicación de chat cifrado end-to-end con claves PGP.
No existe servidor central: uno de los participantes actúa como **host** (levanta
el servidor WebSocket) y el resto se conectan directamente a él.

```
┌─────────────┐        WebSocket + PGP        ┌─────────────┐
│  Cliente A  │◄─────────────────────────────►│  Cliente B  │
│  (host)     │                               │  (join)     │
└─────────────┘                               └─────────────┘
```

En salas de grupo, el host actúa como relay entre peers:

```
┌──────────┐   cifrado(B)   ┌──────────┐   cifrado(C)   ┌──────────┐
│ Cliente B │──────────────►│  Host A  │──────────────►│ Cliente C │
└──────────┘                └──────────┘                └──────────┘
                                 │
                         re-cifra para cada
                         destinatario — ve el
                         plaintext durante el relay
```

No hay relay de terceros. Los mensajes cifrados solo pasan por las máquinas
de los participantes.

---

## Estructura del monorepo

```
stealth-message/
├── docs/
│   └── protocol.md       ← FUENTE DE VERDAD del protocolo (v0.8)
├── cli/                  ← Terminal (Python 3.10+)  ← IMPLEMENTACIÓN REFERENCIA
├── macos/                ← App nativa macOS (Swift 5.9+ / SwiftUI)  ← en desarrollo
├── windows/              ← App nativa Windows 11 (C# 12 / WinUI 3)  ← pendiente
└── linux/                ← App nativa Linux GTK4 (Python 3.10+)     ← pendiente
```

**Principio clave:** no hay código compartido entre plataformas. El contrato es
`docs/protocol.md`. Si dos clientes distintos pueden chatear entre sí, el
protocolo está bien implementado en ambos.

---

## Estado actual de implementación

### CLI (`cli/`) — Implementación referencia — Funcional

| Módulo | Archivo | Estado |
|--------|---------|--------|
| Entrada / flags | `__main__.py` | Completo |
| Configuración y persistencia | `config.py` | Completo |
| Generación de claves | `crypto/keys.py` | Completo |
| Cifrado / descifrado | `crypto/messages.py` | Completo |
| Servidor WebSocket | `network/server.py` | Completo |
| Cliente WebSocket | `network/client.py` | Completo |
| Interfaz de chat | `ui/chat.py` | Completo |
| Asistente de configuración | `ui/setup.py` | Completo |
| Suite de tests | `tests/` | 64 tests, todos pasan |

Comandos disponibles en el CLI:

| Comando | Quién | Descripción |
|---------|-------|-------------|
| `/fp` | todos | Fingerprint del peer actual |
| `/rooms` | todos | Lista de salas y estado |
| `/switch <sala>` | todos | Cambiar de sala activa |
| `/help` | todos | Mostrar ayuda |
| `/quit` / `/exit` / `/q` | todos | Cerrar sesión |
| `/new <sala>` | host | Crear sala 1:1 en caliente |
| `/group <sala>` | host | Convertir sala a modo grupo |
| `/move <alias> <sala>` | host | Mover peer a otra sala |
| `/allow <alias>` | host | Aprobar solicitud de unión |
| `/deny <alias>` | host | Denegar solicitud de unión |
| `/pending` | host | Ver solicitudes pendientes |
| `/disconnect [alias]` | host | Forzar desconexión de un peer |

Flags del ejecutable:

| Flag | Descripción |
|------|-------------|
| `--host [PORT]` | Modo host, puerto por defecto 8765 |
| `--rooms ROOMS` | Salas separadas por comas (modo host) |
| `--join URI` | Modo join, `ws://` añadido automáticamente |
| `--room ROOM` | Sala a unirse (modo join, por defecto "default") |
| `--reset` | Borra la identidad guardada y lanza el asistente |
| `--manual` | Manual de usuario completo |
| `--debug` | Logging detallado |

### macOS (`macos/`) — En desarrollo

| Módulo | Archivo | Estado |
|--------|---------|--------|
| Gestión de claves PGP | `Crypto/PGPKeyManager.swift` | Implementado |
| Almacén Keychain | `Crypto/KeychainStore.swift` | Implementado |
| Errores crypto | `Crypto/CryptoError.swift` | Implementado |
| Tipos de mensajes de protocolo | `Network/Message.swift` | Implementado |
| Cliente WebSocket | `Network/StealthClient.swift` | Implementado |
| Servidor WebSocket | `Network/StealthServer.swift` | Implementado |
| ViewModel principal | `UI/AppViewModel.swift` | Implementado |
| Pantalla de configuración | `UI/SetupView.swift` | Implementado |
| Pantalla de desbloqueo | `UI/UnlockView.swift` | Implementado |
| Hub / identidad | `UI/HubView.swift` | Implementado |
| Pantalla de host | `UI/HostView.swift` | Implementado |
| Pantalla de join | `UI/JoinView.swift` | Implementado |
| Lifecycle / shutdown graceful | `StealthMessageApp.swift` | Implementado |

Dependencias externas:
- **ObjectivePGP 0.99.4** — cifrado/firma RSA-4096 + AES-256
- Keychain Services (framework del sistema)
- Network.framework (`NWListener` / `NWProtocolWebSocket`)
- URLSession (`URLSessionWebSocketTask`) — lado cliente

### Windows (`windows/`) y Linux (`linux/`) — Pendiente

No iniciados. Deben implementar `docs/protocol.md` completo y el mismo
comportamiento de crypto que el CLI.

---

## Capas de cada subproyecto

Todos los subproyectos siguen la misma separación de capas:

```
┌──────────────────────┐
│         UI           │  Presentación (SwiftUI, WinUI 3, GTK4, rich/prompt_toolkit)
├──────────────────────┤
│      ViewModel /     │  Lógica de presentación, estado de la sesión
│   Controlador        │
├──────────────────────┤
│       Crypto         │  Cifrado/descifrado PGP, gestión de claves
├──────────────────────┤
│       Network        │  WebSocket, protocolo de mensajes
├──────────────────────┤
│      Seguridad       │  Almacén de claves del SO (Keychain / DPAPI / libsecret)
└──────────────────────┘
```

Las dependencias fluyen hacia abajo: UI → ViewModel → Crypto/Network → Seguridad.
Nunca al revés. `Crypto` y `Network` no conocen la UI.

---

## Protocolo de comunicación (v0.8)

Capa de transporte: **WebSocket** (RFC 6455)
Formato de mensajes: **JSON** (UTF-8)
Cifrado de contenido: **OpenPGP** (RFC 4880)

### Flujo de descubrimiento de salas (antes de unirse)

```
Cliente                        Host
   │                             │
   │── { type: "listrooms" } ───►│
   │                             │
   │◄── { type: "roomsinfo",     │   lista de salas con tipo y
   │      rooms: [...] }         │   disponibilidad (sin nombres)
   │                             │
   │   [conexión cerrada]        │
   │                             │
   │   [el usuario elige sala]   │
```

### Flujo de una sesión 1:1

```
Cliente (join)                 Host
      │                             │
      │── WebSocket connect ────────►│
      │── { type: "hello",          │  intercambio de claves públicas
      │     version, room,          │  y versión de protocolo
      │     pubkey, alias }         │
      │                             │
      │◄── { type: "hello",         │
      │      pubkey, alias }        │
      │◄── { type: "roomlist",      │  lista de salas de grupo
      │      groups: [...] }        │  conocidas en el servidor
      │                             │
      │  [usuario verifica fingerprints fuera de banda]
      │                             │
      │── { type: "message",        │  mensajes cifrados con la
      │     id, payload,            │  clave pública del host
      │     timestamp }      ───────►│  firmados con clave privada propia
      │◄── { type: "message", ──────│
      │      ... }                  │
      │                             │
      │── { type: "bye" } ─────────►│  cierre limpio
```

### Flujo de sala de grupo

Cuando un segundo peer intenta entrar en una sala de grupo:

```
Cliente C                     Host A                    Cliente B
     │                             │                         │
     │── hello (room: "team") ────►│                         │
     │◄── hello ───────────────────│                         │
     │◄── pending ─────────────────│                         │
     │                             │── on_join_request ─────►│ (UI del host)
     │                             │◄── /allow C ────────────│
     │◄── approved ────────────────│                         │
     │◄── peerlist ────────────────│                         │
     │                             │                         │
     │── message ─────────────────►│── re-cifra para B ─────►│
     │◄── message (sender: B) ─────│◄── message ─────────────│
```

### Desconexión forzada (kick)

El host puede expulsar un peer en cualquier momento:

```
Host                           Cliente
  │                                │
  │── { type: "kick",              │
  │     reason: "..." } ──────────►│
  │                                │  [cliente cierra conexión]
  │   [host cierra su extremo]     │
```

Ver `docs/protocol.md` para la especificación completa de todos los tipos de mensaje,
campos obligatorios, códigos de error y consideraciones de seguridad.

---

## Modelo de salas

### Salas 1:1

- Admiten exactamente **un peer** simultáneo.
- Un segundo peer recibe error `4006` (sala ocupada).
- El host puede tener múltiples salas 1:1 activas en paralelo.
- El host usa `/switch <sala>` para alternar entre conversaciones.

### Salas de grupo

- Admiten **múltiples peers** con aprobación explícita del host.
- El host convierte una sala con `/group <sala>`.
- Nuevos peers reciben `pending` hasta que el host ejecuta `/allow <alias>`.
- El host puede mover peers entre salas con `/move <alias> <sala>` (preaprobado).
- Los mensajes son re-cifrados por el host para cada destinatario de la sala.
- Tras cada join/leave, el servidor envía `peerlist` a todos los peers de la sala.

### Descubrimiento de salas

- Los peers reciben la lista de salas de grupo del servidor tras conectarse (`roomlist`).
- Antes de unirse, pueden consultar todas las salas con sus estados (`listrooms`).
- La lista nunca expone nombres de usuarios conectados, solo conteos.

---

## Modelo de claves PGP

```
Cada usuario tiene:
  - 1 par de claves PGP (pública + privada)  RSA-4096
  - La clave privada NUNCA sale del dispositivo
  - La clave pública se intercambia en el handshake

Para cifrar un mensaje a B:
  cifrar(texto, pubkey_B) + firmar(texto, privkey_A)  →  Sign-then-Encrypt

Para descifrar un mensaje de A:
  descifrar(payload, privkey_B) + verificar_firma(payload, pubkey_A)
  → Discard si la firma es inválida; nunca mostrar contenido no verificado
```

El almacenamiento seguro de la clave privada usa el mecanismo nativo de cada OS:

| Plataforma | Mecanismo                             |
|------------|---------------------------------------|
| macOS      | Keychain Services                     |
| Windows    | DPAPI                                 |
| Linux      | libsecret (SecretService DBus)        |
| CLI        | Archivo `0600` en directorio de configuración (`platformdirs`) |

La passphrase protege la clave privada en disco y solo se mantiene en memoria
durante la sesión activa. Nunca se escribe a disco.

### Reset de identidad

Cada cliente debe ofrecer una forma de borrar el keypair y generar uno nuevo:

- **CLI:** `python -m stealth_cli --reset`
- **macOS:** botón "Reset identity" en la pantalla de desbloqueo y en el hub

El reset borra las claves del disco/Keychain, la configuración guardada, y arranca
el asistente de configuración. El fingerprint anterior queda invalidado; los peers
deberán verificar el nuevo fuera de banda.

---

## Decisiones de diseño

### Sin servidor central
**Decisión:** modelo peer-to-peer directo (uno actúa de host).
**Motivo:** elimina el riesgo de filtración de metadatos desde un servidor relay.
**Consecuencia:** el host debe tener una IP/puerto accesible. Se puede usar
Tailscale o port forwarding para conexiones por internet.

### Sin código compartido entre plataformas
**Decisión:** cada plataforma implementa el protocolo con su stack nativo.
**Motivo:** evitar dependencias cruzadas que complicarían el build y la distribución.
**Consecuencia:** la lógica de protocolo debe estar perfectamente especificada
en `docs/protocol.md` para garantizar la interoperabilidad.

### PGP sobre soluciones ad-hoc
**Decisión:** OpenPGP (RFC 4880) con librerías establecidas (pgpy, ObjectivePGP).
**Motivo:** estándar abierto, auditado, con soporte en todas las plataformas objetivo.
**Consecuencia:** las librerías PGP disponibles en cada plataforma son distintas;
la interoperabilidad depende de seguir el estándar, no de la librería.

### Verificación de identidad fuera de banda
**Decisión:** no hay PKI ni directorio de claves. La verificación es manual.
**Motivo:** cualquier servidor de claves centralizado es un punto de fallo y de confianza.
**Consecuencia:** los usuarios deben comparar fingerprints por otro canal (en persona,
por teléfono) antes de confiar en una conversación.

### Salas de grupo con relay en el host
**Decisión:** en salas de grupo el host re-cifra y reenvía los mensajes.
**Motivo:** los peers no tienen las claves públicas de otros peers, solo la del host.
**Consecuencia:** el host ve el plaintext de los mensajes durante el relay.
Esto está documentado y es inherente al modelo de confianza sin servidor de claves.

### Shutdown graceful
**Decisión:** enviar `bye` a todos los peers antes de cerrar la app.
**Motivo:** los peers no deben experimentar una caída silenciosa de la conexión.
**Consecuencia:** el cierre de la app puede tardar un ciclo de red; se usa
`applicationShouldTerminate` (macOS) para diferir la terminación hasta que
el shutdown async completa.
