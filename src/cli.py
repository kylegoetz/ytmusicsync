import argparse
import sys
from pathlib import Path
from typing import Any

from tqdm import tqdm

from src.cache_manager import UploadsCache
from src.m3u_parser import find_m3u_files, parse_m3u
from src.matcher import TrackMatcher
from src.playlist_builder import PlaylistBuilder
from src.ytm_client import YTMClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ytmusicsync",
        description="Sync legacy iTunes M3U playlists to YouTube Music using only your uploaded music."
    )
    subparsers = parser.add_subparsers(dest="command", required=True, help="Available subcommands")

    # Command: auth
    auth_parser = subparsers.add_parser("auth", help="Configure or verify YouTube Music credentials")
    auth_parser.add_argument("--file", "-f", type=str, default=None, help="Path to auth JSON (e.g. browser.json or oauth.json)")
    auth_parser.add_argument("--verify", action="store_true", help="Verify connection with current credentials")

    # Command: cache
    cache_parser = subparsers.add_parser("cache", help="Download and cache uploaded music library catalog to SQLite")
    cache_parser.add_argument("--auth-file", type=str, default=None, help="Path to auth JSON")
    cache_parser.add_argument("--cache-db", type=str, default="uploads_cache.sqlite", help="Path to SQLite database")
    cache_parser.add_argument("--limit", type=int, default=None, help="Limit number of songs to fetch (for testing)")

    # Command: sync
    sync_parser = subparsers.add_parser("sync", help="Sync a single M3U playlist file to YouTube Music")
    sync_parser.add_argument("m3u", type=str, help="Path to .m3u or .m3u8 playlist file")
    sync_parser.add_argument("--name", type=str, default=None, help="Custom name for the YouTube Music playlist")
    sync_parser.add_argument("--dry-run", action="store_true", help="Preview matches and generate report without creating playlists")
    sync_parser.add_argument("--music-root", type=str, default=None, help="Optional root folder of audio files (e.g. synced Mega folder) to verify local files")
    sync_parser.add_argument("--cache-db", type=str, default="uploads_cache.sqlite", help="Path to SQLite uploads cache")
    sync_parser.add_argument("--auth-file", type=str, default=None, help="Path to auth JSON")
    sync_parser.add_argument("--fuzzy-threshold", type=float, default=88.0, help="Minimum fuzzy match score (0-100, default: 88)")
    sync_parser.add_argument("--allow-duplicates", action="store_true", help="Allow duplicate songs in the playlist")
    sync_parser.add_argument("--report-path", type=str, default=None, help="Custom output path for CSV audit report")

    # Command: batch-sync
    batch_parser = subparsers.add_parser("batch-sync", help="Sync all M3U playlists in a directory to YouTube Music")
    batch_parser.add_argument("folder", type=str, help="Directory containing .m3u / .m3u8 files")
    batch_parser.add_argument("--dry-run", action="store_true", help="Preview matches without creating playlists")
    batch_parser.add_argument("--music-root", type=str, default=None, help="Optional root folder of audio files (e.g. synced Mega folder) to verify local files")
    batch_parser.add_argument("--cache-db", type=str, default="uploads_cache.sqlite", help="Path to SQLite uploads cache")
    batch_parser.add_argument("--auth-file", type=str, default=None, help="Path to auth JSON")
    batch_parser.add_argument("--fuzzy-threshold", type=float, default=88.0, help="Minimum fuzzy match score (0-100, default: 88)")
    batch_parser.add_argument("--allow-duplicates", action="store_true", help="Allow duplicate songs in playlists")
    batch_parser.add_argument("--reports-dir", type=str, default="reports", help="Directory to save CSV audit reports and failure logs")

    return parser


