# Stage 43G-17：封印年度キャッシュの完全読み取り専用GUI接続

作成日：2026-10-10。前工程：Stage43G-16 PR #157 mainマージ済み。

## 目的と境界
数十年・100年のA方式個人成績を閲覧する際、封印済み学校×年度から生成されたStage43G-15派生統計キャッシュを再利用する。**GUIが集計キャッシュを作成・変更する操作は実装しない**。既存のゲーム用cache materializerは別コンポーネントとし、試合原本・ロスター原本・派生DBの3種類を閲覧時に更新しない。

追加：`phase2_engine/career_stats_readonly_adapter.py` の `CareerStatsReadOnlyAdapter`。既存Stage43G-15のSHA整合性・校年度網羅性・台帳一致・統計集計のルールは再利用し、キャッシュ接続はSQLite `file:...?mode=ro` と `PRAGMA query_only=ON`。このAdapterの`materialize`は必ず拒否する。原本台帳の照合も明示的ro接続を利用する。

## 画面への導線と欠損処理

`CareerHistoryBrowseModel` は、対象期間の全年度が封印済みで、対象校の校年度キャッシュが揃い、台帳SHAと件数が一致する場合のみキャッシュを選ぶ。対象年度がactive、またはキャッシュ未生成・一部欠損であれば**従来の原本A方式から検証・再集計**する。キャッシュを読む前に台帳不一致を発見したらエラーにし、破損を黙って原本で隠さない。

既存キャッシュの個人成績SHA、学校×年度fact SHA、レコード件数は読み出し時に検証。fastキャッシュでは**全元試合のpayload SHAを毎回再検証しない**。GUI上の`source_validation`と`source_payloads_rechecked_on_read`により、`sealed_cache_ledger_checked/false`と`raw_archived_A_verified/true`を明示する。ファイル直接改ざんの完全検出は別途原本監査が必要。

本フェーズでは、キャッシュが全期間揃っていない場合の「封印年度キャッシュ＋進行年度原本」の混合集計は行わず、全期間を原本から再集計する。安全優先の暫定契約であり、期間が増えた場合の最適化は後続。画面上のランキングは保存済みA方式に基づく値のみで、規定打席到達・投手勝敗等は推測しない。

## 自動テスト
`tests/test_stage43g17_readonly_cache_browse.py`：
- キャッシュが存在しない状態ではDBを新規作成せず原本経由
- キャッシュ生成後は原本と年度／通算／学校記録が一致し、3つのSQLite原本・キャッシュのバイト列が不変
- active期間と封印済みだが未生成の年度は原本へ
- 新たに封印後にキャッシュを作成すればキャッシュへ切替
- 台帳SHA不一致、キャッシュ行破損、DB破損はfail closed
- 不正キャッシュからの画面遷移では戻り状態が変わらない
- read-only connection上でのCREATE TABLEとGUIアダプタのmaterializeが拒否される

GitHub Actionsの標準Python unittestと関東8都県17校E2Eを両方確認してからPRマージ。

## 受け入れ範囲と次工程
Tk GUIはあくまで独立試験版。Windowsでの表示実機試験・正式UIの統合は未実施。100年×全国3,000校の全量実測、完全年次進行、2026本編との統合、無制限年数への対応は後続。Stage43G-18候補は、封印済み期間と進行中年度の**安全な混合集計**、キャッシュ欠損診断、範囲を限定したパフォーマンス計測。
