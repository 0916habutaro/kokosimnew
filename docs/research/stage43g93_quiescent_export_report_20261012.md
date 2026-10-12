# Stage43G-93：旧A独立export候補の採用前調査結果

Issue #241。最新main `a53d7ff1fac06ed50eaf3e2eda4a68083690791b` から専用ブランチ `codex/stage43g93-quiescent-export` を作成。方式A/B/Cは未採用のまま。[設計書](stage43g93_quiescent_export_design_20261012.md)と[ADR-032](../adr/ADR-032-production-save-inventory-adoption-proposal.md)を参照。

## 結果と採用判断への意味

自己生成した静止slotについて、全旧A履歴・roster・互換入力を独立候補へコピーし、原本不変性と候補の論理内容一致を検証できた。単一JSON rolling backupではこの集合を保護できない。古いcheckpointと進んだ履歴の組合せは自動rollbackせず「要手動判断」で停止する。

**これは全ゲーム復元の承認ではない。** 実career途中保存の参加・feeder・年度ルール等の依存関係を完全に証明できない場合は、整合checksumがあっても候補作成を拒否する。正式な方式Aには、静止の運用保証・互換版管理・全対象状態の復元受入がなお必要。B/Cへ進むかもユーザーの判断に残す。

製品writer/reader/schema/GUIは無変更。既存master・実saveを監査入力に使わない。自動backup/restore・利用開始・同名復元・世代manifest・共通slot lock・migration・削除/履歴GCは導入しない。CLIは自己所有fixtureのunittestだけを実行し、実save rootを受け付けない。

## 検証した実ゲームと境界

実LiveGameServiceの `new_game → 能力モデルでplay → manual/autosave → 既存archive sync → 年度末finalize/seal → 隣接翌年度登録` を、8校・単一夏大会の一時fixtureで検証した。途中6試合、封印後7試合の完全A詳細と8校の生成roster、封印後の大会順位正本を保持した。全国全大会の連続年次進行ではなく、翌年度のゲーム自動開始や100/200年連続playは未検証。

実career multi previewも、別の自己生成rosterを翌年へ進めて参加入力・seed/planを保存するところまで生成し、依存関係の未検証を理由に候補作成が拒否されることを確認した。全資格/feeder/runを緑判定していない。

原本接続はread-only/immutable/query_only。閉じたDBをDBごとConnection.backupし、独立raw oracleで全table/行/schema・payload SHA・ledger・イニング得点・roster identity・大会順位の出典を比較した。JSON/互換入力はbyte集合まで比較し、元保存SHAは不変。製品load/replayや自動同期を候補作成・診断から呼ばない。

新規29テストには、WAL/SHM/journal/tmp、停止未宣言、未知正本/未知table、必須正本欠落、master/config/engine不一致、2slot混在、世代/seed/plan偽装、封印ledger/identity改変、古いJSON、JSON先行、偽SHA、リンク/跨ぎpath、既存出力・再実行、file衝突、ENOSPC/EIO、DB backup内ENOSPC、中断、コピー中・最終照合直後の改変、handle解放を含む。失敗時は原本・既存候補のbyteと件数を変更しない。途中候補はprivate完了記録が無いため利用不可で、署名なし候補memoを偽装しても承認されない。

## Linux実測

Python 3.12.14 / SQLite 3.53.1。新規29テストは41.639秒、failures/errors/skipsは0。Stage91の20テストは0.608秒、Stage92の21テスト・52並行条件は2.707秒で成功。実行中の他の全suite/E2EとCPUを共有した値であり性能保証ではない。

| 条件 | slot原本bytes | 互換入力bytes | 候補payload bytes | copy＋照合秒 | 観測最大合計bytes |
|---|---:|---:|---:|---:|---:|
| active・manual・原本のみ | 1,393,460 | 7,640,880 | 9,034,340 | 0.270 | 18,068,680 |
| sealed・manual・原本のみ | 3,176,587 | 7,640,880 | 10,817,467 | 0.785 | 21,634,934 |
| 隣接翌年登録後・原本のみ | 3,176,587 | 7,640,880 | 10,817,467 | 0.642 | 21,634,934 |
| active・派生あり比較 | 1,487,668 | 7,640,880 | 9,128,548 | 0.698 | 27,291,854 |

派生同梱の増分は94,208 bytes。この比較の派生cacheは未使用の合成blobで、索引query性能や全国storage容量の評価ではない。原本のみ候補を先に保持した同じlab内で派生あり候補を作ったため、最大合計には前の候補とその証拠JSONも含む。候補payload bytesにはlab証拠JSONを含めない。観測点の最大合計は作成中候補の最後の証拠JSON・FS割当・瞬間journal・メモリ・生成テンプレートを含めず、普遍的なピーク容量を主張しない。

機械可読証跡は `audits/phase2/stage43g93/export_linux_20261012.json`、`inventory_20261012.json`、`concurrency_20261012.json`。出力には実saveのpath/ID/SHAを載せない。

関東8都県17校の独立E2Eは2テスト・713.860秒で成功。年度登録9テスト・15.307秒、年度継続10テスト・3.086秒、旧A履歴18テスト・0.069秒も成功。Python 3.12全unittest（Xvfb）は2105件・1146.643秒、失敗/エラー0で成功。skip 2件は上記の関東専用実行分であり、その独立実行は成功済み。master CSV106ファイル・既存save4ファイルの集合と内容もすべて不変。実path/SHAは非公開。集計は `verification_20261012.json` に記録。PR CIは最終headで別途確認する。

## 保証外と次の条件

静止は所有者のwriter停止と全handle終了を前提に、file集合不変・sidecarなし・checkpoint/archive整合を検査する。非参加writer、外部復元、TOCTOU/ABAに対する排他はない。無停止export、複数SQLite＋JSONの同時点保証、同slot復元、別PCのreplay/全所属/成長/資格/大会run再開を保証しない。

Windows/Ubuntu専用CIで作成・handle終了後rename・リンク拒否・同FS制約を確認する。異種FSは拒否境界を注入試験するだけで実移送は未検証。Windowsの開いたfileへのrename、antivirus、NFS、電源断、fsync耐久性、実disk枯渇は保証外。中断試験はKeyboardInterrupt注入であり、電源断試験ではない。

保持年数の新上限はない。全保存履歴を保持し、100年度/32シャードという既存索引の1file/1query制限をゲーム年数へ転用しない。合成100/200年・3746校の追加負荷は任意で、今回は未実施。

全成功候補でも `restoration_authorized=false`、`whole_game_restore_proven=false`、`generation_adopted=false`。全CI成功後もPRは未マージ・auto-mergeなしのレビュー待ちとする。
