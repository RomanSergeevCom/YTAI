/**
 * Генератор `.sqpreset` — «свидетельство о рождении» секвенции.
 *
 * Зачем он вообще. В UXP НЕТ API создания дорожек (проверено по справочнику
 * SequenceEditor/VideoTrack и по локальным типингам). Панель рождает дорожку
 * единственным способом — вставляет в неё одноразовый клип, — а удаление в живой
 * Premiere отрабатывает вхолостую. Результат измерен на YTUVIE01: в секвенции
 * `_SYNC` оказалось 30 айтемов, и ВСЕ 30 — однокадровый мусор преднагрева.
 *
 * Пресет решает это с другого конца: Premiere сама создаёт нужное число дорожек
 * при рождении секвенции. Ни сида, ни заглушек, ни мусора.
 *
 * ⚠️ И главное: `mTargeted` в пресете — записываемое поле НА КАЖДУЮ
 * аудиодорожку. Это единственный найденный способ отдать секвенцию человеку с
 * уже включёнными целями дорожек, потому что API таргетинга в UXP тоже нет.
 * ⚠️ Обратное так же важно: блок `<VideoTracks>` в стоковом пресете ПУСТ при
 * трёх видеодорожках — видеодорожки подорожечно не настраиваются. Поэтому
 * раскладка под Synchronize живёт на аудио, а не на видео.
 *
 * Модуль чистый: ни UXP, ни файловой системы. Тексты пресетов ходят строками.
 */

const TICKS_PER_SECOND = 254016000000;

/** Одна аудиодорожка стокового пресета Premiere 26.x — шаблон на случай, когда
 *  стоковый файл прочитать не удалось. */
const AUDIO_TRACK_TEMPLATE = {
  mAssign: 0, mAudioSends: [], mChannelType: 1, mIsOpen: false, mIsSubmix: false,
  mKeyframeMode: true, mLocked: false, mMatrix: [], mMute: false, mName: '',
  mPan: 0, mPannerAssignments: [], mSolo: false, mSyncLock: true,
  mTargeted: false, mTrackID: -1, mVolume: 1,
};

/**
 * Встроенный запасной пресет — на случай, если стоковый файл Premiere не
 * прочитался (другая версия, другой путь, нет доступа). UHD 25p, Rec.709.
 * EditingModeGUID взят из стокового «UHD (4K) 2160p 25 fps».
 */
const FALLBACK_PRESET_XML = `<?xml version="1.0" encoding="UTF-8"?>
<PremiereData Version="3">
	<SequencePreset ObjectRef="1"/>
	<SequencePreset ObjectID="1" ClassID="5e73dd7e-4f86-4917-80eb-08ddb2f4a5f3" Version="9">
		<VideoTimeDisplay>101</VideoTimeDisplay>
		<AudioTimeDisplay>200</AudioTimeDisplay>
		<VideoFrameRate>10160640000</VideoFrameRate>
		<VideoFrameSize>0,0,3840,2160</VideoFrameSize>
		<AudioFrameRate>5292000</AudioFrameRate>
		<AudioChannelType>1</AudioChannelType>
		<VideoFieldType>0</VideoFieldType>
		<WorkingColorSpace>{"baseColorProfile":{"colorProfileName":"BT.709 RGB Full"},"baseProfileType":1}</WorkingColorSpace>
		<Names Version="1">
			<NameItem Version="1" Index="0">
				<First>en_US</First>
				<Second>YTAI sync bench</Second>
			</NameItem>
		</Names>
		<EditingModeGUID.Mac>795454d9-d3c2-429d-9474-923ab13b7018</EditingModeGUID.Mac>
		<EditingModeGUID.Win>9678AF98-A7B7-4bdb-B477-7AC9C8DF4A4E</EditingModeGUID.Win>
		<VideoPixelAspectRatio>1,1</VideoPixelAspectRatio>
		<VideoUseMaxBitDepth>false</VideoUseMaxBitDepth>
		<VideoUseMaxRenderQuality>false</VideoUseMaxRenderQuality>
		<AdaptiveNumChannels>2</AdaptiveNumChannels>
		<InitialNumberOfVideoTracks>3</InitialNumberOfVideoTracks>
		<AudioTracks>[]</AudioTracks>
		<VideoTracks>[]</VideoTracks>
	</SequencePreset>
</PremiereData>
`;

/** Заменить содержимое одиночного тега. Возвращает {text, hit}. */
function replaceTag(xml, tag, value) {
  const re = new RegExp('<' + tag + '>[\\s\\S]*?</' + tag + '>');
  if (!re.test(xml)) return { text: xml, hit: false };
  return { text: xml.replace(re, '<' + tag + '>' + value + '</' + tag + '>'), hit: true };
}

