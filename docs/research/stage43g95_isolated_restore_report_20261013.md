# Stage43G-95：隔離復元候補の実験報告

Issue #245、基点main `80409dab2d9c3fbfb861c8e909c9d730454abb5a`。[設計](stage43g95_isolated_restore_design_20261013.md)のfixture限定実験を追加した。製品コード・writer・保存schemaは変更していない。本番の手動restore API/CLIを導入したものではない。

自己生成旧A8校単大会→Stage94製品export→製品verify→新規隔離directoryコピー→独立SQL/SHA・正本のread-only一覧/個別全試合/学校記録を照合する。6状態の全試合、inning別得点、個人成績、roster/player identity、全年度台帳とoutcomes、manual/autosave両系列・rolling JSON、固定互換入力338件、候補の全file集合を対象とする。DBは元/候補の論理行一致、候補/隔離先の全byte一致を検証する。

専用20テストは、証拠偽造・整合的年度切落としをprivate anchorで拒否するケースを含む。途中プロセス終了、ENOSPC/EIO/interrupt、欠落、各正本改変、版/slot混同、links/WAL/SHM/journal、出力衝突/包含、二重実行、先行/後置COMPLETE、コピー中/完了後改変を確認する。通常の拒否では元/候補SHA不変、注入writerによる変更では元不変と候補へのハーネス書戻し無しを区別する。途中データは残し、自分の完了receiptだけを取り消す。

検証件数・実測とCIの確定結果は本報告への追記およびPR Checksに記録する。Windows成功をLinux実行から推測しない。ローカルの全Python実行と関東17校実行は分離する。Tkのローカルdisplay接続制限はCI実Tk検証と区別する。

CSV106の集合とbyteは作業前後で照合し、実path/SHA一覧は公開しない。今回、作業領域に既存save関連4fileが存在することを確認した。テスト入力には使わずprivate SHAによる不変性だけを照合する。これらを利用者の本番saveと断定せず、過去報告の0件という値も今回へ流用しない。実ユーザーsaveの復元・内容/全ゲーム再開検証は0件・未検証。

署名/永続承認anchor、全writer排他、複数DB原子性、電源断・fsync、過去生成時の互換版、途中career/別PC全再開は未保証。登録のみの翌年度を実試合進行年と呼ばない。派生索引は不使用。自動復元・本番saveへの復元・既存slot上書き・形式移行・履歴削除は実装も実行もしていない。CI成功後もPRは未マージ・auto-merge無効でレビュー待ちとする。

## ローカル実測（Python3.12/Linux）

新規20件はskipなしで成功、94.857秒。独立期待値の最終補強後に専用suiteを再実行した。各成功状態は元SHA・元/候補SQL・候補/隔離先SHA・read-only閲覧一致。CSV106と既存作業領域save関連4fileの集合/SHAも不変。

|状態|系列|試合|年度|元bytes|候補＝隔離先bytes|export秒|隔離copy＋照合秒|
|---|---|---:|---:|---:|---:|---:|---:|
|active|manual|6|1|1393452|9080519|0.801393|0.810188|
|active|autosave|6|1|1393452|9080523|0.815306|0.807929|
|sealed|manual|7|1|3691326|11379146|1.133218|1.047607|
|sealed|autosave|7|1|3691326|11379150|1.264777|1.2093|
|registered|manual|7|2|3691326|11379146|1.115095|1.068392|
|registered|autosave|7|2|3691326|11379150|1.07799|1.088725|

測定JSONは `audits/phase2/stage43g95/isolated_linux_20261013.json`。各候補には338件の現在互換入力を含む。全履歴を残し年数制限は追加していない。全Python/関東E2Eの終了結果とGitHub全CIはPRの検証記録で確定する。
