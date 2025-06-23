import os
import csv
import sys
import json
import argparse
from urllib.parse import urlparse
from dotenv import load_dotenv

import spotipy
from spotipy.oauth2 import SpotifyOAuth
import libsonic

parser = argparse.ArgumentParser(description="Sync Spotify favorites or playlists to Navidrome.")
parser.add_argument("--playlist", type=str, help="The URL of the Spotify playlist to sync.")
parser.add_argument("--interactive", action="store_true", help="Review each change interactively before applying.")
parser.add_argument("--force", action="store_true", help="Force refetch of Spotify data, ignoring the local cache.")
parser.add_argument("--ignore-genre", type=str, help="Comma-separated list of genres to ignore in reports (e.g., 'funk,rock').")
parser.add_argument("--ignore-artist", type=str, help="Comma-separated list of artists to ignore (e.g., 'Daft Punk,AC/DC').")
parser.add_argument("--debug", action="store_true", help="Enable basic debug output.")
parser.add_argument("--verbose-debug", action="store_true", help="Enable verbose debug output.")
args = parser.parse_args()

DEBUG_MODE = args.debug
VERBOSE_DEBUG_MODE = args.verbose_debug
FORCE_REFETCH = args.force
IGNORED_GENRES = [genre.strip().lower() for genre in args.ignore_genre.split(',')] if args.ignore_genre else []
IGNORED_ARTISTS = [artist.strip().lower() for artist in args.ignore_artist.split(',')] if args.ignore_artist else []

def verbose_print(*args, **kwargs):
    if VERBOSE_DEBUG_MODE:
        print(*args, **kwargs)

load_dotenv(override=True)

SPOTIFY_CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")
SPOTIFY_REDIRECT_URI = os.getenv("SPOTIPY_REDIRECT_URI")
SPOTIFY_USERNAME = os.getenv("SPOTIFY_USERNAME")

NAVIDROME_URL = os.getenv("NAVIDROME_URL")
NAVIDROME_USER = os.getenv("NAVIDROME_USER")
NAVIDROME_PASS = os.getenv("NAVIDROME_PASS")

if not os.path.exists('output'):
    os.makedirs('output')

FAVORITES_CACHE_FILE = 'output/spotify_favorites.json'
MISSING_SONGS_CSV = 'output/missing_songs.csv'
MISSING_ALBUMS_CSV = 'output/missing_albums.csv'

def get_spotify_api():
    try:
        auth_manager = SpotifyOAuth(
            scope="user-library-read playlist-read-private",
            client_id=SPOTIFY_CLIENT_ID,
            client_secret=SPOTIFY_CLIENT_SECRET,
            redirect_uri=SPOTIFY_REDIRECT_URI,
            username=SPOTIFY_USERNAME,
            open_browser=True
        )
        return spotipy.Spotify(auth_manager=auth_manager)
    except Exception as e:
        print(f"❌ Could not connect to Spotify. Error: {e}")
        sys.exit(1)

def fetch_spotify_data(sp, playlist_url=None):
    verbose_print("\n--- VERBOSE: Running fetch_spotify_data ---")
    if playlist_url:
        return fetch_playlist_tracks(sp, playlist_url)
    else:
        return fetch_liked_songs(sp)

def fetch_liked_songs(sp):
    print("--- STAGE 1: Fetching Liked Songs from Spotify ---")
    total_spotify_tracks = sp.current_user_saved_tracks(limit=1)['total']
    print(f"✓ Spotify connection successful. Found {total_spotify_tracks} total liked songs.")

    cache_file = FAVORITES_CACHE_FILE
    if not FORCE_REFETCH and os.path.exists(cache_file):
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                local_data = json.load(f)
            if local_data and 'genre' in local_data[0] and len(local_data) == total_spotify_tracks:
                print(f"✓ Local cache '{cache_file}' is up to date. Skipping download.")
                return local_data, "Favorites"
        except (json.JSONDecodeError, IndexError):
            print("-> Local cache file is corrupted or empty. Refetching...")

    print("-> Fetching all liked songs (this may take a while)...")
    all_tracks_raw = []
    offset = 0
    limit = 50
    while True:
        results = sp.current_user_saved_tracks(limit=limit, offset=offset)
        if not results['items']:
            break
        all_tracks_raw.extend(results['items'])
        offset += limit
        print(f"   Fetched {len(all_tracks_raw)}/{total_spotify_tracks} songs so far...", end='\r')
    
    processed_tracks = process_raw_tracks(sp, all_tracks_raw)
    with open(cache_file, 'w', encoding='utf-8') as f:
        json.dump(processed_tracks, f, ensure_ascii=False, indent=4)
    print(f"\n✓ All Spotify favorites have been saved to '{cache_file}'")
    return processed_tracks, "Favorites"

