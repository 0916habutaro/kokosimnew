"""選手の怪我（game_definition.md §3.2）。

- 練習の怪我：毎月の初めにその月の分を決める（その月のどこかの日から休む）
- 試合の怪我：試合のあとに決める。投手は起きやすく、投げすぎ（1試合の球数・7日間の
  球数）・連投・その年度の公式戦の出場数でさらに起きやすい
- 重さは数日・数週間・数か月。数か月はまれ
- 怪我の間は試合に出られず、成長も止まる。復帰直後は能力が少し下がり、数週間で戻る
- 頻度はセーブごとの設定（なし・少なめ・標準・多め）の倍率を掛ける

値は ``config/players/injuries_v1.json``。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import json
from pathlib import Path
import random


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = Path("config") / "players" / "injuries_v1.json"
SEVERITIES = ("days", "weeks", "months")


@dataclass(frozen=True)
class Injury:
    start: date
    days: int
    severity: int  # 1 数日・2 数週間・3 数か月

    @property
    def end(self) -> date:
        """この日から出られる。"""
        return self.start + timedelta(days=self.days)


class InjuryModel:
    def __init__(self, root: str | Path = ROOT):
        self.config = json.loads((Path(root) / CONFIG_PATH).read_text(encoding="utf-8"))
        self.levels = self.config["levels"]

    def rate(self, level: str) -> float:
        return float(self.levels.get(level, self.levels[self.config["default_level"]])["rate"])

    def label(self, severity: int) -> str:
        return self.config["severity"][SEVERITIES[severity - 1]]["label_ja"] if severity else ""

    # ---- 起きるか ----

    def practice_chance(self, *, pitcher: bool, season_games: int, level: str) -> float:
        p = self.config["practice"]
        chance = float(p["monthly"]) * (1 + float(p["per_season_game"]) * season_games)
        if pitcher:
            chance *= float(p["pitcher_factor"])
        return chance * self.rate(level)

    def match_chance(
        self, *, pitches: int, load7: int, consecutive: int, level: str,
    ) -> tuple[float, bool]:
        """(起きやすさ, 投げすぎか)。``pitches`` が0なら打者・野手として出た試合。"""
        m = self.config["match"]
        if not pitches:
            return float(m["batter"]) * self.rate(level), False
        factor = 1 + max(0, pitches - int(m["pitches_over"])) * float(m["per_pitch_over"])
        factor += max(0, load7 - int(m["load_over"])) * float(m["per_load_over"])
        factor *= float(m["consecutive_factor"]) ** consecutive
        return float(m["pitcher"]) * factor * self.rate(level), factor > 1.0

    # ---- 重さ ----

    def draw(self, rng: random.Random, start: date, *, overuse: bool = False) -> Injury:
        s = self.config["severity"]
        shares = [float(s[name]["share"]) for name in SEVERITIES]
        if overuse:
            shares[2] *= float(s["overuse_months_factor"])
        roll = rng.random() * sum(shares)
        severity = len(SEVERITIES)
        for index, share in enumerate(shares, start=1):
            if roll < share:
                severity = index
                break
            roll -= share
        low, high = s[SEVERITIES[severity - 1]]["days_range"]
        return Injury(start, rng.randint(int(low), int(high)), severity)

    # ---- 復帰直後 ----

    def recovery_step(self, injury: Injury | None, today: date) -> int:
        """復帰直後の能力の下がり方の段階（0 は元どおり）。1週ずつ戻る。"""
        if injury is None or today < injury.end:
            return 0
        days = int(self.config["recovery"][SEVERITIES[injury.severity - 1]]["days"])
        left = days - (today - injury.end).days
        return max(0, -(-left // 7))

    def recovery_drop(self, injury: Injury, step: int) -> tuple[float, int]:
        """(1〜100の能力に掛けて下げる割合, 球速を下げる km/h)。"""
        rule = self.config["recovery"][SEVERITIES[injury.severity - 1]]
        steps = -(-int(rule["days"]) // 7)
        share = step / steps
        return float(rule["drop"]) * share, round(float(rule["velocity_kmh"]) * share)


_MODEL: InjuryModel | None = None


def injury_model() -> InjuryModel:
    global _MODEL
    if _MODEL is None:
        _MODEL = InjuryModel()
    return _MODEL
