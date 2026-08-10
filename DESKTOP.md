# LoudMaster（桌面版）

> 這是本機安裝的指令列／圖形介面版本，沒有檔案大小限制、支援無損輸出與批次處理。
> 大多數人應該先用不用安裝任何東西的**[網頁版](https://stevenmusic.github.io/LoudNorm/)**；
> 這份文件是給需要處理大檔案、長片，或想要無損音訊輸出等進階功能的人看的。

把影片的音量提升到 YouTube 等平台的標準響度——**不破音、不改變畫質、盡可能不改變音質**。

匯入影片（可另外匯入配樂），輸出一個可以直接上傳的成品，沒有檔案大小限制。

```bash
./loudnorm 我的影片.mp4
```

```
✓ 完成：我的影片_loudnorm.mp4
   目標   -14.00 LUFS    -1.00 dBTP   （YouTube）
   原始   -28.43 LUFS   -12.10 dBTP  動態  7.8 LU
   成品   -14.02 LUFS    -1.20 dBTP  動態  7.8 LU
   處理  提升 14.41 dB（純增益，不改變音質）
   影像  h264 1920x1080 原封不動複製（未重新編碼）
   音訊  aac 384000（有損）
```

---

## 這個工具在做什麼

上傳到 YouTube 的影片如果太小聲，觀眾要一直調音量；如果太大聲，YouTube 會自己把它轉小，
而且**不會**因為你的影片小聲就幫你轉大。所以「剛剛好」是有一個明確數字的：
**-14 LUFS**（整合響度），且真實峰值不超過 **-1 dBTP**。

LoudMaster 的做法刻意跟大多數「自動聲音加大」工具不同：

> **能用純增益解決的，就絕不做動態處理。**

它會先量測整支片子，算出需要多少 dB，確認這個增益不會讓峰值超標，然後就只做「乘上一個
固定數字」這一件事。這在數學上是完全透明的——音色、動態、立體聲相位、瞬態全部原封不動，
只是變大聲。

只有在**峰值真的不夠用**的時候（例如素材裡有爆音、拍打聲），才會啟用真實峰值限幅器，
而且只用在「差的那幾 dB」，並且會明白告訴你用了多少。

## 三個「不改變」，分別是什麼意思

| 項目 | 保證程度 | 說明 |
|---|---|---|
| **畫質** | **完全不變（位元完全相同）** | 影像軌是 `-c:v copy` 直接複製，從頭到尾沒有解碼、沒有重新編碼。可以自己驗證：兩個檔案的影像串流 MD5 是一樣的。 |
| **音質** | **不做動態處理；容器允許時完全無損** | 輸出到 `.mkv` / `.mov` 時音訊存成 FLAC／PCM 24-bit，等於「原始訊號 × 一個固定增益」，沒有二次壓縮。輸出到 `.mp4` 時因為容器限制必須轉成 AAC（預設 384 kbps，遠高於一般來源）。 |
| **不破音** | **有量測保證** | 全程 64-bit 浮點運算，中間不可能溢位；峰值以 4 倍超取樣的「真實峰值」為準，成品會再量一次確認沒有超過上限。 |

> **想要完全零損失的音訊？** 把輸出副檔名改成 `.mkv` 或 `.mov` 就好：
> `./loudnorm 影片.mp4 -o 成品.mkv`
> 影像照樣是原封不動複製，音訊變成 FLAC 無損。YouTube 兩種都收，而且它反正會自己重新編碼，
> 給它無損的來源畫質音質只會更好。

---

## 安裝

只需要兩樣東西，都不用寫程式：

**1. ffmpeg**

| 系統 | 指令 |
|---|---|
| macOS | `brew install ffmpeg` |
| Windows | `winget install Gyan.FFmpeg`（或到 [ffmpeg.org](https://ffmpeg.org/download.html) 下載） |
| Ubuntu / Debian | `sudo apt install ffmpeg` |

**2. Python 3.8 以上**（開發時實測 3.10 / 3.11 / 3.12 / 3.13）

macOS 和多數 Linux 內建。Windows 請到 [python.org](https://www.python.org/downloads/) 下載，
安裝時記得勾選 **Add Python to PATH**。

本工具**不需要**安裝任何 Python 套件，全部使用標準函式庫。

---

## 圖形介面

不想碰指令列的話：

* **macOS**：雙擊 `loudmaster-gui.command`
* **Windows**：雙擊 `loudmaster-gui.bat`
* **任何系統**：`python3 -m loudmaster --gui`

視窗裡由上到下就是四個步驟：加入檔案 → 選平台 → （可選）加配樂 → 按「開始處理」。
可以一次丟很多檔案批次處理，也有「只分析響度」按鈕先看看目前多大聲。

> Linux 若出現找不到 Tkinter，安裝 `sudo apt install python3-tk` 即可；
> 或直接用下面的指令列版本。

---

## 指令列用法

```bash
# 最常用：以 YouTube 標準輸出 影片_loudnorm.mp4
./loudnorm 影片.mp4

# 批次處理整個資料夾，輸出到別的地方
./loudnorm *.mp4 -d 輸出資料夾

# 輸出無損音訊（完全不二次壓縮）
./loudnorm 影片.mp4 -o 成品.mkv

# 只想知道現在多大聲，先不要輸出
./loudnorm 影片.mp4 --analyze

# 加入背景音樂，音樂小聲 8 dB，太短就循環，說話時自動壓低音樂
./loudnorm 影片.mp4 --music 配樂.mp3 --music-gain -8 --music-loop --duck

# 用音樂完全取代原本的聲音，並在最後 3 秒淡出
./loudnorm 影片.mp4 --music 配樂.wav --music-mode replace --music-fade-out 3

# 換平台
./loudnorm 影片.mp4 -p apple        # Apple Music -16 LUFS
./loudnorm 影片.mp4 -p broadcast    # 電視 EBU R128 -23 LUFS

# 自訂目標
./loudnorm 影片.mp4 --target-lufs -12 --target-tp -1.5

# 完全不做動態處理，寧可小聲一點也不要限幅
./loudnorm 影片.mp4 --mode safe
```

Windows 上把 `./loudnorm` 換成 `python -m loudmaster`。

完整選項：`./loudnorm --help`；平台清單：`./loudnorm --list-presets`。

### 支援的平台預設

| 代號 | 平台 | 目標 |
|---|---|---|
| `youtube` | YouTube（預設） | -14 LUFS / -1 dBTP |
| `youtube-music` | YouTube Music | -14 LUFS / -1 dBTP |
| `spotify` | Spotify | -14 LUFS / -1 dBTP |
| `apple` | Apple Music / Podcasts | -16 LUFS / -1 dBTP |
| `tiktok` | TikTok / Instagram / Reels | -14 LUFS / -1 dBTP |
| `podcast` | Podcast（語音為主） | -16 LUFS / -1 dBTP |
| `broadcast` | 廣播電視 EBU R128 | -23 LUFS / -1 dBTP |
| `atsc` | 美規電視 ATSC A/85 | -24 LUFS / -2 dBTP |

---

## 它是怎麼做的

跟母帶工程師的流程一樣，共五步：

1. **先完整聽過一遍** — 依 ITU-R BS.1770 / EBU R128 量測整合響度、真實峰值、動態範圍。
   量測的對象就是最後要輸出的訊號（如果你有加配樂，量的是混完之後的結果）。
2. **決定要做什麼** — 算出需要幾 dB，以及峰值餘裕夠不夠。夠 → 純增益，結束。
3. **試算**（只在需要限幅時）— 限幅會吃掉一點響度，所以先用一個純音訊的快速 pass
   量測處理後的實際結果，回頭修正增益。這樣才不會「以為做到 -14，其實只有 -16」。
4. **輸出成品** — 一次編碼完成。影像串流直接複製，完全沒有碰到。
5. **驗收** — 重新量測成品檔案，把實際的 LUFS / dBTP 報給你看。

### 為什麼真實峰值上限是 -1 dBTP，而不是 0

數位訊號的取樣點之間還有波形。播放器把它還原成類比、或是 YouTube 把它轉成 AAC/Opus 時，
還原出來的波形峰值會比原本的取樣點更高。留 1 dB 餘裕，就是為了讓這個「還原後的超出量」
不至於在觀眾的裝置上削波。這是所有串流平台交件規範的共同做法。

限幅器本身也是在 4 倍超取樣（192 kHz）之下運作，才能真正控制到取樣點之間的峰值，
而不是只控制取樣點。

### 為什麼要用 `latency=1`

限幅器需要「預看」訊號才能在爆音來臨前先把音量壓下去，這會讓音訊延後約 5 ms。
5 ms 足以造成可察覺的對嘴不同步，所以工具開啟了延遲補償。
（本專案的測試會實際量測這個位移，確認為 0.000 ms。）

---

## 常見問題

**Q：處理完還是比別人的影片小聲？**
看報告裡的「處理」那一行。如果出現「比目標小聲 X dB」的警告，代表你的素材裡有少數
非常大聲的瞬間（爆麥、拍桌、碰撞聲），把整體音量「頂住」了。工具預設最多只用 6 dB 的限幅，
因為再多聲音會明顯變扁。兩個解法：

* 回去剪掉／修掉那幾個突波（最好的做法），或
* 放寬上限：`--max-limiting 9`

**Q：為什麼輸出 mp4 時音訊變成 AAC？這不是有損嗎？**
是。MP4 容器不能放無損音訊，而改變音量必然要重新編碼音訊，所以這一步無法避免。
預設用 384 kbps（YouTube 官方建議值），實務上聽不出差異。
真的要零損失就輸出 `.mkv` 或 `.mov`，音訊會存成 FLAC／PCM。

**Q：畫質真的完全沒動嗎？**
真的。你可以自己驗：

```bash
ffmpeg -i 原始.mp4    -map 0:v -c copy -f md5 -
ffmpeg -i 成品.mp4    -map 0:v -c copy -f md5 -
```

兩行的 MD5 會一模一樣。（測試套件裡也有這一項。）

**Q：可以只處理純音訊檔嗎？**
可以，丟 `.wav` / `.mp3` / `.flac` 進去就好，行為完全一樣。

**Q：檔案很長會很久嗎？**
主要成本是讀完整個檔案（量測 1 次、輸出 1 次、驗收 1 次；有用到限幅時多 1 次試算）。
因為影像不用重新編碼，速度通常遠快於一般轉檔。不想等的話 `--no-verify --no-refine` 可以少兩趟。

**Q：來源本身就已經削波失真了，救得回來嗎？**
救不回來——已經被削掉的波形沒有留下任何資訊。工具會警告你，並把峰值拉回安全範圍，
但失真本身還在。這種情況只能回去找原始素材重做。

---

## 給開發者

當作函式庫使用：

```python
from loudmaster import discover, JobSpec, run_job, presets

tools = discover()
result = run_job(tools, JobSpec(
    input_path="clip.mp4",
    output_path="clip_master.mkv",
    preset=presets.get("youtube"),
))

print(result.plan.summary())          # 做了什麼
print(result.final_stats.integrated)  # 成品實際響度
print(result.hit_target)              # 有沒有達標
```

也可以用 `--json` 取得機器可讀的報告，或用 `--dry-run` 印出實際會執行的 ffmpeg 指令。

### 專案結構

| 檔案 | 負責 |
|---|---|
| `loudmaster/analysis.py` | 量測（**只量測，絕不處理**） |
| `loudmaster/mastering.py` | 決策：要多少增益、要不要限幅 |
| `loudmaster/graph.py` | 組 ffmpeg 濾鏡圖 |
| `loudmaster/encoders.py` | 選輸出編碼（容器允許就選無損） |
| `loudmaster/pipeline.py` | 串起整個流程 |
| `loudmaster/cli.py` / `gui.py` | 兩種介面 |

量測與處理被刻意分在不同模組，這是「不改變音質」這個承諾能夠成立的結構性原因：
`loudnorm` 濾鏡在本專案裡只被當成**量表**使用，它的動態正規化輸出從來不會進到成品。

### 測試

```bash
python3 -m unittest discover -s tests -v
```

51 個測試。單元測試不需要 ffmpeg；整合測試會實際產生並處理影片檔，
驗證達標精度、峰值安全、影像位元完全相同、失敗時不留半成品——沒有 ffmpeg 時會自動略過。
