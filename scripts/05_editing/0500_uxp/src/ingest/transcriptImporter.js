/**
 * Transcript importer:
 * 1. Binds premiere_transcript.json to each clip via Transcript API (Text panel)
 * 2. Imports SRT into project bin (user drags to caption track manually)
 *
 * Note: UXP API does not support programmatic caption track insertion.
 * SRT must be dragged from 02_Transcripts bin to the timeline manually.
 */

const ppro = require('premierepro');
const uxp = require('uxp');
const uxpfs = uxp.storage.localFileSystem;
const { findProjectItemByName } = require('./timelineBuilder');

/**
 * Convert our premiere_transcript.json format to Adobe Transcript JSON spec.
 *
 * Differences:
 * - start/duration: milliseconds → seconds
 * - speakerId → speaker
 * - adds segment-level start/duration
 * - adds top-level speakers array
 */
function convertToAdobeFormat(jsonContent) {
  const data = typeof jsonContent === 'string' ? JSON.parse(jsonContent) : jsonContent;

  // Collect unique speakers
  const speakerMap = new Map();

  const segments = (data.segments || []).map(seg => {
    const speakerId = seg.speakerId || seg.speaker || '';

    // Track speakers
    if (speakerId && !speakerMap.has(speakerId)) {
      speakerMap.set(speakerId, {
        id: speakerId,
        name: `Speaker ${speakerMap.size + 1}`
      });
    }

    // Convert words: ms → seconds
    const words = (seg.words || []).map(w => ({
      text: w.text,
      start: (w.start || 0) / 1000,
      duration: (w.duration || 0) / 1000,
      confidence: w.confidence || 0,
      eos: w.eos || false,
      tags: w.tags || [],
      type: w.type || 'word'
    }));

    // Compute segment start/duration from words
    const segStart = words.length > 0 ? words[0].start : 0;
    const lastWord = words.length > 0 ? words[words.length - 1] : null;
    const segDuration = lastWord ? (lastWord.start + lastWord.duration - segStart) : 0;

    return {
      language: seg.language || data.language || 'en-us',
      speaker: speakerId,
      start: segStart,
      duration: segDuration,
      words
    };
  });

  return JSON.stringify({
    language: data.language || 'en-us',
    segments,
    speakers: Array.from(speakerMap.values())
  });
}

/**
 * Import transcripts and SRT.
 *
 * @param {Object} project - Premiere Pro project
 * @param {Object} ingest - Parsed ingest JSON object
 * @param {Object|null} transcriptsBin - Target bin for SRT (01_Transcripts)
 * @param {Object} logger - Logger instance
 * @param {Object|null} sequence - Active sequence (unused, kept for API compat)
 * @returns {{ srtImported: boolean, transcriptsImported: number }}
 */
