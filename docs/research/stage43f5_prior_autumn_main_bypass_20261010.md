# Stage 43F-5：前年秋の確定上位校を翌春大会の地区予選免除へ反映

作成日：2026-10-10
依存：Stage43F-4（PR #138） / Stage43F-3（PR #137）
対象：ココシミュNew／ゲーム内の2027年度以降。**正式な2027年の公式出場校ではない**。

## 1. 今回の目的

Stage43F-4は前年秋の確定`CompetitionRun.outcome`と、Stage43C/Dの封印済みA方式試合履歴を照合し、春季大会へ進む学校IDを`prior_autumn_access`へ渡せるようにした。しかし、その学校を次年度の`AnnualCompetitionInput.direct_main_entry_school_ids`へ接続する処理がなく、予選を免除したうえで本戦に出場させられなかった。

Stage43F-5では`phase2_engine.future_prior_autumn_access_bridge.prepare_future_prior_autumn_bypass_preview()`を実装し、**封印された前年秋の実ゲーム順位→翌春地区予選免除→地区予選の勝者と合流して本戦**という経路を実大会エンジンへ接続する。

## 2. 最初の試験対象：茨城県春季大会

| 項目 | 対象・数量 |
|---|---|
| 次年度の春大会 | `CMP000084`（ゲーム内2027年度仮大会） |
| 参照する前年秋大会 | `CMP000085`（2026年ゲーム内秋県大会） |
| ルール | `ACR000004`：前年秋上位4校、地区予選免除・MAIN直行 |
| 地区予選 | `STG000171`／FMT001、4地区 |
| 地区からのMAIN代表枠 | 水戸8・県北8・県南8・県西7＝31校 |
| MAINへの自動出場 | 前年秋の封印済み4校 |
| MAINの想定総数 | 予選31校＋直接4校＝35校 |

新規回帰テストでは、**上位4校を含む39校を試験用参加校として明示**し、そのうち直接4校を地区予選から除外し、残る35校を支部別に割り当てる。予選で31代表が決まったらMAINに4校を追加し、35校で試合を続行できることを検証する。

この39校の選定は仕組みの再現テスト用であり、**2027年の実際の茨城県大会参加校数を表すものではない**。

## 3. 確定データ・入力規約

```text
2026年秋ゲーム結果（全MAIN試合の勝敗と大会順位）
         ↓ Stage43F-4 検証・試合履歴SQLiteへ保存
2026年シーズンを封印（試合台帳と年度のdigest一致）
         ↓
build_future_blueprint_from_archive(year=2027)
         ↓
ACR000004 の学校ID上位4校が resolved
         ↓
2027年の全大会参加校をゲーム内sandbox入力として明示
 + 非直接出場校だけを4地区すべてに明示割当
 + 対象39校の2027年度継続ロスターSQLiteを確認
         ↓
AnnualCompetitionInput(
  direct_main_entry_school_ids=前年秋上位4校,
  group_entrant_school_ids=上位4校を除いた地区参加校,
  main_seed_school_ids=[]   # シードは推測しない
)
         ↓
TournamentEngine.prepare_scheduled_competition_runtime()
         ↓
FMT001地区予選の結果→MAIN31校＋直接4校で35校
```

- 過去年度の試合・大会成績の正本は`HistoricalMatchArchive`／`CareerCompetitionOutcomes`であり、外部の任意JSONを「検証済みゲーム結果」として取り込まない。
- 出場資格は`top_n`、前年`source_year_offset=-1`、`grant_main_entry_bypass_branch_qualifier`、`grants_main_entry=yes`、`excluded_from_bypassed_stage`等のルールに厳密一致する場合に限る。
- **`seed_on_entry=destination_policy`はシード番号の自動付与を意味しない。** 出場資格を獲得しても上位4校というだけで第1～4シードに据えることはしない。ゲーム内の独立したシードルール・順位指定が未確認なら`main_seed_school_ids=[]`のまま。
- 予選の未割当学校があっても2026の学校地区所属テーブルで補完しない。全参加校を明示し、地区の重複・欠損・県外校を拒否する。
- 対象校の2027年度`CareerRosterArchive`がなければ、翌年の別人を再生成せず開始を拒否する。
- 2026公式日程の月日から仮作成した日付は`game_projection_v1`を維持。正式な2027年の日程・大会結果と誤表記しない。
- 未完成の選抜委員会選考・秋季近畿大会参加校参照・FMT002等の複合方式・年次学校地区所属・正式GUIはこのアダプタでは扱わない。

## 4. 実装ファイル・テスト

- `phase2_engine/future_prior_autumn_access_bridge.py`：前年度の封印済み結果を取得し、対応するルール・対象県・前年上位校・地区出場者・地区出場枠・翌年継続ロスターを検証したうえで、`AnnualCompetitionInput`の直接進出と地区参加校を構築。通常の大会エンジンと`AbilityMatchResolver`を再利用する。
- `tests/test_stage43f5_prior_autumn_main_bypass.py`：2026年秋の試験用MAIN3試合の封印→順位の記録→2027春の上位4校免除→実際の地区試合による31代表＋4校で35校。前年結果欠損、未封印、地区重複、前年上位校の二重予選参加、他県校、seedの不一致など13件。

## 5. 残る重要な作業

1. **前年度上位校のシード**：各県の`competition_seed_rules.csv`・MAINシード方針を照合し、ゲーム用のseed orderやシード権の付与を別契約で実装。前年秋の順位＝翌春シード番号という憶測はしない。
2. 県大会の方式と地区分けを年度ごとに再生成し、すべての学校の現役加盟・合同チーム・所属地区を、実際の翌年度ゲームデータとして確定する。
3. FMT002の岐阜県や東京都春のPRELIMINARY`FMT001`など別方式に対応し、6ルールの対象大会でそれぞれ実試合進行を確認する。
4. 春予選終了後の地区大会・選抜・夏大会まで含む複数大会進行と依存関係をゲーム本編に接続。
5. `LiveGameService`のキャリア年度移行、全校ロスター・資格・試合成績の一貫したセーブ・ロード、正式GUIでの歴代閲覧。

**本工程で実際に動くのは、明示的な2027年sandbox参加校による前年上位校の地区予選免除→本戦合流の接続である。** 全国全県で2027年度以降の実ゲーム進行を完成させたわけではない。
