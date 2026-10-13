#!/usr/bin/env bash
set -e

REPO_URL="https://github.com/galihlab/web2gtk.git"
TARBALL_URL="https://github.com/galihlab/web2gtk/archive/refs/heads/main.tar.gz"
INSTALL_DIR="$HOME/.local/share/web2gtk"
BIN_DIR="$HOME/.local/bin"

# Colors for terminal output
BOLD="\033[1m"
GREEN="\033[0;32m"
YELLOW="\033[0;33m"
RED="\033[0;31m"
CYAN="\033[0;36m"
RESET="\033[0m"

# Handle uninstall flag
if [ "$1" = "--uninstall" ] || [ "$1" = "uninstall" ]; then
    echo -e "${YELLOW}==> Uninstalling web2gtk...${RESET}"
    rm -f "$BIN_DIR/web2gtk" "$BIN_DIR/web2gtk-runner"
    if [ -d "$INSTALL_DIR" ]; then
        rm -rf "$INSTALL_DIR"
    fi
    echo -e "${GREEN}==> web2gtk has been uninstalled.${RESET}"
    echo "    (Note: Created app configs in ~/.config/web2gtk and desktop entries were kept intact.)"
    exit 0
fi

echo -e "${BOLD}${CYAN}"
echo "  _      _____ ___    ____  ___ _____ _  __"
echo " | | /| / / __/ _ )  |_  / / _ /_  __/ //_/"
echo " | |/ |/ / _// _  | _/_ < / // / / / / ,<   "
echo " |__/|__/___/____/ /____//____/ /_/ /_/|_|  "
echo -e "${RESET}"
echo -e "${BOLD}Native GTK4/Libadwaita desktop web app generator for Linux${RESET}"
echo ""

# 1. Dependency check & OS detection
check_dependencies() {
    local missing=0
    local distro=""

    if [ -f /etc/os-release ]; then
        . /etc/os-release
        distro="$ID $ID_LIKE"
    fi

    if ! command -v python3 >/dev/null 2>&1; then
        echo -e "${RED}[!] python3 is not installed.${RESET}"
        missing=1
    fi

    # Check GObject / GTK4 / WebKit6 bindings
    if ! python3 -c "import gi; gi.require_version('Gtk', '4.0'); gi.require_version('Adw', '1'); gi.require_version('WebKit', '6.0')" >/dev/null 2>&1; then
        echo -e "${YELLOW}[!] Missing GTK4 / Libadwaita / WebKitGTK-6.0 Python bindings.${RESET}"
        missing=1
    fi

    # Check python helper libraries
    if ! python3 -c "import PIL, requests, bs4" >/dev/null 2>&1; then
        echo -e "${YELLOW}[!] Missing Python libraries (pillow, requests, beautifulsoup4).${RESET}"
        missing=1
    fi

    if [ "$missing" -eq 1 ]; then
        echo ""
        echo -e "${BOLD}Please install the required system dependencies:${RESET}"
        case "$distro" in
            *arch*|*manjaro*|*endeavouros*)
                echo -e "  ${CYAN}sudo pacman -S python-gobject gtk4 libadwaita webkitgtk-6.0 libdbusmenu-glib python-pillow python-requests python-beautifulsoup4 librsvg gst-plugin-va intel-media-driver${RESET}"
                ;;
            *ubuntu*|*debian*|*pop*|*mint*)
                echo -e "  ${CYAN}sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-webkit-6.0 gir1.2-dbusmenu-glib-0.4 python3-pil python3-requests python3-bs4 librsvg2-bin gstreamer1.0-vaapi${RESET}"
                ;;
            *fedora*)
                echo -e "  ${CYAN}sudo dnf install python3-gobject gtk4 libadwaita webkitgtk6.0 libdbusmenu-gtk3 python3-pillow python3-requests python3-beautifulsoup4 librsvg2-tools gstreamer1-vaapi${RESET}"
                ;;
            *opensuse*|*suse*)
                echo -e "  ${CYAN}sudo zypper install python3-gobject typelib-Gtk-4_0 typelib-Adw-1 typelib-WebKit-6_0 python3-Pillow python3-requests python3-beautifulsoup4 rsvg-convert gstreamer-plugins-vaapi${RESET}"
                ;;
            *)
                echo -e "  ${CYAN}Ensure GTK4, Libadwaita, WebKitGTK-6.0, python-gobject, Pillow, BeautifulSoup4, and GStreamer VA-API are installed.${RESET}"
                ;;
        esac
        echo ""
        echo -e "${YELLOW}Continuing installation... (be sure to install dependencies before launching apps)${RESET}"
        echo ""
    else
        echo -e "${GREEN}[✓] System dependencies verified.${RESET}"
    fi
}

