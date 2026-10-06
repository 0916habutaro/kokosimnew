# Stage 12L 2026シーズン最終統合監査

作成日: 2026-10-06

## 目的

Stage 12A〜12Kで分散して整備した大会構造・カレンダー・進出依存を、2026シーズン全体として一括監査する。

対象は competitions.csv に登録された全162大会。

## 全体構成

competition master: 162大会

実行上の区分:
- 県春秋系: 94大会
- 地区大会系: 16大会
- 夏地方大会: 49大会
- 全国大会: 3大会

合計:
- 94 + 16 + 49 + 3 = 162

県春秋94には北海道春・北海道秋・東京秋を含む。
地区大会19カレンダーのうち、この3大会は県大会側の実行経路で扱われるため、regional_rowsは16となる。

## カレンダー監査

season_calendar.csv:
- 登録: 162 / 162
- calendar_status=official_schedule: 162 / 162
- calendar未登録: 0

game_date_list:
- detailed: 112大会
- period_only: 49大会
- future_pending: 1大会
- unexpected empty: 0

### detailed 112大会

competition_level / competition_type上の内訳:
- prefectural levelの春秋: 91大会（春46＋秋45）
- regional levelの春秋: 19大会（春9＋秋10）
- national: 2大会（選抜・夏甲子園）

合計91＋19＋2＝112。

一方、エンジンの実行区分では北海道春・北海道秋・東京秋の3大会をprefectural_rows側で扱うため、実行区分は94県大会＋16地区大会となる。

### period_only 49大会

第108回全国高等学校野球選手権の地方大会49大会。

現状は日本高野連の大会会期を基に start_date / end_date を保持しているが、個別の実試合日は game_date_list へ未構造化。

これはカレンダー欠落ではなく、既知の詳細粒度不足としてStage 12Lで明示する。

### future_pending 1大会

CMP000003 明治神宮大会高校の部。

- 開催期間: 11/19〜11/24
- 抽選日: 10/17
- 10/6時点では抽選前

そのため game_date_list は空欄のまま保持し、10/17以降に確定する。

## 依存関係master

- regional_feeder_rules: 96
- qualification_rules: 59
- competition_access_rules: 22
- selection_rules: 12
- 選抜 selection quota: 32

qualification 59は、
- 夏地方→夏甲子園: 49
- 秋地区→明治神宮: 10

で構成される。

## 現行エンジンで保証する事項

Stage 12Lテストでは以下を一括検証する。

1. competitions.csv 162大会とseason_calendar.csv 162行が完全一致
2. calendar_id側のcompetition重複なし
3. 全162行がofficial_schedule
4. game_date_listがある大会は昇順・重複なし・start/end範囲内
5. 空game_date_listは夏地方49＋神宮1のみ
6. static dependency master件数が期待値と一致
7. competition_runsが162 / 162生成される
8. prefectural_rows 94
9. regional_rows 16
10. summer local 49
11. national 3
12. qualification 59 / 59 PASS
13. access 22 / 22 PASS
14. calendar gap 0
15. internal structure gap 0
16. regional bridge gap 0
17. warnings 0

## Stage 12D旧監査との関係

Stage 12D時点の監査ファイルには、当時未実装だった地区大会接続や神宮依存がBLOCKEDとして残っている。

これらは履歴として保持する。

現行状態の正否判定には、
- Stage 12E以降の実装
- Stage 12H構造修正
- Stage 12K全国依存監査
- Stage 12L統合監査

を使用する。

## 既知の残作業

### REM001 夏地方49大会の試合日詳細
status: known_detail_gap

start/end会期は登録済みだが、game_date_listを実試合日単位へ細分化していない。

次の大規模データ工程候補。

### REM002 明治神宮の個別試合日
status: future_pending

10/17抽選後に確定。

### REM003 秋季県大会19件の実績化
status: ongoing

Stage 12Iで追跡。

### REM004 秋季地区大会9件の実績化
status: ongoing

Stage 12Jで追跡。
東京秋はStage 12Iへ委譲済み。

## Stage 12Lの意味

Stage 12L完了時点では、
- 構造上の大会欠落
- カレンダー行欠落
- 進出ルール未接続
- エンジン未実行大会

を0件にする。

残る作業は
- 将来大会の実績確定
- 夏地方大会の試合日粒度向上

であり、共通大会エンジンの構造欠落とは分離して管理する。

## 次工程

Stage 12Lで全162大会の統合保証が通った後は、待機不要の次工程として
**Stage 12M: 夏地方49大会の個別試合日構造化**
を優先候補とする。
