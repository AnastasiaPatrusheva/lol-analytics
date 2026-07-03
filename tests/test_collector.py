"""Тесты сборщика: разбор матча и парсинг времени (riot_data_collector)."""
from riot_data_collector import flatten_match, unix_time


def _match() -> dict:
    return {
        "metadata": {"matchId": "EUW1_1"},
        "info": {
            "gameDuration": 1800, "gameMode": "CLASSIC", "gameVersion": "16.12.1",
            "queueId": 420,
            "participants": [
                {"puuid": "p1", "championId": 1, "championName": "Annie",
                 "kills": 3, "deaths": 2, "assists": 5, "win": True, "teamId": 100, "item0": 1001},
                {"puuid": "p2", "championId": 2, "championName": "Olaf",
                 "kills": 1, "deaths": 4, "assists": 2, "win": False, "teamId": 200},
            ],
        },
    }


def test_one_row_per_participant():
    rows = flatten_match(_match(), source_puuid="src", source_tier="test")
    assert len(rows) == 2


def test_fields_mapped():
    r = flatten_match(_match(), source_puuid="src", source_tier="test")[0]
    assert r["match_id"] == "EUW1_1"
    assert r["champion_name"] == "Annie"
    assert r["kills"] == 3
    assert r["win"] is True
    assert r["source_tier"] == "test"
    assert r["queue_id"] == 420


def test_missing_challenges_does_not_crash():
    # у участника нет ключа "challenges" -> метрики-челленджи None, без падения
    r = flatten_match(_match(), source_puuid="src", source_tier="test")[0]
    assert r["kda_challenge"] is None


def test_empty_participants():
    m = _match()
    m["info"]["participants"] = []
    assert flatten_match(m, "src", "test") == []


def test_unix_time_none():
    assert unix_time(None) is None


def test_unix_time_date_utc():
    # 2021-01-01 00:00 UTC = 1609459200
    assert unix_time("2021-01-01") == 1609459200


def test_unix_time_naive_assumed_utc():
    assert unix_time("2021-01-01T00:00:00") == 1609459200
