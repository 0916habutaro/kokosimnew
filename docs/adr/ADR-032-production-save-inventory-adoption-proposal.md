# ADR-032：本番save正本集合と世代公開方式の採用判断（未採用案）

- 状態：**Proposed / 未採用。ユーザーの明示承認まで本番導入・移行なし**
- 日付：2026-10-12（日本時間）、Stage43G-91 / Issue #237
- 基点：Stage90後のmain `e74397bced489a12f6c4150b7ef75b8dffe199f5`
- 関連：[ADR-026](ADR-026-deterministic-replay-save.md)、[ADR-027](ADR-027-manual-autosave-slot-chains.md)、[ADR-030](ADR-030-v2-multifile-generation-snapshot-proposal.md)、[ADR-031](ADR-031-generation-backup-recovery-evaluation.md)

## 問題と判断の対象

現行live JSONは選択した年のreplay checkpoint。archive・roster・career途中checkpoint・前年度資格/参加選択はそれぞれ別authorityで、slot全体のgenerationを定義していない。架空v2 calendar/完全Aだけの世代を公開しても、旧Aゲームの途中進行を保護しない。slot IDは通常live JSON/v2に保存されない。索引metaには絶対pathがある。[正本inventoryと機能依存](../research/stage43g91_save_inventory_design_20261012.md)を候補の前提とする。

保存を必ず同一集合へ戻すべき対象は、選択した途中checkpoint＋互換入力・当年出典と重複試合、年度またぎなら前年度封印/順位・roster系譜・参加/host/feeder証拠。封印済み全履歴/roster/identityは永久保持。派生cache/独立学校索引は不使用で始めて明示再生成/明示選択できる。旧A ISOと架空v2 tokenの運用は分離する。

## 利用者が選べる正式採用候補（選択はまだしていない）

| 選択肢 | 利点 | 導入・移行・負荷 | 未保証 / 条件 |
|---|---|---|---|
| **A. 現行保存方式維持＋独立backupのみ** | 最小の変更範囲。既存readerと旧saveを維持。停止/静止した集合の外部backupとinventoryを先に運用可能 | schema移行不要。全authority＋互換入力を漏らさずcopyし原本SHA/semantic照合する運用を定義。SQLiteにはbackup APIを使う候補。派生は別再生成 | 稼働中のDB毎backupは同時点でない。JSON rotationは全save復元でない。共通lock無しの全writer協調・公開原子性は保証しない。旧A競合の修正は別PRが先 |
| **B. immutable世代＋manifestを段階導入** | readerがpinした完全な集合を一度選択し、旧正常世代へ明示切替できる設計 | 最後に1参照を同FSで公開。全writer/reader/backupの契約変更、既存saveの参照変換/互換、署名/信頼anchor、Windows handle/Linux fsync、容量予算が必要。移行は独立承認 | manifest自体で複数DBコピーの同時点を作れない。生成時の集合固定が必要。電源断/target no-clobber/読取pin/rollbackを別試験。v2単独導入で旧A全saveを保護しない |
| **C. 共通slot lock併用（AまたはBと組合せ）** | 全参加writerとsnapshot開始を協調し世代取得中の混在を減らす | live JSON/metadata、旧A sync/seal/outcomes、roster、全career sidecar、任意index build/exportに参加規約。lock order/timeout/死亡解放/Windows/Linuxを実装・検証。copy中は進行待ち | lockだけではcrash後の多file原子公開にならない。非参加raw writer・外部restoreは防げない。NFS/複数PCの共有lockは対象範囲の決定が必要。schema不要でも全経路変更は大きい |

推奨**候補**は、まずAの静止した独立backup契約を固め、旧Aの単一DB競合を別PRで直す。その後、途中ゲーム保護にBが必要かを選び、稼働中取得が要件ならCをBと併用して評価する。推奨は承認/採用ではない。本PRでmanifest/lock/backup/restore製品APIは追加しない。

## 実装技術の比較と定量条件

| 手段 | 一貫性/OSの限界 | 容量/性能と未測定 |
|---|---|---|
| immutable generation＋manifest最後公開 | 完成した同世代集合を選ぶ仕組み。公開参照は同一FS、cross-volume renameは使えない。Linuxはfile fsyncとparent directory fsyncを定義。Windowsはopen handle/共有モード・antivirus・rename失敗/再試行とreader pinを検証。rename成功を電源断耐久性に読み替えない | 正本S、派生I、live L=S+I、保持R、staging1、復元T、新索引Jなら観測可能な概算ピーク `L + R*S + S + T*S + J*I`（派生も世代保持なら更に`R*I`）。Sは全Option A/全年度を含む。copy時間は概ねS/read-write帯域＋semantic/SHA検証、索引再生成別 |
| 共通slot lock | 全参加経路でsnapshot取得を固定。ただし各commitと公開は別。取得順の循環・再入・失効・stale lock・busy timeout/プロセス死亡・外部writerを定義 | 少なくとも集合copy/検証の間のwriter停止が発生し得る。停止時間/CPU/busy retryは本Stage未測定。lock無し/有り比較実測をしたと主張しない |
| SQLite backupで一時copy | 単一DBのcommitted WALも取得可能。多DBではそれぞれ異なるsnapshotで、JSON/metadataを含まない。固定した集合/lockとの併用候補。DB/WALのraw file copyは代替にならない | 1回につき約Sのcopy空間。busy/retry/進捗/cancellation/容量不足を定義。Stage90で静止fixtureとDB毎copy間writerの不一致を実証。稼働中全国連続ゲーム性能は未測定 |
| ATTACHと共通transaction | mainが`:memory:`でなくWALでない等のrollback journal条件下ではSQLite super-journalの複数DBcrash原子性がある。**WALではDB単位でありmulti-DB一括crash原子性が無い**。JSONや外部configには効かない | journal mode/transaction/全呼出し変更、lock競合、既存save互換を評価。copy省略可能な場面はあるがhistory保持/backupは別。OS耐久性/ATTACH性能は未実証。現行への無断導入不可 |

