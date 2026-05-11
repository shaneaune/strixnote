# StrixNote User Guide

## Introduction

StrixNote is a self-hosted audio transcription platform designed for local transcription, search, and transcript management.

Audio files uploaded to StrixNote are automatically processed, transcribed using Whisper, indexed for search, and made available through the web interface.

Typical workflow:

1. Upload audio files
2. Wait for transcription and indexing to complete
3. Open and review transcripts
4. Search across all indexed content

StrixNote is designed to run entirely on your own system without relying on external cloud transcription services.

---

## Main Interface Overview

The StrixNote interface is organized into several main sections accessible from the navigation sidebar.

### Upload

Used to upload audio files for transcription and processing.

### Browse

Displays all uploaded files, transcripts, and processing status information.

### Search

Allows full-text searching across all indexed transcripts.

### Settings

Contains system configuration options including transcription settings, search indexing options, and maintenance tools.

---

## Processing Workflow

After an audio file is uploaded, StrixNote processes it in several stages:

1. Audio validation
2. Audio preprocessing
3. Transcription
4. Transcript segmentation
5. Search indexing

Once processing is complete, the transcript becomes searchable and available in the Browse and Search tabs.

Processing time depends on:
- Audio length
- Whisper model size
- CPU performance
- Number of queued files

---

## Uploading Audio Files

Audio files can be uploaded from the top of the page using the file selection button.

Multiple files can be uploaded at the same time and are automatically added to the processing queue.

### Supported Audio Formats

StrixNote supports the following audio formats:

- WAV
- MP3
- M4A
- AAC
- FLAC
- OGG
- WMA
- MP4
- WEBM

### Selecting Files

Click the Choose Files button to browse and select audio files from your system then click upload.

### Merge Files

The Merge toggle allows multiple uploaded audio files to be combined into a single transcript.

When enabled, all selected files are processed together as one continuous transcription job.

### Upload Progress

A progress indicator is displayed while files are uploading.

Large audio files may take additional time depending on file size and system performance.

---

## Browse Tab

Once processing is complete, transcripts become visible in the Browse tab.

Each transcript entry displays:

- File name
- Processing date
- Audio length
- File size

The transcript list can be sorted by:

- Newest first
- Oldest first

### Opening a Transcript

Clicking anywhere on a transcript row opens the transcript viewer.

The transcript viewer includes:

- Audio player
- Transcript subtitles
- Interactive timeline
- Transcript segment tools

### Browse Page Record Limit

The number of transcripts displayed in the Browse tab can be configured in the Settings tab.

Default value: 20 records

### Upload Progress and Processing

During upload and processing, StrixNote displays progress percentages and status messages for each file.

This provides real-time feedback during transcription and indexing operations.

### Failed Processing Jobs

If a transcription job fails, StrixNote automatically retries processing.

Files that continue to fail after retry attempts are moved to the Broken or Failed folders for troubleshooting and review.

### Pinning Transcripts

The Pin toggle allows important transcripts to remain permanently at the top of the Browse list regardless of sorting order.

### Transcript Button

Clicking the Transcript button opens the full transcript view and enables transcript tools and segment controls.

### Bookmarking Files

Entire transcripts can be bookmarked using the Bookmark toggle.

Bookmarked transcripts appear in the Bookmarks tab for quick access.

### Audio Download

Clicking the Audio button downloads the original uploaded audio file.

### Delete

The Delete button permanently removes the transcript, transcript data, bookmarks, and associated audio file from StrixNote.

---

## Transcript View

The Transcript view displays the full processed transcript for the selected audio file.

By default, transcripts are displayed with timestamps enabled.

### Download Transcript

The Download button exports the entire transcript as a text file.

### No Timestamps Toggle

Enabling the No Timestamps toggle removes timestamps from the exported transcript text file.

This is useful when exporting clean readable text without timing information.

---

## Transcript Segment Tools

Each transcript segment includes several action buttons located at the end of the transcript line.

### Copy Segment

The Clipboard button copies the selected transcript segment to the system clipboard.

### Edit Segment

The Pencil button allows transcript segments to be edited.

Transcript editing is only available when Whisper Default mode is enabled in the Settings tab. Switch to Whisper Default, make the edit then switch back to Post-Processed. 

### Clip Tools

The Scissors button opens the clip tools menu.

Single or multiple transcript segments can be selected for clipping operations.

Available clip options include:

- Download audio clip
- Send To StrixNote reprocesses selected clips into a new transcript

When multiple segments are selected and reprocessed, StrixNote combines the selected audio clips into a new transcription job and it will show up in the file list when done.

### Bookmark Segment

The Star button bookmarks the selected transcript segment.

Bookmarked transcript segments appear in the Bookmarks tab for quick reference.

---

## Search

The Search tab allows transcripts and transcript segments to be searched using keywords, phrases, file names, and date filters.

Search results can be filtered and sorted using several search modes and options.

---

## Search Types

### Segments

Searches inside transcript segment text.

Results display matching transcript segments along with their timestamps and source transcript.

Segment results include quick action buttons for:

- Bookmarking segments
- Opening the transcript

