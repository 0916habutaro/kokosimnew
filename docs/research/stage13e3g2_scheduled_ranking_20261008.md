# Stage 13E-3G-2：任意順位決定戦の年間スケジューラ接続実装報告

2026-10-08

## 追加内容

- 日付・試合結果・残試合中止・セーブ再開用`ScheduledRankingSidecar`
- `ScheduledCompetitionRuntime`の順位試合登録・日付閲覧・明示的結果入力
- `LiveSeasonDependencyRuntimeState`の`today_matches`表示および独立順位戦解決
- `BrowseRepository`にSQLite順位試合とスナップショットを追加
- 新規回帰テスト
- `docs/design/post_qualification_schedule_stage13e3g2.md`に詳細設計

## 重要な保証

- 初めから完了済みの本戦は、順位戦を登録しても引き続き`is_complete=True`
- シード・進出校は`locked_school_ids`のまま固定
- 2026年の実日付・対戦カードが不明な場合は自動登録しない
- 通常の`play_today()`、後続大会の依存関係、および大会成績read modelは変更しない
- 順位戦の試合結果は専用read modelから別表示する

## 保留と次段階

FMT022の順位決定試合は徳島・沖縄での方式差を維持。FMT025は静岡・広島の地区代表確定後の任意イベントのみ対象とする。公式対戦カードの網羅は未実施のためRS2026025・RS2026026は`design_pending`のまま維持。全カードの年度別調査、および将来の正式GUIへの統合は次工程で扱う。

全テスト・年間E2Eの成功をCIで確認する。
