#!/usr/bin/env python
"""
Demonstration of how to call a Webex API endpoint using the SDK
"""
import os


from dotenv import load_dotenv
from wxc_sdk import WebexSimpleApi


def main():
    load_dotenv()

    # after reading .env file all variables defined in the file are accessible as environment variables
    access_token = os.getenv('WEBEX_TOKEN')

    with WebexSimpleApi(tokens=access_token) as api:
        locations = list(api.locations.list())
        print(f'{len(locations)} locations found')
        for location in locations:
            print(location)
            print()

        ca_locations = [location for location in locations
                        if location.address.state == 'CA']
        print()
        print(f'{len(ca_locations)} locations in CA')
        print(', '.join(loc.name for loc in ca_locations))


if __name__ == '__main__':
    main()