Opening a transcript from segment search results automatically opens the transcript viewer at the selected segment location.

### Files

Searches complete transcript files and displays matching transcript entries.

File search results use the same layout and controls as the Browse tab.

### File Name

Searches transcript file names only.

Results are displayed using the same layout and controls as the Browse tab and Files search results.

---

## Search Sorting

### Most Relevant

Sorts search results by relevance to the entered search terms.

This is the recommended default for most searches.

### First Occurrence

Sorts results based on the earliest matching occurrence within transcripts.

Useful when locating the first mention of a keyword or phrase.

---

## Date Filters

Search results can be filtered by upload date or recorded date.

### Any Date

Disables date filtering and searches all indexed transcripts.

### Uploaded Date

Filters results based on the date the file was uploaded to StrixNote.

### Recorded Date

Filters results using the original recorded date metadata when available.

---

## Date Range Selection

### Start Date

Defines the beginning of the search date range.

### End Date

Defines the end of the search date range.

---

## Quick Date Presets

Quick filter buttons are available for commonly used date ranges.

### Today

Limits results to the current day.

### Last 7 Days

Limits results to transcripts from the previous 7 days.

### Last 30 Days

Limits results to transcripts from the previous 30 days.

---

## Search Results

Search results update using the currently selected search mode, sorting option, and date filters.

Large transcript collections may take slightly longer to search depending on system performance and index size.

Search accuracy and matching behavior can be improved using custom synonyms configured in the Settings tab.

---

## Bookmarks

The Bookmarks tab provides quick access to bookmarked transcripts and bookmarked transcript segments.

Bookmarks can be created from either the Browse tab or directly from transcript segments inside the transcript viewer.

---

## Bookmarked Files

Bookmarked files appear at the top of the Bookmarks tab.

Selecting a bookmarked file opens the full transcript viewer.

Bookmarked files remain bookmarked until the bookmark is manually removed or the transcript is deleted.

---

## Bookmarked Segments

Bookmarked transcript segments display:

- Transcript segment text
- Timestamp
- Source transcript

Selecting a bookmarked segment opens the transcript viewer directly at the selected segment.

---

## Managing Bookmarks

Bookmarks can be removed at any time using the Star bookmark button.

Deleting a transcript automatically removes all associated bookmarks.

---

## Settings

The Settings tab contains transcription, transcript formatting, search, and system maintenance options.

Settings are grouped by when changes take effect.

Be sure to click Save after making any changes.

---

## Transcription Defaults

These settings affect new files uploaded after saving.

Existing transcripts and processed files are not modified.

### Language

Sets the default transcription language.

Leaving this field blank enables automatic language detection.

Example:

```text
en
```

### Beam Size

Controls transcription accuracy and processing time.

Higher values may improve transcription accuracy on difficult audio but increase processing time.

Lower values process faster with slightly reduced accuracy.

Recommended default: 5

Range:

```text
1-10
```

### VAD Mode

Controls how silence and pauses are handled before transcription.

Balanced mode is recommended for most audio sources.

Different modes may improve results depending on recording quality and background noise.

---

## Transcript Post-Processing

These settings control how transcript segments are split and displayed after transcription.

### Transcript Segmentation

Controls how transcript lines are divided for display, searching, and clip selection.

Post-processed mode is recommended for most use cases.

### Sentence Break Punctuation

Defines which punctuation characters create sentence breaks.

Default:

```text
.?!
```

### Ignore Abbreviations

Defines abbreviations that should not trigger sentence splitting.

Periods inside these abbreviations are ignored during transcript segmentation.

Example:

```text
Mr.,Mrs.,Ms.,Dr.,Prof.,Sr.,Jr.,St.,vs.,etc.
```

### Max Segment Length

Controls the maximum transcript segment length in seconds.

Longer values create larger transcript blocks while smaller values create shorter more granular segments.

Default:

```text
30 seconds
```

---

## Pause-Aware Splitting

Controls transcript splitting behavior based on pauses in speech.

### Pause Threshold

Defines how long silence must last before a new transcript segment is created.

Lower values create more transcript segments.

Higher values create fewer larger transcript segments.

Recommended range:

```text
0.6-1.2 seconds
```

Default:

```text
0.8 seconds
```

---

## Search and Browsing

These settings apply immediately after saving.

Existing transcript content is not modified.

### Browse Limit

Controls how many results are displayed per page in the Browse and Search tabs.

Range:

```text
5-100
```

Default:

```text
20
```

### Synonyms

Allows custom search synonyms to improve search matching.

Synonyms must be entered as a JSON object.

Example:

```text
{
  "tv": ["television"],
  "gpu": ["graphics card", "video card"]
}
```

---

## Save and Reset

### Save

Applies and stores all current settings.

### Reset to Defaults

Restores all settings to their default values.

---

## Status and Stats

Displays search index health, processing statistics, and maintenance information.

### MeiliSearch Status

Shows the current MeiliSearch connection status.

Example:

```text
MeiliSearch: OK
```

### Processed Audio Files

Displays the total number of processed audio files.

### Files Index

Displays the total number of indexed transcript files.

