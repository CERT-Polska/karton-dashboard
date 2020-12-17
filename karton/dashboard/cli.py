import click
from flask.cli import FlaskGroup

from .app import app


def create_app():
    return app


@click.group(cls=FlaskGroup, create_app=create_app)
def cli():
    """
    A small Flask application that allows for Karton task and queue introspection.
    """
