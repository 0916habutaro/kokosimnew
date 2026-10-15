# ADR-042: 自作山梨夏デモの永続namespaceと明示再開

- 状態: Proposed（製品未採用）
- 日付: 2026-10-15
- 関連: Issue #273、ADR-037～041、Stage43G-109操作設計

## 背景

Stage108のTemporaryDirectoryと親所有capabilityはプロセス寿命を超えた保存契約ではない。製品SaveSlotManagerのmanual/autosave・複数DBと、本番restore/import/activationの契約も異なる。Windowsで2026山梨夏の新規架空デモだけを後日継続するため、製品writerのパス制限を緩める方法を採用しない。

## 決定案

専用namespaceを未存在のディレクトリとして明示opt-inでexclusive作成する。新規ゲームごとに別UUID子ディレクトリ、独立版の固定marker、単一SQLite、OS排他leaseを作成する。writerは`DemoNamespace`とこの機能自身のdemo IDを受け取り、任意SQLiteパスを受け取らない。namespace/子ディレクトリ/DBの実体identityを固定metadataへ記録し、DB内metadataも一致させる。markerにはyear/competition、seed、登録/plan/schema/確率設定SHAも固定する。

再開は明示選択のみ。全schema・全行・SHA・verify_prefix・独立event oracle・同seed全結果再実行・bracket oracleをROで通してから書込みを許可する。SQLiteのlock検査を無視する`immutable=1`は使わない。原本bytes不変を検査し、journal・WAL・ロック・欠損・未知版は修復せず拒否する。leaseは固定ファイルのOS lockで、通常終了と強制プロセス終了により解放される。Windows実体pinはDELETE共有を許可しないhandleで保持する。

原子性は単一SQLiteの1試合transactionだけ。登録・結果・Option A・進出台帳・同順位とmetadataを同一DBに置く。別JSON checkpoint、複数DB同期、round全体の原子性は主張しない。終了要求を計算workerへ通知し、commit前ならrollback、commit後ならその試合を残し、workerとnative接続の終了後にTkを破棄する。

## 制約・帰結

SHA・実体identityは整合性検査であり、第三者真正性の署名ではない。コピー・移動によるimport、壊れたデモの修復、所有領域の自動採用は認めない。実体IDを検証できないファイルシステムも拒否する。同じ原位置のデモを同じOSから再開する狭い試験で、敵対者がOS権限で同時に保存物を書き換えることへの完全防御や、全ファイルシステムの電源断耐性を保証しない。

旧Stage108 lab、338catalog、106CSV、製品writer、旧候補のreadonly診断は変更しない。実ユーザーsaveは検証しない。2027実試合・全国正式GUI・製品restore・GC・配布EXEは対象外。Windows runnerの実Tk自動操作、個人PCの手操作、OSログインセッション跨ぎの手動確認を別々に記録する。
