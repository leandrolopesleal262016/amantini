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

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Database connection defaults (MySQL)
    DB_ENGINE = config('DB_ENGINE', default='mysql+pymysql')
    DB_USERNAME = config('DB_USERNAME', default='amantini')
    DB_PASS = quote_plus(config('DB_PASS', default=''))
    DB_HOST = config('DB_HOST', default='localhost')
    DB_PORT = config('DB_PORT', default=3306)
    DB_NAME = config('DB_NAME', default='amantini')

    @classmethod
    def _mysql_uri(cls):
        auth = f"{cls.DB_USERNAME}:{cls.DB_PASS}" if cls.DB_PASS else cls.DB_USERNAME
        return f"{cls.DB_ENGINE}://{auth}@{cls.DB_HOST}:{cls.DB_PORT}/{cls.DB_NAME}?charset=utf8mb4"

    SQLALCHEMY_DATABASE_URI = None


class ProductionConfig(Config):
    DEBUG = False

    # Security
    SESSION_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_DURATION = 3600


class DebugConfig(Config):
    DEBUG = True
    DB_ENGINE = 'sqlite'
    SQLITE_DB_PATH = config(
        'DEBUG_DB_PATH',
        default=os.path.join(Config.basedir, 'debug.sqlite3')
    )
    SQLALCHEMY_DATABASE_URI = config(
        'DEBUG_DATABASE_URI',
        default='sqlite:///' + os.path.abspath(SQLITE_DB_PATH).replace(os.sep, '/')
    )


# Load all possible configurations
config_dict = {
    'Production': ProductionConfig,
    'Debug': DebugConfig
}


Config.SQLALCHEMY_DATABASE_URI = config('DATABASE_URL', default=None) or Config._mysql_uri()
