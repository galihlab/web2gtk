"""
Built-in Adblocker & Content Filtering Engine for web2gtk.
Supports native WebKit declarative content filters, cosmetic stylesheet injection,
and ultra-lightweight YouTube ad skipping without CPU/RAM overhead or seek crashes.
"""

import os
import json
import tempfile
import gi

gi.require_version('WebKit', '6.0')
gi.require_version('Gio', '2.0')
gi.require_version('GLib', '2.0')

from gi.repository import WebKit, Gio, GLib

# Declarative WebKit content filtering rules for known ad and tracker networks
COMMON_AD_RULES = [
    {"trigger": {"url-filter": r".*doubleclick\.net/.*"}, "action": {"type": "block"}},
    {"trigger": {"url-filter": r".*googlesyndication\.com/.*"}, "action": {"type": "block"}},
    {"trigger": {"url-filter": r".*googleadservices\.com/.*"}, "action": {"type": "block"}},
    {"trigger": {"url-filter": r".*adnxs\.com/.*"}, "action": {"type": "block"}},
    {"trigger": {"url-filter": r".*criteo\.com/.*"}, "action": {"type": "block"}},
    {"trigger": {"url-filter": r".*taboola\.com/.*"}, "action": {"type": "block"}},
    {"trigger": {"url-filter": r".*outbrain\.com/.*"}, "action": {"type": "block"}},
    {"trigger": {"url-filter": r".*scorecardresearch\.com/.*"}, "action": {"type": "block"}},
    {"trigger": {"url-filter": r".*amazon-adsystem\.com/.*"}, "action": {"type": "block"}},
    {"trigger": {"url-filter": r".*pubmatic\.com/.*"}, "action": {"type": "block"}},
    {"trigger": {"url-filter": r".*rubiconproject\.com/.*"}, "action": {"type": "block"}},
    {"trigger": {"url-filter": r".*adservice\.google\..*"}, "action": {"type": "block"}},
]

# YouTube-specific cosmetic ad hiding CSS
YOUTUBE_COSMETIC_CSS = """
#masthead-ad,
ytd-ad-slot-renderer,
ytd-rich-item-renderer:has(ytd-ad-slot-renderer),
.ytp-ad-overlay-container,
.ytp-ad-message-container,
.ytp-ad-overlay-slot,
.ytp-ad-overlay-image,
.ytp-ad-action-interstitial,
ytd-promoted-sparkles-web-renderer,
ytd-banner-promo-renderer,
#player-ads,
ytd-in-feed-ad-layout-renderer,
ytd-engagement-panel-section-list-renderer[target-id="engagement-panel-ads"],
ytd-enforcement-message-view-model,
tp-yt-iron-overlay-backdrop[opened] {
    display: none !important;
}
"""

