# Política de seguridad

## Alcance

Este documento cubre la política de seguridad de `stealth-message` en todos sus
subproyectos: CLI (Python), macOS (Swift), Windows (C#) y Linux (Python/GTK4).

---

## Versiones soportadas

| Versión    | Soporte de seguridad |
|------------|----------------------|
| `main`     | Activo               |
| < 1.0.0    | Sin soporte (pre-release) |

---

## Reporte de vulnerabilidades

**No abrir issues públicos para reportar vulnerabilidades de seguridad.**

Para reportar una vulnerabilidad, contactar de forma privada:

- **Email:** *(añadir dirección de contacto del mantenedor)*
- **Asunto:** `[SECURITY] stealth-message — descripción breve`

Se responderá en un plazo máximo de **72 horas** con la confirmación de recepción.

### Qué incluir en el reporte

1. Descripción del problema y su impacto potencial.
2. Pasos para reproducirlo (PoC si es posible).
3. Versión o commit afectado.
4. Posible mitigación o solución propuesta (opcional).

### Proceso de divulgación responsable

1. Se recibe el reporte de forma privada.
2. Se confirma la vulnerabilidad y se evalúa el impacto.
3. Se desarrolla y prueba la corrección.
4. Se publica la corrección junto con un advisory.
5. Se acredita al investigador (salvo solicitud de anonimato).

---

## Principios de seguridad del proyecto

### Claves privadas
- Las claves privadas PGP **nunca abandonan el dispositivo del usuario**.
- Se almacenan en el almacén seguro del sistema operativo:
  - macOS: Keychain Services (`kSecAttrAccessibleWhenUnlockedThisDeviceOnly`)
  - Windows: DPAPI (`ProtectedData.Protect`, scope `CurrentUser`)
  - Linux: libsecret (SecretService DBus)
  - CLI: archivo con permisos `0600` en el directorio de configuración
- Las passphrases existen solo en memoria durante la sesión activa. **Nunca en disco.**

### Cifrado de mensajes
- Todos los mensajes se cifran con la clave pública del destinatario antes de enviarse.
- Todos los mensajes se firman con la clave privada del emisor.
- Los mensajes con firma inválida se descartan y se notifica al usuario.
- El transporte es WebSocket; se recomienda usar WSS (TLS) en redes no confiables.

### Verificación de identidad
- No hay PKI centralizada ni directorio de claves.
- Los usuarios **deben verificar los fingerprints de las claves por un canal independiente**
  (en persona, por teléfono) antes de confiar en una conversación.
- La UI debe mostrar siempre el fingerprint completo (40 caracteres en grupos de 4).

### Información sensible en el código
- Ningún campo sensible (passphrase, clave privada, fingerprint de tests) debe aparecer
  en logs, consola, clipboard o archivos de configuración de tests.
- Las passphrases en UI usan siempre campos de contraseña (`SecureField`, `PasswordBox`,
  `Gtk.Entry.set_visibility(False)`, `prompt_toolkit` con `is_password=True`).

### Dependencias
- Minimizar dependencias de terceros, especialmente en módulos crypto.
- Las dependencias de criptografía deben ser librerías establecidas y auditadas.
- Revisar las dependencias ante nuevas vulnerabilidades (CVEs) antes de cada release.

---

## Amenazas fuera del alcance actual

Las siguientes amenazas están fuera del alcance de la versión actual (v0.x):

- **Forward secrecy:** los mensajes cifrados con una clave comprometida son descifrable
  retroactivamente. Una futura versión (v2) introducirá claves de sesión efímeras.
- **NAT traversal / relay:** la conexión directa requiere que el host sea accesible.
  No hay soporte para TURN ni relay en esta versión.
- **Anonimato de red:** las IPs de los participantes son visibles entre ellos.
  No hay integración con Tor ni redes de anonimato.
- **Protección contra análisis de tráfico:** los metadatos de red (tamaño, timing)
  no se ofuscan en esta versión.
