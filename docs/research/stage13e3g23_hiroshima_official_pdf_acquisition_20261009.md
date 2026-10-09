# Stage 13E-3G-23：2026広島公式組合せPDFの8件取得再調査と証拠の受入準備

実施日：2026-10-09

## 今回の成果（2026年のPDF本文は未取得）

2026年公式地区組合せ8件の高野連掲載元とGoogle DriveファイルIDを再照合し、Google Drive閲覧ページの「Loading…」のみ取得できた。**PDFの画像・本文・試合番号の矢印は1件も取得できなかった。** ブラウザのHTML shellを「PDFを読んだ」と記録しない。

- 正式な掲載元：https://hiroshima.hhbf1950.or.jp/大会関連/硬式部各種大会
- 春季西部・北部・南部・東部：各1件。原本タイトルをGoogle Driveのリンク先HTMLメタデータで確認。
- 秋季西部・北部・南部・東部：各1件。原本タイトルをGoogle Driveのリンク先HTMLメタデータで確認。
- Google Driveの `/file/d/<id>/view` ページの読み込み表示しか得られず、PDF byte stream、各校の組合せの矢印は未確認。
- 2025秋西の高野連旧サイトPDFは閲覧可能だが**2026の証拠とは別年**。Stage22で比較した年別ゲート差は保護する。
- 2026二次結果223試合／西部秋25試合／SportsOnline87子大会の観測情報は保持するが、「公式2026原本から復元した抽選矢印」とは呼ばない。

## 新しい監査台帳とコード

`data/research/2026/hiroshima_official_bracket_pdf_access_audit_2026.csv`（8件）には以下を一件一行で記録した。

- 高野連公式案内→Google DriveファイルID・表示ファイル名・対応season/district/SGR
- 2026-10-09閲覧時点の `drive_html_loading_only` と `pdf_body_bytes_obtained=no`
- `pdf_sha256`空欄、`verified_pairing_edge_count=0`
- `allow_annual_bracket_graph=no`、`allow_live_fmt025_runtime=no`

`phase2_engine/hiroshima_stage13e3g23.py` は、既存 `hiroshima_bracket_pdf_review_2026.csv`（8件）とStage21地区別release review（8件）との参照一致を検査する。Google Driveの他ドメイン差替え、試合枝が閲覧済みという偽フラグ、PDF hashの偽登録、2025原本の2026混用、FMT025本体の不正解禁を拒否する。既存本体・マッチシミュレーター・学校抽選・任意順位戦は変更しない。

`tests/test_stage13e3g23_hiroshima_official_pdf_access.py` は正常系／改ざん時の fail-closed を検証。

## 次の工程：2026原本を実際に取得できた時の受入

1. 高野連サイトの該当公式リンクから2026年秋西のPDF原本を人が保存する（公式ファイルであることを URL と年度で確認）。取得不可なら取得不可として継続記録する。
2. 原本PDFのハッシュ・PDFページ・抽選試合番号・一次敗者の二位校送出先・二位校勝者の横断条件を、引用ページとともに別の根拠データにする。**本台帳の値を単に `yes` に書き換えるだけでは解禁できない。**
3. 秋西9子大会・18校・25試合について、公式原本と2026出版社記録の試合経路差を明示した監査を行う。
4. 他7地区へ展開し、学校数に左右される可変ゲートの仕様と、2026年度固定の組合せを分離。**ゲーム本体のFMT025変更・任意順位戦の `design_pending` 解除は別工程の承認が必要**。

**判定**：出典リンク8件再確認・取得可否台帳8件・誤解禁拒否の回帰追加。公式2026抽選図の復元・FMT025 runtime変更は未達のまま。
