# stealth-message/macos — CLAUDE.md

App nativa para macOS usando Swift y SwiftUI. Plataforma prioritaria del proyecto.
Lee también el CLAUDE.md raíz del monorepo antes de trabajar en este subproyecto.

## Stack

- **Lenguaje**: Swift 5.9+
- **UI**: SwiftUI (con AppKit solo cuando SwiftUI no llegue)
- **Concurrencia**: Swift Concurrency — `async/await` + `Actor`. Sin callbacks ni GCD.
- **PGP**: ObjectivePGP (via Swift Package Manager)
- **Red**: `URLSessionWebSocketTask` (Network.framework, sin dependencias externas)
- **Claves seguras**: Keychain Services — las claves privadas nunca salen del Keychain
- **Build**: Swift Package Manager (Package.swift) — compatible con VSCode + extensión Swift
- **Tests**: XCTest + Swift Testing
- **Mínimo macOS**: 13.0 (Ventura)

## Entorno de desarrollo

Este subproyecto está estructurado como un **Swift Package Manager package** para
poder trabajar en VSCode con la extensión oficial Swift (swiftlang.swift-vscode).

Para compilar y ejecutar en el simulador o para gestionar entitlements y distribución,
abrir el directorio en Xcode. Los dos entornos son compatibles con el mismo Package.swift.

```bash
# Instalar extensión Swift en VSCode (si no está instalada)
# Buscar "swiftlang.swift-vscode" en el marketplace de VSCode

# Compilar desde terminal
cd macos
swift build

# Ejecutar tests
swift test

# Abrir en Xcode cuando sea necesario
open Package.swift
```

## Estructura

```
macos/
├── CLAUDE.md
├── Package.swift             ← definición SPM: targets, dependencias, plataforma mínima
├── Sources/
│   └── StealthMessage/
│       ├── App/
│       │   └── StealthMessageApp.swift   ← @main, WindowGroup
│       ├── Views/
│       │   ├── ContentView.swift         ← vista raíz, navegación principal
│       │   ├── SetupView.swift           ← wizard de primer uso (generar clave PGP)
│       │   ├── ChatView.swift            ← vista de conversación activa
│       │   └── ContactFingerprintView.swift ← muestra fingerprint para verificación
│       ├── ViewModels/
│       │   ├── SetupViewModel.swift
│       │   └── ChatViewModel.swift
│       ├── Crypto/
│       │   ├── PGPKeyManager.swift       ← generar, cargar, exportar claves (Keychain)
│       │   └── MessageCrypto.swift       ← cifrar/descifrar según protocol.md §2.1
│       ├── Network/
│       │   ├── StealthServer.swift       ← WebSocket host (protocol.md §1–§4)
│       │   └── StealthClient.swift       ← WebSocket join
│       ├── Models/
│       │   ├── Message.swift             ← struct Codable para mensajes del protocolo
│       │   └── Contact.swift             ← alias + clave pública verificada
│       └── Persistence/
│           └── KeychainManager.swift     ← wrapper de Keychain Services
└── Tests/
    └── StealthMessageTests/
        ├── CryptoTests.swift
        └── NetworkTests.swift
```

## Convenciones de código Swift

- **SwiftUI idiomático**: vistas pequeñas y componibles. Nada de lógica de negocio en las vistas.
- **MVVM estricto**: toda lógica va en ViewModels marcados con `@MainActor`.
- **Swift Concurrency**: `async/await` y `Actor` para todo. Prohibido `DispatchQueue.main.async`.
- **Keychain obligatorio** para claves privadas. Nunca `UserDefaults`, nunca disco sin cifrar.
- **Manejo de errores**: `throws` + `do/catch`. Nunca `try!` en producción. `try?` solo
  cuando el fallo es genuinamente irrelevante.
- **Accesibilidad**: añadir `.accessibilityLabel` en controles custom.
- **Comentarios**: solo donde el "por qué" no es obvio. El código debe ser autodocumentado.

## Implementación del protocolo

Este subproyecto implementa `docs/protocol.md` completo.
Referencias directas por sección:

- Handshake → `Network/StealthServer.swift` y `Network/StealthClient.swift` (§1)
- Cifrado → `Crypto/MessageCrypto.swift` (§2.1)
- Ping/pong y bye → módulos de Network (§3)
- Códigos de error → `Models/Message.swift` enum ProtocolError (§4)

## Seguridad

- La clave privada PGP se genera una sola vez y se almacena en Keychain con
  `kSecAttrAccessibleWhenUnlockedThisDeviceOnly`.
- La passphrase del Keychain no se expone nunca a la capa de UI.
- El campo de passphrase en SetupView usa `.textContentType(.password)` y
  `SecureField` — nunca `TextField`.
- Al mostrar el fingerprint de una clave, usar siempre formato de 40 chars en grupos de 4.

## Notas para Claude Code

- Estructurar el Package.swift con un target ejecutable (`StealthMessage`) y un target
  de librería (`StealthMessageCore`) para que los tests puedan importar el core sin
  instanciar la app completa.
- `MessageCrypto.swift` debe tener una API puramente funcional: funciones que reciben
  datos y devuelven datos. Sin estado. Más fácil de testear.
- Los ViewModels son `@MainActor` pero los métodos de Network y Crypto son `async` y
  se ejecutan en sus propios actores — llamarlos con `await` desde el ViewModel.
- No usar `@AppStorage` para nada relacionado con seguridad.
- Objective-C bridging para ObjectivePGP: crear un wrapper Swift limpio en
  `Crypto/PGPKeyManager.swift` para que el resto del código no vea la API ObjC.