def fetch_playlist_tracks(sp, playlist_url):
    print(f"--- STAGE 1: Fetching Playlist from Spotify ---")
    playlist_id = playlist_url.split('/')[-1].split('?')[0]
    try:
        playlist_info = sp.playlist(playlist_id, fields="name,tracks.total")
        playlist_name = playlist_info['name']
        total_playlist_tracks = playlist_info['tracks']['total']
        print(f"✓ Successfully found playlist '{playlist_name}' with {total_playlist_tracks} tracks.")
    except Exception as e:
        print(f"❌ Could not fetch playlist info. Is the URL correct? Error: {e}")
        sys.exit(1)
        
    print("-> Fetching all playlist tracks (this may take a while)...")
    all_tracks_raw = []
    offset = 0
    while True:
        results = sp.playlist_items(playlist_id, limit=100, offset=offset)
        if not results['items']:
            break
        all_tracks_raw.extend(results['items'])
        offset += 100
        print(f"   Fetched {len(all_tracks_raw)}/{total_playlist_tracks} songs so far...", end='\r')

    processed_tracks = process_raw_tracks(sp, all_tracks_raw)
    return processed_tracks, playlist_name

def process_raw_tracks(sp, all_tracks_raw):
    print(f"\n-> Fetching artist genres...")
    artist_ids = {item['track']['artists'][0]['id'] for item in all_tracks_raw if item.get('track') and item['track']['artists']}
    artist_genres_map = {}
    artist_ids_list = list(artist_ids)
    for i in range(0, len(artist_ids_list), 50):
        batch = artist_ids_list[i:i+50]
        artists_details = sp.artists(batch)
        for artist in artists_details['artists']:
            artist_genres_map[artist['id']] = ", ".join(artist['genres']) if artist['genres'] else ''
    
    print("-> Processing and saving track data...")
    processed_tracks = []
    for item in all_tracks_raw:
        track = item.get('track')
        if track and track.get('album') and track.get('artists'):
            artist_id = track['artists'][0]['id']
            processed_tracks.append({
                'id': track['id'],
                'title': track['name'],
                'artist': track['artists'][0]['name'],
                'album': track['album']['name'],
                'album_type': track['album'].get('album_type', 'album'),
                'album_url': track['album'].get('external_urls', {}).get('spotify', ''),
                'genre': artist_genres_map.get(artist_id, ''),
                'added_at': item.get('added_at', '')
            })
    return processed_tracks

def get_navidrome_connection():
    print("\n-> Connecting to Navidrome server...")
    try:
        parsed_url = urlparse(NAVIDROME_URL)
        connection_params = {'baseUrl': parsed_url.scheme + "://" + parsed_url.hostname,'username': NAVIDROME_USER,'password': NAVIDROME_PASS,'appName': 'SpotifySync','serverPath': "/rest"}
        if parsed_url.port:
            connection_params['port'] = parsed_url.port
        conn = libsonic.Connection(**connection_params)
        conn.ping()
        print("✓ Navidrome connection successful.")
        return conn
    except Exception as e:
        print(f"❌ Could not connect to Navidrome. Please check URL, user, and pass. Error: {e}")
        if DEBUG_MODE or VERBOSE_DEBUG_MODE:
            import traceback
            traceback.print_exc()
        sys.exit(1)

def interactive_session(to_add, to_remove):
    print("\n--- Interactive Session ---")
    approved_add = []
    approved_remove = []

    if to_add:
        print("\n--- Songs to Add/Star ---")
        for song in to_add:
            action = input(f"  + {song['artist']} - {song['title']} | (A)dd, (S)kip, (I)gnore Artist, (Q)uit? ").lower()
            if action == 'a':
                approved_add.append(song)
            elif action == 's':
                continue
            elif action == 'i':
                artist_to_ignore = song['artist'].lower()
                if artist_to_ignore not in IGNORED_ARTISTS:
                    IGNORED_ARTISTS.append(artist_to_ignore)
                print(f"    -> Ignoring '{song['artist']}' for the rest of this session.")
            elif action == 'q':
                break
    
    if to_remove:
        print("\n--- Songs to Remove/Unstar ---")
        for song in to_remove:
            action = input(f"  - {song['artist']} - {song['title']} | (R)emove, (S)kip, (Q)uit? ").lower()
            if action == 'r':
                approved_remove.append(song)
            elif action == 's':
                continue
            elif action == 'q':
                break
    
    return approved_add, approved_remove