async function importTranscripts(project, ingest, transcriptsBin, logger, sequence, projectCode) {
  // Create per-scene transcript sub-bins inside sourceBin (00_Source)
  const { createTranscriptSceneBins } = require('./binManager');
  let transcriptSceneBins = {};
  const scenes = [...new Set(ingest.clips.map(c => c.scene).filter(Boolean))].sort();
  if (transcriptsBin && scenes.length > 0) {
    try {
      transcriptSceneBins = await createTranscriptSceneBins(
        project, transcriptsBin, scenes, logger, projectCode);
    } catch (err) {
      logger.debug(`Transcript scene bins failed: ${err.message}`);
    }
  }
  let srtImported = false;
  let transcriptsImported = 0;

  // 1. Skip general SRT files — only import per-scene SRTs
  // General captions/transcript SRTs stay on disk but are NOT imported into Premiere
  const captionsSrtPath = ingest.files && ingest.files.captions_srt;
  const srtPath = ingest.files && ingest.files.transcript_srt;
  if (captionsSrtPath) {
    logger.info(`General word-level SRT on disk (not imported): ${captionsSrtPath.split('/').pop()}`);
  }
  if (srtPath) {
    logger.info(`General transcript SRT on disk (not imported): ${srtPath.split('/').pop()}`);
  }

  // 1b. Import per-scene SRT files into per-scene transcript bins in 00_Source
  const sceneCaptions = ingest.files && ingest.files.scene_captions_srt;
  const sceneTranscripts = ingest.files && ingest.files.scene_transcript_srt;

  // Helper: import one SRT into a scene transcript bin
  async function importSceneSrt(sceneSrtPath, scene, label) {
    const targetBin = transcriptSceneBins[scene] || transcriptsBin || null;
    try {
      await project.importFiles([sceneSrtPath], true, targetBin, false);
      srtImported = true;
      const fname = sceneSrtPath.split('/').pop();
      logger.info(`${label} → ${targetBin ? targetBin.name : 'root'}: ${fname}`);
    } catch (err) {
      logger.warn(`${label} import failed for ${scene}: ${err.message}`);
    }
  }

  if (sceneCaptions && typeof sceneCaptions === 'object') {
    for (const [scene, path] of Object.entries(sceneCaptions)) {
      if (path) await importSceneSrt(path, scene, 'Captions');
    }
  }
  if (sceneTranscripts && typeof sceneTranscripts === 'object') {
    for (const [scene, path] of Object.entries(sceneTranscripts)) {
      if (path) await importSceneSrt(path, scene, 'Transcript');
    }
  }

  if (srtImported) {
    logger.info('Per-scene SRTs imported. Drag from transcript bins to timeline caption track.');
  } else if (!sceneCaptions && !sceneTranscripts) {
    logger.warn('No per-scene SRT paths in ingest JSON');
  }

  // 2. Bind premiere_transcript.json to each clip via Transcript API
  for (const clip of ingest.clips) {
    if (!clip.premiere_transcript) {
      logger.debug(`No premiere_transcript for ${clip.clip_id}`);
      continue;
    }

    try {
      // Read the transcript JSON file
      const fileEntry = await uxpfs.getEntryWithUrl('file://' + clip.premiere_transcript);
      const rawContent = await fileEntry.read();
      logger.debug(`Read transcript: ${clip.premiere_transcript}`);

      // Convert to Adobe format (ms→s, speakerId→speaker, add speakers array)
      const adobeJson = convertToAdobeFormat(rawContent);
      const parsed = JSON.parse(adobeJson);
      const totalWords = (parsed.segments || []).reduce((sum, s) => sum + (s.words ? s.words.length : 0), 0);
      const speakerNames = (parsed.speakers || []).map(s => s.name).join(', ');
      logger.debug(`Adobe JSON: ${adobeJson.length} chars, ${parsed.segments ? parsed.segments.length : 0} segments, ${totalWords} words, ${parsed.speakers ? parsed.speakers.length : 0} speakers (${speakerNames})`);

      // Find the clip in the project
      const clipItem = await findProjectItemByName(project, clip.filename, logger);
      if (!clipItem) {
        logger.warn(`Clip "${clip.filename}" not found in project — cannot bind transcript`);
        continue;
      }
      logger.debug(`Found clip: "${clipItem.name}" (type=${clipItem.type})`);

      // Cast to ClipProjectItem (required by Transcript API)
      const castClip = ppro.ClipProjectItem.cast(clipItem);
      if (!castClip) {
        logger.warn(`"${clip.filename}" cannot be cast to ClipProjectItem — skipping transcript`);
        continue;
      }
      logger.debug(`ClipProjectItem.cast success for "${clip.filename}"`);

      // Parse and bind transcript to clip
      const textSegments = ppro.Transcript.importFromJSON(adobeJson);
      logger.debug(`importFromJSON returned ${textSegments ? 'TextSegments' : 'null'} for ${clip.clip_id}`);

      project.lockedAccess(() => {
        project.executeTransaction((compoundAction) => {
          const action = ppro.Transcript.createImportTextSegmentsAction(
            textSegments,
            castClip
          );
          compoundAction.addAction(action);
        }, `Import transcript ${clip.clip_id}`);
      });

      transcriptsImported++;
      logger.info(`Transcript bound: "${clip.filename}" (${clip.clip_id})`);
    } catch (err) {
      logger.warn(`Failed to bind transcript for ${clip.clip_id}: ${err.message}`);
      if (err.stack) logger.debug(err.stack);
    }
  }

  logger.info(`Transcripts: SRT=${srtImported}, bound=${transcriptsImported}/${ingest.clips.length}`);
  return { srtImported, transcriptsImported };
}

module.exports = { importTranscripts };
