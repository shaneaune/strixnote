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

> [!NOTE]
> **Experimental GPU Branch**
>
> This branch contains the current development version of NVIDIA GPU acceleration for StrixNote. It is intended for testing and hardware compatibility validation.
>
> GPU installation is currently supported only through the matching Proxmox Helper Script on the `feature/gpu-acceleration` branch.
>
> For the stable CPU-only release, use the `main` branch.

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
* Dedicated VM

Recommended:

* 6 to 8 CPU cores
* 12 to 16 GB RAM
* 40 GB free disk space
* Dedicated VM

Operating systems tested:

* Debian 12

Software:

* Docker
* Docker Compose

Performance notes:

- Transcription is GPU-intensive
- The Whisper model uses approximately 3 GB RAM when loaded
- A 4-core system is sufficient for basic use

Memory behavior:

- After the first transcription, RAM usage may appear high (for example 6–8 GB on an 8 GB system)
- This is expected behavior
- The Whisper model remains loaded in memory for faster processing
- Linux also uses available RAM for filesystem cache
- Tools like Proxmox may report this cached memory as "used"

---

## Experimental NVIDIA GPU Installation

> **Experimental Feature**
>
> NVIDIA GPU acceleration is currently under active development and hardware compatibility testing. At this time, GPU installation is supported **only** through the StrixNote Proxmox Helper Script.

### Current Support

The GPU installation has been validated on:

* NVIDIA Quadro P2000
* Debian 12
* CUDA acceleration enabled

Additional NVIDIA GPU models will be added as they are tested.

| GPU | Operating System | Status |
|------|------------------|--------|
| NVIDIA Quadro P2000 | Debian 12 | ✅ Fully validated |

### Requirements

Before using the Proxmox Helper Script for a GPU installation:

* Proxmox VE host with IOMMU enabled
* An NVIDIA GPU with CUDA support
* The GPU must not already be assigned to another virtual machine

> **Important**
>
> The GPU **must not** already be assigned to another virtual machine. Proxmox allows a PCI device to be attached to only one VM at a time. If the selected GPU is already attached to another VM, VM creation will fail.

### Installation

GPU acceleration is currently available from the experimental GPU branch.

Run the Proxmox Helper Script:

```bash
bash <(curl -s https://raw.githubusercontent.com/shaneaune/strixnote-proxmox-helper/feature/gpu-acceleration/proxmox-create-strixnote-vm.sh)
```

The helper script will automatically download and install the experimental GPU-enabled version of StrixNote.

Helper repository:

https://github.com/shaneaune/strixnote-proxmox-helper/tree/feature/gpu-acceleration

### Installation Notes

During a GPU installation the helper script will:

* Create a new Debian 12 virtual machine
* Configure the VM for GPU passthrough
* Install the NVIDIA driver
* Automatically reboot the VM when required
* Reconnect after the reboot and resume the installation
* Install StrixNote and configure GPU acceleration
* install Docker and required packages
* configure permissions automatically
* create the configuration file (.env)
* create data directories
* start containers
* wait for Meilisearch
* apply search schema
* preload the transcription model

The automatic reboot during installation is expected and requires no user intervention.

Installation time depends on your hardware and internet connection. A typical installation takes 15–30 minutes. The installer may appear to pause several times while downloading packages, installing drivers, or preloading the transcription model. This is expected.


### First run:

* Upload an audio file
* Wait for processing
* Open the transcript in Browse

The model is preloaded, so there is no first-run delay. GPU accelerated processing should be about 8X faster then CPU. 

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

* CPU: Approximately real-time on a modern 4-core processor.
* GPU-accelerated processing is approximately 8× faster than CPU processing on the currently supported hardware.

---

Viewing transcripts:

* Click a file to load the player
* Click Transcript to view text
* Click a segment to jump to that point

---

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

If you want to change the port after setup you can do so by editing the `.env` file located in the main directory.

STRIXNOTE_WEB_PORT=8080

For example, to use port 9090:

STRIXNOTE_WEB_PORT=9090

After changing the port, restart the containers by running these commands from inside the StrixNote directory:

```bash
./scripts/dc.sh down
./scripts/dc.sh up -d
```

## Configuration (.env)

StrixNote uses a `.env` file for configuration.

Some options are available for adjusting behavior such as:
- Whisper model selection
- language settings
- processing parameters

These options are currently not fully tested. If you experiment with them, feedback is appreciated.
Changing models or processing settings may significantly affect performance and resource usage.

Important:
Most changes to the `.env` file require rebuilding the containers to take effect.

To apply changes, run from inside the StrixNote directory:

```bash
./scripts/dc.sh down
./scripts/dc.sh up -d --build
```

---

## Troubleshooting

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

---

## Updating

To update an existing StrixNote installation:

```bash
cd strixnote
./upgrade.sh
```

Before upgrading, it is recommended to back up the data directory.

The data directory contains uploaded audio, transcripts, settings, search data, and migration status.

---

## Project Status

StrixNote is a working, self-hosted transcription system with a complete install flow and core feature set.

CPU functionality is stable. This branch contains the current experimental NVIDIA GPU implementation, which is undergoing hardware compatibility testing before being merged into the main branch.

The application has been tested on a clean Debian 12 environment with a reproducible install process. Core functionality including transcription, search, playback, and editing is stable.

The current focus is on polish, usability, and preparing for broader use.

---

## Roadmap

### Current Focus

* Validate additional NVIDIA GPU models
* Refine the GPU installation experience
* Improve installation documentation
* Continue UI polish and usability improvements
* Improve error handling and diagnostics

---

### Short Term

* Expand GPU compatibility testing
* Bulk actions (delete and manage multiple files)
* Transcript export improvements
* Improve processing and indexing status visibility

---

### Mid Term

* Multiple Whisper model selection (performance vs. accuracy)
* Index health visibility in Settings
* Reindex progress indicator for large rebuilds
* Improved file management tools

---

### Long Term

* Merge the GPU branch into the main branch
* AMD GPU support (if feasible)
* Optional authentication
* API access for automation and integrations

---

## Notes

* The system is functional and suitable for daily use
* Some features are still being refined for usability and performance
* Update instructions will be added once versioned releases are introduced

---

## Expected Behavior

The following behaviors are normal during operation:


### Automatic Reboot During Installation

During a GPU installation, the virtual machine will automatically reboot after the NVIDIA driver is installed.
The Proxmox Helper Script will wait for the VM to come back online and automatically resume the installation.

---

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

```text
/processed/_failed
/processed/_broken
```

* These folders are created automatically during installation

If you made it this far good for you. Have a great day!
