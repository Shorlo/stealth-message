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

No hay relay, no hay broker, no hay servidor de mensajes. Los mensajes cifrados
solo pasan por las máquinas de los participantes.

---

## Estructura del monorepo

```
stealth-message/
├── docs/
│   └── protocol.md       ← FUENTE DE VERDAD del protocolo
├── cli/                  ← Terminal (Python 3.10+)
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

## Protocolo de comunicación

Capa de transporte: **WebSocket** (RFC 6455)
Formato de mensajes: **JSON** (UTF-8)
Cifrado de contenido: **OpenPGP** (RFC 4880)

### Flujo de una sesión

```
Cliente A (host)              Cliente B (join)
      │                             │
      │◄── WebSocket connect ───────│
      │                             │
      │◄── { type: "hello",  ───────│  intercambio de claves públicas
      │       pubkey, alias }       │  y versión de protocolo
      │─── { type: "hello",  ──────►│
      │       pubkey, alias }       │
      │                             │
      │  [usuario verifica fingerprints fuera de banda]
      │                             │
      │◄── { type: "message", ──────│  mensajes cifrados con la
      │       id, payload,          │  clave pública del destinatario
      │       timestamp }           │  y firmados con la propia clave privada
      │─── { type: "message", ─────►│
      │       ... }                 │
      │                             │
      │─── { type: "bye" } ────────►│  cierre limpio
      │                             │
```

Ver `docs/protocol.md` para la especificación completa de todos los tipos de mensaje,
campos obligatorios, códigos de error y consideraciones de seguridad.

---

## Modelo de claves PGP

```
Cada usuario tiene:
  - 1 par de claves PGP (pública + privada)
  - La clave privada NUNCA sale del dispositivo
  - La clave pública se intercambia en el handshake

Para cifrar un mensaje a B:
  cifrar(texto, pubkey_B) + firmar(texto, privkey_A)

Para descifrar un mensaje de A:
  descifrar(payload, privkey_B) + verificar_firma(payload, pubkey_A)
```

El almacenamiento seguro de la clave privada usa el mecanismo nativo de cada OS:

| Plataforma | Mecanismo           |
|------------|---------------------|
| macOS      | Keychain Services   |
| Windows    | DPAPI               |
| Linux      | libsecret (SecretService DBus) |
| CLI        | Archivo `0600` en directorio de configuración |

---

## Decisiones de diseño

### Sin servidor central
**Decisión:** modelo peer-to-peer directo (uno actúa de host).
**Motivo:** elimina el riesgo de filtración de metadatos desde un servidor relay.
**Consecuencia:** el host debe tener una IP/puerto accesible. Futuras versiones
pueden añadir soporte a través de NAT.

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
