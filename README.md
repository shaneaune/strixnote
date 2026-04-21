``` id="2v18cf"
+--------------------------------------------------------------------------------+
|      /\___/\        ____  _        _      _   _       _                        |
|     /  o o  \      / ___|| |_ _ __(_)_  _| \ | | ___ | |_ ___                  |
|    |   \^/   |     \___ \| __| '__| \ \/ /  \| |/ _ \| __/ _ \                 |
|    |  (___)  |      ___) | |_| |  | |>  <| |\  | (_) | ||  __/                 |
|    |  /   \  |     |____/ \__|_|  |_/_/\_\_| \_|\___/ \__\___|                 |
|    |_/|_|_|\_|                                                                 |
+--------------------------------------------------------------------------------+
```
Self-hosted audio transcription with search, playback, and editing.
Fully local, no cloud required.

## Overview

StrixNote is a self-hosted audio transcription system that converts audio files into searchable, time-stamped text.

It supports single recordings or multiple files that can be merged and transcribed into structured segments. Transcripts are indexed for fast search at both the file and segment level and are integrated with audio playback for precise navigation.

Key capabilities:

* Transcription of audio files into timestamped segments
* Full-text and segment-level search
* Jump-to-audio playback from search results
* Configurable transcript segmentation and formatting (punctuation and time-based splitting)
* Transcript editing and formatting controls
* Clip extraction and export
* Fully self-hosted (no cloud dependencies after setup)

Designed for:

* Professionals transcribing meetings
* Students reviewing lectures
* Anyone managing recorded audio or voice notes

---

## Privacy and Network Behavior

StrixNote operates entirely on your local system after installation.

* All transcription is done locally
* Audio files and transcripts never leave your system
* Search indexing is handled locally (Meilisearch)
* No external APIs are used during normal operation

Internet access is only required during installation to:

* download container images
* download the transcription model

---

## Requirements

Minimum:

* 4 CPU cores
* 8 GB RAM
* 20 GB free disk space
* 64-bit Linux

Recommended:

* 6 to 8 CPU cores
* 12 to 16 GB RAM
* SSD storage
* Dedicated system or VM

Operating systems tested:

* Debian 12

Other Linux distributions may work but are not officially tested.

Software:

* Docker
* Docker Compose

Performance notes:

- Transcription is CPU-intensive
- The Whisper model uses approximately 3 GB RAM when loaded
- A 4-core system is sufficient for basic use
- Additional CPU cores improve transcription speed significantly

Memory behavior:

- After the first transcription, RAM usage may appear high (for example 6–8 GB on an 8 GB system)
- This is expected behavior
- The Whisper model remains loaded in memory for faster processing
- Linux also uses available RAM for filesystem cache
- Tools like Proxmox may report this cached memory as "used"

To verify actual available memory, run:

free -h

If the "available" value is high, the system is operating normally.

---

## Installation (Debian 12)

Tested on a clean Debian 12 VM.

Recommended VM:

* 8 vCPU
* 8 GB RAM minimum (12 GB recommended)
* 40 GB disk

---

### Step 1 - Install Debian

Use a minimal install with:

* SSH server
* standard system utilities

Do not install a desktop environment.

---

### Step 2 - Switch to root

Run the following:

```bash
su -
```

---

### Step 3 - Install dependencies

Run the following:

```bash
apt update
apt upgrade -y
apt install -y sudo docker.io docker-compose git
systemctl enable docker
systemctl start docker
usermod -aG sudo user
usermod -aG docker user
```

Replace "user" with your username if different.

IMPORTANT:
You must log out and reconnect after this step for Docker permissions to take effect.

---

### Step 4 - Verify setup

Verify:
```bash
sudo whoami
groups
```
You should see:

* root
* docker listed in groups

---

### Step 5 - Install StrixNote

Run the following:

```bash
git clone https://github.com/shaneaune/strixnote.git
cd strixnote
./install.sh
```

This process may take several minutes on first run.

The installer will:

