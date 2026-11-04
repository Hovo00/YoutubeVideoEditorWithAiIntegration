// Application UI language (English/Russian) — purely cosmetic, never affects
// app logic or the video's own spoken language (that's languageSelect, a
// completely separate concept handled in app.js). Plain global-scope script
// (no bundler/modules here), loaded before app.js so `t()`/`applyTranslations`
// are available everywhere.

const UI_LANG_KEY = "videoeditory_ui_lang";

const TRANSLATIONS = {
  en: {
    header_subtitle: "Edit a video by editing its transcript.",

    settings_button_title: "Settings",
    settings_lang_label: "Interface language",

    step1_heading: "1. Paste a YouTube link",
    step1_desc:
      "The app downloads the video and transcribes it locally with Whisper — no manual " +
      "caption download/upload needed. Pick the language that's actually spoken in the " +
      "video for best accuracy.",
    youtube_url_placeholder: "https://youtu.be/...",
    language_select_placeholder: "Select the video's language…",
    lang_option_english: "English",
    lang_option_russian: "Russian",
    lang_option_armenian: "Armenian",
    lang_option_spanish: "Spanish",
    lang_option_french: "French",
    lang_option_german: "German",
    lang_option_italian: "Italian",
    lang_option_portuguese: "Portuguese",
    lang_option_ukrainian: "Ukrainian",
    lang_option_turkish: "Turkish",
    lang_option_arabic: "Arabic",
    lang_option_hindi: "Hindi",
    lang_option_chinese: "Chinese",
    lang_option_japanese: "Japanese",
    lang_option_korean: "Korean",
    go_button: "Go",

    alert_need_url: "Paste a YouTube URL first.",
    alert_need_language: "Please select the language spoken in the video first.",
    ingest_status_starting: "Starting...",
    ingest_status_could_not_start: "Could not start: {detail}",
    ingest_status_resuming: "Resuming previous session...",
    ingest_status_lost_track: "Lost track of this project — paste the URL again.",
    ingest_status_working: "Working...",
    ingest_status_elapsed: "{message} ({elapsed}s elapsed)",
    ingest_status_cached_both: "Loaded from library (already downloaded and transcribed).",
    ingest_status_cached_video: "Video loaded from library, transcribed in {elapsed}s.",
    ingest_status_transcribed: "Transcribed in {elapsed}s.",
    ingest_status_transcript_load_failed:
      "Transcription finished but the transcript could not be loaded.",
    ingest_status_failed: "Failed: {error}",
    video_info_restored: "Restored previous session — duration {duration}",
    video_info_duration: "Duration {duration}",

    step2_heading: "2. Choose how to edit",
    edit_mode_manual_option: "Manual — delete parts yourself, no AI",
    edit_mode_outline_option: "AI outline — Claude structures + corrects, you pick sections to remove",
    edit_mode_autonomous_option: "AI autonomous — Claude decides what to cut from your instruction",

    manual_desc:
      "Every cue Whisper produced, with its exact timestamp. Check the ones you want " +
      "removed, then cut — no AI involved.",
    cut_selected_cues_button: "Cut selected cues",
    cues_status_loading: "Loading...",
    cues_status_count: "{count} cue(s).",
    alert_need_video: "Paste and transcribe a video first.",
    alert_check_one_cue: "Check at least one cue to remove first.",
    alert_could_not_build_cuts: "Could not build cuts from selection: {detail}",

    outline_desc_html:
      "In Claude Desktop (or a <code>claude</code> terminal), attach/<code>cd</code> into " +
      'this project folder. Click "Copy message for Claude" below, paste it as your ' +
      "first message, and send it — the message points Claude at " +
      "<code>AI_EDITING_INSTRUCTIONS.md</code> so it reads the rules before doing " +
      "anything. It'll read <code>workspace/subtitles.vtt</code> and write " +
      "<code>workspace/outline.md</code>: the transcript broken into topic-based " +
      "paragraphs with titles, correcting Whisper's transcription mistakes along the way.",
    copy_message_button: "Copy message for Claude",
    load_outline_button: "Load outline",
    outline_status_loading: "Loading...",
    outline_status_sections: "{count} section(s).",
    outline_status_empty: "outline.md is empty so far.",
    outline_note:
      "Each paragraph/sub-paragraph below shows Claude's (possibly corrected) transcript " +
      "text for that span — check the box on any paragraph or sub-paragraph to mark it " +
      'for removal, then click "Cut selected sections".',
    cut_selected_sections_button: "Cut selected sections",
    alert_check_one_section: "Check at least one paragraph or sub-paragraph to remove first.",

    autonomous_desc_html:
      'Describe the overall result you want — e.g. "this is 40 minutes, trim it to ' +
      'about 15, keep only the important information." Claude decides what to remove. ' +
      'Click "Copy message for Claude" and paste it into Claude Desktop/terminal; it ' +
      "writes <code>workspace/cuts.md</code> for you.",
    autonomous_instruction_placeholder:
      "e.g. trim this to about 15 minutes, keep only the important information",
    alert_need_instruction: "Describe the result you want first.",
    load_cuts_file_button: "Load cuts from workspace/cuts.md",
    manual_fallback_summary: "Or paste a reply from another AI manually",
    manual_fallback_desc_html:
      "Paste the full structured reply you got back from ChatGPT (or another AI) " +
      "after giving it <code>AI_EDITING_INSTRUCTIONS.md</code> plus your instruction " +
      "and transcript — including its <code>## REMOVED</code> section.",
    parse_cuts_button: "Parse cuts",
    alert_paste_ai_reply: "Paste the AI's reply first.",
    alert_parsing_failed: "Parsing failed: {detail}",
    alert_could_not_load_cuts: "Could not load workspace/cuts.md: {detail}",

    step3_heading: "3. Review cuts",
    table_header_start: "Start",
    table_header_end: "End",
    table_header_duration: "Dur.",
    table_header_text_reason: "Text / reason",
    summary_html:
      "Original duration: <b>{original}</b> &nbsp;·&nbsp; " +
      "Cuts found: <b>{count}</b> &nbsp;·&nbsp; " +
      "Removed: <b>{removed}</b> &nbsp;·&nbsp; " +
      'New duration (if all cuts kept enabled): <b id="newDuration">{newDuration}</b>',

    step4_heading: "4. Choose audio & render",
    audio_mode_original_option: "Original audio — just cut, keep the real audio",
    audio_mode_auto_option: "Automatic TTS — generate a voice-over for every chunk automatically",
    audio_mode_manual_option: "Manual TTS — edit/generate/upload voice-over per chunk yourself",

    audio_original_desc: "Keeps the original audio untouched, no voice-over, no music.",
    render_button: "Render edited video",
    alert_no_cuts_enabled:
      "No cuts are enabled — nothing to remove. Enable at least one cut, or there's nothing to render.",
    render_status_starting: "Starting render...",
    render_status_failed_start: "Render failed to start: {detail}",

    auto_tts_desc:
      "Generates a voice-over for every chunk with the voice you pick below — Piper " +
      "(free, local) or, if configured, Azure (paid, higher quality). The speed " +
      "(0.9x–1.1x) is picked automatically per chunk so the voice-over fills its " +
      "window. For Azure, each chunk is first measured with a free Piper voice, so " +
      "chunks that can't fit are never sent to Azure. Chunks that are too long, or " +
      "would leave more than 5 seconds of silence, are listed for you to fix before " +
      "the render continues.",
    auto_tts_review_summary:
      "{bad} of {total} chunk(s) need attention. The others are ready. " +
      "Edit the text and click Recheck (free check first; Azure only runs once it fits), " +
      "or Accept anyway. Then Continue render. Azure characters used in this run: {chars}.",
    auto_tts_review_all_ok:
      "All {total} chunk(s) are ready. Azure characters used in this run: {chars}.",
    auto_tts_continue_button: "Continue render",
    auto_tts_recheck_button: "Recheck",
    auto_tts_accept_button: "Accept anyway",
    auto_tts_checking: "Checking...",
    auto_tts_chars: "{n} characters",
    auto_tts_flag_too_long_estimate:
      "Too long — predicted {est}s even at {rate}x, but the window is {slot}s. " +
      "Cut about {chars} characters.",
    auto_tts_flag_too_long_audio:
      "Too long — the voice-over is {audio}s at {rate}x, but the window is {slot}s " +
      "({over}s over). Cut about {chars} characters, or accept it and it will be cut off.",
    auto_tts_flag_too_short_estimate:
      "Too short — predicted {est}s even at {rate}x, which leaves {gap}s of silence in the " +
      "{slot}s window. Add about {chars} characters.",
    auto_tts_flag_too_short_audio:
      "Too short — the voice-over is {audio}s at {rate}x, which leaves {gap}s of silence " +
      "in the {slot}s window. Add about {chars} characters, or accept it.",
    auto_tts_chunk_ok: "Fits — {audio}s at {rate}x, window {slot}s.",
    auto_tts_chunk_accepted: "Accepted as-is — {audio}s at {rate}x, window {slot}s.",
    auto_tts_unresolved: "Some chunks still need attention.",
    auto_tts_button: "Generate voice-over automatically & render",
    tts_speed_label: "Speed:",
    alert_no_voices:
      "No TTS voices are available — install a Piper voice model, or configure " +
      "AZURE_SPEECH_KEY/AZURE_SPEECH_REGION for Azure voices (see the setup docs).",
    auto_tts_status_starting: "Starting automatic voice-over...",
    auto_tts_status_failed: "Could not start: {detail}",

    manual_tts_desc:
      "Text from everything your currently enabled cuts above would keep. If you " +
      "used the AI outline edit mode, this is one chunk per outline paragraph/" +
      "sub-paragraph; otherwise it falls back to ~500-character chunks cut at cue " +
      'boundaries. Click "Generate with Piper" on a chunk for a free, local, offline ' +
      "voice-over (no API key, runs on this machine), or copy the text into any other TTS " +
      "tool and upload the result. Each chunk shows how many seconds of video it has to " +
      "fill, and the check tells you if the audio is too long for that slot. The text in " +
      "each chunk is editable — fix anything you want changed before copying or " +
      "generating, since that text is exactly what gets read aloud. Once a chunk has " +
      "audio (generated or uploaded), a player appears so you can listen right there.",
    generate_chunks_button: "Generate voice-over text chunks",
    chunks_status_building: "Building chunks...",
    chunks_status_result:
      "{count} chunk(s) — {kept} of {total} cues kept. {modeNote} " +
      "Toggling cuts above? Click this button again to refresh the chunks.",
    mode_note_outline: "One chunk per outline paragraph/sub-paragraph.",
    mode_note_fallback: "No outline found — using ~500-character chunks instead.",
    azure_usage_text:
      "Azure usage this month ({month}): {used} / {limit} characters ({pct}% of free tier).",
    cut_original_audio_label: "Cut the original audio track",
    add_music_label: "Add background music",
    volume_label: "Volume:",
    db_label: "dB",
    render_with_audio_button: "Render with custom audio",
    alert_add_music_check: 'Check "Add background music" and choose a music file, or uncheck it.',
    download_link_text: "Download edited video",

    chunk_label: "Chunk {n}",
    slot_label: "slot: {duration}s",
    copy_text_button: "Copy text",
    copy_button_copied: "Copied!",
    upload_voiceover_button: "Upload voice-over",
    alert_choose_audio_file: "Choose an audio file first.",
    audio_status_uploading: "Uploading...",
    audio_status_upload_failed: "Upload failed: {detail}",
    audio_fit_ok: "Fits — audio is {audio}s, slot is {slot}s.",
    audio_fit_overflow:
      "Too long — audio is {audio}s but the slot is only {slot}s ({overflow}s over). " +
      "Regenerate it shorter or it will be cut off.",
    generate_with_azure_button: "Generate with Azure (paid, counts toward quota)",
    generate_with_piper_button: "Generate with Piper (free, local)",
    audio_status_generating_azure: "Generating speech via Azure...",
    audio_status_generating_local: "Generating speech locally...",
    audio_status_generation_failed: "Generation failed: {detail}",

    render_status_done: "Done in {elapsed}s.",
    render_status_failed: "Failed: {error}",
    render_status_rendering_fallback: "Rendering...",
    render_status_progress:
      "{message} ({elapsed}s elapsed, re-encoding can take a while for long videos)",
  },

  ru: {
    header_subtitle: "Редактируйте видео, редактируя его транскрипт.",

    settings_button_title: "Настройки",
    settings_lang_label: "Язык интерфейса",

    step1_heading: "1. Вставьте ссылку на YouTube",
    step1_desc:
      "Приложение скачивает видео и расшифровывает его локально с помощью Whisper — " +
      "вручную скачивать и загружать субтитры не нужно. Выберите язык, на котором " +
      "действительно говорят в видео, для лучшей точности.",
    youtube_url_placeholder: "https://youtu.be/...",
    language_select_placeholder: "Выберите язык видео…",
    lang_option_english: "Английский",
    lang_option_russian: "Русский",
    lang_option_armenian: "Армянский",
    lang_option_spanish: "Испанский",
    lang_option_french: "Французский",
    lang_option_german: "Немецкий",
    lang_option_italian: "Итальянский",
    lang_option_portuguese: "Португальский",
    lang_option_ukrainian: "Украинский",
    lang_option_turkish: "Турецкий",
    lang_option_arabic: "Арабский",
    lang_option_hindi: "Хинди",
    lang_option_chinese: "Китайский",
    lang_option_japanese: "Японский",
    lang_option_korean: "Корейский",
    go_button: "Старт",

    alert_need_url: "Сначала вставьте ссылку на YouTube.",
    alert_need_language: "Пожалуйста, сначала выберите язык, на котором говорят в видео.",
    ingest_status_starting: "Запуск...",
    ingest_status_could_not_start: "Не удалось начать: {detail}",
    ingest_status_resuming: "Восстановление предыдущей сессии...",
    ingest_status_lost_track: "Проект потерян — вставьте ссылку заново.",
    ingest_status_working: "Выполняется...",
    ingest_status_elapsed: "{message} (прошло {elapsed} с)",
    ingest_status_cached_both: "Загружено из библиотеки (уже скачано и расшифровано).",
    ingest_status_cached_video: "Видео загружено из библиотеки, расшифровано за {elapsed} с.",
    ingest_status_transcribed: "Расшифровано за {elapsed} с.",
    ingest_status_transcript_load_failed:
      "Расшифровка завершена, но не удалось загрузить транскрипт.",
    ingest_status_failed: "Ошибка: {error}",
    video_info_restored: "Предыдущая сессия восстановлена — длительность {duration}",
    video_info_duration: "Длительность {duration}",

    step2_heading: "2. Выберите способ редактирования",
    edit_mode_manual_option: "Вручную — удаляйте части сами, без ИИ",
    edit_mode_outline_option: "ИИ-план — Claude структурирует + исправляет, вы выбираете что удалить",
    edit_mode_autonomous_option: "Автономный ИИ — Claude сам решает, что вырезать, по вашей инструкции",

    manual_desc:
      "Каждая реплика, распознанная Whisper, с точной временной меткой. Отметьте те, " +
      "которые нужно удалить, затем вырежьте их — без участия ИИ.",
    cut_selected_cues_button: "Вырезать отмеченные реплики",
    cues_status_loading: "Загрузка...",
    cues_status_count: "Реплик: {count}.",
    alert_need_video: "Сначала вставьте ссылку и дождитесь расшифровки видео.",
    alert_check_one_cue: "Сначала отметьте хотя бы одну реплику для удаления.",
    alert_could_not_build_cuts: "Не удалось создать вырезки из выбранного: {detail}",

    outline_desc_html:
      "В Claude Desktop (или в терминале <code>claude</code>) подключите/перейдите " +
      "(<code>cd</code>) в папку этого проекта. Нажмите «Скопировать сообщение для Claude» " +
      "ниже, вставьте его как первое сообщение и отправьте — сообщение указывает Claude " +
      "на файл <code>AI_EDITING_INSTRUCTIONS.md</code>, чтобы он сначала прочитал правила. " +
      "Он прочитает <code>workspace/subtitles.vtt</code> и запишет " +
      "<code>workspace/outline.md</code>: транскрипт, разбитый на тематические абзацы с " +
      "заголовками, с исправлением ошибок распознавания Whisper по ходу дела.",
    copy_message_button: "Скопировать сообщение для Claude",
    load_outline_button: "Загрузить план",
    outline_status_loading: "Загрузка...",
    outline_status_sections: "Разделов: {count}.",
    outline_status_empty: "outline.md пока пуст.",
    outline_note:
      "Каждый абзац/подабзац ниже показывает (возможно, исправленный) текст транскрипта " +
      "Claude для этого отрезка — отметьте галочкой любой абзац или подабзац, чтобы " +
      "пометить его на удаление, затем нажмите «Вырезать отмеченные разделы».",
    cut_selected_sections_button: "Вырезать отмеченные разделы",
    alert_check_one_section: "Сначала отметьте хотя бы один абзац или подабзац для удаления.",

    autonomous_desc_html:
      "Опишите желаемый результат в целом — например, «это видео на 40 минут, сократи " +
      "его примерно до 15, оставь только самое важное». Claude сам решит, что убрать. " +
      "Нажмите «Скопировать сообщение для Claude» и вставьте его в Claude Desktop/терминал; " +
      "он запишет для вас файл <code>workspace/cuts.md</code>.",
    autonomous_instruction_placeholder:
      "например: сократи примерно до 15 минут, оставь только самое важное",
    alert_need_instruction: "Сначала опишите желаемый результат.",
    load_cuts_file_button: "Загрузить вырезки из workspace/cuts.md",
    manual_fallback_summary: "Или вставьте ответ от другого ИИ вручную",
    manual_fallback_desc_html:
      "Вставьте полный структурированный ответ, полученный от ChatGPT (или другого ИИ) " +
      "после того, как вы дали ему <code>AI_EDITING_INSTRUCTIONS.md</code>, свою " +
      "инструкцию и транскрипт — включая раздел <code>## REMOVED</code>.",
    parse_cuts_button: "Разобрать вырезки",
    alert_paste_ai_reply: "Сначала вставьте ответ ИИ.",
    alert_parsing_failed: "Не удалось разобрать: {detail}",
    alert_could_not_load_cuts: "Не удалось загрузить workspace/cuts.md: {detail}",

    step3_heading: "3. Проверьте вырезки",
    table_header_start: "Начало",
    table_header_end: "Конец",
    table_header_duration: "Длит.",
    table_header_text_reason: "Текст / причина",
    summary_html:
      "Исходная длительность: <b>{original}</b> &nbsp;·&nbsp; " +
      "Найдено вырезок: <b>{count}</b> &nbsp;·&nbsp; " +
      "Удалено: <b>{removed}</b> &nbsp;·&nbsp; " +
      'Новая длительность (если все вырезки включены): <b id="newDuration">{newDuration}</b>',

    step4_heading: "4. Выберите звук и рендер",
    audio_mode_original_option: "Оригинальная дорожка — просто вырезать, сохранить реальный звук",
    audio_mode_auto_option: "Автоматическая озвучка — сгенерировать озвучку для каждого фрагмента автоматически",
    audio_mode_manual_option: "Ручная озвучка — редактируйте/генерируйте/загружайте озвучку для каждого фрагмента сами",

    audio_original_desc: "Оставляет оригинальную дорожку без изменений, без озвучки и музыки.",
    render_button: "Отрендерить готовое видео",
    alert_no_cuts_enabled:
      "Нет включённых вырезок — нечего удалять. Включите хотя бы одну вырезку, иначе рендерить нечего.",
    render_status_starting: "Запуск рендера...",
    render_status_failed_start: "Не удалось запустить рендер: {detail}",

    auto_tts_desc:
      "Генерирует озвучку для каждого фрагмента выбранным ниже голосом — Piper " +
      "(бесплатно, локально) или, если настроен, Azure (платно, выше качество). " +
      "Скорость (0.9x–1.1x) подбирается автоматически для каждого фрагмента, чтобы " +
      "озвучка заполнила своё окно. Для Azure каждый фрагмент сначала измеряется " +
      "бесплатным голосом Piper, поэтому фрагменты, которые не помещаются, в Azure не " +
      "отправляются. Слишком длинные фрагменты, а также оставляющие больше 5 секунд " +
      "тишины, показываются для исправления до продолжения рендера.",
    auto_tts_review_summary:
      "{bad} из {total} фрагмент(ов) требуют внимания, остальные готовы. Отредактируйте " +
      "текст и нажмите «Проверить» (сначала бесплатная проверка, Azure — только когда " +
      "помещается) или «Принять как есть». Затем «Продолжить рендер». Символов Azure за " +
      "этот запуск: {chars}.",
    auto_tts_review_all_ok:
      "Все {total} фрагмент(ов) готовы. Символов Azure за этот запуск: {chars}.",
    auto_tts_continue_button: "Продолжить рендер",
    auto_tts_recheck_button: "Проверить",
    auto_tts_accept_button: "Принять как есть",
    auto_tts_checking: "Проверка...",
    auto_tts_chars: "{n} символов",
    auto_tts_flag_too_long_estimate:
      "Слишком длинно — прогноз {est} с даже на {rate}x, а окно {slot} с. " +
      "Сократите примерно на {chars} символов.",
    auto_tts_flag_too_long_audio:
      "Слишком длинно — озвучка {audio} с на {rate}x, а окно {slot} с (превышение на " +
      "{over} с). Сократите примерно на {chars} символов или примите — конец будет обрезан.",
    auto_tts_flag_too_short_estimate:
      "Слишком коротко — прогноз {est} с даже на {rate}x, остаётся {gap} с тишины в окне " +
      "{slot} с. Добавьте примерно {chars} символов.",
    auto_tts_flag_too_short_audio:
      "Слишком коротко — озвучка {audio} с на {rate}x, остаётся {gap} с тишины в окне " +
      "{slot} с. Добавьте примерно {chars} символов или примите.",
    auto_tts_chunk_ok: "Подходит — {audio} с на {rate}x, окно {slot} с.",
    auto_tts_chunk_accepted: "Принято как есть — {audio} с на {rate}x, окно {slot} с.",
    auto_tts_unresolved: "Некоторые фрагменты всё ещё требуют внимания.",
    auto_tts_button: "Сгенерировать озвучку автоматически и отрендерить",
    tts_speed_label: "Скорость:",
    alert_no_voices:
      "Нет доступных голосов для озвучки — установите голосовую модель Piper, либо " +
      "настройте AZURE_SPEECH_KEY/AZURE_SPEECH_REGION для голосов Azure (см. инструкцию по установке).",
    auto_tts_status_starting: "Запуск автоматической озвучки...",
    auto_tts_status_failed: "Не удалось начать: {detail}",

    manual_tts_desc:
      "Текст из всего, что останется с учётом текущих включённых вырезок выше. Если вы " +
      "использовали режим редактирования «ИИ-план», это один фрагмент на абзац/подабзац " +
      "плана; иначе используются фрагменты примерно по 500 символов по границам реплик. " +
      "Нажмите «Сгенерировать с Piper» на фрагменте для бесплатной локальной офлайн-" +
      "озвучки (без API-ключа, работает на этой машине) или скопируйте текст в любой " +
      "другой инструмент озвучки и загрузите результат. Каждый фрагмент показывает, " +
      "сколько секунд видео ему нужно заполнить, а проверка покажет, не слишком ли длинная " +
      "озвучка для этого места. Текст каждого фрагмента можно редактировать — исправьте " +
      "всё, что нужно, перед копированием или генерацией, так как именно этот текст будет " +
      "озвучен. Как только у фрагмента появится озвучка (сгенерированная или загруженная), " +
      "появится плеер, чтобы прослушать её прямо здесь.",
    generate_chunks_button: "Сгенерировать текстовые фрагменты для озвучки",
    chunks_status_building: "Построение фрагментов...",
    chunks_status_result:
      "Фрагментов: {count} — сохранено {kept} из {total} реплик. {modeNote} " +
      "Изменили вырезки выше? Нажмите эту кнопку снова, чтобы обновить фрагменты.",
    mode_note_outline: "Один фрагмент на абзац/подабзац плана.",
    mode_note_fallback: "План не найден — используются фрагменты по ~500 символов.",
    azure_usage_text:
      "Использование Azure в этом месяце ({month}): {used} / {limit} символов ({pct}% бесплатного лимита).",
    cut_original_audio_label: "Убрать оригинальную звуковую дорожку",
    add_music_label: "Добавить фоновую музыку",
    volume_label: "Громкость:",
    db_label: "дБ",
    render_with_audio_button: "Отрендерить с собственным звуком",
    alert_add_music_check: "Отметьте «Добавить фоновую музыку» и выберите музыкальный файл, либо снимите галочку.",
    download_link_text: "Скачать готовое видео",

    chunk_label: "Фрагмент {n}",
    slot_label: "окно: {duration} с",
    copy_text_button: "Скопировать текст",
    copy_button_copied: "Скопировано!",
    upload_voiceover_button: "Загрузить озвучку",
    alert_choose_audio_file: "Сначала выберите аудиофайл.",
    audio_status_uploading: "Загрузка...",
    audio_status_upload_failed: "Не удалось загрузить: {detail}",
    audio_fit_ok: "Подходит — озвучка {audio} с, окно {slot} с.",
    audio_fit_overflow:
      "Слишком длинно — озвучка {audio} с, а окно всего {slot} с (превышение на {overflow} с). " +
      "Сгенерируйте короче, иначе будет обрезано.",
    generate_with_azure_button: "Сгенерировать через Azure (платно, расходует квоту)",
    generate_with_piper_button: "Сгенерировать через Piper (бесплатно, локально)",
    audio_status_generating_azure: "Генерация речи через Azure...",
    audio_status_generating_local: "Генерация речи локально...",
    audio_status_generation_failed: "Не удалось сгенерировать: {detail}",

    render_status_done: "Готово за {elapsed} с.",
    render_status_failed: "Ошибка: {error}",
    render_status_rendering_fallback: "Рендеринг...",
    render_status_progress:
      "{message} (прошло {elapsed} с, перекодирование длинных видео может занять время)",
  },
};

