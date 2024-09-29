#!/usr/bin/env python
import requests
import random
import sys
import textwrap
import time
import json
import pathlib
from typing import Self
import string
import os

season_order = {
    "WINTER": 0,
    "SPRING": 1,
    "SUMMER": 2,
    "FALL": 3
}

_debug = (
    "DEBUG" in os.environ
    and os.environ["DEBUG"].lower() not in ["0", "", "false", "off", "no"]
)


def split_array(array, size):
    return [array[i:i + size] for i in range(0, len(array), size)]


def generate_sample(
        data: list,
        filter_: callable = None,
        size: int = 10,
        seed: int | None = None,
        offset: int = 0):
    if seed is not None:
        random.seed(seed)
    debug(
        "Generating sample",
        [
            f'data: {len(data)}',
            f'filter_: {bool(filter_)}',
            f'size: {size}',
            f'seed: {seed}',
            f'offset: {offset}'
        ]
    )
    shuffled = random.sample(data, k=len(data))
    skipped = 0
    sample = []
    for v in shuffled:
        if filter_ is None or filter_(v):
            if skipped >= offset:
                sample.append(v)
                if len(sample) >= size:
                    break
            else:
                skipped += 1
    return sample


class RateLimiter:
    timestamps = []
    window = 60
    count = None
    x_ratelimit_reset = None
    x_ratelimit_remaining = None
    x_ratelimit_limit = None
    x_ratelimit_retry_after = None
    cooldown = 60.01
    data_file_path = None

    def __init__(
            self,
            window_seconds: float = 60,
            count: float = None,
            cooldown: float = None):
        self.window = window_seconds
        self.count = count
        self.cooldown = cooldown

    def update_timestamps(self):
        t0 = time.time() - self.window
        self.timestamps = [t for t in self.timestamps if t > t0]

    def x_update(self, response):
        headers = response.headers
        if 'X-RateLimit-Reset' in headers:
            self.x_ratelimit_reset = int(headers['X-RateLimit-Reset'])
        if 'Retry-After' in headers:
            self.x_ratelimit_retry_after = int(headers['Retry-After'])
        if 'X-RateLimit-Remaining' in headers:
            self.x_ratelimit_remaining = int(headers['X-RateLimit-Remaining'])
        if 'X-RateLimit-Limit' in headers:
            self.x_ratelimit_limit = int(headers['X-RateLimit-Limit'])
        window_requests = len(self.timestamps)
        debug(
            'Ratelimits updated',
            [
                f'limit: {self.x_ratelimit_limit}',
                f'remaining: {self.x_ratelimit_remaining}',
                f'reset: {self.x_ratelimit_reset}',
                f'retry after: {self.x_ratelimit_retry_after}',
                f'window: {self.x_ratelimit_retry_after}',
                f'window requests: {window_requests}'
            ]
        )

    def window_limit(self):
        self.update_timestamps()
        if self.count is None:
            return
        while len(self.timestamps) >= self.count:
            self.update_timestamps()
            time.sleep(0.1)
        self.timestamps += [time.time()]

    def reset(self):
        self.x_ratelimit_limit = None
        self.x_ratelimit_remaining = None
        self.x_ratelimit_reset = None
        self.x_ratelimit_retry_after = None

    def limit(self):
        self.window_limit()
        if self.x_ratelimit_retry_after is not None:
            debug(
                'Waiting for rate limit:',
                f'retry_after: {self.x_ratelimit_retry_after}'
            )
            time.sleep(self.x_ratelimit_retry_after + 0.1)
            self.reset()
        elif self.x_ratelimit_reset is not None:
            debug(
                'Waiting for rate limit:',
                [
                    f'now: {time.time()}',
                    f'reset: {self.x_ratelimit_reset}'
                ]
            )
            time.sleep(self.x_ratelimit_reset - time.time() + 0.1)
            self.reset()
        if self.x_ratelimit_remaining is None:
            return
        if self.x_ratelimit_remaining >= 1:
            return
        else:
            debug(
                'Waiting for rate limit:',
                f'cooldown: {self.cooldown}'
            )
            time.sleep(self.cooldown)
        self.reset()


