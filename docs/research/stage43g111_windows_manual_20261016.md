# Stage43G-111 個人Windows年次継承手動チェック

**個人PCでの手動操作は未検証**。Windows runnerの自動試験と区別する。
[Stage110手動チェックシート](stage43g110_windows_manual_20261016.md)の保存先/ID/終了/再ログイン手順は維持する。
この追記は既存デモを2027へ移行する手順ではない。Stage111には既存セーブを入力する機能も、2027本番slot/年次GUIもない。

実施日＿＿／Windows版＿＿／Python3.12版＿＿／各項目の成功・失敗・未実施＿＿。
秘密path・ユーザー名・原本SHA・demo/save/backupを報告や公開artifactへ添付しない。

|番号|操作|確認すること|結果|
|---|---|---|---|
|111-1|レビュー対象checkoutからPowerShellで `py -3.12 tests/stage43g111_audit.py --require-windows --json-output "$env:TEMP\stage111-manual-new.json"`|出力名は未存在の新規名にする。8件成功・skip0、33校/660現役、卒業264/進級396/新入264、2027試合0|未実施|
|111-2|`py -3.12 examples/stage43g111_annual_roster_read.py --self-created-only --school-id SCH000202 --player-state graduated`|自己生成31試合を待つ。学校の2026旧20人/合同team注記/試合/順位と2027新20人を見る。選択卒業選手は2026成績を残し、2027はgraduated・試合なし|未実施|
|111-3|同コマンドを `--player-state returning` で実施|同じ永久ID・元学校・入学年・roster_noのまま学年が+1。2027の試合別成績なし・通算空|未実施|
|111-4|同コマンドを `--player-state newcomer` で実施|2026はnot_yet_enrolled/profileなし。2027は1年生・入学年2027。名前一致から過去選手へ接続しない|未実施|
|111-5|`--school-id SCH000220` でも111-2を実施|塩山の別20人が継承される。2026の農林・塩山合同team成績は単独学校成績に複写されない|未実施|
|111-6|111-1のprocess再開・故障結果を見る|校別commit後の別Python再開、確定前rollback、確定ACK喪失後の同一性、hot journalの無修復拒否が成功|未実施|
|111-7|通常終了後にPowerShellプロンプト復帰を確認|native SQLite/lease/pinが閉じる。一時領域は試験終了で片付けられ、個人の既存デモ/saveは変更されない|未実施|
|111-8|Stage110シートのサインアウト/再ログイン・PC再起動項目|本人が実施した種類と症状を別記。CIのPythonプロセス再起動で実証済みとはしない|未実施|

111-2〜5は毎回**別の自己生成一時領域**で2026を計算し、2027学校ロスターだけを作成する。
プロセスを完全終了した後の一時領域の保持や、OS再ログインを跨ぐStage111データの再開は提供しない。
capabilityは親が一時領域を保持する限定試験用で、実ユーザーの保存先として配布・使用しない。
Windowsサインアウト/PC再起動後のStage110保存再開・実体IDは依然として**本人PCで手動未検証**。

失敗時は項目番号、操作順、エラー文言、件数、待ち秒数、Windows/Python/Tk版、再ログイン/再起動の有無だけを報告する。
journal/WAL削除、marker修復、旧saveの復元/移行、履歴削除、2027試合実行は行わない。