* create data directories
* start containers
* wait for Meilisearch
* apply search schema
* preload the transcription model

---

### Step 6 - Open the interface

Open in your browser:

```text
http://<server-ip>:8080
```
If you specified another port number in the setup use that port.
---

First run:

* Upload an audio file
* Wait for processing
* Open the transcript in Browse

The model is preloaded, so there is no first-run delay.

---

## Usage

Uploading:

* Open the web interface
* Click Upload
* Select files
* Optionally merge files

Test audio:
https://commons.wikimedia.org/wiki/Category:Audio_files_of_speeches

---

Processing:

* Starts automatically after upload
* Progress is shown in the UI

Typical speed:

* About 1 minute of audio per minute of processing on a 4-core system

---

Viewing transcripts:

* Click a file to load the player
* Click Transcript to view text
* Click a segment to jump to that point

Segment tools:

* Copy
* Edit (available in Whisper Default mode)
* Clip
* Bookmark

---

Searching:

* Go to the Search tab
* Enter a query

Search types:

* Files
* Segments
* File name

Filters:

* Relevance or first occurrence
* Upload date or recorded date
* Custom date range

---

Editing:

* Switch to "Whisper Default" mode in settings
* Edit segments
* Save changes
* Switch back to "Post-processed" mode in settings

Edits update search immediately.

---

Display modes:

* Whisper Default (raw output)
* Post-processed (formatted segments)

---

Clips:

* Select segments
* Export audio clip
* Optionally re-import for processing

---

Organization:

* Pin files
* Bookmark files or segments
* Sort by date

---

Maintenance:

If search results become inconsistent:

* Go to Settings
* Run Reindex

---

## Data Storage

All data is stored locally at:

/opt/strixnote/data

Directory layout:

Directory layout:

```text
incoming/           - new files waiting to be processed
processed/          - completed audio and transcripts
processed/_failed/  - files that failed during processing
processed/_broken/  - files that could not be processed (invalid or corrupt)
status/             - processing state files
config/             - application settings
meili/              - search index database
models/             - Whisper model files
```

Notes:

* No data leaves the system
* Ensure enough disk space is available
* Uploads are blocked if disk space is too low
* Files are moved to _failed or _broken if they cannot be processed
* These folders are created automatically during installation

---

## Optional Network Share

You can expose the incoming folder as a network share:

```text
\\your-server\incoming
```

Files placed here are processed automatically.
Refresh the Browse tab to see new files.

## Port Configuration

By default, StrixNote runs on port 8080.

You can change the port by editing the `.env` file before starting:

STRIXNOTE_WEB_PORT=8080

For example, to use port 9090:

STRIXNOTE_WEB_PORT=9090

After changing the port, restart the containers:

```bash
docker compose down
docker compose up -d
```

## Troubleshooting

### Install script fails with Docker permission error

Error example:

```text
PermissionError: [Errno 13] Permission denied
docker.errors.DockerException: Error while fetching server API version
```

Cause:
Your user is not in the `docker` group.

Fix:

1. Switch to root:

```bash
su -
```

2. Run the following:
```bash
usermod -aG docker your_username
```

3. Log out completely and reconnect (or reconnect SSH)

4. Verify:
```bash
groups
```
You should see `docker` in the list.

---

### install.sh stops immediately with a docker group error

Cause:
Same as above — Docker permissions are not active yet.

Fix:
Follow the steps above and log out/in before running install again.

---

### Meilisearch did not become ready

Error example:

ERROR: Meilisearch did not become ready.

Cause:

* Docker service not running
* container startup failure
* system resources too low

Fix:

Check container status:
```bash
./scripts/dc.sh ps
```
Check logs:
```bash
./scripts/dc.sh logs
```
Ensure Docker is running:
```bash
sudo systemctl status docker
```
---

### Install appears to hang during model preload

Message:

```text
Preloading Whisper model...
Downloading/loading model...
```

Cause:
This is normal on first install.

The system is:

* downloading the model
* loading it into memory

