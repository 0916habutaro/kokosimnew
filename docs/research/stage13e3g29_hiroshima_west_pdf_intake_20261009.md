# Stage 13E-3G-29：2026秋季広島西部・公式原本PDF取得の再監査とオフライン受入れパイプライン

実施日：2026-10-09

## 検証結果（完了・未完了を明示）

原本PDFを再取得するため、広島県高野連の公式サイト、Google Drive HTMLプレビュー、プレビュー画像URL、Google Driveの直接ダウンロードURL、分離実行環境からのHTTPS取得を再試行した。

- **広島県高野連の公式リンクと大会要項は閲覧できる**。2026秋季県大会32校の地区枠は西部7・北部6・南部10・東部9。
- Google Driveのファイル画面は「Loading…」HTMLで、Imageアンカーを含む。**原本PDFではない**。
- 今回その画像アンカーを辿った画像取得は403 Forbidden。Stage24で以前確認できた図画像1枚の観測は履歴として保存し、今回の画像取得失敗で「過去の観測も不存在」とはしない。
- Google Driveの `uc?export=download&id=...` の直接URLでも原本PDFバイトは得られず、実行環境の直接HTTPSリクエストはDNS解決不可だった。
- 新規取得した原本PDF数＝**0件**、生バイトSHA256数＝**0件**、高解像度原本による公式試合番号の独立確定＝**0/25**、公式個別進行矢印の独立確定＝**0/32**。実結果・出版社側の25試合や32接続が誤りという意味ではない。
- 2025年度の別年度公式PDFは**2026年度図の代用品にしない**。

確認元：
- 県高野連：https://hiroshima.hhbf1950.or.jp/大会関連/硬式部各種大会
- 2026秋西原本への連盟掲載リンク：https://drive.google.com/file/d/1VxVW_r_L5MwnP3hkqZToGe3o5StK5NQ-/view?usp=sharing
- 二次史実：https://www.reiwa-hb-sch-and-res-gatr-fod.com/hiroshima/2026autumn/west-area/
- 出版社子大会：https://www.sportsonline.jp/reportv2/PublisherFull/Rally.aspx?ParentID=RX%5DSZ

## 変更ファイル

- `data/research/2026/hiroshima_autumn_west_pdf_acquisition_attempts_stage13e3g29.csv`：**5件の取得・表示試行**を日付・対象Drive ID・URL・閲覧方法・結果・証拠等級ごとに分離。リンクを確認した成功と、PDF本文を取得した成功は違うと判定。
- `phase2_engine/hiroshima_official_pdf_intake.py`：外部で入手した本物のPDFを今後オフライン受入れするためのCLI。
  - PDF生バイト先頭の `%PDF-1.x`／`%PDF-2.0` と末尾 `%%EOF`、ファイルサイズの上限／下限、年度・対象DriveファイルIDの一致をチェック。Loading HTMLやプレビューPNGをPDFと誤認するのを拒否。
  - Popplerの `pdfinfo` によって解析可能なページか別途確認。解析できないPDFでは成功扱いしない。
  - 元バイトのSHA-256・長さ・ページ数・表示用PNGのファイル名などを `original_pdf_candidate_manifest.json` に保存。必要なら `pdftoppm` によって**300dpi** PNGを作成（文字OCR・試合番号の自動補完なし）。
  - 取得ファイルの来歴は別途人手で追跡・検証する。ローカルの任意PDFを読み込めただけでは広島県高野連の正式原本と判定しない。
  - ゲーム本体・公式番号25行・公式進行矢印32行・任意順位戦を自動変更しない。
- `phase2_engine/hiroshima_stage13e3g29.py`：Stage28の57件の未確認キューとStage23/24の過去観測を改変せず、5試行の「PDF原本0件」監査。
- `tests/test_stage13e3g29_official_pdf_intake.py`：HTML/PNG・別年度・不正な原本主張、SHA256、pdfinfo、300dpi、公式番号誤解禁を回帰テスト。
- `data/research/2026/research_pending_queue.csv`：RS2026026のStage29状況を追記。

## 原本が今後入手できた場合のローカル手順

ユーザーが公式Google Driveページをブラウザで開いて「ダウンロード」などから**実際のPDFファイル**を入手できた場合：

```bash
python -m phase2_engine.hiroshima_official_pdf_intake \
  --pdf /path/to/R8_autumn_west_original.pdf \
  --output-dir /path/to/west_pdf_review \
  --render
```

PDF読み取りと300dpi画像化にはPoppler（`pdfinfo`、`pdftoppm`）が必要。生成画像とSHA256の台帳は**正式な人手確認を始めるための素材**であり、画像ができただけで公式の全矢印を証明したことにはしない。実資料が取得できた場合、試合番号・矢印のレビュータスクはStage28の別CSVに位置付きで入力し、照合→独立確認→承認を経る。

## 完了判定と次工程

Stage29完了：原本未取得の状況と失敗理由を再現できる形で記録、**原本が実際に確保された際に検査・300dpi閲覧できるオフライン受入れ器を実装してテスト**。公式番号・公式敗者移動の完全確認は**未完了**であり、本番FMT025と任意順位戦`design_pending`は変更しない。

次はStage30として、原本PDFや高解像度画像が本当に取得できる環境での実資料照合に進む。取得が難しい場合は同じ失敗取得を繰り返さず、**他の公式日程・規則資料から敗者復活の一般的な転送方針がどこまで明文確認できるか**を独立研究キューにする。