function getUiLanguage() {
  const saved = localStorage.getItem(UI_LANG_KEY);
  return saved && TRANSLATIONS[saved] ? saved : "en";
}

function t(key, vars) {
  const lang = getUiLanguage();
  let template = (TRANSLATIONS[lang] && TRANSLATIONS[lang][key]) || TRANSLATIONS.en[key] || key;
  if (vars) {
    for (const [name, value] of Object.entries(vars)) {
      template = template.replaceAll(`{${name}}`, String(value));
    }
  }
  return template;
}

function applyTranslations() {
  document.documentElement.lang = getUiLanguage();

  document.querySelectorAll("[data-i18n]").forEach((el) => {
    el.textContent = t(el.dataset.i18n);
  });
  document.querySelectorAll("[data-i18n-html]").forEach((el) => {
    el.innerHTML = t(el.dataset.i18nHtml);
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
    el.placeholder = t(el.dataset.i18nPlaceholder);
  });
  document.querySelectorAll("[data-i18n-title]").forEach((el) => {
    el.title = t(el.dataset.i18nTitle);
  });
}

function setUiLanguage(lang) {
  if (!TRANSLATIONS[lang]) return;
  localStorage.setItem(UI_LANG_KEY, lang);
  applyTranslations();
}

applyTranslations();
