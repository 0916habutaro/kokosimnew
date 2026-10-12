# Stage 43G-88：厳密SHA検証の重複削減・全国校数再監査報告

作成日：2026-10-12（日本時間）。Issue #231。基点main `cfedd2f13a3f8688f5b5b6597c97f8530807a66b`。[日本語設計](stage43g88_request_verification_design_20261012.md)。実測JSONは `audits/phase2/stage43g88/`。

## 実装と保護した範囲

学校索引の件数取得と表示取得を、API呼出し内の検証済みsliceで接続した。同じ原本年度・索引の広範囲検証は1回となり、表示のmatch出典・完全A payload SHA・学校所属・勝敗/loser照合は維持する。カレンダーはdigest検証済みの同じファイルsnapshotから取得する。

厳密selected_yearsでは学校・大会フィルタの外側にある全試合JSON SHA/identity/論理日付、全学校所属行、memberships digestも照合する。封印status・年度header・calendar SHA・全台帳SHA・indexed_yearの完全年度集合/件数も省略しない。pageは従来の限定的検証契約を維持する。返値と順序は変更前APIと完全比較した。

全ファイルにread snapshotと独立data_version watcherを持ち、検索中のSQLiteコミットやpathのdevice/inode差し替えを観測した場合は結果を拒否する。原本/カレンダー/索引のWAL競合、表示途中での原本全JSON改変/全所属削除、後続年度calendar改変、索引差し替えの回帰を追加した。ファイルごとのsnapshotは一貫しているが、複数ファイルの完全原子性は主張しない。最終監視後のコミット等、詳しい限界は設計書を参照。

保存schema・索引schema・旧A原本・保存API・索引作成API・GUI・ゲーム方式・学校マスターは変更していない。100年度/索引、32シャード/検索は維持し、ゲームの保存可能年数上限は新設しない。別リクエストの検証結果や永続的な検証済みflagは使わない。

現行マスターも再計数し、3,746校/硬式野球部、47都道府県、162大会、構造生成18,146試合（春5,899・夏5,582・秋6,665）を再確認した。独立記録は `master_20261012.json`。構造生成は実日付進行の全国大会完走ではない。

## 測定条件

Python 3.12.14 / SQLite 3.53.1 / Linux 6.18.44 x86_64。CPU quota `200000 100000`（2 core相当）。seed 2026101201。学校IDと完全Aの密度はStage87と同じ生成APIを利用する。全国fixtureは3,746校・1年度・各校10試合＝18,730試合、9イニング・18打者・2投手・2チーム、2種類の合成大会。実全国大会162大会の連続進行を再現したものではない。

**before/afterは同じ一時DB・同じseed・同じ検証水準・同じ環境**。beforeは固定mainの2モジュールをgitからロードし、afterと全返値/学校・相手・得点・大会・論理日付oracleを照合する。各APIを1回warmupし、before→after / after→before / before→afterの3組を測定した。cProfileは追加の別読取として記録し、下表の時間には混ぜていない。

OS/SQLiteキャッシュは排除していない。共有CPUであり、周辺の短い対象回帰と実行が重なる可能性もある。全unittest・関東E2Eの長い実行は4ケースの比較終了後に開始した。試行3回ではp95や速度SLOを保証できない。Stage87の全国24,851.449msは別実行時の参考値で、今回の改善倍率の分母にしない。

## 同一DBの変更前後比較

時間は非profileの3回中央値ms。倍率はbefore÷after。

| fixture | 校/保存年度/試合/索引 | page前→後ms | page倍率 | strict前→後ms | strict倍率 |
|---|---|---:|---:|---:|---:|
| small100 | 100/2/400/1 | 3.838→2.732 | 1.405 | 83.698→41.748 | 2.005 |
| national3746 | 3746/1/18730/1 | 62.777→27.392 | 2.292 | 3672.606→1789.161 | 2.053 |
| sparse200 | 2/200/400/2 | 44.884→12.805 | 3.505 | 116.955→59.489 | 1.966 |
| shards32 | 100/32/3200/32 | 39.145→23.090 | 1.695 | 514.176→322.430 | 1.595 |

| fixture | strict before min〜max ms | strict after min〜max ms |
|---|---:|---:|
| small100 | 82.553〜86.196 | 41.686〜42.959 |
| national3746 | 3593.839〜3868.038 | 1778.359〜1878.642 |
| sparse200 | 116.916〜150.736 | 52.683〜64.528 |
| shards32 | 489.822〜525.325 | 311.208〜322.770 |

