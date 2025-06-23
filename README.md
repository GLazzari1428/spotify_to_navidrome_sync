# Spotify to Navidrome Sync Utility

A powerful and flexible Python script to synchronize your music library between Spotify and Navidrome. This tool can sync your entire "Liked Songs" library (including unstarring songs you've unliked) or manage Navidrome playlists to mirror your Spotify playlists perfectly.

It's designed to be safe and informative, always performing a "dry run" to show you what will change before asking for confirmation.

## Features

-   **Two Sync Modes**:
    1.  **Favorites Sync**: A true two-way sync for your "Liked Songs". It finds songs to star in Navidrome and also finds songs to *unstar* if you've unliked them on Spotify.
    2.  **Playlist Sync**: Mirrors a Spotify playlist in Navidrome. It automatically creates the playlist if it doesn't exist, and on subsequent runs, it deletes and recreates it to ensure a perfect match, adding all available songs and removing ones that are no longer on the Spotify playlist.

-   **Interactive Mode**: Use the `--interactive` flag (in Favorites mode) to review each proposed change (star or unstar) and approve, skip, or permanently ignore the artist on the fly.

-   **Powerful Filtering**:
    -   `--ignore-artist`: Exclude specific artists from the "missing" reports.
    -   `--ignore-genre`: Exclude songs based on genre keywords from the "missing" reports.

-   **Smart Caching**: For "Favorites" sync, it saves your library to a local file. On future runs, it intelligently checks if the cache is up-to-date and skips the lengthy download from Spotify, saving significant time. Use `--force` to override this.

-   **Detailed Reporting**: Generates two CSV reports in the `output` folder for songs that are on Spotify but not found in your Navidrome library:
    -   `missing_songs.csv`: A detailed list of every missing song with its artist, album, and genre.
    -   `missing_albums.csv`: A consolidated list of unique albums containing missing songs, complete with artist, genre, and a direct Spotify URL to help you find them. (Automatically excludes "singles").

-   **Robust Debugging**: Includes `--debug` and `--verbose-debug` flags for easy troubleshooting.

## Setup

1.  **Prerequisites**: Ensure you have Python 3.6+ installed.

2.  **Clone the Repository**:
    ```bash
    git clone <your-repo-url>
    cd <your-repo-folder>
    ```

3.  **Create Venv & Install Dependencies**:
    ```bash
    python -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    ```

4.  **Spotify API Credentials**:
    -   Go to the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard/applications) and create a new app.
    -   Note your **Client ID** and **Client Secret**.
    -   In your app's settings, add `http://localhost:8888/callback` as a Redirect URI.

5.  **Create `.env` File**:
    -   Create a file named `.env` in the root of the project.
    -   Copy the contents of `.env.example` into it and fill in your credentials.

    ```ini
    # .env file
    # Spotify Credentials
    SPOTIPY_CLIENT_ID='YOUR_SPOTIFY_CLIENT_ID'
    SPOTIPY_CLIENT_SECRET='YOUR_SPOTIFY_CLIENT_SECRET'
    SPOTIPY_REDIRECT_URI='http://localhost:8888/callback'
    SPOTIFY_USERNAME='YOUR_SPOTIFY_USERNAME' # Optional, but helps Spotipy

    # Navidrome Credentials
    NAVIDROME_URL='YOUR_NAVIDROME_URL' # e.g., [http://192.168.1.100:4533](http://192.168.1.100:4533)
    NAVIDROME_USER='YOUR_NAVIDROME_USERNAME'
    NAVIDROME_PASS='YOUR_NAVIDROME_PASSWORD'
    ```

## Usage

The script is run from your terminal using `main.py`.

#### **Sync Liked Songs (Default Mode)**

```bash
python main.py
```
### **Sync a Specific Playlist**
This will delete and recreate the playlist in Navidrome to match Spotify.

```bash
python main.py --playlist="[https://open.spotify.com/playlist/your_playlist_id](https://open.spotify.com/playlist/your_playlist_id)"
```
### **Interactive Favorites Sync**
Review each song to be starred or unstarred.

```bash
python main.py --interactive
```
### **Filtering Reports**
Flags can be combined. The following command will sync your favorites but ignore any missing "rock" or "pop" songs from the final CSV reports.

```bash
python main.py --ignore-genre="rock,pop" --ignore-artist="AC/DC"
```
### **Forcing a Full Refresh**
To ignore the local cache and download all data fresh from Spotify:

```bash
python main.py --force
```
## **Help & Debugging**

### **See all available commands**
```bash
python main.py --help
```

### **For troubleshooting connection issues**
```bash
python main.py --debug
```

### **For deep, step-by-step logging**
```bash
python main.py --verbose-debug
```