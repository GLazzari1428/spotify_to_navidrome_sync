import os
import csv
import sys
import json
from urllib.parse import urlparse
from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from libresonic import Connection as LibresonicConnection

load_dotenv()

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
MISSING_SONGS_CSV = 'output/missing_in_navidrome.csv'

def fetch_and_save_spotify_favorites():
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
        print("✓ Spotify connection successful.")
    except Exception as e:
        print(f"❌ Could not connect to Spotify. Error: {e}")
        sys.exit(1)

    print("-> Fetching all liked songs (this may take a while)...")
    all_favorites = []
    offset = 0
    limit = 50

    while True:
        results = sp.current_user_saved_tracks(limit=limit, offset=offset)
        if not results['items']:
            break

        for item in results['items']:
            track = item['track']
            if track:
                all_favorites.append({
                    'title': track['name'],
                    'artist': track['artists'][0]['name'],
                    'album': track['album']['name'],
                    'added_at': item['added_at']
                })
        
        offset += limit
        print(f"   Fetched {len(all_favorites)} songs so far...")

    all_favorites.reverse()
    print(f"✓ Found a total of {len(all_favorites)} liked songs.")

    with open(SPOTIFY_DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(all_favorites, f, ensure_ascii=False, indent=4)
    
    print(f"✓ All Spotify favorites have been saved to '{SPOTIFY_DATA_FILE}'")
    return all_favorites

def run_sync_with_preview():
    print("\n--- STAGE 2: Analyzing and Syncing with Navidrome ---")
    
    try:
        with open(SPOTIFY_DATA_FILE, 'r', encoding='utf-8') as f:
            spotify_songs = json.load(f)
        print(f"✓ Loaded {len(spotify_songs)} songs from '{SPOTIFY_DATA_FILE}'")
    except FileNotFoundError:
        print(f"❌ Data file not found. Please run Stage 1 first.")
        return

    print("-> Connecting to Navidrome server...")
    try:
        parsed_url = urlparse(NAVIDROME_URL)
        
        conn = LibresonicConnection(
            baseUrl=parsed_url.hostname,
            username=NAVIDROME_USER,
            password=NAVIDROME_PASS,
            port=parsed_url.port,
            appName='SpotifySync',
            secure=(parsed_url.scheme == 'https')
        )
        conn.ping()
        print("✓ Navidrome connection successful.")
    except Exception as e:
        print(f"❌ Could not connect to Navidrome. Please check URL, user, and pass. Error: {e}")
        sys.exit(1)

    print("\n-> Starting analysis (Dry Run)...")
    to_favorite = []
    to_skip = []
    to_log_as_missing = []

    for idx, song in enumerate(spotify_songs):
        print(f"   Analyzing [{idx+1}/{len(spotify_songs)}]: {song['artist']} - {song['title']}", end='\r')
        
        search_query = f"{song['artist']} {song['title']}"
        search_result = conn.search3(query=search_query, songCount=1, songOffset=0)

        if 'song' in search_result['searchResult3']:
            navidrome_song = search_result['searchResult3']['song'][0]
            song_info = {'id': navidrome_song['id'], 'title': song['title'], 'artist': song['artist']}
            
            if navidrome_song.get('starred'):
                to_skip.append(song_info)
            else:
                to_favorite.append(song_info)
        else:
            to_log_as_missing.append(song)
    
    print("\n✓ Analysis complete.                 ")

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
    
    if not to_favorite:
        print("\nNo new songs to favorite. All actions are complete.")
        write_missing_csv(to_log_as_missing)
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
            conn.star(s_id=song['id'])
            print(f"  ✓ Favorited: {song['artist']} - {song['title']}")
            favorited_count += 1
        except Exception as e:
            print(f"  ❌ Failed to favorite {song['artist']} - {song['title']}. Error: {e}")
    
    write_missing_csv(to_log_as_missing)

    print("\n--- Sync Complete! ---")
    print(f"Successfully favorited: {favorited_count} songs.")
    print(f"Skipped (already favorited): {len(to_skip)} songs.")
    if to_log_as_missing:
        print(f"Missing from library: {len(to_log_as_missing)} songs. See '{MISSING_SONGS_CSV}' for details.")

def write_missing_csv(missing_songs_list):
    if not missing_songs_list:
        return
        
    with open(MISSING_SONGS_CSV, 'w', newline='', encoding='utf-8') as csv_file:
        csv_writer = csv.writer(csv_file)
        csv_writer.writerow(['Title', 'Artist', 'Album', 'Date Added to Spotify'])
        for song in missing_songs_list:
             csv_writer.writerow([song['title'], song['artist'], song['album'], song['added_at']])
    print(f"✓ Missing songs report saved to '{MISSING_SONGS_CSV}'")

if __name__ == '__main__':
    fetch_and_save_spotify_favorites()
    run_sync_with_preview()
