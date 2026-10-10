# Stage 43E：選手の進級・卒業・新入生と永続Player ID

策定日：2026-10-10
対象：ココシミュNew
依存：Stage 43D（PR #133、mainマージ済・マージ後CI成功）
位置づけ：**次年度の選手継続と履歴保存の基盤実装**。2027年度大会の本番生成・年度またぎセーブ操作・GUIはまだ未対応。

## 1. 設計方針

ユーザーの長期進行・歴代所属選手閲覧要件を踏まえ、次年度の全選手を再抽選しない。

1. **在学継続する1・2年生**：同じ `player_id`, `school_id`, `entry_year`, 氏名、守備位置、投打、roster_noを保持し、学年のみ+1する。
2. **3年生**：翌年度の現役20人ロスターから卒業させる。過去の年度ロスターと選手IDはSQLite履歴へ残す。
3. **新1年生**：卒業した選手が使用していたロスター枠へ補充。新規Player IDは `career_seed + school_id + 新入学年度 + roster_no` の独立した名前空間をSHA-256で導出し、同名の別人と重ならない。
4. **seed再現**：翌年度の同じ学校・seed・卒業枠なら新入生ID・氏名・投打は再現可能。他校の生成順序に影響されない。
5. **20人とポジション枠**：現在のゲームに用意されたコア20人と投手5・捕手2などの守備位置枠を維持。卒業枠に同ポジションの新1年生を配属する（現段階の暫定仕様）。

## 2. 学年人数の重要な調整

初年度は `GRADE_COUNTS={1:5,2:7,3:8}` に固定されている。翌年度もこの内訳を強制すると、既存1年生5人から2年生7人を作るために **存在しなかった2人の選手を後付け**しなければならず、経歴が破綻する。

このため、初年度生成と継続年度の学年構成を別ポリシーとする。

| 年度 | 1年生 | 2年生 | 3年生 | 合計 | 卒業した人数 |
|---|---:|---:|---:|---:|---:|
| 2026（初年度） | 5 | 7 | 8 | 20 | ― |
| 2027 | 8 | 5 | 7 | 20 | 8 |
| 2028 | 7 | 8 | 5 | 20 | 7 |
| 2029 | 5 | 7 | 8 | 20 | 5 |

- `SchoolRoster.cohort_policy="initial_v1"` は初年度の配分を厳密に維持し、既存のto_dict内容も変えない。
- `cohort_policy="career_v1"` は1～3年生の20人で、必ず進級元の年度記録を引き継いだロスター。初年度の学年比へ強制的に戻さない。
- **暫定**：20人は「試合用コアロスター」であり、本来の部員総数ではない。入部者数・途中退部・控え登録やポジション転向は後続で別仕様にできるようにする。
- 現在のプレースホルダー氏名は学年ごとに同名が生じ得るが、同名を統合しない。IDが人物同一性の正本。

## 3. 実装

| ファイル | 実装内容 |
|---|---|
| `game_core/players.py` | 既存2026生成契約を維持して`SchoolRoster.cohort_policy`と継続年度検証を追加 |
| `game_core/career_rosters.py` | `advance_school_roster`・`advance_rosters`。既存ロスターから翌年度への進級・卒業・補充を実施。変更結果のサマリを返す |
| `phase2_engine/career_roster_archive.py` | 学校×年度の完全ロスター、選手個体の不変属性を別SQLiteへ保存。過去の同一年度への改変・選手個体情報の衝突を拒否。学校と選手IDから履歴を読める |
| `game_core/tournament_bridge.py` | `AbilityMatchResolver(roster_provider=...)` を追加。提供者がいれば年度・学校に一致する保存済み選手を使用。欠損時に旧方式で別人を再生成しない。指定しない既存の2026経路は従来どおり |

履歴DBの使用例：

```python
from game_core.players import PlayerRosterGenerator
from phase2_engine.career_roster_archive import CareerRosterArchive

generator = PlayerRosterGenerator()
initial = generator.generate_for_school_id(repo, school_id, 2026, seed)
archive = CareerRosterArchive("out/saves/<slot>/career_rosters.sqlite3")
archive.save_initial_roster(initial)

archive.advance_and_save(
    repo.team(school_id), next_year=2027, career_seed=seed,
)
old_roster = archive.roster(2026, school_id)
new_roster = archive.roster(2027, school_id)
same_person_history = archive.player_history(old_roster.players[0].player_id)
```

能力試合側は：

```python
from game_core.tournament_bridge import AbilityMatchResolver
resolver = AbilityMatchResolver(repo, roster_provider=archive.roster)
# 年度・学校に対応する保存済み roster から TeamMatchInputを構築
```

実行順序は必ず `2026登録→2027へ進級→2028へ進級`。年度を飛ばしたり、保存済み2027年を別seedの別人に置き換えたりする操作は拒否する。

## 4. 履歴データモデル

`CareerRosterArchive` のSQLite構造：

- `career_school_rosters`: `(year, school_id)` を複合主キーとし、学校年度の20人全員の正本JSONとSHA-256を保持。
- `career_player_identities`: `player_id` を主キーとし、氏名・学校・入学年度・守備位置・投打などの固定属性を保存。学年は除いて照合する。
- `school_years(school_id)`: 学校の保存済み全年度を返す。
- `player_history(player_id)`: 入学から卒業までの各年度の学年・所属・ロスター番号を返す。
- `roster(year, school_id)`: その年度の全選手を復元。バイト破損・指紋不一致や検証エラーは拒否する。

既存の `HistoricalMatchArchive` は「試合」正本、新しい`CareerRosterArchive`は「全選手の在学歴」正本。年度確定トランザクションへの一体化は**Stage43F/43G以降の課題**であり、本Stage単独では2種類のSQLiteの同時commitを保証しない。

## 5. 受入とテスト

`tests/test_stage43e_career_rosters.py`：

- 2026初年度のseed結果・人数配分が変わらない。
- 2026→2027→2028→2029の進級・卒業と同一選手IDが一致。
- 2036年までの10年連続テストで20人・守備位置枠・ID重複なし。
- 別学校とのID衝突なし、生成順に依存しない。
- 年度飛び・seed変更・学校変更拒否。
- 元ロスターの不変性、継続年度のCSV互換。
- SQLiteの読出し・同年度再保存冪等・改変拒否・途中失敗のロールバック・履歴検索。
- 能力モデル試合が同じ選手IDを参照し、年度欠損なら再生成しない。

## 6. 残る作業

1. 2026→2027の実際の`LiveGameService`で、試合用ロスターを`CareerRosterArchive`から選ぶ起動処理と、年度ごとの再開・復元を設計する。
2. 2027年度の大会・選抜等の前年秋成績の引継ぎ、ゲーム内生成日程の構造化。
3. 同一選手の年齢・能力・成長曲線、負傷や退部、全所属部員とベンチ登録、守備位置変更を別契約で実装する。
4. 全学校の年度開始ロスター確定・年度途中転入／退部・年度終了の原子的保存。
5. 100・500・1000年相当の履歴件数で、SQLiteサイズ、選手履歴照会、バックアップ／復元の性能と容量を監査する。
6. 2026時点の学校・大会の公式資料を、将来年度の実際の公式結果や正式日程であるかのように扱わない。

**現時点では複数年のゲーム進行・正式GUIを実装したという意味ではない。** 現実の加盟校一覧と、ゲーム内の選手・試合は引き続き区別する。
