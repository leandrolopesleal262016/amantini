# -*- encoding: utf-8 -*-
"""
Copyright (c) 2019 - present AppSeed.us
"""

import os
from urllib.parse import quote_plus
from decouple import config


class Config(object):

    basedir = os.path.abspath(os.path.dirname(__file__))

    # Set up the App SECRET_KEY
    SECRET_KEY = config('SECRET_KEY', default='S#perS3crEt_007')

    # Database connection defaults (MySQL)
    DB_ENGINE = config('DB_ENGINE', default='mysql+pymysql')
    DB_USERNAME = config('DB_USERNAME', default='amantini')
    DB_PASS = quote_plus(config('DB_PASS', default=''))
    DB_HOST = config('DB_HOST', default='localhost')
    DB_PORT = config('DB_PORT', default=3306)
    DB_NAME = config('DB_NAME', default='amantini')

    _auth_part = f"{DB_USERNAME}:{DB_PASS}" if DB_PASS else DB_USERNAME
    SQLALCHEMY_DATABASE_URI = f"{DB_ENGINE}://{_auth_part}@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"
    SQLALCHEMY_TRACK_MODIFICATIONS = False


class ProductionConfig(Config):
    DEBUG = False

    # Security
    SESSION_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_DURATION = 3600


class DebugConfig(Config):
    DEBUG = True


# Load all possible configurations
config_dict = {
    'Production': ProductionConfig,
    'Debug': DebugConfig
}