def fatal(msg, extra: list[str] | str | None = None):
    raise Exception(info_str(msg, extra))


def info_str(msg: str, extra: list[str] | str | None = None):
    if isinstance(extra, list):
        extra_lines = [
            line for string in extra
            for line in str(string).split('\n')
        ]
    elif extra:
        extra_lines = [
            *(str(extra).split('\n'))
        ]
    else:
        lines = [msg]
        extra_lines = []
    extra_lines = [
        line for string in extra_lines
        for line in textwrap.wrap(
            string,
            break_on_hyphens=False,
            width=120
        )
    ]
    lines = [msg, *extra_lines]
    return '\n    '.join(lines)


def info(msg, extra: list[str] | str | None = None):
    print(info_str(msg, extra), file=sys.stderr)


def info_long_list(msg: str, data: list[str]):
    if len(data) <= 16:
        info(msg, data)
    else:
        rows = split_array([f'{t:16.16}' for t in data], 4)
        info(msg, [' '.join(r) for r in rows])


def columnize(
        data: list[str],
        col_n: int = 4,
        col_width: int = 16) -> str:
    padded = [f'{t:{col_width}.{col_width}}' for t in data]
    rows = split_array(padded, col_n)
    return '\n'.join([' '.join(r) for r in rows])


def warning(msg, extra: list[str] | str | None = None):
    print(info_str(msg, extra), file=sys.stderr)


def debug(msg, extra: list[str] | str | None = None):
    if not _debug:
        return
    print(info_str(msg, extra), file=sys.stderr)


class API:

    url = None
    access_token = None
    ratelimiter = None

    def __init__(
            self,
            url: str | None = 'https://graphql.anilist.co',
            access_token: str | None = None):
        self.url = url or self.url
        self.access_token = access_token
        self.ratelimiter = RateLimiter()

    def retry_request(
            self,
            url: str,
            json: dict = None,
            headers: dict = None,
            count: int = 10):
        for i in range(0, count):
            self.ratelimiter.limit()
            response = requests.post(url, json=json, headers=headers)
            self.ratelimiter.x_update(response)
            data = response.json()
            status = response.status_code
            if status == 200:
                if 'errors' in data:
                    fatal(
                        "Error executing query:",
                        f"error: {data['errors'][0]['message']}"
                    )
                return data
            if status == 429:
                info("Ratelimit reached. Retrying.")
                continue
            warning(
                "Request failed:",
                [
                    f"status: {status}",
                    f"text: {response.text}"
                ]
            )
        fatal(
            "Request failed:",
            [
                f"status: {status}",
                f"text: {response.text}"
            ]
        )

    def do_query(
            self,
            query: str,
            variables: dict = {},
            access_token: str | None = None) -> dict:
        json = {'query': query, 'variables': variables}
        access_token = access_token or self.access_token
        if access_token:
            headers = {'Authorization': f'Bearer {access_token}'}
        else:
            headers = None
        return self.retry_request(self.url, json, headers, count=10)