def handle_auth(args: argparse.Namespace) -> int:
    auth_file = Path(args.file) if args.file else None
    print("=== YouTube Music Authentication Setup ===")
    
    # Try testing current client
    try:
        client = YTMClient(auth_file)
        if args.verify or client.auth_path:
            print(f"Testing existing credentials from: {client.auth_path}...")
            result = client.test_connection()
            if result["status"] == "ok":
                print("✓ Successfully authenticated with YouTube Music!")
                return 0
            else:
                print(f"✗ Authentication failed: {result['error']}")
    except Exception as e:
        print(f"No valid session found: {e}")

    print("\nHow would you like to authenticate?")
    print("  [1] Browser Session Setup (Recommended - easy, no developer account required)")
    print("  [2] OAuth TV Device Login (Requires Google Cloud OAuth Client ID)")
    print("  [q] Quit")
    
    choice = input("\nEnter choice (1/2/q): ").strip()
    if choice == "1":
        from ytmusicapi.setup import setup
        print("\nOpening interactive browser setup:")
        print("1. Open https://music.youtube.com in Chrome or Firefox (logged in).")
        print("2. Open Developer Tools (F12 or Inspect) -> Network tab.")
        print("3. In the filter box, type 'browse'.")
        print("4. Click on 'Library' or 'Uploads' in YouTube Music.")
        print("5. Right-click the 'browse' request in Network -> Copy -> Copy request headers.")
        print("6. Paste them below when prompted, and press Enter, then Ctrl-D (or EOF).\n")
        try:
            setup(filepath="browser.json")
            print("✓ Successfully saved credentials to browser.json!")
            return 0
        except Exception as e:
            print(f"✗ Setup failed: {e}")
            return 1
    elif choice == "2":
        from ytmusicapi.setup import setup_oauth
        client_id = input("Enter Google Cloud OAuth Client ID: ").strip()
        client_secret = input("Enter Google Cloud OAuth Client Secret: ").strip()
        try:
            setup_oauth(client_id=client_id, client_secret=client_secret, filepath="oauth.json")
            print("✓ Successfully saved credentials to oauth.json!")
            return 0
        except Exception as e:
            print(f"✗ OAuth setup failed: {e}")
            return 1
    return 0


def handle_cache(args: argparse.Namespace) -> int:
    cache = UploadsCache(args.cache_db)
    print(f"Connecting to YouTube Music and caching uploads to {args.cache_db}...")
    
    try:
        client = YTMClient(args.auth_file)
    except Exception as e:
        print(f"✗ Authentication error: {e}")
        print("Run 'python main.py auth' first to authenticate.")
        return 1

    pbar = tqdm(unit="songs", desc="Caching uploaded songs")

    def on_batch(count: int):
        pbar.n = count
        pbar.refresh()

    try:
        total = client.sync_uploaded_songs_to_cache(cache=cache, limit=args.limit, batch_callback=on_batch)
        pbar.close()
        print(f"✓ Cached {total} uploaded songs in {args.cache_db}.")
        return 0
    except Exception as e:
        pbar.close()
        print(f"✗ Error caching uploaded songs: {e}")
        return 1


def run_sync_single(
    m3u_path: Path | str,
    cache_db: Path | str = "uploads_cache.sqlite",
    auth_file: Path | str | None = None,
    custom_name: str | None = None,
    dry_run: bool = False,
    fuzzy_threshold: float = 88.0,
    allow_duplicates: bool = False,
    report_path: Path | str | None = None,
    log_path: Path | str | None = None,
    music_root: Path | str | None = None,
    matcher: TrackMatcher | None = None
) -> dict[str, Any]:
    m3u = Path(m3u_path)
    if not m3u.exists():
        raise FileNotFoundError(f"M3U playlist not found: {m3u}")

    if matcher is None:
        cache = UploadsCache(cache_db)
        if cache.get_total_count() == 0:
            raise RuntimeError(
                f"Uploads cache '{cache_db}' is empty! "
                "Please run 'python main.py cache' first to download your uploaded songs library."
            )
        matcher = TrackMatcher(cache, fuzzy_threshold=fuzzy_threshold)

    playlist_name = custom_name or m3u.stem
    print(f"\nProcessing playlist: '{playlist_name}' ({m3u.name})")

    tracks = parse_m3u(m3u, music_root=music_root)
    print(f"Extracted {len(tracks)} track entries from M3U.")

    match_results = []
    for t in tqdm(tracks, desc="Matching tracks to uploaded library", unit="tracks"):
        match_results.append(matcher.match_track(t))

    ytm_client = None
    if not dry_run:
        ytm_client = YTMClient(auth_file)

    builder = PlaylistBuilder(ytm_client)

    # Determine report and failure log output paths
    if report_path:
        out_report = Path(report_path)
    else:
        out_report = Path(f"sync_report_{playlist_name}.csv")

    if log_path:
        out_log = Path(log_path)
    else:
        out_log = out_report.parent / f"sync_failures_{playlist_name}.txt"

    builder.export_report(match_results, out_report)
    builder.export_failure_log(match_results, out_log, playlist_name=playlist_name)

    missing_files_count = sum(1 for m in match_results if not getattr(m.track, "file_exists", False))
    found_files_count = len(match_results) - missing_files_count

    summary = builder.sync_playlist(
        playlist_name=playlist_name,
        match_results=match_results,
        dry_run=dry_run,
        allow_duplicates=allow_duplicates
    )
    summary["report_path"] = str(out_report)
    summary["log_path"] = str(out_log)
    summary["missing_files_count"] = missing_files_count
    summary["found_files_count"] = found_files_count
    return summary


