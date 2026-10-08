# Stage 13E-3F-2 P0秋季pre-MAIN解消・神宮chain監査報告

作成日: 2026-10-08

## 目的

Stage 13E-3F-1で抽出したP0 national chainを優先し、以下を実施した。

1. 秋田秋 `CMP000079` の未構造化pre-MAINを確定する
2. 秋季P0 pre-MAIN 28件の実施日をverified化する
3. verified化後に残ったruntime calendar gapを実装不整合とデータ不足へ切り分ける
4. 年末Live E2Eを再実行し、秋地区大会→神宮chainの改善量を測定する

実行条件:

- year: 2026
- seed: 2026100827
- start: 2026-01-01
- processed through: 2026-12-31
- 仮日付なし

## 秋田秋 CMP000079

秋田県高野連公式年間日程 P2SRC016 と大会結果資料 P2SRC332 を照合した。

2026年秋季県大会前段は、

- 一次予選: 8代表
- 敗者側二次予選: 8代表
- MAIN進出: 合計16校

である。

既存の `FMT005`（全県一次＋全県敗者復活）で表現可能なため、専用formatは追加していない。

追加:

- stage: `STG000212 PRELIMINARY_QUALIFIER`
- format: `FMT005`
- primary_output_slots: 8
- repechage_output_slots: 8
- stage calendar:
  - 2026-08-27
  - 2026-08-28
  - 2026-08-31
  - 2026-09-01
  - 2026-09-04
  - 2026-09-05
  - 2026-09-06
  - 2026-09-07

9/12以降はMAIN。

## P0秋季pre-MAIN stage calendar

Stage 13E-3F-1時点のP0 national 28件について、開催期間そのものではなく、2026結果資料上で実際に試合が行われた日のunionを `competition_stage_calendar.csv` に登録した。

Stage calendar全体は最終的に:

- total pre-MAIN rows: 50
- verified: 29
  - P0秋季28
  - 秋田追加1
- research_pending: 21
  - P1 regional chain: 20
  - P2 local only: 1

calendar relation:

- explicitly_excluded_from_main_calendar: 27
- not_structured_separately: 23

## verified後に残った4 calendar gap

日付登録後も以下4大会がcalendar gapとして残った。

- `CMP000112` 静岡秋
- `CMP000136` 広島秋
- `CMP000140` 徳島秋
- `CMP000162` 沖縄秋

追加診断の結果、日付不足ではなくruntimeが不要な試合まで生成していたことが原因だった。

### FMT022

対象:

- 徳島秋 `CMP000140`
- 沖縄秋 `CMP000162`

format masterは

- `run_until_semifinalists_identified`
- `quarterfinal_winners`
- `top4_seed_pool`

を定義している。

しかしlegacy / lazyの両実装は優勝決定までsingle eliminationを継続していた。

修正:

- single elimination runtimeへ `stop_at_survivors` を追加
- `FMT022` は `output_slots=4` の4校が確定した時点で停止
- legacy / lazy双方を同一契約へ変更
- 既存formatはdefault `stop_at_survivors=1` のため挙動不変

注意:

徳島8/24、沖縄8/13・14など、seed pool確定後にも実大会の順位・優勝決定試合は存在する。
現行FMT022はmaster定義どおり「秋季県大会のシード4校確定」に必要な範囲までをdependency runtimeとして扱う。
順位決定部分を独立した非blocking eventとして完全再現する場合は後続stageで扱う。

### FMT025

対象:

- 静岡秋 `CMP000112`
- 広島秋 `CMP000136`

format phase masterはRANKINGを `generate_only_if_rank_order_required` としている。

しかしlegacy / lazyの両実装は、全代表決定後に常に全qualifierを使ったRANKING knockoutを生成していた。

修正:

- `rank_order_required` が明示された場合のみRANKING phaseを生成
- 現在のFMT025大会には同parameter指定がないため、代表決定後に不要な全順位トーナメントを生成しない
- legacy / lazyを同一条件へ変更

実際の地区順位決定戦を将来完全再現する場合は、全代表を再トーナメントするのではなく、公式方式に沿った限定的なranking-only subgraphとして別途構造化する。

## 年末Live E2E比較

### Stage 13E-3F-1

- complete: 98
- calendar_gap: 46
- blocked: 2
- waiting_dependency: 16
- 未完了: 64
- completed matches: 6,176

### Stage 13E-3F-2

- complete: 133
- calendar_gap: 20
- blocked: 2
- waiting_dependency: 7
- 未完了: 29
- completed matches: 10,308

改善量:

- complete: +35
- 未完了: -35
- completed matches: +4,132
- pending stage rows: 49 → 21
- P0 pending stage rows: 28 → 0

## 神宮chain

F-1では神宮 `CMP000003` は10地区代表が揃わず `waiting_dependency` だった。

F-2では秋季P0解消により、

- 秋季都道府県大会
- 秋季8地区大会
- 神宮10代表aggregate

までdependency chainが通った。

`CMP000003` はmaterialize済みで、`unresolved_source_competition_ids=()`。

残るblockerは神宮自身のMAIN個別試合日。

`season_calendar.csv` には

- 開催期間: 2026-11-19〜2026-11-24
- 個別 `game_date_list`: 未確定

のため、年末監査では

- blocker: `calendar_gap`
- origin: `calendar_gap_without_pending_stage`
- calendar_gap_count: 2

となる。

したがって秋→地区→神宮のdependency不足は解消済みであり、次は神宮個別試合日を抽選後の公式情報から確定する工程へ分離できる。

## 残存blocker

### research_pending pre-MAIN

21 rows:

- P1 regional chain: 20
- P2 local only: 1

### dependency resolution

2大会:

- `CMP000095` 神奈川春
  - `ACR000008`
- `CMP000113` 愛知春
  - `ACR000012`

いずれもSenbatsu bootstrapの `expected=1` に対してresolved=2。

### waiting_dependency

7大会。すべて春地区chain:

- `CMP000005`
- `CMP000006`
- `CMP000007`
- `CMP000008`
- `CMP000009`
- `CMP000010`
- `CMP000012`

## テスト

追加・更新:

- FMT022 top-four cutoff regression
- FMT025 optional ranking regression
- stage calendar verified/pending count regression
- full-season planner verified calendar regression
- year-end blocker audit regression
- Stage 13E-3F-2 final chain regression

最終GitHub Actions:

- Ran 573 tests in 88.525s
- OK

## 判断

Stage 13E-3F-2完了。

P0 autumn pre-MAINは0件まで解消し、神宮はdependency待ちからMAIN日付不足へ前進した。

次候補は以下。

1. 神宮 `CMP000003` の2026個別試合日を抽選後公式資料でverified化
2. P1春季pre-MAIN 20件の実施日verified化
3. `CMP000095` / `CMP000113` のSenbatsu access resolution修正
4. FMT022 / FMT025のranking-only実大会を非blocking subgraphとして完全再現するか設計判断
