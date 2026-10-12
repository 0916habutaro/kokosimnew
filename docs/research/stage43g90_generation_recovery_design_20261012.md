# Stage 43G-90：複数SQLiteのbackup/restore・保存世代公開契約の評価設計

2026-10-12（日本時間）。Issue #235。基点 `07b456e5ef6c1e803ddd3880c16f2a67f638307e`（PR #234マージ後main）。独立ブランチ `codex/stage43g90-generation-recovery-audit`。

本Stageは監査・独立実験・提案である。productionのschema、保存形式、writer、reader、GUI、lockを変更しない。既存saveの入力/出力を受ける復元CLI、上書き、世代削除、移行は実装しない。実験manifestを製品の新しい保存契約と解釈しない。

## 調査した実際の保存契約

Stage87〜89の設計/報告、ADR-026〜030、下表の実コードと呼出しを確認した。

| 保存物・実装 | 優先順位・正本性 | 実際の接続・保護条件 |
|---|---|---|
| `live_season_save.py` / `save_slots.py` のmanual/autosave JSON | live再開の正本。schema v1、checksum、plan/resolver契約、processed datesと決定的replay | 旧Aの実運用。manual/autosaveは別チェーン、既定backup3。latestはゲーム日付等で比較。metadataは非正本 |
| `live_game_service.py` / `historical_match_archive.py` | 旧Aの最終得点・イニング・個人成績と`career_years`の封印ledger、archive identityが正本 | JSON保存後にarchive sync。load時にもreplay後sync。旧backupをloadしても新しい履歴を消さない。ISO日付を保持。loadはread-onlyではないため監査に既存saveを渡さない |
| `career_roster_archive.py` | 年度/学校snapshot、永続選手ID、所属・入学年・identityが正本 | `career_school_rosters`と`career_player_identities`は同じSQLite。年次snapshotを不変に保存。試合JSONだけからロスター・キャリアidentityを推測しない |
| `career_calendar_v2.py` | 架空年度ごとの明示承認済みplanとSHAが正本 | 独立実験用sidecar。`G{year}:MM-DD`。旧AのISOと混ぜない。plan変更拒否。calendarのみcommit |
| `career_v2_option_a_archive.py` | 完全A payload/SHA、`v2_game_years`のstatus/件数/ledgerが正本 | 実運用live大会には接続されない。append/sealは同一v2内でBEGIN IMMEDIATE。calendarは別DBで、DB群の保存世代transactionはない |
| `career_v2_school_read_index.py` / `career_v2_school_century_shards.py` | 学校所属・年度metadata・membership SHAは再生成可能な派生索引 | 元のsource/calendar絶対pathをmetaに保存。新規targetにhard-link公開。復元先へ移すとforeign出典で拒否する。100年度/索引、最大32シャード/操作 |
| `career_player_stat_cache.py` / `career_v2_player_stat_cache.py` | 年次/学校/選手集計cacheは派生物 | 試合・ロスターが正本。復元後は不使用/明示再生成の候補。キャッシュを正本の代わりに使わない |
| `career_history_gui_bridge.py` と既存slot/学校read model | 選択/表示model。ファイルや世代の正本ではない | 新slotで新reader/proofを構築する。索引候補は自動承認しない |

旧Aの既存replayとarchive再同期は新v2の自動復元とは異なる。本PRはどちらにも手を加えない。ロスターは履歴閲覧の必須正本だが、live JSON保存と常に同じtransactionで更新されるという保証は存在しない。backup対象は単に拡張子SQLiteの全ファイルを集めるのでなく、機能ごとの依存を明示する必要がある。

## 提案する一貫性単位と公開条件（未採用）

一貫性単位を「slot identity＋承認済みgeneration＋必須正本集合」とする。旧Aを含む製品セーブの場合は選択されたlive JSON/replay契約と全封印済み履歴、ロスター/identity、必要なマスター/設定/resolver versionまでを依存として列挙する。v2 sandboxでは完全A・年次ledger・全calendar・必要なroster/identityを正本集合とする。metadata title/mtime・派生索引を必須正本としない。履歴全体を復元可能にし、最新年度だけをbackupしない。

