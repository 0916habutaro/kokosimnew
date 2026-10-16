# Stage110 WindowsデモUIと処理時間の測定・改善

対象はゲーム内試験用2026山梨夏、架空32チーム・33校・660永久選手ID・640登録枠・5ラウンド31試合。Windows個人利用・非配布。起点はStage109マージ済みmain `750a2f716e3518948f3b74d5dd6dffd39bad6118`。製品採用、全国正式GUI、2027年度開始を行わない。ADR-037〜042のProposedを変更しない。

## 計測と優先順位

Stage109の実コードを固定mainから別TemporaryDirectoryへ展開し、同じPython・OS・seed・31試合の操作順で新版と順番に比較する。実ユーザーのデモ、save、backupは入力にしない。`tests/stage43g110_measure.py` は新規作成、各1試合、1/16/31件での別プロセスRO reader、再開、SQLite transaction、全件監査、行生成、試合計算、mapped Tkの描画・個人成績選択を記録する。計測wrapperはテストプロセス内だけ。inclusive時間は包含関係があるため合算しない。transaction時間には前後監査とSQL・commitを含む。`ro_read_verify`にもseed全再実行・SQL/SHA検証を含む。

初期cProfileでは1試合進行×31に全件監査155回、行生成217回。描画、未表示成績表、行データ再生成を改善対象とし、全件検証・試合モデルの省略は採用しない。cProfile秒数は計測自身の大きな負荷を含むため性能比較値に使わない。

## 操作・状態

常時の試験用・架空結果表示に、初回と再開の番号付き案内を追加する。初回は未存在namespace→新規デモ、再開は既存専用ルート→demo ID→続きから。ID欄を明示し、IDを記録するよう案内する。新規は別UUIDの追加で、既存デモの初期化ではない。

進捗バーは検証済みcommit件数だけを0〜31で示す。各試合のRO検証後に、保存済みX/31、前試合の校名・得点、次の対戦、ラウンド/5と残り試合数をqueue経由で更新する。`_next`は画面用の対戦名解決だけを行い、能力付き試合入力を表示目的で再生成しない。履歴は操作終了時に検証済みsnapshotから表示する。

|状態|表示・許可|
|---|---|
|未開始|専用保存先作成/選択→新規/明示再開の案内|
|処理中|履歴消去、開始時点の保存件数と現在の未保存計算を区別。保存先切替・多重クリックを無効化|
|各試合の検証済みcommit|件数/バー/前試合/次戦を更新。次の計算中結果は未保存|
|進行を中断|要求と完了を区別。commit前はrollback。終了後に改めて全件RO検証して保存済み件数を表示|
|通常完了|保存済み件数。同じ保存先・IDから再開できる案内|
|終了要求|中断と接続解放を待つ。ウィンドウが消えPythonプロンプトが戻るまで終了完了ではない|
|検証拒否|snapshot・全表・選択欄・バーを消去。未検証の前画面/件数を再利用せず、原本を修復しない|

workerはTk widgetを触らない。中断ボタンは画面を閉じず、処理境界で中断して同じデモから続行できる。キャンセル通知自体を保存完了の証拠にしない。commit直後に通知された場合はその試合が残る。

チーム選択には校名とID、元学校選択にも校名とIDを示す。登録・元学校タブと個人成績タブへの導線、選択人数、未登録/未出場人数を表示する。未登録者の空の通算は「未登録・未出場」、登録済み空成績は「未出場」。合同の勝敗を元学校ごとの単独勝敗へ複製しない。

## 採用する処理改善（2箇所）

1. **単一書込みtransactionの行差分生成**：直前の`_audit`は従来通り独立oracle、seed replay、schema/SQL/SHA全検証を完了する。その同じ呼出しが既に生成・照合したexpected行をwriterへ返し、同じ行の再生成を1回減らす。差分判定はset検索にし、INSERTする表順・行順とfault/cancel境界を維持する。書込み後`_audit`も残す。永続cacheや操作間cacheは作らない。
2. **未表示の個人成績表の遅延構築**：選択中の検証済みsnapshotと選手範囲だけを保持し、個人成績タブを要求した時に集計・Treeview構築する。タブ表示時も実体guardを実行し、選択変更やclearで前の行を消す。全660人・全試合・通算の情報は保持し、単に非表示時の作業を避ける。

デモmarker、namespace版、SQLite schema、固定recipeを変更しない。Stage100〜108のwriter、338互換catalog、106CSV、製品`LiveGameService`/`SaveSlotManager`/`HistoricalMatchArchive`は変更しない。UIの未出場文言に合わせ、従来全660人Tk試験は実際に成績タブを開いて全行と通算を照合する。

## 同値性と互換

固定Stage109と新版で全31試合の完全A JSON、入力JSON、全イニング、投打成績、SQL各行、最終順位、学校参加・登録・元学校IDをbyte同値で比較する。namespace/UUID/OS実体IDは独立作成で異なるため、cross-namespace SQL比較から固定metadataだけを除外し、この除外を報告する。

さらに同じmetadata・同じ初期DB・同じ全31 prefix入力で、旧list差分のreferenceと実際の新版`_append_rows`を別のin-memory SQLiteへ適用し、0〜31の全32段階で`serialize()`のDB bytes一致を要求する。全DBファイルが別namespaceでも同一であるとは主張しない。

旧main由来Stage109デモを新コードの別Python readerで1/16/31件で開き、元DB bytes不変を確認する。別の旧mainプロセスが1件保存して完全終了後、新コードがRO検証して残り30件を追記し、旧版31件のSQL/完全Aと比較する。旧12版backup候補は従来11版gateに真のStage109 main自己生成・RO内容verifyを1件追加する。replay/restore/activationは許可しない。

## 保護・確認範囲

namespace/UUID/実体ID、OS lease、Windows native pin、DELETE header・sidecar拒否、symlink/junction/reparse/hardlink・任意SQLite writer拒否を維持する。書込み前と別起動の全検証を省略しない。原子性は単一SQLite・1試合transactionのみ。SHAは整合性で真正性署名ではない。媒体障害/OS強制終了の完全復旧を保証しない。

既存Stage91〜109必須CIを削除・skip追加せず維持し、同じWindowsデモworkflowの2 jobsに新規試験・前後計測を加える。全unittestと関東17校E2Eを維持する。旧版fixtureの生成cacheや必須gate整理は今回実装しない。既存CI所要時間の測定と提案は実測報告へ記す。

Windows runnerのmapped Tk自動操作は本人PCの手操作とは別。本人の実施結果は未提供につき**手動未検証**、サインアウト/再ログイン・OS再起動後の実体ID保持も**未検証**。手動チェックシートに従い、拒否したデモを修復・コピー移動して採用しない。
