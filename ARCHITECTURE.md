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
│   └── protocol.md       ← FUENTE DE VERDAD del protocolo
├── cli/                  ← Terminal (Python 3.10+)  ← funcional
├── macos/                ← App nativa macOS (Swift 5.9+ / SwiftUI)
├── windows/              ← App nativa Windows 11 (C# 12 / WinUI 3)
└── linux/                ← App nativa Linux GTK4 (Python 3.10+)
```

**Principio clave:** no hay código compartido entre plataformas. El contrato es
`docs/protocol.md`. Si dos clientes distintos pueden chatear entre sí, el
protocolo está bien implementado en ambos.

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

## Protocolo de comunicación (v0.5)

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
Cliente (join)                Host
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
     │                             │                         │
     │── message ─────────────────►│── re-cifra para B ─────►│
     │◄── message (sender: B) ─────│◄── message ─────────────│
```

Ver `docs/protocol.md` para la especificación completa de todos los tipos de mensaje,
campos obligatorios, códigos de error y consideraciones de seguridad.

---

## Modelo de salas (CLI)

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
  cifrar(texto, pubkey_B) + firmar(texto, privkey_A)

Para descifrar un mensaje de A:
  descifrar(payload, privkey_B) + verificar_firma(payload, pubkey_A)
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
**Decisión:** OpenPGP (RFC 4880) con librerías establecidas (pgpy, ObjectivePGP, PgpCore).
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
