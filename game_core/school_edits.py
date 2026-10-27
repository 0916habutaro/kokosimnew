"""学校・選手の能力編集。名簿の能力を変え、戦力は同じ選手から再計算する。"""
from __future__ import annotations

from dataclasses import replace
import json
import math
from pathlib import Path

from .abilities import PitchAbility, validate_ability_snapshot
from .roster_book import SCALARS
from .team_strength import TeamStrengthGenerator


def number(value, low, high, label, *, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{label}は数値で指定してください')
    if not low <= value <= high or (integer and int(value) != value):
        raise ValueError(f'{label}は{low}〜{high}' + ('の整数' if integer else '') + 'で指定してください')
    return int(value) if integer else float(value)


class AbilityEditor:
    def __init__(self, config_root='config'):
        root = Path(config_root)
        self.config = json.loads((root / 'school_edits/ability_edits_v1.json').read_text(encoding='utf-8'))
        self.screen = json.loads((root / 'screen/screen_v1.json').read_text(encoding='utf-8'))
        self.teams = TeamStrengthGenerator(root / 'abilities')

    def player(self, snapshot, changes, pitch_types):
        if not isinstance(changes, dict) or set(changes) - set(SCALARS) - {'position_aptitude', 'pitch_repertoire'}:
            raise ValueError('編集できない能力項目があります')
        out = {}
        for name, value in changes.items():
            if name in SCALARS:
                if getattr(snapshot, name) is None:
                    raise ValueError(f'この選手には{name}の能力がありません')
                low, high = (100, 165) if name == 'velocity_kmh' else (1, 100)
                out[name] = number(value, low, high, name, integer=True)
            elif name == 'position_aptitude':
                current = dict(snapshot.position_aptitude)
                if not isinstance(value, dict) or set(value) - set(current):
                    raise ValueError('守備適性の項目が不正です')
                current.update({k: number(v, 60 if k == snapshot.primary_position else 1,
                                          100, k, integer=True) for k, v in value.items()})
                out[name] = tuple(current.items())
            else:
                if not isinstance(value, list) or not 2 <= len(value) <= 4:
                    raise ValueError('球種は2〜4種類で指定してください')
                pitches = []
                for row in value:
                    if not isinstance(row, dict) or set(row) != {'pitch_type', 'quality', 'command', 'usage'}:
                        raise ValueError('変化球の項目が不正です')
                    if row['pitch_type'] not in pitch_types:
                        raise ValueError('その球種はありません')
                    pitches.append(PitchAbility(row['pitch_type'], **{
                        k: number(row[k], 1, 100, k, integer=True) for k in ('quality', 'command', 'usage')
                    }))
                kinds = [p.pitch_type for p in pitches]
                if len(set(kinds)) != len(kinds):
                    raise ValueError('同じ球種は重複して指定できません')
                if 'four_seam' not in kinds:
                    raise ValueError('ストレートは必ず含めてください')
                if sum(p.usage for p in pitches) != 100:
                    raise ValueError('球種の使用割合は合計100にしてください')
                out[name] = tuple(pitches)
        result = replace(snapshot, **out)
        validate_ability_snapshot(result)
        return result

    def overall(self, snapshots):
        team = self.teams.generate(snapshots)
        return sum(getattr(team, k) * v for k, v in self.screen['school_overall_weights'].items())

    def target(self, value):
        if isinstance(value, str) and value in self.screen['ability_ranks']:
            return float(self.screen['ability_ranks'][value]) + self.config['team']['tolerance']
        if value == 'G':
            return float(self.screen['ability_ranks']['F']) / 2
        return number(value, 1, 100, '総合力')

    def team(self, book, players, target):
        """変化量を探索するだけ。到達を確かめてから呼出側が全員を一括保存する。"""
        target = self.target(target)
        if len(players) < 9:
            raise ValueError('総合力の調整には現在の部員が9人以上必要です')
        originals = [book.base_ability(p) for p in players]
        rule = self.config['team']

        def trial(delta):
            candidates = []
            for old in originals:
                changes = {name: max(1, min(100, round(getattr(old, name) + delta)))
                           for name in SCALARS if name != 'velocity_kmh' and getattr(old, name) is not None}
                if old.velocity_kmh is not None:
                    velocity = old.velocity_kmh
                    if delta > 0:
                        room = max(0, rule['velocity_cap'] - velocity)
                        velocity += room * (1 - math.exp(-delta * rule['velocity_delta_factor'] / room)) if room else 0
                    else:
                        velocity += delta * rule['velocity_delta_factor']
                    changes['velocity_kmh'] = max(100, min(165, round(velocity)))
                changes['pitch_repertoire'] = tuple(replace(
                    pitch, quality=max(1, min(100, round(pitch.quality + delta))),
                    command=max(1, min(100, round(pitch.command + delta))),
                ) for pitch in old.pitch_repertoire)
                candidates.append(replace(old, **changes))
            strength = self.overall([book.project_ability(p, s) for p, s in zip(players, candidates)])
            return strength, candidates

        low, high = rule['delta_range']
        trials = [trial(low), trial(high), trial(0)]
        attainable = [trials[0][0], trials[1][0]]
        for _ in range(rule['search_iterations']):
            mid = (low + high) / 2
            item = trial(mid)
            trials.append(item)
            if item[0] < target:
                low = mid
            else:
                high = mid
        achieved, snapshots = min(trials, key=lambda t: abs(t[0] - target))
        reached = abs(achieved - target) <= rule['tolerance']
        return {
            'requested': target, 'before': trials[2][0], 'achieved': achieved,
            'reached': reached, 'range': attainable,
            'reason': '' if reached else ('能力上限・球速・守備適性・現在の部員構成と復帰補正を保つと、'
                       f'総合力は約{attainable[0]:.1f}〜{attainable[1]:.1f}です。指定値には到達できません'),
        }, snapshots
