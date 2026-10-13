# ADR-035: 残るSQLite所有境界とバックアップ再開の段階導入

Status: **Proposed（未採用）**

Date: 2026-10-14

## 背景

Stage43G-99は5製品ファイルの短期接続・履歴generatorに明示closeを追加し、338入力の旧候補内容検証と現行replay承認を分けた。全SQLite APIの寿命統一と、旧候補からの製品再開は実装していない。

## 次Stageで検討する案

- cache writerやBrowseRepositoryの残るwith-only接続は、実呼出し・transaction・generator返却を棚卸ししてから小単位で改修する。外側がconnectionを借りている箇所で勝手にcloseしない。各版の固定catalog digestと変更前後の真のexport候補を回帰する。
- `LiveGameService`へ実生成ロスター／大会結果の保存を統合する際は、通常進行・load replay・seal・例外時の冪等性と所有者を同時に設計する。今回の試験workerのcache読取と明示保存を本番統合済みと扱わない。
- 将来replay実験を許可する場合、受け入れる生成時入力版・runtime、入力真正性の確認方法、複数大会・歴史全年度の不足情報を明示する。候補内の任意Pythonをそのまま実行せず、レビュー済み実装・新規隔離fixtureでbaselineとのゲーム結果／完全A／ロスター／大会結果一致を証明する。既存saveへのwrite/restoreは別仕様と別承認の対象とする。

## 現Stageで採用しないもの

旧338コードの製品への常設同梱、unsigned receiptからの生成時真正性推定、互換版が異なる場合の自動replay、既存slotのmigration／上書き、履歴削除、方式B/C／共通lockの本番採用、全国正式GUI一括導入。

## 次の受入判断

Windowsで正常・異常・commit/rollback例外・中断したreader・複数reader・UI子窓終了後のnative handlesを確認する。新旧catalogを混ぜず候補内容は保全し、replayの条件不足は拒否として提出する。全unittestと関東17校E2E、既存バックアップ回帰の成功を維持する。年度登録だけを翌年度実試合開始と扱わない。
