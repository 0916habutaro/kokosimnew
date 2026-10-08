# Stage 13E-3F-4：2026年度シーズン最終統合監査

調査日：2026-10-08
基準：PR #85までのmain（年度=2026、乱数seed=2026100827）
対象：全国162大会、全MAINカレンダー162件、pre-MAIN stage calendar 50件、調査台帳26件

## 目的と監査範囲

1. 47都道府県の各県大会・10地区大会・全国大会を含む162大会のMAIN日程とステージ参照関係を点検。
2. 50のpre-MAIN日程について verified・昇順・重複なし・正規ISO日付を再検査。
3. 同一大会内のpre-MAINとMAINの日付重複を調査。**同一日の別ステージ実試合**だけは、別CSVに根拠付きで列挙し、無根拠の重複を不整合として検出する。
4. 調査台帳の21件のstage-calendarタスクがresolvedになっているか検証する。
5. full-season live runtimeを2026-12-31までseed 2026100827で実行し、依存関係の待機数、残存未完了大会、全国大会の状態を確認する。
6. 未公開の大会日程と、再現方式の設計保留を「完了」と取り違えず、別々の後続タスクとして残す。

## 重要所見：岐阜秋CMP000110の一次／二次日程

Stage 12Gで作成されたCAL000110（岐阜県秋季）は、8/29・8/30・9/5を含む「大会全体」の日付一覧をMAIN日程としても登録していた。しかし一次トーナメント（STG000207）の日付SC2026025は8/29・8/30・9/5であり、pre-MAINとMAINの境界が誤っていた。

2026年公式の**1次トーナメント**・**2次トーナメント**それぞれの結果を照合したところ：
- 2026-08-29、2026-08-30：**一次のみ**。MAINに含めない。
- 2026-09-05：一次と二次が**同じ日に並行して実施**。一次SC2026025とMAIN CAL000110の双方に登録するのが正しい。
- 2026-09-06以降：二次側の実試合日。

修正：
- CAL000110 `start_date`: 8/29 → **9/5**
- CAL000110 `game_date_list`: 8/29・8/30を除外し、9/5を含む既存の二次トーナメント試合日を維持。
- SC2026025の日付は変更しない。
- 同日開催の根拠付き例外 `data/schedules/2026/known_same_day_stage_overlaps.csv` を新設。例外として許可するのは **CMP000110 / SC2026025 / 2026-09-05 の1件だけ**。
- 例外を一律に禁止すると正しい同日開催が消えるため、不明な重複だけをFAILとする。登録した例外が今後不要になった場合もstale exceptionとしてFAILにする。

根拠：
- [岐阜県高野連・第79回秋季県大会の一次／二次最終結果](https://ghbf.asfsite.jp/event/schedule/entry-6248.html)
- [一次トーナメントの日別試合結果](https://www.hb-nippon.com/tournaments/1918)
- [二次トーナメントの日別試合結果](https://www.hb-nippon.com/tournaments/1936)

## pre-MAINの到達点

- pre-MAINステージ 50 / 50：verified
- pre-MAIN未確認：0件
- ステージ日程用research queue 21 / 21：resolved
- MAIN 162大会のカレンダー参照を維持

上記は**ゲーム用2026年モデルのカレンダー構造化の完了**を意味し、実際の2026年秋の公式大会がすべて終了したという意味ではない。

## 年間E2E最終目標（CIで検証）

- 実行seed：2026100827
- シミュレーション進行期限：2026-12-31
- 大会完了 **161/162** を維持
- 未完了1件：明治神宮大会（CMP000003）、公式の高校部の正確な試合日を待機
- pre-MAIN未到達0件、下流依存待ち0件、追加の不明なcalendar gap0件

※「完了161」はゲームの乱数シミュレーションが年末まで進めた大会数であり、2026年10月8日に実際の高校野球大会が161件終了したという意味ではない。

## 保留事項の引き継ぎ

| 調査タスク | 種別 | 状態 | 内容と取扱い |
| --- | --- | --- | --- |
| RS2026022 | P0・main_calendar | awaiting_publication | 明治神宮大会CMP000003。11/19～24の会期のみ既知。高校部の抽選前のため、個別試合日・組合せは推測せず、2026/10/17以降に公式発表を再確認 |
| RS2026025 | P2・format_research | design_pending | CMP000140・FMT022の代表決定後順位戦（徳島秋等）のnon-blocking表現を設計 |
| RS2026026 | P2・format_research | design_pending | CMP000112・FMT025の代表決定後順位戦（静岡秋等）を独立したlimited subgraphとして設計 |

現時点の神宮大会公式ページは会期 **2026/11/19～24** とする一方、高校の部の組み合わせは「抽選前」。2026/10/08時点では任意の高校部試合日を確定した扱いにしない。

公式：
- [日本学生野球協会・第57回明治神宮野球大会開催要項](https://student-baseball.or.jp/game/jingu/2026/2026jingu.html)
- [日本学生野球協会・2026高校の部の組み合わせ](https://student-baseball.or.jp/system/prog/bracket.php?d=highschool&e=jingu&k=all&m=pc&s=2026)

## 再実行手順

```bash
python -m phase2_engine.final_season_integrity_audit_cli \
  --data-dir data \
  --year 2026 \
  --seed 2026100827 \
  --output-dir out/final_season_integrity_audit

python -m unittest discover -s tests -p 'test_*.py' -v
```

監査CLIはJSONの `ok` がtrueでない場合、終了コード1を返す。報告ファイルは `final_season_integrity_summary.json` と `final_season_integrity_checks.csv`。追加調査が必要な行は `DEFERRED` として可視化し、既知例外と区別する。

CI成功後、Stage 13E-3F-4をマージし、Stage 13E-3Gでは後続の2つの順位決定戦方式と神宮公開待ちの扱いを整理する。
