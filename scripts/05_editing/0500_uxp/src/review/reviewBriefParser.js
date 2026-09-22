/**
 * reviewBriefParser.js — Parse review_brief.json for the Review pipeline.
 *
 * Review brief is created by compare_review.py + generate_review_html.py.
 * It contains:
 *   - timeline[]: ordered entries of type "edited" and "insertion"
 *   - unused_segments[]: Assembly brief segments not in the edit
 *   - project{}: metadata (edited video, fps, review version)
 *
 * This parser validates the schema and normalizes the data for
 * reviewAssembler.js to build the _5_Review sequence.
 */

/**
 * Parse and validate review_brief.json content.
 *
 * @param {string} jsonContent - Raw JSON string
 * @param {Object} logger - Logger instance
 * @returns {{ project, timeline, insertions, editedVideoFile, fps, projectCode }}
 */
function parseReviewBrief(jsonContent, logger) {
  var data;
  try {
    data = JSON.parse(jsonContent);
  } catch (e) {
    throw new Error('Invalid JSON in review brief: ' + e.message);
  }

  // Validate required sections
  if (!data.project) throw new Error('Missing "project" section in review brief');
  if (!data.timeline || !Array.isArray(data.timeline)) throw new Error('Missing "timeline" array in review brief');

  var project = data.project;
  var fps = project.fps || 25;
  var editedVideoFile = project.edited_video || '';
  var projectCode = project.project_id || '';
  var reviewVersion = project.review_version || 1;

  if (!editedVideoFile) {
    if (logger) logger.warn('No edited_video specified in review brief');
  }

  // Separate timeline into edited segments and insertions
  var editedEntries = [];
  var insertions = [];
  var totalEdited = 0;
  var totalInsertions = 0;

  for (var i = 0; i < data.timeline.length; i++) {
    var entry = data.timeline[i];

    if (entry.type === 'edited') {
      if (entry.status === 'cut') continue; // Skip cut segments

      editedEntries.push({
        idx: totalEdited,
        tcIn: entry.tc_in || '00:00.0',
        tcOut: entry.tc_out || '00:00.0',
        transcript: entry.transcript || '',
        matchedSegments: entry.matched_segments || [],
        comment: entry.comment || '',
        _originalIdx: i
      });
      totalEdited++;

    } else if (entry.type === 'insertion') {
      if (entry.status !== 'insert') continue; // Skip non-insert entries

      insertions.push({
        idx: totalInsertions,
        insertAfterTc: entry.insert_after_tc || '',
        sourceFile: entry.source_file || '',
        sourceTcIn: entry.source_tc_in || '',
        sourceTcOut: entry.source_tc_out || '',
        originalSegmentId: entry.original_segment_id || '',
        originalBlockName: entry.original_block_name || '',
        transcript: entry.transcript || '',
        comment: entry.comment || '',
        _originalIdx: i
      });
      totalInsertions++;
    }
  }

  // Also check unused_segments for any with user_action = "insert"
  if (data.unused_segments && Array.isArray(data.unused_segments)) {
    for (var j = 0; j < data.unused_segments.length; j++) {
      var seg = data.unused_segments[j];
      if (seg.user_action === 'insert' && seg.insert_position) {
        insertions.push({
          idx: totalInsertions,
          insertAfterTc: seg.insert_position,
          sourceFile: seg.source_file || '',
          sourceTcIn: seg.tc_in || '',
          sourceTcOut: seg.tc_out || '',
          originalSegmentId: seg.segment_id || '',
          originalBlockName: seg.block_name || '',
          transcript: seg.transcript || '',
          comment: seg.comment || '',
          _fromUnused: true
        });
        totalInsertions++;
      }
    }
  }

  if (logger) {
    logger.info('Review brief parsed:');
    logger.info('  Edited video: ' + editedVideoFile);
    logger.info('  Timeline entries: ' + editedEntries.length + ' edited + ' + insertions.length + ' insertions');
    logger.info('  FPS: ' + fps);
    logger.info('  Review version: ' + reviewVersion);
  }

  // Parse deleted_segments (clips removed from Review timeline)
  var deletedSegments = [];
  if (data.deleted_segments && Array.isArray(data.deleted_segments)) {
    for (var ds = 0; ds < data.deleted_segments.length; ds++) {
      var del = data.deleted_segments[ds];
      deletedSegments.push({
        segmentId: del.segment_id || 'del_' + ds,
        removedIn: del.removed_in || '',
        reason: del.reason || '',
        sourceFile: del.source_file || '',
        sourceTcIn: del.source_tc_in || '',
        sourceTcOut: del.source_tc_out || '',
        durationSec: del.duration_sec || 0,
        speaker: del.speaker || '',
        transcript: del.transcript || '',
        assemblyRef: del.assembly_ref || ''
      });
    }
    if (logger) logger.info('  Deleted segments: ' + deletedSegments.length);
  }

  return {
    project: project,
    timeline: editedEntries,
    insertions: insertions,
    deletedSegments: deletedSegments,
    deletedSceneSequence: data.deleted_scene_sequence || '',
    editedVideoFile: editedVideoFile,
    fps: fps,
    projectCode: projectCode,
    reviewVersion: reviewVersion,
    stats: data.stats || {}
  };
}

module.exports = {
  parseReviewBrief
};
