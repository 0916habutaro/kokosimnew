# ADR-040: 狭い2試合planと隔離SQLiteのプロセス間再開

- Status: **Proposed（製品未採用）**
- Date: 2026-10-15
- Context: Stage43G-107 / Issue #269、ADR-037/038/039を継続

Stage106のmatch1/seed430104固定APIを維持したまま、別のStage107入力型・3team/2試合plan fingerprintと厳密validatorを追加する。登録簿・元学校・永久IDを再利用し、決勝は保存済み初戦の勝者と北杜BYEから決定する。旧driverの内部計算と独立event oracleだけを明示利用し、旧公開入口を一般化しない。

新しい親所有TemporaryDirectory内のSQLiteに開始登録／plan、初戦、決勝／team順位を別transactionで追記する。親が所有権を保持し、mintした実体identity capabilityをspawn子プロセスに渡す。初戦commit後にそのプロセスを終了し、次のプロセスが全内容検証後に決勝を計算・commitする。readerはpathをROで受けるがwriterはpathや既存saveから復元しない。

整合性は全登録・元学校・入力・seed/event再実行と、計算部に依存しない大会oracle・SQL index照合で確認する。BYEは勝利に数えず、順位はteamにのみ所属する。学校参加と永久選手の試合別・累計を別read-only lab GUIで表示する。未完了／欠損時に前の完了画面を残さない。

単一SQLiteの試合単位原子性だけを実証し、JSON／複数製品DB原子性や真正性署名は採用しない。旧save・本番restore・製品大会／writer／全国GUI接続、32team拡張、翌年開始、履歴削除は認可しない。親所有者終了後の永久保存・一般的な再起動復元の完成を主張しない。
