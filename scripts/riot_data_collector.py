"""
Small Riot API data collector for the LoL project.

The script is intentionally incremental:
- starts from a high-tier league endpoint;
- resolves PUUIDs;
- downloads match ids for each player;
- skips already downloaded match ids using a log file;
- saves player rows, participant rows, and download log to data/api/.

Example:
    python scripts/riot_data_collector.py --tier challenger --max-players 10 --matches-per-player 5
    python scripts/riot_data_collector.py --tier master --player-offset 20 --max-players 10 --matches-per-player 5

API key:
    Set RIOT_API_KEY in the environment or paste it when prompted.
"""

from __future__ import annotations

import argparse
import os
import time
from datetime import datetime, timezone
from getpass import getpass
from pathlib import Path
from typing import Any

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parent.parent
REGION = "euw1"
MATCH_REGION = "europe"
QUEUE = "RANKED_SOLO_5x5"
QUEUE_ID = 420

DATA_DIR = PROJECT_ROOT / "data" / "api"
PLAYERS_PATH = DATA_DIR / "players_api.csv"
MATCHES_PATH = DATA_DIR / "matches_api.csv"
LOG_PATH = DATA_DIR / "download_log_api.csv"


class RiotApiError(RuntimeError):
    pass


class RiotClient:
    def __init__(self, api_key: str, request_sleep: float = 1.2, max_retries: int = 3):
        self.headers = {"X-Riot-Token": api_key}
        self.request_sleep = request_sleep
        self.max_retries = max_retries

    def get(self, url: str, params: dict[str, Any] | None = None) -> Any:
        # All Riot requests go through this method, so rate limit handling
        # and retry logic stay in one place instead of being copied across functions.
        try:
            import requests
        except ImportError as exc:
            raise RiotApiError(
                "The 'requests' package is required. Install it with: pip install requests"
            ) from exc

        for attempt in range(1, self.max_retries + 1):
            response = requests.get(url, headers=self.headers, params=params, timeout=30)

            if response.status_code == 200:
                time.sleep(self.request_sleep)
                return response.json()

            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", "10"))
                print(f"Rate limit: sleeping {retry_after} sec")
                time.sleep(retry_after)
                continue

            if response.status_code in (500, 502, 503, 504):
                wait = attempt * 5
                print(f"Temporary Riot error {response.status_code}: retry in {wait} sec")
                time.sleep(wait)
                continue

            if response.status_code in (401, 403):
                raise RiotApiError("API key is invalid or expired.")

            raise RiotApiError(
                f"Unexpected Riot API response {response.status_code}: {response.text[:300]}"
            )

        raise RiotApiError(f"Request failed after {self.max_retries} attempts: {url}")


def get_api_key() -> str:
    # For the notebook workflow we usually paste a fresh development key.
    # If RIOT_API_KEY exists in the environment, the script can run without manual input.
    api_key = os.environ.get("RIOT_API_KEY", "").strip()
    if not api_key:
        api_key = getpass("Paste fresh RIOT_API_KEY: ").strip()
    if not api_key:
        raise RiotApiError("RIOT_API_KEY is empty.")
    return api_key


def league_url(tier: str) -> str:
    endpoints = {
        "challenger": "challengerleagues",
        "grandmaster": "grandmasterleagues",
        "master": "masterleagues",
    }
    tier_key = tier.lower()
    if tier_key not in endpoints:
        raise ValueError("tier must be one of: challenger, grandmaster, master")
    return (
        f"https://{REGION}.api.riotgames.com/lol/league/v4/"
        f"{endpoints[tier_key]}/by-queue/{QUEUE}"
    )


def load_csv(path: Path) -> pd.DataFrame:
    if path.exists():
        return pd.read_csv(path)
    return pd.DataFrame()


def save_csv(df: pd.DataFrame, path: Path) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8")


