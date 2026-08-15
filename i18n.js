/* ════════════════════════════════════════════════════════════════
   Shared zh-Hant / English toggle for LoudMaster's two pages.

   Loaded as a plain (non-module) <script src="i18n.js"> in <head>, on
   both index.html and help.html, so it runs and executes synchronously
   before the rest of the page parses. Two jobs, split by timing:

   1. Immediately (top of this file, before <body> even exists): read
      the stored language and, if it's "en", mark <html> so the page's
      own CSS (`html.i18n-pending body{visibility:hidden}`) hides the
      body until the real translation pass has run — otherwise the
      zh-Hant text baked into the HTML would flash for a frame before
      JS replaces it. Nothing to do for the zh case since that's what
      the raw HTML already shows.
   2. Once the DOM exists — each page calls initSmI18n() itself, after
      its own markup and script are in place — walk data-i18n /
      data-i18n-attr / data-i18n-html elements, update <title>/meta
      tags, wire the #langToggle button, and reveal the page.

   Storage key is shared across all four sibling tools + the hub
   (same-origin subpaths), so a visitor's choice carries over between
   tools and between index.html/help.html of this one.
   ════════════════════════════════════════════════════════════════ */

var SM_LANG_KEY = "sm_lang";

function getStoredLang() {
  try { return localStorage.getItem(SM_LANG_KEY) === "en" ? "en" : "zh"; }
  catch (e) { return "zh"; }
}

(function () {
  var lang = getStoredLang();
  document.documentElement.lang = lang === "en" ? "en" : "zh-Hant";
  if (lang === "en") document.documentElement.classList.add("i18n-pending");
})();