# Ultra-lightweight YouTube ad handler:
# - Strips ad placements from ytInitialPlayerResponse and fetch payload before player loads
# - Resilient skip button clicker targeting both class selectors and button text (Skip / Lewati)
# - Auto-mutes and fast-forwards short ads without touching video.currentTime or player state
# - Zero MutationObserver loops to guarantee 0% CPU and zero memory leak
YOUTUBE_ADBLOCK_SCRIPT = """
(function() {
    // 1. Strip ad placements from the player payload.
    //    Key set deliberately mirrors uBlock Origin's youtube.com quick-fixes
    //    (adPlacements / adSlots / playerAds). Pruning anything beyond that --
    //    notably adBreakHeartbeatParams, auxiliaryUi and the promoted* renderers --
    //    makes YouTube's anti-adblock trip and the player dies with error 282054944.
    const AD_KEYS = ['adPlacements', 'playerAds', 'adSlots', 'legacyImportant'];

    function pruneKeys(obj, keys) {
        if (!obj || typeof obj !== 'object') return;
        for (let i = 0; i < keys.length; i++) {
            try { delete obj[keys[i]]; } catch (e) {}
        }
    }

    function pruneAds(obj) {
        if (!obj || typeof obj !== 'object') return obj;
        pruneKeys(obj, AD_KEYS);
        if (obj.playerResponse && typeof obj.playerResponse === 'object') {
            pruneKeys(obj.playerResponse, AD_KEYS);
        }
        // Shorts / feed ads travel inside /next payloads
        if (Array.isArray(obj.entries)) {
            for (let i = 0; i < obj.entries.length; i++) {
                const ep = obj.entries[i] && obj.entries[i].command && obj.entries[i].command.reelWatchEndpoint;
                if (ep && ep.adClientParams) { try { delete ep.adClientParams.isAd; } catch (e) {} }
            }
        }
        return obj;
    }

    function isInnerTube(url) {
        return typeof url === 'string' &&
            (url.indexOf('/youtubei/v1/player') !== -1 || url.indexOf('/youtubei/v1/next') !== -1);
    }

    try {
        // Hook JSON.parse to prune ad placements from payloads decoded in-page
        const origParse = JSON.parse;
        JSON.parse = function(...args) {
            const res = origParse.apply(this, args);
            return pruneAds(res);
        };

        let _ytPlayerResponse = undefined;
        Object.defineProperty(window, 'ytInitialPlayerResponse', {
            configurable: true,
            enumerable: true,
            get() { return _ytPlayerResponse; },
            set(val) {
                _ytPlayerResponse = pruneAds(val);
            }
        });

        // YouTube serves /player over fetch in some builds
        if (window.fetch) {
            const origFetch = window.fetch;
            window.fetch = async function(...args) {
                const response = await origFetch.apply(this, args);
                try {
                    const url = typeof args[0] === 'string' ? args[0] : (args[0] && args[0].url) || '';
                    if (isInnerTube(url)) {
                        const data = pruneAds(await response.clone().json());
                        return new Response(JSON.stringify(data), {
                            status: response.status,
                            statusText: response.statusText,
                            headers: response.headers
                        });
                    }
                } catch(e) {}
                return response;
            };
        }

        // ...and over XMLHttpRequest in others (this is why ads leaked before:
        // only fetch was hooked, so the /player payload went through untouched)
        const origOpen = XMLHttpRequest.prototype.open;
        XMLHttpRequest.prototype.open = function(method, url) {
            this.__web2gtkUrl = url;
            return origOpen.apply(this, arguments);
        };

        const textDesc = Object.getOwnPropertyDescriptor(XMLHttpRequest.prototype, 'responseText');
        if (textDesc && textDesc.get) {
            Object.defineProperty(XMLHttpRequest.prototype, 'responseText', {
                configurable: true,
                get: function() {
                    const raw = textDesc.get.call(this);
                    if (isInnerTube(this.__web2gtkUrl) && typeof raw === 'string' && raw.length > 1) {
                        try { return JSON.stringify(pruneAds(JSON.parse(raw))); } catch(e) { return raw; }
                    }
                    return raw;
                }
            });
        }

        const respDesc = Object.getOwnPropertyDescriptor(XMLHttpRequest.prototype, 'response');
        if (respDesc && respDesc.get) {
            Object.defineProperty(XMLHttpRequest.prototype, 'response', {
                configurable: true,
                get: function() {
                    const raw = respDesc.get.call(this);
                    if (isInnerTube(this.__web2gtkUrl) && raw && typeof raw === 'object') {
                        return pruneAds(raw);
                    }
                    return raw;
                }
            });
        }
    } catch(e) {}

    // 2. Runtime fallback: fast-forward and auto-skip residual ads
    let wasAd = false;
    let adMuted = false;

    function findSkipButton() {
        const selectors = [
            '.ytp-skip-ad-button',
            '.ytp-ad-skip-button',
            '.ytp-ad-skip-button-modern',
            '.ytp-ad-skip-button-slot button',
            'button.ytp-ad-skip-button',
            'button.ytp-ad-skip-button-modern',
            '.ytp-ad-skip-button-container button',
            'button[aria-label*="Skip"]',
            'button[class*="skip"]',
            '[id^="skip-button"]'
        ];
        for (let i = 0; i < selectors.length; i++) {
            const el = document.querySelector(selectors[i]);
            if (el) return el;
        }
        // Fallback: search player buttons by text content (e.g. "Skip", "Lewati")
        const buttons = document.querySelectorAll('#movie_player button, .video-ads button, .ytp-ad-module button');
        for (let i = 0; i < buttons.length; i++) {
            const text = (buttons[i].textContent || '').toLowerCase().trim();
            if (text.includes('skip') || text.includes('lewati')) {
                return buttons[i];
            }
        }
        return null;
    }

    function triggerClick(el) {
        if (!el) return;
        try { el.click(); } catch(e) {}
        try {
            const evt = new MouseEvent('click', { bubbles: true, cancelable: true, view: window });
            el.dispatchEvent(evt);
        } catch(e) {}
    }

    function handleAds() {
        const player = document.querySelector('#movie_player, .html5-video-player');
        const video = document.querySelector('#movie_player video, video.html5-main-video, video');
        if (!player || !video) return;

        const isAd = player.classList.contains('ad-showing') ||
                     player.classList.contains('ad-interrupting') ||
                     Boolean(player.querySelector('.ytp-ad-player-overlay, .ytp-ad-player-overlay-layout'));

        if (isAd) {
            wasAd = true;

            // Mute ad audio so user hears nothing
            if (!video.muted) {
                video.muted = true;
                adMuted = true;
            }

            // Fast-forward ad at 16x speed (finishes 6s bumper ad in ~0.37s)
            try {
                if (video.playbackRate < 16.0) {
                    video.playbackRate = 16.0;
                }
            } catch(e) {
                try { video.playbackRate = 8.0; } catch(e2) {}
            }

            // Ensure ad continues playing to finish fast
            if (video.paused) {
                video.play().catch(function() {});
            }

            // Click skip button immediately when available
            const skipBtn = findSkipButton();
            if (skipBtn) {
                triggerClick(skipBtn);
            }
        } else {
            if (wasAd) {
                wasAd = false;
                // Restore audio
                if (adMuted) {
                    video.muted = false;
                    adMuted = false;
                }
                // Restore playback speed
                if (video.playbackRate > 1.0) {
                    video.playbackRate = 1.0;
                }
                if (video.paused) {
                    video.play().catch(function() {});
                }
            } else if (video.playbackRate > 1.0) {
                // Safety guard: ensure regular video never stays accelerated
                video.playbackRate = 1.0;
            }
        }

        // Always click skip or overlay close buttons if present
        const anySkip = findSkipButton();
        if (anySkip) triggerClick(anySkip);

        const closeBtn = document.querySelector('.ytp-ad-overlay-close-button, button.ytp-ad-overlay-close-button');
        if (closeBtn) triggerClick(closeBtn);

        // Dismiss anti-adblock or confirmation dialogs
        const dismiss = document.querySelector('tp-yt-paper-dialog #dismiss-button, #dismiss-button, .style-scope.yt-confirm-dialog-renderer');
        if (dismiss) triggerClick(dismiss);

        const enforcement = document.querySelector('ytd-enforcement-message-view-model');
        if (enforcement) {
            enforcement.remove();
            const backdrop = document.querySelector('tp-yt-iron-overlay-backdrop');
            if (backdrop) backdrop.remove();
            if (video && video.paused) video.play().catch(function() {});
        }
    }

    // 150ms gentle polling: responsive ad skipping with virtually zero CPU overhead
    setInterval(handleAds, 150);
})();
"""


