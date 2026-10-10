# Stage 43G-27：10000年度以降のA方式試合を旧原本を変更せずに保存・閲覧するsidecar

作成日：2026-10-11。Stage43G-26 PR #167はPython3.12全unit、関東17校E2E、各種v2/フルA/20年50年専用CIが成功し、mainマージ済み（`39d629d3df909be72e7124dfd4331bff416713cf`）。

## 目的と境界
現在の`historical_matches.sqlite3`はmatch_dateを旧ISO文字列として扱い、実ゲーム年度の既存データと紐づく。Stage43G-25/26のv2論理日付`G10000:04-01`を、この既存match_dateにそのまま上書き／保存するのは非互換であり危険。

**本工程は実大会ランタイムを切り替えず、明示許可済み架空v2カレンダーに属する合成試合のA方式（最終スコア、イニング、打者・投手個人成績）を、別SQLiteに保存・封印し、10000年度の論理日付で閲覧可能にするための互換試験基盤。** 本番の無制限年度進行機能ではない。

## 追加コード
`phase2_engine/career_v2_option_a_archive.py`：

- `CareerV2OptionAArchive(db_path,calendar_path,legacy_archive_path=None)`：**専用** `fictional_option_a_v2.sqlite3`を扱う。過去の`historical_matches.sqlite3`に対する書込やALTER TABLE、既存試合の日付変換はしない。
- `append(year, source)`：`G10000:04-01`などの厳密な`GameDaySlot`と、先に保存された架空`CareerCalendarV2Archive`の大会ID・対象年度・承認済み日付が一致することを必須にする。元A方式の`_history_payload`正規化／得点・勝敗・イニングの整合検査を再利用。
- `ability_model_v1`による**イニング別得点・チーム成績・打者成績・投手成績の4種類がすべて非空**であることを要求。打席イベント・逐球イベントは保存しない。日付由来には`fictional_v2_day_slot`を明示し、旧ISO形式をv2記録に紛れ込ませない。
- v2原本JSONとカレンダーJSONのSHAを保存し、年度別`v2_game_years`でactive/sealed状態を管理。保存された試合の再投入は内容一致なら冪等、不一致なら拒否。年度封印後の新規追加は拒否、封印時に全行SHA・年度試合数・台帳SHAを検証。
- **旧DBを指定した場合、旧原本と同じ年度・大会・試合IDの新sidecar重複保存を拒否**。旧DB読み取りはSQLite`mode=ro`、元のハッシュは変えない。
- `year_matches`／`day_matches`：年度または論理日付でA方式原本をページング。元レコードSHA／カレンダー由来／主キー・日付・得点／封印台帳の不変性を検証してから返す。読み取り時にDB・索引を作成せず、不正・未登録データの補完も行わない。
- 現行`CareerHistoryBrowseModel`に`fictional_v2_option_a_year`／`fictional_v2_option_a_day`を別APIで追加し、従来の学校戦績・大会・個人通算の画面を変更しない。

## 実行例

10000年度の合成記録を表示する場合（事前に架空ゲームの日程・合成試合を**専用sidecarへ明示登録済み**であることが必要）：

```sh
python -m phase2_engine.career_v2_option_a_archive --slot-root SAVE --year 10000 --limit 30

python -m phase2_engine.career_v2_option_a_archive --slot-root SAVE --day-token G10000:04-01 --competition-id CMP000086
```

上記CLIは既存DBを読取専用で開く。書き込み可能な機能はクラスの`append`／`seal_year`を明示使用するときに限る。

## テスト範囲
`tests/test_stage43g27_v2_option_a_archive.py`：
1. 年度10000のA方式試合2件（イニング18行・打者18行・投手2行・チーム2行/試合）を登録、年度封印、日・年一覧、ページング、参照前後の2DB SHA不変。
2. 封印後の新試合・元試合と異なる冪等再投入・日付未登録・公式日付を装ったデータ・box score欠損を拒否。
3. 元の別`historical_matches.sqlite3`の2026試合と同じID/年/大会での二重登録を拒否、原本ファイルSHAと元試合の閲覧を維持。
4. v2原本のSHA改変、封印台帳・カレンダーSHA改変、必須年度未登録・不正ページ指定の拒否。
5. 旧`CareerHistoryBrowseModel`から10000年度の独立v2 A方式試合の閲覧と日付別結果を利用可能。
6. 専用CI `.github/workflows/career-v2-option-a-sidecar.yml`の実行により上記全テストを毎PR監査。通常全unittest・関東17校E2Eも引き続き成功必須。

## 留保：ゲームの年数無制限が完成したわけではない
- **本Stageの10000年度のA方式試合は意図的に生成した架空の合成データ。** 実際の全国予選・地区大会・甲子園を10000年度まで進行させたものではない。
- sidecarは過去のA方式試合を保全するが、既存`CareerPlayerRecordView`／`CareerPlayerStatCache`はこの新sidecarの10000年度選手統計をまだ計算しない。今回の合成例の選手IDは旧ロスターの恒久IDと結びついていない。正式に記録を通算する前に、年度別20人ロスター・卒業/入学・ID帰属・派生キャッシュ生成との統合が必要。
- 年度間の大会ランタイム・次年度ロスター・参加校・大会枠、2026大会カレンダーのゲーム内再利用ルール、実際の新年度試合生成は本Stageでは接続しない。sidecar年次計画は任意の対象年度に作れるが、実ゲーム開始許可は別のsealed年度＋大会ルール判定を要する。
- v2日時は旧YYYY-MM-DDに挿入できない。日付別read modelはサンドボックス専用で、現行GUIの本番画面とは分ける。
- `year_matches`と`day_matches`は選んだ年度の全レコードを検証したのちページングするため、大規模な数万試合／年度の安定した閲覧速度は保証しない。後工程で封印台帳・索引・DB分割を安全に連携する設計を検討する。
- SQLiteの年度は符号付き64bit上限があり、ディスク容量も有限。「実用上年数に上限を感じさせない」ための管理設計が今後必要。

## 次工程
Stage43G-28候補：v2側A方式を保存済み年度ロスターの**恒久選手ID**と照合して個人成績キャッシュ・歴代記録へ統合する検証、試合日付v2を正式な大会スケジューラへ接続する前提条件の契約化。既存のA方式原本とsidecarに二重保存しない段階的移行と、安全な差分バックアップも要検証。
