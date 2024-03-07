#!/usr/bin/env python
import requests
import random
import sys
import textwrap


def fetch_user_media_list(username: str) -> list[dict]:
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
    info('Fetching user media list:', username)
    media_list = []
    for i in range(1, 1000):
        data = do_query(
            query,
            variables = {
                "username": username,
                "page": i
            }
        )
        media_list += [m for m in data['data']['Page']['mediaList']]
        if not data['data']['Page']['pageInfo']['hasNextPage']:
            break
    info('Animes:', [m['media']['title']['romaji'] for m in media_list])
    return media_list


def do_query(query: str, variables: dict = {}, access_token: str | None = None) -> dict:
    url = 'https://graphql.anilist.co'
    if access_token:
        auth_header = {'Authorization': f'Bearer {access_token}'}
        response = requests.post(
            url,
            json={'query': query, 'variables': variables},
            headers=auth_header
        )
    else:
        response = requests.post(
            url,
            json={'query': query, 'variables': variables}
        )
    data = response.json()
    if 'errors' in data:
        fatal("Error executing query:", data['errors'][0]['message'])
    return data


def fatal(msg, extra: list[str] | str | None = None):
    raise Exception(info_str(msg, extra))


def info_str(msg: str, extra: list[str] | str | None = None):
    if isinstance(extra, list):
        extra_lines = [
            line for string in extra
                for line in string.split('\n')
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
                width=100)
    ]
    lines = [ msg, *extra_lines ]
    return '\n    '.join(lines)


def info(msg, extra: list[str] | str | None = None):
    print(info_str(msg, extra), file=sys.stderr)


def add_media(media_id: int, status: str, access_token: str):
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
    data = do_query(
        mutation,
        {
            'mediaId': media_id,
            'status': status
        },
        access_token=access_token
    )
    return data['data']['SaveMediaListEntry']


def add_multiple_media(
        media_ids: list[int] = [],
        status: str = "PLANNING",
        access_token: str | None = None):
    added = []
    for i in media_ids:
        m = add_media(
            i,
            status=status,
            access_token=access_token
        )
        added += [{
            'media_title': m['media']['title']['romaji'],
            'status': m['status']
        }]
    info(
        'Added entries:',
        [ f'{u["media_title"]}: {u["status"]}' for u in sorted(added, key=lambda u: u['media_title'].lower())]
    )


def update_status(media_list_ids: list[int] = [], status: str = "PLANNING", access_token: str | None = None):
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
    data = do_query(
        mutation,
        {
            'mediaListIds': media_list_ids,
            'status': status
        },
        access_token=access_token
    )
    updates = [
        {
            'media_title': m['media']['title']['romaji'],
            'status': m['status']
        } for m in data['data']['UpdateMediaListEntries']
    ]
    info(
        'Updated entries:',
        [ f'{u["media_title"]}: {u["status"]}' for u in sorted(updates, key=lambda u: u['media_title'].lower())]
    )


def update_or_add_medias(
        user_media_list: list = [],
        media_ids: list[int] = [],
        status: str = "PLANNING",
        access_token: str | None = None):
    media_id_to_media_list_id = {m['mediaId']: m['id'] for m in user_media_list}
    update_media_list_ids = []
    add_media_ids = []
    for i in media_ids:
        if i in media_id_to_media_list_id:
            update_media_list_ids += [media_id_to_media_list_id[i]]
        else:
            add_media_ids += [i]
    if update_media_list_ids:
        update_status(update_media_list_ids, status = status, access_token=access_token)
    if add_media_ids:
        add_multiple_media(add_media_ids, status = status, access_token=access_token)


def generate_training_list(
        user: str = None,
        source_users: list[str] = [],
        number_of_animes: int = 10,
        token: str = 'token'):
    """
    Edit anilist statuses for amq

    Note: THIS SCRIPT WILL CHANGE YOUR LIST STATUSES

    Prerequisiters:
    * AniList `user` that is used in amq.
    * One or more AniList `source_users` from whose lists to select animes from

    This script:
    1) Sets whole list for given `user` as "PLANNING"
    2) Sets/adds a random subset of the `source_users` lists to `user` list as "COMPLETED" 

    Args:
        user: username whose list to edit
        source_users: list of users from whose list to adde entries from
        number_of_animes: number of animes to set as "PLANNING"
        token: access token for the API. Check the AniList. Generate one using the implicit auth flow: https://anilist.gitbook.io/anilist-apiv2-docs/overview/oauth/implicit-grant
    """
    if not user: fatal('Username missing')
    if not token: fatal('Access token missing')
    if isinstance(source_users, str):
        source_users = [source_users]
    info(f'Access token:', token)
    media_list = fetch_user_media_list(user)
    media_list_ids = [m['id'] for m in media_list]
    source_media_list = [
        media_list_id for u in source_users
            for media_list_id in fetch_user_media_list(u)
    ]
    source_media_ids = [
        m['mediaId'] for m in source_media_list
    ]
    update_status(media_list_ids, "PLANNING", access_token=token)
    training_set = random.sample(
        source_media_ids,
        min(number_of_animes, len(source_media_ids))
    )
    update_or_add_medias(
        media_list,
        training_set,
        status="COMPLETED",
        access_token=token
    )


if __name__ == "__main__":
    import fire
    fire.Fire(generate_training_list)

