import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import argparse
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

from web2gtk import __version__
from web2gtk.manifest import AppManifest, slugify
from web2gtk.generator import install_app, uninstall_app
from web2gtk.engine.runner import run_manifest
from web2gtk.exporter import export_standalone, export_arch_pkgbuild


REPO_URL = "https://github.com/galihlab/web2gtk.git"
REPO_BRANCH = "main"
TARBALL_URL = f"https://github.com/galihlab/web2gtk/archive/refs/heads/{REPO_BRANCH}.tar.gz"


def _repo_root() -> Path:
    """Absolute path of the source checkout this module was loaded from."""
    return Path(__file__).resolve().parents[1]


def _version_on_disk(root: Path) -> str:
    """Read __version__ from the file so it reflects a just-completed pull."""
    try:
        text = (root / "web2gtk" / "__init__.py").read_text(encoding="utf-8")
    except OSError:
        return "unknown"
    match = re.search(r"""__version__\s*=\s*["']([^"']+)["']""", text)
    return match.group(1) if match else "unknown"


def cmd_create(args):
    url = args.url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    # Deduce name from URL if not given
    name = args.name
    if not name:
        domain = urlparse(url).netloc
        # remove www. and tld
        parts = domain.replace("www.", "").split(".")
        name = parts[0].capitalize() if parts else "WebApp"

    slug = args.slug or slugify(name)
    if not slug.endswith("-gtk"):
        slug += "-gtk"

    app_id = args.id or f"io.github.web2gtk.{slug.replace('-', '_')}"
    icon_name = args.icon_name or slug

    print(f"==> Creating web app for '{name}' ({url})...")
    manifest = AppManifest(
        name=name,
        url=url,
        slug=slug,
        app_id=app_id,
        icon=icon_name,
        stealth=not args.no_stealth,
        persistent_storage=not args.no_persistent,
        system_tray=not args.no_tray,
        adblock=not args.no_adblock
    )

    install_app(manifest, icon_path_or_url=args.icon)
    print(f"==> Installed successfully!")
    print(f"    - Launcher: ~/.local/bin/{manifest.slug}")
    print(f"    - Desktop:  ~/.local/share/applications/{manifest.slug}.desktop")
    print(f"    - Manifest: {manifest.manifest_path}")
    print(f"    - Storage:  {manifest.data_dir} (Persistent SQLite Cookies & LocalStorage)")
    print(f"\nYou can now launch '{manifest.slug}' from terminal or search for '{manifest.name}' in your applications menu.")

    if args.run:
        print(f"\n==> Launching {manifest.name}...")
        run_manifest(manifest)


def cmd_list(args):
    apps = AppManifest.list_all()
    if not apps:
        print("No web apps installed yet.")
        print("Run: web2gtk create <url> --name <name>")
        return

    print(f"{'SLUG':<20} {'NAME':<22} {'URL':<32} {'TRAY':<6} {'STEALTH':<8} {'ADBLOCK':<8}")
    print("-" * 102)
    for app in apps:
        tray = "Yes" if app.system_tray else "No"
        stealth = "Yes" if app.stealth else "No"
        adblock = "Yes" if getattr(app, "adblock", True) else "No"
        print(f"{app.slug:<20} {app.name:<22} {app.url:<32} {tray:<6} {stealth:<8} {adblock:<8}")


def cmd_remove(args):
    slug = args.slug
    print(f"==> Removing web app '{slug}'...")
    uninstall_app(slug, purge_data=args.purge)
    print(f"==> Web app '{slug}' successfully removed from system.")
    if args.purge:
        print("    Session data and cookies have also been purged.")


def cmd_run(args):
    try:
        manifest = AppManifest.load(args.slug)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    run_manifest(manifest)


def cmd_info(args):
    try:
        manifest = AppManifest.load(args.slug)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Name:        {manifest.name}")
    print(f"Slug:        {manifest.slug}")
    print(f"URL:         {manifest.url}")
    print(f"App ID:      {manifest.app_id}")
    print(f"Icon:        {manifest.icon}")
    print(f"System Tray: {'Yes' if manifest.system_tray else 'No'}")
    print(f"Anti-Bot:    {'Yes' if manifest.stealth else 'No'}")
    print(f"Adblock:     {'Yes' if getattr(manifest, 'adblock', True) else 'No'}")
    print(f"Data Dir:    {manifest.data_dir}")
    print(f"Cache Dir:   {manifest.cache_dir}")
    print(f"Config Dir:  {manifest.config_dir}")