公開可能になる条件は次の順で満たす仕様案である。

1. 利用者が候補slot/generationと必要機能を明示承認。未承認/unknown/foreign generationを選ばない。
2. 必須ファイル存在、schema/互換契約、SQLite integrity、信頼する承認記録とfile SHA/論理SHAを検証。manifest自身だけを信頼元にしない。
3. 封印status、年度集合、calendarの承認済みday、原本identity/payload SHA、ledgerを再計算。完全Aの最終得点・イニング・個人成績、学校所属、ロスター・選手identityを照合する。active年度は封印履歴として公開しない。
4. source/calendarの世代ずれ、異slot、欠損を拒否。すべて旧世代/すべて新世代/明示利用拒否だけを許す。
5. 索引を不使用として開始。必要なら復元先の新規pathで明示再生成し、新出典・全所属/SHAを検証して候補として明示承認。元の索引metaを復元先pathへ書き換えない。
6. 検証後に初めて読取結果を公開。旧世代のファイル・選択状態を先に破壊しない。

| 派生物の扱い | 利点 | 費用・保証境界 |
|---|---|---|
| 索引も必須同世代・同path | 一括読取準備の形が簡単 | path束縛で別path復元に失敗。既存schema/出典契約の移行が必要。容量増。欠損索引が正本復元を止める |
| 正本のみ必須、索引不使用/明示再生成 | 既存出典契約を維持。索引が無くても正本を保護できる | 再生成時間・新索引用容量。検索の利用開始には別の承認が必要。勝手に再生成/自動選択しない |

実験は後者を基本にする。容量/移植性実験では索引も診断用コピーとして保存するが、自動使用しない。含めた診断用ファイルのSHA異常はbundle検証で保守的に拒否する。正本だけのbackupも別テストで成立を確認する。実験にはlive JSONの世代backupは含めないため、製品セーブ全体の復旧を証明したとはしない。

## 独立実験とoracle

`career_v2_generation_recovery_audit.py` のGenerationLabは自身のTemporaryDirectory fixtureのみを所有する。CLI引数は既定profile、新規証拠JSON、回帰実行指定だけで、任意save root/復元先を取らない。既存ファイルの証拠JSON上書きも拒否する。productionからこのmoduleをimportしない。

既存Stage87の同じseed・実APIによる合成完全Aを生成する。小規模では4校×2年度G10099/G10100×34試合/校、136試合・1校68件。9イニング18half、18打者、2投手、2チーム成績を現行フィールドで保持する。対戦・得点は合成で、勝ち上がり、継投/交代/延長、実会期、能力simulation、長期同一選手の能力履歴を再現しない。

期待する学校履歴は入力から生成し、検索readerの返値から作らない。raw SQLで年度ledgerの`competition_id,match_id,record_sha256`を整列、canonical JSON/SHA256を独自に再計算する。calendarと全payloadのSHA、day/identity、イニング・打者得点・投手失点と最終スコアを照合する。全tableのschema/row集合をraw SQLでhashし、承認時とbackup/restore後を比較する。この論理SHAはSQLite page配置・journal/headerの変化を区別でき、ファイルSHAもコピー検証に別使用する。

別の旧A封印済みguardと、2校の実CareerRosterArchive初期snapshot/identityを必須集合に含める。復元したrosterと40名のplayer_historyは既存APIとraw論理SHAで照合する。合成試合のAUDIT用選手IDは実rosterへ所属付けしないため、試合→ロスターの全選手帰属を本fixtureの成果に含めない。既存Stage28/29の帰属/成績回帰は全unittestで維持する。

backupは各SQLiteのbackup APIを用いるが、承認前後・コピー後の独立proofで集合一致を確認する。これは私有fixtureの確定的スケジュールの保証であり、production writerへの共通lockや汎用multi-DB snapshotは実装していない。manifestに格納したproofと別のメモリ上承認anchorを突合する。実験の承認は関数の明示呼出しであり、製品導入に対するユーザー承認ではない。