var I18N = {
  zh: {
    // ── meta / head (both pages) ──
    meta_title: "LoudMaster — 影片音量一鍵調到 YouTube 標準",
    meta_desc: "直接在瀏覽器裡把影片或音樂調到 YouTube 標準響度,不破音、不改變畫質。不用安裝任何東西,檔案也不會上傳到伺服器。",
    og_locale: "zh_TW",
    meta_help_title: "說明 — LoudMaster",
    meta_help_desc: "LoudMaster 怎麼運作、平台目標列表、常見問題。",

    // ── header (both pages) ──
    header_home_label: "首頁",
    header_home_aria: "回首頁",
    header_theme_title: "切換淺色 / 深色",
    header_theme_aria: "切換淺色或深色主題",
    help_theme_aria: "切換主題",
    header_help_link: "說明",
    help_back_link: "返回",
    lang_switch_to_en: "切換為英文",
    lang_switch_to_zh: "切換為中文",

    // ── index.html: empty state ──
    empty_aria: "載入影片或音樂檔",
    empty_title: "點擊這裡載入影片或音樂檔案",
    empty_sub: "支援 MP4 / MOV / WebM / MP3 / WAV 等常見格式",
    empty_learn_more: "或先看看它是怎麼運作的 →",
    empty_privacy: "全程在瀏覽器裡處理,檔案不會上傳到伺服器",
    empty_engine_bar_aria: "處理引擎下載進度",
    empty_engine_loading: "準備處理引擎中…",

    // ── index.html: ready state ──
    ready_meta_loading: "讀取中…",
    file_meta_loaded: "已載入",
    ready_preset_label: "響度目標",
    preset_youtube_opt: "YouTube（-14 LUFS / -1 dBTP）",
    preset_spotify_opt: "Spotify（-14 LUFS / -1 dBTP）",
    preset_tiktok_opt: "TikTok / Instagram（-14 LUFS / -1 dBTP）",
    preset_apple_opt: "Apple Music / Podcasts（-16 LUFS / -1 dBTP）",
    preset_broadcast_opt: "廣播電視 EBU R128（-23 LUFS / -1 dBTP）",
    preset_custom_opt: "自訂目標…",
    preset_youtube_note: "YouTube 播放時只會把過響的影片轉小聲,不會把小聲的轉大聲。",
    preset_spotify_note: "Spotify 預設的 Normal 音量模式目標。",
    preset_tiktok_note: "手機短影音平台實測的正規化目標。",
    preset_apple_note: "Apple 的 Sound Check 目標。",
    preset_broadcast_label: "廣播電視 EBU R128",
    preset_broadcast_note: "歐洲廣播規範 EBU R128 的交件標準。",
    preset_custom_label: "自訂",
    preset_target_hint: "目標：{i} LUFS / {tp} dBTP",
    preset_target_high_warn: "　響度目標偏高，成品可能需要較多限幅甚至無法完全達標。",
    ready_custom_lufs_label: "整合響度（LUFS）",
    ready_custom_tp_label: "真實峰值上限（dBTP）",
    ready_denoise_label: "降噪比較（選用）",
    ready_denoise_hint: "會保留原始與降噪兩版，可先 A/B 比較再決定下載哪個；降噪偏保守、不易變悶，但處理時間較長。",
    ready_choose_another: "換一個檔案",
    ready_start: "開始處理",
    file_size_warn: "這個檔案超過 500 MB。瀏覽器版沒有安裝限制，但影片全部要載入記憶體處理，大檔案可能會很慢或讓分頁當掉。建議先用較短的片段測試。",

    // ── index.html: working state ──
    working_warn_title: "請讓這個分頁保持在最前面",
    working_warn_body: "切到其他分頁、鎖定螢幕，處理可能會被瀏覽器暫停，需要重新開始。",
    working_caption: "處理時間依裝置效能而不同，完成後會自動顯示成品。",
    working_cancel_aria: "取消處理",
    working_cancel_title: "取消",
    working_cancel_label: "取消",
    working_log_show: "顯示詳細記錄",
    working_log_hide: "隱藏詳細記錄",

    // ── index.html: done state ──
    done_variant_plain: "原始版",
    done_variant_denoised: "降噪版",
    done_stat_lufs_label: "整合響度",
    done_stat_tp_label: "真實峰值",
    done_reset: "處理另一個",
    done_download: "下載成品",
    done_reprocess: "換個目標重新處理這個檔案",
    done_chart_show: "顯示響度曲線",
    done_chart_hide: "隱藏響度曲線",
    done_chart_head: "成品響度隨時間變化",
    done_report: "下載響度報告（JSON）",

    // ── index.html: error state / footer ──
    error_default: "發生錯誤。",
    error_retry: "再試一次",
    footer_loading: "正在載入處理引擎…",

    // ── index.html: engine loading / errors (runtime) ──
    engine_load_code: "載入處理引擎程式…",
    engine_load_code_timeout_label: "載入引擎程式",
    engine_download_core_label: "下載引擎程式",
    engine_download_wasm_label: "下載引擎核心",
    engine_start_label: "啟動引擎",
    engine_download_core_progress: "下載處理引擎程式…",
    engine_download_wasm_progress: "下載處理引擎…",
    engine_start_progress: "啟動處理引擎…",
    engine_ready: "處理引擎已就緒",
    engine_no_source: "連不上處理引擎。",
    engine_source_n: "來源 {n}：{msg}",
    engine_timeout: "{label}逾時（超過 {sec} 秒沒有回應）",
    engine_download_fail: "下載失敗（HTTP {status}）：{url}",
    engine_load_failed_title: "處理引擎載入失敗。",
    engine_retry: "重試",
    engine_load_failed_full: "處理引擎載入失敗。\n\n詳細原因：\n{reason}\n\n可以檢查網路連線，或把這段文字截圖回報。",
    engine_no_wasm_text: "此瀏覽器不支援 WebAssembly，無法使用此工具",
    engine_no_wasm_status: "此瀏覽器不支援 WebAssembly",

    // ── index.html: file handling (runtime) ──
    probe_fail: "無法讀取這個檔案,可能不是有效的影片或音訊檔。",
    measure_fail: "量測失敗,無法解析響度資訊。",
    silence_fail: "這個檔案的音訊是(接近)無聲,無法計算需要提升多少音量。",
    render_output_stage: "輸出成品",
    render_correct_stage: "修正峰值（第 {n} 次）",
    render_verify_stage: "驗證成品",
    file_not_media: "這個檔案看起來不是影片或音訊。請確認檔案格式。",
    file_meta_reading: "{size} MB · 讀取中…",
    file_surround: "環繞音效",
    file_no_audio: "這個檔案沒有偵測到音軌，無法調整音量。",
    file_read_error: "讀取檔案時發生錯誤。",

    // ── index.html: processing (runtime) ──
    proc_analyze_stage: "分析原始響度",
    proc_unsupported_codec: "目前不支援輸出 {codec} 編碼的影像。\n請改用支援 H.264 / VP9 的影片，或使用進階版（Python 命令列工具）。",
    proc_generic_error: "處理時發生錯誤，請再試一次。",
    proc_chart_stage: "分析響度變化",
    proc_done_stage: "完成",
    variant_denoise_label: "（降噪版）",
    variant_denoise_full_label: "（降噪版，完整影片）",
    variant_gain_up: "提升",
    variant_gain_down: "降低",
    variant_note_gain: "{dir} {db} dB",
    variant_note_limiter: "，其中部分經過真實峰值限幅器處理",
    variant_note_pure_gain: "（純增益，不改變音質）",
    variant_note_video_kept: "。影像已原封不動保留，未重新編碼。",
    variant_note_preview_only: "。畫面沿用原始版預覽，這裡只是比較聲音；下載時才會產生這個版本專屬的完整影片。",
    variant_note_lossless_wav: "。輸出為無損 24-bit WAV。",
    variant_note_surround: "依 ITU-R BS.1770 對 {layout} 環繞聲道加權量測，非只取前左右聲道。",
    variant_note_denoised: "已套用保守降噪。",
    variant_warn_shortfall: "這段素材峰值偏高（可能有爆音或碰撞聲），完全達標需要更多限幅，因此成品會比目標小聲約 {db} dB，避免聲音被壓得太扁。",
    download_building_video: "產生完整影片中…",
    download_rebuild_fail: "產生完整影片時發生錯誤，請再試一次。",
    share_read_fail: "讀取檔案失敗",

    // ── help.html ──
    help_h2_how: "它是怎麼運作的",
    help_principle_html: "<strong>能用純增益解決的，就絕不做動態處理。</strong>先量測整段音訊，算出需要多少 dB，確認這個增益不會讓峰值超標，然後就只做「乘上一個固定數字」這一件事——數學上完全透明，音色、動態、立體聲相位、瞬態全部原封不動，只是變大聲。",
    help_limiter_note_html: "只有在<strong>峰值真的不夠用</strong>的時候（例如素材裡有爆音、拍打聲），才會啟用真實峰值限幅器，而且只用在「差的那幾 dB」，成品做完後會再重新量一次確認真的達標。",
    help_h3_flow: "流程",
    help_flow_1_html: "<strong>量測</strong>依 ITU-R BS.1770 / EBU R128 量測整合響度與真實峰值。",
    help_flow_2_html: "<strong>決定</strong>算出需要幾 dB。峰值餘裕夠就純增益結束；不夠才動用限幅。",
    help_flow_3_html: "<strong>輸出並驗證</strong>影像串流直接複製，音訊套用增益後編碼。做完立刻重新量測成品，如果峰值還是超標會自動修正增益、重跑一次——這個保證來自實測的數字，不是假設安全邊際一定夠。",
    help_h3_quality: "畫質完全不變",
    help_quality_p: "影像軌是直接複製，從頭到尾沒有解碼、沒有重新編碼。可以自己驗證：來源與成品的影像串流MD5 完全相同。",
    help_md5_snippet: "ffmpeg -i 原始.mp4 -map 0:v -c copy -f md5 -\nffmpeg -i 成品.mp4 -map 0:v -c copy -f md5 -",
    help_h3_why_minus1: "為什麼峰值上限是 -1 dBTP，而不是 0",
    help_why_minus1_p: "數位訊號的取樣點之間還有波形。播放器把它還原成類比、或平台把它轉成 AAC/Opus 時，還原出來的波形峰值會比原本的取樣點更高。留 1 dB 餘裕，就是為了讓這個「還原後的超出量」不至於在觀眾的裝置上削波。這是所有串流平台交件規範的共同做法。",

    help_h2_platforms: "支援的平台",
    help_th_platform: "平台",
    help_th_target: "目標",
    help_row_broadcast: "廣播電視 EBU R128",
    help_row_custom: "自訂目標",
    help_row_custom_desc: "自行輸入 LUFS（-70 ～ -5）與真實峰值上限",
    help_platforms_note: "如果平台不在清單上，或有特定交件規範，選「自訂目標…」自己輸入數字即可，運作方式完全相同。",

    help_h2_faq: "常見問題",
    faq_q1: "處理完還是比別人的影片小聲？",
    faq_a1: "如果出現「比目標小聲」的提示，代表素材裡有少數非常大聲的瞬間（爆麥、拍桌、碰撞聲），把整體音量「頂住」了。回去剪掉／修掉那幾個突波是最好的做法——限幅器能做的事有限，再多聲音會明顯變扁。",
    faq_q2: "為什麼影片輸出是 AAC？這不是有損嗎？",
    faq_a2: "是。改變音量必然要重新編碼音訊，這一步無法避免。瀏覽器版統一輸出 AAC／Opus，實務上聽不出差異。",
    faq_q3: "純音訊檔案為什麼輸出的是 WAV？",
    faq_a3: "WAV 是無損格式，瀏覽器版對音訊檔一律輸出 24-bit 無損 WAV（並套用三角形高通 dither，避免降低位元深度時產生的量化雜訊），確保「不改變音質」這個承諾百分之百成立。",
    faq_q4: "可以順便降噪嗎？",
    faq_a4: "可以。就緒畫面有一個「降噪比較（選用）」勾選框，預設不開；開啟後會同時處理原始與降噪兩版，完成後可以 A/B 聽過再決定下載哪個。降噪偏保守，適合底噪、電流聲、風聲這類穩定的雜訊，很吵或不規則的雜訊沒辦法完全去除，且因為要處理兩次，時間會比平常長。影片檔比較時降噪版只有聲音、沒有畫面（避免手機同時載入兩份完整影片），下載時才會補上完整畫面。",
    faq_q5: "可以自己輸入目標響度嗎？",
    faq_a5: "可以。平台選單選「自訂目標…」，就能自行輸入整合響度（LUFS）與真實峰值上限（dBTP），運作方式和選預設平台完全相同，一樣是先量測、算出增益，不夠才動用限幅。",
    faq_q6: "5.1 環繞聲道的影片也能處理嗎？",
    faq_a6: "可以。量測時會依 ITU-R BS.1770 對環繞聲道正確加權（不是只看前左右兩聲道），聲道數與空間定位也會完整保留，處理前後只有整體音量不同。",
    faq_q7: "可以匯出處理紀錄嗎？",
    faq_a7: "處理完成後可以下載一份 JSON 格式的響度報告，記錄處理前後的 LUFS／真實峰值、使用的目標、是否動用限幅等資訊，方便存檔或交給後製團隊核對。",
    faq_q8: "怎麼知道素材裡響度有沒有忽大忽小？",
    faq_a8: "完成畫面可以展開「顯示響度曲線」，看整段素材處理前後的響度隨時間變化，方便確認有沒有某幾段特別大聲或特別小聲。",
    faq_q9: "檔案不會被上傳到哪裡吧？",
    faq_a9: "不會。整個處理過程用的是 WebAssembly 版的 ffmpeg，直接在你的瀏覽器裡執行，檔案從頭到尾只存在你的裝置記憶體裡，沒有任何網路上傳。這也是為什麼瀏覽器分頁關掉、處理就會中斷——沒有伺服器在背景繼續幫你跑。",
    faq_q10: "影片很大或很長，處理很慢或分頁當掉怎麼辦？",
    faq_a10: "瀏覽器版沒有硬性大小限制，但影片會整個載入記憶體處理，沒有串流機制，裝置效能與可用記憶體是實際上限。建議以短片（幾分鐘、幾百 MB 內）為主，或先用短片段測試看看。",
    faq_q11: "我的影片格式顯示不支援怎麼辦？",
    faq_a11: "目前支援 H.264／HEVC（輸出 MP4）與 VP8／VP9／AV1（輸出 WebM）的影片，涵蓋絕大多數手機錄影與網路影片。遇到其他格式，建議先用其他工具轉成 MP4 或 WebM 再上傳。"
  },

  en: {
    meta_title: "LoudMaster — One-Click Loudness for YouTube",
    meta_desc: "Normalize video or music loudness to YouTube's standard right in your browser — no clipping, no quality loss. Nothing to install, and files never leave your device.",
    og_locale: "en_US",
    meta_help_title: "Help — LoudMaster",
    meta_help_desc: "How LoudMaster works, the platform target list, and frequently asked questions.",

    header_home_label: "Home",
    header_home_aria: "Back to hub",
    header_theme_title: "Switch light / dark",
    header_theme_aria: "Toggle light or dark theme",
    help_theme_aria: "Toggle theme",
    header_help_link: "Help",
    help_back_link: "Back",
    lang_switch_to_en: "Switch to English",
    lang_switch_to_zh: "Switch to Chinese",

    empty_aria: "Load a video or audio file",
    empty_title: "Click to load a video or audio file",
    empty_sub: "Supports MP4, MOV, WebM, MP3, WAV, and more",
    empty_learn_more: "Or see how it works first →",
    empty_privacy: "Everything runs in your browser — files are never uploaded",
    empty_engine_bar_aria: "Processing engine download progress",
    empty_engine_loading: "Preparing processing engine…",

    ready_meta_loading: "Reading…",
    file_meta_loaded: "Loaded",
    ready_preset_label: "Loudness target",
    preset_youtube_opt: "YouTube (-14 LUFS / -1 dBTP)",
    preset_spotify_opt: "Spotify (-14 LUFS / -1 dBTP)",
    preset_tiktok_opt: "TikTok / Instagram (-14 LUFS / -1 dBTP)",
    preset_apple_opt: "Apple Music / Podcasts (-16 LUFS / -1 dBTP)",
    preset_broadcast_opt: "Broadcast EBU R128 (-23 LUFS / -1 dBTP)",
    preset_custom_opt: "Custom target…",
    preset_youtube_note: "YouTube only turns down over-loud videos on playback — it never turns quiet ones up.",
    preset_spotify_note: "Spotify's default Normal volume mode target.",
    preset_tiktok_note: "Target measured in practice on short-form mobile platforms.",
    preset_apple_note: "Apple's Sound Check target.",
    preset_broadcast_label: "Broadcast EBU R128",
    preset_broadcast_note: "The European broadcast standard EBU R128 delivery spec.",
    preset_custom_label: "Custom",
    preset_target_hint: "Target: {i} LUFS / {tp} dBTP",
    preset_target_high_warn: " Target is quite high — the result may need heavy limiting, or might not fully reach it.",
    ready_custom_lufs_label: "Integrated loudness (LUFS)",
    ready_custom_tp_label: "True peak ceiling (dBTP)",
    ready_denoise_label: "Denoise comparison (optional)",
    ready_denoise_hint: "Keeps both a plain and a denoised version so you can A/B them before choosing which to download; denoising is conservative and won't sound muffled, but takes longer to process.",
    ready_choose_another: "Choose another file",
    ready_start: "Start processing",
    file_size_warn: "This file is over 500 MB. There's no install-size limit in the browser version, but the whole video has to load into memory to process, so large files may be slow or crash the tab. Try a shorter clip first.",

    working_warn_title: "Keep this tab in the foreground",
    working_warn_body: "Switching tabs or locking your screen may make the browser pause processing, forcing a restart.",
    working_caption: "Processing time depends on your device; the result appears automatically when done.",
    working_cancel_aria: "Cancel processing",
    working_cancel_title: "Cancel",
    working_cancel_label: "Cancel",
    working_log_show: "Show details",
    working_log_hide: "Hide details",

    done_variant_plain: "Plain",
    done_variant_denoised: "Denoised",
    done_stat_lufs_label: "Integrated loudness",
    done_stat_tp_label: "True peak",
    done_reset: "Process another",
    done_download: "Download result",
    done_reprocess: "Reprocess this file with a different target",
    done_chart_show: "Show loudness chart",
    done_chart_hide: "Hide loudness chart",
    done_chart_head: "Output loudness over time",
    done_report: "Download loudness report (JSON)",

    error_default: "Something went wrong.",
    error_retry: "Try again",
    footer_loading: "Loading processing engine…",

    engine_load_code: "Loading engine code…",
    engine_load_code_timeout_label: "Load engine code",
    engine_download_core_label: "Download engine code",
    engine_download_wasm_label: "Download engine core",
    engine_start_label: "Start engine",
    engine_download_core_progress: "Downloading engine code…",
    engine_download_wasm_progress: "Downloading engine…",
    engine_start_progress: "Starting engine…",
    engine_ready: "Engine ready",
    engine_no_source: "Couldn't reach the processing engine.",
    engine_source_n: "Source {n}: {msg}",
    engine_timeout: "{label} timed out (no response after {sec}s)",
    engine_download_fail: "Download failed (HTTP {status}): {url}",
    engine_load_failed_title: "Failed to load the processing engine.",
    engine_retry: "Retry",
    engine_load_failed_full: "Failed to load the processing engine.\n\nDetails:\n{reason}\n\nCheck your network connection, or screenshot this text to report the issue.",
    engine_no_wasm_text: "This browser doesn't support WebAssembly — this tool can't run here",
    engine_no_wasm_status: "WebAssembly not supported",

    probe_fail: "Couldn't read this file — it may not be a valid video or audio file.",
    measure_fail: "Measurement failed — couldn't parse the loudness data.",
    silence_fail: "This file's audio is (nearly) silent — there's no way to calculate the needed gain.",
    render_output_stage: "Rendering output",
    render_correct_stage: "Correcting peak (pass {n})",
    render_verify_stage: "Verifying output",
    file_not_media: "This doesn't look like a video or audio file. Please check the file format.",
    file_meta_reading: "{size} MB · Reading…",
    file_surround: "surround",
    file_no_audio: "No audio track detected in this file — loudness can't be adjusted.",
    file_read_error: "An error occurred while reading the file.",

    proc_analyze_stage: "Analyzing source loudness",
    proc_unsupported_codec: "Video encoded as {codec} isn't supported for output yet.\nPlease use an H.264 / VP9 video, or the advanced desktop tool (Python CLI).",
    proc_generic_error: "Something went wrong during processing — please try again.",
    proc_chart_stage: "Analyzing loudness over time",
    proc_done_stage: "Done",
    variant_denoise_label: " (denoised)",
    variant_denoise_full_label: " (denoised, full video)",
    variant_gain_up: "Boosted",
    variant_gain_down: "Reduced",
    variant_note_gain: "{dir} {db} dB",
    variant_note_limiter: ", part of it processed through a true-peak limiter",
    variant_note_pure_gain: " (pure gain — no change to sound quality)",
    variant_note_video_kept: ". Video kept byte-for-byte, not re-encoded.",
    variant_note_preview_only: ". Reusing the plain version's picture for preview — this is just for comparing sound; the full video for this version is built when you download it.",
    variant_note_lossless_wav: ". Output is lossless 24-bit WAV.",
    variant_note_surround: " Measured with ITU-R BS.1770 surround weighting for {layout}, not just the front left/right channels.",
    variant_note_denoised: " Conservative denoising applied.",
    variant_warn_shortfall: "This clip has high peaks (possibly clipping or impact sounds) — fully reaching the target would need more limiting, so the result is about {db} dB quieter than the target to avoid squashing the sound.",
    download_building_video: "Building full video…",
    download_rebuild_fail: "An error occurred while building the full video — please try again.",
    share_read_fail: "Failed to read the file",

    help_h2_how: "How it works",
    help_principle_html: "<strong>If plain gain can solve it, dynamics processing never gets used.</strong> The whole file is measured first, the needed gain in dB is calculated, and — once that gain is confirmed not to push peaks over the ceiling — the only thing that happens is multiplying by a fixed number. That's mathematically transparent: tone, dynamics, stereo phase, and transients all stay exactly as they were, just louder.",
    help_limiter_note_html: "A true-peak limiter only kicks in when <strong>peaks genuinely don't leave enough headroom</strong> (say, the source has clipping or impact sounds), and even then it's only applied to the few dB that are short. The finished file is re-measured afterward to confirm it actually hit the target.",
    help_h3_flow: "The process",
    help_flow_1_html: "<strong>Measure</strong> integrated loudness and true peak per ITU-R BS.1770 / EBU R128.",
    help_flow_2_html: "<strong>Decide</strong> how many dB are needed. Enough peak headroom means pure gain and done; not enough brings in limiting.",
    help_flow_3_html: "<strong>Render and verify</strong> — the video stream is copied directly, audio is encoded with the gain applied. The result is re-measured immediately; if peaks are still over, the gain is auto-corrected and it runs again — that guarantee comes from measured numbers, not an assumption that the safety margin is always enough.",
    help_h3_quality: "Picture quality is completely unchanged",
    help_quality_p: "The video track is copied directly — never decoded, never re-encoded, start to finish. You can verify it yourself: the video stream's MD5 is identical between source and result.",
    help_md5_snippet: "ffmpeg -i original.mp4 -map 0:v -c copy -f md5 -\nffmpeg -i result.mp4 -map 0:v -c copy -f md5 -",
    help_h3_why_minus1: "Why the peak ceiling is -1 dBTP, not 0",
    help_why_minus1_p: "A digital signal still has waveform between its sample points. When a player reconstructs it as analog, or a platform re-encodes it to AAC/Opus, the reconstructed waveform's peak can end up higher than the original samples. Leaving 1 dB of headroom keeps that reconstruction overshoot from clipping on the listener's device. It's the common practice across every streaming platform's delivery spec.",

    help_h2_platforms: "Supported platforms",
    help_th_platform: "Platform",
    help_th_target: "Target",
    help_row_broadcast: "Broadcast (EBU R128)",
    help_row_custom: "Custom target",
    help_row_custom_desc: "Enter your own LUFS (-70 to -5) and true-peak ceiling",
    help_platforms_note: "If your platform isn't listed, or it has its own delivery spec, choose \"Custom target…\" and enter the numbers yourself — it works exactly the same way.",

    help_h2_faq: "Frequently asked questions",
    faq_q1: "The result is still quieter than everyone else's video?",
    faq_a1: "If you see a \"quieter than target\" note, a handful of very loud moments in the source (a popped mic, a table thump, an impact sound) are capping the overall level. The best fix is to go back and trim or fix those spikes — a limiter can only do so much, and pushing it further visibly squashes the sound.",
    faq_q2: "Why is video output AAC? Isn't that lossy?",
    faq_a2: "Yes. Changing loudness always requires re-encoding the audio — there's no way around that step. The browser version outputs AAC/Opus consistently, and in practice the difference isn't audible.",
    faq_q3: "Why is audio-only output a WAV file?",
    faq_a3: "WAV is a lossless format. The browser version always outputs 24-bit lossless WAV for audio files (with triangular high-pass dither applied to avoid the quantization noise that comes from narrowing bit depth), so the \"no change to sound quality\" promise holds 100%.",
    faq_q4: "Can it denoise at the same time?",
    faq_a4: "Yes. The ready screen has a \"Denoise comparison (optional)\" checkbox, off by default; turning it on processes both a plain and a denoised version, and you can A/B them by ear afterward before choosing which to download. Denoising is conservative — good for steady noise like hiss, hum, or wind, but it won't fully remove loud or irregular noise, and doing two passes takes longer than usual. For video files, the denoised comparison is audio-only (no picture, so a phone isn't loading two full videos at once); the full picture is added back when you download it.",
    faq_q5: "Can I enter a custom target loudness?",
    faq_a5: "Yes. Choose \"Custom target…\" from the platform menu to enter your own integrated loudness (LUFS) and true-peak ceiling (dBTP) — it works exactly like a preset platform, measuring first and calculating gain, with limiting only when there isn't enough headroom.",
    faq_q6: "Does it handle 5.1 surround video too?",
    faq_a6: "Yes. Measurement correctly weights surround channels per ITU-R BS.1770 (not just the front left/right), and the channel count and spatial positioning are fully preserved — only the overall level changes.",
    faq_q7: "Can I export a processing record?",
    faq_a7: "Yes. After processing, you can download a JSON loudness report recording the before/after LUFS and true peak, the target used, whether limiting was applied, and more — handy for archiving or handing off to a post-production team.",
    faq_q8: "How do I know if the loudness in my source jumps around?",
    faq_a8: "The done screen has a \"Show loudness chart\" you can expand to see loudness over time, before and after, across the whole clip — useful for spotting sections that run especially loud or quiet.",
    faq_q9: "My file isn't uploaded anywhere, right?",
    faq_a9: "Correct. The entire process runs on the WebAssembly build of ffmpeg, executing directly in your browser — the file only ever lives in your device's memory, with no network upload at all. That's also why closing the browser tab interrupts processing: there's no server running it for you in the background.",
    faq_q10: "My video is huge or long and processing is slow or crashes the tab — what do I do?",
    faq_a10: "The browser version has no hard size limit, but the whole video loads into memory to process — there's no streaming path — so your device's performance and available memory are the real ceiling. Short clips (a few minutes, a few hundred MB) work best; try a short segment first if you're unsure.",
    faq_q11: "It says my video format isn't supported — what now?",
    faq_a11: "H.264/HEVC (outputting MP4) and VP8/VP9/AV1 (outputting WebM) are supported today, covering the vast majority of phone recordings and web video. For anything else, convert to MP4 or WebM with another tool first, then upload it here."
  }
};

