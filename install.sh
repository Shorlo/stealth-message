#!/usr/bin/env bash
# stealth-message installer for Linux and macOS
# Usage: curl -fsSL https://syberiancode.com/stealth-message/install.sh | bash
set -e

PACKAGE="stealth-message-cli"
BINARY="stealth-cli"
MIN_PYTHON_MINOR=10

# ── Colours ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()    { echo -e "${GREEN}[stealth-message]${NC} $*"; }
warning() { echo -e "${YELLOW}[stealth-message]${NC} $*"; }
error()   { echo -e "${RED}[stealth-message] Error:${NC} $*" >&2; exit 1; }

# ── Find a Python 3.10+ interpreter ────────────────────────────────────────────
find_python() {
    for cmd in python3.13 python3.12 python3.11 python3.10 python3 python; do
        if command -v "$cmd" &>/dev/null; then
            local minor
            minor=$("$cmd" -c "import sys; print(sys.version_info.minor)" 2>/dev/null)
            local major
            major=$("$cmd" -c "import sys; print(sys.version_info.major)" 2>/dev/null)
            if [ "$major" = "3" ] && [ "$minor" -ge "$MIN_PYTHON_MINOR" ] 2>/dev/null; then
                echo "$cmd"
                return 0
            fi
        fi
    done
    return 1
}

# ── Main ───────────────────────────────────────────────────────────────────────
info "Installing $PACKAGE..."

PYTHON=$(find_python) || error "Python 3.10 or newer is required.\nInstall it from https://python.org or via your package manager."
info "Using $PYTHON ($(${PYTHON} --version))"

# pipx — preferred: isolated environment, no system pollution
if command -v pipx &>/dev/null; then
    info "Installing via pipx..."
    pipx install --python "$PYTHON" "$PACKAGE"
else
    # pip fallback with --user
    warning "pipx not found — falling back to pip install --user"
    warning "Consider installing pipx for cleaner management: https://pipx.pypa.io"
    "$PYTHON" -m pip install --user --upgrade "$PACKAGE"

    # Ensure ~/.local/bin is in PATH for this session
    export PATH="$HOME/.local/bin:$PATH"

    # Warn if not in shell config
    SHELL_RC=""
    case "$SHELL" in
        */zsh)  SHELL_RC="$HOME/.zshrc" ;;
        */bash) SHELL_RC="$HOME/.bashrc" ;;
    esac
    if [ -n "$SHELL_RC" ] && ! grep -q '\.local/bin' "$SHELL_RC" 2>/dev/null; then
        warning "Add ~/.local/bin to your PATH permanently:"
        warning "  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> $SHELL_RC"
    fi
fi

echo ""
info "$BINARY installed successfully!"
info "Run: $BINARY --help"