class Commands(object):
    """
    AniList AMQ Tool.

    Check the `README.md` for instructions
    """

    _media = None
    _api = None
    _media_sets = None

    def __init__(
            self,
            data_file: str | None = 'media.json',
            access_token: str | None = None,
            no_data: bool = False):
        self._media_sets = {}
        if data_file is not None:
            self._data_file_path = pathlib.Path(data_file)
        if self._data_file_path and self._data_file_path.exists():
            self._load_data(self._data_file_path)
        elif not no_data:
            fatal(
                "Anime data not found.",
                [
                    f"Call the `update_data` command to generate f{data_file}.",
                    "Or define `--no-data` to continue without the data.",
                    "Continuing without data means you cannot generate"
                    " samples from the 'ALL' set."
                ]
            )
        self._api = API(access_token=access_token)

    def fetch_media(
            self,
            media_ids: list[int] | int) -> list[dict]:
        """
        Return medias corresponding to the given media_ids
        """
        query = '''
        query ($page: Int, $ids: [Int]) {
            Page (page: $page) {
                pageInfo {
                    total
                    currentPage
                    lastPage
                    hasNextPage
                    perPage
                }
                media (id_in: $ids) {
                    type
                    id
                    idMal
                    seasonYear
                    season
                    seasonInt
                    popularity
                    favourites
                    trending
                    tags {
                        id
                        name
                    }
                    genres
                    averageScore
                    meanScore
                    title {
                        native
                        romaji
                        english
                    }
                    mediaListEntry {
                        id
                    }
                    isAdult
                }
            }
        }
        '''
        debug('Fetching media:', media_ids)
        if isinstance(media_ids, int):
            media_ids = [media_ids]
        media = []
        for i in range(1, 1000):
            data = self._api.do_query(
                query,
                variables={
                    "page": i,
                    "ids": media_ids,
                }
            )
            media += [m for m in data['data']['Page']['media']]
            if not data['data']['Page']['pageInfo']['hasNextPage']:
                break
        info_long_list(
            'Fetched media',
            sorted(
                [m['title']['romaji'] for m in media],
                key=lambda v: v.lower()
            )
        )
        return media

    def fetch_current_user(self):
        """
        Return the currently authenticated username
        """
        query = '''
        query {
            Viewer {
                name
            }
        }
        '''
        return self._api.do_query(query)["data"]["Viewer"]["name"]

    def fetch_user_media(
            self,
            media_set_name: str,
            username: str | None = None) -> Self:
        query = '''
        query ($username: String, $page: Int) {
            Page (page: $page) {
                pageInfo {
                    total
                    currentPage
                    lastPage
                    hasNextPage
                    perPage
                }
                mediaList (userName: $username) {
                    id
                    mediaId
                    media {
                        id
                        title {
                            romaji
                        }
                    }
                }
            }
        }
        '''
        if username is None:
            username = self.fetch_current_user()
        info('Fetching user media:', username)
        media_list = []
        for i in range(1, 1000):
            data = self._api.do_query(
                query,
                variables={
                    "username": username,
                    "page": i
                }
            )
            media_list += [m for m in data['data']['Page']['mediaList']]
            if not data['data']['Page']['pageInfo']['hasNextPage']:
                break
        media = self.fetch_media([m["mediaId"] for m in media_list])
        info_long_list(
            'Fetched user media',
            sorted(
                [m['title']['romaji'] for m in media],
                key=lambda v: v.lower()
            )
        )
        self._save_media(media_set_name, media)
        return self

    def _fetch_all_animes(self) -> list[dict]:
        query = '''
        query ($page: Int) {
            Page (page: $page) {
                pageInfo {
                    total
                    currentPage
                    lastPage
                    hasNextPage
                    perPage
                }
                media (type: ANIME) {
                    type
                    id
                    idMal
                    seasonYear
                    season
                    seasonInt
                    popularity
                    favourites
                    trending
                    hashtag
                    synonyms
                    tags {
                        id
                        name
                    }
                    coverImage {
                        extraLarge
                    }
                    genres
                    averageScore
                    meanScore
                    title {
                        native
                        romaji
                        english
                    }
                    isAdult
                    relations {
                        edges {
                            relationType
                            node {
                                id
                            }
                        }
                    }
                }
            }
        }
        '''
        info('Fetching all animes')
        medias = []
        i = 0
        hasNextPage = True
        lastPage = '?'
        while hasNextPage:
            i += 1
            info('Fetching animes:', f'{i}/{lastPage}')
            data = self._api.do_query(
                query,
                variables={
                    "page": i
                }
            )
            pageInfo = data['data']['Page']['pageInfo']
            hasNextPage = pageInfo["hasNextPage"]
            lastPage = pageInfo['lastPage']
            medias += data['data']['Page']['media']
        return medias

    def _add_media(self, media_id: int, status: str):
        mutation = '''
        mutation ($mediaId: Int, $status: MediaListStatus) {
            SaveMediaListEntry (mediaId: $mediaId, status: $status) {
                media {
                    title {
                        romaji
                    }
                }
                status
            }
        }
        '''
        data = self._api.do_query(
            mutation,
            {
                'mediaId': media_id,
                'status': status
            }
        )
        return data['data']['SaveMediaListEntry']

    def _delete_media(self, media_list_id: int):
        mutation = '''
        mutation ($mediaListId: Int) {
            DeleteMediaListEntry (id: $mediaListId) {
                deleted
            }
        }
        '''
        data = self._api.do_query(
            mutation,
            {
                'mediaListId': media_list_id
            }
        )
        return data['data']['DeleteMediaListEntry']['deleted']

    def add_media(
            self,
            media_ids: list[int] | int = [],
            status: str = "PLANNING"):
        """
        Add the listed media_ids to the currently authenticated user's list
        """
        if isinstance(media_ids, int):
            media_ids = [media_ids]
        added = []
        for i in media_ids:
            m = self._add_media(
                i,
                status=status
            )
            added += [{
                'media_title': m['media']['title']['romaji'],
                'status': m['status']
            }]
        info(
            'Added entries:',
            [
                f'{u["media_title"]}: {u["status"]}'
                for u in sorted(added, key=lambda u: u['media_title'].lower())
            ]
        )
        return self

    def _update_status(
            self,
            media_list_ids: list[int] | int = [],
            status: str = "PLANNING"):
        if isinstance(media_list_ids, int):
            media_list_ids = [media_list_ids]
        mutation = '''
        mutation ($mediaListIds: [Int], $status: MediaListStatus) {
            UpdateMediaListEntries (ids: $mediaListIds, status: $status) {
                media {
                    title {
                        romaji
                    }
                }
                status
            }
        }
        '''
        data = self._api.do_query(
            mutation,
            {
                'mediaListIds': media_list_ids,
                'status': status
            }
        )
        updates = [
            {
                'media_title': m['media']['title']['romaji'],
                'status': m['status']
            } for m in data['data']['UpdateMediaListEntries']
        ]
        info(
            'Updated entries:',
            [
                f'{u["media_title"]}: {u["status"]}'
                for u in sorted(
                    updates,
                    key=lambda u: u['media_title'].lower()
                )
            ]
        )

    def _save_media(self, name: str, media: list[dict]):
        if name in self._media_sets:
            fatal("Media set already exists:", name)
        self._media_sets[name] = media

    def _load_media(self, name: str):
        if name not in self._media_sets:
            fatal("No media set with name", name)
        return self._media_sets[name]

    def _tmp_name(self):
        return ''.join(
            random.choices(
                string.ascii_letters + string.digits,
                k=16
            )
        )

    def create_media_set(
            self,
            name: str,
            media: list[int] | list[dict] | int | dict = []):
        """
        Create a named set of media

        Args:
        name: Name for the `media set`
        media: List of media ids or objects
        """
        if isinstance(media, int) or isinstance(media, dict):
            media = [media]
        media_ids = (
            media if isinstance(media[0], int)
            else [m["id"] for m in media]
        )
        media = self.fetch_media(media_ids)
        self._save_media(name, media)
        return self

    def update_or_add_media(
            self,
            media_set_name: str,
            status: str = "PLANNING"):
        """
        Add media, or update media list status

        Args:
        media_set_name: Name of the `media set`. E.g. generated using the
                        `create_media_sample` command
        status: PLANNING | WATCHING | COMPLETED | DROPPED
        """
        media = self._load_media(media_set_name)
        media_ids = [m["id"] for m in media]
        media_set_name = self._tmp_name()
        # Re-fetch media, because the loaded set may not have up-to-date
        # information about the user's MediaList'
        media = self.fetch_media(media_ids)
        update_media = [
            m for m in media
            if m['mediaListEntry'] is not None
        ]
        update_media_list_ids = [
            m["mediaListEntry"]["id"]
            for m in update_media
        ]
        add_media = [
            m for m in media
            if m['mediaListEntry'] is None
        ]
        add_media_ids = [
            m["id"] for m in add_media
        ]
        if update_media_list_ids:
            self._update_status(
                update_media_list_ids,
                status=status
            )
        if add_media_ids:
            self.add_media(
                add_media_ids,
                status=status
            )
        info(
            "Updated media list status:",
            [m["title"]["romaji"] for m in update_media]
        )
        info(
            "Added new media to list",
            [m["title"]["romaji"] for m in add_media]
        )
        return self

    def delete_media(
            self,
            media_set_name: str,
            status: str = "PLANNING"):
        """
        Delete media from the authenticated user's list

        Args:
        media_set_name: Name of the `media set`. E.g. fetched with `fetch_user_media`
        """
        mutation = '''
        mutation ($mediaId: Int, $status: MediaListStatus) {
            DeleteMediaListEntry (mediaId: $mediaId, status: $status) {
                media {
                    title {
                        romaji
                    }
                }
                status
            }
        }
        '''
        media = self._load_media(media_set_name)
        results = {
            m["title"]["romaji"]: self._delete_media(m["mediaListEntry"]["id"])
            for m in media
        }
        info(
            "Deleted entries:",
            [f"{k}: {v}" for k, v in results.items()]
        )
        return self

    def delete_list(self):
        """
        Remove everything from the currently authenticated user's list
        """
        media_set_name = self._tmp_name()
        self.fetch_user_media(media_set_name)
        self.delete_media(media_set_name)
        return self

    def replace_list(
            self,
            media_set_name: str,
            status: str = 'PLANNING'):
        """
        Replace the currently authenticated user's list with the given
        `media set`
        """
        self.delete_list()
        self.update_or_add_media(media_set_name)
        return self

    def _print_media_json(self, media):
        json.dump(media, sys.stdout, indent=4)

    def _print_media_simple_json(self, media):
        data = [{"id": m["id"], "name": m["title"]["romaji"]} for m in media]
        data = sorted(data, key=lambda m: m["id"])
        json.dump(data, sys.stdout, indent=4)

    def _print_media_titles(self, media):
        titles = [m["title"]["romaji"] for m in media]
        titles = sorted(t for t in titles)
        print('\n'.join(titles))

    def _print_media_columns(self, media, cols_n):
        titles = [m["title"]["romaji"] for m in media]
        titles = sorted(t for t in titles)
        print(columnize(titles, cols_n, 24))

    def print(
            self,
            media_set_name: str,
            simple: bool = False,
            text: bool = False,
            columns: int | bool = False):
        """
        Print contents of a given `media set`

        Args:
        media_set_name: Name of the `media set` to print
        """
        media = self._load_media(media_set_name)
        if columns:
            if columns is True:
                columns = 4
            self._print_media_columns(media, columns)
        elif text:
            self._print_media_titles(media)
        elif simple:
            self._print_media_simple_json(media)
        else:
            self._print_media_json(media)
        return self

    def _normalized_popularity(self, popularity):
        return 100 * popularity / self._max_popularity

    def _load_data(self, file: str = 'media.json'):
        filepath = pathlib.Path(file)
        with open(filepath, "r") as f:
            media = json.load(f)
        self._media = {m['id']: m for m in media}
        popularity_sorted = sorted(media, key=lambda m: m["popularity"])
        n = len(media)
        for i, m in enumerate(popularity_sorted):
            m["popularity_percent"] = 100 * i / n
        self._max_media_id = sorted(
            media,
            key=lambda m: m['id']
        )[-1]['id']
        self._max_popularity = sorted(
            media,
            key=lambda m: m['popularity']
        )[-10]['popularity']
        self._save_media("ALL", media)

    def update_data(self):
        """
        Fetch all anime data from AniList to a file
        """
        media = self._fetch_all_animes()
        with open(self._data_file_path, "w") as f:
            json.dump(media, f)

    def _create_filter(
            self,
            min_year: int | None = None,
            min_season: str | None = None,
            max_year: int | None = None,
            max_season: str | None = None,
            min_popularity: float | None = None,
            max_popularity: float | None = None,
            min_popularity_percent: float | None = None,
            max_popularity_percent: float | None = None,
            genres: list[str] | None = None,
            tags: list[str] | None = None):
        filters = []
        if min_year is not None:
            filters.append(lambda m: m["seasonYear"] >= min_year)
        if max_year is not None:
            filters.append(lambda m: m["seasonYear"] <= max_year)
        if min_season is not None:
            min_season_order = season_order[min_season]
            filters.append(
                lambda m: (
                    ("season" in m)
                    and (m_season_order := (season_order[m["season"]]))
                    and (m_season_order >= min_season_order)
                )
            )
        if max_season is not None:
            max_season_order = season_order[max_season]
            filters.append(
                lambda m: (
                    ("season" in m)
                    and (m_season_order := (season_order[m["season"]]))
                    and (m_season_order >= max_season_order)
                )
            )
        if min_popularity is not None:
            def f_min_popularity(m):
                return m["popularity"] >= min_popularity
            filters.append(f_min_popularity)
        if max_popularity is not None:
            def f_max_popularity(m):
                return m["popularity"] >= max_popularity
            filters.append(f_max_popularity)
        if min_popularity_percent is not None:
            def f_min_popularity_percent(m):
                pp = self._media[m["id"]]["popularity_percent"]
                return pp >= min_popularity_percent
            filters.append(f_min_popularity_percent)
        if max_popularity_percent is not None:
            def f_max_popularity_percent(m):
                pp = self._media[m["id"]]["popularity_percent"]
                return pp <= max_popularity_percent
            filters.append(f_max_popularity_percent)
        if genres is not None:
            genres = [g.lower() for g in genres]

            def f_genres(m):
                return any([(g.lower() in genres) for g in m["genres"]])
            filters.append(f_genres)
        if tags is not None:
            tags = [t.lower() for t in tags]

            def f_tags(m):
                return any([(t["name"].lower() in tags) for t in m["tags"]])
            filters.append(f_tags)

        def filter_(m):
            return m is not None and all([f(m) for f in filters])
        return filter_

    def sample_set(
            self,
            source_media_set: str,
            target_media_set: str,
            size: int = 10,
            offset: int = 0,
            seed: int | None = None,
            min_year: int | None = None,
            min_season: str | None = None,
            max_year: int | None = None,
            max_season: str | None = None,
            min_popularity: float | None = None,
            max_popularity: float | None = None,
            min_popularity_percent: float | None = None,
            max_popularity_percent: float | None = None,
            genres: list[str] | None = None,
            tags: list[str] | None = None):
        """
        Select a random sample from given source `media set` and store it in
        the target `media set`.

        Args:
            size: number of media to select
            offset: offset resulting list by this many
            seed: Set a seed for the rng
            min_year: Filter by the year
            min_season: Filter by the season: WINTER | SPRING | SUMMER | FALL
            max_year: Filter by the year
            max_season: Filter by the season: WINTER | SPRING | SUMMER | FALLs
            min_popularity: Filter by popularity (number of users with media
                            on their list)
            max_popularity: Filter by popularity (number of users with media
                            on their list)
            min_popularity_percent: Select from the top XX% of the most
                                    popular anime
            max_popularity_percent: Select form the bottom XX% of the least
                                    popular anime
            genres: Filter by genre/genres
            tags: Filter by tag/tags
        """
        filter_ = self._create_filter(
            min_year, min_season, max_year, max_season, min_popularity,
            max_popularity, min_popularity_percent, max_popularity_percent,
            genres, tags
        )
        source = self._load_media(source_media_set)
        source = {
            m["id"]: m
            for m in source
        }
        data = [
            source.get(i, None)
            for i in range(0, 1000000)
        ]
        sample = generate_sample(
            data,
            filter_=filter_,
            size=size,
            offset=offset,
            seed=seed
        )
        self._save_media(target_media_set, sample)
        return self

    def popularity_distribution(self):
        pops = [
            self._normalized_popularity(m["popularity"])
            for m in self._media.values()
        ]
        return {i: len([p for p in pops if p >= i]) for i in range(0, 200)}

    def end(self):
        """
        Stop processing
        """
        pass


if __name__ == "__main__":
    import fire
    fire.Fire(Commands)
