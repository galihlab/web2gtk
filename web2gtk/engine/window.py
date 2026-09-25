import os
import json
import re
from urllib.parse import urlparse
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('WebKit', '6.0')
gi.require_version('GLib', '2.0')
gi.require_version('Gdk', '4.0')
gi.require_version('Gio', '2.0')

from gi.repository import Gtk, Adw, WebKit, GLib, Gdk, Gio

try:
    from web2gtk.engine.adblock import setup_adblock
except ImportError:
    from adblock import setup_adblock

STEALTH_SCRIPT = ""

# WebAudio-backed VirtualAudio to completely bypass WebKitGTK/GStreamer playbin pipeline leak
AUDIO_CLEANUP_SCRIPT = """
(function() {
    try {
        const OrigAudio = window.Audio;
        const origCreateElement = document.createElement;
        const origCreateElementNS = document.createElementNS;

        let audioCtx = null;
        function getAudioContext() {
            if (!audioCtx) {
                const AC = window.AudioContext || window.webkitAudioContext;
                if (AC) audioCtx = new AC();
            }
            if (audioCtx && audioCtx.state === 'suspended') {
                audioCtx.resume().catch(() => {});
            }
            return audioCtx;
        }

        ['pointerdown', 'keydown', 'touchstart', 'click'].forEach(evt => {
            window.addEventListener(evt, () => {
                if (audioCtx && audioCtx.state === 'suspended') {
                    audioCtx.resume().catch(() => {});
                }
            }, { passive: true, capture: true });
        });

        const bufferCache = new Map();
        let lastPlayTime = 0;
        const THROTTLE_MS = 15;

        function normalizeUrl(url) {
            if (!url) return '';
            try {
                return new URL(url, document.baseURI || window.location.href).href;
            } catch(e) {
                return String(url);
            }
        }

        function loadBuffer(url) {
            const norm = normalizeUrl(url);
            if (!norm) return Promise.reject(new Error('No URL'));
            if (bufferCache.has(norm)) return bufferCache.get(norm);

            const p = (async () => {
                const ctx = getAudioContext();
                if (!ctx) throw new Error('No AudioContext');
                const resp = await fetch(norm);
                const arrayBuf = await resp.arrayBuffer();
                return await ctx.decodeAudioData(arrayBuf);
            })();
            bufferCache.set(norm, p);
            return p;
        }

        class WebAudioPlayer extends EventTarget {
            constructor(src) {
                super();
                this._src = normalizeUrl(src);
                this._volume = 1.0;
                this._muted = false;
                this._playbackRate = 1.0;
                this._currentTime = 0;
                this._loop = false;
                this._paused = true;
                this._ended = true;
                this._duration = 1.0;
                this._preload = 'auto';
                this._currentSource = null;
                if (this._src) this.load();
            }

            get src() { return this._src; }
            set src(v) {
                this._src = normalizeUrl(v);
                if (this._src) this.load();
            }
            get currentSrc() { return this._src; }
            get preload() { return this._preload; }
            set preload(v) { this._preload = String(v); }
            get crossOrigin() { return this._crossOrigin || ''; }
            set crossOrigin(v) { this._crossOrigin = String(v); }
            get autoplay() { return false; }
            set autoplay(v) {}
            get defaultMuted() { return false; }
            set defaultMuted(v) {}
            get defaultPlaybackRate() { return 1.0; }
            set defaultPlaybackRate(v) {}
            get readyState() { return 4; }
            get networkState() { return 1; }
            get duration() { return this._duration; }
            get volume() { return this._volume; }
            set volume(v) { this._volume = Math.max(0, Math.min(1, Number(v) || 0)); }
            get muted() { return this._muted; }
            set muted(v) { this._muted = Boolean(v); }
            get playbackRate() { return this._playbackRate; }
            set playbackRate(v) { this._playbackRate = Number(v) || 1.0; }
            get currentTime() { return this._currentTime; }
            set currentTime(v) { this._currentTime = Number(v) || 0; }
            get loop() { return this._loop; }
            set loop(v) { this._loop = Boolean(v); }
            get paused() { return this._paused; }
            get ended() { return this._ended; }
            get tagName() { return 'AUDIO'; }
            get nodeName() { return 'AUDIO'; }
            get nodeType() { return 1; }

            load() {
                if (!this._src) return;
                this.dispatchEvent(new Event('loadstart'));
                loadBuffer(this._src).then(buf => {
                    if (buf && buf.duration) this._duration = buf.duration;
                    this.dispatchEvent(new Event('loadedmetadata'));
                    this.dispatchEvent(new Event('loadeddata'));
                    this.dispatchEvent(new Event('canplay'));
                    this.dispatchEvent(new Event('canplaythrough'));
                    this.dispatchEvent(new Event('load'));
                }).catch(() => {
                    this.dispatchEvent(new Event('canplay'));
                    this.dispatchEvent(new Event('canplaythrough'));
                });
            }

            async play() {
                const now = Date.now();
                if (now - lastPlayTime < THROTTLE_MS) return Promise.resolve();
                lastPlayTime = now;

                if (!this._src) return Promise.resolve();
                const ctx = getAudioContext();
                if (!ctx) return Promise.resolve();

                try {
                    const buf = await loadBuffer(this._src);
                    if (buf && buf.duration) this._duration = buf.duration;

                    const source = ctx.createBufferSource();
                    const gain = ctx.createGain();

                    source.buffer = buf;
                    source.playbackRate.value = this._playbackRate;
                    source.loop = this._loop;
                    gain.gain.value = this._muted ? 0 : this._volume;

                    source.connect(gain);
                    gain.connect(ctx.destination);

                    if (this._currentSource) {
                        try { this._currentSource.stop(); } catch(e) {}
                    }
                    this._currentSource = source;
                    this._paused = false;
                    this._ended = false;
                    this.dispatchEvent(new Event('play'));
                    this.dispatchEvent(new Event('playing'));

                    source.onended = () => {
                        this._paused = true;
                        this._ended = true;
                        this._currentSource = null;
                        this.dispatchEvent(new Event('ended'));
                    };

                    source.start(0, this.currentTime || 0);
                    return Promise.resolve();
                } catch(err) {
                    this._paused = true;
                    this._ended = true;
                    this.dispatchEvent(new Event('error'));
                    return Promise.resolve();
                }
            }

            pause() {
                this._paused = true;
                if (this._currentSource) {
                    try { this._currentSource.stop(); } catch(e) {}
                    this._currentSource = null;
                }
                this.dispatchEvent(new Event('pause'));
            }

            canPlayType(type) { return 'probably'; }

            cloneNode() {
                const c = new WebAudioPlayer(this._src);
                c.volume = this._volume;
                c.muted = this._muted;
                c.playbackRate = this._playbackRate;
                return c;
            }

            setAttribute(n, v) { if (typeof n === 'string' && n.toLowerCase() === 'src') this.src = v; }
            getAttribute(n) { return (typeof n === 'string' && n.toLowerCase() === 'src') ? this.src : null; }
            hasAttribute(n) { return (typeof n === 'string' && n.toLowerCase() === 'src') ? Boolean(this.src) : false; }
            removeAttribute(n) { if (typeof n === 'string' && n.toLowerCase() === 'src') this.src = ''; }

            get onended() { return this._onended; }
            set onended(fn) {
                if (this._onended) this.removeEventListener('ended', this._onended);
                this._onended = fn;
                if (fn) this.addEventListener('ended', fn);
            }
            get onplay() { return this._onplay; }
            set onplay(fn) {
                if (this._onplay) this.removeEventListener('play', this._onplay);
                this._onplay = fn;
                if (fn) this.addEventListener('play', fn);
            }
            get onpause() { return this._onpause; }
            set onpause(fn) {
                if (this._onpause) this.removeEventListener('pause', this._onpause);
                this._onpause = fn;
                if (fn) this.addEventListener('pause', fn);
            }
            get onerror() { return this._onerror; }
            set onerror(fn) {
                if (this._onerror) this.removeEventListener('error', this._onerror);
                this._onerror = fn;
                if (fn) this.addEventListener('error', fn);
            }
            get oncanplay() { return this._oncanplay; }
            set oncanplay(fn) {
                if (this._oncanplay) this.removeEventListener('canplay', this._oncanplay);
                this._oncanplay = fn;
                if (fn) this.addEventListener('canplay', fn);
            }
            get oncanplaythrough() { return this._oncanplaythrough; }
            set oncanplaythrough(fn) {
                if (this._oncanplaythrough) this.removeEventListener('canplaythrough', this._oncanplaythrough);
                this._oncanplaythrough = fn;
                if (fn) this.addEventListener('canplaythrough', fn);
            }
        }

        window.Audio = WebAudioPlayer;
        WebAudioPlayer.prototype.constructor = WebAudioPlayer;

        document.createElement = function(tagName, options) {
            if (typeof tagName === 'string' && tagName.toLowerCase() === 'audio') {
                return new WebAudioPlayer();
            }
            return origCreateElement.call(document, tagName, options);
        };

        document.createElementNS = function(ns, tagName, options) {
            if (typeof tagName === 'string' && tagName.toLowerCase() === 'audio') {
                return new WebAudioPlayer();
            }
            return origCreateElementNS.call(document, ns, tagName, options);
        };

        if (typeof HTMLAudioElement !== 'undefined') {
            try {
                Object.defineProperty(HTMLAudioElement, Symbol.hasInstance, {
                    value: function(inst) {
                        return inst instanceof WebAudioPlayer || inst instanceof HTMLMediaElement;
                    }
                });
            } catch(e) {}
        }
        if (typeof HTMLMediaElement !== 'undefined') {
            try {
                Object.defineProperty(HTMLMediaElement, Symbol.hasInstance, {
                    value: function(inst) {
                        return inst instanceof WebAudioPlayer || inst instanceof HTMLMediaElement;
                    }
                });
            } catch(e) {}
        }
    } catch(e) {}
})();
"""

