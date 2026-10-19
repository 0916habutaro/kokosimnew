# Stage43G-119-C：独立SQLite保存v3・完全監査・差分append

2026-10-20（日本時間）。対応 Issue #300、設計契約はmainの
`stage43g119b_v3_save_design_20261018.md` 全13章。
起点mainは `e4151e0fcb0dc969ec2f3a859c10ce9fa1db568e`、独立ブランチは
`stage43g119c-sqlite-v3-engine`、日本語PRは #301。PR #299とIssue #297の工程には変更を加えない。

## 実装契約と変更範囲

|段階|実装・証拠|
|---|---|
|C1|`saved_fictional_bracket_v3.py`：専用filename・lease・capability・STRICT schema・UPDATE/DELETE拒否trigger・`application_id=0x4B563303`・`user_version=3`。旧版と型・名前・header・schemaで相互拒否|
|C2|`full_audit()`：出典を再受理し、全結果をdecode、同seed runnerとイベントoracleで再計算。graphとprogressionの2系統で進出・順位を導出し、全表・入力・結果SHA・chainを比較。差分行builderを呼ばない|
|C3|`fictional_v3_dependencies.py`：process/PID・ファイル/ディレクトリidentity・サイズ・bytes SHA・出典の推移的読取manifest・未知sidecarを照合。公開操作の例外はREVOKED。監査成功だけで復帰|
|C4|現在の1試合だけを検証・直列化・INSERT。過去結果listのprefix JSONを再構築しない。公開`snapshot/next_input/receipt`と冪等再送にも境界検査。連続K=8・決勝前・完了時に完全監査|
|C5|`AppendReceipt(sequence, chain_head, db_sha256)`、最新ACKを渡す`resume(..., anchor=receipt)`。同inodeへの短いprefixの書戻しを拒否|
|C6|専用`stage43g119c_cases.py`：header/schema/各派生表/結果とSHAの同時偽造、source/config/master変更、raw write、fork/PID、link/junction、lease、混在、hot journal、commit前後kill、ACK消失、読戻し故障|
|C7|実16/32teamの全appendを独立再導出。別途、同じteam/match_id/scope/seedの制御fixtureで入力SHAを除く全結果を比較。実v2/v3大会の乱数同値は主張しない|
|C8|新設`fictional_scenario_history_v3.py`：単一・複数scenarioのread-only履歴、学校/永久選手ID、投打成績A、合同勝敗をentry teamに分離|
|C9|独立した子processでv2/v3の15/31試合を同じrunner・出典・要求・環境で計測。合成31/64/128/256件は実大会と別ハーネス|
|C10|新設`stage119c-fictional-bracket-v3.yml`：Linux/Windows並行・fail-fast無効・JSON artifact。全unittestへ入れるのは高速契約9件だけ|

既存のv1/v2保存実装、`fictional_scenario_history.py`、bracket、試合runner、旧テスト、旧workflow、
masterおよび互換catalogの338入力は変更しない。Stage119-A以前のmain `86dee10` と起点mainの双方に対する
旧ソースbytes比較、source/旧DB/masterのbytes監査、全20旧exportのRO監査を独立に行う。
既存ユーザーsaveは使わず、故障系は所有者が保持する一時領域または子process内の独立コピーだけを使用する。

## 信頼境界・保存と復旧

