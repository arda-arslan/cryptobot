import configparser


def load_api_keys():
    """
    Simple function to load api key, api secret key and api passphrase from a
    config.ini file so that these values aren't hardcoded in the source code.

    Returns:
        api_key: string
            32 character string representing the account's api key
        api_secret_key: string
            88 character string representing the account's api secret key
        api_passphrase: string
            11 character string representing the account's api passphrase
    """

    config = configparser.ConfigParser()
    config.read('../config.ini')
    api_key = config['user']['api_key']
    api_secret_key = config['user']['api_secret_key']
    api_passphrase = config['user']['api_passphrase']

    return api_key, api_secret_key, api_passphrase
