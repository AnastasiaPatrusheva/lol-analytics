import duckdb
import pandas as pd
import pytest

from build_composition_backtest import _team_scores
from lol_utils.sql import install_macros
from run_data_quality import Report, check_win_balance
from dashboard.tabs import strength


def test_backtest_requires_two_complete_teams_with_one_winner():
    roles = ['TOP', 'JUNGLE', 'MIDDLE', 'BOTTOM', 'UTILITY']
    rows = []
    for mid in ['valid', 'incomplete', 'no_winner', 'mixed', 'repeated_role']:
        for team in [100, 200]:
            for i, role in enumerate(roles):
                if mid == 'incomplete' and team == 200 and i == 0:
                    role = 'UNDEFINED'
                if mid == 'repeated_role' and team == 200 and i == 0:
                    role = 'JUNGLE'
                win = team == 100 and mid != 'no_winner'
                if mid == 'mixed' and team == 100 and i == 0:
                    win = False
                rows.append(dict(match_id=mid, team_id=team, champion_id=i,
                                 role_key=role, win=win, data_source='test'))
    fact = pd.DataFrame(rows)
    matches = pd.DataFrame({'match_id': fact.match_id.unique(),
                            'data_source': 'test', 'game_version': '16.12.1'})
    con = duckdb.connect()
    install_macros(con)
    con.register('fact_participant', fact)
    con.register('dim_match', matches)
    result = _team_scores(con, 'test', '16.12')
    assert set(result.match_id) == {'valid'}
    assert len(result) == 2


def test_quality_detects_invalid_match_despite_balanced_source():
    rows = []
    for mid, outcome in [('a', False), ('b', True)]:
        for team in [100, 200]:
            rows.extend([dict(data_source='test', match_id=mid, team_id=team,
                              win=outcome, game_duration_min=25)] * 5)
    report = Report()
    check_win_balance(pd.DataFrame(rows), report)
    check = next((r for r in report.rows if r['check'] == 'match_outcomes'), None)
    assert check is not None
    assert not check['passed']
    assert '2' in check['detail']


def test_role_example_overall_includes_rare_roles(monkeypatch):
    rows = []
    for role, n, wins in [('JUNGLE', 120, 72), ('UTILITY', 120, 48), ('TOP', 10, 0)]:
        rows.extend(dict(data_source='test', match_id=f'{role}_{i}',
                         champion_id=1, role_key=role, win=i < wins) for i in range(n))
    fact = pd.DataFrame(rows)
    matches = fact[['data_source', 'match_id']].copy()
    champions = pd.DataFrame({'champion_id': [1], 'champion_name': ['Example']})
    con = duckdb.connect()
    con.register('fact_participant', fact)
    con.register('dim_match', matches)
    con.register('dim_champion', champions)
    monkeypatch.setattr(strength, 'run', lambda sql: con.execute(sql).df())
    result = strength.role_gap_example('test', '', 30)
    assert result['total'] == 250
    assert result['overall'] == pytest.approx(120 / 250)
    assert result['best_games'] == result['worst_games'] == 120


def test_segments_do_not_depend_on_input_order():
    import numpy as np
    from build_player_segments import FEATURES, segment_source
    rng = np.random.default_rng(42)
    df = pd.DataFrame(rng.normal(size=(150, len(FEATURES))), columns=FEATURES)
    df['puuid'] = [f'player{i:04}' for i in range(len(df))]
    first = segment_source(df).set_index('puuid').sort_index()
    shuffled = segment_source(df.sample(frac=1, random_state=17)).set_index('puuid').sort_index()
    pd.testing.assert_frame_equal(first[['cluster','archetype']], shuffled[['cluster','archetype']])
