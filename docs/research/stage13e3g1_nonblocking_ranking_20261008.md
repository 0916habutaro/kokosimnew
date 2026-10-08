# Stage 13E-3G-1 実装・調査報告

日付：2026-10-08

対象：FMT022（徳島秋・沖縄秋）、FMT025（静岡春秋・広島春秋）

## 確定事項

- 代表／シード権が確定した後の順位決定戦は、資格決定結果に影響しない**独立した任意イベント**とする。
- 徳島の新人中央大会は8校が2ブロックで戦い、上位4校が秋季シードを取得する。8月24日に2つのブロック決勝が行われている。
- 沖縄の新人中央大会は準々決勝の勝者4校が秋季シードを取得する。その後の8月13日準決勝と8月14日決勝で大会内順位が決まる。
- 静岡の秋季県大会予選は代表決定後の8月30日に上位決定戦を開催し、敗れても県大会出場権は失わない。
- 広島・静岡の年次カードは公式記録に依存するため、未提示のペアを勝手に固定データ化しない。

## コード・データ

- `data/competitions/post_qualification_ranking_profiles.csv`：6大会の方式プロファイル
- `phase2_engine/post_qualification_ranking.py`：代表資格固定・試合順序・結果記録・再開
- `phase2_engine/engine.py`：大会ステージの実出力から順位戦を組み立てる明示API
- `tests/test_stage13e3g1_nonblocking_ranking.py`：方式別と負例の回帰テスト
- 設計方針：`docs/design/post_qualification_ranking_stage13e3g1.md`

## 副作用防止

既存MAINカレンダー・pre-MAINカレンダーは変更しない。
既存`CompetitionRun`の進出校・シード割当・試合結果や大会進行状態を変更しない。
デフォルトでは追加試合を自動生成しない。年度別の正式対戦を知るまでは静岡・広島の順位戦を推測しない。

## 保留

`RS2026025`（FMT022）および`RS2026026`（FMT025）は、日程エンジンへの登録・read modelへの接続がまだないため`design_pending`のまま維持。Stage 13E-3G-2でライブ進行との接続と必要な年次ペア確定を行う。

## 根拠

- 徳島2026新人中央大会：https://www.hb-nippon.com/tournaments/1857
- 徳島2026秋シード4校：https://www.topics.or.jp/articles/-/1489451
- 沖縄2026新人中央大会：https://www.hb-nippon.com/tournaments/1740
- 沖縄2026秋シード確定：https://www.hb-nippon.com/articles/16145
- 静岡2026秋上位校決定戦：https://www.hb-nippon.com/calendar?date=2026-08-30
- 静岡市立高校の公式活動記録：https://shizuokacity-h.ed.jp/＜野球部＞秋季県大会予選代表決定戦/