check_dependencies

# 2. Determine source location
# Check if running inside cloned repo
CURRENT_DIR="$(pwd)"
SCRIPT_DIR=""
if [ -n "${BASH_SOURCE[0]}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

SOURCE_DIR=""
if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/web2gtk/__init__.py" ]; then
    echo -e "${CYAN}==> Installing from local repository: $SCRIPT_DIR${RESET}"
    SOURCE_DIR="$SCRIPT_DIR"
elif [ -f "$CURRENT_DIR/web2gtk/__init__.py" ]; then
    echo -e "${CYAN}==> Installing from current directory: $CURRENT_DIR${RESET}"
    SOURCE_DIR="$CURRENT_DIR"
else
    # Remote / Curl mode
    echo -e "${CYAN}==> Downloading web2gtk into $INSTALL_DIR...${RESET}"
    mkdir -p "$INSTALL_DIR"

    if command -v git >/dev/null 2>&1; then
        if [ -d "$INSTALL_DIR/.git" ]; then
            echo "    Updating existing repository..."
            git -C "$INSTALL_DIR" pull --quiet
        else
            echo "    Cloning repository..."
            git clone --depth=1 "$REPO_URL" "$INSTALL_DIR" --quiet
        fi
    elif command -v curl >/dev/null 2>&1 && command -v tar >/dev/null 2>&1; then
        echo "    Downloading source archive..."
        curl -sSL "$TARBALL_URL" | tar -xz --strip-components=1 -C "$INSTALL_DIR"
    else
        echo -e "${RED}[ERROR] Neither git nor curl+tar is available. Please install git or curl.${RESET}"
        exit 1
    fi
    SOURCE_DIR="$INSTALL_DIR"
fi

# 3. Setup binaries and system paths
mkdir -p "$BIN_DIR"
chmod +x "$SOURCE_DIR/bin/web2gtk"
chmod +x "$SOURCE_DIR/bin/web2gtk-runner"

ln -sf "$SOURCE_DIR/bin/web2gtk" "$BIN_DIR/web2gtk"
ln -sf "$SOURCE_DIR/bin/web2gtk-runner" "$BIN_DIR/web2gtk-runner"

# 4. Ensure desktop directories exist
mkdir -p "$HOME/.local/share/icons/hicolor/32x32/apps"
mkdir -p "$HOME/.local/share/icons/hicolor/128x128/apps"
mkdir -p "$HOME/.local/share/icons/hicolor/256x256/apps"
mkdir -p "$HOME/.local/share/applications"
mkdir -p "$HOME/.config/web2gtk/apps"

# 5. Check PATH
PATH_OK=0
case ":$PATH:" in
    *":$BIN_DIR:"*) PATH_OK=1 ;;
esac

echo ""
echo -e "${GREEN}${BOLD}==> web2gtk successfully installed!${RESET}"
echo -e "    Binaries linked in: ${CYAN}$BIN_DIR${RESET}"
echo ""

if [ "$PATH_OK" -eq 0 ]; then
    echo -e "${YELLOW}[!] Warning: $BIN_DIR is not in your current PATH.${RESET}"
    echo "    Add this to your ~/.bashrc or ~/.zshrc:"
    echo -e "    ${CYAN}export PATH=\"\$HOME/.local/bin:\$PATH\"${RESET}"
    echo ""
fi

echo "Quick start:"
echo -e "  ${CYAN}web2gtk create https://chatgpt.com --name \"ChatGPT\"${RESET}"
echo -e "  ${CYAN}web2gtk list${RESET}"
echo -e "  ${CYAN}web2gtk --help${RESET}"
echo ""
