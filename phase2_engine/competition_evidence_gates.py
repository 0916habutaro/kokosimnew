"""Stage115: read-only saved-year evidence gates, never a season-start token.

Only fictional declarations have an accepting adapter in this stage. A source
label, URL, digest or caller's authority enum cannot authenticate official data.
No database/path is accepted by this API; Stage111/114 owns the SQLite reads.
"""
from dataclasses import asdict, dataclass
from datetime import date
from enum import Enum

from .registered_full_a_lab_store import canonical, digest
from .saved_practice_match import saved_authority

RECIPE = 'stage43g115_competition_evidence_v1'


class Authority(Enum):
    FICTIONAL_DECLARATION = 'self_created_fictional_scenario'
    HISTORICAL_CONTEXT = 'historical_context_not_future_authority'
    OFFICIAL_CLAIM = 'unaccepted_official_claim'


@dataclass(frozen=True)
class Evidence:
    authority: Authority
    year: int
    source: str
    recipe: str


@dataclass(frozen=True)
class EntryTeam:
    entry_team_id: str
    # Explicit school/program membership; a team is not a school authority.
    programs: tuple[tuple[str, str], ...]
    player_ids: tuple[str, ...]


@dataclass(frozen=True)
class EntrySet:
    evidence: Evidence
    teams: tuple[EntryTeam, ...]


@dataclass(frozen=True)
class JointComposition:
    evidence: Evidence
    teams: tuple[tuple[str, tuple[tuple[str, str], ...]], ...]


@dataclass(frozen=True)
class QualificationDecision:
    entry_team_id: str
    eligible: bool
    basis: str  # explicit_scenario or saved_prior_year
    exempt: bool


@dataclass(frozen=True)
class Qualification:
    evidence: Evidence
    decisions: tuple[QualificationDecision, ...]
    prior_year_receipt_sha256: str | None


@dataclass(frozen=True)
class DistrictRules:
    evidence: Evidence
    rule_version: str
    district_id: str
    # school, program, district; independently declared for this year
    memberships: tuple[tuple[str, str, str], ...]


@dataclass(frozen=True)
class SeedRules:
    evidence: Evidence
    rule_version: str
    # Explicitly empty means no seeds; None means unknown.
    seeds: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class DrawRules:
    evidence: Evidence
    method: str
    participant_slots: int
    bracket_size: int
    bye_count: int


@dataclass(frozen=True)
class Schedule:
    evidence: Evidence
    # Only a declared date envelope for feasibility. No matches are scheduled.
    round_dates: tuple[str, ...]


@dataclass(frozen=True)
class CompetitionRequest:
    competition_id: str
    year: int
    competition_type: str
    namespace: str
    entries: EntrySet | None = None
    joints: JointComposition | None = None
    qualification: Qualification | None = None
    districts: DistrictRules | None = None
    seeds: SeedRules | None = None
    draw: DrawRules | None = None
    schedule: Schedule | None = None


@dataclass(frozen=True)
class GateReport:
    recipe: str
    competition_id: str
    year: int
    namespace: str
    roster_year_accepted: bool
    prior_sealed_year_checked: bool
    entry_set_checked: bool
    joint_composition_checked: bool
    qualification_checked: bool
    district_rules_checked: bool
    seed_rules_checked: bool
    draw_checked: bool
    schedule_checked: bool
    fictional_scenario_ready: bool
    official_year_verified: bool
    product_season_start_authorized: bool
    reasons: tuple[str, ...]
    # canonical typed inputs bind every independent gate, including absent ones.
    evidence_digests: tuple[tuple[str, str], ...]
    request_sha256: str

    def to_dict(self):
        return asdict(self)