def main():
    sp = get_spotify_api()
    spotify_tracks, sync_target_name = fetch_spotify_data(sp, args.playlist)
    conn = get_navidrome_connection()
    
    to_add, to_remove, to_log_as_missing = [], [], []
    
    print("\n-> Starting analysis (Dry Run)...")
    
    spotify_track_map = {f"{track['artist'].lower()}||{track['title'].lower()}": track for track in spotify_tracks}

    if not args.playlist:
        print("-> Comparing Spotify Liked Songs with Navidrome Stars...")
        navidrome_starred = conn.getStarred()['starred'].get('song', [])
        navidrome_track_map = {f"{track['artist'].lower()}||{track['title'].lower()}": track for track in navidrome_starred}
        
        for key, track in spotify_track_map.items():
            if key not in navidrome_track_map:
                to_add.append(track)
        
        for key, track in navidrome_track_map.items():
            if key not in spotify_track_map:
                to_remove.append(track)
        
        to_log_as_missing = to_add

    else:
        print(f"-> Comparing Spotify playlist '{sync_target_name}' with Navidrome library...")
        navidrome_song_ids_to_add = []
        for track in spotify_tracks:
            search_result = conn.search2(query=f"{track['artist']} {track['title']}", songCount=1)['searchResult2']
            if 'song' in search_result:
                navidrome_song_ids_to_add.append(search_result['song'][0]['id'])
            else:
                to_log_as_missing.append(track)
        
        to_add = navidrome_song_ids_to_add
    
    print(f"\n✓ Analysis complete.                 ")
    
    filtered_missing = []
    ignored_genre_counts = {genre: {'songs': 0, 'albums': set()} for genre in IGNORED_GENRES}
    ignored_artist_counts = {artist: {'songs': 0, 'albums': set()} for artist in IGNORED_ARTISTS}

    if IGNORED_GENRES or IGNORED_ARTISTS:
        print(f"\n-> Applying filters to missing songs report...")
        for song in to_log_as_missing:
            is_ignored = False
            if song['artist'].lower() in [a.lower() for a in IGNORED_ARTISTS]:
                ignored_artist_counts.setdefault(song['artist'].lower(), {'songs': 0, 'albums': set()})
                ignored_artist_counts[song['artist'].lower()]['songs'] += 1
                ignored_artist_counts[song['artist'].lower()]['albums'].add((song['artist'], song['album']))
                is_ignored = True
            
            if not is_ignored and IGNORED_GENRES:
                song_genres = [g.strip().lower() for g in song.get('genre', '').split(',')]
                for ignored_genre in IGNORED_GENRES:
                    if any(ignored_genre in s_g for s_g in song_genres):
                        ignored_genre_counts[ignored_genre]['songs'] += 1
                        ignored_genre_counts[ignored_genre]['albums'].add((song['artist'], song['album']))
                        is_ignored = True
                        break
            
            if not is_ignored:
                filtered_missing.append(song)
    else:
        filtered_missing = to_log_as_missing

    approved_add, approved_remove = [], []

    if args.interactive and not args.playlist:
        approved_add, approved_remove = interactive_session(to_add, to_remove)
    else:
        print("\n--- PREVIEW OF CHANGES ---")
        if args.playlist:
             print(f"\n{len(to_add)} songs from Spotify will be synced to Navidrome playlist '{sync_target_name}'.")
             print(f"{len(filtered_missing)} songs from the Spotify playlist were not found in your Navidrome library.")
        else:
            print(f"\n{len(to_add)} songs will be STARRED in Navidrome:")
            for song in to_add[:10]: print(f"  + {song['artist']} - {song['title']}")
            if len(to_add) > 10: print(f"  ... and {len(to_add) - 10} more.")

            print(f"\n{len(to_remove)} songs will be UNSTARRED from Navidrome:")
            for song in to_remove[:10]: print(f"  - {song['artist']} - {song['title']}")
            if len(to_remove) > 10: print(f"  ... and {len(to_remove) - 10} more.")
        
        if not to_add and not to_remove:
            print("\nEverything is up to date!")
            write_missing_reports(filtered_missing)
            return

        confirm = input("\nDo you want to apply these changes? (yes/no): ").lower()
        if confirm in ['y', 'yes']:
            approved_add, approved_remove = to_add, to_remove
        else:
            print("Operation cancelled. Reports for missing songs are still being generated.")
            write_missing_reports(filtered_missing)
            sys.exit()

    print("\n-> Applying changes...")
    if args.playlist:
        playlists = conn.getPlaylists()['playlists']['playlist']
        target_playlist = next((p for p in playlists if p['name'] == sync_target_name), None)
        if target_playlist:
            print(f"-> Deleting existing Navidrome playlist '{sync_target_name}'...")
            conn.deletePlaylist(pid=target_playlist['id'])
        
        print(f"-> Creating new playlist '{sync_target_name}' with {len(to_add)} songs...")
        conn.createPlaylist(name=sync_target_name, songIds=to_add)
        print("✓ Playlist sync complete.")

    else: 
        if approved_add:
            add_ids = [s['id'] for s in approved_add]
            conn.star(sids=add_ids)
            print(f"✓ Starred {len(add_ids)} songs.")
        if approved_remove:
            remove_ids = [s['id'] for s in approved_remove]
            conn.unstar(sids=remove_ids)
            print(f"✓ Unstarred {len(remove_ids)} songs.")

    write_missing_reports(filtered_missing)

    print("\n--- Sync Complete! ---")
    if not args.playlist:
        if approved_add:
            print(f"Songs starred: {len(approved_add)}")
        if approved_remove:
            print(f"Songs unstarred: {len(approved_remove)}")
        
    if IGNORED_GENRES:
        print("\n--- Ignored Genre Summary ---")
        for genre, counts in ignored_genre_counts.items():
            if counts['songs'] > 0:
                print(f"- '{genre}': Ignored {counts['songs']} songs across {len(counts['albums'])} unique albums.")
    
    if IGNORED_ARTISTS:
        print("\n--- Ignored Artist Summary ---")
        for artist, counts in ignored_artist_counts.items():
            if counts['songs'] > 0:
                print(f"- '{artist.title()}': Ignored {counts['songs']} songs across {len(counts['albums'])} unique albums.")