- 要求はオブジェクト参照の一致に加え、保存契約の正規化JSONと各公開操作で照合する。入れ子の可変コンテナを同じ参照のまま変更しても検出し、再監査途中の要求変更も拒否する。
- 状態はTRUSTED / REVOKED / COMPLETE / CLOSED。入力不正も信頼を失効させる。復元したbytesが同じでも、明示的な`full_audit()`なしに再利用しない。
- manifestは最小集合の推測を避け、`phase2_engine`・`game_core`・`config`・`data`と所有された年次/source領域を保守的に列挙する。ディレクトリidentityも記録し、元ファイルinodeを移しただけのディレクトリ交換も拒否する。
- `config/match`・ability/stats設定・学校masterを含め、ファイル追加/欠落/変更でfast pathを拒否する。スレッド内の明示的なread boundaryで一覧外の`open`/SQLite接続を拒否し、出典へのwriteも拒否する。SQLite出典接続は明示的な`mode=ro`に限定する。
- 入力生成・新試合検証・差分行導出・履歴組立をread boundary内に揃える。練習/v1履歴を指定したsnapshotは、その所有rootも呼出時manifestへ追加し、旧版の完全監査と前後digest照合を行う。履歴classはTRUSTED確立前に読み込み、fast pathでのlazy importを行わない。
- `__pycache__`は出典に使わない。境界内の未列挙bytecode読取もfail-closed。実行中のPython標準ライブラリcodeとprocess memoryは実行環境の信頼境界とする。再開時には必ず結果を再計算する。
- chainは`kokosim-v3-chain`にNULを付けたdomain separatorと、64桁lowercase ASCII hexの前chain・入力SHA・結果SHAを連結してSHA-256する。入力は`previous_chain_sha256`であり、v2の`previous_results_sha256`を流用しない。
- 書込みは`BEGIN IMMEDIATE`、`synchronous=FULL`、DELETE journal。commit後はSELECTでSHARED lockを取得してから新行を主キーで読み戻し、前後のDB SHAを比較する。
- ACK消失またはcommit後読戻し失敗では、DBに結果が入っている場合がある。REVOKEDから完全監査し、同一入力/結果を再送すると`False`。暗黙の再試行・自動監査による失効解除はしない。
- hot journal・WAL・SHM・未知sidecarは接続前に拒否し、ファイルを変更しない。自動復旧APIは設けない。テストによるjournal削除とbytes復元は、破壊試験の所有者によるfixtureの後処理である。
- Windowsのbyte-range leaseは再openした別handleから読まない。保持中の所有handleをmutex内で読み、pathとhandleのidentity、固定bytesを照合し、seek位置を戻す。出典・optional履歴のmanifestも同じ方式でleaseをSHA化する。ロックの一時解除は行わない。
- `snapshot()`が渡す履歴は検査時点のdetached snapshot。要求と可変なbracket graphを複製し、閲覧側の変更がtrusted cacheへ戻らないようにする。外部への受渡し前にDB/出典を再照合し、liveなDB閲覧キャッシュにはしない。

### anchorと残余リスク

最新receiptは呼出側がDBの外に保持し、再開時に渡す。DB領域へanchorファイルを同居させると未知ファイルとして拒否する。
`db_sha256`はACK時のbytes記録であり、後続の正常appendでは変わる。再開では保存数の下限と該当位置のchainを確認する。
**anchorなし・古いanchorでは正当な短いprefixへのrollbackを検出できない。** 独立した永続化先と製品復旧手順は後続工程。

leaseは協調的ロックであり、同一権限のraw writerを防がない。commitと読取lock開始の間に旧行だけを改変すると、
新行の読戻しに成功する窓は残る。故障試験はこの窓を実際に通し、決勝前の完全監査が完了受理を阻止することを確認する。
SHA/chain/checkpointを真正性の証明とは扱わず、電源断耐久性・悪意あるprocess memory変更への防御は主張しない。

## 実行方法

```bash
# 高速な契約だけ。全unittestの自動discover対象もこのファイルのみ追加。
python -m unittest discover -s tests -p test_stage43g119c_contract.py -v

# 本物の16/32team、全故障、全20旧export、性能JSON。重いケースはtest*.pyに置かない。
python tests/stage43g119c_audit.py --old-versions --json-output work/v3-audit.json
# native Windowsのみで --require-windows を追加する。

# 既存と同じ全unittest/skip条件とStage119-A計時。
KOKOSIM_SKIP_STAGE43G10_E2E=1 python tests/stage43g119_ci_metrics.py --json-output work/unittest-timings.json
```

出典は自己生成2026の保存31試合→受理済2027全33校/660active/924永久ID。
実在学校masterの変更、公式2027条件の補完、製品セーブ/GUI統合、実大会64team以上は行わない。
`official_year_verified=False` / `product_season_start_authorized=False` を維持する。

## 検証と実測

固定コードの専用監査は **18件・skip 0・failure 0・error 0** で成功。監査中のcode SHAは不変。所要1092.536秒。
環境はmanaged cloud Linux（GitHub Actionsではない）、Python 3.12.14 / SQLite 3.53.1、`os.cpu_count=3`。
正本は [Linux実測JSON](stage43g119c_linux_measurement_20261020.json)。本物の16/32teamの全試合、全イベント・投打成績A・永久ID・進出/順位・合同勝敗を検査した。
全20旧exportは別の独立監査で29件・skip 0成功。[旧export JSON](stage43g119c_old_exports_linux_20261020.json)。

### 同一runner・出典・要求・環境のv2/v3対照

