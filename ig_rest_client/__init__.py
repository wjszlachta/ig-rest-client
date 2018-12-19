# Copyright (c) 2018 Wojciech Szlachta
#
# Licensed under the ISC License. See LICENSE file in the project root for full license information.

import json
import logging
import time
from abc import ABCMeta, abstractmethod
from typing import Tuple, Union
from urllib.parse import urljoin

from requests import request

IG_REST_TRADING_API_LIVE_URL = 'https://api.ig.com/gateway/deal/'
IG_REST_TRADING_API_DEMO_URL = 'https://demo-api.ig.com/gateway/deal/'

_DEFAULT_TIMEOUT_IN_SECONDS = 10.0

log = logging.getLogger()


class AbstractIgRestSession(metaclass=ABCMeta):
    """IG REST trading API session interface."""

    def get(self, endpoint: str, **kwargs) -> dict:
        """HTTP GET operation to API endpoint."""

        return self._request('GET', endpoint, **kwargs)

    def post(self, endpoint: str, **kwargs) -> dict:
        """HTTP POST operation to API endpoint."""

        return self._request('POST', endpoint, **kwargs)

    def put(self, endpoint: str, **kwargs) -> dict:
        """HTTP PUT operation to API endpoint."""

        return self._request('PUT', endpoint, **kwargs)

    def delete(self, endpoint: str, **kwargs) -> dict:
        """HTTP DELETE operation to API endpoint."""

        return self._request('DELETE', endpoint, **kwargs)

    @abstractmethod
    def _request(self, method: str, endpoint: str, params: dict = None, data: dict = None, headers: dict = None) -> dict:
        """HTTP request method of interface implementation."""

    def switch_session_account(self, account_id: str, default_account: bool = False) -> dict:
        result_json = self.put('session', headers={'Version': '1'}, data={'accountId': account_id, 'defaultAccount': default_account})
        self._set_account_id(account_id)
        return result_json

    def session_details(self) -> dict:
        result_json = self.get('session', headers={'Version': '1'})
        if self._get_account_id() != result_json['accountId']:
            raise Exception('incorrect accountId in session details')
        return result_json

    def log_out(self) -> None:
        self.delete('session', headers={'Version': '1'})

    @abstractmethod
    def _get_account_id(self) -> str:
        """Get accountId method of interface implementation."""

    @abstractmethod
    def _set_account_id(self, account_id: str) -> None:
        """Set accountId method of interface implementation."""


class IgRestSessionUsingVersion2LogIn(AbstractIgRestSession):
    """IG REST trading API session implementation using Version 2 POST /session endpoint to log in."""

    def __init__(self, api_key: str, account_id: str, rest_api_username: str, rest_api_password: str, rest_api_url: str = IG_REST_TRADING_API_DEMO_URL,
                 rest_api_timeout: Union[None, float, Tuple[float, float]] = _DEFAULT_TIMEOUT_IN_SECONDS):
        self._api_key = api_key
        self._account_id = account_id
        self._rest_api_username = rest_api_username
        self._rest_api_password = rest_api_password
        self._rest_api_url = rest_api_url
        self._rest_api_timeout = rest_api_timeout

        self._headers = {'Content-Type': 'application/json',
                         'Accept': 'application/json; charset=UTF-8',
                         'X-IG-API-KEY': self._api_key}

        self._authorization_headers = None

    def _get_account_id(self) -> str:
        return self._account_id

    def _set_account_id(self, account_id: str) -> None:
        self._account_id = account_id

    def _request(self, method: str, endpoint: str, params: dict = None, data: dict = None, headers: dict = None) -> dict:
        if not self._authorization_headers:
            self._log_in()

        my_headers = {**self._headers, **self._authorization_headers}
        if headers is not None:
            my_headers.update(headers)

        if data is not None:
            json_data = json.dumps(data)
        else:
            json_data = None
        response = request(method, urljoin(self._rest_api_url, endpoint), params=params, data=json_data, headers=my_headers, timeout=self._rest_api_timeout)

        if response.ok:
            response_headers = response.headers
            for authorization_header in self._authorization_headers.keys():
                if authorization_header in response_headers:
                    self._authorization_headers.update({authorization_header: response_headers[authorization_header]})

            if response.content:
                return response.json()
            else:
                return {}
        else:
            log.error('Request failed')
            log.error('Status code: %s', response.status_code)
            log.error('Response text: %s', response.text)
            raise Exception

    def _log_in(self) -> None:
        response = request('POST', urljoin(self._rest_api_url, 'session'),
                           data=json.dumps({'encryptedPassword': False, 'identifier': self._rest_api_username, 'password': self._rest_api_password}),
                           headers={**self._headers, 'Version': '2'}, timeout=self._rest_api_timeout)
        if response.ok:
            response_json = response.json()
            response_headers = response.headers
        else:
            log.error('Failed to log in')
            log.error('Status code: %s', response.status_code)
            log.error('Response text: %s', response.text)
            raise Exception

        self._authorization_headers = {'CST': response_headers['CST'],
                                       'X-SECURITY-TOKEN': response_headers['X-SECURITY-TOKEN']}

        if self._account_id != response_json['currentAccountId']:
            self.switch_session_account(self._account_id)


