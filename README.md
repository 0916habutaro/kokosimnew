# KokoSimNew / ココシミュNew

高校野球の大会構造・日程・試合進行を扱うゲーム用データ／エンジンの管理リポジトリ。

## 現在地
- Phase 1: 完了（47都道府県、学校 3,746、硬式野球部 3,746）
- Phase 2: Stage 12M完了（Stage 12M-1〜8で夏地方49大会すべてを個別実試合日へ詳細化）
- Stage 12G: 全国47都道府県の春秋94大会の日程を `season_calendar.csv` に正式反映済み
- 県春秋94大会の日程: official_schedule 94 / research_pending 0
- Stage 12G初回試合日: 累計809日。Stage 12I再照合で福岡秋10/14を追加し、現在のmasterは810日相当
- 夏地方大会の個別試合日: 49 / 49大会を実績化済み（Stage 12M-1〜7 累計511日＋12M-8 118日＝累計629日、残り0大会）
- 秋季実績再照合: 2026-10-06 EODに県大会6件を実績更新。埼玉は完了、県大会残件18・地区大会残件9
- Stage 12N: 秋季残件の将来予定日を再照合カレンダー化。県18＋地区9＝27追跡行（26大会）、最初のcheckpointは10/7北海道・福岡
- Stage 12O: checkpoint駆動の再照合キュー生成を実装。指定日までのtoday_pending / overdueを自動抽出
- Stage 12P: 観戦用試合結果read modelを実装。seed再現スコア・学校表示名・実スコアoverride対応
- Stage 12Q: 日付別試合一覧・大会別結果一覧・学校別戦績の閲覧read modelを実装
- Stage 12R: 3閲覧read modelのSQLite永続化・GUI向けrepository層を実装
- Stage 12S: SQLite repositoryを読むread-only GUIを実装（年度・日付別試合・大会結果・学校戦績）
- Stage 12T: GUI実行確認＋日付画面の大会/都道府県フィルタ＋トーナメント表示＋学校/大会間の画面遷移
- Stage 12U: ホーム画面＋都道府県名表示＋春夏秋/大会種別フィルタ＋トーナメント学校クリック
- Stage 13A: 架空選手・学校ロスター基盤を実装。1校20人をseed再現生成し、player_id・学年・守備位置・投打・所属を構造化
- Stage 13B-1: 能力生成前の設計・変更管理基盤を固定。能力カタログ、1-100尺度、学校能力算出原則、version/revision、RNG namespace、ADR、調整JSONを正本化
- Stage 13B-2: PlayerAbilitySnapshotのseed再現生成・分布監査を実装
- Stage 13B-3: StartingLineup / PitchingStaff / TeamStrengthSnapshotを実装
- Stage 13B-4: 合成program成分＋cohort成分による学校別入部品質モデルを実装。3seed×各1,000校のbaseline/intake比較監査で、batting_strength sd約1.7→4.2、pitching_strength sd約2.4→4.6〜4.8
- Stage 13C-1: 能力ベース試合の入出力、MatchEvent、打者/投手/チームGameStats、winner ownership、ResultView `ability_model_v1` 接続、event/stats reconciliation contractを実装
- Stage 13C-2: batter vs pitcher能力から打席eventを生成し、base/out state・9回＋延長・walk-off・投手継投・個人成績を一貫生成するMatchSimulatorを実装。3seed×各1,000試合監査で平均総得点9.80〜9.91、stronger側勝率61.4〜62.2%
- Stage 13C-3: TournamentEngineのMAINへAbilityMainMatchResolverを正式接続。能力試合のscore/winnerがブラケット進行・CompetitionRun・ResultViewへ自動反映され、GameStats / MatchEventの大会単位保存にも対応
- Stage 13C-4: pre-MAIN共通bracketへMatchResolutionを展開し、AbilityMatchResolverをMAIN/pre-MAIN共通化。SeasonOrchestratorから能力モデルをopt-in可能にし、GameStats / MatchEventをBrowseRepository SQLite schema v2へ永続化