def write_missing_reports(missing_songs_list):
    verbose_print("\n--- VERBOSE: Running write_missing_reports ---")
    if not missing_songs_list:
        open(MISSING_SONGS_CSV, 'w').close()
        open(MISSING_ALBUMS_CSV, 'w').close()
        return
        
    with open(MISSING_SONGS_CSV, 'w', newline='', encoding='utf-8') as csv_file:
        csv_writer = csv.writer(csv_file)
        csv_writer.writerow(['Title', 'Artist', 'Album', 'Genre', 'Date Added to Spotify'])
        for song in missing_songs_list:
             csv_writer.writerow([song['title'], song['artist'], song['album'], song.get('genre', ''), song['added_at']])
    print(f"✓ Missing songs report saved to '{MISSING_SONGS_CSV}'")

    missing_albums = {}
    for song in missing_songs_list:
        album_key = (song['artist'], song['album'])
        if album_key not in missing_albums:
            missing_albums[album_key] = (song.get('album_url', ''), song.get('album_type', ''), song.get('genre', ''))
            if VERBOSE_DEBUG_MODE and len(missing_albums) < 4:
                verbose_print(f"--- VERBOSE: Added to missing albums -> {album_key}: {missing_albums[album_key]}")

    with open(MISSING_ALBUMS_CSV, 'w', newline='', encoding='utf-8') as csv_file:
        csv_writer = csv.writer(csv_file)
        csv_writer.writerow(['Artist', 'Album', 'Genre', 'Spotify URL'])
        for (artist, album), (url, album_type, genre) in sorted(missing_albums.items()):
            if album_type != 'single':
                csv_writer.writerow([artist, album, genre, url])
    print(f"✓ Missing albums report saved to '{MISSING_ALBUMS_CSV}'")


if __name__ == '__main__':
    main()
