# Stage 43G-88：検索1回に閉じた厳密検証共有の設計

作成日：2026-10-12（日本時間）。Issue #231。基点はPR #230マージ後のmain `cfedd2f13a3f8688f5b5b6597c97f8530807a66b`。

## 調査と変更の理由

Stage87の設計・報告・実測JSONを読み、既存実装をcProfileで確認した。年代横断検索は全シャードについて件数取得用の `limit=1` 読取を行い、その後表示を含むシャードを再度読む。各読取で `_verify_index_years` が封印台帳・カレンダー・厳密モードの全原本JSON/全所属行を検証する。

100校・2年度・400試合・対象校8試合の初回厳密検索では、索引検証2回、年度header/ledger各4回、`_verify_match` 809回を観測した。800回は400試合の重複走査、9回は件数取得時の1件と表示8件の出典確認である。全国3,746校・1年度・18,730試合では37,471回（18,730×2＋11）。単なる学校SQLの遅さではなく、全JSONのdigest・decode・所属照合の重複が主要費用だった。

シャード数をS、表示取得に寄与するシャード数をPとすると、変更前の年度範囲検証回数はS＋P、変更後はS。表示がない学校/offsetでは従来からP=0であり、全ケースが2倍になるという主張はしない。表示用SHA/所属/スコア照合の少数の再検証は維持する。

## 読取範囲と既存契約

| 境界 | page | selected_years |
|---|---|---|
| 正本v2/カレンダー/索引の出典path・schema・年度範囲 | 必須 | 必須 |
| 対象範囲の保存年度、sealed status、calendar digest、header、ledger | 全保存年度 | 全保存年度 |
| indexed_yearの年度集合、calendar/ledger SHA、試合/所属件数 | 必須 | 必須 |
| 完全A payload SHA・内容identity・承認済み論理日付・勝者得点 | 件数取得1件＋表示対象 | 対象年度の他校を含む全試合＋表示対象 |
| school_game全所属行と正本から再構成した所属、memberships digest | 全件は証明しない | 大会/学校フィルタ適用前に全件照合 |
| 表示matchの存在、SHA/token、学校所属・相手・勝敗・loser | 必須 | 必須 |
| 未封印・欠落/重複シャード・foreign source・stale index | 拒否 | 拒否 |
| 観測した検索中のSQLiteコミット/ファイル差し替え | 拒否 | 拒否 |

既存APIの引数、返値キー、ページ順、最大limit200、既定30件、offset、2大会フィルタは維持する。pageの表示外JSON/所属を全件検証済みとはしない。厳密selected_yearsは対象校0件や表示外offsetでも全校正本と全所属を検証する。検索中の競合拒否は強化する。

索引1ファイルは100年度、検索1回は最大32シャード。これらは処理単位の制約で、セーブ年度上限ではない。旧AのISO日付とv2 `G{year}:MM-DD` を分離する。GUIは既存Tkinter試験GUI、手動候補・明示選択のまま。DB schema、封印/保存/索引生成の承認方針、ゲーム方式、学校マスターは変更しない。

## 呼出し内の共有

`career_v2_school_read_index.py` に私有の `_school_read_request` / `_SchoolReadRequest` / `_VerifiedSchoolSlice` を置く。外部APIに検証済みflagやscope引数を足さず、リクエストごとに必ず新規生成する。

1. ExitStackで正本・カレンダー・各明示索引をmode=roで開く。
2. 各読取接続でBEGINし、sqlite_masterを読み、ファイルごとのread snapshotを取得する。
3. 同じ索引接続でmetadata/年度範囲/全所属を検証し、同じ正本接続の全SHA/ledger確認を行う。
4. calendarは `_SnapshotCalendar` を通して同じ接続から読む。既存calendarのschema/source/policyと `_verified` digest検証、既存 `_calendar_info` の承認条件を維持する。
5. `_VerifiedSchoolSlice` はsource/cache接続と検証済みplansのみを保持し、件数取得と表示取得がこれを共有する。全試合payloadを恒久cacheしない。strict照合用全所属リストは年度検証終了後に解放される。
6. 各シャードを1度prepareする。表示に寄与しないシャードも検証する。表示原本の `_presentation` を省略しない。
7. 結果返却前に全ファイルの独立watcherを確認し、接続とplansを閉じる。失敗時もExitStackが接続を閉じる。

単一索引APIも同じ私有readerを使うので、検証・表示の実装が二重に分岐しない。別検索・別学校・別大会には検証結果を流用しない。永続的な検証済みフラグ、schema migration、索引の自動承認・修復は追加しない。

## SQLite snapshot・data_versionの保証範囲

変更前の年代readerは原本/カレンダーの持続接続で `PRAGMA data_version` を比較した。別接続からそのDBへコミットした変更を観測できるが、各シャードの検証/件数/表示は別の接続とtransactionであり、一貫した共通読取snapshotではなかった。索引への検索途中の更新監視もなかった。

変更後は各ファイルについて読取transactionを固定する。WALなら他接続がコミットしても読取transactionは古いsnapshotを読む。snapshot内のdata_versionだけではその更新を検出できないため、BEGINしない独立watcher接続で初期/最終data_versionを比較する。ファイルpathのdevice/inodeも比較して差し替え/削除を拒否する。最大32索引＋原本＋calendarの34ファイルについて、読取34接続＋watcher34接続までを使う。

WAL競合の回帰は、件数取得直後に原本/カレンダー/索引それぞれへ実コミットを挿入し、page/selected_years両方で拒否を確認する。さらに全原本JSONの改ざん・全所属行削除後でも内部の次の表示は検証時snapshotの件数/内容を読むこと、2年度目calendar改変時も同じcalendar snapshotで検証することを確認し、最終監視で結果を拒否する。索引のbyte同一ファイル差し替えと単一索引APIのWAL監視も検証する。

**複数ファイルの完全原子性は保証しない。** snapshot取得と最終watcher確認はファイルごとに順次行われ、同時に全DBのlockを取得する処理ではない。最終watcher確認後の書込、取得前の変更、未コミット変更、SQLiteを経由しない同一inodeへの直接上書き、攻撃的なABA差し替え等を一律検出する保証はない。読み取ったsnapshot内の封印/出典整合性と、監視区間に観測したSQLiteコミットの拒否を保証範囲とする。rollback journalでは保持したread lockがwriter commitを遅延させうる。将来の複数ファイル世代整合性は別Stageで設計する。

## 検証と性能比較の運用

新規11試験とStage79/83/84/85/86/87回帰、実Tkを専用CIで実行する。通常CIは100校・2年度・400試合だけを比較し、全国校数は手動workflow_dispatchの別jobに分離する。既存全Python unittestと関東17校E2Eは従来workflowで必須確認する。

`career_v2_verification_audit` は固定baseline commitから変更前2モジュールを読み、同じfixture/seed/密度/検証モードで変更前後の返値を完全比較する。入力oracle照合、SHA不変、profile回数も記録する。ウォームアップ各1回の後、before/afterの順を交互に変えて3回測る。cProfile実行時間は別記録で、非profile時間の改善倍率に混ぜない。SQLite/OSキャッシュを排除せず、共有CPUのばらつきはmin/median/max/all samplesで公開する。Stage87の別実行の24,851msを今回before値として使用しない。

fixtureは一時ディレクトリで生成・検証・破棄する。正式セーブの指定・更新、旧A書換え、履歴削除・再圧縮は行わない。固定ms閾値は設けず、正しい拒否と全試合検証件数を合否条件とする。結果・制約・後続課題は[実測報告](stage43g88_request_verification_report_20261012.md)に記す。
