# Stage43G-112 県横断ロスター継承 実測報告

対象は山梨33校（保存済み架空31試合の正本）と、repo実マスターの長野4校（学校ロスター専用の自己生成fixture）。2026→2027を同じ `stream_school_transitions` / `advance_school_roster` / `CareerRosterArchive` で継承する。別県の大会結果・2027公式資格/日程・未来試合の生成は0件。製品年度のシーズン開始承認も0件。

|対象|前年度現役|卒業|進級|新入|翌年現役|卒業含む永久ID|
|---|---:|---:|---:|---:|---:|---:|
|山梨33校|660|264|396|264|660|924|
|長野4校|80|32|48|32|80|112|

学校ID/program ID・元学校・入学年・永久ID・氏名・守備/利き手・roster_noを進級時に保持する。学年以外の全プロフィールを独立SQL/JSON oracleで照合し、卒業生を含む過去履歴を永久IDで読む。山梨の登録640人と学校660人を区別し、合同2校の学校ロスターとteam勝敗の分離を維持する。

長野4校のマスター出典、北信支部・代表区分の扱い、既存契約表、保存/認可境界は[設計書](stage43g112_cross_prefecture_roster_design_20261016.md)に記載。実例は `python examples/stage43g112_roster_only_read.py --self-created-only`。

自動検証の集計、OS/Python・計時・DB容量・50/100/200年・同名別県の実IDはaudit JSONへ記録する。Windowsは既存Stage111のartifactに `cross-prefecture-rosters.json` を追加する。Linuxは補助証跡で、Windows native判定の代用にしない。

個人Windows実機の手操作・目視、サインアウト/再ログイン、PC再起動は未検証。実ユーザーの既存デモ/save/backupの使用・変更は0件で、実ユーザーデータ互換性は未検証。旧14版の自己生成候補のRO内容整合性確認は、認証済み真正性やrestore/replay許可を意味しない。複数DB間の原子性、200年分の試合履歴検証、全国47県シーズン完成は主張しない。

## Linuxの構造stream補助計測

`python examples/stage43g112_roster_stream_probe.py --self-created-only --schools 1000` と同じ条件で、2036→2037・seed430112・1000実学校IDの構造ロスターを学校単位に自己生成して測定した。receipt検証8.014019秒、共通遷移7.689404秒、Python tracemalloc peak 3,631,836 bytes（repo読込後に計測開始、RSSではない）。SQLite書込0・試合生成0・製品年度受理0。複数の補助試験を同一Linux環境で実行中の値であり、Windows速度や数千校同時保存の保証へ外挿しない。

集計証跡は `audits/phase2/stage43g112/linux_structural_stream_20261016.json`。前年度生成を2回使うのは保存ゲームを入力としない構造probeだけであり、試行DBの進級は保存済み前年度rosterから行う。

## Linux補助audit

Python3.12.14、Linuxの初回実装head `9aadd82` を対象に、新10件/skip0、363.174秒で成功。自己生成一時領域だけを使用した。計時には前年度31試合fixture構築/保存検証と旧111checkoutの自己生成候補verifyを含む。全unittest・関東E2E等を並行実行中の補助値である。後続の同seed37校1036永久ID照合とarchive直接衝突rollback強化も個別実行で成功した。

|測定範囲|経過秒|DB bytes|保持内容|
|---|---:|---:|---|
|長野4校 継承・受理・全永久ID履歴読取・冪等再試行|0.322888|167,936|80現役、卒業含む112永久ID|
|山梨33校 同上（既存保存source再検証を含む）|28.736089|1,085,440|660現役、卒業含む924永久ID、source31試合bytes不変|
|1校50回継承（tracemalloc有効）|1.985778|638,976|51 snapshot、355永久identity、20現役|
|1校100回継承（同上、累積）|3.784403|1,228,800|101 snapshot、688永久identity、20現役|
|1校200回継承（同上、累積）|7.292984|2,408,448|201 snapshot、1,355永久identity、20現役|

200回継承のPython traced peakは191,130 bytes。試合生成は全期間0件。`player_history` は最古選手についても入学年と学校索引で最大3年を読み、RO前後のDB SHAが一致した。新recipeを受け入れる試験ではなく、既存placeholder recipeの厳密な継承を確認している。

原集計: `audits/phase2/stage43g112/linux_roster_contract_20261016.json`。Windows nativeのclose/renameとCI結果はWindows専用gateで別途確認する。

## Windows専用gateの実測

初回実装head `9aadd82bada24bac408c2ef8fb99f61a6142b045` の [Windows年次gate](https://github.com/0916habutaro/kokosimnew/actions/runs/38905755234/job/116988787229) で、従来Stage111 8件/skip0（289.458秒）と新Stage112 10件/skip0（216.876秒）が成功した。Windows Python3.12.10、既存ジョブ内の連続実行。新audit全体には前年度31試合fixtureと旧111候補生成を含む。

|Windows測定範囲|秒|DB bytes|確認内容|
|---|---:|---:|---|
|長野4校 共通trialの継承・受理・履歴全件読取・冪等再試行|0.320250|167,936|卒業32/進級48/新入32、112永久ID、20現役/校|
|山梨33校 共通trialの同上（source再検証を含む）|24.620172|1,085,440|卒業264/進級396/新入264、924永久ID、31試合source bytes不変|
|1校50回継承（tracemalloc有効）|2.388810|638,976|51 snapshot、355永久identity|
|1校100回継承（累積）|6.104458|1,228,800|101 snapshot、688永久identity|
|1校200回継承（累積）|11.778237|2,408,448|201 snapshot、1,355永久identity、最古履歴保持|
|既存Stage111の校年追記/全33受理だけ|3.559365|1,310,720|従来lineage/閲覧924人とsource不変を回帰確認|

共通trialの「継承・受理・全履歴読取・再試行」と、従来Stage111の「追記/受理だけ」は計時範囲が違うため、24.620172秒と3.559365秒を単純な性能比として比較しない。200回継承のtraced peakは191,213 bytes（RSSではない）、全期間で試合生成/製品年度開始0件。

別process強制終了後の再開、native接続保持下の明示close/rename、hot journal/sidecarの接続前拒否、RO SQL/SHA不変がWindowsで成功。旧111の真のmain checkoutから生成した候補も338catalog/106CSV照合・RO内容verify・原本bytes不変が成功した。従来13版の検証は既存Stage109/110/111 gateに維持している。

公開集計を `audits/phase2/stage43g112/windows_roster_contract_20261016.json` に保存した。元artifactは `stage43g111-windows-annual-rosters`（`annual-rosters.json` と `cross-prefecture-rosters.json`）。後続commitでは同seed37校1036永久IDの追加照合と、既存archiveを直接通す衝突rollback試験を強化した。最終headの新旧gate・全unittest・関東E2Eの結果は [PR #280 checks](https://github.com/0916habutaro/kokosimnew/pull/280/checks) と日本語PR本文に最終集約する。

初回headの関東8都県17校E2Eは2件成功、435.946秒（[ジョブ](https://github.com/0916habutaro/kokosimnew/actions/runs/38905755134/job/116988786039)）。最終headでも同じE2Eと全unittest、Stage109/110/111 native Windows/Tk、保存境界回帰を省略せず確認する。


全unittestの前Stage実測3386.766秒（約56分）に新audit約4分が加わるため、時間超過による中断を避ける目的で全unittestジョブのtimeoutだけ60→75分へ変更した。テスト選択・件数・assertion・skip条件・関東E2Eジョブは変更していない。新workflow/jobを追加するものではない。
