"""
Simple helper to work with service app tokens
"""
import logging
import sys
from json import dumps, loads
from os import getenv
from os.path import basename, splitext, isfile
from typing import Optional

from dotenv import load_dotenv
from yaml import safe_load, safe_dump

from wxc_sdk import WebexSimpleApi
from wxc_sdk.integration import Integration
from wxc_sdk.tokens import Tokens

__all__ = ['get_tokens']


def yml_path() -> str:
    """
    Path to an YML file to cache service app refresh and access tokens
    """
    return f'{splitext(basename(__file__))[0]}.yml'


def read_tokens_from_file() -> Optional[Tokens]:
    """
    Read service app tokens from YML file
    :return: tokens or None if reading from file failed for some reason
    """
    path = yml_path()
    if not isfile(path):
        return None
    try:
        with open(path, mode='r') as f:
            data = safe_load(f)
        tokens = Tokens.parse_obj(data)
    except Exception:
        return None
    return tokens


def write_tokens_to_file(tokens: Tokens):
    """
    Write service app tokens to cache (YML file)
    """
    with open(yml_path(), mode='w') as f:
        safe_dump(tokens.dict(exclude_none=True), f)


def get_access_token() -> Tokens:
    """
    Get a new access token using the refresh token
    """
    # required environment variables
    env_vars = ('SERVICE_APP_REFRESH_TOKEN', 'SERVICE_APP_CLIENT_ID', 'SERVICE_APP_CLIENT_SECRET')

    if not all(getenv(s) for s in env_vars):
        raise KeyError(f'Not all required environment variables ({", ".join(env_vars)}) defined.')
    tokens = Tokens(refresh_token=getenv('SERVICE_APP_REFRESH_TOKEN'))
    integration = Integration(client_id=getenv('SERVICE_APP_CLIENT_ID'),
                              client_secret=getenv('SERVICE_APP_CLIENT_SECRET'),
                              scopes=[], redirect_url=None)
    integration.refresh(tokens=tokens)
    # write tokens to cache
    write_tokens_to_file(tokens)
    return tokens


def get_tokens() -> Optional[Tokens]:
    """
    Get tokens from file .. or create a new access token using the refresh toen
    """
    # try to read from file
    tokens = read_tokens_from_file()
    # .. or create new access token using refresh token
    if tokens is None:
        tokens = get_access_token()
    if tokens.remaining < 24 * 60 * 60:
        tokens = get_access_token()
    return tokens


def test_service_app():
    load_dotenv()
    tokens = get_tokens()

    # dump token information
    print(dumps(loads(tokens.json()), indent=2))
    print()
    print('scopes:')
    print('\n'.join(f' * {s}' for s in sorted(tokens.scope.split())))

    # try to list people and call queues using the tokens
    api = WebexSimpleApi(tokens=tokens)
    users = list(api.people.list())
    print(f'{len(users)} users')
    queues = list(api.telephony.callqueue.list())
    print(f'{len(queues)} call queues')


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    test_service_app()