def handle_sync(args: argparse.Namespace) -> int:
    try:
        summary = run_sync_single(
            m3u_path=args.m3u,
            cache_db=args.cache_db,
            auth_file=args.auth_file,
            custom_name=args.name,
            dry_run=args.dry_run,
            music_root=args.music_root,
            fuzzy_threshold=args.fuzzy_threshold,
            allow_duplicates=args.allow_duplicates,
            report_path=args.report_path
        )
    except Exception as e:
        print(f"✗ Sync failed: {e}")
        return 1

    print("\n--- Sync Summary ---")
    print(f"Playlist:          {summary['playlist_name']}")
    print(f"Total Tracks:      {summary['total_tracks']}")
    print(f"Matched in YTM:    {summary['matched_tracks']} ({summary['match_rate']}%)")
    print(f"Unmatched in YTM:  {summary['unmatched_tracks']}")
    print(f"Local Audio Files: {summary['found_files_count']} found on disk, {summary['missing_files_count']} missing from disk")
    print(f"Mode:              {'DRY-RUN (no changes made)' if summary['dry_run'] else 'LIVE (created playlists)'}")
    print(f"Audit CSV:         {summary['report_path']}")
    print(f"Diagnostic Log:    {summary['log_path']}")

    if summary["unmatched_tracks"] > 0 or summary["missing_files_count"] > 0:
        print("\n[!] Failures / Warnings detected:")
        if summary["unmatched_tracks"] > 0:
            print(f"  • {summary['unmatched_tracks']} track(s) in M3U could not be found in your YouTube Music uploads.")
        if summary["missing_files_count"] > 0:
            print(f"  • {summary['missing_files_count']} audio file(s) referenced in M3U are missing from your local disk.")
        print(f"  --> Check '{summary['log_path']}' for detailed reasons and track list.")

    if summary["chunks"]:
        print("\nPlaylists:")
        for chunk in summary["chunks"]:
            pl_id = f" [ID: {chunk['playlist_id']}]" if chunk["playlist_id"] else ""
            print(f"  • {chunk['title']}: {chunk['track_count']} tracks{pl_id}")

    return 0


def handle_batch_sync(args: argparse.Namespace) -> int:
    folder = Path(args.folder)
    if not folder.is_dir():
        print(f"✗ Error: '{args.folder}' is not a valid directory.")
        return 1

    m3u_files = find_m3u_files(folder)
    if not m3u_files:
        print(f"No .m3u or .m3u8 files found in '{args.folder}'.")
        return 0

    print(f"Found {len(m3u_files)} playlist files in '{args.folder}'.")
    reports_dir = Path(args.reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)

    cache = UploadsCache(args.cache_db)
    if cache.get_total_count() == 0:
        print(f"✗ Uploads cache '{args.cache_db}' is empty! Please run 'python main.py cache' first.")
        return 1

    shared_matcher = TrackMatcher(cache, fuzzy_threshold=args.fuzzy_threshold)

    success_count = 0
    total_unmatched = 0
    total_missing_files = 0

    for idx, m3u in enumerate(m3u_files, 1):
        print("\n==========================================")
        print(f"Playlist {idx}/{len(m3u_files)}: {m3u.name}")
        print("==========================================")
        report_path = reports_dir / f"sync_report_{m3u.stem}.csv"
        log_path = reports_dir / f"sync_failures_{m3u.stem}.txt"
        try:
            summary = run_sync_single(
                m3u_path=m3u,
                cache_db=args.cache_db,
                auth_file=args.auth_file,
                dry_run=args.dry_run,
                music_root=args.music_root,
                fuzzy_threshold=args.fuzzy_threshold,
                allow_duplicates=args.allow_duplicates,
                report_path=report_path,
                log_path=log_path,
                matcher=shared_matcher
            )
            print(f"Matched {summary['matched_tracks']}/{summary['total_tracks']} ({summary['match_rate']}%)")
            total_unmatched += summary["unmatched_tracks"]
            total_missing_files += summary["missing_files_count"]
            success_count += 1
        except Exception as e:
            print(f"✗ Failed syncing '{m3u.name}': {e}")

    print(f"\n✓ Batch sync completed! Successfully processed {success_count}/{len(m3u_files)} playlists.")
    if total_unmatched > 0 or total_missing_files > 0:
        print(f"[!] Total unmatched across playlists: {total_unmatched}")
        print(f"[!] Total missing audio files: {total_missing_files}")
    print(f"Detailed CSV reports and failure logs saved in: {reports_dir.resolve()}/")
    return 0