200年度は2校の疎fixture、32索引は100年刻みの32保存年度で、全国200年や連続3,200年の実大会ではない。pageの倍率が重複回数より大きいケースはcalendar接続共有やキャッシュ/共有CPUを含み、個々の寄与は分解していない。

## プロファイルで確認した重複回数

| fixture | 全年度/索引検証前→後 | header/ledger前→後 | strict `_verify_match` 前→後 |
|---|---:|---:|---:|
| small100 | 2→1 | 4→2 | 809→409 |
| national3746 | 2→1 | 2→1 | 37471→18741 |
| sparse200 | 3→2 | 300→200 | 632→432 |
| shards32 | 47→32 | 47→32 | 4762→3262 |

全国は18,730試合の重複全走査を除いた結果で、18,730全試合＋11表示出典検証を残した。32索引では1件ずつの件数読取32回＋30件表示で、全走査3,200回＋62表示出典検証となる。各JSONにpage/strictの回数、全時間sample、min/median/max、実行順、環境を保存した。

## 回帰・不変性・CI

新規11件が成功。主な追加範囲は1年度/索引の検証1回、別リクエストでの再検証、page/strict意味の違い、全校混在/0件/跨ぎページ、偽SHA/digest、原本/カレンダー/索引へのWALコミット、固定snapshot、索引差し替え、単一索引APIの監視である。

実Tk付きローカル専用回帰：Stage79 10件（ベンチマーク2件含む）、Stage83 8件、Stage84 9件、Stage85 9件、Stage86 2件、Stage87 11件、新規Stage88 11件＝**60件すべて成功、スキップなし**。手動候補・索引明示選択・原本/旧A分離・失敗時のGUI保持も既存回帰で確認した。

各比較fixtureで変更前後の全返値一致、独立oracleの36読取確認、正本/calendar/旧A/索引SHA不変、一時fixture削除を確認した。既存作業環境のセーブ4ファイルとマスター106CSVも事前SHAと一致。Stage87で記載された14セーブは当時の別ファイル集合で、今回存在する4ファイルの結果と混同しない。

専用workflow `career-v2-request-verification.yml` は60回帰と100校400試合比較だけを通常CIで実行し、全SHAを省略しない。全国負荷はworkflow_dispatchの任意別jobとした。既存の全Python unittest・関東17校E2E・関連専用CIも確認し、**最終headの結果/件数/run URLはPR本文を最新の確認記録とする**。進行中/未実行は成功と扱わず、全成功後もPRはマージせずレビュー待ちで停止する。

## 未解決と次Stage候補

- 複数DBの原子的な世代snapshot、最終監視後の変更まで含む整合性プロトコルは未導入。世代識別/保存中読取/バックアップ復旧を別Stageで設計する。
- 厳密検索は依然全試合SHA/JSON・全所属を確認するためO(対象年度の全試合)である。単一学校30件だからO(30)になるとは主張しない。完全Aの統計成績をdecodeする費用が主要な残存要因。
- 多数年度のledger費用、appendの小transaction費用、メモリピーク、最大接続68本の運用評価は後続。無関係なschema変更やSHA省略は採用しない。
- 全国100/200年の実大会連続進行、能力試合の継投/交代/延長を含む容量分布、独立runnerでのcold/warm・複数seed・十分な反復数は未検証。

## 再現

```bash
python -m phase2_engine.career_v2_verification_audit
python -m phase2_engine.career_v2_verification_audit --schools 3746 --years 1 --rounds 10 --allow-large
python -m phase2_engine.career_v2_verification_audit --schools 2 --years 200 --rounds 2
python -m phase2_engine.career_v2_verification_audit --schools 100 --years 32 --rounds 2 --year-step 100 --allow-large
xvfb-run -a python -m unittest discover -s tests -p 'test_stage43g88_request_scoped_verification.py' -v
KOKOSIM_SKIP_STAGE43G10_E2E=1 python -m unittest discover -s tests -v
python -m unittest discover -s tests -p 'test_stage43g10_full_kanto17_e2e.py' -v
```

比較CLIにはbaseline commitを含むgit履歴が必要。専用CIはfetch-depth:0で取得する。出力は計測JSONのみで、既存セーブ/索引を指定するオプションはない。