Fix:
Wait. This can take several minutes depending on system speed.

---

### Model preload warning about HF Hub

Message:

Warning: You are sending unauthenticated requests to the HF Hub.

Cause:
No HuggingFace token is set.

Fix:
This is normal and does not affect functionality.

StrixNote downloads the transcription model during installation and does not require an account or API key.

Advanced users can optionally provide a Hugging Face token to improve download speed and avoid rate limits.

---

### Upload works but nothing appears in Browse

Cause:
Search index (Meilisearch schema) was not applied.

Fix:

Run the following:
```bash
./scripts/dc.sh exec -T upload_api python - <<EOF
from app import ensure_meili_schema
ensure_meili_schema()
EOF
```
Then refresh the page.

---

### Search returns errors (400 / 502)

Cause:
Missing Meilisearch filterable or sortable attributes.

Fix:
Same as above — reapply schema.

---

### High memory usage after install

Observation:
System may appear to use most available RAM.

Cause:

* Whisper model stays loaded (~3 GB)
* Linux uses RAM for caching

Check actual availability:
```bash
free -h
```
If "available" memory is still high, system is operating normally.

---

### Docker commands fail inside scripts

Cause:
User does not have permission to access Docker socket.

Fix:
Ensure user is in docker group and session has been restarted.

---

### No sudo command available

Cause:
Minimal Debian install does not include sudo.

Fix:

Switch to root:
```bash
su -
```
Install sudo:
```bash
apt install -y sudo
```
---

### Install commands appear to do nothing after su -

Cause:
Commands were pasted together with `su -`.

Fix:
Run commands separately:

1. su -
2. enter password
3. then run commands

---

### Disk space errors on upload

Cause:
System does not have enough free disk space.

Fix:
Free up disk space or expand storage.

---

### Still not working

Collect diagnostic info:
```bash
./scripts/dc.sh ps
./scripts/dc.sh logs
```
Include this output when asking for help.


## Updating

Update instructions will be added once versioned releases are available.


## Project Status

StrixNote is a working, self-hosted transcription system with a complete install flow and core feature set.

The application has been tested on a clean Debian 12 environment with a reproducible install process. Core functionality including transcription, search, playback, and editing is stable.

The current focus is on polish, usability, and preparing for broader use.

---

## Roadmap

### Current Focus (Stabilization)

* Improve UI clarity and user feedback
* Better visibility of processing and indexing status
* Refine install experience and documentation
* Develop Proxmox helper script
* Improve error handling and logging

---

### Short Term

* Bulk actions (delete, manage multiple files)
* Transcript export improvements

---

### Mid Term

* Index health visibility in Settings
* Reindex progress indicator for large rebuilds
* Improved file management tools

---

### Longer Term

* Optional GPU acceleration
* Multiple model selection (performance vs accuracy)
* Optional authentication layer
* API access for automation and integrations

---

## Notes

* The system is functional and suitable for daily use
* Some features are still being refined for usability and performance
* Update instructions will be added once versioned releases are introduced

---

## Expected Behavior

The following behaviors are normal during operation:

### High memory usage

* After the first transcription, RAM usage may appear high
* The Whisper model remains loaded in memory for faster processing
* Linux also uses available RAM for caching
* System monitors (such as Proxmox) may report this as high memory usage

To verify actual available memory:
```bash
free -h
```
If the "available" value is high, the system is operating normally.

---

### Model preload delay

* During installation, the model preload step may take several minutes
* This includes downloading and initializing the model
* The process may appear idle near completion

This is expected and only occurs once.

---

### Processing time

* Transcription runs automatically after upload
* Processing time depends on CPU performance
* A typical 4-core system processes audio at approximately real-time speed

---

### Container startup time

* After starting the system, services may take a few seconds to become ready
* The installer waits for required services before continuing

---

### Failed or invalid files

* Files that cannot be processed are moved to:

/processed/_failed
/processed/_broken

* These folders are created automatically during installation

If you made it this far good for you. Have a great day!