根拠：[SQLite ATTACH](https://www.sqlite.org/lang_attach.html)、[WAL](https://www.sqlite.org/wal.html)、[Online Backup](https://www.sqlite.org/backup.html)。Stage90の[実測報告](../research/stage43g90_generation_recovery_report_20261012.md)の全国3,746校×1年度×2試合/校は**3,746合成試合**、元集合33.7MiB、2backup＋2restore＋索引を保持した観測最大172.8MiB（約5.13倍）、backup約1.9–2.1秒、restore約1.4–1.8秒。2校×200保存年度は400合成試合。共有環境2sampleで、全国100/200年連続ゲーム・4方式比較benchmark・SLOではない。

年数をn、追加完全A/roster/証拠を年平均aとした容量の単純モデルは `S(n)=S0+n*a`。R世代を毎回full copyで保持すると `R*S(n)`。Option Aを圧縮後削除した仮想値や過去年のGCで小さく見積もらない。retention/copy-on-writeは今後の評価対象、履歴削除承認ではない。容量逼迫時は保存を安全に停止/候補を示す設計を別途選ぶ。保存可能年数の新上限は設けない。100年/1索引・32索引/1操作は検索/buildのbatch制約であり、年数上限ではない。

## 明示承認が必要な項目

1. 対象：旧A途中進行/年度またぎ/閲覧/別PC移送のどこまで同一世代を保証するか。架空v2は別のopt-in実験として保持するか。
2. slot/世代identity、private ownership/署名/鍵/永続approval anchor、未知file/外部入力catalogの扱い。SHAは認証ではない。
3. A/B/Cの選択、全writer参加範囲、共通lock order/timeout、世代生成と同FS公開/reader pinの契約。
4. 既存saveはlegacy参照のまま残すか、読み取り互換adapterを別途導入するか。移行対象/失敗時停止/元原本保持を別承認。
5. Windows/Linux/対象FSの耐久化、電源断・disk full・衝突、busy/retryの受入条件。
6. 保持世代数/容量予算/最終正常世代pin。GC/過去履歴削除はこの承認に含めず、別判断にする。
7. 派生索引の不使用→新規生成→完全照合→明示選択。旧meta/pathの書換えをしない。正式GUIは別Stage。

## 承認後の段階ロードマップとrollback条件

- 最初の別PR候補：旧A単一DBのsync/seal writer予約を最小範囲で修正し、今回のEvent scheduleを「先行側による正常封印/明示拒否」へ変更。schema/世代方式の移行は不要。Issueの指示どおり本Stageでは提案に留める。
- Aが承認された場合の最初の実装単位：停止したslotの**独立export候補作成＋全正本/互換入力inventory照合**だけ。新しい空の出力先、元save不変、派生不使用、手動レビューを受入条件とし、製品restore/切替は実装しない。
- B/Cの段階導入が承認された場合の最初の実装単位：旧A一slotのlive JSON＋history＋該当roster/選択証拠＋互換入力を対象とする**shadow generation候補の生成/拒否試験**。全入口のlock参加表と旧形式read継続を先に確認し、公開参照の製品切替は別PR/別承認。v2のみで完了としない。
- 後段で公開/pin/署名と旧save互換、明示復元、索引再生成をそれぞれ受入。自動fallback/restoreは別承認。未封印途中状態はsealed履歴契約と分ける。

必須正本/互換入力欠落、slot/世代/ledger不一致、非参加writer、同FS公開不可、Windows handle/耐久性未検証、容量超過、過去Aの得点/イニング/個人成績変化、元save書換えが一つでもあれば導入/公開を停止する。rollbackは旧形式と元原本を保存したまま最後に検証済みの参照へ**明示的に**戻す案。新しく確定した履歴を削除して巻戻すものではない。混在集合を自動promotion/修復しない。

## Stage91の決定

調査/検証資料をレビューへ提出する。**A/B/Cいずれも正式採用しない**。ADR-030/031をAcceptedへ変更せず、production manifest/共通lock/自動復元/移行/履歴削除/正式GUIを追加しない。全CI成功後もPRを未マージ・auto-mergeなしで停止する。
