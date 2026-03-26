# DOCX Thinkific Batch Spec

## Purpose

`process_docx_thinkific.py` parses a DOCX workbook that contains:

- Thinkific lesson links
- lesson descriptions
- additional links below lessons
- embedded images
- occasional tables

The script creates one local project per lesson and stores all related material together.

## Input

Primary input:

- a `.docx` file, for example:
  `/Users/romansergeev/Downloads/YTCG.docx`

Supported content patterns:

- lesson title paragraphs like `Phase_...mp4`
- Thinkific lesson links stored as Word `HYPERLINK` field codes
- extra links to Google Docs, YouTube, Milanote, product pages, etc.
- embedded DOCX media
- Word tables

## Lesson Boundary Rule

A new lesson starts when a paragraph:

- ends with `.mp4`
- and contains a Thinkific lesson hyperlink

All following paragraphs/tables/images belong to that lesson until the next lesson-start paragraph.

## Per-Lesson Outputs

Inside each lesson project folder:

- main lesson video
- downloader metadata
- transcription outputs
- screenshots
- `document_notes.md`
- `document_manifest.json`
- `doc_images/`
- `linked_resources/`
- `extra_links_manifest.json`

## Extra Link Strategy

The script tries resources in this order:

1. Thinkific lesson-like links -> resolve and download media directly
2. Google Docs / Sheets -> try export URLs first
3. YouTube -> use `yt-dlp` if available, otherwise save a local reference file
4. Generic HTTP pages/files -> save response body locally

Important:

- links pointing to the same lesson page are skipped as duplicate references
- this is a best-effort downloader, not a crawler with site-specific auth flows for every domain

## DOCX Parsing Notes

The source workbook does not store Thinkific links as normal relationship hyperlinks.
Instead, they are embedded as Word field codes:

- `w:instrText` with `HYPERLINK "..."`

So the parser must read field-code text, not only standard relationship hyperlinks.

Embedded images are read from:

- `word/media/*`

## CLI Contract

Main options:

- `docx_path`
- `--output-dir`
- `--cookie-header`
- `--cookie-file`
- `--engine`
- `--download-only`
- `--no-transcribe`
- `--no-screenshots`
- `--no-extra-links`
- `-n / --speakers`
- `-m / --model`
- `--language`
- `--transcribe-python`
- `--transcribe-script`
- `--scene-threshold`
- `--scene-max-width`
- `--limit`
- `--dry-run`

## Dry Run

`--dry-run` must:

- parse the DOCX
- detect lesson blocks
- show target project directories
- avoid network downloads

## Non-Goals

- editing the DOCX in place
- modifying scripts outside `/Users/romansergeev/YTAI/utils/thinkific_downloader`
- perfect semantic interpretation of every external link
