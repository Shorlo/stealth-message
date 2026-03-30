# stealth-message — Especificación del protocolo v0.1

> **Este documento es la fuente de verdad.**
> Toda implementación (CLI, macOS, Windows, Linux) debe seguirlo exactamente.
> Si hay contradicción entre el código y este documento, el documento manda.
> Para proponer cambios, actualizar este archivo primero y luego el código.

---

## Visión general

El transporte es **WebSocket** (RFC 6455). Los mensajes son objetos **JSON** codificados
en UTF-8. El cifrado es **OpenPGP** (RFC 4880) aplicado al campo `payload` de cada mensaje.

Modelo de conexión: uno de los participantes actúa como **host** (levanta el servidor
WebSocket) y el resto se conectan como **clientes**. No hay servidor central.

---

## 1. Establecimiento de conexión

### 1.1 Handshake inicial

Nada más establecerse la conexión WebSocket, ambas partes deben intercambiar sus
identidades. El cliente envía primero:

```json
{
  "type": "hello",
  "version": "1",
  "room": "<nombre de sala, máx. 64 chars, opcional — por defecto \"default\">",
  "alias": "<nombre visible, máx. 64 chars, UTF-8>",
  "pubkey": "<clave pública PGP en formato ASCII-armored, Base64 URL-safe>"
}
```

El servidor responde con el mismo formato (sin `room`):

```json
{
  "type": "hello",
  "version": "1",
  "alias": "<nombre visible del host>",
  "pubkey": "<clave pública PGP del host, ASCII-armored>"
}
```

**Reglas:**
- Si `version` no es `"1"`, la parte receptora debe cerrar la conexión con código 4001.
- El campo `room` identifica la sala de chat a la que el cliente quiere conectarse.
  Es opcional; si se omite, se usa `"default"`.
- Cada sala admite exactamente **un peer simultáneo**. Si la sala ya está ocupada,
  el servidor rechaza con código 4006 antes de enviar su propio hello.
- Si el servidor tiene salas predefinidas y el room solicitado no existe,
  rechaza con código 4007.
- El `alias` es solo para mostrar en la UI. No tiene valor criptográfico.
- La autenticidad del interlocutor se verifica mediante la huella (fingerprint) de su clave
  pública, que debe mostrarse al usuario para verificación manual fuera de banda.
- El handshake debe completarse en menos de 10 segundos o la conexión se cierra.

---

## 2. Mensajes de chat

### 2.1 Mensaje cifrado

```json
{
  "type": "message",
  "id": "<UUID v4>",
  "payload": "<mensaje OpenPGP cifrado y firmado, ASCII-armored, Base64 URL-safe>",
  "timestamp": 1712000000000
}
```

**Campos:**
- `id`: UUID v4 generado por el emisor. Sirve para deduplicación.
- `payload`: el texto del mensaje cifrado con la clave pública del destinatario y firmado
  con la clave privada del emisor. El texto plano antes de cifrar es una cadena UTF-8.
- `timestamp`: Unix timestamp en milisegundos (UTC) en el momento del envío.

**Proceso de cifrado (emisor):**
1. Tomar el texto plano del mensaje (string UTF-8).
2. Cifrar con la clave pública del destinatario (obtenida en el handshake).
3. Firmar con la propia clave privada.
4. Serializar en ASCII-armored y codificar en Base64 URL-safe.

**Proceso de descifrado (receptor):**
1. Decodificar Base64, obtener el bloque ASCII-armored.
2. Descifrar con la propia clave privada.
3. Verificar la firma con la clave pública del emisor (obtenida en el handshake).
4. Mostrar el texto plano solo si la firma es válida.

Si la firma no es válida, descartar el mensaje y notificar al usuario con una advertencia.

---

## 3. Control de sesión

### 3.1 Cierre limpio

Antes de cerrar la conexión intencionalmente:

```json
{
  "type": "bye"
}
```

### 3.2 Keep-alive

