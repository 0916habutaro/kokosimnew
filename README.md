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
- Stage 13D-1: SQLite GameStatsの整数countから大会別／シーズン別の個人成績read modelを実装。AVG/OBP/SLG/OPS/ISO、ERA/WHIP/K/9/BB/9/K/BB/K-BB%を導出し、規定到達を考慮した打撃・投手ランキングとBrowseGuiModel APIを追加
- Stage 13D-2: 試合seedと選手identity seedを分離し、同一シーズンのplayer_idを大会横断で固定。SQLite schema v3へplayer_masterを追加し、学校ロスター成績・選手詳細・選手検索・大会ランキングのGUI read契約を実装
- Stage 13D-3: 既存read-only Tkinter GUIへ選手検索・選手詳細・学校20人ロスター・大会別打撃/投手ランキングを追加。学校→ロスター→選手、大会→ランキング→選手の画面遷移を実装
- Stage 13E-1: SeasonRuntimeStateを追加し、ゲーム内current_date、pending/completed/unscheduled、play_today/next_day/advance_to/advance_throughを実装。未来のscore/winner/ability detailを非公開のまま、消化済み試合だけ学校戦績・大会状態へ反映
- Stage 13E-2: MAINトーナメントをbracket skeletonと勝敗解決へ分離。MainTournamentRuntimeState / ScheduledMainTournamentRuntimeを追加し、ready matchだけを当日にMatchResolver実行するlazy・resumable進行を実装。random/Ability双方でlegacy一括runとのCompetitionRun完全一致を検証
- Stage 13E-3A: pre-MAIN共通runtime primitive（single elimination / gate / round robin / block forest）を追加し、FMT001 qualifier→MAINをlazy化。北海道春CMP000004でlegacy CompetitionRun完全一致を検証
- Stage 13E-3B-1: FMT006の3〜4校POOL_RR→3校pool2位CROSS_PLAYOFF→MAINをlazy化。神奈川春CMP000095でrandom/detailed resolver・annual pool overrideのlegacy CompetitionRun完全一致を検証
- Stage 13E-3B-2: FMT002〜005 / 007〜017 / 025の複合qualifierをlazy phase composition化。PRIMARY→敗者復活/SECONDARY、league/zone→secondary、FMT005 global repechage、mixed-model stageを対象20大会でlegacy CompetitionRun完全一致検証
- Stage 13E-3B-3: SEED_EVENT系FMT001 / 009 / 018〜024、岐阜秋FMT026 gate、愛媛秋seed→qualifierをlazy化。seed完了前は後続stageを生成せず、対象9大会でlegacy CompetitionRun完全一致を検証
- Stage 13E-3C: ScheduledCompetitionRuntime / LiveSeasonRuntimeStateを追加し、ready frontierだけを大会日程へ割り当ててcurrent_date当日にMatchResolverを実行。北海道春qualifier→MAIN・岐阜秋seed→gate→MAINを日付進行してlegacy CompetitionRun完全一致を検証。pre-MAIN日付不足はcalendar gapとして停止
- Stage 13E-3D-1: 2026 pre-MAIN stage calendar masterを49 stageで新設し、全件research_pendingとしてMAIN日程の誤流用を防止。同年competition_access_rulesをlive dependency化し、宮城の夏優勝→秋直接出場、三重の夏優勝→秋SEED_EVENT免除＋seed付与をsource公式最終日まで遅延してactivate。両destinationでlegacy CompetitionRun完全一致を検証
- Stage 13E-3D-2: qualification_rules 59件・regional_feeder_rules 96件・近畿regional playoff 2件をLiveSeasonDependencyRuntimeStateへ接続。49地方大会→夏甲子園、四国4県→春季四国、近畿playoff、秋10代表→神宮entrant生成をlive化し、夏甲子園・春季四国ではlegacy CompetitionRun完全一致を検証
- Stage 13E-3D-3: LiveSeasonGraphPlannerを追加し、2026全162大会・165 dependency edge・season calendar 162件・pre-MAIN stage calendar 49件からannual templateとtopological live graphを自動構築。131 root / 31 dependency待ちで起動し、49地方大会→夏甲子園・東西東京夏優勝→秋東京232校構造まで手動AnnualCompetitionInputなしで自動materializeする回帰を確認
- Stage 13E-3E-1: full-season live runtimeのJSON save/load v1を実装。plan fingerprint＋processed date＋完了MatchResolutionからfresh runtimeをdeterministic replayし、current_date・dependency状態・activated_on・score/ability detailまで完全照合して再開。atomic write、checksum、resolver contract、plan変更・改ざん検出を追加
- Stage 13E-3E-2: SaveSlotManager / LiveGameServiceを追加し、1スロット内でmanual/autosaveを独立管理。世代backup、latest判定、旧世代復旧、slot一覧・削除、new/load/save/autosave、日付進行後autosaveをservice化。実full-season new_gameで162 template / 131 active / 31 waitingを起動しinitial manual saveまで確認
- Stage 13E-3E-3: user-facing `slot_metadata.json`、破損saveを隔離できるrecovery source一覧、backup→primary復旧昇格、SaveMigrationRegistry、LiveGameService CLIを追加。CLIはnew/list/status/recoveries/rename/save/recover/play-today/next-day/advance/deleteをservice経由で実行し、fake旧schema→現行v1 migration・unknown schema拒否も回帰確認
- Stage 13E-3F-1: 2026 full-season live runtimeを12/31までE2E監査。162大会中98完了、calendar gap 46、dependency待ち16、runtime blocked 2を確認。49 pre-MAIN pending rowsをP0/P1/P2へ優先度付けし、秋田秋CMP000079の前段予選未構造化疑い1件と神奈川春CMP000095・愛知春CMP000113のSenbatsu access解決失敗2件を追加blockerとして52 actionへ整理

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