def cmd_export(args):
    try:
        manifest = AppManifest.load(args.slug)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    fmt = args.format.lower()
    output_dir = args.output or "dist"

    print(f"==> Exporting '{manifest.name}' ({manifest.slug}) format={fmt}...")
    if fmt in ("standalone", "tar", "tar.gz"):
        out_path = export_standalone(manifest, output_dir=output_dir)
        print(f"==> Standalone installer package created successfully:")
        print(f"    - Tarball:   {out_path}")
        print(f"    - Directory: {os.path.splitext(os.path.splitext(out_path)[0])[0]}")
        print(f"\nTo share with others:")
        print(f"  Send the file '{out_path}'.")
        print(f"  The recipient simply extracts it and runs './install.sh'!")
    elif fmt in ("arch", "pkgbuild"):
        out_path = export_arch_pkgbuild(manifest, output_dir=output_dir)
        print(f"==> PKGBUILD directory generated successfully:")
        print(f"    - Path: {out_path}")
        print(f"\nTo build the Arch package:")
        print(f"  cd {out_path} && makepkg -si")
    else:
        print(f"Unsupported export format: {fmt}", file=sys.stderr)
        sys.exit(1)


def cmd_update(args):
    """Update this web2gtk installation in place from the upstream repository."""
    root = _repo_root()
    before_version = __version__
    git_dir = root / ".git"
    use_git = git_dir.is_dir() and shutil.which("git") is not None

    print(f"==> web2gtk {before_version}")
    print(f"    Source: {root}")

    if use_git:

        def git(*argv):
            return subprocess.run(
                ["git", "-C", str(root), *argv],
                capture_output=True,
                text=True,
            )

        before_sha = git("rev-parse", "--short", "HEAD").stdout.strip() or "unknown"
        print(f"    Commit: {before_sha}")
        print(f"==> Pulling latest changes from origin/{REPO_BRANCH}...")

        if args.force:
            result = git("fetch", "--depth=1", "origin", REPO_BRANCH)
            if result.returncode == 0:
                result = git("reset", "--hard", "FETCH_HEAD")
        else:
            result = git("pull", "--ff-only")

        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            print(f"[ERROR] Update failed:\n{detail}", file=sys.stderr)
            print("    Local changes in the install directory block the update.", file=sys.stderr)
            print("    Re-run with 'web2gtk update --force' to discard them.", file=sys.stderr)
            sys.exit(1)

        after_sha = git("rev-parse", "--short", "HEAD").stdout.strip() or "unknown"
        changed = before_sha != after_sha

    elif git_dir.is_dir():
        print("[ERROR] This is a git checkout but 'git' is not installed.", file=sys.stderr)
        print("    Install git, or re-run the installer script.", file=sys.stderr)
        sys.exit(1)

    else:
        # Installed from a source archive: fetch the archive again and copy it over.
        print("==> Not a git checkout - downloading the latest source archive...")
        print(f"    {TARBALL_URL}")
        incoming_version = before_version
        try:
            with tempfile.TemporaryDirectory(prefix="web2gtk-update-") as tmp:
                archive = Path(tmp) / "web2gtk.tar.gz"
                with urlopen(TARBALL_URL, timeout=60) as response, open(archive, "wb") as handle:
                    shutil.copyfileobj(response, handle)

                with tarfile.open(archive) as tar:
                    try:
                        tar.extractall(tmp, filter="data")
                    except TypeError:  # filter= added in Python 3.12
                        tar.extractall(tmp)

                extracted = [
                    p for p in Path(tmp).iterdir()
                    if p.is_dir() and p.name.startswith("web2gtk-")
                ]
                if not extracted:
                    raise RuntimeError("archive did not contain a web2gtk-* directory")

                source = extracted[0]
                incoming_version = _version_on_disk(source)

                for item in source.iterdir():
                    destination = root / item.name
                    if item.is_dir():
                        shutil.copytree(item, destination, dirs_exist_ok=True)
                    else:
                        shutil.copy2(item, destination)
        except Exception as exc:
            print(f"[ERROR] Update failed: {exc}", file=sys.stderr)
            sys.exit(1)

        changed = incoming_version != before_version

    after_version = _version_on_disk(root)

    print()
    if not changed:
        print("==> Already up to date.")
    elif use_git:
        print(f"==> Updated: {before_sha} -> {after_sha}")
    else:
        print("==> Updated from the latest source archive.")

    if before_version != after_version:
        print(f"    Version: {before_version} -> {after_version}")
    else:
        print(f"    Version: {after_version}")

    print()
    print("Restart any running web2gtk apps to pick up the new engine.")
    print("Installed apps, their manifests and saved sessions were left untouched.")