var currentLang = getStoredLang();

function t(key, params) {
  var dict = I18N[currentLang] || I18N.zh;
  var str = (dict && dict[key] != null) ? dict[key] : (I18N.zh[key] != null ? I18N.zh[key] : key);
  if (params) {
    for (var k in params) {
      if (Object.prototype.hasOwnProperty.call(params, k)) {
        str = str.split("{" + k + "}").join(String(params[k]));
      }
    }
  }
  return str;
}

function tRaw(lang, key) {
  var dict = I18N[lang] || I18N.zh;
  return (dict && dict[key] != null) ? dict[key] : (I18N.zh[key] != null ? I18N.zh[key] : null);
}

function applyStaticTranslations(lang) {
  var textEls = document.querySelectorAll("[data-i18n]");
  for (var i = 0; i < textEls.length; i++) {
    var el = textEls[i];
    var val = tRaw(lang, el.getAttribute("data-i18n"));
    if (val != null) el.textContent = val;
  }
  var htmlEls = document.querySelectorAll("[data-i18n-html]");
  for (var j = 0; j < htmlEls.length; j++) {
    var hel = htmlEls[j];
    var hval = tRaw(lang, hel.getAttribute("data-i18n-html"));
    if (hval != null) hel.innerHTML = hval;
  }
  var attrEls = document.querySelectorAll("[data-i18n-attr]");
  for (var k = 0; k < attrEls.length; k++) {
    var ael = attrEls[k];
    var spec = ael.getAttribute("data-i18n-attr").split(",");
    for (var s = 0; s < spec.length; s++) {
      var pair = spec[s].split(":");
      if (pair.length < 2) continue;
      var attr = pair[0].trim();
      var key = pair.slice(1).join(":").trim();
      var aval = tRaw(lang, key);
      if (aval != null) ael.setAttribute(attr, aval);
    }
  }
}