python -m phase2_engine.live_game_cli \
  --data-dir data \
  --save-root out/saves \
  new slot01 \
  --seed 2026100801 \
  --title "2026年シーズン"

python -m phase2_engine.live_game_cli \
  --data-dir data \
  --save-root out/saves \
  list

python -m phase2_engine.live_game_cli \
  --data-dir data \
  --save-root out/saves \
  next-day slot01

python -m phase2_engine.live_game_cli \
  --data-dir data \
  --save-root out/saves \
  recoveries slot01

python -m phase2_engine.full_season_live_audit_cli \
  --data-dir data \
  --year 2026 \
  --seed 2026100827 \
  --output-dir out/full_season_live_audit

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

## Stage 13E-3G-6（静岡の大会ブロックと恒常地区の区別・広島の試合分類）

2026年秋季静岡県大会予選で、**藤枝明誠―沼津東は異なる恒常地区に属するI・Jブロック代表同士の上位決定戦**であることを確認。学校の地理的地区は変更せず、追加順位イベント`XBLOCK_I_J@D20260830`を明示学校ID2校・出場権確定後に限り生成できる。

- `post_qualification_cross_block_pairs.csv`：2026実証ブロックI/J・学校ID・資格固定・資料URL
- `ranking_cross_block_2026.py`：史実結果を転用しない安全な非blocking順位イベントと広島資格決定戦の保護
- 広島春秋の既知3試合は、県大会出場権を決める試合として順位戦から隔離。全地区のその他試合は追加検証が必要
- FMT025の完全な再現とGUIは未完のため、`RS2026026`を`design_pending`のまま維持

報告：`docs/research/stage13e3g6_cross_block_hiroshima_20261008.md`

## Stage 13E-3G-5（同地区・複数日順位戦と旧DB互換）

順位決定戦の`event_id`を任意で追加し、**同じ地区の複数日イベントを別々に保存・閲覧・再開**できるようにした。静岡春西部地区の4月4日と11日を回帰テストで再現する。

- 旧順位戦ID／snapshotはそのまま読み込める。`event_id`ありだけ`group_id@event_id`とする
- `ScheduledCompetitionRuntime`は複数イベントを同時保持。任意順位戦は代表・シードや大会完了に影響しない
- SQLiteは旧表を維持し、専用v2 snapshot表と`ranking_instance_id`列を安全に追加
- 異なる日付の順位戦を上書きせず、旧データと新データを同一日付／大会別read modelで閲覧
- 静岡秋の越境1件と広島の代表決定・順位決定区分の追加調査は未完。研究台帳RS2026025/26は保留維持

日本語設計：`docs/design/post_qualification_multi_instance_stage13e3g5.md`

## Stage 13E-3G-4（既存学校ID・地区所属の正式照合）

大容量ファイル取得の問題により空と誤認していたPhase 1マスターの実体を確認。**学校3,746校・野球部3,746件・2026地区所属6,871件は既存mainに登録済み**であり、再作成や上書きは行わない。

- `data/competitions/2026/post_qualification_rank_school_aliases.csv`：学校名略称11件の明示ID対応
- `data/competitions/2026/post_qualification_rank_school_mapping.csv`：歴史的観測34試合の両校school_idと地区対応。53校すべてをID対応
- FMT022の5試合は代表・シード校の確定後のみ実行可能。静岡FMT025は同地区25試合をgroup確定、藤枝明誠（中部）―沼津東（東部）の1件は跨地区となり保留
- 広島の代表決定戦3件は資格確定に影響するため、非blocking順位戦へ**登録禁止**
- `phase2_engine/ranking_school_reconciliation_2026.py`：全マスター整合監査と資格済み校限定FMT025**単日**sidecar生成
- 同一地区の**複数日**順位戦は現行group単位sidecarでは試合IDが衝突するため、次工程でインスタンスキー対応を設計する。RS2026025/26は設計保留のまま

