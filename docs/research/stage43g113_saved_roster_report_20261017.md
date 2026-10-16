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
hot journal拒否、異seed/recipe/source/学校集合拒否、ID衝突rollback、未確定公開拒否、
ファイルID差替・hardlink・sidecar拒否、close→rename→reopenを含む。

Linux Python3.12.14補助監査は10件成功、失敗0・error0・skip0、78.464秒。

|Linux補助計測|実測|
|---|---:|
|2026 source100校初回保存|0.792秒|
|targetへの保存正本コピー・照合|1.734秒|
|100校検証・進級・受理（tracemalloc有効）|3.711秒|
|2026 source DB|1,957,888 bytes|
|2027 target DB（2026履歴を含む）|3,211,264 bytes|
|進級時tracemalloc peak|17,798,030 bytes|
|OS process peak RSS|91,815,936 bytes|
|RO閲覧＋全2800永久IDの履歴検索|3.628秒|
|1/50/100校強制終了＋別process再開|9.738 / 9.963 / 10.028秒|

上記はsource保存・targetコピー・進級・RO検索・再開processでそれぞれtracemallocを有効にした実測。
RO peakは14,595,123 bytes。1/50/100校後の再開process単独は5.791 / 5.794 / 5.681秒、
tracemalloc peakは47,064,004 / 47,717,229 / 48,326,269 bytes、OS peak RSSは
110,366,720 / 111,210,496 / 111,976,448 bytes。再開processにはmodule importとsource/target照合を含む。
親processの強制終了・再開一連時間とは区別する。

SQLは `idx_career_rosters_school_year` のcovering index検索を使用。
Windows実測・CIの最終結果は実行完了後に追記する。未実行の計測値は記載しない。

## 維持する既存検証と限界

山梨31試合完全A・32team/33学校・過去履歴、Stage111/112、Windows native Tk/SQLite、
旧15版候補RO verify、全unittest、関東8都県17校E2Eを既存CIで確認する。
50/100/200年は既存Stage112の長野1校の学校ロスター単独試験であり、200年完全試合履歴の実績ではない。
任意の既存save/backup、製品writer、migration/restore、2027大会進行は対象外。
個人Windows PC手動操作、ログイン切替・再起動は未検証。
