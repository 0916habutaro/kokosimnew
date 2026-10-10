# Stage 43G-21：A方式個人成績・年度ロスター・派生キャッシュの容量／閲覧性能の実測基盤

作成日：2026-10-11。前提Stage43G-20 PR #161は両通常CI＋専用50/100年ベンチマーク成功後mainへマージ済み。

## 目的と Stage43G-20 との差

Stage43G-20は保存済みスコアのみを持つ実SQLiteスキーマの試合結果を24校×50/100年で計測した。前段のStage43G-13はイニング別・打者/投手の**合成データ**と20人年度ロスターを保存できるものの、合成試合の選手IDはゲーム年度ロスターに基づいておらず、Stage43G-14/15の選手ID帰属・個人成績キャッシュ検証に使用できない。

Stage43G-21では`synthetic_ability_record`を**実際にセーブした学校×年度ロスターの選手ID**に紐づけ、A方式の打者／投手全フィールドを補完して、既存コードの本物の成績検証・封印・派生キャッシュをすべて通す。生成は模擬試合であり実大会進行エンジンではない。

## 実装

`phase2_engine/career_full_a_benchmark.py`：
- DataRepositoryから実在校IDを選び、`PlayerRosterGenerator.generate_for_school_id`＋`CareerRosterArchive.advance_and_save`によって毎年20人の保存ロスターを生成する（同一選手IDの3学年継続、卒業・新入部員の入れ替わりを含む）。
- 合成試合の`inning_scores`、`team_stats`、`batter_stats`、`pitcher_stats`を残し、後二者の選手IDを当年の保存ロスターと一致させ、Stage43G-14の全`BATTER`／`PITCHER`フィールドを補完する。
- `HistoricalMatchArchive.sync`で書き込み、`seal_year`で各年度件数・台帳SHAを封印する。封印後に限り`CareerPlayerStatCache.materialize`で全学校・全年度の派生キャッシュを作る。
- 実ファイル内の全試合がイニング・チーム・打者・投手の4リストを持つか全件確認。保存レコード数、キャッシュ行数、年度別ロスター数、恒久選手ID数を数える。
- 先頭／中央／末尾の学校を抽出し、`CareerPlayerRecordView`の原本からの個人通算と歴代打撃ランキングが`CareerStatsReadOnlyAdapter`のキャッシュからの同じ値に一致することを確認する。
- 原本・キャッシュの5種類の読み取り実測：原本個人通算、キャッシュ個人通算、原本歴代打撃ランキング、キャッシュ歴代ランキング、学校別試合ページ。反復時間の中央値msと`tracemalloc` Pythonピークbytesを収集。
- `historical_matches.sqlite3`、`career_rosters.sqlite3`、`derived_player_stats.sqlite3`の3ファイルごとの実容量と合計容量、保存・封印・キャッシュ生成に要した時間を出力。
- 3つのDBのSHA-256を閲覧前後で比較し、**閲覧でDBを更新しない**ことを確認。
- `TemporaryDirectory`に限り作成。ユーザー実セーブを書き換えず、処理終了後に一時データを削除。データマスターのみ既存dataルートから読み込む。

## CI計測条件

`.github/workflows/full-a-history-benchmark.yml`は通常PR時に以下の同一20試合の比較を実行し、GitHub Actions artifactで生の実測JSONを30日保存する。

| 試験 | データ数 | 計測範囲 |
|---|---:|---|
| A方式＋ロスター＋キャッシュ | 2校×10年×年2対戦÷2＝20試合 | 試合・ロスター・派生キャッシュ3DB、原本/キャッシュ通算・ランキング・学校試合 |
| Stage43G-20スコアのみ | 2校×10年×年1試合＝20試合 | アーカイブ1DB、学校試合ページのみ |

ゲーム試合の保存形式が異なるためスコアのみとの容量差を比較できるが、コスト全体の純粋な差ではない。試合のペアリング、年間試合数、選手出場状況も本ゲームの大会を再現していない。

テスト`tests/test_stage43g21_full_a_storage_benchmark.py`：2校×2年と4校×3年の実保存・選手ID整合・キャッシュ照合、3DBの閲覧不変、候補学校の画面実測、件数不一致拒否、規模指定バリデーション。

## 上限と未達

`run_full_a_benchmark`は学校数は偶数かつ最大100校、1～100年、各学校年1～20試合、反復1～10回。1,000`school_year_game`を超える際は`--allow-large`必須。データは仮想試合かつ選手の能力は成績算出に使われず、実試合生成や全国の大会日程とは無関係である。

**全国3000校×100年の完全A方式の性能・容量は本工程では測定していない**。正式GUI、数百年への無制限年次進行、数十万校年度のキャッシュ生成コストは後続。10年時点のメトリクスは本番の3,000校×100年に外挿しない。

## 実行コマンド

```sh
python -m phase2_engine.career_full_a_benchmark --data-root data --schools 2 --years 10 --games-per-school-year 2 --repeats 2 --output-json full-a-10y.json
```

大きな合成テストは、個別の利用可能な容量・実行時間を確認し`--allow-large`を明示的に指定する。

## 次工程候補

Stage43G-22：試合ごとのフルA方式保存容量の支配要因分析と圧縮・レコード分割候補の監査（原本の形式は変更しない）、20年/50年の少数校によるキャッシュ計測、全国規模の見積りは別モデルで表現する。エンジン全体の年数無制限については毎年の大会設定・選手育成・卒業・新規入学・セーブID維持の長期継続検証が必要。
