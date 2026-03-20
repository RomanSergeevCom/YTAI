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
 * @param {Object|null} transcriptsBin - Target bin for SRT (02_Transcripts)
 * @param {Object} logger - Logger instance
 * @param {Object|null} sequence - Active sequence (unused, kept for API compat)
 * @returns {{ srtImported: boolean, transcriptsImported: number }}
 */
async function importTranscripts(project, ingest, transcriptsBin, logger, sequence, projectCode) {
  let srtImported = false;
  let transcriptsImported = 0;

  // 1. Import SRT files into project bin
  // Import word-level captions SRT (preferred for caption track)
  const captionsSrtPath = ingest.files && ingest.files.captions_srt;
  const srtPath = ingest.files && ingest.files.transcript_srt;

  if (captionsSrtPath) {
    logger.debug(`Captions SRT path: ${captionsSrtPath}`);
    try {
      let capContent = null;
      try {
        const capEntry = await uxpfs.getEntryWithUrl('file://' + captionsSrtPath);
        capContent = await capEntry.read();
        const blockCount = (capContent.match(/^\d+$/gm) || []).length;
        logger.debug(`Captions SRT: ${capContent.length} chars, ${blockCount} blocks (word-level)`);
      } catch (sizeErr) {
        logger.debug(`Cannot read captions SRT for check: ${sizeErr.message}`);
      }

      // If projectCode available, create short-named copy and import ONLY it (not the original)
      if (projectCode) {
        const shortName = projectCode + '_1_Ingest_captions.srt';
        if (captionsSrtPath.split('/').pop() !== shortName && capContent) {
          try {
            const dirPath = captionsSrtPath.replace(/[/\\][^/\\]+$/, '');
            const dir = await uxpfs.getEntryWithUrl('file://' + dirPath);
            const shortFile = await dir.createFile(shortName, { overwrite: true });
            await shortFile.write(capContent);
            await project.importFiles([dirPath + '/' + shortName], true, transcriptsBin || null, false);
            srtImported = true;
            logger.info(`Captions SRT imported: ${shortName} (short-named copy, word-level)`);
          } catch (copyErr) {
            // Fallback: import original if short copy fails
            await project.importFiles([captionsSrtPath], true, transcriptsBin || null, false);
            srtImported = true;
            logger.info(`Captions SRT imported: ${captionsSrtPath.split('/').pop()} (original, word-level)`);
          }
        } else {
          // Already has short name
          await project.importFiles([captionsSrtPath], true, transcriptsBin || null, false);
          srtImported = true;
          logger.info(`Captions SRT imported: ${captionsSrtPath.split('/').pop()} (word-level)`);
        }
      } else {
        // No projectCode — import original as-is
        await project.importFiles([captionsSrtPath], true, transcriptsBin || null, false);
        srtImported = true;
        logger.info(`Captions SRT imported: ${captionsSrtPath.split('/').pop()} (word-level)`);
      }
    } catch (err) {
      logger.warn(`Captions SRT import failed: ${err.message}`);
    }
  }

  if (srtPath) {
    logger.debug(`Transcript SRT path: ${srtPath}`);
    try {
      let srtContent = null;
      try {
        const srtEntry = await uxpfs.getEntryWithUrl('file://' + srtPath);
        srtContent = await srtEntry.read();
        const blockCount = (srtContent.match(/^\d+$/gm) || []).length;
        logger.debug(`Transcript SRT: ${srtContent.length} chars, ${blockCount} blocks (sentence-level)`);
      } catch (sizeErr) {
        logger.debug(`Cannot read SRT for size check: ${sizeErr.message}`);
      }

      // If projectCode available, create short-named copy and import ONLY it (not the original)
      if (projectCode) {
        const shortName = projectCode + '_1_Ingest_transcript.srt';
        if (srtPath.split('/').pop() !== shortName && srtContent) {
          try {
            const dirPath = srtPath.replace(/[/\\][^/\\]+$/, '');
            const dir = await uxpfs.getEntryWithUrl('file://' + dirPath);
            const shortFile = await dir.createFile(shortName, { overwrite: true });
            await shortFile.write(srtContent);
            await project.importFiles([dirPath + '/' + shortName], true, transcriptsBin || null, false);
            if (!captionsSrtPath) srtImported = true;
            logger.info(`Transcript SRT imported: ${shortName} (short-named copy, sentence-level)`);
          } catch (copyErr) {
            // Fallback: import original if short copy fails
            await project.importFiles([srtPath], true, transcriptsBin || null, false);
            if (!captionsSrtPath) srtImported = true;
            logger.info(`Transcript SRT imported: ${srtPath.split('/').pop()} (original, sentence-level)`);
          }
        } else {
          // Already has short name
          await project.importFiles([srtPath], true, transcriptsBin || null, false);
          if (!captionsSrtPath) srtImported = true;
          logger.info(`Transcript SRT imported: ${srtPath.split('/').pop()} (sentence-level)`);
        }
      } else {
        // No projectCode — import original as-is
        await project.importFiles([srtPath], true, transcriptsBin || null, false);
        if (!captionsSrtPath) srtImported = true;
        logger.info(`Transcript SRT imported: ${srtPath.split('/').pop()} (sentence-level, reference)`);
      }
    } catch (err) {
      logger.warn(`Transcript SRT import failed: ${err.message}`);
      if (err.stack) logger.debug(err.stack);
    }
  }

  // 1b. Import per-scene caption SRT files
  const sceneCaptions = ingest.files && ingest.files.scene_captions_srt;
  if (sceneCaptions && typeof sceneCaptions === 'object') {
    const sceneNames = Object.keys(sceneCaptions);
    logger.info(`Per-scene captions: ${sceneNames.length} scenes (${sceneNames.join(', ')})`);
    for (const [scene, sceneSrtPath] of Object.entries(sceneCaptions)) {
      if (!sceneSrtPath) continue;
      try {
        // Create short-named copy for the scene
        const shortName = projectCode
          ? `${projectCode}_1_${scene}_captions.srt`
          : sceneSrtPath.split('/').pop();

        if (projectCode && sceneSrtPath.split('/').pop() !== shortName) {
          const dirPath = sceneSrtPath.replace(/[/\\][^/\\]+$/, '');
          const dir = await uxpfs.getEntryWithUrl('file://' + dirPath);
          const srtEntry = await uxpfs.getEntryWithUrl('file://' + sceneSrtPath);
          const srtContent = await srtEntry.read();
          const shortFile = await dir.createFile(shortName, { overwrite: true });
          await shortFile.write(srtContent);
          await project.importFiles([dirPath + '/' + shortName], true, transcriptsBin || null, false);
        } else {
          await project.importFiles([sceneSrtPath], true, transcriptsBin || null, false);
        }
        srtImported = true;
        logger.info(`Scene captions imported: ${shortName} (${scene})`);
      } catch (err) {
        logger.warn(`Scene captions import failed for ${scene}: ${err.message}`);
      }
    }
  }

  if (!captionsSrtPath && !srtPath && !sceneCaptions) {
    logger.warn('No SRT file paths in ingest JSON (files.captions_srt / files.transcript_srt / files.scene_captions_srt missing)');
  }

  if (srtImported) {
    if (sceneCaptions) {
      logger.info('To add per-scene captions: drag scene SRT from 02_Transcripts to each timeline caption track');
    } else {
      const dragTarget = captionsSrtPath ? captionsSrtPath.split('/').pop() : srtPath.split('/').pop();
      logger.info(`To add captions: drag "${dragTarget}" from 02_Transcripts to timeline caption track`);
    }
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
