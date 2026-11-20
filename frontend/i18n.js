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

    step_project_heading: "2. What do you want to make?",
    work_type_label: "Work type",
    work_type_revoice_option: "Re-voice edit — cut bloopers and voice the video with TTS",
    work_type_review_option: "Review of a review — quote the reviewer and add AI review parts",
    work_type_revoice_desc:
      "Cut what you don't need, optionally add new parts (intro, outro…), and voice the result " +
      "with text-to-speech or keep the original audio.",
    work_type_review_desc:
      "The video is someone else's review. You cut it down to the parts worth quoting, then " +
      "Claude writes your own review around them (\"he also talked about X — let's listen…\"). " +
      "The reviewer's parts play as quotes; the review parts are spoken by TTS, with footage " +
      "you pick from this video or other links.",
    output_language_label: "Output language",
    output_language_same_option: "Same as the video",
    output_language_russian_option: "Russian — Claude translates",
    output_language_same_desc: "Everything stays in the video's language ({lang}).",
    output_language_translate_desc:
      "Claude writes the outline, the kept text and every new part in {lang}. The edited video " +
      "is voiced in {lang} with TTS; manual cue-by-cue editing isn't available, because the " +
      "text has to be translated.",
    project_continue_button: "Continue",
    project_status_saved: "Saved. Claude reads these settings from workspace/project.md.",
    project_status_failed: "Could not save the settings: {detail}",
    translation_note_html:
      "Translating into <b>{lang}</b>: the AI outline is written in {lang}. With AI autonomous, " +
      "Claude first writes a {lang} outline and then cuts whole sections of it.",
    edit_mode_manual_unavailable: "Manual — not available when translating",
    step_review_heading: "5. AI review (required)",
    review_parts_desc_html:
      "Describe your review — what you agree or disagree with, what to add. Claude reads the " +
      "kept parts in <code>workspace/script.md</code> and writes your review parts to " +
      "<code>workspace/additions.md</code>: it introduces the reviewer's parts as quotes " +
      "(\"…let's listen to what he said\") and reacts after them. The reviewer's own words " +
      "are never changed. In the next step you pick the footage shown while your review is spoken.",
    review_parts_instruction_placeholder:
      "e.g. agree on the striking analysis, argue about the prediction, add recent facts",
    load_review_parts_button: "Load review parts",
    delete_outline_button: "Delete outline",
    confirm_delete_outline:
      "Delete the outline for this video and language? It's removed from the app's saved outlines too, so you'll need to ask Claude for a new one.",
    outline_status_deleted: "Outline deleted. Copy the message for Claude to get a new one.",
    outline_status_restored: "Restored the outline saved earlier for this video — no need to ask Claude again.",
    outline_status_saved_note: "Saved for this video: it comes back next time you open it.",
    review_status_script_written:
      "Wrote workspace/script.md ({count} sections to quote). Paste the copied message into Claude, then click \"Load review parts\".",
    alert_need_review_instruction: "Describe your review first (what to agree on, argue about, add).",
    original_audio_label: "Speaker's real voice",
    original_audio_replace_option: "Replace — voice everything with TTS",
    original_audio_under_option: "Keep quieter under the TTS (voice-over translation)",
    original_audio_keep_option: "Keep as is — voice only the new parts",
    audio_mode_original_unavailable: "Original audio — not available for this project",
    auto_tts_own_voice: "His own voice — not voiced.",

    step2_heading: "3. Choose how to edit",
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

    step3_heading: "4. Review cuts",
    table_header_start: "Start",
    table_header_end: "End",
    table_header_duration: "Dur.",
    table_header_text_reason: "Text / reason",
    summary_html:
      "Original duration: <b>{original}</b> &nbsp;·&nbsp; " +
      "Cuts found: <b>{count}</b> &nbsp;·&nbsp; " +
      "Removed: <b>{removed}</b> &nbsp;·&nbsp; " +
      'New duration (if all cuts kept enabled): <b id="newDuration">{newDuration}</b>',

    step_add_heading: "5. Add new parts (optional)",
    add_parts_desc_html:
      "Ask Claude to write new spoken parts on top of the edited text — an intro, an outro, " +
      "recent news about the person… Your existing text stays exactly as it is: Claude only " +
      "writes the new parts to <code>workspace/additions.md</code>, each placed before or " +
      "after one section. They get a voice-over like everything else, and in the next step you " +
      "can pick the footage shown while each one is spoken.",
    add_parts_instruction_placeholder: "e.g. add a short intro, an outro, and his latest news",
    load_additions_button: "Load new parts",
    skip_add_parts_button: "Skip this step",
    continue_add_parts_button: "Continue",
    back_to_add_parts_button: "← Add new parts",
    alert_need_add_instruction: "Describe what to add first (e.g. an intro and an outro).",
    additions_status_script_written:
      "Wrote workspace/script.md ({count} sections). Paste the copied message into Claude, then click \"Load new parts\".",
    additions_status_script_failed: "Could not write the script for Claude: {detail}",
    additions_status_loading: "Loading new parts…",
    additions_status_loaded: "Loaded {count} new part(s).",
    additions_status_failed: "Could not load new parts: {detail}",
    additions_position_before: "before §{n} {title}",
    additions_position_after: "after §{n} {title}",
    added_tag: "NEW",
    added_time_label: "inserted at {time}",
    added_slot_label: "length = its voice-over",
    added_audio_result: "Voice-over is {audio}s — the video pauses this long for this new part.",
    additions_audio_note:
      "{count} new part(s) included. They're spoken only with Automatic or Manual TTS; " +
      "\"Original audio\" renders without them.",

    broll_heading: "6. Video for new parts (optional)",
    broll_desc:
      "While a new part is spoken, the edited video pauses. Pick what's shown during that pause: " +
      "parts of the main video, or of any other YouTube video you add here. Only the picture is " +
      "used — the voice-over is the sound. Drag the window on the timeline to choose a part, drag " +
      "its edges to change its length, and add as many clips as you like. Anything not filled " +
      "holds the last frame.",
    broll_url_placeholder: "Paste another YouTube link…",
    broll_add_source_button: "+ Add video",
    broll_continue_button: "Continue to audio",
    broll_source_main: "Main video",
    broll_source_downloading: "downloading… {pct}%",
    broll_source_failed: "failed",
    broll_remove_source_title: "Remove this video and its clips",
    broll_loading: "Measuring the new parts…",
    broll_load_failed: "Could not load the footage picker: {detail}",
    broll_needs: "≈ {seconds}s to fill",
    broll_filled: "{filled}s of {needed}s filled",
    broll_filled_over: "{filled}s picked for ≈ {needed}s — the end is trimmed to the voice-over",
    broll_no_clips: "No footage yet — the video holds a still frame.",
    broll_choose_button: "Choose footage",
    broll_close_button: "Done",
    broll_add_clip_button: "Add this clip",
    broll_play_selection: "▶ Play window",
    broll_pause: "❚❚ Pause",
    broll_length_label: "Length",
    broll_fill_rest_button: "Fill the rest",
    broll_zoom_in_title: "Zoom in (or scroll on the timeline)",
    broll_zoom_out_title: "Zoom out",
    broll_zoom_fit_title: "Show the whole video",
    broll_keys_hint: "←/→ move 0.1s · Shift+←/→ 1s · Space play · Enter add",
    broll_source_not_ready: "This video is still downloading.",
    broll_clip_preview_title: "Show in the picker",
    broll_clip_up_title: "Play earlier",
    broll_clip_down_title: "Play later",
    broll_clip_remove_title: "Remove clip",
    broll_save_failed: "Could not save clips: {detail}",
    broll_add_source_failed: "Could not add the video: {detail}",
    alert_need_broll_url: "Paste a YouTube link first.",

    step4_heading: "7. Choose audio & render",
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
      "in the {slot}s window. Add about {chars} characters, make pauses longer (||3), or accept it.",
    auto_tts_pauses_note: "Voiced in {parts} parts with pauses (the ||seconds marks in the text).",
    auto_tts_pause_help_html:
      "Pauses: <code>||</code> in the text = pause here (length picked automatically), " +
      "<code>||3</code> = pause exactly 3 seconds (<code>||1.5</code> works too). They're never read aloud. " +
      "When a voice-over is too short for its window, it's voiced in parts with pauses, and the pauses " +
      "it made are written into the text like this — change the numbers and click Recheck.",
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

    step_project_heading: "2. Что вы хотите сделать?",
    work_type_label: "Тип работы",
    work_type_revoice_option: "Переозвучка — вырезать лишнее и озвучить видео TTS",
    work_type_review_option: "Обзор обзора — цитировать автора и добавить обзор от ИИ",
    work_type_revoice_desc:
      "Вырежьте ненужное, при желании добавьте новые части (вступление, концовку…) и озвучьте " +
      "результат синтезом речи или оставьте оригинальный звук.",
    work_type_review_desc:
      "Видео — чужой обзор. Вы оставляете части, которые стоит процитировать, а Claude пишет ваш " +
      "собственный обзор вокруг них («он также говорил о X — давайте послушаем…»). Части автора " +
      "звучат как цитаты, части обзора озвучивает TTS, с видеорядом, который вы выбираете из " +
      "этого видео или других ссылок.",
    output_language_label: "Язык результата",
    output_language_same_option: "Как в видео",
    output_language_russian_option: "Русский — Claude переводит",
    output_language_same_desc: "Всё остаётся на языке видео ({lang}).",
    output_language_translate_desc:
      "Claude пишет структуру, оставленный текст и все новые части на языке: {lang}. Видео " +
      "озвучивается синтезом речи; ручное редактирование по репликам недоступно, потому что " +
      "текст нужно перевести.",
    project_continue_button: "Продолжить",
    project_status_saved: "Сохранено. Claude читает эти настройки из workspace/project.md.",
    project_status_failed: "Не удалось сохранить настройки: {detail}",
    translation_note_html:
      "Перевод на язык <b>{lang}</b>: структура ИИ пишется на этом языке. В автономном режиме " +
      "Claude сначала пишет структуру на этом языке, а затем вырезает её разделы целиком.",
    edit_mode_manual_unavailable: "Вручную — недоступно при переводе",
    step_review_heading: "5. Обзор от ИИ (обязательно)",
    review_parts_desc_html:
      "Опишите ваш обзор — с чем вы согласны или не согласны, что добавить. Claude читает " +
      "оставленные части в <code>workspace/script.md</code> и пишет части обзора в " +
      "<code>workspace/additions.md</code>: представляет части автора как цитаты («…давайте " +
      "послушаем, что он сказал») и реагирует после них. Слова автора никогда не меняются. " +
      "На следующем шаге вы выберете видеоряд для частей обзора.",
    review_parts_instruction_placeholder:
      "например: согласиться с разбором ударки, поспорить с прогнозом, добавить свежие факты",
    load_review_parts_button: "Загрузить части обзора",
    delete_outline_button: "Удалить структуру",
    confirm_delete_outline:
      "Удалить структуру для этого видео и языка? Она удалится и из сохранённых в приложении, и нужно будет снова просить Claude.",
    outline_status_deleted: "Структура удалена. Скопируйте сообщение для Claude, чтобы получить новую.",
    outline_status_restored: "Восстановлена сохранённая ранее структура этого видео — просить Claude снова не нужно.",
    outline_status_saved_note: "Сохранена для этого видео: в следующий раз она загрузится сама.",
    review_status_script_written:
      "Записан workspace/script.md (разделов для цитирования: {count}). Вставьте скопированное сообщение в Claude, затем нажмите «Загрузить части обзора».",
    alert_need_review_instruction: "Сначала опишите ваш обзор (с чем согласиться, о чём поспорить, что добавить).",
    original_audio_label: "Настоящий голос автора",
    original_audio_replace_option: "Заменить — озвучить всё TTS",
    original_audio_under_option: "Оставить тише под TTS (закадровый перевод)",
    original_audio_keep_option: "Оставить как есть — озвучить только новые части",
    audio_mode_original_unavailable: "Оригинальная дорожка — недоступно для этого проекта",
    auto_tts_own_voice: "Его собственный голос — не озвучивается.",

    step2_heading: "3. Выберите способ редактирования",
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

    step3_heading: "4. Проверьте вырезки",
    table_header_start: "Начало",
    table_header_end: "Конец",
    table_header_duration: "Длит.",
    table_header_text_reason: "Текст / причина",
    summary_html:
      "Исходная длительность: <b>{original}</b> &nbsp;·&nbsp; " +
      "Найдено вырезок: <b>{count}</b> &nbsp;·&nbsp; " +
      "Удалено: <b>{removed}</b> &nbsp;·&nbsp; " +
      'Новая длительность (если все вырезки включены): <b id="newDuration">{newDuration}</b>',

    step_add_heading: "5. Добавить новые части (необязательно)",
    add_parts_desc_html:
      "Попросите Claude написать новые части поверх отредактированного текста — вступление, " +
      "заключение, последние новости о герое… Ваш текст остаётся без изменений: Claude пишет " +
      "только новые части в <code>workspace/additions.md</code>, каждую перед или после одного " +
      "раздела. Они озвучиваются как и всё остальное, а на следующем шаге можно выбрать, какое " +
      "видео показывать, пока звучит каждая из них.",
    add_parts_instruction_placeholder: "например: добавь короткое вступление, заключение и его последние новости",
    load_additions_button: "Загрузить новые части",
    skip_add_parts_button: "Пропустить этот шаг",
    continue_add_parts_button: "Продолжить",
    back_to_add_parts_button: "← Добавить новые части",
    alert_need_add_instruction: "Сначала опишите, что добавить (например, вступление и заключение).",
    additions_status_script_written:
      "Записан workspace/script.md ({count} разделов). Вставьте скопированное сообщение в Claude, затем нажмите «Загрузить новые части».",
    additions_status_script_failed: "Не удалось записать текст для Claude: {detail}",
    additions_status_loading: "Загрузка новых частей…",
    additions_status_loaded: "Загружено новых частей: {count}.",
    additions_status_failed: "Не удалось загрузить новые части: {detail}",
    additions_position_before: "перед §{n} {title}",
    additions_position_after: "после §{n} {title}",
    added_tag: "НОВОЕ",
    added_time_label: "вставка в {time}",
    added_slot_label: "длина = озвучка",
    added_audio_result: "Озвучка {audio} с — на столько видео остановится для этой новой части.",
    additions_audio_note:
      "Включено новых частей: {count}. Они озвучиваются только в режимах «Автоматическая озвучка» " +
      "или «Ручная озвучка»; «Оригинальная дорожка» рендерится без них.",

    broll_heading: "6. Видео для новых частей (необязательно)",
    broll_desc:
      "Пока звучит новая часть, отредактированное видео стоит на паузе. Выберите, что показывать " +
      "в это время: фрагменты основного видео или любого другого видео с YouTube, добавленного " +
      "здесь. Берётся только картинка — звук даёт озвучка. Перетаскивайте окно по шкале времени, " +
      "чтобы выбрать фрагмент, тяните его края, чтобы изменить длину, и добавляйте сколько угодно " +
      "клипов. Незаполненное время держит последний кадр.",
    broll_url_placeholder: "Вставьте ещё одну ссылку YouTube…",
    broll_add_source_button: "+ Добавить видео",
    broll_continue_button: "Перейти к звуку",
    broll_source_main: "Основное видео",
    broll_source_downloading: "загрузка… {pct}%",
    broll_source_failed: "ошибка",
    broll_remove_source_title: "Убрать это видео и его клипы",
    broll_loading: "Измеряю длину новых частей…",
    broll_load_failed: "Не удалось открыть выбор видео: {detail}",
    broll_needs: "≈ {seconds} с заполнить",
    broll_filled: "заполнено {filled} с из {needed} с",
    broll_filled_over: "выбрано {filled} с на ≈ {needed} с — конец обрежется по озвучке",
    broll_no_clips: "Видео пока не выбрано — будет стоп-кадр.",
    broll_choose_button: "Выбрать видео",
    broll_close_button: "Готово",
    broll_add_clip_button: "Добавить этот клип",
    broll_play_selection: "▶ Проиграть окно",
    broll_pause: "❚❚ Пауза",
    broll_length_label: "Длина",
    broll_fill_rest_button: "Заполнить остаток",
    broll_zoom_in_title: "Приблизить (или прокрутите колесо над шкалой)",
    broll_zoom_out_title: "Отдалить",
    broll_zoom_fit_title: "Показать всё видео",
    broll_keys_hint: "←/→ сдвиг 0,1 с · Shift+←/→ 1 с · Пробел — воспроизвести · Enter — добавить",
    broll_source_not_ready: "Это видео ещё загружается.",
    broll_clip_preview_title: "Показать в выборе",
    broll_clip_up_title: "Раньше",
    broll_clip_down_title: "Позже",
    broll_clip_remove_title: "Удалить клип",
    broll_save_failed: "Не удалось сохранить клипы: {detail}",
    broll_add_source_failed: "Не удалось добавить видео: {detail}",
    alert_need_broll_url: "Сначала вставьте ссылку YouTube.",

    step4_heading: "7. Выберите звук и рендер",
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
      "{slot} с. Добавьте примерно {chars} символов, удлините паузы (||3) или примите.",
    auto_tts_pauses_note: "Озвучено в {parts} частях с паузами (метки ||секунды в тексте).",
    auto_tts_pause_help_html:
      "Паузы: <code>||</code> в тексте — пауза здесь (длина подбирается автоматически), " +
      "<code>||3</code> — пауза ровно 3 секунды (<code>||1.5</code> тоже можно). Они не читаются вслух. " +
      "Если озвучка короче своего окна, она озвучивается частями с паузами, и сделанные паузы " +
      "записываются в текст в таком виде — измените числа и нажмите «Проверить».",
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
