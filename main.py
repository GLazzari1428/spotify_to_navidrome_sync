import os
import csv
import sys
from datetime import datetime
from dotenv import load_dotenv

import spotipy
from spotipy.oauth2 import SpotifyOAuth
import libsonic

# --- CONFIGURATION ---
# Load credentials from .env file
load_dotenv()

# Spotify API details from .env
SPOTIFY_CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")
SPOTIFY_REDIRECT_URI = os.getenv("SPOTIPY_REDIRECT_URI")
SPOTIFY_USERNAME = os.getenv("SPOTIFY_USERNAME")

# Navidrome API details from .env
NAVIDROME_URL = os.getenv("NAVIDROME_URL")
NAVIDROME_USER = os.getenv("NAVIDROME_USER")
NAVIDROME_PASS = os.getenv("NAVIDROME_PASS")

# Name for the output file for songs not found in Navidrome
MISSING_SONGS_CSV = 'missing_in_navidrome.csv'

# --- SCRIPT ---

def get_spotify_favorites():
    """
    Authenticates with Spotify and fetches all 'Liked Songs' from the user's library.
    Returns a list of dictionaries, each containing song details.
    """
    print("-> Connecting to Spotify...")
    try:
        auth_manager = SpotifyOAuth(
            scope="user-library-read",
            client_id=SPOTIFY_CLIENT_ID,
            client_secret=SPOTIFY_CLIENT_SECRET,
            redirect_uri=SPOTIFY_REDIRECT_URI,
            username=SPOTIFY_USERNAME,
            open_browser=True # Will try to open a browser for you to log in the first time
        )
        sp = spotipy.Spotify(auth_manager=auth_manager)
        print("✓ Spotify connection successful.")
    except Exception as e:
        print(f"❌ Could not connect to Spotify. Error: {e}")
        sys.exit(1)

    print("-> Fetching all liked songs from Spotify (this may take a while)...")
    all_favorites = []
    offset = 0
    limit = 50 # Max limit per request

    while True:
        results = sp.current_user_saved_tracks(limit=limit, offset=offset)
        if not results['items']:
            break # No more songs left

        for item in results['items']:
            track = item['track']
            if track: # Ensure track data exists
                all_favorites.append({
                    'title': track['name'],
                    'artist': track['artists'][0]['name'], # Primary artist
                    'album': track['album']['name'],
                    'added_at': item['added_at']
                })
        
        offset += limit
        print(f"   Fetched {len(all_favorites)} songs so far...")

    # By default, Spotify returns newest first. We reverse it to process oldest first.
    # This way, the favoriting order in Navidrome will match the order you added them.
    all_favorites.reverse()
    print(f"✓ Found a total of {len(all_favorites)} liked songs on Spotify.")
    return all_favorites


def connect_to_navidrome():
    """
    Connects to the Navidrome server using the libsonic library.
    Returns a connection object.
    """
    print("-> Connecting to Navidrome server...")
    try:
        # libsonic requires the URL without http/https, port, and user/pass separately
        base_url = NAVIDROME_URL.split('//')[1].split(':')[0]
        port = NAVIDROME_URL.split(':')[-1] if ':' in NAVIDROME_URL.split('//')[1] else '80'
        if 'https' in NAVIDROME_URL:
            port = '443'
        
        conn = libsonic.Connection(
            baseUrl=base_url,
            port=port,
            user=NAVIDROME_USER,
            password=NAVIDROME_PASS,
            appName='SpotifySync',
            ssl=True if 'https' in NAVIDROME_URL else False
        )
        # Check connection with a simple ping
        conn.ping()
        print("✓ Navidrome connection successful.")
        return conn
    except Exception as e:
        print(f"❌ Could not connect to Navidrome. Please check URL, user, and pass. Error: {e}")
        sys.exit(1)

def main():
    """
    Main function to orchestrate the sync process.
    """
    # Get all songs from Spotify
    spotify_songs = get_spotify_favorites()
    if not spotify_songs:
        print("No songs to process. Exiting.")
        return

    # Connect to Navidrome
    nd_conn = connect_to_navidrome()

    # Prepare CSV file for missing songs
    print(f"-> Preparing CSV for missing songs: '{MISSING_SONGS_CSV}'")
    csv_file = open(MISSING_SONGS_CSV, 'w', newline='', encoding='utf-8')
    csv_writer = csv.writer(csv_file)
    csv_writer.writerow(['Title', 'Artist', 'Album', 'Date Added to Spotify'])
    
    missing_count = 0
    favorited_count = 0
    skipped_count = 0

    print("\n--- Starting Sync Process ---\n")

    for idx, song in enumerate(spotify_songs):
        print(f"[{idx+1}/{len(spotify_songs)}] Processing: {song['artist']} - {song['title']}")

        try:
            # Search for the song in Navidrome
            search_query = f"{song['artist']} {song['title']}"
            search_result = nd_conn.search3(query=search_query, songCount=5)

            if 'song' in search_result['searchResult3']:
                # Found at least one match, let's check it
                navidrome_song = search_result['searchResult3']['song'][0] # Take the top result

                # Check if it's already favorited (starred)
                if navidrome_song.get('starred'):
                    print("   - Status: Found and already favorited. Skipping.")
                    skipped_count += 1
                else:
                    # Song exists but is not favorited, so let's favorite it
                    print("   - Status: Found, not favorited. Favoriting now...")
                    nd_conn.star(songId=navidrome_song['id'])
                    print("   ✓ Successfully favorited in Navidrome.")
                    favorited_count += 1
            else:
                # Song was not found in Navidrome library
                print("   - Status: Song not found in Navidrome. Logging to CSV.")
                csv_writer.writerow([song['title'], song['artist'], song['album'], song['added_at']])
                missing_count += 1

        except Exception as e:
            print(f"   - ❌ An error occurred while processing this song: {e}")

    # --- Final Summary ---
    csv_file.close()
    print("\n--- Sync Complete! ---")
    print(f"New songs favorited in Navidrome: {favorited_count}")
    print(f"Songs already favorited (skipped): {skipped_count}")
    print(f"Songs not found in Navidrome library: {missing_count}")
    if missing_count > 0:
        print(f"✓ Details for missing songs have been saved to '{MISSING_SONGS_CSV}'")

if __name__ == '__main__':
    main()