### Segments Index

Displays the total number of indexed transcript segments.

### Files Index Match

Verifies that transcript files and search indexes are synchronized correctly.

### Last Reindex

Displays the date and time of the most recent search index rebuild.

### App Version

Displays the currently installed StrixNote version.

### Search Index Version

Displays the current search index schema version.

### Last Migration

Displays the result of the most recent transcript migration check performed during application upgrades or database changes.

This is primarily used during version updates when StrixNote checks and updates existing transcript data structures if required.

---

## Re-Index

Rebuilds the search indexes for all transcripts.

Re-indexing is only recommended if search results appear incorrect, incomplete, or missing.

---

# Advanced Configuration

The advanced configuration section covers optional settings and internal behavior intended for advanced users and self-hosted deployments.

Most users will not need to modify these settings.

Changes to advanced settings may require restarting StrixNote containers or services.

---

## Environment Configuration (.env)

StrixNote uses a `.env` file to control system behavior, Whisper configuration, storage locations, and service settings.

After modifying the `.env` file, restart the affected containers for changes to take effect.

Example:

```bash
docker compose restart transcribe_worker
```

Some configuration changes may require a full container restart.

> [!WARNING]
> Most advanced Whisper configuration options in the `.env` file have not been extensively tested across all hardware and deployment configurations.
>
> Alternative models, compute types, and device settings are provided for advanced users but are used at your own risk.
>
> Some combinations may result in:
>
> - Increased RAM or VRAM usage
> - Slower transcription performance
> - Container instability
> - Model loading failures
> - Unsupported hardware errors
>
> If issues occur, revert to the default recommended settings and restart the transcription worker.

---

## Web Port

Controls which port the StrixNote web interface uses.

Example:

```env
STRIXNOTE_WEB_PORT=8080
```

The web interface would then be accessible at:

```text
http://your-server-ip:8080
```

---

## Data Storage Directory

Controls where StrixNote stores audio files, transcripts, indexes, clips, and application data.

Example:

```env
DATA_DIR=./data
```

For VM or dedicated storage deployments, a mounted storage path may be preferred.

Example:

```env
DATA_DIR=/storage/transcribe
```

---

## MeiliSearch Configuration

StrixNote uses MeiliSearch for transcript indexing and full-text search.

The MeiliSearch master key secures access to the search service.

Example:

```env
MEILI_MASTER_KEY=your-key-here
```

Changing the key may require restarting containers.

---

## Whisper Model Selection

The Whisper model controls transcription accuracy and processing speed.

Example:

```env
WHISPER_MODEL=medium.en
```

### Common English Models

- base.en
- small.en
- medium.en

### Larger Models

- large-v3
- large-v3-turbo

Larger models improve accuracy but require significantly more RAM and processing time.

---

## Multilingual Models

Multilingual models support transcription in multiple languages.

Examples:

```env
WHISPER_MODEL=small
WHISPER_MODEL=medium
WHISPER_MODEL=large-v3
```

Models without the `.en` suffix support multilingual transcription.

---

## Whisper Device Selection

Controls which hardware device is used for transcription.

### CPU Mode

Works on all supported systems.

Example:

```env
WHISPER_DEVICE=cpu
```

### NVIDIA CUDA GPU

Requires NVIDIA GPU support, CUDA drivers, and container GPU passthrough configuration.

Example:

```env
WHISPER_DEVICE=cuda
```

Changing device type requires restarting the transcription worker.

---

## Compute Type Configuration

Controls transcription precision and performance.

### CPU Recommended Settings

```env
WHISPER_COMPUTE=int8
```

Fastest and most efficient option for CPU transcription.

Additional CPU options:

```env
WHISPER_COMPUTE=int8_float32
WHISPER_COMPUTE=float32
```

### CUDA GPU Recommended Settings

```env
WHISPER_COMPUTE=float16
```

Recommended for NVIDIA GPU acceleration.

Additional GPU options:

```env
WHISPER_COMPUTE=int8_float16
WHISPER_COMPUTE=float32
```

---

## Restarting After Whisper Changes

After changing Whisper model, device, or compute settings, restart the transcription worker.

Example:

```bash
docker compose restart transcribe_worker
```

---

## Failed and Broken Files

Files that repeatedly fail transcription are automatically moved to the failed or broken folders.

Common causes include:

- Corrupted audio files
- Unsupported codecs
- Incomplete uploads
- FFmpeg processing failures

These files can be manually reviewed or reprocessed later.

---

## Search Indexing

StrixNote uses MeiliSearch to index:

- Transcript text
- Segment text
- File metadata
- Timestamps
- Search synonyms

If search results appear incorrect or incomplete, use the Re-Index button in the Settings tab.

---

## Backup Recommendations

Important data to back up includes:

- Uploaded audio files
- Transcript databases
- Search indexes
- Configuration files
- `.env` file

Regular backups are recommended for production systems.

---

## Logs and Troubleshooting

Container logs can be viewed using:

```bash
docker compose logs -f
```

Logs may help diagnose:

- Failed transcription jobs
- Search indexing problems
- FFmpeg issues
- Container startup failures