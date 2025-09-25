# -*- encoding: utf-8 -*-
"""
Copyright (c) 2019 - present AppSeed.us
"""
from flask_migrate import Migrate
from sys import exit
from urllib.parse import urlsplit, urlunsplit
from decouple import config
from apps.config import config_dict
from apps import create_app, db

# WARNING: Don't run with debug turned on in production!
DEBUG = config('DEBUG', default=True, cast=bool)

# The configuration
get_config_mode = 'Debug' if DEBUG else 'Production'

try:
    # Load the configuration using the default values
    app_config = config_dict[get_config_mode.capitalize()]
except KeyError:
    exit('Error: Invalid <config_mode>. Expected values [Debug, Production] ')

app = create_app(app_config)
Migrate(app, db)

if DEBUG:
    app.logger.info('DEBUG       = ' + str(DEBUG))
    app.logger.info('Environment = ' + get_config_mode)

    uri = app_config.SQLALCHEMY_DATABASE_URI
    masked_uri = uri
    try:
        split = urlsplit(uri)
        username = split.username or ''
        password = '***' if split.password else ''
        auth = username
        if username and password:
            auth = f'{username}:{password}'
        elif password and not username:
            auth = password

        host = split.hostname or ''
        port = f':{split.port}' if split.port else ''

        netloc = auth
        if host:
            netloc = f'{netloc + "@" if netloc else ""}{host}{port}'

        masked_uri = urlunsplit((split.scheme, netloc, split.path, split.query, split.fragment))
    except Exception:
        masked_uri = uri

    app.logger.info('DBMS        = ' + masked_uri)

if __name__ == "__main__":
    print("Running Flask app:", app)
    app.run(host='0.0.0.0', port=5001)
