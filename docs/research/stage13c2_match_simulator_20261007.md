# Stage 13C-2 能力ベースMatchSimulator 実装報告

作成日: 2026-10-07

## 目的

Stage 13C-1のcontractを満たす、最初の完全試合シミュレータを実装する。

最終得点を直接生成するのではなく、PlayerAbilityを使った打席eventからscoreと個人成績を同時生成する。

## 実装

`game_core/match_simulator.py`

### MatchSimulator

実装済み:

- 9人打順循環
- batter vs pitcher event weight
- pitch repertoire quality反映
- defense_strength反映
- runner identity付きbase state
- single / double / triple / HR進塁
- BB / HBP force advance
- reached_on_error
- fielder_choice
- sacrifice bunt
- sacrifice fly
- 3out inning progression
- 9回
- 延長
- 9回裏省略
- walk-off
- PitchingStaff順の継投
- BatterGameStats集計
- PitcherGameStats集計
- TeamGameStats集計
- MatchEvent生成
- Stage 13C-1 final reconciliation

### Tournament同期

`synchronize_tournament_match()`

で能力試合結果を既存 `phase2_engine.models.Match` へ同期できる。

同期項目:

- winner
- loser
- score_source
- team1_score
- team2_score
- last_inning
- ending_half

Stage 13C-2ではTournamentEngine全体のresolver差し替えまでは行わず、同期境界を用意した。

## Match config revision 2

status:

`design_default_not_tuned`

### base PA probabilities

- SO 0.190
- BB 0.080
- HBP 0.010
- 1B 0.155
- 2B 0.045
- 3B 0.006
- HR 0.025
- ROE 0.020
- FC 0.019
- field out 0.450

合計1.0。

これらをそのまま最終確率にはせず、能力差によりweight調整する。

## Ability connection

### batter

- contact
- power
- plate_discipline
- strikeout_resistance
- bunt
- speed
- baserunning

### pitcher

- stuff
- control
- strikeout
- groundball
- stamina
- pitch repertoire quality

### team

- defense_strength

TeamStrengthの総合値を直接scoreへ加算しない。

## Pitcher usage

starting aceからPitchingStaff order順に使用。

交代理由:

- batters faced threshold
- stamina
- runs allowed quick hook

v1ではbatting lineupとpitcher substitutionを分離しており、投手交代後も打順上の先発投手は置換しない。

## Simplifications

未実装:

- 盗塁
- 代打
- 守備交代
- double play
- wild pitch / passed ball
- balk
- pitcher responsibility for inherited runners
- 詳細なearned run判定
- 大会固有コールド
- タイブレーク
- 球種別打者相性

これらを無理にStage 13C-2へ詰め込まず、contractを維持したまま後続revisionで追加する。

## Tests

Stage 13C-2専用回帰テストで確認:

- 完全試合seed再現
- tieなし
- Stage 13C-1 reconciliation
- event / PA連番
- batting order循環
- event catalog制約
- score/event runs一致
- batter/pitcher hit整合
- PA/BF整合
- match namespace isolation
- short regulation override
- 強打者event weight方向性
- 強投手SO weight方向性
- multiple pitcher usage
- Tournament Match同期
- revision/status

初回GitHub Actions:

- 417 tests
- `Ran 417 tests in 9.312s`
- OK

## Distribution audit

3seed × 1,000 games = 3,000 games。

各seedで240校を生成してpairing。

主結果:

- mean total runs: 9.80〜9.91
- P50: 9
- P95: 19
- one-run games: 24.5〜26.2%
- shutout: 10.7〜12.2%
- extra innings: 7.1〜8.2%
- team2 win: 48.7〜52.3%
- stronger overall win: 61.4〜62.2%
- SO/PA: 19.28〜19.45%
- BB/PA: 7.84〜8.03%
- H/PA: 22.81〜22.93%
- HR/PA: 2.58〜2.62%
- pitchers used/team: 3.176〜3.213

能力差5〜10ではstronger側勝率66.5〜76.3%、10以上では75.8〜90.7%。

## Interpretation

エンジンとしての初期要件は満たす。

ただし実在高校野球への校正は未実施なので、「現実と一致した率」とは扱わない。

特にmax total runs 28〜40のtailはコールドルール導入前でもあり、今後要監視。

## 次工程

Stage 13C-3候補:

- TournamentEngineのwinner_resolverをMatchSimulatorへ正式接続
- CompetitionRunにability_model_v1のscoreを保持
- ResultViewへ自動供給
- 複数試合で同一選手のGameStatsを保存

その後Stage 13Dで個人成績read model / ランキングへ進む。