def main():
    parser = argparse.ArgumentParser(
        prog="web2gtk",
        description="Lightweight native GTK4/Libadwaita desktop web app generator for Linux"
    )
    parser.add_argument(
        "--version", "-V",
        action="version",
        version=f"web2gtk {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Command: create
    create_parser = subparsers.add_parser("create", help="Create and install a new web app")
    create_parser.add_argument("url", help="Target website URL (e.g. https://claude.ai)")
    create_parser.add_argument("--name", "-n", help="Display name for the application")
    create_parser.add_argument("--slug", "-s", help="Custom executable slug (default: name-gtk)")
    create_parser.add_argument("--id", help="Custom desktop Application ID")
    create_parser.add_argument("--icon", "-i", help="Path to custom icon file (PNG/SVG/ICO)")
    create_parser.add_argument("--icon-name", help="Existing system icon name")
    create_parser.add_argument("--no-tray", action="store_true", help="Disable D-Bus system tray")
    create_parser.add_argument("--no-stealth", action="store_true", help="Disable anti-bot stealth script")
    create_parser.add_argument("--no-persistent", action="store_true", help="Use ephemeral in-memory session")
    create_parser.add_argument("--no-adblock", action="store_true", help="Disable built-in adblocker and YouTube ad-skipping")
    create_parser.add_argument("--run", "-r", action="store_true", help="Launch immediately after creation")
    create_parser.set_defaults(func=cmd_create)

    # Command: list
    list_parser = subparsers.add_parser("list", help="List all installed web apps")
    list_parser.set_defaults(func=cmd_list)

    # Command: remove
    remove_parser = subparsers.add_parser("remove", aliases=["uninstall"], help="Remove an installed web app")
    remove_parser.add_argument("slug", help="Slug of the app to remove")
    remove_parser.add_argument("--purge", "-p", action="store_true", help="Also delete saved sessions and cookies")
    remove_parser.set_defaults(func=cmd_remove)

    # Command: run
    run_parser = subparsers.add_parser("run", help="Run an installed app by slug")
    run_parser.add_argument("slug", help="Slug of the app to run")
    run_parser.set_defaults(func=cmd_run)

    # Command: info
    info_parser = subparsers.add_parser("info", help="Show details of an installed app")
    info_parser.add_argument("slug", help="Slug of the app")
    info_parser.set_defaults(func=cmd_info)

    # Command: export
    export_parser = subparsers.add_parser("export", help="Export app into standalone bundle or PKGBUILD")
    export_parser.add_argument("slug", help="Slug of the app to export")
    export_parser.add_argument("--format", "-f", choices=["standalone", "arch"], default="standalone", help="Export format (default: standalone)")
    export_parser.add_argument("--output", "-o", default="dist", help="Output directory (default: dist)")
    export_parser.set_defaults(func=cmd_export)

    # Command: update
    update_parser = subparsers.add_parser(
        "update", aliases=["upgrade"], help="Update web2gtk itself to the latest version"
    )
    update_parser.add_argument("--force", "-f", action="store_true",
                               help="Discard local changes and hard-reset to origin (git checkouts only)")
    update_parser.set_defaults(func=cmd_update)

    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(0)

    args.func(args)


if __name__ == "__main__":
    main()
