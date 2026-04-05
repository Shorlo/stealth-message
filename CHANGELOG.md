# Changelog

Todos los cambios notables de este proyecto se documentan en este archivo.

El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.0.0/),
y el proyecto usa [Semantic Versioning](https://semver.org/lang/es/).

---

## [Unreleased]

### Added
- `docs/protocol.md`: documented `peerlist` message type (v0.6). Sent by the
  server to all peers in a group room after each join/leave event; contains the
  alias and fingerprint of every other peer currently in the room.

### Fixed
- `ui/chat.py`: `/switch <room>` in host mode now lists all connected peers one
  per line instead of showing only the last one.
- `ui/chat.py`: host-mode `on_disconnected` now also removes the peer from
  `peer_fingerprints`, preventing stale fingerprints from appearing in `/fp`
  after a peer moves to another room.
- `ui/chat.py`: `/fp` in a group room now shows the fingerprint of every peer
  in the room, not just the first one. This applies to both the host and to
  non-host peers: the server now broadcasts a `peerlist` message (alias +
  fingerprint of each other peer) to all group room members whenever someone
  joins or leaves, so every participant has an up-to-date view.
- `ui/chat.py`: `/rooms` in join mode now queries the server live via
  `query_rooms()` and shows all rooms with their real status (available,
  occupied, group), matching the room list shown during the connection wizard.
- `network/server.py`: group-room join approval now waits outside
  `HANDSHAKE_TIMEOUT` (10 s). Previously the host's 60 s approval window was
  inadvertently capped at 10 s, causing the server to close the connection
  before the host could type `/allow <alias>`, which made every approval appear
  as "join request denied by host" on the client side.
- `network/server.py`: group rooms now require host approval for every peer,
  including the first one. Previously the approval gate was only triggered when
  the room already had peers (`if existing and is_group`), so the first peer to
  join an empty group room bypassed approval entirely.

### Changed
- `network/server.py`: replaced deprecated `asyncio.get_event_loop()` with
  `asyncio.get_running_loop()` in `make_group_room()`.
- `ui/chat.py`: extracted `_make_join_client(room_id)` — single factory that
  creates a `StealthClient` and wires all six callbacks (`on_message`,
  `on_disconnected`, `on_pending`, `on_approved`, `on_move`, `on_roomlist`).
  Eliminates duplicated callback blocks in `run_join`, `_switch_join_room`, and
  `_reconnect_to_room`, and fixes the missing `on_move` / `on_pending` /
  `on_approved` callbacks that were absent in `_reconnect_to_room`.
- `ui/chat.py`: extracted `_make_send_fn(room_id)` — replaces three identical
  inline closures (`_make_send_new`, `_make_send_g`, `_make_send_m`) that
  existed inside `_input_loop`.
- `ui/chat.py`: extracted `_dispatch_command(text)` — all command parsing
  (`/quit`, `/fp`, `/help`, `/rooms`, `/new`, `/switch`, `/allow`, `/deny`,
  `/group`, `/move`, `/pending`) moved out of `_input_loop` into a dedicated
  async method. `_input_loop` now delegates to it in three lines.

### Changed
- `README.md`: actualizado con características actuales, inicio rápido y ejemplo de uso
- `ARCHITECTURE.md`: actualizado con modelo de salas, flujo de descubrimiento,
  flujo de sala de grupo y decisión de diseño sobre relay en host
- `__main__.py` (`--manual`): manual actualizado — descubrimiento de salas,
  `/rooms` con salas conocidas, ejemplos con grupo/move, tabla de seguridad ampliada,
  `ws://` automático documentado

### Fixed
- `__main__.py`: la URI introducida sin prefijo `ws://` (e.g. `192.168.1.10:8765`) se
  normaliza automáticamente — aplica tanto al modo interactivo como al flag `--join`

### Added
- **Consulta de salas al unirse (modo interactivo)**: tras introducir la URI del servidor,
  se muestra automáticamente la lista de salas disponibles con tipo y estado antes de
  preguntar a qué sala unirse. Nunca se muestran nombres de usuarios conectados.
  - Salas 1:1: `available` / `occupied`
  - Salas de grupo: `host + N users`
  - `network/server.py`: maneja `listrooms` antes del handshake; responde con `roomsinfo`
    (`_rooms_info`, `_handle_listrooms`). `_do_handshake` acepta `first_msg` ya leído.
  - `network/client.py`: función standalone `query_rooms(uri)`.
  - `__main__.py`: `_print_room_list(uri)` llama a `query_rooms` y renderiza tabla Rich.
  - `docs/protocol.md`: mensajes `listrooms` / `roomsinfo`, versión 0.5.
- **Descubrimiento de salas de grupo**: los peers ven en `/rooms` todas las salas de grupo
  del servidor aunque no estén en ellas — pueden hacer `/switch <sala>` para solicitar
  entrada (el host debe aprobar si la sala ya tiene usuarios)
  - `network/server.py`: nuevo mensaje `roomlist` enviado tras el handshake y cada vez
    que se crea o convierte una sala de grupo. Métodos `_send_roomlist_to` y
    `_broadcast_roomlist`.
  - `network/client.py`: maneja `roomlist`, nuevo callback `on_roomlist(list[str])`.
  - `ui/chat.py`: `_update_known_groups` actualiza `_room_states`; `_print_rooms` muestra
    `[yellow]group[/yellow]  /switch to join` para salas conocidas pero no unidas.
  - `docs/protocol.md`: mensaje `roomlist`, versión 0.4.

### Fixed
- `network/client.py`, `ui/chat.py`: en sala de grupo, los mensajes reenviados mostraban
  el nombre del host en lugar del emisor real — el cliente ahora lee el campo `sender`
  del frame y lo usa como alias en la UI
- `ui/chat.py`: la lista de comandos ya no se muestra cada vez que un peer se conecta
  en modo host — solo aparece en el banner inicial y al escribir `/help`
- `ui/chat.py`: `/move` desconectaba la sesión entera del peer — al hacer `/switch` o `/move`,
  el `_recv_task` del cliente antiguo disparaba `on_disconnected` en su bloque `finally`,
  poniendo `_stop_event` y cerrando el chat. Corregido anulando `on_disconnected` del cliente
  viejo antes de llamar a `disconnect()`.

### Changed
- `ui/chat.py`: `_print_help` reescrita con una tabla Rich (`Table.grid`) en lugar de
  texto inline — los comandos se muestran en dos columnas alineadas (comando + descripción)
- `__main__.py`: manual de usuario — sustituidos nombres de ejemplo (Shorlo/Pepe/Juan)
  por nombres genéricos (Alice/Bob/Carol) y sala `sala` por `team`

### Added
- **Sistema de salas (rooms)**: el host puede crear múltiples salas independientes
  (`--rooms bob,carol`); cada sala admite exactamente un peer simultáneo.
  - `network/server.py`: `StealthServer` acepta `rooms: list[str] | None`.
    Nuevo dict `_rooms: dict[room_id, PeerSession]` en lugar del antiguo `_peers`.
    Nuevo método `send_to_room(room_id, plaintext)`.  Firmas de callbacks ampliadas
    con `room_id` como tercer parámetro.  Nuevo property `room_peers`.
    Errores 4006 (sala llena) y 4007 (sala no encontrada).
  - `network/client.py`: `connect(uri, room_id="default")` envía el campo `room`
    en el hello.  Nuevo property `room_id`.  Detecta respuestas de error del servidor
    durante el handshake (4006/4007) y las propaga como `ProtocolError`.
  - `ui/chat.py`: UI multi-sala — prompt muestra la sala activa (`[Shorlo@pepe]`),
    mensajes etiquetados con `[sala]`, comandos `/switch <room>`, `/rooms`, `/next`.
    `ChatScreen` acepta `room_ids: list[str]`.  `run_chat` acepta `rooms` y `room`.
  - `__main__.py`: flags `--rooms` (host) y `--room` (join); `_prompt_mode` pregunta
    salas de forma interactiva.
  - `docs/protocol.md`: campo `room` en hello del cliente, códigos 4006 y 4007,
    versión 0.2 del protocolo.
  - `tests/test_network.py`: 7 tests nuevos — room full (4006), room not found (4007),
    aislamiento entre salas, dos peers en salas distintas, `send_to_room` vacía,
    `room_peers`, servidor abierto acepta cualquier sala.

### Fixed
- `ui/chat.py`: markup `[dim]...[/dim]` se imprimía como texto literal en el banner
  de conexión del host — cambiado a `Text.from_markup()` en todos los sitios afectados
- `ui/chat.py`: la lista de comandos no aparecía al conectarse un peer en modo host —
  ahora se encola en `on_connected` junto con el banner de fingerprint
- `ui/chat.py`: `/rooms` se enviaba como mensaje en lugar de consumirse como comando
- `ui/chat.py`: banner de join mostraba `Connected to [room1] Shorlo`; ahora muestra
  `Connected to Shorlo  [room: room1]`
- `ui/chat.py`: UI de salas activada con 1 sola sala nombrada (antes requería ≥2)
- `network/server.py`: `_allowed_rooms` cambiado de `frozenset` a `set` para mutabilidad
- `ui/chat.py`: `/rooms` imprimía `[dim]waiting for peer…[/dim]` literal — `_print_rooms`
  usaba `Text.assemble()` que no parsea markup; reescrito con `console.print()` y markup
- `__main__.py`: manual de usuario actualizado con salas, salas de grupo, ejemplos con
  3 participantes, tabla de comandos host vs. todos, modelo de seguridad ampliado
- `ui/chat.py`: la línea raw del prompt se borra con escape ANSI `\x1b[1A\x1b[2K`
  antes de imprimir el mensaje propio formateado con hora y sala; restaurado `_print_outgoing`

### Added
- **Salas de grupo (group rooms)**: múltiples peers por sala con aprobación del host
  - `network/server.py`: `StealthServer(group_rooms=[...])`, `make_group_room()`,
    `approve_join()`, `deny_join()`, `pending_requests`, `move_peer(alias, room)`.
    Nuevo callback `on_join_request(alias, fp, room_id)`. Mensajes `pending`, `approved`,
    `move`. Reenvío automático entre peers del mismo grupo. Código de error 4008.
  - `network/client.py`: `_approval_loop` — bloquea `connect()` hasta que el host
    aprueba o deniega. Callbacks `on_pending`, `on_approved`, `on_move`.
  - `ui/chat.py`: host recibe notificación de solicitud de entrada con fingerprint.
    Comandos `/allow <alias>`, `/deny <alias>`, `/group <room>`, `/move <alias> <room>`,
    `/pending`. Cliente muestra "Waiting for host approval…" y "Approved!" automáticamente.
    `/move` del host desencadena `_switch_join_room` automático en el cliente.
  - `docs/protocol.md`: mensajes `pending`, `approved`, `move`; código 4008; versión 0.3.
  - `tests/test_network.py`: 4 tests nuevos — aprobación, denegación (4008), reenvío
    de mensajes en grupo, `move_peer` pre-aprueba (64/64 tests pasando).

### Added
- `network/server.py`: método `add_room(room_id)` — añade una sala en caliente
- `ui/chat.py`: `/switch <room>` en modo join — desconecta del room actual y conecta
  al nuevo; si el room está lleno (4006) muestra "Room already occupied" y reconecta
  al room anterior; si no existe (4007) igual; `_switch_join_room` y `_reconnect_to_room`
- `ui/chat.py`: comando `/new <room>` en modo host — crea una sala nueva sin reiniciar
- `ui/chat.py`: `/help` e `/rooms` siempre disponibles en modo host
- `ui/chat.py`: banner de inicio del host muestra la URL de conexión y los comandos
- `__main__.py`: suprimidos warnings de pgpy que aparecían en pantalla durante el chat
  (compresión, self-sigs, revocación, flags, TripleDES) — son limitaciones internas de
  pgpy que no afectan al cifrado ni a la firma
- `ui/chat.py`: bucle infinito del prompt — el `asyncio.wait_for` con timeout 0.2s
  cancelaba y reiniciaba `prompt_async` continuamente, imprimiendo el prompt en una
  línea nueva cada vez. Reemplazado por `asyncio.wait(FIRST_COMPLETED)` con una tarea
  para el prompt y otra para el stop event; el prompt ya no se interrumpe nunca.

### Added
- `.vscode/settings.json`: intérprete Python apuntado al `.venv` de `cli/` para resolver warnings de Pylance
- `--manual` flag en `__main__.py`: manual de usuario completo renderizado con Rich (configuración, modos host/join, internet, comandos de chat, seguridad, flags)
- `cli/stealth_cli/ui/setup.py`: wizard de primer uso — alias, passphrase con confirmación, RSA-4096 con spinner, muestra fingerprint
- `cli/stealth_cli/ui/chat.py`: pantalla de chat Rich + prompt_toolkit — modo host y join, mensajes entrantes sin romper el input, `/fp`, `/help`, `/quit`
- `cli/stealth_cli/__main__.py`: punto de entrada completo — detección primer uso, validación de passphrase, selección de modo interactiva o por flags `--host`/`--join`
- `cli/stealth_cli/config.py`: persistencia de claves con platformdirs — `save_keypair`, `load_*`, permisos 0600 en clave privada
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
