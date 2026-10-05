# 既知のレガシー成果物

`archive/legacy_tools/phase2_rule_engine_reference_stage12b.py` は Stage 12B 時点の参照バリデータです。
Stage 12F原本の時点ですでに、後続Stageで追加されたassignment/groupに対して固定件数45を前提とするため `--validate` はFAILします。
これは今回のフォルダ再構成による回帰ではありません。現行の受入基準は `python -m unittest discover -s tests -v` と `phase2_engine.season_cli` です。
