<p align="center">
  <img src="assets/banner.png" alt="web2gtk banner" width="100%">
</p>

<p align="center">
  <strong>Lightweight, native GTK4 / Libadwaita desktop web app generator for Linux.</strong><br>
  Turn any web application into a first-class native GNOME desktop app without the bloat of Electron or Chromium.
</p>

<p align="center">
  <a href="https://github.com/galyarderlabs/web2gtk/actions"><img src="https://github.com/galyarderlabs/web2gtk/actions/workflows/ci.yml/badge.svg" alt="CI / CD"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License: MIT"></a>
</p>

---

## Why web2gtk?

Most web-to-desktop app generators (like Nativefier or Pake) bundle entire Chromium runtimes or require heavy dependencies, consuming hundreds of megabytes of disk space and memory for a single web page.

`web2gtk` leverages your system's existing **WebKitGTK 6.0** runtime and native **GTK4 + Libadwaita** libraries:

| Feature | Nativefier (Electron) | Pake (Tauri) | **web2gtk** |
|---|---|---|---|
| **App Bundle Size** | 150 MB – 300 MB | 15 MB – 30 MB | **< 1 KB** (shared system runtime) |
| **RAM Usage** | 500 MB – 1.2 GB | 150 MB – 300 MB | **80 MB – 150 MB** |
| **Styling & Theming** | Web / Custom frame | Generic webview wrapper | **100% Native Libadwaita** |
| **System Tray** | XEmbed / AppIndicator | Webview Tray | **Pure D-Bus StatusNotifierItem (SNI)** |
| **Session Persistence** | Chrome Profile | SQLite / Webview | **Isolated SQLite Cookies & Storage** |
| **Anti-Bot / Cloudflare** | Often flagged | May break 2FA | **Clean Linux WebKit (authentic fingerprint)** |

---

## Key Features

- **Persistent Auth Across Reboots:** Session tokens and cookies persist cleanly in SQLite (`cookies.sqlite`). No surprise logouts after rebooting.
- **Cloudflare & Bot-Detection Friendly:** Pure, untampered Linux WebKit engine with authentic platform fingerprint (eliminating fake stealth red flags) and disabled ITP for reliable login sessions.
- **D-Bus System Tray Support:** Built on the `org.kde.StatusNotifierItem` protocol. Optional tray minimization via menu with dynamic attention status (`NeedsAttention`) when background tasks finish.
- **Automatic Icon Scraper:** Automatically discovers high-res icons (`apple-touch-icon`, web app manifests, or SVGs) from target URLs and formats them into standard 32x32, 128x128, and 256x256 PNGs.
- **Full Media & Hardware Permissions:** Supports WebRTC microphone and camera (voice chat in ChatGPT, Google Meet, etc.) and desktop notifications.
- **OAuth Popup Friendly:** Popup authentication flows (Google, Apple, Microsoft, GitHub) open seamlessly in dedicated transient windows without breaking the parent session.
- **Export & Share:** Easily export any configured app into a portable standalone `.tar.gz` installer package or Arch Linux `PKGBUILD`.

---

## System Prerequisites

Ensure the following packages are installed on your Linux distribution:

### Arch Linux / Manjaro
```bash
sudo pacman -S python-gobject gtk4 libadwaita webkitgtk-6.0 libdbusmenu-glib python-pillow python-requests python-beautifulsoup4 librsvg gst-plugin-va intel-media-driver
```

### Ubuntu / Debian
```bash
# Ubuntu 24.04+ / Debian 12+
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-webkit-6.0 gir1.2-dbusmenu-glib-0.4 python3-pil python3-requests python3-bs4 librsvg2-bin gstreamer1.0-vaapi
```

### Fedora
```bash
# Fedora 39+
sudo dnf install python3-gobject gtk4 libadwaita webkitgtk6.0 libdbusmenu-gtk3 python3-pillow python3-requests python3-beautifulsoup4 librsvg2-tools gstreamer1-vaapi
```

---

## Installation

### One-Line Quick Install (Recommended)

Run the remote installer via `curl`:

```bash
curl -sSL https://raw.githubusercontent.com/galihlab/web2gtk/main/install.sh | bash
```

### Or Clone & Install Locally

```bash
git clone https://github.com/galyarderlabs/web2gtk.git
cd web2gtk
./install.sh
```

The commands `web2gtk` and `web2gtk-runner` will be immediately available in `~/.local/bin/`.

---

## Usage

### 1. Create a New Web App (`create`)

Simply provide the website URL:
```bash
# Auto-fetch icon and deduce name
web2gtk create https://claude.ai --name "Claude"

# Use a custom local icon
web2gtk create https://github.com --name "GitHub" --icon ./github.png

# Create without system tray
web2gtk create https://notion.so --name "Notion" --no-tray
```

The app is instantly integrated into your GNOME Application menu (App Grid) and can be executed from terminal (e.g. `claude-gtk`).

### 2. List Installed Web Apps (`list`)

```bash
web2gtk list
```

Output:
```text
SLUG                 NAME                   URL                                 TRAY   STEALTH 
-----------------------------------------------------------------------------------------------
claude-gtk           Claude                 https://claude.ai                   Yes    Yes     
github-gtk           GitHub                 https://github.com                  Yes    Yes     
```

### 3. Inspect App Details (`info`)

```bash
web2gtk info claude-gtk
```

### 4. Run an App Directly (`run`)

```bash
web2gtk run claude-gtk
```
*(Or directly call its slug command: `claude-gtk`)*

### 5. Remove an App (`remove` / `uninstall`)

```bash
# Remove desktop entry, launcher, and icon
web2gtk remove claude-gtk

# Remove app and purge all session cookies & storage
web2gtk remove claude-gtk --purge
```

### 6. Export for Distribution (`export`)

Want to share an app (like Claude, ChatGPT, or NotebookLM) with someone without requiring them to install `web2gtk` first?

```bash
# 1. Export as a standalone portable installer package (.tar.gz, ~13 KB)
web2gtk export claude-gtk

# 2. Export as an Arch Linux PKGBUILD directory
web2gtk export claude-gtk --format arch
```

The exported package will be in `dist/claude-gtk-installer.tar.gz`. The recipient simply extracts it and runs:
```bash
./install.sh
```
The app will be installed with its own icon, launcher in `~/.local/bin/`, and desktop menu entry.

---

## Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `Alt + Left Arrow` | Navigate Back |
| `Alt + Right Arrow` | Navigate Forward |
| `Ctrl + R` | Reload Page |
| `Ctrl + +` / `Ctrl + -` | Zoom In / Zoom Out |
| `Ctrl + 0` | Reset Zoom |
| `Ctrl + W` | Hide to System Tray (or close window) |
| `Ctrl + Q` | Quit Application |
| `F11` | Toggle Fullscreen |
| `F12` | Toggle Web Inspector / Developer Tools |

---

## Roadmap

See [ROADMAP.md](ROADMAP.md) for upcoming milestones, planned features (AUR package, Flatpak, optional Libadwaita GUI Manager), and project guiding principles.

---

## License

[MIT License](LICENSE) © 2026 Galyarder Labs
