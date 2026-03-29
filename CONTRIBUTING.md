# Guía de contribución

Gracias por tu interés en contribuir a `stealth-message`.
Lee esta guía antes de abrir un issue o enviar un pull request.

---

## Antes de empezar

1. Lee el [README](README.md) para entender qué es el proyecto.
2. Lee [ARCHITECTURE.md](ARCHITECTURE.md) para entender la estructura y las decisiones de diseño.
3. Lee [SECURITY.md](SECURITY.md) para conocer la política de seguridad.
4. Lee `docs/protocol.md` — es la fuente de verdad del protocolo.
5. Lee el `CLAUDE.md` del subproyecto en el que vayas a trabajar.

---

## Cómo reportar bugs

- Usa los **Issues de GitHub** para reportar bugs.
- **Excepción:** si el bug es una vulnerabilidad de seguridad, sigue las instrucciones
  de [SECURITY.md](SECURITY.md) y **no abras un issue público**.
- Antes de abrir un issue, busca si ya existe uno similar.
- Incluye: descripción, pasos para reproducir, resultado esperado vs. obtenido,
  versión del SO y del subproyecto afectado.

---

## Cómo proponer mejoras

- Abre un **Issue** describiendo la mejora antes de implementarla.
- Explica el problema que resuelve y por qué la solución propuesta es la correcta.
- Para cambios grandes o que afecten al protocolo, espera feedback antes de escribir código.

---

## Proceso de contribución

### 1. Fork y branch

```bash
git clone https://github.com/<tu-usuario>/stealth-message.git
cd stealth-message
git checkout -b feature/descripcion-corta
# o
git checkout -b fix/descripcion-corta
```

### 2. Cambios en el protocolo

Si tu contribución implica un cambio en el protocolo de comunicación:

1. **Actualiza `docs/protocol.md` primero.** El documento es la fuente de verdad.
2. Describe el cambio, su motivación y su impacto en los cuatro subproyectos.
3. Actualiza todos los subproyectos afectados en el mismo PR.

### 3. Código

- Sigue las convenciones del subproyecto (ver su `CLAUDE.md`).
- Escribe tests para la lógica nueva, especialmente en los módulos `crypto/` y `network/`.
- Los módulos `crypto/` y `network/` requieren tests antes de cualquier merge (TDD).
- Nunca pongas información sensible (claves, passphrases) en tests o configuración.

### 4. CHANGELOG

**Obligatorio:** actualiza `CHANGELOG.md` en la sección `[Unreleased]` con una entrada
que describa tu cambio. Usa las categorías de [Keep a Changelog](https://keepachangelog.com/es-ES/1.0.0/):

- `Added` — nueva funcionalidad
- `Changed` — cambio en funcionalidad existente
- `Deprecated` — funcionalidad que se eliminará en el futuro
- `Removed` — funcionalidad eliminada
- `Fixed` — corrección de bug
- `Security` — corrección relacionada con seguridad

### 5. Pull Request

- Título corto y descriptivo en inglés o español.
- Describe **qué** cambia y **por qué**.
- Si cierra un issue: `Closes #<número>`.
- Los PRs que afectan al protocolo deben documentar el impacto en los cuatro subproyectos.
- Un PR debe tener un alcance claro; evita mezclar features con refactors no relacionados.

---

## Estándares de código por subproyecto

| Subproyecto | Lenguaje | Formato    | Lint   | Tipos   |
|-------------|----------|------------|--------|---------|
| `cli/`      | Python   | `black`    | `ruff` | `mypy`  |
| `linux/`    | Python   | `black`    | `ruff` | `mypy`  |
| `macos/`    | Swift    | swift-format | SwiftLint | — |
| `windows/`  | C#       | `dotnet format` | Roslyn analyzers | Nullable enable |

---

## Política de merge

- Se requiere al menos **1 revisión** antes de hacer merge.
- Los tests deben pasar en CI.
- No se hace merge de código con secretos, claves o passphrases hardcodeadas.
- Los cambios de protocolo requieren revisión explícita de los mantenedores.

---

## Código de conducta

Este proyecto sigue el principio de colaboración respetuosa y constructiva.
Las contribuciones se evalúan por su mérito técnico. Se esperan comunicaciones
directas, honestas y profesionales.
