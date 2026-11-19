import duckdb
import numpy as np
import pandas as pd
import pytest

from build_star_schema import build
from build_player_segments import aggregate_players, segment_source, FEATURES
from dashboard.stats import two_proportion_pvalue
from lol_utils import config as cfg
from lol_utils.sql import install_macros


def test_item_is_counted_once_per_player_build(tmp_path, monkeypatch):
    rows=[]
    roles=cfg.STANDARD_POSITIONS
    for i in range(10):
        row=dict(data_source='test',match_id='m1',participant_id=i+1,puuid=f'player{i}',
                 game_start_utc='2026-09-01T12:00:00Z',game_duration_min=25.,
                 game_version='16.12.1',queue_id=420,source_tier='test',
                 champion_id=i+1,champion_name=f'Champion{i}',summoner_name='',riot_id_game_name='',
                 team_position=roles[i%5],team_id=100 if i<5 else 200,win=i<5,
                 kills=2,deaths=2,assists=2,kda=2.,gold_earned=10000,gold_per_min=400.,
                 total_damage_dealt_to_champions=10000,damage_per_min=400.,vision_score=20,
                 vision_per_min=.8,total_minions_killed=100,cs_per_min=4.)
        row.update({f'item{j}':1 if j==0 or (j==1 and i==0) else 0 for j in range(7)})
        rows.append(row)
    pd.DataFrame(rows).to_parquet(tmp_path/'common.parquet')
    pd.DataFrame([dict(champion_id=i+1,champion_name=f'Champion{i}',title='test',tags='Fighter') for i in range(10)]).to_csv(tmp_path/'champions.csv',index=False)
    pd.DataFrame([dict(item_id=1,item_name='Sword',gold_total=350,tags='Damage')]).to_csv(tmp_path/'items.csv',index=False)
    for name,value in [('COMMON_TABLE',tmp_path/'common'),('CHAMPIONS_REF',tmp_path/'champions.csv'),
                       ('ITEMS_REF',tmp_path/'items.csv'),('API_DIR',tmp_path/'no-api')]:
        monkeypatch.setattr(cfg,name,value)
    con=duckdb.connect()
    build(con)
    # The slot bridge keeps both swords; the mart counts ten player inventories.
    assert con.execute('SELECT COUNT(*) FROM fact_participant_item').fetchone()[0]==11
    count,wr=con.execute('SELECT appearances,winrate FROM item_stats').fetchone()
    assert count==10
    assert wr==pytest.approx(.5)


def test_segments_use_only_main_role_and_its_sample_threshold(tmp_path,monkeypatch):
    rows=[]
    for player,roles in [('a',['TOP']*11+['UTILITY']*9),('b',['TOP']*20),
                         ('c',cfg.STANDARD_POSITIONS*5)]:
        for role in roles:
            rows.append(dict(data_source='test',puuid=player,role_key=role,win=True,
                             kills=2,deaths=2,assists=2,cs_per_min=10. if role=='TOP' else 1.,
                             damage_per_min=10.,vision_per_min=1.,gold_per_min=10.))
    pd.DataFrame(rows).to_parquet(tmp_path/'fact_participant.parquet')
    pd.DataFrame([dict(data_source='test',puuid=p,riot_id_game_name=p,source_tier='test') for p in ['a','b','c']]).to_parquet(tmp_path/'dim_player.parquet')
    monkeypatch.setattr(cfg,'STAR_DIR',tmp_path)
    monkeypatch.setattr('build_player_segments.MIN_GAMES',10)
    con=duckdb.connect()
    install_macros(con)
    result=aggregate_players(con).set_index('puuid')
    assert set(result.index)=={'a','b'}
    assert result.loc['a','games']==11
    assert result.loc['a','cs_per_min']==pytest.approx(1.)
    assert result.loc['a','kda']==pytest.approx(1.)


def test_cluster_names_follow_role_baseline_not_sample_mean():
    rng=np.random.default_rng(42)
    df=pd.DataFrame(np.nan,index=range(80),columns=FEATURES)
    df['vision_per_min']=np.repeat([1.1,1.2,1.8,1.9],20)+rng.normal(0,.002,80)
    df['gold_per_min']=1+rng.normal(0,.00001,80)
    df['puuid']=[f'player{i:03}' for i in range(80)]
    result=segment_source(df)
    # Every cluster has above-role vision; no below-role label can be justified.
    assert all(name.startswith('Играет на обзор') for name in result.archetype.unique())


def test_small_samples_use_two_sided_exact_test():
    assert two_proportion_pvalue(0,5,5,5)==pytest.approx(2/252)
    assert two_proportion_pvalue(5,5,0,5)==pytest.approx(2/252)
    assert two_proportion_pvalue(0,5,0,5)==1.


def test_large_samples_keep_normal_test():
    assert two_proportion_pvalue(60,100,40,100)==pytest.approx(.004677734981047266)
