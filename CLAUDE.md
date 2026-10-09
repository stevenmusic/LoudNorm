# LoudNorm 專案規則

## 所有工具共用的規則(使用者要求,2026-10;FingerDrill、ScrollScore、HarmonyMap、HarmonyHands、BackingTrack、SightScore、LessonNotes、LoudNorm 都一樣)
- **版面要適配所有尺寸**:折疊機 280、SE 320、各種手機直式與橫式、iPad 直橫、筆電、桌機、1080p。
  沒有橫向捲動、元素不超出畫面、按鈕文字不被截斷、點擊區域至少 28×28、頂欄品牌名與按鈕不重疊、底部固定列不蓋住內容。
  改了畫面就用 Playwright 逐一尺寸檢查(做法可照抄 FingerDrill 的 `tools/test/layout.mjs`,19 種尺寸)
- **模擬真人操作,確認沒有 bug**:觸控隨機點、連點、按住、拖曳、旋轉螢幕、重新整理、切語言/主題、播放中做別的事……
  每一步檢查狀態一致、沒有 console 錯誤(做法可照抄 FingerDrill 的 `tools/test/human.mjs`,換幾個隨機種子跑)
- **每次更新(每次 push)都用中文條列說明改了什麼、為什麼改**