AUTH_DOMAINS = (
    "accounts.google.com",
    "appleid.apple.com",
    "login.microsoftonline.com",
    "login.live.com",
    "github.com",
    "auth0.com",
    "clerk.com",
    "okta.com",
    "facebook.com",
    "meta.com",
    "instagram.com",
    "threads.net",
    "threads.com",
    "auth.meta.com",
    "accountscenter.instagram.com",
    "accountscenter.meta.com",
    "accountscenter.facebook.com",
)

APP_FAMILIES = (
    ("threads.net", "threads.com", "instagram.com", "facebook.com", "meta.com", "fb.com", "cdninstagram.com", "fbcdn.net"),
    ("google.com", "youtube.com", "googleusercontent.com", "gstatic.com", "googleapis.com"),
)


def is_auth_url(url_str):
    if not url_str:
        return False
    try:
        from urllib.parse import urlparse
        p = urlparse(url_str)
        host = p.netloc.lower()
        if any(ad in host for ad in AUTH_DOMAINS):
            return True
        path = p.path.lower()
        if any(kw in path for kw in ("/auth/", "/login", "/signin", "/oauth", "/sso", "/challenge")):
            return True
    except Exception:
        pass
    return False


def is_same_app_domain(url_str, app_url):
    if not url_str or not app_url:
        return False
    try:
        from urllib.parse import urlparse
        target_host = urlparse(url_str).netloc.lower()
        app_host = urlparse(app_url).netloc.lower()
        if target_host == app_host or target_host.endswith("." + app_host):
            return True
        # Check app families (e.g. Threads <-> Instagram <-> Meta)
        for family in APP_FAMILIES:
            if any(f in app_host for f in family) and any(f in target_host for f in family):
                return True
        if "notebook" in app_host and "notebook" in target_host and target_host.endswith(".google.com"):
            return True
        parts_target = target_host.split(".")
        parts_app = app_host.split(".")
        if len(parts_target) >= 2 and len(parts_app) >= 2:
            root_target = ".".join(parts_target[-2:])
            root_app = ".".join(parts_app[-2:])
            if root_target == root_app and root_target not in ("google.com", "github.com", "microsoft.com", "apple.com"):
                return True
    except Exception:
        pass
    return False