/** Sets the shared language, re-runs the static translation pass, and
 *  updates the #langToggle button itself (its label is the language you'd
 *  switch INTO, matching the existing theme-toggle's icon-button style —
 *  fixed-width .btn.icon, so flipping it never changes layout). */
function applyLanguage(lang) {
  lang = lang === "en" ? "en" : "zh";
  currentLang = lang;
  try { localStorage.setItem(SM_LANG_KEY, lang); } catch (e) {}
  document.documentElement.lang = lang === "en" ? "en" : "zh-Hant";
  applyStaticTranslations(lang);

  var toggle = document.getElementById("langToggle");
  if (toggle) {
    toggle.textContent = lang === "en" ? "中" : "EN";
    var label = lang === "en" ? tRaw(lang, "lang_switch_to_zh") : tRaw(lang, "lang_switch_to_en");
    toggle.setAttribute("title", label);
    toggle.setAttribute("aria-label", label);
    toggle.setAttribute("aria-pressed", String(lang === "en"));
  }
}

/**
 * Call once per page, after the page's own markup exists (i.e. from a
 * script placed after the body content, or from the top of a deferred/
 * module script — both run after parsing). Applies the stored language,
 * lets the caller refresh any JS-managed dynamic text (progress labels,
 * engine status, etc. — content that plain data-i18n can't own because
 * script overwrites it after load), then reveals the page.
 *
 * opts.afterApply(lang), if given, runs after every language application —
 * both this initial one and every later toggle click.
 */
function initSmI18n(opts) {
  opts = opts || {};
  var lang = getStoredLang();
  applyLanguage(lang);
  if (typeof opts.afterApply === "function") opts.afterApply(lang);
  document.documentElement.classList.remove("i18n-pending");

  var toggle = document.getElementById("langToggle");
  if (toggle) {
    toggle.addEventListener("click", function () {
      var next = currentLang === "en" ? "zh" : "en";
      applyLanguage(next);
      if (typeof opts.afterApply === "function") opts.afterApply(next);
    });
  }
}

window.I18N = I18N;
window.t = t;
window.applyLanguage = applyLanguage;
window.initSmI18n = initSmI18n;
window.getStoredLang = getStoredLang;
