# Stage 43G-28：封印v2 A方式と年度ロスターの恒久選手ID照合

作成日：2026-10-11。前工程PR #168（Stage43G-27）は全CI成功後、mainへマージ済み（`82b6236561d3f80df4c5b092f380fa472c9ee3e6`）。

## 目的

前工程の`fictional_option_a_v2.sqlite3`は、10000年度の試合・得点・各種box scoreを別原本として安全に残せるが、合成選手`SCALE-*`などのIDが、その年度に正式保存された20人ロスターの恒久`player_id`かどうかは未検証である。その状態で旧`career_player_stat_cache`に自動合算してはならない。

今回は**封印済みv2側試合を、別原本`career_rosters.sqlite3`の同一年・同一校の保存済みロスターと読み取り専用で照合する検証レイヤー**を追加する。過去のA方式原本、v2原本、カレンダー、ロスター、既存成績キャッシュは変更しない。

## 追加物

- `phase2_engine/career_v2_roster_attribution.py`：`CareerV2RosterAttribution.school_year(year, school_id)`
- `tests/test_stage43g28_v2_roster_attribution.py`：10000年度の2校20人ずつを保存した試験データで検証
- `.github/workflows/career-v2-roster-attribution.yml`：専用CI

## 整合性・改変防止ルール

1. v2側は`year_matches`のSHA・カレンダー整合・封印台帳検証を再利用し、**sealed年度のみ**統計集計を認める。active年度は拒否。
2. 選択校だけでなく対戦校についても`career_school_rosters(year,school_id)`原本を取得・SHA照合する。実在しない年度ロスターを合成で埋めない。
3. 各ロスターに含まれる選手について、`career_player_identities`の`school_id`・`entry_year`・ID・身元JSON SHAが一致することを確認する。氏名・背番号による推測照合は禁止。
4. 打者・投手行の`school_id`は対戦2校のどちらか、`player_id`はその年度ロスター内の恒久IDでなければ拒否。同じ試合・同じ区分の重複選手、非整数・負数、打撃内訳不整合も拒否。
5. 正常に検証できた試合だけを、従来の`CareerPlayerRecordView`の指標定義に沿って**メモリ上で集計**する。出塁率・打率・防御率などの算式は既存実装を再利用し、投手勝敗や打席イベントは推定しない。
6. ロスター不存在、選手ID改変、原本SHA改変、不完全な個人成績を拒否する。検証処理では`mode=ro`のSQLite接続のみ利用し、閲覧時に新規DB・索引を作らない。

## 非保証・残工程

- 10000年度データはあくまで**架空合成年度**の検証。全国大会進行・年度繰越や正式GUIを実行する機能ではない。
- 本Stageは`player_year_stat_cache`や既存GUIを変更・合算しない。返す`rows`は独立して検証したv2側の暫定集計であり、本番の歴代通算記録ではない。
- 既存のG-27合成`SCALE-*`選手は、正式年度ロスターの恒久IDではない限り**拒否されるのが正しい**。今回の試験では実際に保存した年度ロスターIDへ付け替えた合成試合のみを認める。
- ゲーム内の卒業・入学や連年選手帰属の保証には各年のロスター遷移が必要。次工程でv2専用キャッシュ（原本と別ファイル）への年度封印・ID帰属・差分生成を検討する。
- 現実的な全国3000校・長期100年の性能・ディスク費用は未計測。読み出しは年度の全A原本を毎ページ再検証するため、大規模な性能を保証しない。

## 監査

```bash
python -m unittest discover -s tests -p 'test_stage43g28_v2_roster_attribution.py' -v
python -m unittest discover -s tests -p 'test*.py'
```

PRマージ条件：Python全unittest、関東17校E2E、G-28専用CI、関連v2互換CIが成功していることを確認する。
