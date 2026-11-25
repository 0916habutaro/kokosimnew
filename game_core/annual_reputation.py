"""セーブごとの学校評判。確定した大会を一度だけ、翌4月の入学前に反映する。"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
import math
from pathlib import Path
from statistics import NormalDist

from .ability_config import load_config
from .school_reputation import reputation_for


# 目標の点を比べるときの桁数。点は重み×到達点の和なので、これより細かい差は計算の誤差
POINT_DIGITS = 9


def _shares(scores):
    order = sorted(scores, key=lambda sid: (scores[sid], sid))
    return {sid: (i + 0.5) / len(order) for i, sid in enumerate(order)}


KOSHIEN_TYPES = ('national_championship', 'national_invitational')


def _century_schools(season, competition_id: str) -> set[str]:
    """選考の記録（select_invitational の selection_basis）で21世紀枠に選ばれた学校。"""
    for entry in getattr(season, 'history', None) or ():
        if entry.get('action') == 'select_invitational' and entry.get('competition_id') == competition_id:
            return {sid for sid, basis in (entry.get('selection_basis') or {}).items() if basis == 'century'}
    return set()


def _prefecture(season, school_id: str) -> str:
    try:
        return season.repo.team(school_id).prefecture_code
    except (KeyError, AttributeError):
        return ''


def koshien_prefecture_games(season, matches) -> dict[str, list[int]]:
    """都道府県 → [勝ち, 試合]。甲子園の勝ち負けのついた試合のうち、県どうしの試合だけ（同じ県どうしは数えない）。"""
    out: dict[str, list[int]] = {}
    for match in matches:
        if not match.winner_id or not match.loser_id:
            continue
        winner, loser = _prefecture(season, match.winner_id), _prefecture(season, match.loser_id)
        if not winner or not loser or winner == loser:
            continue
        out.setdefault(winner, [0, 0])
        out.setdefault(loser, [0, 0])
        out[winner][0] += 1
        out[winner][1] += 1
        out[loser][1] += 1
    return out


def initial_prefecture_records(root: Path) -> tuple[dict[str, float], dict[str, float]]:
    """史実の県どうしの試合の勝ち・試合（``school_reputation_v1`` の ``prefecture_strength.years`` の年）。"""
    from .school_reputation import koshien_game_records

    import json

    strength = json.loads((Path(root) / 'config/abilities/school_reputation_v1.json')
                          .read_text(encoding='utf-8'))['prefecture_strength']
    first, last = (int(y) for y in strength['years'])
    records = koshien_game_records(Path(root) / 'historical_data', first, last)
    return ({code: float(w) for code, (w, g) in records.items()},
            {code: float(g) for code, (w, g) in records.items()})


class AnnualReputation:
    def __init__(self, root: str | Path, seed: int, first_year: int = 2026):
        root = Path(root).resolve()
        initial = reputation_for(str(root))
        self.config = load_config(
            root / 'config/abilities/annual_reputation_v1.json',
            expected_config_id='annual_reputation_v1',
        ).payload
        if not 0 < self.config['carry'] < 1:
            raise ValueError('annual reputation carry must be between 0 and 1')
        if not 0 < self.config['max_annual_change_z'] < math.inf:
            raise ValueError('annual reputation change limit must be positive and finite')
        for weights in ('competition_weights', 'finish_points'):
            if any(not 0 <= v < math.inf for v in self.config[weights].values()):
                raise ValueError(f'annual reputation {weights} must be nonnegative and finite')
        recent = self.config['recent_year_weights']
        if not recent or any(not 0 <= v < math.inf for v in recent) or not recent[0] > 0:
            raise ValueError('annual reputation recent_year_weights must be nonnegative and finite')
        rule = self.config.get('prefecture_strength') or {}
        if rule and (not 0 < float(rule['decay']) <= 1 or not 0 <= float(rule['shrink_games']) < math.inf
                     or not 0 <= float(rule['scale']) < math.inf):
            raise ValueError('annual reputation prefecture_strength needs 0<decay<=1 and finite scale, shrink_games >= 0')
        self.rank_labels = initial.config['rank_labels']
        self.mean, self.stddev = initial._mean, initial._stddev
        self.edits = {}
        self.seed = seed
        self.first_year = self.updated_year = first_year
        # z は順位の正規変換。初年度は従来の program_z と完全に同じ。
        self.values = {sid: initial.program_z(sid, seed) for sid in initial.school_ids}
        self.intake_by_year = {first_year: dict(self.values)}
        self.counted: set[tuple[int, str]] = set()
        # 完了日、学校ごとの点。年度が閉じて大会の状態を手放しても残る。
        self.pending: dict[tuple[int, str], tuple[str, dict[str, float]]] = {}
        # 更新した年 → その1年の学校ごとの点（点のある学校だけ。直近の年数分だけ残す）
        self.yearly_points: dict[int, dict[str, float]] = {}
        # 学校 → ゲームの中の甲子園（夏・選抜）の出場の年度（大会を持つシーズンの年度。選抜は前の年度）。
        # 21世紀枠の選抜は数えない。入部品質の公立の上乗せ（school_intake の public_component）に使う
        self.koshien: dict[str, list[int]] = {}
        # 県の強さ（甲子園の県どうしの試合の勝ち・試合）。初めは史実（初期の評判の県の差と同じ年の範囲）、
        # 毎年4月に decay を掛けてからゲームの甲子園の試合を足す。県大会の点の重みに使う
        self.prefecture_wins, self.prefecture_games = initial_prefecture_records(root)
        self.prefecture_pending: dict[tuple[int, str], tuple[str, dict[str, list[int]]]] = {}

    def program_z(self, school_id: str, entry_year: int) -> float | None:
        year = max(self.first_year, entry_year)
        if year not in self.intake_by_year:
            raise ValueError(f'reputation for intake {year} is not fixed yet')
        return self.intake_by_year[year].get(school_id)

    def rank(self, school_id: str) -> str:
        share = _shares(self.values).get(school_id)
        if share is None:
            return ''
        return next(label for label, minimum in self.rank_labels if share >= float(minimum))

    def edit(self, school_id, value, mode, day, *, minimum, maximum):
        from .school_edits import number

        if school_id not in self.values:
            raise ValueError("その学校には評判がありません")
        value = number(value, minimum, maximum, "評判値")
        if mode not in ("automatic", "fixed"):
            raise ValueError("評判の更新方式が不正です")
        self.values[school_id] = value
        self.edits[school_id] = {"requested": value, "mode": mode, "date": day}
        # 入学済みの年度は書き換えない。次の4月に初めて新入生へ反映する。

    def collect(self, seasons) -> None:
        """予選も含め大会全体が確定してから採る。試合別の点との二重加算はしない。"""
        for year, season in sorted(seasons.items()):
            for cid, scheduled in sorted(season.competitions.items()):
                key = (year, cid)
                if key in self.counted or key in self.pending or not scheduled.is_complete:
                    continue
                run = scheduled.to_competition_run()
                outcome = run.outcome
                if outcome is None:
                    continue
                competition = season.repo.competitions[cid]
                weight = self.config['competition_weights'][competition['competition_type']]
                points = defaultdict(float)
                finish = self.config['finish_points']
                # 順位決定戦・予選の試合数や不戦勝によらず、最終到達点を1回だけ使う。
                for sid in run.entrant_school_ids:
                    points[sid] = float(finish['appearance'])
                for sids, label in (
                    (outcome.quarterfinalist_school_ids, 'best8'),
                    (outcome.semifinalist_school_ids, 'best4'),
                    ([outcome.runner_up_school_id], 'runner_up'),
                    ([outcome.champion_school_id], 'champion'),
                ):
                    for sid in sids:
                        if sid:
                            points[sid] = max(points[sid], float(finish[label]))
                # 連合チームの結果は構成校それぞれに付ける（初期値の union_start と同じ考え方）
                from .joint_teams import union_teams

                for team in union_teams(season, cid):
                    if team.lead in points:
                        for partner in team.partners:
                            points[partner] = max(points[partner], points[team.lead])
                completed = [m.completed_on for m in scheduled.matches.values() if m.completed_on]
                if not completed:
                    continue
                ctype = competition['competition_type']
                if ctype in self._prefecture_rule().get('weighted_competition_types', ()):
                    points = {sid: p * self.prefecture_factor(_prefecture(season, sid)) for sid, p in points.items()}
                self.pending[key] = (max(completed), {sid: p * weight for sid, p in points.items()})
                if ctype in KOSHIEN_TYPES:
                    self.__dict__.setdefault('prefecture_pending', {})[key] = (
                        max(completed), koshien_prefecture_games(season, scheduled.matches.values()))
                if competition['competition_type'] in KOSHIEN_TYPES:
                    century = _century_schools(season, cid)
                    koshien = self.__dict__.setdefault('koshien', {})
                    for sid in run.entrant_school_ids:
                        if sid not in century:
                            koshien.setdefault(sid, []).append(year)

    def _prefecture_rule(self) -> dict:
        return self.config.get('prefecture_strength') or {}

    def prefecture_rate(self, code: str) -> float:
        """県の強さ：甲子園の県どうしの試合の勝率を5割に寄せた値 (勝ち + k×0.5)/(試合 + k)。"""
        k = float(self._prefecture_rule().get('shrink_games', 0.0))
        wins = self.prefecture_wins.get(code, 0.0)
        games = self.prefecture_games.get(code, 0.0)
        return (wins + k * 0.5) / (games + k) if games + k > 0 else 0.5

    def prefecture_factor(self, code: str) -> float:
        """県大会の勝ち上がりの点に掛ける 1 ＋ scale ×（県の強さ − 0.5）（0より小さくしない）。"""
        scale = float(self._prefecture_rule().get('scale', 0.0))
        return max(0.0, 1.0 + scale * (self.prefecture_rate(code) - 0.5)) if code else 1.0

    def _update_prefectures(self, day: date) -> None:
        """4月1日：県の強さの勝ち・試合に decay を掛け、前の日までに終わった甲子園の県どうしの試合を足す。"""
        decay = float(self._prefecture_rule().get('decay', 1.0))
        for table in (self.prefecture_wins, self.prefecture_games):
            for code in table:
                table[code] *= decay
        pending = self.__dict__.setdefault('prefecture_pending', {})
        for key, (completed, records) in list(pending.items()):
            if completed >= day.isoformat():
                continue
            for code, (wins, games) in records.items():
                self.prefecture_wins[code] = self.prefecture_wins.get(code, 0.0) + wins
                self.prefecture_games[code] = self.prefecture_games.get(code, 0.0) + games
            del pending[key]

    def update(self, day: date) -> bool:
        if (day.month, day.day) != (4, 1) or day.year <= self.updated_year:
            return False
        if day.year != self.updated_year + 1:
            raise ValueError('reputation must be updated in consecutive school years')
        totals: dict[str, float] = defaultdict(float)
        for key, (completed, points) in list(self.pending.items()):
            if completed >= day.isoformat():
                continue
            for sid, value in points.items():
                if sid in self.values and value:
                    totals[sid] += value
            self.counted.add(key)
            del self.pending[key]
        self._update_prefectures(day)
        recent = [float(w) for w in self.config['recent_year_weights']]
        self.yearly_points[day.year] = dict(totals)
        for year in [y for y in self.yearly_points if y <= day.year - len(recent)]:
            del self.yearly_points[year]
        # 目標の点：直近の年の点を重みを付けて合わせる（今年 recent[0]、前の年 recent[1] …）
        target_points = defaultdict(float)
        for back, weight in enumerate(recent):
            for sid, value in self.yearly_points.get(day.year - back, {}).items():
                target_points[sid] += weight * value
        # 同点（点のない学校など）は前の評判の順。結果のない学校は順位がほとんど動かない。
        # 足し方による小数の誤差（0.6+0.3 と 0.75+0.15 など）で同点が崩れないよう丸めて比べる
        before = dict(self.values)
        rounded = {sid: round(value, POINT_DIGITS) for sid, value in target_points.items()}
        order = sorted(before, key=lambda sid: (rounded.get(sid, 0.0), before[sid], sid))
        carry = float(self.config['carry'])
        limit = float(self.config['max_annual_change_z'])
        normal = NormalDist(self.mean, self.stddev)
        for index, sid in enumerate(order):
            target = normal.inv_cdf((index + 0.5) / len(order))
            setting = self.edits.get(sid)
            if setting and setting['mode'] == 'fixed':
                self.values[sid] = setting['requested']
                continue
            change = (target - self.values[sid]) * (1 - carry)
            self.values[sid] += max(-limit, min(limit, change))
        self.updated_year = day.year
        self.intake_by_year[day.year] = {
            sid: normal.inv_cdf(share) for sid, share in _shares(self.values).items()
        }
        return True