def fetch_league_players(
    client: RiotClient,
    tier: str,
    max_players: int,
    player_offset: int = 0,
) -> pd.DataFrame:
    # player_offset lets us continue collection from the next slice of league players.
    # Without it, repeated runs would keep requesting the same top players and mostly find duplicates.
    league = client.get(league_url(tier))
    entries = league.get("entries", [])
    selected_entries = entries[player_offset : player_offset + max_players]

    rows = []
    for entry in selected_entries:
        row = {
            "source_tier": tier.lower(),
            "queue_type": QUEUE,
            "league_id": league.get("leagueId"),
            "league_name": league.get("name"),
            "summoner_id": entry.get("summonerId"),
            "puuid": entry.get("puuid"),
            "league_points": entry.get("leaguePoints"),
            "rank": entry.get("rank"),
            "wins": entry.get("wins"),
            "losses": entry.get("losses"),
            "veteran": entry.get("veteran"),
            "inactive": entry.get("inactive"),
            "fresh_blood": entry.get("freshBlood"),
            "hot_streak": entry.get("hotStreak"),
            "collected_at_utc": now_utc(),
        }
        rows.append(row)

    players_df = pd.DataFrame(rows)
    return players_df


def enrich_missing_puuids(client: RiotClient, players_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for row in players_df.to_dict("records"):
        if row.get("puuid"):
            rows.append(row)
            continue

        summoner_id = row.get("summoner_id")
        if not summoner_id:
            rows.append(row)
            continue

        url = f"https://{REGION}.api.riotgames.com/lol/summoner/v4/summoners/{summoner_id}"
        summoner = client.get(url)
        row["puuid"] = summoner.get("puuid")
        row["profile_icon_id"] = summoner.get("profileIconId")
        row["summoner_level"] = summoner.get("summonerLevel")
        rows.append(row)

    return pd.DataFrame(rows)


def fetch_match_ids(
    client: RiotClient,
    puuid: str,
    matches_per_player: int,
    start_time: int | None,
    end_time: int | None,
) -> list[str]:
    # Match-V5 works by PUUID. We request ranked solo queue matches only,
    # so the resulting dataset matches the high-tier SoloQ framing of the project.
    url = (
        f"https://{MATCH_REGION}.api.riotgames.com/lol/match/v5/"
        f"matches/by-puuid/{puuid}/ids"
    )
    params: dict[str, Any] = {
        "queue": QUEUE_ID,
        "start": 0,
        "count": matches_per_player,
    }
    if start_time is not None:
        params["startTime"] = start_time
    if end_time is not None:
        params["endTime"] = end_time

    return client.get(url, params=params)


def fetch_match_detail(client: RiotClient, match_id: str) -> dict[str, Any]:
    url = f"https://{MATCH_REGION}.api.riotgames.com/lol/match/v5/matches/{match_id}"
    return client.get(url)


def flatten_match(match: dict[str, Any], source_puuid: str, source_tier: str) -> list[dict[str, Any]]:
    # One Riot match response is nested JSON. For analysis we flatten it into
    # participant-level rows: 1 match -> 10 rows, one row per player in the match.
    metadata = match.get("metadata", {})
    info = match.get("info", {})
    participants = info.get("participants", [])

    rows = []
    for participant in participants:
        challenges = participant.get("challenges", {}) or {}
        row = {
            "match_id": metadata.get("matchId"),
            "source_puuid": source_puuid,
            "source_tier": source_tier,
            "game_creation": info.get("gameCreation"),
            "game_start_timestamp": info.get("gameStartTimestamp"),
            "game_end_timestamp": info.get("gameEndTimestamp"),
            "game_duration_sec": info.get("gameDuration"),
            "game_mode": info.get("gameMode"),
            "game_type": info.get("gameType"),
            "game_version": info.get("gameVersion"),
            "map_id": info.get("mapId"),
            "platform_id": info.get("platformId"),
            "queue_id": info.get("queueId"),
            "participant_id": participant.get("participantId"),
            "puuid": participant.get("puuid"),
            "summoner_id": participant.get("summonerId"),
            "summoner_name": participant.get("summonerName"),
            "riot_id_game_name": participant.get("riotIdGameName"),
            "riot_id_tagline": participant.get("riotIdTagline"),
            "summoner_level": participant.get("summonerLevel"),
            "champion_id": participant.get("championId"),
            "champion_name": participant.get("championName"),
            "team_id": participant.get("teamId"),
            "win": participant.get("win"),
            "team_position": participant.get("teamPosition"),
            "individual_position": participant.get("individualPosition"),
            "lane": participant.get("lane"),
            "role": participant.get("role"),
            "kills": participant.get("kills"),
            "deaths": participant.get("deaths"),
            "assists": participant.get("assists"),
            "gold_earned": participant.get("goldEarned"),
            "gold_spent": participant.get("goldSpent"),
            "total_damage_dealt_to_champions": participant.get("totalDamageDealtToChampions"),
            "total_damage_taken": participant.get("totalDamageTaken"),
            "damage_self_mitigated": participant.get("damageSelfMitigated"),
            "total_minions_killed": participant.get("totalMinionsKilled"),
            "neutral_minions_killed": participant.get("neutralMinionsKilled"),
            "vision_score": participant.get("visionScore"),
            "wards_placed": participant.get("wardsPlaced"),
            "wards_killed": participant.get("wardsKilled"),
            "detector_wards_placed": participant.get("detectorWardsPlaced"),
            "dragon_kills": participant.get("dragonKills"),
            "baron_kills": participant.get("baronKills"),
            "turret_kills": participant.get("turretKills"),
            "double_kills": participant.get("doubleKills"),
            "triple_kills": participant.get("tripleKills"),
            "quadra_kills": participant.get("quadraKills"),
            "penta_kills": participant.get("pentaKills"),
            "kda_challenge": challenges.get("kda"),
            "kill_participation": challenges.get("killParticipation"),
            "item0": participant.get("item0"),
            "item1": participant.get("item1"),
            "item2": participant.get("item2"),
            "item3": participant.get("item3"),
            "item4": participant.get("item4"),
            "item5": participant.get("item5"),
            "item6": participant.get("item6"),
            "collected_at_utc": now_utc(),
        }
        rows.append(row)

    return rows


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def unix_time(value: str | None) -> int | None:
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def append_unique(existing: pd.DataFrame, new_rows: pd.DataFrame, subset: list[str]) -> pd.DataFrame:
    # Incremental runs append new rows but keep only one copy of each logical entity.
    # For matches the uniqueness key is match_id + participant_id.
    if existing.empty:
        return new_rows.drop_duplicates(subset=subset)
    combined = pd.concat([existing, new_rows], ignore_index=True)
    return combined.drop_duplicates(subset=subset, keep="last")


def save_parquet_if_available(df: pd.DataFrame, path: Path) -> None:
    # Parquet is a useful bonus format for DuckDB/analytics, but CSV remains enough
    # for the project if pyarrow is not installed in the current environment.
    try:
        df.to_parquet(path, index=False)
    except Exception as exc:
        print(f"Parquet skipped for {path.name}: {exc}")


def run(args: argparse.Namespace) -> None:
    DATA_DIR.mkdir(exist_ok=True)

    client = RiotClient(
        api_key=get_api_key(),
        request_sleep=args.request_sleep,
        max_retries=args.max_retries,
    )

    print("Checking Riot API key...")
    client.get(league_url(args.tier))
    print("API key works.")

    print(f"Loading {args.tier} players from offset {args.player_offset}...")
    players_new = fetch_league_players(
        client=client,
        tier=args.tier,
        max_players=args.max_players,
        player_offset=args.player_offset,
    )
    players_new = enrich_missing_puuids(client, players_new)

    players_existing = load_csv(PLAYERS_PATH)
    players_all = append_unique(players_existing, players_new, ["puuid"])
    save_csv(players_all, PLAYERS_PATH)
    save_parquet_if_available(players_all, DATA_DIR / "players_api.parquet")

    matches_existing = load_csv(MATCHES_PATH)
    log_existing = load_csv(LOG_PATH)

    downloaded_match_ids = set()
    if not log_existing.empty and "status" in log_existing.columns:
        # The log is our deduplication layer. If a match was already downloaded successfully,
        # the collector skips it on future runs instead of calling Riot API again.
        downloaded_match_ids = set(
            log_existing.loc[log_existing["status"].eq("success"), "match_id"].dropna()
        )

    match_rows_buffer: list[dict[str, Any]] = []
    log_rows: list[dict[str, Any]] = []

    start_time = unix_time(args.start_date)
    end_time = unix_time(args.end_date)

    players_for_run = players_new.dropna(subset=["puuid"]).head(args.max_players)
    print(f"Players in this run: {len(players_for_run)}")

    for player in players_for_run.to_dict("records"):
        puuid = player["puuid"]
        print(f"Fetching match ids for player {puuid[:8]}...")
        try:
            match_ids = fetch_match_ids(
                client=client,
                puuid=puuid,
                matches_per_player=args.matches_per_player,
                start_time=start_time,
                end_time=end_time,
            )
        except Exception as exc:
            log_rows.append(
                {
                    "match_id": None,
                    "source_puuid": puuid,
                    "source_tier": args.tier,
                    "status": "match_ids_error",
                    "error": str(exc),
                    "collected_at_utc": now_utc(),
                }
            )
            continue

        for match_id in match_ids:
            if match_id in downloaded_match_ids:
                # Same match can be found through several top players.
                # Skipping it here keeps the dataset clean and saves API quota.
                continue

            print(f"Downloading match {match_id}...")
            try:
                match = fetch_match_detail(client, match_id)
                match_rows_buffer.extend(flatten_match(match, puuid, args.tier))
                log_rows.append(
                    {
                        "match_id": match_id,
                        "source_puuid": puuid,
                        "source_tier": args.tier,
                        "status": "success",
                        "error": None,
                        "collected_at_utc": now_utc(),
                    }
                )
                downloaded_match_ids.add(match_id)
            except Exception as exc:
                log_rows.append(
                    {
                        "match_id": match_id,
                        "source_puuid": puuid,
                        "source_tier": args.tier,
                        "status": "match_detail_error",
                        "error": str(exc),
                        "collected_at_utc": now_utc(),
                    }
                )

            if len(match_rows_buffer) >= args.save_every_matches * 10:
                # Save periodically, not only at the end, so a long run still leaves
                # useful partial results if the API key expires or the notebook stops.
                matches_existing = flush_matches(matches_existing, match_rows_buffer)
                match_rows_buffer = []
                log_existing = flush_log(log_existing, log_rows)
                log_rows = []

    matches_existing = flush_matches(matches_existing, match_rows_buffer)
    log_existing = flush_log(log_existing, log_rows)

    print("Done.")
    print(f"Players saved: {len(players_all)} -> {PLAYERS_PATH}")
    print(f"Participant rows saved: {len(matches_existing)} -> {MATCHES_PATH}")
    print(f"Log rows saved: {len(log_existing)} -> {LOG_PATH}")


def flush_matches(existing: pd.DataFrame, rows: list[dict[str, Any]]) -> pd.DataFrame:
    # One downloaded match creates 10 participant rows. The unique key protects
    # against duplicated match downloads across repeated collector runs.
    if not rows:
        return existing
    new_df = pd.DataFrame(rows)
    combined = append_unique(existing, new_df, ["match_id", "participant_id"])
    save_csv(combined, MATCHES_PATH)
    save_parquet_if_available(combined, DATA_DIR / "matches_api.parquet")
    return combined


def flush_log(existing: pd.DataFrame, rows: list[dict[str, Any]]) -> pd.DataFrame:
    # The log is intentionally append-only: it records both successful downloads
    # and errors, which helps explain what happened during API collection.
    if not rows:
        return existing
    new_df = pd.DataFrame(rows)
    combined = pd.concat([existing, new_df], ignore_index=True) if not existing.empty else new_df
    save_csv(combined, LOG_PATH)
    save_parquet_if_available(combined, DATA_DIR / "download_log_api.parquet")
    return combined


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Incremental Riot API collector.")
    parser.add_argument("--tier", default="challenger", choices=["challenger", "grandmaster", "master"])
    parser.add_argument("--player-offset", type=int, default=0)
    parser.add_argument("--max-players", type=int, default=10)
    parser.add_argument("--matches-per-player", type=int, default=5)
    parser.add_argument("--start-date", default=None, help="UTC date, e.g. 2026-05-01 or 2026-05-01T00:00:00+00:00")
    parser.add_argument("--end-date", default=None, help="UTC date, e.g. 2026-06-01 or 2026-06-01T00:00:00+00:00")
    parser.add_argument("--request-sleep", type=float, default=1.2)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--save-every-matches", type=int, default=5)
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