Para mantener la conexión activa en redes con timeout agresivo:

```json
{ "type": "ping" }
```

Respuesta obligatoria:

```json
{ "type": "pong" }
```

El intervalo de ping recomendado es 30 segundos. Si no se recibe `pong` en 10 segundos,
la implementación debe considerar la conexión caída y notificar al usuario.

---

## 4. Gestión de errores

### 4.1 Mensaje de error

Cuando una parte recibe un mensaje malformado o no puede procesarlo:

```json
{
  "type": "error",
  "code": 4002,
  "reason": "<descripción breve en inglés>"
}
```

**Códigos de error definidos:**

| Código | Significado                                        |
|--------|----------------------------------------------------|
| 4001   | Versión del protocolo incompatible                 |
| 4002   | Mensaje malformado (JSON inválido o campos missing)|
| 4003   | Firma PGP inválida                                 |
| 4004   | Error de descifrado (clave incorrecta u otro)      |
| 4005   | Timeout en el handshake                            |
| 4006   | Sala llena (ya hay un peer conectado en esa sala)  |
| 4007   | Sala no encontrada en este servidor                |
| 4008   | Solicitud de entrada denegada o expirada (sala de grupo) |

Tras enviar un error de código 4001, la conexión debe cerrarse.
Los errores 4002–4005 son recuperables; la sesión puede continuar.

---

## 5. Formato general de un mensaje

Todo mensaje tiene obligatoriamente el campo `type`. El resto de campos dependen del tipo.

| type      | Dirección          | Campos adicionales obligatorios         |
|-----------|--------------------|-----------------------------------------|
| hello     | ambas partes       | version, alias, pubkey (+ room en cliente) |
| message   | emisor → receptor  | id, payload, timestamp (+ sender en reenvíos de grupo) |
| listrooms | cliente → servidor | — (solicita la lista de salas antes de unirse)          |
| roomsinfo | servidor → cliente | rooms (lista de salas con tipo y disponibilidad, sin nombres de peers) |
| roomlist  | servidor → cliente | groups (lista de nombres de salas de grupo descubribles) |
| pending   | servidor → cliente | — (sala de grupo ocupada, esperando aprobación del host) |
| approved  | servidor → cliente | — (host aprobó la entrada)              |
| move      | servidor → cliente | room (host solicita cambio de sala)     |
| bye       | cualquiera         | —                                       |
| ping      | cualquiera         | —                                       |
| pong      | respuesta a ping   | —                                       |
| error     | cualquiera         | code, reason                            |

Mensajes con `type` desconocido deben ignorarse silenciosamente (para compatibilidad futura).

---

## 6. Consideraciones de seguridad

- **Sin servidor de relay central.** El host es siempre un participante de la conversación,
  nunca un tercero.
- **Verificación de identidad fuera de banda.** Los usuarios deben comparar los fingerprints
  de sus claves por un canal independiente (en persona, por teléfono) antes de confiar
  en una conversación.
- **Sin persistencia en el servidor.** El host no debe almacenar mensajes ajenos en disco.
- **Claves efímeras opcionales.** Una futura versión del protocolo (v2) podrá introducir
  un mecanismo de forward secrecy mediante claves de sesión efímeras.

---

## 7. Historial de versiones

| Versión | Fecha      | Cambios                        |
|---------|------------|--------------------------------|
| 0.1     | 2026-03    | Borrador inicial               |
| 0.2     | 2026-03    | Sistema de salas (room): campo room en hello, códigos 4006 y 4007, límite 1 peer/sala |
| 0.3     | 2026-03    | Salas de grupo: mensajes pending/approved/move, código 4008, aprobación del host |
| 0.4     | 2026-03    | Descubrimiento de salas de grupo: mensaje roomlist (servidor → cliente) |
| 0.5     | 2026-03    | Consulta de salas antes de unirse: listrooms / roomsinfo (sin nombres de peers) |
