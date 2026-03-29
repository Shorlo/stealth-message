# stealth-message/windows — CLAUDE.md

App nativa para Windows 11 usando C# y WinUI 3. Plataforma prioritaria 2.
Lee también el CLAUDE.md raíz del monorepo antes de trabajar en este subproyecto.

## Stack

- **Lenguaje**: C# 12 + .NET 8
- **UI**: WinUI 3 (Windows App SDK) — Fluent Design nativo de Windows 11
- **Concurrencia**: `async/await` + `Task`. Sin `Thread` manual ni `BackgroundWorker`.
- **PGP**: `PgpCore` (NuGet) — wrapper limpio sobre BouncyCastle
- **Red**: `System.Net.WebSockets.ClientWebSocket` (nativo .NET, sin dependencias externas)
- **Claves seguras**: Windows DPAPI (`System.Security.Cryptography.ProtectedData`)
- **Build**: MSBuild via `dotnet` CLI — compatible con VSCode + extensión C#
- **Tests**: xUnit + Moq
- **Mínimo**: Windows 10 22H2 / Windows 11
- **Distribución**: MSIX (recomendado) o instalador WiX

## Entorno de desarrollo

El proyecto puede editarse en VSCode con la extensión C# (ms-dotnettools.csharp)
o en Visual Studio 2022 Community (gratuito). Para el diseñador XAML visual
se necesita Visual Studio, pero el código puede escribirse y compilarse desde VSCode.

```bash
# Instalar extensión C# en VSCode:
# Buscar "ms-dotnettools.csharp" en el marketplace

# Compilar
cd windows
dotnet build

# Ejecutar tests
dotnet test

# Restaurar paquetes NuGet
dotnet restore
```

## Estructura

```
windows/
├── CLAUDE.md
├── StealthMessage.sln
├── StealthMessage/
│   ├── StealthMessage.csproj       ← proyecto principal WinUI 3
│   ├── App.xaml(.cs)               ← punto de entrada, configuración de la app
│   ├── Views/
│   │   ├── MainWindow.xaml(.cs)    ← ventana principal, navegación
│   │   ├── SetupPage.xaml(.cs)     ← wizard de primer uso
│   │   ├── ChatPage.xaml(.cs)      ← pantalla de conversación activa
│   │   └── FingerprintPage.xaml(.cs) ← verificación de fingerprint
│   ├── ViewModels/
│   │   ├── ViewModelBase.cs        ← INotifyPropertyChanged, RelayCommand
│   │   ├── SetupViewModel.cs
│   │   └── ChatViewModel.cs
│   ├── Crypto/
│   │   ├── PgpKeyManager.cs        ← generar, cargar, exportar claves (DPAPI)
│   │   └── MessageCrypto.cs        ← cifrar/descifrar según protocol.md §2.1
│   ├── Network/
│   │   ├── StealthServer.cs        ← WebSocket host (protocol.md §1–§4)
│   │   └── StealthClient.cs        ← WebSocket join
│   ├── Models/
│   │   ├── Message.cs              ← record/class para mensajes del protocolo
│   │   └── Contact.cs              ← alias + clave pública verificada
│   └── Security/
│       └── DpapiManager.cs         ← wrapper DPAPI para persistencia de claves
└── StealthMessage.Tests/
    ├── StealthMessage.Tests.csproj
    ├── CryptoTests.cs
    └── NetworkTests.cs
```

## Convenciones de código C#

- **MVVM estricto**: ninguna lógica de negocio en code-behind (`.xaml.cs`).
  Solo inicialización del ViewModel y navegación.
- **Nullable references habilitadas** en el `.csproj` (`<Nullable>enable</Nullable>`).
  Sin `!` innecesarios. Gestionar nulos explícitamente.
- **`async/await`** para todo I/O. Nunca `.Result` ni `.Wait()` — causa deadlocks en UI.
- **Records** para modelos inmutables (`Message`, `Contact`).
- **`ILogger<T>`** de Microsoft.Extensions.Logging para logging. Nunca `Console.WriteLine`.
- **DPAPI obligatorio** para claves privadas en disco. Nunca texto plano.
- Sufijos de convención: `ViewModel`, `Service`, `Manager`, `Page`, `View`.

## Implementación del protocolo

Este subproyecto implementa `docs/protocol.md` completo.
Referencias directas por sección:

- Handshake → `Network/StealthServer.cs` y `Network/StealthClient.cs` (§1)
- Cifrado → `Crypto/MessageCrypto.cs` (§2.1)
- Ping/pong y bye → módulos de Network (§3)
- Códigos de error → `Models/ProtocolError.cs` enum (§4)

## Seguridad

- La clave privada PGP se cifra con DPAPI (`ProtectedData.Protect`) antes de escribirla
  en `%APPDATA%\stealth-message\keys\`. El scope es `CurrentUser`.
- La passphrase PGP solo vive en memoria (`SecureString`) durante la sesión.
  Se descarta explícitamente con `Dispose()` al cerrar la app.
- Los campos de passphrase en XAML usan `PasswordBox`, nunca `TextBox`.
- Al mostrar fingerprints usar siempre formato 40 chars en grupos de 4.

## Notas para Claude Code

- En WinUI 3 el dispatcher es `DispatcherQueue`, no `Dispatcher`. Para actualizar la UI
  desde un hilo de background: `dispatcherQueue.TryEnqueue(() => { ... })`.
- `ClientWebSocket` no es thread-safe para envíos concurrentes — usar un `SemaphoreSlim`
  o una cola de envío en `StealthClient.cs`.
- El proyecto WinUI 3 requiere el Windows App SDK. Añadir al `.csproj`:
  `<PackageReference Include="Microsoft.WindowsAppSDK" Version="1.5.*" />`
- Para tests unitarios de crypto y network, el proyecto de tests NO necesita WinUI —
  puede ser un proyecto `net8.0` estándar que referencie solo las clases de negocio.
- Al generar el MSIX para distribución, el certificado de firma puede ser self-signed
  para pruebas locales.