復元は新規一時dirへ排他的新規fileをコピーして再検証する。既存dirの再利用/上書きは禁止。読取はselected_yearsで他校/表示外の全payload・所属も検証し、30/30/8、0件校、2大会filter、範囲外offsetを入力oracleと照合する。

## 障害・回復状態表

各子プロセスはmultiprocessing spawnで起動。SQLite Connection subclassのcommit/transaction出口、既存index os.link、実験copy/manifest/rename境界でPipeに到達通知を送り待機する。親が通知を受けてprocess.killし、join後に新接続で再起動相当の検証を行う。全待ち20秒上限。ランダムsleepは使わない。productionに注入hookを追加しない。

| 障害位置・内容 | 許容する観測/回復結果 |
|---|---|
| calendar commit前/後kill | 未登録/登録済みplan。封印済み旧公開世代を維持。未使用plan追加だけを新履歴と表示しない |
| append commit前/後kill | 新試合なし/activeとして1試合保存。active年度を完全封印世代として拒否 |
| seal commit前/後kill | active拒否/sealedの全ledger一致。旧公開世代は常に完全 |
| index commit前/後、hard-link公開前/後kill | 未公開temp/完成候補のみ。途中tempや一部シャードを自動承認しない |
| 候補承認前/承認後に原本変更 | 未承認backup拒否/承認proofの不一致拒否。承認recordの永続化クラッシュは未検証 |
| backup各copy・manifest・renameの前後kill | 未公開generationは拒否、公開後は全集合一致。旧公開世代を維持 |
| restore各copy・manifest前後・読取前kill | 不完全dirは拒否、完全なコピー集合だけ検証可能。自動promotionなし |
| WAL未checkpoint・commit後kill | mainファイルだけのraw copyを使わずbackup APIでcommit済み内容を回収。roで開いた復元DBに空WAL/SHMが生成され得るが、コピーに元WALを必要としない |
| rename失敗/公開target既存 | injected EACCES/既存拒否。旧世代/target guard不変。private single-owner renameであり、並行target衝突のno-clobber保証は未提供 |
| ディスク不足/コピー途切れ | ENOSPC例外注入/実際のfixture半分truncateを検出して拒否。実ディスクを満杯にしない |
| 古いmanifest/不正SHA/manifestだけ書換え | 別の承認anchor・file SHA・raw proofで拒否。署名を実装したとはしない |
| 正しい旧/新DBのcalendarを取り違え | file SHAを更新しても承認proof不一致で拒否。新原本＋旧calendarの欠落も公開しない |
| 原本/calendar/roster改ざん・欠落 | 再計算したfile SHAだけでは信頼しない。承認proof/ledger/input oracleで拒否 |
| 異slot/移植した旧索引 | slot identity/出典path不一致で拒否。コピーしたmetaを更新しない |
| DB個別backup間に実次年度保存 | コピー集合不一致で拒否。SQLite backup単体の複数DB時点保証の欠如を再現 |

SQLite/WALの実process crashを試すが、OS停止・電源断、ストレージ故障、fsyncやdirectory fsyncの耐久性、ネットワークFS、同inode raw破壊/ABA攻撃、全スケジュールの数学的原子性は未保証。manifestのflush/fsyncだけでこの保証を主張しない。

## 4方式の比較（採用判断前）