|team/版|作成 s|play合計 s|最初 s|中間 s|決勝 s|再開 s|snapshot s|DB bytes|子最大RSS KiB|
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
|16/v2|2.677|95.554|5.408|6.887|7.863|3.239|3.110|2744320|123772|
|16/v3|5.318|11.231|0.174|3.078|6.166|3.405|0.069|2760704|127588|
|32/v2|2.941|259.493|5.953|7.716|12.239|5.013|4.881|5541888|130228|
|32/v3|5.789|20.719|0.135|3.217|6.911|3.386|0.082|5644288|184680|

16teamのplay合計の実測改善率は **88.25%**（`(v2−v3)/v2`）。

32teamのplay合計の実測改善率は **92.02%**（`(v2−v3)/v2`）。

中間は16teamの試合8、32teamの試合16で、v3はいずれもK境界の完全監査を含む。決勝はcommit前後の完全監査を含む。
作成時間はv3の方が長い。32teamのDBは102,400 bytes、子最大RSSは54,452 KiB増加した。実大会の結果列は別であり、RSSには独立oracle等も含むため、保存エンジン単独のメモリ差をこの測定から分離しない。

各ケースは新しい子process。最大RSSはその子のsource受理・再開・独立oracleを含むhigh-water値で、playだけの値ではない。親CPU・子CPU・試合ごとのCPUはJSONで区別する。
層別時間はinclusive。guard、source manifest、DB SHA、入力/新試合検証、progression/差分行、INSERT、commit、SELECT/読戻しを含み、重複する値を足して内訳比率を作らない。
実v2/v3大会ではdraw/scope/match_idが異なる。内容の乱数同値を主張せず、制御fixtureの一致と実v3の独立E2Eを別の証拠とする。単回の同条件測定であり、すべてのPCへの倍率保証ではない。

### K・失効・決勝と残余窓

16teamの自動完全監査位置は `[8, 14, 15]`、所要秒は `[2.931, 2.934, 2.812]`。
未保存0試合の不正入力で失効した後の明示的再監査は2.937秒。32teamのK/決勝コストは試合ごとのlayers/full_auditに記録する。
暫定K=8をこの規模の実測と境界試験に基づいて維持する。Kの最適値を網羅探索したとは主張しない。
最新anchorによる同inode rollback拒否、anchorなし/古いanchorでの検出不能、commit後ACK/読戻し失敗からの冪等確定を検証した。
commit/読戻し間の旧行改変が新行の検査を通る残余窓も反例として実行し、決勝前完全監査が完了受理を阻止した。

### 計測専用の決定的合成ハーネス

|N|新規導出中央値 µs|DB SHA中央値 µs|全件監査 ms|DB bytes|
|---:|---:|---:|---:|---:|
|31|51.057|38.047|0.097|73728|
|64|50.931|57.476|0.168|139264|
|128|55.499|99.335|0.457|270336|
|256|55.909|188.624|0.753|532480|

合成ハーネスは試合runner/Bracketを呼ばない。各appendは当該recordだけを直列化し、全監査はN行を1回ずつ走査する。全ケースでprefix list直列化0回。短時間の単回計測のノイズを含むため、時間値だけから一般的な漸近性能を証明したとは扱わない。実大会の上限は32team/31試合のまま。

### CI・全unittest・開発中の失敗

新設 [Linux/Windows専用workflow](../../.github/workflows/stage119c-fictional-bracket-v3.yml) は実規模・故障・旧20export・性能JSONを両OSで実行する。
GitHub Actionsの最終job/JSON artifact、Windows固有のhandle/junction/lease結果、既存全unittestのStage119-A計時とmain比は、[PR #301](https://github.com/0916habutaro/kokosimnew/pull/301)の最終検証欄を正本とする。managed Linuxの結果をGitHub CIや個人Windows PCの結果として報告しない。
全unittestへ追加するのは高速契約9件のみ。main基準JSONはPR #298のrun `39244344431`（2,453件、skip 57、5,797.1555秒）。重い新ケースはdiscover対象外であり、既存のskip条件・timeout・CI-1/CI-2の扱いは変更しない。
開発中には読取境界の補強とnative Windowsのbyte-range lease/合成接続closeの不具合を修正した。実行中のsource更新を検出した2 errorの予備監査、Windows初回失敗、ハーネス更新で中断した予備実行を[監査メモJSON](stage43g119c_preliminary_audit_notes_20261020.json)に記録し、受入・速度評価へ混ぜない。
個人Windows PC、OSログイン/再起動、電源断、製品セーブ/GUI統合、50/100/200年、実大会64team以上は未実施。

提出は未マージ・auto-merge無効・レビュー待ち。ユーザーの明示承認なしにmainへマージしない。
