import click
from flask.cli import FlaskGroup

from .app import app


@click.group(cls=FlaskGroup, create_app=lambda: app)
def cli():
    """
    A small Flask application that allows for Karton task and queue introspection.
    """