| 方式 | WAL/複数DB crash原子性 | Windows/Linuxと運用 | 容量・時間、保持/信頼 | 既存保存の移行 |
|---|---|---|---|---|
| immutable世代dir＋manifest | 全必要fileを完成させ、1つの選択世代を最後に公開する設計。renameと耐久化/reader pinを正しく定義する必要。DB毎のcommitを同時にする仕組みではない | 本実験は両OS CIの新規private dir rename。製品ではWindows open handle/antivirus、Linux dir fsync、同FS公開/衝突、電源断を別検証 | live＋保持世代＋staging＋restore＋新索引がピーク。manifest署名/ローカル信頼anchorが必要。GCは別承認 | 世代identity・選択参照・writer/reader変更が必要。既存index path束縛をどう維持するか決定が必要 |
| slot共通lock | 全writerとsnapshot確保が参加すれば論理集合を固定可能。lock自体はmulti-file書込のcrash原子性を作らない | OS lock、timeout、プロセス死亡時解放、Windows/Linux、NFSを定義。非参加writer/外部restoreは防げない | コピー数を減らし得るがbackup中のwriter待ち。lockを署名/信頼の代わりにしない | 全保存・読取・backup経路の参加契約が必要。DB schema不要でもコード移行が大きい |
| SQLite backup | 1DBのWAL commit済みsnapshotをコピーする。複数DBの同時点は保証しない（本実験で再現）。世代/lockと組合せる案 | Python3.12標準sqlite3で両OS確認。busy/retry・reader/writer監視・長期backupを別定義 | コピー1回につき集合サイズB。再生成/厳密読取時間は別計測。file SHA＋semantic proofが必要 | DB形式の移行は不要。集合承認/公開契約の追加は必要 |
| ATTACH共通transaction | WALでは複数DBの一括crash原子性は保証されない。rollback journal条件（mainが:memory:でなくWALでない）ではsuper-journalで成立するSQLite仕様だが今回実証しない | journal modeとsynchronous、OS/FS故障、lock/busyを再設計。別path索引と独立writerを統合する必要 | snapshotコピーを省けるケースはあるがbackup/保持容量は別。実測比較なし。署名にはならない | journal/transaction/呼出し変更と既存save移行評価が必要。無断導入不可 |

根拠：[SQLite ATTACH](https://www.sqlite.org/lang_attach.html)、[WAL](https://www.sqlite.org/wal.html)、[Online Backup](https://www.sqlite.org/backup.html)。共通lock/ATTACHは設計比較のみ。4方式を同じ条件で性能benchmarkしたとの主張はしない。測定したのはprivate immutableコピー候補＋SQLite backup＋明示索引再生成の組合せである。

## 年数無制限・世代保持・容量方針案

保存年数は無制限。100年度/索引、32シャード/検索やfixture生成上限をbackup可能年数に流用しない。大きな原本のbackupは全履歴を対象にし、索引再生成/検証だけを複数batchへ分ける案を検討する。今回200保存年度の疎fixtureは3シャードで扱える。32シャードを超えるバックアップの製品公開は未実装/未保証。

正本は世代間で勝手に削除しない。保持方針案は「利用中/承認済み/復旧用の世代をpinし、失敗stagingを隔離してinventory、削除候補のみ表示」。保持数/日数、容量逼迫時の停止、参照中generation、承認record保持、暗号化/署名key、最終正常世代の定義を利用者承認後に決める。実行可能GC、古いhistory削除、自動fallbackは実装しない。既存manual/autosaveの既定3backupをこの新案で変更しない。

容量の単純見積もりは必須正本S・派生I、bundle B=S+Iならlive B＋保持R×B＋staging B＋復元S+I＋新索引I。実測には2保持backupと2復元dirと新索引を含める。時系列に同内容を2ラベルで保持する容量実験であり、実測JSONのold/newは異内容世代ではない。異なる旧/新封印世代の内容整合性は別回帰で検証する。実測はfile-size sumの観測最大であり、割当block、RSS、FS圧縮、copy内部の瞬間ピークではない。

## CI・成果物・次の判断

専用CIはUbuntu/Windows、Python3.12で小規模のkill/WAL/oracle/SHA回帰と容量測定を必須とする。大規模3,746校×短年度と200年度疎fixtureはworkflow_dispatchに分離する。固定時間閾値は置かず、41障害/世代subtest、件数・SHA・全入力oracle・不変性が合格条件。CIタイムアウトは無限待ち防止でSLOではない。全unittestと関東8都県17校E2Eは既存workflowを維持する。

[ADR-031](../adr/ADR-031-generation-backup-recovery-evaluation.md)は採用前提案。[報告書](stage43g90_generation_recovery_report_20261012.md)に実測・保証範囲を記す。次Stageは対象機能と正本集合、世代/lock/移行案、信頼元、耐久化、索引不使用時UX、保持/GCの具体的承認を必要とする。本StageのPRは全CI成功後もマージせずレビュー待ち。
