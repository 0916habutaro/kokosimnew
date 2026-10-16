# Stage43G-113 100校保存型年度継承の実測報告

## 実装範囲

山梨33・長野33・静岡34校を最新mainの実マスターと再照合。
学校100・program100・地区所属200行、106 master CSVのSHAを監査記録に固定した。
自己所有の隔離SQLiteへ保存した2026学校ロスター正本から、同じ共通APIで2027へ継承する。
独立SQL/JSON oracleで卒業800・進級1200・新入800・現役2000・累計永久ID2800を確認する。
2026の学校・永久profile・entry_year、卒業生の過去在籍を保全する。
学校年度確定と大会開始許可は分離し、2027出場資格・日程・試合の生成数は0。

## 検証結果

専用監査は保存9件＋真の旧Stage112 export1件の10件を要求し、skipがあれば失敗する。
1/50/100校commit直後のprocess強制終了・別process再開、acceptance前rollback・後強制終了、
hot journal拒否、異seed/recipe/source（同一bytesの別所有実体も拒否）/学校集合拒否、ID衝突rollback、未確定公開拒否、
ファイルID差替・hardlink・sidecar拒否、close→rename→reopenを含む。

Linux Python3.12.14補助監査は10件成功、失敗0・error0・skip0、79.648秒。

|Linux補助計測|実測|
|---|---:|
|2026 source100校初回保存|0.777秒|
|targetへの保存正本コピー・照合|1.753秒|
|100校検証・進級・受理（tracemalloc有効）|3.703秒|
|2026 source DB|1,957,888 bytes|
|2027 target DB（2026履歴を含む）|3,211,264 bytes|
|進級時tracemalloc peak|17,798,566 bytes|
|OS process peak RSS|90,746,880 bytes|
|RO閲覧＋全2800永久IDの履歴検索|3.505秒|
|1/50/100校強制終了＋別process再開|9.940 / 10.090 / 10.264秒|

上記はsource保存・targetコピー・進級・RO検索・再開processでそれぞれtracemallocを有効にした実測。
RO peakは14,595,451 bytes。1/50/100校後の再開process単独は5.966 / 5.871 / 5.876秒、
tracemalloc peakは47,065,587 / 47,718,877 / 48,327,634 bytes、OS peak RSSは
110,366,720 / 111,321,088 / 112,050,176 bytes。再開processにはmodule importとsource/target照合を含む。
親processの強制終了・再開一連時間とは区別する。

SQLは `idx_career_rosters_school_year` のcovering index検索を使用。

## Windows Python3.12.10 実測

実装commit `e8ad236fee43a176b91afa03a7f4e45011ddbfbc`、
[成功run 38932731172](https://github.com/0916habutaro/kokosimnew/actions/runs/38932731172)。
GitHub hosted Windows上で専用10件すべて成功、失敗0・error0・skip0、513.042秒。
同一ジョブのStage111は8件/289.339秒、Stage112は10件/220.427秒でいずれもskip0成功。
測定正本は `audits/phase2/stage43g113/windows_saved_rosters_20261017.json`。

|Windows計測（各処理tracemalloc有効）|実測|
|---|---:|
|2026 source100校初回保存|6.371秒|
|targetへの保存正本コピー・照合|8.668秒|
|100校検証・進級・受理|12.512秒|
|2026 source DB / 2027 target DB|1,957,888 / 3,211,264 bytes|
|source保存tracemalloc peak / process RSS peak|8,062,468 / 73,678,848 bytes|
|進級tracemalloc peak / process RSS peak|17,797,737 / 97,824,768 bytes|
|RO閲覧＋全2800永久IDの履歴検索|9.067秒|
|RO tracemalloc peak|14,595,435 bytes|
|1/50/100校強制終了＋別process再開の一連時間|31.938 / 30.725 / 32.449秒|

|校別commit後の再開process単独|実時間|tracemalloc peak bytes|OS peak RSS bytes|
|---|---:|---:|---:|
|1校|23.643秒|47,218,935|121,044,992|
|50校|16.832秒|47,887,406|121,430,016|
|100校|12.458秒|48,587,036|121,692,160|

再開後のDB容量は全ケースともsource1,957,888 / target3,211,264 bytes。
RSSはOSのprocess全体high-water markで、処理単独の増分ではない。
再開process計測にはmodule import・source/target照合・残校保存・受理を含む。
全2800人の履歴は受理済みDBの学校年度索引を使い、過去の試合を再生成しない。
Windowsでもcovering index `idx_career_rosters_school_year` を使用。
両OSの106 CSV SHAをパス区切りだけ正規化して照合し、全件同一bytesだった。

初回Windows監査は再開試験の一時領域cleanup順序によりerror1となった
（[run 38929672250](https://github.com/0916habutaro/kokosimnew/actions/runs/38929672250)）。
追加TemporaryDirectoryの削除より先に最終resumeのlease/pinsを明示closeするLIFO順序へ修正した。
削除エラーの無視・GCによる解放は採用せず、上記の再実行で全10件の成功を確認した。

## 同OSのCI負荷と削減案

同じWindowsジョブの専用監査はStage111 289.339秒、Stage112 220.427秒、Stage113 513.042秒。
100校の1回の初回保存・コピー・進級はそれぞれ6.371 / 8.668 / 12.512秒であり、
513秒の監査全体には9件それぞれの独立source/target初期化、異source作成、複数process故障、旧版exportも含む。
単回の実測であり、初回失敗runと再実行の差を高速化効果とは扱わない。

優先的な比較案は、破壊しない検索/gate試験間だけで同じ不変sourceを共有し、
各試験前後のSHA・実体ID照合は維持する方法である。差替・hot journal試験のsourceは独立を保つ。
まだ共有による短縮は実証しておらず、今回は独立した全10件・既存15版・全回帰を維持した。
校別commitごとの全100校再検証を避け、検証走査は操作単位の線形処理としている。
単件school/player APIは呼出しごとに完全照合し、大量履歴検索は受理済みbrowseを一回取得した後に
既存archiveの索引検索を使う。製品GUIの恒久キャッシュやwriter/schema変更は実施していない。

文書・実測JSON反映後の最終CI状態は [PR #282のChecks](https://github.com/0916habutaro/kokosimnew/pull/282/checks)
を参照する。未マージ・auto-merge無効でレビュー待ちにする。

## 維持する既存検証と限界

山梨31試合完全A・32team/33学校・過去履歴、Stage111/112、Windows native Tk/SQLite、
旧15版候補RO verify、全unittest、関東8都県17校E2Eを既存CIで確認する。
50/100/200年は既存Stage112の長野1校の学校ロスター単独試験であり、200年完全試合履歴の実績ではない。
任意の既存save/backup、製品writer、migration/restore、2027大会進行は対象外。
個人Windows PC手動操作、ログイン切替・再起動は未検証。
