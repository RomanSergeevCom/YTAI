import whisper
from pyannote.audio import Pipeline
import os

INPUT_FILE = "/Volumes/RYA Blue/YTCG38_Coffee/01_Raw/01_02_Audio/YTCG38_Coffee_FULL_AUDIO.wav"
OUTPUT_DIR = "/Volumes/RYA Blue/YTCG38_Coffee/02_Transcripts/02_01_Runs"
OUTPUT_TXT = os.path.join(OUTPUT_DIR, "transcript_with_speakers.txt")

print("Loading Whisper...")
model = whisper.load_model("large-v3")

print("Transcribing...")
result = model.transcribe(INPUT_FILE, language=None, word_timestamps=True)

print("Loading speaker diarization...")
pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1")

print("Detecting speakers...")
diarization = pipeline(INPUT_FILE)

print("Matching speakers to text...")
segments_with_speakers = []

for segment in result["segments"]:
    seg_start = segment["start"]
    seg_end = segment["end"]
    seg_text = segment["text"].strip()
    
    speaker = "UNKNOWN"
    for turn, _, spk in diarization.itertracks(yield_label=True):
        if turn.start <= seg_start < turn.end:
            speaker = spk
            break
    
    segments_with_speakers.append({
        "start": seg_start,
        "end": seg_end,
        "speaker": speaker,
        "text": seg_text
    })

print("Saving...")
with open(OUTPUT_TXT, "w", encoding="utf-8") as f:
    for seg in segments_with_speakers:
        start = f"{int(seg['start']//60):02d}:{seg['start']%60:05.2f}"
        end = f"{int(seg['end']//60):02d}:{seg['end']%60:05.2f}"
        f.write(f"[{start} - {end}] {seg['speaker']}\n{seg['text']}\n\n")

print(f"Done! {OUTPUT_TXT}")