def interactive_menu() -> int:
    """
    Interactive text menu for users who launch the application directly (e.g. double-clicking .exe on Windows)
    without specifying command line arguments.
    """
    while True:
        print("\n==============================================")
        print("    YouTube Music Playlist Sync (ytmusicsync) ")
        print("==============================================")
        print("  [1] Connect / Verify Account (auth)")
        print("  [2] Download & Cache Uploaded Songs (cache)")
        print("  [3] Sync a Single Playlist (sync)")
        print("  [4] Sync a Folder of Playlists (batch-sync)")
        print("  [5] Exit")
        print("==============================================")

        try:
            choice = input("Select an option (1-5): ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            return 0

        if choice == "1":
            handle_auth(argparse.Namespace(file=None, verify=False))
        elif choice == "2":
            handle_cache(argparse.Namespace(auth_file=None, cache_db="uploads_cache.sqlite", limit=None))
        elif choice == "3":
            m3u = input("Enter path to .m3u / .m3u8 file: ").strip().strip('"').strip("'")
            if not m3u:
                print("No path entered.")
                continue
            music_root = input("Enter local music folder (e.g. Mega folder) to verify audio files, or press Enter to skip: ").strip().strip('"').strip("'")
            dry_str = input("Run in Dry-Run preview mode first? (Y/n): ").strip().lower()
            dry_run = dry_str != "n"
            handle_sync(argparse.Namespace(
                m3u=m3u,
                cache_db="uploads_cache.sqlite",
                auth_file=None,
                name=None,
                dry_run=dry_run,
                music_root=music_root if music_root else None,
                fuzzy_threshold=88.0,
                allow_duplicates=False,
                report_path=None
            ))
        elif choice == "4":
            folder = input("Enter path to folder containing playlists: ").strip().strip('"').strip("'")
            if not folder:
                print("No folder path entered.")
                continue
            music_root = input("Enter local music folder (e.g. Mega folder) to verify audio files, or press Enter to skip: ").strip().strip('"').strip("'")
            dry_str = input("Run in Dry-Run preview mode first? (Y/n): ").strip().lower()
            dry_run = dry_str != "n"
            handle_batch_sync(argparse.Namespace(
                folder=folder,
                cache_db="uploads_cache.sqlite",
                auth_file=None,
                dry_run=dry_run,
                music_root=music_root if music_root else None,
                fuzzy_threshold=88.0,
                allow_duplicates=False,
                reports_dir="reports"
            ))
        elif choice in ("5", "q", "exit"):
            print("Goodbye!")
            return 0
        else:
            print("Invalid option. Please enter 1, 2, 3, 4, or 5.")

        try:
            input("\nPress Enter to return to menu...")
        except (KeyboardInterrupt, EOFError):
            return 0


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    # When run without arguments (e.g. double-clicked on Windows), launch interactive menu
    if not argv:
        return interactive_menu()

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "auth":
        return handle_auth(args)
    elif args.command == "cache":
        return handle_cache(args)
    elif args.command == "sync":
        return handle_sync(args)
    elif args.command == "batch-sync":
        return handle_batch_sync(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())

