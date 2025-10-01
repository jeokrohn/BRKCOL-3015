#!/usr/bin/env python
"""
Demonstration of how to call a Webex API endpoint directly
"""
import os

import requests
from dotenv import load_dotenv


def main():
    # load .env file
    load_dotenv()

    # after reading .env file all variables defined in the file are accessible as environment variables
    access_token = os.getenv('WEBEX_TOKEN')

    url = 'https://webexapis.com/v1/locations'
    with requests.Session() as session:
        headers = {'Authorization': f'Bearer {access_token}'}
        response = session.get(url=url, headers=headers)
        response.raise_for_status()
        data = response.json()
        print(f'{len(data["items"])} locations found')
        for location in data['items']:
            print(location)
            print()

        # look for locations in California
        ca_locations = [location for location in data['items']
                        if location['address']['state'] == 'CA']
        print()
        print(f'{len(ca_locations)} locations in CA')
        print(', '.join(loc['name'] for loc in ca_locations))


if __name__ == '__main__':
    main()
