# Stage 43G-30：旧ISO原本と架空v2原本の年度横断読取判定

作成日：2026-10-11

前工程PR #170はPython3.12全unittest、関東17校E2E、v2ロスター照合・v2個人成績キャッシュCIが全成功後、mainマージ済み（`d558fdefd9d135c04c3f1f16e10482c9603ad8da`）。

## 背景

旧`historical_matches.sqlite3`は2026～9999年度までのGregorian ISO日付を表現する一方、10000年度以降の架空試合は`fictional_option_a_v2.sqlite3`に論理日付`G10000:04-01`で保存される。2026年の実際の日程を無条件に再利用することや、旧とv2に同じ年度の試合が存在する状態で、学校・選手通算成績へ合算することは危険。

## Stage 43G-30追加物

- `phase2_engine/career_cross_era_read_gate.py`：`CareerCrossEraReadGate(legacy_path, v2_path, calendar_path).inspect(years, verify_source=False)`
- `tests/test_stage43g30_cross_era_read_gate.py`：2026旧原本＋10000架空v2原本の独立読取判定、異常年度、改変、読み取り専用保証のテスト
- `.github/workflows/career-cross-era-read-gate.yml`：専用CI

## 判定契約

1. 入力は明示された**重複なしの昇順年度リスト**。全年度を推定生成することはなく、存在しない対象年度・未封印年度は拒否。
2. 旧とv2の年間台帳をまず別々に読み、**保存全体で重複年度が一つでもあれば**対象年以外でも拒否。旧は9999年度以内、v2は10000年度以降のみに限定。
3. 封印済み台帳の試合件数と全試合レコードSHAの目録を再計算し、台帳不一致を拒否。v2は承認済み架空カレンダーのSHA一致も必須。
4. `verify_source=True`の明示指定時に、旧は各元試合JSON SHA・年度・大会・試合ID・旧ISO日付を、v2は既存のA方式sidecarの原本・カレンダー・勝敗等を深く検証。
5. `inspect([2026,10000])`のように間の年度を明示していないときは、2027～9999を`unverified_intervening_year_intervals`として返す。**その間ゲームが進行した、記録がある、と判断しない**。
6. 読取は全てSQLite `mode=ro`、`query_only=ON`。閲覧でデータベース・インデックス・原本を作成・更新せず、旧実績・v2実績・個人成績キャッシュを連結・移行しない。
7. 戻り値の`routes`は各年度の選択すべき参照元と日付表現の**安全な判定情報**であり、正式画面・合算テーブル・年度横断キャッシュそのものではない。

## 2026年度旧原本と10000年度架空v2原本の検証例

```python
from phase2_engine.career_cross_era_read_gate import CareerCrossEraReadGate

gate = CareerCrossEraReadGate(
    "SAVE/historical_matches.sqlite3",
    "SAVE/fictional_option_a_v2.sqlite3",
    "SAVE/sandbox_calendar_v2.sqlite3",
)
manifest = gate.inspect([2026, 10000], verify_source=True)
# 旧: YYYY-MM-DD、架空v2: G{year}:MM-DD
# 間の2027～9999年度は未検証として明示
# 個人成績や日付を一つの表へ統合する許可は返さない
```

## 重要な留保

- 旧年度の実ゲームと、10000年度の**架空合成試合**が同一セーブで連続進行したことを証明するものではない。
- 前段のG-28/G-29も含め、10000年度に全47都道府県の大会を生成・進行させたものではない。
- 同じ恒久選手IDが新旧キャッシュに存在しても、このStageでは合算をしない。年度別入学卒業・実ロスター継続・全中間年度の完了と選手帰属の証明が別途必要。
- 高速な標準検証では台帳SHAと年度メタデータの整合まで。レコードJSONの改変は`verify_source=True`で検知。
- 3000校・50～100年の負荷測定、長期保存領域の分割・バックアップ・復旧は後続Stageへ持ち越す。

## mainマージ条件

Python全unittest・関東17校E2E・Stage 43G-30専用CI・関連v2互換CIがすべて成功してからのみmainへ反映する。作成直後のCI成功を推測せず、結果を確認する。
