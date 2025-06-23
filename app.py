import os
import csv
import sys
import json
import argparse
from urllib.parse import urlparse
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, jsonify, Response
import io

import spotipy
from spotipy.oauth2 import SpotifyOAuth
import libsonic

load_dotenv(override=True)

app = Flask(__name__)

# --- Configuration ---
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
ALBUM_ART_CACHE = 'output/album_art_cache.json'
SPOTIFY_CACHE_PATH = '.spotipy_cache_web'

# --- Helper Functions ---

def get_spotify_api():
    try:
        auth_manager = SpotifyOAuth(scope="user-library-read playlist-read-private", client_id=SPOTIFY_CLIENT_ID, client_secret=SPOTIFY_CLIENT_SECRET, redirect_uri=SPOTIFY_REDIRECT_URI, username=SPOTIFY_USERNAME, cache_path=SPOTIFY_CACHE_PATH, open_browser=True)
        return spotipy.Spotify(auth_manager=auth_manager)
    except Exception as e:
        print(f"❌ Could not connect to Spotify. Error: {e}")
        return None

def get_navidrome_connection():
    try:
        parsed_url = urlparse(NAVIDROME_URL)
        connection_params = {'baseUrl': parsed_url.scheme + "://" + parsed_url.hostname, 'username': NAVIDROME_USER, 'password': NAVIDROME_PASS, 'appName': 'SpotifySyncWeb', 'serverPath': "/rest"}
        if parsed_url.port:
            connection_params['port'] = parsed_url.port
        conn = libsonic.Connection(**connection_params)
        conn.ping()
        return conn
    except Exception as e:
        print(f"❌ Could not connect to Navidrome. Error: {e}")
        return None

def process_raw_tracks(sp, all_tracks_raw):
    artist_ids = {item['track']['artists'][0]['id'] for item in all_tracks_raw if item.get('track') and item['track']['artists']}
    artist_genres_map = {}
    artist_ids_list = list(artist_ids)
    for i in range(0, len(artist_ids_list), 50):
        batch = artist_ids_list[i:i + 50]
        artists_details = sp.artists(batch)
        for artist in artists_details['artists']:
            artist_genres_map[artist['id']] = ", ".join(artist['genres']) if artist['genres'] else ''
    
    processed_tracks = []
    for item in all_tracks_raw:
        track = item.get('track')
        if track and track.get('album') and track.get('artists'):
            processed_tracks.append({'id': track['id'],'title': track['name'],'artist': track['artists'][0]['name'],'album': track['album']['name'],'album_type': track['album'].get('album_type', 'album'),'album_url': track['album'].get('external_urls', {}).get('spotify', ''),'genre': artist_genres_map.get(track['artists'][0]['id'], ''),'added_at': item.get('added_at', '')})
    return processed_tracks

