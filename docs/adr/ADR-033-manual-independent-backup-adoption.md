# ADR-033：方式Aの段階適用と停止済み旧A手動exportの限定採用

- 状態：**Accepted（Stage43G-94の限定範囲）**
- 日付：2026-10-12（日本時間）
- Issue：#243、基点：PR #242マージ後の最新main
- 関連：[ADR-032](ADR-032-production-save-inventory-adoption-proposal.md)、[設計](../research/stage43g94_manual_backup_design_20261012.md)

## 決定

利用者が2026-10-12に方式A（現行保存形式維持＋独立backup）をStage43G-94から段階実装するよう明示した。承認対象は、停止宣言した単純な旧A一slotの手動export API/独立CLI、read-only正本監査、新規独立候補の照合、安全な拒否まで。

通常のゲーム動作には接続せず、必須selector・停止宣言・新規出力指定がある場合だけ動作する。旧A ISOと架空v2 G年を分離し、全年度・全試合Option A、ledger、roster identity、outcomes、存在するlive両系列・rolling backupsを保持する。派生cache/索引は不使用で始める。固定repo許可リストの互換入力は現在版として同梱するが、過去生成時の外部版の同一性やゲーム再開は保証しない。

完了receiptは署名や保存世代manifestではない。停止宣言・前後SHA・二重照合は排他を証明しない。未検証career、未知version/authority、不整合、writer artifact、衝突、リンク、I/O障害は成功扱いにせず、失敗候補を保持する。

## 承認に含まれないもの

自動backup/restore、元save上書き・移行・削除、全履歴GC、署名/鍵/永続承認anchor、保存世代manifest、共通slot lock、方式B/C、公開参照切替、import/activation、正式GUI、途中career全replay、全国100/200年実進行・他PC完全再開は未承認。100年度/索引・32シャード/照会をゲーム年数制限にしない。

ADR-032のStage91時点のProposed/未採用という履歴は維持し、この決定への追補だけを追加する。ADR-030/031の状態は変えない。PRはCI成功後もマージせずレビュー待ちとする。

## 帰結と次段階

手動製品入口を得る一方、適用対象は単大会の検証済み契約に限定される。現行JSONに生成時の外部入力hash/slot identityがない限界を表示する。将来のrestore実験は自己生成fixtureの新規隔離directoryとread-only検証だけに限定し、本番復元・方式変更は別判断とする。