def _payload(value):
    if isinstance(value, Authority):
        return value.value
    if hasattr(value, '__dataclass_fields__'):
        return {k: _payload(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {k: _payload(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_payload(v) for v in value]
    return value


def _sha(value):
    return digest(canonical(_payload(value)))


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _unique(values):
    return len(values) == len(set(values))


def _evidence(item, expected, year):
    _require(type(item) is expected, 'typed_contract_required')
    e = item.evidence
    _require(type(e) is Evidence and type(e.authority) is Authority,
             'typed_authority_required')
    _require(e.authority is Authority.FICTIONAL_DECLARATION,
             'no_accepted_official_authority_adapter')
    _require(type(e.year) is int and e.year == year, 'evidence_year_mismatch')
    _require(type(e.source) is str and bool(e.source.strip())
             and type(e.recipe) is str and bool(e.recipe.strip()), 'source_recipe_required')


def dry_run(lab, request, *, fictional_opt_in=False):
    """Validate only; saved source checks precede every call, no reusable token.

    Partial requests enumerate missing evidence. Malformed contracts fail closed.
    All official gates remain false, including for an official-looking URL.
    The prior receipt proves a sealed game history, never real-world eligibility.
    """
    _require(type(request) is CompetitionRequest, 'typed_competition_request_required')
    _require(type(request.year) is int and request.year == 2027, 'saved2027_year_required')
    snap, rosters, _, raw = saved_authority(lab)
    base = snap.repo.competition(request.competition_id)
    _require(request.competition_type == base['competition_type'], 'competition_type_mismatch')
    _require(type(request.namespace) is str and bool(request.namespace), 'namespace_required')
    fictional = request.namespace.startswith('fictional:') and len(request.namespace) > len('fictional:')
    enabled = fictional and fictional_opt_in is True
    reasons = []
    if not enabled:
        reasons.append('explicit_fictional_namespace_and_opt_in_required')
    prior_sha = digest(raw)
    schools = {r.school_id: r for r in rosters}
    people = {p.player_id: (r.school_id, r.program_id) for r in rosters for p in r.players}
    teams = request.entries.teams if type(request.entries) is EntrySet else ()
    team_ids = tuple(t.entry_team_id for t in teams if type(t) is EntryTeam)
    programs = tuple(pair for t in teams if type(t) is EntryTeam for pair in t.programs)
    checks = {}
    digests = [('saved_roster', _sha(tuple(r.to_dict() for r in rosters))),
               ('prior_sealed_year', prior_sha)]
    contracts = (('entry_set', EntrySet, request.entries),
                 ('joint_composition', JointComposition, request.joints),
                 ('qualification', Qualification, request.qualification),
                 ('district_rules', DistrictRules, request.districts),
                 ('seed_rules', SeedRules, request.seeds),
                 ('draw', DrawRules, request.draw), ('schedule', Schedule, request.schedule))
    for key, expected, item in contracts:
        digests.append((key, _sha(item)))
        checks[key] = False
        if item is None:
            reasons.append(key + ':missing_evidence')
            continue
        try:
            _evidence(item, expected, request.year)
            _require(enabled, 'fictional_declaration_not_opted_in')
            if key == 'entry_set':
                _require(type(teams) is tuple and len(teams) >= 2
                         and all(type(t) is EntryTeam for t in teams), 'two_typed_entries_required')
                _require(_unique(team_ids) and all(type(tid) is str and tid.startswith(request.namespace + ':')
                         for tid in team_ids), 'duplicate_or_foreign_team_namespace')
                _require(_unique(programs) and _unique([s for s, _ in programs])
                         and _unique([p for _, p in programs]), 'school_program_or_joint_double_entry')
                registered = []
                for t in teams:
                    _require(type(t.programs) is tuple and bool(t.programs)
                             and type(t.player_ids) is tuple and len(t.player_ids) == 20,
                             'explicit_programs_and_20_registered_players_required')
                    for sid, pid in t.programs:
                        _require(sid in schools and schools[sid].program_id == pid,
                                 'unknown_saved_school_program')
                    _require(all(pid in people and people[pid] in t.programs for pid in t.player_ids),
                             'graduated_unknown_or_other_school_player')
                    _require({people[pid] for pid in t.player_ids} == set(t.programs),
                             'joint_member_without_registered_player')
                    registered.extend(t.player_ids)
                _require(_unique(registered), 'duplicate_permanent_player_id')
            else:
                _require(checks['entry_set'], 'valid_entry_set_required')
                if key == 'joint_composition':
                    expected_joints = tuple((t.entry_team_id, t.programs) for t in teams if len(t.programs) > 1)
                    _require(type(item.teams) is tuple and item.teams == expected_joints,
                             'explicit_joint_composition_mismatch')
                elif key == 'qualification':
                    _require(type(item.decisions) is tuple
                             and all(type(d) is QualificationDecision for d in item.decisions)
                             and sorted(d.entry_team_id for d in item.decisions) == sorted(team_ids),
                             'qualification_must_cover_each_entry_once')
                    _require(all(d.basis in ('explicit_scenario', 'saved_prior_year')
                                 and d.eligible is True and type(d.exempt) is bool for d in item.decisions), 'unsupported_qualification_or_exemption')
                    uses_prior = any(d.basis == 'saved_prior_year' for d in item.decisions)
                    _require(item.prior_year_receipt_sha256 == (prior_sha if uses_prior else None),
                             'prior_sealed_year_receipt_mismatch')
                elif key == 'district_rules':
                    _require(type(item.rule_version) is str and bool(item.rule_version.strip())
                             and type(item.district_id) is str and bool(item.district_id.strip()),
                             'district_rule_version_required')
                    _require(type(item.memberships) is tuple and sorted(item.memberships)
                             == sorted((s, p, item.district_id) for s, p in programs),
                             'district_membership_must_cover_each_program_once')
                elif key == 'seed_rules':
                    _require(type(item.rule_version) is str and bool(item.rule_version.strip())
                             and type(item.seeds) is tuple, 'explicit_seed_rule_required')
                    _require(_unique([t for t, _ in item.seeds]) and _unique([n for _, n in item.seeds])
                             and all(t in team_ids and type(n) is int and 1 <= n <= len(teams)//2
                                     for t, n in item.seeds), 'invalid_or_duplicate_seed')
                elif key == 'draw':
                    n, size = item.participant_slots, item.bracket_size
                    _require(item.method == 'single_elimination' and type(n) is int and n == len(teams)
                             and type(size) is int and n <= size < 2*n and size & (size-1) == 0
                             and type(item.bye_count) is int and item.bye_count == size-n,
                             'draw_slots_bracket_or_byes_mismatch')
                elif key == 'schedule':
                    _require(checks['draw'], 'valid_draw_required')
                    dates = item.round_dates
                    _require(type(dates) is tuple and len(dates) == request.draw.bracket_size.bit_length()-1
                             and list(dates) == sorted(set(dates)), 'ordered_distinct_round_dates_required')
                    parsed = [date.fromisoformat(d) for d in dates]
                    _require(all(d.year == request.year and d.isoformat() == raw_date
                                 for d, raw_date in zip(parsed, dates)), 'schedule_year_or_format_mismatch')
            checks[key] = True
        except (ValueError, TypeError, AttributeError) as error:
            # Keep the stable gate name and a useful contract failure reason.
            reasons.append(key + ':' + str(error))
    ready = enabled and all(checks.values())
    reasons.extend(('official_2027_entry_unknown', 'official_2027_joint_composition_unknown',
                    'official_2027_qualification_unknown', 'official_2027_district_rules_unknown',
                    'official_2027_seed_unknown', 'official_2027_schedule_unknown',
                    'product_season_start_not_authorized_in_stage115'))
    return GateReport(RECIPE, request.competition_id, request.year, request.namespace, True, True,
        checks['entry_set'], checks['joint_composition'], checks['qualification'], checks['district_rules'],
        checks['seed_rules'], checks['draw'], checks['schedule'], ready, False, False,
        tuple(reasons), tuple(digests), _sha(request))
