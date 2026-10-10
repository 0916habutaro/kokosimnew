# Stage 43F：2027年度以降の仮大会・仮日程と前年秋の資格引継ぎ

作成日：2026-10-10
対象：ココシミュNew
依存：Stage 43E（PR #134、main反映済／マージ後CI成功）
区分：**次年度大会生成の基礎データ**。ゲーム内2027大会の実プレイ・自動進行の完成ではない。

## 1. 実装の境界と理由

Stage43Eで「選手IDが変わらず進級し卒業・新入生が入る」土台を作った。しかし次年度大会生成には以下の未解決事項がある。

- `LiveSeasonGraphPlanner._competition_rows()` は `competitions.csv` の `reference_year` がその年の行だけを抽出。マスターは2026年度に固定。
- 2026の`season_calendar.csv`と`competition_stage_calendar.csv`は**実際の公式試合日・事後確認日**を含み、2027の公式資料ではない。
- 春選抜は`committee_selection`で決まる。前年秋の優勝校だけから自動で32校を確定することはできない。
- `competition_access_rules.csv`には`source_year_offset=-1`の規則があり、現行plannerは前年秋の順位を `prior_year_structural_bootstrap` として代用する箇所がある。長期ゲームでは**実際にプレイした前年の結果を正本**とする必要がある。
- 学校・合同チーム・予選出場単位は2026マスターと翌年度で変わる可能性がある。例：2026の夏大会の地区分けを無条件に2027の公式出場校だと宣言できない。
- 2026の大会方式自体も調査の残件がある。未確認部分を将来年の確定ルールとして勝手に有効化してはならない。

そのためStage43Fでは、**過去年度の大会IDを継続キーとして維持し、未来年度の仮大会・仮日程を出力する独立ブループリント**を実装する。まだライブ実行には渡さず、別工程で資格・大会方式・選手継続を検証後に接続する。

## 2. 出力内容

`phase2_engine.future_season_blueprint.build_future_season_blueprint()`：

| 項目 | 内容 |
|---|---|
| `competitions` | 2026年度の大会ID・種別・地域・方式を参照する未来年度の仮大会一覧。名称は「ゲーム内2027年度 CMP...（仮大会）」等とし、2026の正式大会名や第n回・令和8年度を使わない |
| `calendars` | 2026の開催月日を年だけ置換した**ゲーム内候補日**。実際の2027公式日程ではない |
| `stage_calendars` | pre-MAINなどの2026試合日を、同じ月日でゲーム用に仮投影。2026の`verified`は継承しない |
| `prior_autumn_access` | 前年秋を参照する明示的な出場規則の解決状況。ゲーム内確定順位がなければ`unresolved` |
| `committee_selections` | センバツ等の委員会選考大会は`committee_selection_pending`として保留 |
| `live_runtime_ready` | 常に`false`。この資料だけで正式大会の自動進行・保存は開始できない |

全仮日程は`date_source=game_projection_v1`／`real_world_verified=false`、出典IDと公式確認日を空欄にする。日程不明の大会について空白を埋めず、候補日を一切創作しない。

2026で確認された日程を月日移動しただけで曜日・祝日・会場・休養日が適切になるわけではない。候補として生成しているだけで、将来の本番スケジューラでは曜日・会場・組合せ・試合数・各ステージ前後関係を調整する必要がある。

`base_seed` と年度・大会IDから独立したSHA-256 RNG用seedを導出する。参照順によって結果を変えず、同じ`base_seed`で再現できる。

## 3. 前年秋→翌春の資格

`competition_access_rules.csv`の `source_year_offset=-1` の規則を列挙する。

- 対象年が2027なら、前年2026のゲーム内確定大会結果だけを参照する（2028なら2027）。
- 例：茨城県春季大会`CMP000084`の`ACR000004`は、前年秋の茨城県大会`CMP000085`上位4校を対象とする。
- `previous_results`の`source_competition_id`の値には、`{year:2026, status:"completed", source:"game_result", ranked_school_ids:[...]}`を受け付ける。年度・完了状態・出典・順位数と重複を検証し、失敗時は`unresolved`のままにする。
- これは信頼済み保存結果から正本を渡すための**入力契約**。任意JSON自体がゲーム結果を証明するわけではない。将来`HistoricalMatchArchive`と大会順位read modelから実結果を渡す接続器が必要。
- 2026の公式資料に基づく「固定上位n枠」の同じ仕組みを翌年のゲーム用に使う前提は、規則の適用年・開催方式が後年変更されていないという保証ではない。正式な年度別ルールは別途更新・検証する。
- **秋季地区大会の学校抽出やセンバツ委員会選考など、一般の`top_n`に置き換えられないものは、推測せず保留**する。

## 4. 実行例

```bash
python -m phase2_engine.future_season_blueprint \
  --data-dir data \
  --year 2027 \
  --seed 20261010 \
  --output out/game_2027_provisional_blueprint.json
```

ゲーム内の前年秋大会確定順位を管理している場合のみ`--prior-results-json path/to/previous_game_results.json`を渡せる。未入力は未解決として明示し、適当な出場校を生成しない。

例（**説明用の架空の学校ID**）：

```json
{
  "CMP000085": {
    "year": 2026,
    "status": "completed",
    "source": "game_result",
    "ranked_school_ids": ["SCH-A", "SCH-B", "SCH-C", "SCH-D"]
  }
}
```

結果ブループリントは`official_calendar=false`, `live_runtime_ready=false`と記録する。

## 5. 検証内容

`tests/test_stage43f_future_season_blueprint.py`：

- 全162大会のIDを重複なく扱い、スキーマ2026の年を2027へ仮移動。
- 2026の公式日程出典／検証済み表示／大会名称を2027の真実として複写しない。
- stage日程も仮日程に格下げし、空だったgame_date_listは空のまま。
- 同seed再生成の完全一致、異なるseedでは大会seedのみ変化。
- 前年秋結果がない場合は未解決、保存した2026秋上位4校を与えた場合のみ解決。
- 2025等の別年度、未完了、出典違い、順位不足や重複は拒否。
- 委員会選考／未対応の地区秋選抜は未解決のまま。
- 2028が2027の結果を要求。10000年以降は現在の`datetime`ではエラーを明示する。

## 6. 次の工程（Stage 43F-2 / Stage 43G）

1. `LiveSeasonGraphPlanner`を2026固定CSVから分離し、年度別仮大会マスター・仮日程・`AnnualCompetitionInput`を入力できる正式インターフェースを整備。
2. 2026の構造自体の未確認箇所や、翌年に持ち越せない日程・学校地区所属を分類。未来年度の抽選／大会の実行に必要な欠損を埋める。
3. 前年秋の実際の`CompetitionRun.outcome`や大会順位表から正本を作り、`previous_results`へ接続。秋県大会と秋地区大会・センバツ選考を別々に処理。
4. `CareerRosterArchive`から学校の当該年度ロスターを試合シミュレーションに渡し、既存選手IDと試合別GameStatsが一貫することを確認。
5. キャリア年次のセーブ／ロード、履歴SQLiteの追記、学校・大会・選手の年度切替read modelを一体的に検証。
6. 全県のpre-MAIN、本戦、春秋地区大会、センバツ、神宮、夏の甲子園を年度跨ぎで自動進行し、年度終了できるところまで実ゲームテスト。

**今回の完成は「2027以降の仮大会・仮日程ブループリントと前年秋資格の一部解決機能」です。2027のゲーム本編がプレイ可能になったという意味ではない。**
