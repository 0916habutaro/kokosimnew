# Stage 13E-3G-1：代表確定後の順位決定戦（FMT022 / FMT025）設計

作成日：2026-10-08

## 目的

2026年の実際の大会形式に合わせ、**代表校またはシード校が決定した後に実施する試合**をモデル化する。勝敗は順位の表示に使えるが、出場枠・シード権・県大会の進出枠には絶対に逆流させない。

従来の `TournamentEngine.run()` と lazy scheduled runtime に自動追加すると既存の試合日数・スロット・進出依存関係まで影響する。**3G-1では独立のranking-only sidecarとして作成し、まず勝敗・資格固定・途中保存の契約を確定する。** 後続3G-2で日付に紐付く任意の試合生成・read model反映を接続する。

## 対象・方式

| 対象 | モデル | 確定条件 | その後に許容する試合 | 影響を受けるデータ |
| --- | --- | --- | --- | --- |
| 徳島秋（CMP000140） | FMT022 | 新人中央大会で4シードが確定 | 2ブロックの決勝戦 `two_block_deciders` | ブロック内順位メタデータのみ |
| 沖縄秋（CMP000162） | FMT022 | 新人中央大会準々決勝の勝者4校が確定 | 2準決勝→決勝 `semifinal_final` | 大会内順位メタデータのみ |
| 静岡春・秋（CMP000111/112） | FMT025 | 東・中・西地区の本大会代表が確定 | 当該代表間の上位決定戦 `pairwise_deciders` | 地区内上位情報のみ |
| 広島春・秋（CMP000135/136） | FMT025 | 4地区の代表枠が確定 | 必要な代表間順位戦 `pairwise_deciders` | 地区内上位情報のみ |

2026年資料では、静岡市立高校は8月23日の代表決定戦に勝利し、8月30日に静岡商との「上位校決定戦」に進んでいる。この**代表確定済み**という状態を順位戦開始の前提とする。広島については地区ごとの実対戦カードが年度ごとに変わるため、詳細な年次カードが与えられない限り**勝手に対戦を創作しない**。

## データ契約

`data/competitions/post_qualification_ranking_profiles.csv` に6大会分を追加。

主なカラム：
- `format_model_id`: FMT022またはFMT025
- `ranking_event_mode`: `two_block_deciders` / `semifinal_final` / `pairwise_deciders`
- `entrant_contract`: シード4校が確定済み、または各地区代表が確定済みであること
- `result_effect`: 常に `ranking_metadata_only`
- `annual_draw_requirement`: FMT025は`explicit_annual_pairs_required`
- `primary_source_id`: 既存の2026一次根拠

ゲーム内の架空年度では、FMT022は4シードの登録順から固定の模擬組合せを生成できる。正確な当年結果の再現を行う場合は、必ず当年の対戦ペアを明示する。FMT025は既存の地区代表全員に順位戦が必ずあるとは限らないため、明示された年次ペアがない限りイベント生成を拒否する。

## ランタイム境界

呼び出し：

```python
runtime = TournamentEngine(repo).prepare_post_qualification_ranking(
    stage_execution=completed_stage,
    group_id="SGR000184",
    pairings=(("SCHOOL_A", "SCHOOL_D"), ("SCHOOL_B", "SCHOOL_C")),
)
ready = runtime.ready_matches()
runtime.resolve(ready[0]["match_id"], ready[0]["team1"])
saved = runtime.snapshot()
restored = RankingOnlyEventRuntime.from_snapshot(saved)
```

- `completed_stage.metadata.group_models`・`group_outputs`を読み、実際の出力校だけを固定する。
- `stage_execution.output_school_ids`外の学校が混じれば生成失敗。
- 同一選手・学校を複数カードへ入れる場合、未資格校・同校対戦、カード重複、未生成の決勝の先行resolveはエラー。
- `ready_matches`は試合の作成だけで勝敗を自動決定しない。
- `resolve`は入力された勝者が当該カード出場校か検証する。
- `snapshot`はシード／代表の`locked_school_ids`と順位結果を別々に保持。途中保存して再開可能。
- 勝敗で変化するのは`ranking_metadata`のみ。 `CompetitionRun.outcome`・`seed_assignments`・`main_entrant_school_ids`・`qualifying output`を変更しない。
- 本機能はまだ`CompetitionRun`・定期試合生成・read-only GUIへ自動統合しない。この段階でシーズンの日程を勝手に増やさない。

## テスト観点

1. 徳島：確定4シード→2試合、資格不変。
2. 沖縄：確定4シード→2準決勝→動的決勝、資格不変。
3. 静岡：確定5代表うち任意の明示ペアで順位試合を実施、未出場代表も維持。
4. 明示ペア不在／未資格校／二重登録／未成立決勝のresolve拒否。
5. JSONシリアライズ→復元で結果・次の試合一致。
6. 対象外モデルや異なるstage/groupの組み合わせ拒否。

## 公式・補助根拠

- [徳島新人中央大会2026年8月20～24日](https://www.hb-nippon.com/tournaments/1857)：8チームで2ブロックに分かれ各ブロック決勝、4校の秋季シードを確定
- [徳島秋2026年シード校4校](https://www.topics.or.jp/articles/-/1489451)
- [沖縄新人中央大会2026年8月9～14日](https://www.hb-nippon.com/tournaments/1740)：準々決勝・準決勝・決勝の実施
- [沖縄ベスト4で秋季シードを取得](https://www.hb-nippon.com/articles/16145)
- [静岡市立高校：秋季県大会予選代表確定後の上位決定戦](https://shizuokacity-h.ed.jp/＜野球部＞秋季県大会予選代表決定戦/)
- [8月30日の静岡秋上位決定戦のカード例](https://www.hb-nippon.com/calendar?date=2026-08-30)

## 現時点の制約・次工程

これまでのFMT022/FMT025の通常の予選・シード抽出を変更しないため、年間E2E結果161/162大会は引き続き維持される。3G-1は**独立ランタイムの初期実装**であり、研究台帳RS2026025/RS2026026の最終解決ではない。次の3G-2では以下を検討：
- FMT022は実際にシード確定した瞬間と追加順位試合の試合日を切り分け、`ScheduledCompetitionRuntime`に非blockingイベントを必要時のみ積む。
- FMT025はグループごとの年次ペア／試合日を入力して初めて任意イベントを積む。地区ごとの代表枠数は固定したまま。
- 保存済み順位戦の試合結果をmatch read modelとGUIで閲覧できるようにする。
- 既存の大会終了判定と独立して追加順位イベントの未実施・中止を扱う。
