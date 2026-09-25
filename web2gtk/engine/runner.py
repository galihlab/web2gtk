import os
import sys
import argparse


# Reset process niceness if inherited from high-priority parent (e.g. gnome-shell at -12)
# Ensures web apps run at normal unthrottled desktop priority (nice 0) without inheriting compositor priority
try:
    current_nice = os.nice(0)
    if current_nice < 0:
        os.nice(0 - current_nice)
except Exception:
    pass

# Optimize GPU hardware acceleration & media pipeline for Linux
os.environ.setdefault("GST_VAAPI_ALL_DRIVERS", "1")
os.environ.setdefault("WEBKIT_FORCE_COMPOSITING_MODE", "1")

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('WebKit', '6.0')
gi.require_version('GLib', '2.0')
gi.require_version('Gdk', '4.0')
gi.require_version('Gio', '2.0')

from gi.repository import Adw, Gio, Gdk, WebKit
from web2gtk import __version__
from web2gtk.manifest import AppManifest
from web2gtk.engine.window import Web2GtkWindow
from web2gtk.engine.tray import StatusNotifierTray


class Web2GtkApp(Adw.Application):
    def __init__(self, manifest: AppManifest):
        super().__init__(
            application_id=manifest.app_id,
            flags=Gio.ApplicationFlags.HANDLES_OPEN
        )
        self.manifest = manifest
        self.win = None
        self.tray = None

    def do_startup(self):
        Adw.Application.do_startup(self)
        self.setup_actions()

    def do_activate(self):
        try:
            if not self.win:
                self.win = Web2GtkWindow(self, self.manifest)
                if self.manifest.system_tray:
                    self.tray = StatusNotifierTray(self, self.win, self.manifest)
                    self.win.tray = self.tray
            self.win.set_visible(True)
            self.win.present()
            self.win.web_view.grab_focus()
        except Exception as e:
            print(f"[{self.manifest.slug}] Activation error: {e}", file=sys.stderr)
            self.quit()

    def do_open(self, files, hint):
        self.do_activate()
        if files:
            for f in files:
                uri = f.get_uri()
                if uri and uri.startswith(("http://", "https://")):
                    self.win.web_view.load_uri(uri)
                    break

    def do_shutdown(self):
        try:
            if self.tray and hasattr(self.tray, "unregister"):
                self.tray.unregister()
        except Exception:
            pass
        try:
            if self.win:
                if hasattr(self.win, "web_view") and self.win.web_view:
                    try:
                        self.win.web_view.terminate_web_process()
                    except Exception:
                        pass
                self.win.destroy()
        except Exception:
            pass
        Adw.Application.do_shutdown(self)

    def setup_actions(self):
        def add_action(name, callback):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)

        add_action("zoom_in", lambda *_: self.win.zoom_in() if self.win else None)
        add_action("zoom_out", lambda *_: self.win.zoom_out() if self.win else None)
        add_action("zoom_reset", lambda *_: self.win.zoom_reset() if self.win else None)
        add_action("inspect", self.action_inspect)
        add_action("copy_url", self.action_copy_url)
        add_action("clear_cache", self.action_clear_cache)
        add_action("hide_to_tray", lambda *_: self.win.set_visible(False) if self.win else None)
        add_action("about", self.action_about)
        add_action("quit", lambda *_: self.quit())

    def action_inspect(self, *_):
        if self.win:
            inspector = self.win.web_view.get_inspector()
            inspector.show()

    def action_copy_url(self, *_):
        if self.win:
            uri = self.win.web_view.get_uri()
            if uri:
                clipboard = Gdk.Display.get_default().get_clipboard()
                clipboard.set(uri)

    def action_clear_cache(self, *_):
        if self.win and self.win.session:
            dm = self.win.session.get_website_data_manager()
            dm.clear(WebKit.WebsiteDataTypes.MEMORY_CACHE | WebKit.WebsiteDataTypes.DISK_CACHE, 0, None, None)
            self.win.web_view.reload()

    def action_about(self, *_):
        about = Adw.AboutDialog(
            application_name=self.manifest.name,
            application_icon=self.manifest.icon,
            developer_name="Galyarder Labs",
            version=__version__,
            copyright="© 2026 Galyarder Labs",
            comments=f"Lightweight native GTK4/Libadwaita desktop wrapper for {self.manifest.url}",
            website=self.manifest.url,
            issue_url="https://github.com/galihlab/web2gtk"
        )
        about.present(self.win)


def run_manifest(manifest: AppManifest, argv=None):
    if argv is None:
        argv = [manifest.slug]
    app = Web2GtkApp(manifest)
    return app.run(argv)


def main():
    parser = argparse.ArgumentParser(description="web2gtk runtime runner")
    parser.add_argument("manifest", help="Path to manifest JSON or installed app slug")
    parser.add_argument("args", nargs="*", help="Extra arguments passed to application")
    args = parser.parse_args(sys.argv[1:2])

    try:
        manifest = AppManifest.load(args.manifest)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    app_args = [manifest.slug] + sys.argv[2:]
    sys.exit(run_manifest(manifest, app_args))


if __name__ == "__main__":
    main()
