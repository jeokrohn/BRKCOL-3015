import os
from os.path import abspath, join, dirname, isfile
from typing import Optional

from flask import Flask
from wxc_sdk import WebexSimpleApi
from wxc_sdk.integration import Integration
from wxc_sdk.tokens import Tokens
from yaml import safe_load, safe_dump

__all__ = ['AppWithTokens']


class AppWithTokens(Flask):

    """
    A child class of a Flask app with a WebexSimpleApi instance using service app tokens.
    Requires that service app credentials are set in these environment variables:
        * SERVICE_APP_REFRESH_TOKEN
        * SERVICE_APP_CLIENT_ID
        * SERVICE_APP_CLIENT_SECRET
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tokens = self.get_tokens()
        self.api = WebexSimpleApi(tokens=self.tokens)

    @staticmethod
    def yml_path() -> str:
        path = abspath(join(dirname(__file__), '../..', 'app_tokens.yml'))
        return path

    def read_tokens_from_file(self) -> Optional[Tokens]:
        path = self.yml_path()
        if not isfile(path):
            return None
        try:
            with open(path, mode='r') as f:
                data = safe_load(f)
            tokens = Tokens.parse_obj(data)
        except Exception:
            return None
        return tokens

    def write_tokens_to_file(self, tokens: Tokens):
        with open(self.yml_path(), mode='w') as f:
            safe_dump(tokens.dict(exclude_none=True), f)

    def get_access_token(self) -> Tokens:
        tokens = Tokens(refresh_token=os.getenv('SERVICE_APP_REFRESH_TOKEN'))
        integration = Integration(client_id=os.getenv('SERVICE_APP_CLIENT_ID'),
                                  client_secret=os.getenv('SERVICE_APP_CLIENT_SECRET'),
                                  scopes=[], redirect_url=None)
        integration.refresh(tokens=tokens)
        self.write_tokens_to_file(tokens)
        return tokens

    def get_tokens(self) -> Optional[Tokens]:
        """
        Get tokens
        """
        # try to read from file
        tokens = self.read_tokens_from_file()
        # .. or create new access token using refresh token
        if tokens is None:
            tokens = self.get_access_token()
        # get a new access token if remaining lifetime is less than a day
        if tokens.remaining < 24 * 60 * 60:
            tokens = self.get_access_token()
        return tokens