def is_chess_app(url_str):
    if not url_str:
        return False
    try:
        host = urlparse(url_str).netloc.lower()
        return "chess.com" in host or "lichess.org" in host
    except Exception:
        return False


DOWNLOAD_DIR = os.path.expanduser("~/Downloads")


class Web2GtkWindow(Adw.ApplicationWindow):
    def __init__(self, app, manifest):
        super().__init__(application=app, title=manifest.name)
        self.app = app
        self.manifest = manifest
        self.config_file = os.path.join(self.manifest.config_dir, "window_state.json")

        # Window sizing & state
        state = self.load_window_state()
        self.set_default_size(state.get("width", 1080), state.get("height", 800))
        if state.get("is_maximized", False):
            self.maximize()

        # Tray notification dedup state
        self._last_notified_title = None
        self.connect("notify::visible", self.on_visibility_changed)

        # Intercept close request
        self.connect("close-request", self.on_close_request)

        # Persistent Network Session
        if self.manifest.persistent_storage:
            os.makedirs(self.manifest.data_dir, exist_ok=True)
            os.makedirs(self.manifest.cache_dir, exist_ok=True)
            self.session = WebKit.NetworkSession.new(
                data_directory=self.manifest.data_dir,
                cache_directory=self.manifest.cache_dir
            )
            # Persistent SQLite cookies
            cookie_file = os.path.join(self.manifest.data_dir, "cookies.sqlite")
            cookie_manager = self.session.get_cookie_manager()
            cookie_manager.set_accept_policy(WebKit.CookieAcceptPolicy.ALWAYS)
            cookie_manager.set_persistent_storage(
                cookie_file, WebKit.CookiePersistentStorage.SQLITE
            )
        else:
            self.session = WebKit.NetworkSession.new_ephemeral()
            cookie_manager = self.session.get_cookie_manager()
            cookie_manager.set_accept_policy(WebKit.CookieAcceptPolicy.ALWAYS)

        # Disable ITP for reliable cross-origin auth flows
        self.session.set_itp_enabled(False)

        # WebKit Settings & GPU Hardware Acceleration
        self.settings = WebKit.Settings()
        if "youtube.com" in (self.manifest.url or "").lower():
            self.settings.set_user_agent(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15"
            )
        elif "chatgpt.com" in (self.manifest.url or "").lower() or "openai.com" in (self.manifest.url or "").lower():
            self.settings.set_user_agent(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.3 Safari/605.1.15"
            )
        else:
            self.settings.set_user_agent(self.manifest.user_agent)
        self.settings.set_enable_developer_extras(True)
        self.settings.set_enable_webrtc(True)
        self.settings.set_enable_media_stream(True)
        self.settings.set_javascript_can_access_clipboard(True)
        self.settings.set_javascript_can_open_windows_automatically(True)

        # Performance & GPU hardware acceleration
        self.settings.set_hardware_acceleration_policy(WebKit.HardwareAccelerationPolicy.ALWAYS)
        self.settings.set_enable_smooth_scrolling(False)
        self.settings.set_enable_2d_canvas_acceleration(True)
        self.settings.set_enable_page_cache(True)
        self.settings.set_enable_back_forward_navigation_gestures(True)
        self.settings.set_enable_webgl(True)
        self.settings.set_enable_webaudio(True)
        self.settings.set_enable_media(True)
        self.settings.set_enable_mediasource(True)
        self.settings.set_enable_media_capabilities(True)
        self.settings.set_media_playback_allows_inline(True)
        self.settings.set_media_playback_requires_user_gesture(False)

        # Enforce hardware-accelerated media decoding to avoid CPU software decoding fallbacks (e.g. libdav1d AV1)
        if getattr(self.manifest, "hardware_media_only", True):
            self.settings.set_media_content_types_requiring_hardware_support("video/*")

        # User Content Manager
        self.user_content_manager = WebKit.UserContentManager()

        if self.manifest.stealth and STEALTH_SCRIPT:
            stealth_script = WebKit.UserScript(
                source=STEALTH_SCRIPT,
                injected_frames=WebKit.UserContentInjectedFrames.ALL_FRAMES,
                injection_time=WebKit.UserScriptInjectionTime.START
            )
            self.user_content_manager.add_script(stealth_script)

        # Setup built-in adblocking & YouTube ad-skipping
        if getattr(self.manifest, "adblock", True):
            setup_adblock(self.user_content_manager, self.manifest.cache_dir, self.manifest.url)

        # Chess audio pipeline leak mitigation (bounded VirtualAudio pooler)
        if is_chess_app(self.manifest.url):
            audio_cleanup_script = WebKit.UserScript(
                source=AUDIO_CLEANUP_SCRIPT,
                injected_frames=WebKit.UserContentInjectedFrames.ALL_FRAMES,
                injection_time=WebKit.UserScriptInjectionTime.START
            )
            self.user_content_manager.add_script(audio_cleanup_script)

        # Ensure keyboard focus and handle background visibility/suspension
        self.connect("notify::is-active", self.on_window_active_changed)
        self.connect("notify::visible", self.on_window_visibility_changed)
        if hasattr(self.props, "suspended"):
            self.connect("notify::suspended", self.on_window_suspended_changed)

        # Main Layout
        self.main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(self.main_box)

        # HeaderBar
        self.header_bar = Adw.HeaderBar()
        self.header_bar.add_css_class("flat")
        self.main_box.append(self.header_bar)

        # Title widget
        parsed_url = urlparse(self.manifest.url)
        self.title_widget = Adw.WindowTitle(
            title=self.manifest.name,
            subtitle=parsed_url.netloc or self.manifest.url
        )
        self.header_bar.set_title_widget(self.title_widget)

        # Nav buttons
        self.nav_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.header_bar.pack_start(self.nav_box)

        self.btn_back = Gtk.Button(icon_name="go-previous-symbolic")
        self.btn_back.set_tooltip_text("Kembali (Alt+Left)")
        self.btn_back.connect("clicked", self.on_back_clicked)
        self.btn_back.set_sensitive(False)
        self.nav_box.append(self.btn_back)

        self.btn_forward = Gtk.Button(icon_name="go-next-symbolic")
        self.btn_forward.set_tooltip_text("Maju (Alt+Right)")
        self.btn_forward.connect("clicked", self.on_forward_clicked)
        self.btn_forward.set_sensitive(False)
        self.nav_box.append(self.btn_forward)

        self.btn_reload = Gtk.Button(icon_name="view-refresh-symbolic")
        self.btn_reload.set_tooltip_text("Muat Ulang (Ctrl+R)")
        self.btn_reload.connect("clicked", self.on_reload_clicked)
        self.nav_box.append(self.btn_reload)

        self.btn_home = Gtk.Button(icon_name="go-home-symbolic")
        self.btn_home.set_tooltip_text(f"Beranda {self.manifest.name}")
        self.btn_home.connect("clicked", lambda _: self.web_view.load_uri(self.manifest.url))
        self.nav_box.append(self.btn_home)

        # Menu Button
        self.menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic")
        self.menu_btn.set_tooltip_text("Menu Aplikasi")
        self.header_bar.pack_end(self.menu_btn)
        self.setup_menu()

        # Progress bar
        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.add_css_class("osd")
        self.progress_bar.set_visible(False)
        self.main_box.append(self.progress_bar)

        # Primary WebView
        self.web_view = WebKit.WebView(
            network_session=self.session,
            user_content_manager=self.user_content_manager,
            settings=self.settings
        )
        bg = Gdk.RGBA()
        bg.parse("#101010")
        self.web_view.set_background_color(bg)
        self.web_view.set_vexpand(True)
        self.web_view.set_hexpand(True)
        self.main_box.append(self.web_view)

        # Connect signals
        self.web_view.connect("notify::estimated-load-progress", self.on_progress_changed)
        self.web_view.connect("notify::title", self.on_title_changed)
        self.web_view.connect("notify::uri", self.on_uri_changed)
        self.web_view.connect("load-changed", self.on_load_changed)
        self.web_view.connect("load-failed", self.on_load_failed)
        self.web_view.connect("create", self.on_create_popup)
        self.web_view.connect("permission-request", self.on_permission_request)
        self.web_view.connect("show-notification", self.on_show_notification)
        self.web_view.connect("decide-policy", self.on_decide_policy)
        self.session.connect("download-started", self.on_download_started)

        # Keyboard shortcuts
        self.setup_shortcuts()

        # Initial Load
        GLib.idle_add(lambda: self.web_view.load_uri(self.manifest.url))

    def setup_menu(self):
        menu = Gio.Menu()

        view_section = Gio.Menu()
        view_section.append("Perbesar (Ctrl++)", "app.zoom_in")
        view_section.append("Perkecil (Ctrl+-)", "app.zoom_out")
        view_section.append("Reset Zoom (Ctrl+0)", "app.zoom_reset")
        menu.append_section(None, view_section)

        tools_section = Gio.Menu()
        tools_section.append("Salin URL Halaman", "app.copy_url")
        tools_section.append("Buka Web Inspector (F12)", "app.inspect")
        tools_section.append("Hapus Cache", "app.clear_cache")
        menu.append_section(None, tools_section)

        app_section = Gio.Menu()
        app_section.append(f"Tentang {self.manifest.name}", "app.about")
        if self.manifest.system_tray:
            app_section.append("Sembunyikan ke Tray", "app.hide_to_tray")
        app_section.append("Keluar (Ctrl+Q)", "app.quit")
        menu.append_section(None, app_section)

        self.menu_btn.set_menu_model(menu)

    def setup_shortcuts(self):
        controller = Gtk.EventControllerKey()
        controller.connect("key-pressed", self.on_key_pressed)
        self.add_controller(controller)

    def on_key_pressed(self, controller, keyval, keycode, state):
        ctrl = (state & Gdk.ModifierType.CONTROL_MASK) != 0
        alt = (state & Gdk.ModifierType.ALT_MASK) != 0

        if ctrl:
            if keyval in (Gdk.KEY_r, Gdk.KEY_R):
                self.web_view.reload()
                return True
            elif keyval in (Gdk.KEY_plus, Gdk.KEY_equal, Gdk.KEY_KP_Add):
                self.zoom_in()
                return True
            elif keyval in (Gdk.KEY_minus, Gdk.KEY_KP_Subtract):
                self.zoom_out()
                return True
            elif keyval in (Gdk.KEY_0, Gdk.KEY_KP_0):
                self.zoom_reset()
                return True
            elif keyval in (Gdk.KEY_q, Gdk.KEY_Q):
                self.app.quit()
                return True
            elif keyval in (Gdk.KEY_w, Gdk.KEY_W):
                if self.manifest.system_tray:
                    self.set_visible(False)
                else:
                    self.close()
                return True
        elif alt:
            if keyval == Gdk.KEY_Left:
                if self.web_view.can_go_back():
                    self.web_view.go_back()
                return True
            elif keyval == Gdk.KEY_Right:
                if self.web_view.can_go_forward():
                    self.web_view.go_forward()
                return True
        elif keyval == Gdk.KEY_F11:
            if self.is_fullscreen():
                self.unfullscreen()
            else:
                self.fullscreen()
            return True
        elif keyval == Gdk.KEY_F12:
            inspector = self.web_view.get_inspector()
            if inspector.is_attached():
                inspector.close()
            else:
                inspector.show()
            return True

        return False

    def zoom_in(self):
        level = self.web_view.get_zoom_level()
        self.web_view.set_zoom_level(min(level + 0.1, 3.0))

    def zoom_out(self):
        level = self.web_view.get_zoom_level()
        self.web_view.set_zoom_level(max(level - 0.1, 0.5))

    def zoom_reset(self):
        self.web_view.set_zoom_level(1.0)

    def on_back_clicked(self, _):
        if self.web_view.can_go_back():
            self.web_view.go_back()

    def on_forward_clicked(self, _):
        if self.web_view.can_go_forward():
            self.web_view.go_forward()

    def on_reload_clicked(self, _):
        self.web_view.reload()

    def on_progress_changed(self, web_view, _):
        progress = web_view.get_estimated_load_progress()
        self.progress_bar.set_fraction(progress)
        self.progress_bar.set_visible(progress < 0.95)

    def on_title_changed(self, web_view, _):
        title = web_view.get_title()
        if title:
            self.title_widget.set_title(title)
            self.set_title(title)

            # Tray notification: send native GNOME notification when window is hidden
            if not self.get_visible() and title != self._last_notified_title:
                self._last_notified_title = title
                match = re.match(r"^[\(\u2022\s]*(\d+)[\)\s\u2022]", title)
                body = f"{match.group(1)} new messages" if match else title
                notif = Gio.Notification.new(self.manifest.name)
                notif.set_body(body)
                notif.set_priority(Gio.NotificationPriority.HIGH)
                self.app.send_notification(f"{self.manifest.slug}-reply", notif)
                self._has_sent_notification = True

    def on_visibility_changed(self, *_):
        if self.get_visible() and getattr(self, "_has_sent_notification", False):
            self._last_notified_title = None
            self._has_sent_notification = False
            try:
                self.app.withdraw_notification(f"{self.manifest.slug}-reply")
            except Exception:
                pass

    def on_uri_changed(self, web_view, _):
        uri = web_view.get_uri()
        if uri:
            try:
                host = urlparse(uri).netloc
                self.title_widget.set_subtitle(host if host else self.manifest.name)
            except Exception:
                pass

    def send_desktop_notification(self, summary, body, urgency=2):
        """Send desktop notification via direct D-Bus with fallback to GApplication."""
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            proxy = Gio.DBusProxy.new_sync(
                bus,
                Gio.DBusProxyFlags.NONE,
                None,
                "org.freedesktop.Notifications",
                "/org/freedesktop/Notifications",
                "org.freedesktop.Notifications",
                None
            )
            hints = {
                "desktop-entry": GLib.Variant("s", self.manifest.slug),
                "urgency": GLib.Variant("y", urgency),
            }
            proxy.Notify(
                "(susssasa{sv}i)",
                self.manifest.name,
                0,
                self.manifest.icon,
                summary,
                body,
                [],
                hints,
                6000
            )
            print(f"[{self.manifest.slug}] Desktop notification sent: {summary} - {body}")
        except Exception as e:
            print(f"[{self.manifest.slug}] D-Bus notification error: {e}")

        try:
            notif = Gio.Notification.new(summary)
            notif.set_body(body)
            notif.set_priority(Gio.NotificationPriority.HIGH)
            self.app.send_notification(f"{self.manifest.slug}-notify", notif)
        except Exception:
            pass

    def on_window_active_changed(self, *_):
        if self.is_active():
            self.web_view.grab_focus()
            if hasattr(self, "tray") and self.tray:
                self.tray.set_attention(False)

    def pause_media(self):
        try:
            if hasattr(self, "web_view") and self.web_view:
                self.web_view.evaluate_javascript(
                    """
                    (function() {
                        try {
                            document.querySelectorAll('video').forEach(function(v) {
                                if (!v.paused) {
                                    v._web2gtk_paused = true;
                                    v.pause();
                                }
                            });
                        } catch(e) {}
                    })();
                    """,
                    -1, None, None, None, None, None
                )
        except Exception:
            pass

    def resume_media(self):
        try:
            if hasattr(self, "web_view") and self.web_view:
                self.web_view.evaluate_javascript(
                    """
                    (function() {
                        try {
                            document.querySelectorAll('video').forEach(function(v) {
                                if (v._web2gtk_paused) {
                                    v._web2gtk_paused = false;
                                    v.play().catch(function(){});
                                }
                            });
                        } catch(e) {}
                    })();
                    """,
                    -1, None, None, None, None, None
                )
        except Exception:
            pass

    def on_window_visibility_changed(self, *_):
        if not self.get_visible():
            self.pause_media()
        else:
            self.resume_media()

    def on_window_suspended_changed(self, *_):
        if hasattr(self.props, "suspended") and self.props.suspended:
            self.pause_media()
        else:
            self.resume_media()

    def on_show_notification(self, web_view, notification):
        title = notification.get_title() or self.manifest.name
        body = notification.get_body() or ""
        self.send_desktop_notification(title, body, urgency=1)
        return True

    def on_decide_policy(self, web_view, decision, decision_type):
        if decision_type == WebKit.PolicyDecisionType.RESPONSE:
            if not decision.is_mime_type_supported():
                decision.download()
                return True
        return False

    def on_load_changed(self, web_view, load_event):
        if load_event in (WebKit.LoadEvent.COMMITTED, WebKit.LoadEvent.FINISHED):
            self.progress_bar.set_fraction(1.0)
            self.progress_bar.set_visible(False)
            self.btn_back.set_sensitive(web_view.can_go_back())
            self.btn_forward.set_sensitive(web_view.can_go_forward())
            web_view.grab_focus()

    def on_load_failed(self, web_view, load_event, failing_uri, error):
        """Ignore navigation cancellations (e.g. client redirects, pushState) to avoid error pages."""
        self.progress_bar.set_visible(False)
        if getattr(error, "code", None) == 302 or "cancelled" in str(error).lower():
            return True
        return False

    def on_create_popup(self, web_view, navigation_action):
        """Handle popup windows (OAuth logins) and route external links to default browser."""
        req = navigation_action.get_request()
        uri = req.get_uri() if req else None

        # External non-auth links open directly in system browser
        if uri and uri not in ("about:blank", ""):
            if not is_auth_url(uri) and not is_same_app_domain(uri, self.manifest.url):
                try:
                    Gio.AppInfo.launch_default_for_uri(uri, None)
                except Exception as e:
                    print(f"[{self.manifest.slug}] Error launching default browser: {e}")
                return None

        popup = Adw.Window(transient_for=self, modal=False)
        popup.set_default_size(520, 680)

        popup_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        popup.set_content(popup_box)

        popup_header = Adw.HeaderBar()
        popup_header.add_css_class("flat")
        popup_title = Adw.WindowTitle(title="Login")
        popup_header.set_title_widget(popup_title)
        popup_box.append(popup_header)

        # Related view automatically inherits the parent view's network session
        popup_web_view = WebKit.WebView(
            related_view=web_view,
            user_content_manager=self.user_content_manager,
            settings=self.settings
        )
        popup_web_view.set_vexpand(True)
        popup_web_view.set_hexpand(True)
        popup_box.append(popup_web_view)

        def on_popup_decide_policy(wv, decision, decision_type):
            if decision_type == WebKit.PolicyDecisionType.NAVIGATION_ACTION:
                nav_action = decision.get_navigation_action()
                target_req = nav_action.get_request()
                target_uri = target_req.get_uri() if target_req else None
                if target_uri and target_uri not in ("about:blank", ""):
                    if not is_auth_url(target_uri) and not is_same_app_domain(target_uri, self.manifest.url):
                        try:
                            Gio.AppInfo.launch_default_for_uri(target_uri, None)
                        except Exception as e:
                            print(f"[{self.manifest.slug}] Error launching default browser: {e}")
                        decision.ignore()
                        popup.close()
                        return True
            elif decision_type == WebKit.PolicyDecisionType.RESPONSE:
                if not decision.is_mime_type_supported():
                    decision.download()
                    popup.close()
                    return True
            return False

        popup_web_view.connect("decide-policy", on_popup_decide_policy)
        popup_web_view.connect(
            "notify::title",
            lambda wv, _: popup_title.set_title(wv.get_title() or "Login")
        )
        popup_web_view.connect("close", lambda _: popup.close())

        popup.present()
        return popup_web_view

    def on_permission_request(self, web_view, request):
        if isinstance(request, (WebKit.UserMediaPermissionRequest,
                                WebKit.DeviceInfoPermissionRequest,
                                WebKit.NotificationPermissionRequest)):
            request.allow()
            return True
        return False

    def on_download_started(self, session, download):
        """Route downloads to ~/Downloads with non-clobbering filenames."""
        def on_decide_destination(dl, suggested_filename):
            try:
                os.makedirs(DOWNLOAD_DIR, exist_ok=True)
                filename = suggested_filename or "download"
                dest_path = os.path.join(DOWNLOAD_DIR, filename)
                base, ext = os.path.splitext(dest_path)
                counter = 1
                while os.path.exists(dest_path):
                    dest_path = f"{base} ({counter}){ext}"
                    counter += 1

                # WebKitDownload expects a native absolute path, NOT a file:// URI
                dl.set_destination(dest_path)

                def on_finished(d):
                    filename = os.path.basename(dest_path)
                    print(f"[{self.manifest.slug}] Download finished: {dest_path}")
                    self.send_desktop_notification(
                        summary="Download Complete",
                        body=f"{filename} saved to ~/Downloads",
                        urgency=2
                    )
                    if hasattr(self, "tray") and self.tray:
                        self.tray.set_attention(True, f"Download: {filename}")

                dl.connect("finished", on_finished)
                dl.connect(
                    "failed",
                    lambda d, err: print(f"[{self.manifest.slug}] Download failed: {err.message}")
                )
            except Exception as e:
                print(f"[{self.manifest.slug}] Download error: {e}")
            return True

        download.connect("decide-destination", on_decide_destination)

    def load_window_state(self):
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return self.manifest.window or {"width": 1080, "height": 800, "is_maximized": False}

    def save_window_state(self):
        try:
            os.makedirs(self.manifest.config_dir, exist_ok=True)
            data = {
                "width": self.get_width(),
                "height": self.get_height(),
                "is_maximized": self.is_maximized()
            }
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except Exception:
            pass

    def on_close_request(self, _):
        self.save_window_state()
        if self.manifest.system_tray:
            self.set_visible(False)
            return True
        self.app.quit()
        return False