def write_missing_reports(missing_songs_list, ignored_artists=[], ignored_genres=[]):
    filtered_missing = []
    if ignored_genres or ignored_artists:
        for song in missing_songs_list:
            is_ignored = False
            if song['artist'].lower() in [a.lower() for a in ignored_artists]:
                is_ignored = True
            
            if not is_ignored and ignored_genres:
                song_genres = [g.strip().lower() for g in song.get('genre', '').split(',')]
                for ignored_genre in ignored_genres:
                    if any(ignored_genre in s_g for s_g in song_genres):
                        is_ignored = True
                        break
            
            if not is_ignored:
                filtered_missing.append(song)
    else:
        filtered_missing = missing_songs_list

    with open(MISSING_SONGS_CSV, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Title', 'Artist', 'Album', 'Genre', 'Date Added to Spotify'])
        for song in filtered_missing:
            writer.writerow([song['title'], song['artist'], song['album'], song.get('genre', ''), song['added_at']])
            
    missing_albums = {}
    for song in filtered_missing:
        album_key = (song['artist'], song['album'])
        if album_key not in missing_albums:
            missing_albums[album_key] = (song.get('album_url', ''), song.get('album_type', ''), song.get('genre', ''))
    
    with open(MISSING_ALBUMS_CSV, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Artist', 'Album', 'Genre', 'Spotify URL'])
        for (artist, album), (url, album_type, genre) in sorted(missing_albums.items()):
            if album_type != 'single':
                writer.writerow([artist, album, genre, url])

def cache_album_art(sp):
    print("-> Caching album art...")
    if not os.path.exists(MISSING_ALBUMS_CSV):
        return

    art_cache = {}
    if os.path.exists(ALBUM_ART_CACHE):
        with open(ALBUM_ART_CACHE, 'r') as f:
            art_cache = json.load(f)

    with open(MISSING_ALBUMS_CSV, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        album_urls_to_fetch = [row['Spotify URL'] for row in reader if row.get('Spotify URL') and row.get('Spotify URL') not in art_cache]
    
    if not album_urls_to_fetch:
        print("✓ Album art cache is up to date.")
        return

    print(f"-> Found {len(album_urls_to_fetch)} new albums to fetch art for.")
    album_ids = [url.split('/')[-1].split('?')[0] for url in album_urls_to_fetch]

    for i in range(0, len(album_ids), 20):
        batch_ids = album_ids[i:i+20]
        try:
            album_details_list = sp.albums(batch_ids)
            for album_details in album_details_list['albums']:
                if album_details and album_details['images']:
                    spotify_url = album_details['external_urls']['spotify']
                    art_cache[spotify_url] = album_details['images'][0]['url']
        except Exception as e:
            print(f"Warning: Failed to fetch a batch of album arts. Error: {e}")

    with open(ALBUM_ART_CACHE, 'w') as f:
        json.dump(art_cache, f, indent=2)
    print("✓ Album art cache has been updated.")


# --- Flask Routes ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/run-sync', methods=['POST'])
def run_sync():
    print("--- SYNC PROCESS STARTED ---")
    sync_type = request.form.get('sync_type')
    playlist_url = request.form.get('playlist_url')
    force_refetch = request.form.get('force_refetch') == 'true'
    ignored_artists = [a.strip() for a in request.form.get('ignore_artist', '').split(',') if a]
    ignored_genres = [g.strip() for g in request.form.get('ignore_genre', '').split(',') if g]

    sp = get_spotify_api()
    conn = get_navidrome_connection()
    if not sp or not conn:
        return "Failed to connect to Spotify or Navidrome. Check console.", 500

    # --- Fetch Spotify Data ---
    spotify_tracks, sync_target_name = [], "Favorites"
    if sync_type == 'playlist' and playlist_url:
        playlist_id = playlist_url.split('/')[-1].split('?')[0]
        playlist_info = sp.playlist(playlist_id, fields="name,tracks.total")
        sync_target_name = playlist_info['name']
        total_playlist_tracks = playlist_info['tracks']['total']
        all_tracks_raw = []
        offset = 0
        while True:
            results = sp.playlist_items(playlist_id, limit=100, offset=offset)
            if not results['items']: break
            all_tracks_raw.extend(results['items'])
            offset += 100
        spotify_tracks = process_raw_tracks(sp, all_tracks_raw)
    else:
        total_spotify_tracks = sp.current_user_saved_tracks(limit=1)['total']
        cache_file = FAVORITES_CACHE_FILE
        if not force_refetch and os.path.exists(cache_file):
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    local_data = json.load(f)
                if local_data and len(local_data) == total_spotify_tracks:
                    spotify_tracks = local_data
            except (json.JSONDecodeError, IndexError):
                pass
        
        if not spotify_tracks:
            all_tracks_raw = []
            offset = 0
            while True:
                results = sp.current_user_saved_tracks(limit=50, offset=offset)
                if not results['items']: break
                all_tracks_raw.extend(results['items'])
                offset += 50
            spotify_tracks = process_raw_tracks(sp, all_tracks_raw)
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(spotify_tracks, f, ensure_ascii=False, indent=4)

    # --- Analysis & Execution Logic ---
    to_log_as_missing = []
    if sync_type == 'playlist':
        navidrome_song_ids_to_add = []
        for track in spotify_tracks:
            search_result = conn.search2(query=f"{track['artist']} {track['title']}", songCount=1)['searchResult2']
            if 'song' in search_result:
                navidrome_song_ids_to_add.append(search_result['song'][0]['id'])
            else:
                to_log_as_missing.append(track)
        
        playlists = conn.getPlaylists()['playlists']['playlist']
        target_playlist = next((p for p in playlists if p['name'] == sync_target_name), None)
        if target_playlist:
            conn.deletePlaylist(pid=target_playlist['id'])
        conn.createPlaylist(name=sync_target_name, songIds=navidrome_song_ids_to_add)
    else: # Favorites Sync
        to_add, to_remove = [], []
        spotify_track_map = {f"{t['artist'].lower()}||{t['title'].lower()}": t for t in spotify_tracks}
        navidrome_starred = conn.getStarred()['starred'].get('song', [])
        navidrome_track_map = {f"{t['artist'].lower()}||{t['title'].lower()}": t for t in navidrome_starred}
        
        for key, track in spotify_track_map.items():
            if key not in navidrome_track_map:
                to_add.append(track)
        
        for key, track in navidrome_track_map.items():
            if key not in spotify_track_map:
                to_remove.append(track)

        if to_add: conn.star(sids=[s['id'] for s in to_add])
        if to_remove: conn.unstar(sids=[s['id'] for s in to_remove])
        to_log_as_missing = to_add

    # --- Write Reports and Cache Art ---
    write_missing_reports(to_log_as_missing, ignored_artists, ignored_genres)
    cache_album_art(sp)

    print("--- SYNC PROCESS COMPLETED ---")
    return redirect(url_for('report'))

@app.route('/report')
def report():
    return render_template('report.html')

@app.route('/api/albums')
def get_albums_api():
    if not os.path.exists(MISSING_ALBUMS_CSV): return jsonify([])

    art_cache = {}
    if os.path.exists(ALBUM_ART_CACHE):
        with open(ALBUM_ART_CACHE, 'r') as f:
            art_cache = json.load(f)
    
    albums_data = []
    with open(MISSING_ALBUMS_CSV, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            spotify_url = row.get('Spotify URL')
            image_url = art_cache.get(spotify_url)
            if spotify_url and image_url:
                albums_data.append({
                    "artist": row["Artist"],
                    "album": row["Album"],
                    "genre": row["Genre"],
                    "url": spotify_url,
                    "image_url": image_url
                })
    return jsonify(albums_data)

@app.route('/api/delete-albums', methods=['POST'])
def delete_albums_api():
    data = request.json
    urls_to_delete = data.get('album_urls', [])
    
    rows = []
    if os.path.exists(MISSING_ALBUMS_CSV):
        with open(MISSING_ALBUMS_CSV, 'r', newline='', encoding='utf-8') as f:
            reader = csv.reader(f)
            rows = list(reader)

        if rows:
            header = rows[0]
            updated_rows = [header] + [row for row in rows[1:] if len(row) > 3 and row[3] not in urls_to_delete]
            
            with open(MISSING_ALBUMS_CSV, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerows(updated_rows)

    return jsonify({"success": True, "message": f"Deleted {len(rows) - len(updated_rows)} albums."})

@app.route('/export-selected', methods=['POST'])
def export_selected_api():
    data = request.json
    urls_to_export = data.get('album_urls', [])
    
    header = ['Artist', 'Album', 'Genre', 'Spotify URL']
    rows_to_export = [header]
    if os.path.exists(MISSING_ALBUMS_CSV):
        with open(MISSING_ALBUMS_CSV, 'r', newline='', encoding='utf-8') as f:
            reader = csv.reader(f)
            next(reader) 
            for row in reader:
                if len(row) > 3 and row[3] in urls_to_export:
                    rows_to_export.append(row)

    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerows(rows_to_export)
    output = Response(si.getvalue(), mimetype='text/csv')
    output.headers["Content-Disposition"] = "attachment; filename=missing_albums_selected.csv"
    return output


if __name__ == '__main__':
    app.run(debug=True, port=5001)