調査報告：`docs/research/stage13e3g4_school_area_reconciliation_20261008.md`

## Stage 13E-3G-3（2026実大会の順位戦対戦カード照合）

2026年の徳島・沖縄・静岡について、**確認できた順位決定戦31試合**を実日付・学校名・スコア・出典付きで参照用CSVに保存。広島の代表決定戦3試合は`qualification_decider_not_ranking`として別分類し、任意の順位戦へ自動投入しない。

- `data/competitions/2026/post_qualification_rank_observations.csv`：歴史的観測34レコード
- `phase2_engine/ranking_reference_2026.py`：試合参照CSVの整合性監査と、学校ID・資格済み4校を**明示照合**できたFMT022だけの未実施fixture生成
- 3G-4でGit blobを再取得した結果、学校マスター3,746校・2026地区所属6,871件が存在すると確認。空判定は大容量ファイル取得の問題による誤認。FMT025は25件の同地区groupまで明示照合し、越境1件を保留
- 架空年度の勝者・スコアを2026実試合の勝敗で上書きしない
- 静岡・広島の正式地区紐付けと参照試合の資格分類が残るため、RS2026025/RS2026026は`design_pending`のまま継続

調査報告：`docs/research/stage13e3g3_official_ranking_20261008.md`

## Stage 13E-3G-2（任意順位決定戦のスケジュール・保存・結果閲覧）

代表・シード確定後の任意順位試合を、**明示した試合日だけ**年間の`today_matches()`へ表示し、専用`play_today_rankings()`で勝敗を入力できるようにした。既存の大会完了・進出・年間E2E依存判定を変更しない。

- `ScheduledRankingSidecar`：日付、試合中止、勝者・スコア、途中セーブ/再開
- `ScheduledCompetitionRuntime` / `LiveSeasonDependencyRuntimeState`：任意順位試合の登録、一覧、明示的進行
- `BrowseRepository`：専用SQLite表に保存し、日付別・大会別に追加順位戦を閲覧
- FMT025等の年度別カードが未確定の場合、日程・相手を推測せず**未登録**
- FMT022/FMT025研究タスクは完全な実大会再現までdesign_pendingを維持

設計：`docs/design/post_qualification_schedule_stage13e3g2.md`

## Stage 13E-3G-1（代表決定後の任意順位決定戦）

FMT022（徳島・沖縄）とFMT025（静岡・広島）について、**代表・シード枠を固定した後だけ**試合を行う非blocking順位戦の独立ランタイムを追加した。

- `phase2_engine/post_qualification_ranking.py`：2ブロック決勝／準決勝＋決勝／明示ペア順位決定、途中結果の保存・再開。
- `data/competitions/post_qualification_ranking_profiles.csv`：県・方式別プロファイル6大会。
- `TournamentEngine.prepare_post_qualification_ranking()`：既存StageExecutionの確定出力校を利用する**明示オプトインAPI**。
- 既存の`CompetitionRun`、シード割当・県本戦進出校・年度スケジューラは変更しない。日付・実スコアを推測して増やさない。
- 後続3G-2で任意順位試合の日付処理・セーブ・read modelとの接続を検討。FMT022/FMT025の調査台帳（RS2026025/26）はこの段階では設計保留を維持。

日本語設計：`docs/design/post_qualification_ranking_stage13e3g1.md`

## 最新工程（Stage 13E-3F-4）

2026年全162大会の年間E2E監査を実施。**ゲーム内のシミュレーションとして161大会を完了**し、神宮大会CMP000003の個別日程が未公開のため1大会が保留。pre-MAIN日程は50/50件verified、研究待ち0件。大会数・進出依存関係・日付・CSV正規化を監査する。なお、実際の2026年の全大会が終了したという意味ではない。

岐阜県秋季大会では一次（8/29・30・9/5）と二次（9/5以降）が同日に重なる9/5を根拠付きで許可し、MAINから一次専用の8/29・30を除外した。ほかの予選／MAIN日付重複は検出する。

```bash
python -m phase2_engine.final_season_integrity_audit_cli \
  --data-dir data --year 2026 --seed 2026100827 \
  --output-dir out/final_season_integrity_audit
```

結果はJSON・CSVに出力され、未公開日程と未確定設計はDEFERREDとして明示する。研究報告：`docs/research/stage13e3f4_final_season_integrity_20261008.md`。

次は2026/10/17以降の神宮高校部公式抽選・個別日程公開の確認（RS2026022）と、順位決定戦の残存2方式FMT022/FMT025（RS2026025/26）の設計を進める。正式GUIは引き続き中核機能の確認後に実装する。
