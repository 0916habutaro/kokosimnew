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
