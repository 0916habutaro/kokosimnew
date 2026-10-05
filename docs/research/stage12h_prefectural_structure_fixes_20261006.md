# Stage 12H 県大会前段予選構造 修正報告書

作成日: 2026-10-06

## 対象
Stage 12Gの日程調査で判明した3件の構造不整合を修正した。

- 東京都春 CMP000094
- 和歌山県秋 CMP000128
- 愛媛県秋 CMP000144

## 東京都春
従来は全登録校をMAINへ直接投入していた。2026制度に合わせ、PRELIMINARY_QUALIFIERを追加した。

- 前年秋季東京都本大会出場: 64校を一次予選免除
- 春季一次予選: 47代表
- 本大会: 64 + 47 = 111校

構造: PRELIMINARY_QUALIFIER -> MAIN

## 和歌山秋
従来は全登録校をMAINへ直接投入していた。県一次予選と県二次予選を分離した。

- 県下高校野球新人戦ベスト4: 一次予選免除
- 県一次予選: 4ゾーン各1代表
- 県二次予選: 4 + 4 = 8校

構造: PRELIMINARY_QUALIFIER -> MAIN

## 愛媛秋
従来はSEED_EVENT後に全60校をMAINへ投入していたが、実大会は県大会予選を経て16校本選となる。

- 地区新人大会: 東予5・中予4・南予3 = 12シード
- 当年夏愛媛大会優勝校: SEED_EVENT免除で1シード追加
- 県大会予選シード: 計13校
- 県大会予選: 60校から16代表
- 本選: 16校
- 予選シード情報は本選へ持ち越さない

構造: SEED_EVENT -> PRELIMINARY_QUALIFIER -> MAIN

FMT001を拡張し、前段予選にシード情報が指定された場合のみ、保護シードを代表ブロックへ1校ずつ分散する。既存FMT001大会の挙動は変更しない。

## エンジン変更
- seed event -> qualifier -> MAIN の汎用実行経路を追加
- FMT001へ任意のprotected seed分散を追加
- MAINへ渡すseed metadataをdestination_stageでフィルタ
- 新人戦結果が独立competitionとして未物質化の場合の構造bootstrap resolverを追加
- 愛媛秋の県内一括予選をannual group overrideとして解決

## 検証結果
GitHub Actionsで実行。

- unit test: 129 / 129 PASS
- Stage 12H validation: 15 / 15 PASS
- 県大会E2E: 94 / 94 PASS
- access rules: 22 / 22 PASS
- calendar gaps: 0
- internal structure gaps: 0
- warnings: 0

個別結果:
- CMP000094: entrants 269 / MAIN 111 / MAIN matches 110
- CMP000128: entrants 39 / MAIN 8 / MAIN matches 7
- CMP000144: entrants 60 / seeds 13 / MAIN 16 / MAIN matches 15

## 次工程
Stage 12H後は、Stage 12Gで将来予定日として登録した2026秋季大会について、大会終了後の実施日・順延日を再照合する。