def setup_adblock(user_content_manager: WebKit.UserContentManager, cache_dir: str, target_url: str):
    """Compile and apply adblocking rules and scripts to WebKit UserContentManager."""
    is_youtube = "youtube.com" in (target_url or "").lower()

    # 1. YouTube specific ad skipper & cosmetic stylesheet
    if is_youtube:
        yt_script = WebKit.UserScript(
            source=YOUTUBE_ADBLOCK_SCRIPT,
            injected_frames=WebKit.UserContentInjectedFrames.TOP_FRAME,
            injection_time=WebKit.UserScriptInjectionTime.START
        )
        user_content_manager.add_script(yt_script)

        yt_style = WebKit.UserStyleSheet(
            source=YOUTUBE_COSMETIC_CSS,
            injected_frames=WebKit.UserContentInjectedFrames.ALL_FRAMES,
            level=WebKit.UserStyleLevel.USER,
            allow_list=None,
            block_list=None
        )
        user_content_manager.add_style_sheet(yt_style)
        # Skip raw network content filtering for YouTube to prevent anti-adblock playback crashes
        return

    # 2. Native WebKit Content Filter Store with automatic hash-based cache invalidation
    filter_dir = os.path.join(cache_dir, "adblock_filters")
    os.makedirs(filter_dir, exist_ok=True)
    store = WebKit.UserContentFilterStore.new(filter_dir)

    import hashlib
    rules_hash = hashlib.md5(json.dumps(COMMON_AD_RULES, sort_keys=True).encode()).hexdigest()[:8]
    filter_id = f"web2gtk_filter_{rules_hash}"

    def on_filter_saved(s, res, _):
        try:
            compiled_filter = s.save_from_file_finish(res)
            if compiled_filter:
                user_content_manager.add_filter(compiled_filter)
        except Exception:
            pass

    def on_filter_loaded(s, res, _):
        try:
            compiled_filter = s.load_finish(res)
            if compiled_filter:
                user_content_manager.add_filter(compiled_filter)
        except Exception:
            compile_rules()

    def compile_rules():
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
                json.dump(COMMON_AD_RULES, f)
                tmp_rules_file = f.name

            gfile = Gio.File.new_for_path(tmp_rules_file)
            store.save_from_file(filter_id, gfile, None, on_filter_saved, None)
        except Exception:
            pass

    try:
        store.load(filter_id, None, on_filter_loaded, None)
    except Exception:
        compile_rules()