## ディレクトリ
- `data/master/` 学校・加盟校・出典の基礎マスター
- `data/areas/` 地区区分・学校所属
- `data/competitions/` 大会・stage・進出・seed・format・地域大会接続
- `data/schedules/2026/` 2026年日程マスター／試合日
- `data/sources/` Phase 2調査出典
- `phase2_engine/` 大会・シーズン共通エンジン
- `game_core/` 選手・能力・個人成績・年度進行などゲーム本体の中核機能
- `config/abilities/` 能力定義・生成分布・学校能力集約のversion付き調整値
- `config/match/` 能力ベース試合・event catalog・個人成績contract
- `docs/design/` 能力・学校能力・調整運用の設計正本
- `docs/adr/` 設計判断記録
- `docs/tuning/` 能力・試合モデルの調整履歴
- `tests/` 回帰テスト
- `audits/` Phase/Stage別の監査・manifest・validation
- `archive/snapshots/` 移管元の完成ZIP（復旧用）

## 実行
```bash
python -m unittest discover -s tests -v
python -m phase2_engine.season_cli --data-dir data --year 2026 --seed 2026100501
python -m phase2_engine.reconciliation_cli \
  --queue audits/phase2/stage12i/stage12i_autumn_reconciliation_queue_20261006.csv \
  --as-of 2026-10-06 \
  --output audits/phase2/stage12i/stage12i_recheck_status_20261006.csv

python -m phase2_engine.recheck_calendar_cli \
  --calendar data/schedules/2026/autumn_recheck_calendar.csv \
  --as-of 2026-10-07 \
  --output audits/phase2/stage12o/stage12o_due_queue_20261007.csv

python -m phase2_engine.season_cli \
  --data-dir data \
  --year 2026 \
  --seed 2026100501 \
  --result-dir out \
  --sqlite-db out/kokosim_browse.sqlite3

python -m phase2_engine.browse_gui \
  --db out/kokosim_browse.sqlite3 \
  --data-dir data

python -m game_core.player_cli \
  --data-dir data \
  --year 2026 \
  --seed 2026100701 \
  --school-id SCH000001 \
  --output out/players_SCH000001.csv

python -m game_core.ability_cli \
  --data-dir data \
  --config-dir config/abilities \
  --year 2026 \
  --seed 2026100701 \
  --school-limit 1000 \
  --output out/abilities.csv \
  --audit-output out/ability_audit.csv

python -m game_core.team_strength_cli \
  --data-dir data \
  --config-dir config/abilities \
  --year 2026 \
  --seed 2026100701 \
  --school-limit 1000 \
  --output out/team_strength.csv \
  --audit-output out/team_strength_audit.csv

python -m game_core.stage13c2_audit \
  --data-dir data \
  --ability-config-dir config/abilities \
  --match-config-dir config/match \
  --year 2026 \
  --school-count 240 \
  --game-count 1000 \
  --output out/stage13c2_match_audit.csv
```

## 正本ルール
展開済みの `data/`, `phase2_engine/`, `tests/` を正本とする。`archive/snapshots/` のZIPは復旧用で、日常編集には使用しない。

## 次工程
正式GUIの作り込みはいったん保留し、ゲーム中核機能を優先する。Stage 13C-4でMAINだけでなくSEED_EVENT・地区予選・gate・league等が利用する共通bracketへMatchResolutionを展開し、SeasonOrchestratorから同じAbilityMatchResolverをMAIN/pre-MAIN双方へ注入できるようになった。BrowseRepositoryはschema version 2となり、ability_matches / batter_game_stats / pitcher_game_stats / team_game_stats / match_eventsを同一SQLiteへ保存できる。岐阜秋58校のSEED_EVENT→FIRST_TOURNAMENT→MAIN実走でも全非bye試合がability_model_v1で完走済み。次工程はStage 13D-1としてSQLiteのGameStatsから打者・投手の大会/シーズン集計、AVG/OBP/SLG/OPS、ERA/WHIP/K-BB等のread modelとランキングを実装する。秋季実績はStage 12Oのdueキューで後追い可能。
