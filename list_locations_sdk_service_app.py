#!/usr/bin/env python
"""
Demonstration of how to call a Webex API endpoint using the SDK with cached service app tokens
"""

from dotenv import load_dotenv
from wxc_sdk import WebexSimpleApi

from service_app import get_tokens


def main():
    load_dotenv()
    tokens = get_tokens()

    with WebexSimpleApi(tokens=tokens) as api:
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