/** Вставить тег перед закрытием SequencePreset, если его не было. */
function ensureTag(xml, tag, value) {
  const r = replaceTag(xml, tag, value);
  if (r.hit) return r.text;
  return xml.replace('</SequencePreset>', '\t\t<' + tag + '>' + value + '</' + tag + '>\n\t</SequencePreset>');
}

function ticksPerFrame(fps) {
  if (!fps || !isFinite(fps) || fps <= 0) return null;
  return Math.round(TICKS_PER_SECOND / fps);
}

/**
 * Собрать текст пресета под нужную раскладку.
 *
 * @param {string|null} stockXml  текст стокового .sqpreset (или null → запасной)
 * @param {Object} opts
 *   @param {number} opts.aTracks    сколько аудиодорожек создать
 *   @param {number} [opts.vTracks]  сколько видеодорожек (для стенда хватает 1)
 *   @param {boolean} [opts.targeted=true]  включить цель на каждой аудиодорожке
 *   @param {boolean} [opts.syncLock=false] sync lock (для стенда снимаем: иначе
 *          ход Synchronize потянет за собой соседние дорожки)
 *   @param {boolean} [opts.locked=false]   замок дорожки
 *   @param {number} [opts.fps]
 *   @param {number} [opts.width] @param {number} [opts.height]
 *   @param {number} [opts.sampleRate]
 *   @param {string} [opts.name]
 * @returns {string} текст .sqpreset
 */
function buildPresetXml(stockXml, opts = {}) {
  const aTracks = Math.max(1, opts.aTracks | 0);
  const vTracks = Math.max(1, (opts.vTracks === undefined ? 1 : opts.vTracks) | 0);
  const targeted = opts.targeted !== false;
  const syncLock = opts.syncLock === true;
  const locked = opts.locked === true;

  let xml = (typeof stockXml === 'string' && stockXml.indexOf('<SequencePreset') !== -1)
    ? stockXml
    : FALLBACK_PRESET_XML;

  // Шаблон дорожки берём ИЗ САМОГО пресета, а не из своей копии: так генератор
  // переживёт смену формата в новой версии Premiere, а не начнёт тихо писать поля,
  // которых там больше нет.
  let template = AUDIO_TRACK_TEMPLATE;
  const m = xml.match(/<AudioTracks>([\s\S]*?)<\/AudioTracks>/);
  if (m) {
    try {
      const arr = JSON.parse(m[1]);
      if (Array.isArray(arr) && arr.length && arr[0] && typeof arr[0] === 'object') template = arr[0];
    } catch (e) { /* остаёмся на своём шаблоне */ }
  }

  const tracks = [];
  for (let i = 0; i < aTracks; i++) {
    tracks.push(Object.assign({}, template, {
      mTargeted: targeted, mSyncLock: syncLock, mLocked: locked, mTrackID: -1,
    }));
  }

  xml = ensureTag(xml, 'AudioTracks', JSON.stringify(tracks));
  xml = ensureTag(xml, 'VideoTracks', '[]');
  xml = ensureTag(xml, 'InitialNumberOfVideoTracks', String(vTracks));

  const tpf = ticksPerFrame(opts.fps);
  if (tpf) xml = ensureTag(xml, 'VideoFrameRate', String(tpf));
  if (opts.width && opts.height) {
    const rect = '0,0,' + (opts.width | 0) + ',' + (opts.height | 0);
    xml = ensureTag(xml, 'VideoFrameSize', rect);
    xml = replaceTag(xml, 'PreviewVideoFrameSize', rect).text;
  }
  if (opts.sampleRate) {
    xml = ensureTag(xml, 'AudioFrameRate', String(Math.round(TICKS_PER_SECOND / opts.sampleRate)));
  }
  if (opts.name) {
    xml = xml.replace(/(<NameItem[\s\S]*?<Second>)[\s\S]*?(<\/Second>)/, '$1' + opts.name + '$2');
  }
  return xml;
}

/** Разобрать сгенерированный пресет обратно — для проверок и тестов. */
function readPresetTracks(xml) {
  const m = xml.match(/<AudioTracks>([\s\S]*?)<\/AudioTracks>/);
  const v = xml.match(/<InitialNumberOfVideoTracks>(\d+)<\/InitialNumberOfVideoTracks>/);
  let audio = [];
  if (m) { try { audio = JSON.parse(m[1]); } catch (e) { audio = []; } }
  return { audio, videoCount: v ? parseInt(v[1], 10) : null };
}

module.exports = {
  buildPresetXml,
  readPresetTracks,
  ticksPerFrame,
  TICKS_PER_SECOND,
  FALLBACK_PRESET_XML,
  AUDIO_TRACK_TEMPLATE,
};
