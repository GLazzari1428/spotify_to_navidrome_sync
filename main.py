import os
import csv
import sys
import json
from urllib.parse import urlparse
from dotenv import load_dotenv

import spotipy
from spotipy.oauth2 import SpotifyOAuth
import libsonic

# --- Debug Flags ---
DEBUG_MODE = "--debug" in sys.argv
VERBOSE_DEBUG_MODE = "--verbose-debug" in sys.argv
FORCE_REFETCH = "--force" in sys.argv

def verbose_print(*args, **kwargs):
    if VERBOSE_DEBUG_MODE:
        print(*args, **kwargs)

# --- Configuration ---
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

SPOTIFY_DATA_FILE = 'output/spotify_favorites.json'
MISSING_SONGS_CSV = 'output/missing_songs.csv'
MISSING_ALBUMS_CSV = 'output/missing_albums.csv'

def fetch_and_save_spotify_favorites():
    verbose_print("\n--- VERBOSE: Running fetch_and_save_spotify_favorites ---")
    print("--- STAGE 1: Fetching Songs from Spotify ---")
    print("-> Connecting to Spotify...")
    try:
        auth_manager = SpotifyOAuth(
            scope="user-library-read",
            client_id=SPOTIFY_CLIENT_ID,
            client_secret=SPOTIFY_CLIENT_SECRET,
            redirect_uri=SPOTIFY_REDIRECT_URI,
            username=SPOTIFY_USERNAME,
            open_browser=True
        )
        sp = spotipy.Spotify(auth_manager=auth_manager)
        
        total_spotify_tracks = sp.current_user_saved_tracks(limit=1)['total']
        print(f"✓ Spotify connection successful. Found {total_spotify_tracks} total liked songs.")

        if FORCE_REFETCH:
            print("-> --force flag detected. Forcing a full refetch from Spotify.")
        elif os.path.exists(SPOTIFY_DATA_FILE):
            try:
                with open(SPOTIFY_DATA_FILE, 'r', encoding='utf-8') as f:
                    local_data = json.load(f)
                
                if local_data and 'genre' in local_data[0] and 'album_url' in local_data[0] and len(local_data) == total_spotify_tracks:
                    print(f"✓ Local cache '{SPOTIFY_DATA_FILE}' is up to date and has the correct format. Skipping download.")
                    return local_data
                else:
                    print(f"-> Local cache is outdated or in an old format. Refetching to get new data (Genres/URLs)...")
            except (json.JSONDecodeError, IndexError):
                print("-> Local cache file is corrupted or empty. Refetching...")

    except Exception as e:
        print(f"❌ Could not connect to Spotify. Error: {e}")
        sys.exit(1)

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
    
    if VERBOSE_DEBUG_MODE and all_tracks_raw:
        verbose_print(f"\n--- VERBOSE: First raw track item:\n{json.dumps(all_tracks_raw[0], indent=2)}")

    print(f"\n-> Fetching artist genres...")
    artist_ids = {item['track']['artists'][0]['id'] for item in all_tracks_raw if item.get('track') and item['track']['artists']}
    artist_genres_map = {}
    artist_ids_list = list(artist_ids)
    for i in range(0, len(artist_ids_list), 50):
        batch = artist_ids_list[i:i+50]
        artists_details = sp.artists(batch)
        for artist in artists_details['artists']:
            artist_genres_map[artist['id']] = ", ".join(artist['genres']) if artist['genres'] else ''
    
    if VERBOSE_DEBUG_MODE and artist_genres_map:
         verbose_print(f"--- VERBOSE: Sample of genre map:\n{dict(list(artist_genres_map.items())[:3])}")

    print("-> Processing and saving track data...")
    all_favorites = []
    for item in all_tracks_raw:
        track = item['track']
        if track and track.get('album') and track.get('artists'):
            artist_id = track['artists'][0]['id']
            all_favorites.append({
                'title': track['name'],
                'artist': track['artists'][0]['name'],
                'album': track['album']['name'],
                'album_type': track['album'].get('album_type', 'album'),
                'album_url': track['album'].get('external_urls', {}).get('spotify', ''),
                'genre': artist_genres_map.get(artist_id, ''),
                'added_at': item['added_at']
            })

    if VERBOSE_DEBUG_MODE and all_favorites:
        verbose_print(f"--- VERBOSE: First processed favorite object:\n{json.dumps(all_favorites[-1], indent=2)}")

    all_favorites.reverse()
    with open(SPOTIFY_DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(all_favorites, f, ensure_ascii=False, indent=4)
    
    print(f"✓ All Spotify favorites have been saved to '{SPOTIFY_DATA_FILE}'")
    return all_favorites

def run_sync_with_preview():
    verbose_print("\n--- VERBOSE: Running run_sync_with_preview ---")
    print("\n--- STAGE 2: Analyzing and Syncing with Navidrome ---")
    
    spotify_songs = fetch_and_save_spotify_favorites()
    if not spotify_songs:
        print("No songs to process. Exiting.")
        return

    print("\n-> Connecting to Navidrome server...")
    try:
        parsed_url = urlparse(NAVIDROME_URL)
        
        connection_params = {
            'baseUrl': parsed_url.scheme + "://" + parsed_url.hostname,
            'username': NAVIDROME_USER,
            'password': NAVIDROME_PASS,
            'appName': 'SpotifySync',
            'serverPath': "/rest"
        }
        if parsed_url.port:
            connection_params['port'] = parsed_url.port
        
        if DEBUG_MODE:
            print("--- DEBUG: Connection Parameters ---")
            print(f"   - baseUrl: {connection_params.get('baseUrl')}")
            print(f"   - port: {connection_params.get('port')}")
            print(f"   - username: {connection_params.get('username')}")
            print("------------------------------------")
            print("--> Attempting to create connection object...")

        conn = libsonic.Connection(**connection_params)
        
        if DEBUG_MODE:
            print("✓ Connection object created.")
            print("--> Attempting to ping server...")

        conn.ping()
        print("✓ Navidrome connection successful.")

    except Exception as e:
        print(f"❌ Could not connect to Navidrome. Please check URL, user, and pass. Error: {e}")
        if DEBUG_MODE or VERBOSE_DEBUG_MODE:
            import traceback
            traceback.print_exc()
        sys.exit(1)

    print("\n-> Starting analysis (Dry Run)...")
    to_favorite = []
    to_skip = []
    to_log_as_missing = []

    for idx, song in enumerate(spotify_songs):
        print(f"   Analyzing [{idx+1}/{len(spotify_songs)}]: {song['artist']} - {song['title']}", end='\r')
        sys.stdout.flush()
        
        search_query = f"{song['artist']} {song['title']}"
        search_result = conn.search2(query=search_query, songCount=1, songOffset=0)

        if VERBOSE_DEBUG_MODE and idx < 3:
            verbose_print(f"\n--- VERBOSE: Search Query: {search_query}")
            verbose_print(f"--- VERBOSE: Search Result:\n{json.dumps(search_result, indent=2)}")

        if 'song' in search_result['searchResult2']:
            navidrome_song = search_result['searchResult2']['song'][0]
            song_info = {'id': navidrome_song['id'], 'title': song['title'], 'artist': song['artist']}
            
            if navidrome_song.get('starred'):
                to_skip.append(song_info)
            else:
                to_favorite.append(song_info)
        else:
            to_log_as_missing.append(song)
    
    print(f"\n✓ Analysis complete.                 ")

    print("\n--- PREVIEW OF CHANGES ---")
    print(f"\n{len(to_favorite)} songs will be NEWLY FAVORITED in Navidrome:")
    for song in to_favorite[:10]:
        print(f"  + {song['artist']} - {song['title']}")
    if len(to_favorite) > 10:
        print(f"  ... and {len(to_favorite) - 10} more.")

    print(f"\n{len(to_skip)} songs are ALREADY FAVORITED and will be skipped.")
    
    print(f"\n{len(to_log_as_missing)} songs are MISSING from your Navidrome library:")
    for song in to_log_as_missing[:10]:
        print(f"  - {song['artist']} - {song['title']}")
    if len(to_log_as_missing) > 10:
        print(f"  ... and {len(to_log_as_missing) - 10} more.")
    
    print("\n--------------------------")
    
    if not to_favorite and not to_log_as_missing:
        print("\nEverything is up to date!")
        return
        
    if not to_favorite:
        print("\nNo new songs to favorite. Writing missing songs report.")
        write_missing_reports(to_log_as_missing)
        return

    try:
        confirm = input("Do you want to apply these changes? (yes/no): ")
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")
        sys.exit()

    if confirm.lower() not in ['y', 'yes']:
        print("Operation cancelled. No changes have been made to Navidrome.")
        return

    print("\n-> Applying changes...")
    favorited_count = 0
    for song in to_favorite:
        try:
            conn.star(sids=[song['id']])
            print(f"  ✓ Favorited: {song['artist']} - {song['title']}")
            favorited_count += 1
        except Exception as e:
            print(f"  ❌ Failed to favorite {song['artist']} - {song['title']}. Error: {e}")
    
    write_missing_reports(to_log_as_missing)

    print("\n--- Sync Complete! ---")
    print(f"Successfully favorited: {favorited_count} songs.")
    print(f"Skipped (already favorited): {len(to_skip)} songs.")
    if to_log_as_missing:
        print(f"Missing from library: {len(to_log_as_missing)} songs. See reports in 'output' folder for details.")

def write_missing_reports(missing_songs_list):
    verbose_print("\n--- VERBOSE: Running write_missing_reports ---")
    if not missing_songs_list:
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
    run_sync_with_preview()
