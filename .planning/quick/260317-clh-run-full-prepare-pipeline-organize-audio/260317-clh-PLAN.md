---
phase: quick
plan: 260317-clh
type: execute
wave: 1
depends_on: []
files_modified: []
autonomous: true
must_haves:
  truths:
    - "YTCG37 project has v3.0 folder structure with video and audio organized"
    - "DJI TX audio is synced to camera clips with ingest.json written"
    - "Transcription JSON exists with speaker diarization (2 speakers)"
    - "UXP ingest brief is generated for Premiere Pro"
  artifacts:
    - path: "/Volumes/RYA T7 Blue 2/YTCG37_Setup_UAE_Company_Remotely/01_Media/Source/Video/"
      provides: "Organized video files"
    - path: "/Volumes/RYA T7 Blue 2/YTCG37_Setup_UAE_Company_Remotely/01_Media/Source/Audio/"
      provides: "Extracted and synced audio"
    - path: "/Volumes/RYA T7 Blue 2/YTCG37_Setup_UAE_Company_Remotely/01_Media/Source/Setup/ingest.json"
      provides: "Pipeline metadata with sync offsets and transcription"
  key_links: []
---

<objective>
Run the full YTAI prepare pipeline (organize, extract audio, DJI sync, transcribe) on YTCG37_Setup_UAE_Company_Remotely, then generate UXP ingest brief.

Purpose: Prepare this flat-structure project (2 FX3 clips, 2 DJI TX WAVs, 2 speakers) for editing in Premiere Pro.
Output: Organized folder structure, synced audio, transcription with diarization, UXP ingest brief.
</objective>

<execution_context>
@/Users/romansergeev/.claude/get-shit-done/workflows/execute-plan.md
@/Users/romansergeev/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
Project: /Volumes/RYA T7 Blue 2/YTCG37_Setup_UAE_Company_Remotely
Structure: Flat (no scene folders)
Files: RYA-FX3-0099.MP4, RYA-FX3-0100.MP4 + matching XMLs + 2 DJI TX WAVs (TX02_MIC037, TX02_MIC038)
Pipeline: python ~/YTAI/scripts/run_pipeline.py
UXP generator: python ~/YTAI/scripts/01_prepare/0105_generate_uxp_ingest.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Run full prepare + transcribe pipeline</name>
  <files></files>
  <action>
Run the full YTAI pipeline with --all flag and 2 speakers:

```bash
python ~/YTAI/scripts/run_pipeline.py "/Volumes/RYA T7 Blue 2/YTCG37_Setup_UAE_Company_Remotely" --all --speakers 2
```

This executes in order:
1. Init v3.0 folder structure (01_Media/, 02_Exports/, etc.)
2. Auto-organize media files (video to Source/Video/, DJI WAVs to DJI_Audio/)
3. Extract audio from video clips + concatenate FULL_AUDIO
4. Sync DJI wireless audio (timezone auto-detected from XML sidecars)
5. Whisper transcription + Pyannote speaker diarization (2 speakers)

The pipeline runs with console output. Monitor for errors. If DJI sync fails on timezone detection, check XML sidecar availability.

IMPORTANT: This will take several minutes due to audio extraction (ffmpeg) and transcription (Whisper). Use a generous timeout.
  </action>
  <verify>
    <automated>ls -la "/Volumes/RYA T7 Blue 2/YTCG37_Setup_UAE_Company_Remotely/01_Media/Source/Video/" && ls -la "/Volumes/RYA T7 Blue 2/YTCG37_Setup_UAE_Company_Remotely/01_Media/Source/Audio/" && cat "/Volumes/RYA T7 Blue 2/YTCG37_Setup_UAE_Company_Remotely/01_Media/Source/Setup/ingest.json" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'Clips: {len(d.get(\"clips\",[]))}, Transcription: {\"transcription\" in str(d)}')"</automated>
  </verify>
  <done>v3.0 folder structure created, video and audio organized, DJI audio synced, transcription complete with 2-speaker diarization, ingest.json written</done>
</task>

<task type="auto">
  <name>Task 2: Generate UXP ingest brief</name>
  <files></files>
  <action>
Run the UXP ingest generator to create the Premiere Pro ingest brief:

```bash
python ~/YTAI/scripts/01_prepare/0105_generate_uxp_ingest.py --project "/Volumes/RYA T7 Blue 2/YTCG37_Setup_UAE_Company_Remotely"
```

This reads ingest.json and generates the UXP-compatible brief for the Premiere Pro panel to import clips and build the timeline.
  </action>
  <verify>
    <automated>ls -la "/Volumes/RYA T7 Blue 2/YTCG37_Setup_UAE_Company_Remotely/01_Media/Source/Setup/"*ingest* 2>/dev/null && echo "UXP ingest files found"</automated>
  </verify>
  <done>UXP ingest brief generated and saved alongside ingest.json in the Setup folder</done>
</task>

<task type="checkpoint:human-verify" gate="blocking">
  <what-built>Full pipeline run: folder structure, audio sync, transcription, and UXP ingest brief for YTCG37_Setup_UAE_Company_Remotely</what-built>
  <how-to-verify>
    1. Check folder structure: ls "/Volumes/RYA T7 Blue 2/YTCG37_Setup_UAE_Company_Remotely/01_Media/Source/"
    2. Verify synced audio in Audio/ folder — spot-check one WAV in a player
    3. Open ingest.json — confirm clip entries have sync offsets and transcription segments
    4. Confirm UXP ingest brief exists in Setup/ folder
  </how-to-verify>
  <resume-signal>Type "approved" or describe issues</resume-signal>
</task>

</tasks>

<verification>
- v3.0 folder structure exists (01_Media/Source/Video/, Audio/, Setup/)
- Video files moved to Source/Video/
- DJI WAVs processed and synced
- ingest.json contains clip data with sync offsets
- Transcription data present with speaker labels
- UXP ingest brief generated
</verification>

<success_criteria>
YTCG37 project is fully prepared for Premiere Pro editing: organized, synced, transcribed, with UXP ingest brief ready for import.
</success_criteria>

<output>
After completion, create `.planning/quick/260317-clh-run-full-prepare-pipeline-organize-audio/260317-clh-SUMMARY.md`
</output>
