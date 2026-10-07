# Stage 13D-2 Player Master / GUI Contract 実装報告

作成日: 2026-10-07

## 目的

Stage 13D-1で作成した個人成績read modelへplayer masterを接続し、学校ロスター・選手詳細・大会ランキングのGUI境界まで完成させる。

## Identity seed修正

従来:

```
competition seed
 -> roster
 -> player ability
 -> team strength
 -> match RNG
```

Stage 13D-2:

```
season seed
 -> roster / identity
 -> player ability
 -> team strength

competition match seed
 -> match RNG
```

へ分離した。

AbilityMatchResolver.begin_season()でseason team generation seedを固定する。

## Player master

AbilityMatchResolverは生成済みSchoolRosterを保持し、
player_master_records()で1選手1rowへ正規化する。

SeasonOrchestratorはseason終了時にSeasonExecution.player_master_recordsへsnapshotする。

## SQLite

BrowseRepository schema v3。

追加:

- player_master

read API:

- player_record
- school_roster
- search_players

save_season_browse_repository()は

1. browse views
2. player master
3. GameStats / MatchEvent

の順で保存する。

## Stats join

Stage 13D-1 aggregateへplayer_master LEFT JOINを追加。

追加表示項目:

- player_name
- academic_year
- roster_no
- primary_position
- bats
- throws

masterがない場合はplayer_id等へfallback。

## GUI contract

BrowseGuiModel:

- search_players
- school_roster_stats
- player_detail
- competition_leaderboards

正式画面実装は後続。

## Regression

専用fixtureで確認予定:

- match seedが異なってもplayer identity固定
- player master重複なし
- SQLite v3保存
- 20人school roster
- bench player表示
- player name join
- player search
- competition leaderboard display payload
