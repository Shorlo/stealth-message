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
            local minor major
            minor=$("$cmd" -c "import sys; print(sys.version_info.minor)" 2>/dev/null)
            major=$("$cmd" -c "import sys; print(sys.version_info.major)" 2>/dev/null)
            if [ "$major" = "3" ] && [ "$minor" -ge "$MIN_PYTHON_MINOR" ] 2>/dev/null; then
                echo "$cmd"
                return 0
            fi
        fi
    done
    return 1
}

# ── Install pipx via system package manager ────────────────────────────────────
install_pipx() {
    info "Installing pipx..."
    if command -v apt-get &>/dev/null; then
        sudo apt-get install -y pipx
    elif command -v brew &>/dev/null; then
        brew install pipx
    elif command -v dnf &>/dev/null; then
        sudo dnf install -y pipx
    elif command -v pacman &>/dev/null; then
        sudo pacman -Sy --noconfirm python-pipx
    else
        return 1
    fi
}

# ── Main ───────────────────────────────────────────────────────────────────────
info "Installing $PACKAGE..."

PYTHON=$(find_python) || error "Python 3.10 or newer is required.\nInstall it from https://python.org or via your package manager."
info "Using $PYTHON ($(${PYTHON} --version))"

# Ensure pipx is available — install it if not
if ! command -v pipx &>/dev/null; then
    warning "pipx not found — attempting to install it automatically..."
    if install_pipx; then
        # pipx may not be in PATH immediately after apt install
        export PATH="$HOME/.local/bin:$PATH"
    else
        error "Could not install pipx automatically.\nPlease install it manually: https://pipx.pypa.io\nThen re-run this installer."
    fi
fi

info "Installing via pipx..."
pipx install --python "$PYTHON" "$PACKAGE"

# Ensure pipx bin dir is in PATH
pipx ensurepath --quiet 2>/dev/null || true

echo ""
info "$BINARY installed successfully!"
info "Run: $BINARY --help"
info "If the command is not found, restart your terminal or run: pipx ensurepath"
