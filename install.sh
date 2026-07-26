#!/usr/bin/env bash
set -e

echo "====================================================="
echo "       Guardian Agent — Repository Installer          "
echo "====================================================="

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "[1/5] Checking Python environment..."
if ! command -v python3 &> /dev/null; then
    echo "ERROR: python3 is required but not installed."
    exit 1
fi

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "Found Python $PYTHON_VERSION"

echo "[2/5] Installing guardian-agent package in editable mode..."
pip install --user --break-system-packages -e .

echo "[3/5] Browser Automation Setup (Playwright)..."
read -p "[?] Do you want to install Playwright browser binaries (~300MB) for visual UI testing? [y/N]: " INSTALL_PLAYWRIGHT

if [[ "$INSTALL_PLAYWRIGHT" =~ ^[Yy]$ ]]; then
    echo "Installing Playwright and browser binaries..."
    pip install --user --break-system-packages playwright
    python3 -m playwright install || echo "WARNING: Playwright browser download completed with warnings."
    echo "Playwright browser automation enabled."
else
    echo "Skipping Playwright binary download."
    echo "Guardian Agent will operate using fast, low-footprint HTTP inspection fallback mode."
fi

echo "[4/5] Provider & Gateway Configuration..."
read -p "[?] Do you want to auto-discover legitimate free-tier API endpoints (OpenRouter/OmniRoute)? [Y/n]: " DISCOVER_FREE

if [[ ! "$DISCOVER_FREE" =~ ^[Nn]$ ]]; then
    echo "Discovering free tier model endpoints..."
    python3 -m guardian_agent provider discover-free --project . || true
fi

read -p "[?] Do you want to configure local Ollama provider endpoint? [y/N]: " SETUP_OLLAMA

if [[ "$SETUP_OLLAMA" =~ ^[Yy]$ ]]; then
    echo "Configuring local Ollama provider..."
    python3 -m guardian_agent provider setup-ollama --project . || true
fi

echo "[5/5] Verifying installation..."
python3 -m guardian_agent status --project .

echo ""
echo "====================================================="
echo " SUCCESS: Guardian Agent integration is complete!"
echo " "
echo " Quick commands:"
echo "   guardian status                       # View project brain status"
echo "   guardian export --target antigravity   # Export for Google Antigravity"
echo "   guardian export --target codex         # Export for OpenAI Codex"
echo "   guardian export --target claude        # Export for Claude Code"
echo "   guardian --help                        # View all commands"
echo "====================================================="