class IgRestSessionUsingVersion3LogIn(AbstractIgRestSession):
    """IG REST trading API session implementation using Version 3 POST /session endpoint to log in."""

    def __init__(self, api_key: str, account_id: str, rest_api_username: str, rest_api_password: str, rest_api_url: str = IG_REST_TRADING_API_DEMO_URL,
                 rest_api_timeout: Union[None, float, Tuple[float, float]] = _DEFAULT_TIMEOUT_IN_SECONDS):
        self._api_key = api_key
        self._account_id = account_id
        self._rest_api_username = rest_api_username
        self._rest_api_password = rest_api_password
        self._rest_api_api_url = rest_api_url
        self._rest_api_timeout = rest_api_timeout

        self._headers = {'Content-Type': 'application/json',
                         'Accept': 'application/json; charset=UTF-8',
                         'X-IG-API-KEY': self._api_key}

        self._oauth_token = None
        self._authorization_headers = None
        self._token_expiry_timestamp = None

    def _get_account_id(self) -> str:
        return self._account_id

    def _set_account_id(self, account_id: str) -> None:
        self._account_id = account_id
        self._authorization_headers.update({'IG-ACCOUNT-ID': account_id})

    def _time_when_request_completes(self) -> float:
        time_now = time.monotonic()

        if isinstance(self._rest_api_timeout, float):
            return time_now + self._rest_api_timeout
        elif isinstance(self._rest_api_timeout, int):
            return time_now + float(self._rest_api_timeout)
        else:
            return time_now + _DEFAULT_TIMEOUT_IN_SECONDS

    def _request(self, method: str, endpoint: str, params: dict = None, data: dict = None, headers: dict = None) -> dict:
        if not (self._oauth_token and self._authorization_headers):
            self._log_in()

        if self._time_when_request_completes() > self._token_expiry_timestamp:
            self._refresh_token()

        my_headers = {**self._headers, **self._authorization_headers}
        if headers is not None:
            my_headers.update(headers)

        if data is not None:
            json_data = json.dumps(data)
        else:
            json_data = None
        response = request(method, urljoin(self._rest_api_api_url, endpoint), params=params, data=json_data, headers=my_headers, timeout=self._rest_api_timeout)

        if response.ok:
            if response.content:
                return response.json()
            else:
                return {}
        else:
            log.error('Request failed')
            log.error('Status code: %s', response.status_code)
            log.error('Response text: %s', response.text)
            raise Exception

    def _log_in(self) -> None:
        response = request('POST', urljoin(self._rest_api_api_url, 'session'),
                           data=json.dumps({'identifier': self._rest_api_username, 'password': self._rest_api_password}),
                           headers={**self._headers, 'Version': '3'}, timeout=self._rest_api_timeout)
        if response.ok:
            response_json = response.json()
        else:
            log.error('Failed to log in')
            log.error('Status code: %s', response.status_code)
            log.error('Response text: %s', response.text)
            raise Exception

        self._oauth_token = response_json['oauthToken']
        self._authorization_headers = {'IG-ACCOUNT-ID': response_json['accountId'],
                                       'Authorization': 'Bearer ' + self._oauth_token['access_token']}
        self._token_expiry_timestamp = time.monotonic() + float(self._oauth_token['expires_in'])

        if self._account_id != response_json['accountId']:
            self.switch_session_account(self._account_id)

    def _refresh_token(self) -> None:
        response = request('POST', urljoin(self._rest_api_api_url, 'session/refresh-token'),
                           data=json.dumps({'refresh_token': self._oauth_token['refresh_token']}), headers={**self._headers, 'Version': '1'},
                           timeout=self._rest_api_timeout)
        if response.ok:
            response_json = response.json()
        else:
            log.error('Failed to refresh token')
            log.error('Status code: %s', response.status_code)
            log.error('Response text: %s', response.text)
            # we assume that both access_token and refresh_token might have expired, so we attempt to log in again
            self._log_in()
            return

        self._oauth_token = response_json
        self._authorization_headers.update({'Authorization': 'Bearer ' + self._oauth_token['access_token']})
        self._token_expiry_timestamp = time.monotonic() + float(self._oauth_token['expires_in'])


# we are currently using IgRestSessionUsingVersion2LogIn - when using OAuth in IgRestSessionUsingVersion3LogIn we get HTTP 500 server error when switching
# session account using PUT /session endpoint (bug report submitted)
IgRestSession = IgRestSessionUsingVersion2LogIn
