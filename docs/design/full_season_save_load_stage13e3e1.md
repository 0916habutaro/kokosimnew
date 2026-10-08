# Stage 13E-3E-1 full-season save/load contract

作成日: 2026-10-08

## 目的

Stage 13E-3D-3で2026全162大会をLiveSeasonGraphPlannerから
自動構築・日付進行できるようになった。

Stage 13E-3E-1では、そのlive runtimeをゲーム終了後も
同一状態から再開できるversion付きsave/load contractを定義する。

対象:

- current_date
- 処理済み日付
- 完了試合
- score / winner / resolver detail
- active competition
- completed competition
- waiting dependency
- activated_on
- deferred未materialize competition
- plan seed
- resolver contract

未来の勝敗・未materialize大会の参加校はsaveへ書かない。

## schema

schema_version:

stage13e3e1.live-season-save.v1

JSON UTF-8を正本とする。

pickleやPython object graphの直接保存は行わない。

## 保存方式

live runtime内部の多数のruntime classを直接serializeしない。

保存するのは再構築に必要なstable event/state contract。

### identity

- year
- rng_seed
- resolver_contract
- plan_fingerprint

### clock

- start_date
- current_date
- processed_dates

processed_datesはplay_today済みの日を表す。

現行runtime APIではstart_dateから連続している必要がある。

save時current_dateは

- 最後に処理した日そのもの
- 最後に処理した日の翌日

のどちらか。

これにより「当日試合実行前」と「当日試合実行後」を区別できる。

### completed_match_results

completed matchのみ保存。

各matchについてScheduledRuntimeMatchのstable dataを保存する。

- competition_id
- match_id
- match_date
- date_source
- stage / phase / round
- participant
- winner / loser
- team1_score / team2_score
- score_source
- ability_detail

pending matchは保存しない。

未来participantはplan/runtimeから再生成する。

### dependency

- status_by_competition
- activated_on
- runtime_summary
- public_snapshot_fingerprint

### history

runtime historyを保存する。

restore検証完了後、replay中に再生成されたhistoryを
saved historyへ置換する。

## plan fingerprint

plan_fingerprintは以下のcanonical JSONをSHA-256する。

- LiveSeasonPlanEntry
- AnnualCompetitionInput templates
- annual_build_strategies
- season calendar
- stage calendar
- dependency edges
- topological order
- external access bootstrap resolutions
- planner warnings
- year / rng_seed

学校・大会構造・日程・依存規則の変更でplanner出力が変われば
loadを拒否する。

silent migrationは行わない。

## payload checksum

payload_checksumはchecksum fieldを除くsave bodyのcanonical JSONを
SHA-256する。

ファイル破損や単純な手編集を検出する。

checksumを再計算して改ざんされた場合でも、
restore replay resultとの比較で検出する。

## restore algorithm

1. JSON schema / checksum検証
2. save year / rng_seed / resolver_contract検証
3. plannerから現在のLiveSeasonGraphPlanを再構築
4. plan_fingerprint一致確認
5. saved start_dateでfresh runtimeを起動
6. processed_dates最終日までlive runtimeを再実行
7. saved current_dateが翌日ならclockだけ1日進める
8. completed match result完全比較
9. dependency status比較
10. activated_on比較
11. public snapshot fingerprint比較
12. runtime summary比較
13. saved historyを復元
14. runtimeを返す

内部runtime objectをdeserializeしないため、
implementation detailへのsave format依存を抑えられる。

## resolver contract

saveにはresolver_contract stringを必須保存する。

default:

default_deterministic_v1

AbilityMatchResolver等を使う場合は、
ゲーム側が能力試合モデルversionを渡す。

例:

ability_model_v1

load時にresolver_contractが違えば即時拒否する。

さらに同じcontractでも実際のreplay resultが異なれば
LiveSeasonSaveReplayErrorとする。

つまりcontract名だけでなく結果レベルでも整合性を確認する。

### replay requirement

v1ではstored MatchResolutionをruntimeへ強制注入せず、
同一resolverで再演算してsaved resultと照合する。

したがってresolverは同一contract内でseed再現可能である必要がある。

現在のrandom resolver / ability modelはseed再現を前提としているため、
既存ゲーム設計と一致する。

将来、外部APIや非決定論resolverを導入する場合は
authoritative result injection migrationを別schemaで追加する。

## JSON file I/O

write_live_season_save():

1. destination.parentを作成
2. destination + ".tmp"へUTF-8 JSON出力
3. Path.replaceでfinal pathへ置換

途中クラッシュで既存saveを中途半端なJSONへ直接上書きしない。

read_live_season_save():

- JSON decode
- schema validate
- restore replay

を一括実行する。

## deferred competition

save時点でまだmaterializeされていないdependency destinationは
AnnualCompetitionInput実体をsaveしない。

plan fingerprint / status / clockからrestore時にもwaiting状態を再現する。

source resultが将来確定すると、
3D-3のdeferred structural builderが同じseedでmaterializeする。

これによりfuture participant leakを避ける。

## validation scenario

宮城mini graph:

CMP000029 夏宮城
→ ACR000002
→ CMP000077 秋宮城

### save point A

start_date=2026-07-01

advance_to(2026-07-28)

状態:

- processed through: 2026-07-27
- current_date: 2026-07-28
- CMP000029 runtime resultは内部確定済み
- official release 7/28は未処理
- CMP000077 runtime未materialize

この状態をsave→restore。

public_snapshot / history完全一致。

restore後play_today()で両runtimeとも同じCMP000077をactivate。

### save point B

7/28処理後。

CMP000077 materialize済み状態をJSON fileへatomic write。

read/restore後、

- public snapshot
- history
- dependency state

完全一致。

さらに8/2まで双方を進行して一致。

### scored resolver

custom deterministic resolver:

- 4-2
- score_source=save_test_v1
- ability_detail marker

を保存・replayし、detailまで一致することを確認。

## failure behavior

以下ではloadを拒否する。

- unsupported schema
- checksum mismatch
- year mismatch
- rng seed mismatch
- resolver contract mismatch
- plan fingerprint mismatch
- completed result mismatch
- dependency status mismatch
- activation date mismatch
- public snapshot mismatch
- runtime summary mismatch

壊れたsaveをbest effortで続ける挙動はv1では採用しない。

## 次工程

Stage 13E-3E-2候補:

- save slot metadata / slot一覧
- autosave policy
- rolling backup
- game startup facade
  - new_game
  - load_game
  - save_game
- SQLite browse read modelとのsave世代紐付け
- schema migration registry

pre-MAIN stage calendar verified化は並行して継続する。
