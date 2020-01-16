import sys
import click
import os.path as op
import sqlite3
import shutil
from functools import partial
import subprocess as sp

from .common import (
    get_data_dir,
    get_site_url,
    get_port,
    SQLITEDB
)

from .stop import _stop


@click.command()
@click.option(
    "--old-hg-name",
    help="The name of the running higlass container"
         " that needs to be updated.",
    required = False,
)
@click.option(
    "--old-site-url",
    help="site-url at the old location."
         " Provide this when higlass container"
         " one is updating is not running.",
    required=False,
)
@click.option(
    "--old-port",
    help="port at the old location."
         " Provide this when higlass container"
         " one is updating is not running.",
    required=False,
    default="80",
    type=str,
)
@click.option(
    "--old-data-dir",
    help="data directory of the higlass"
         " that is to be updated (usually 'hg-data')."
         " Provide this when higlass container"
         " is not running.",
    required=False,
)
@click.option(
    "--new-site-url",
    default="http://localhost",
    help="site-url at the new location.",
    required=True
)
@click.option(
    "--new-port",
    help="port at the new location",
    required = False,
    default="80",
    type=str,
)
def update_viewconfs(old_hg_name,
                    old_site_url,
                    old_port,
                    old_data_dir,
                    new_site_url,
                    new_port):
    """
    The script allows one to update viewconfs saved
    in an existing higlass database. It does so
    by modifying references to tilesets that use
    old-site-url:old-port --> new-site-url:new-port

    old/new-site-urls must include schema (http, https):
    http://localhost
    http://old.host.org
    ...

    if 'old-hg-name' is provided and higlass is running,
    then 'old-site-url,old-port,old-data-dir' are inferred.

    if 'old-hg-name' is NOT provided
    then at least 'old-site-url'and 'old-data-dir'
    are required.

    Post 80 is default http port and both
    new-port and old-port defaults to it,
    if not specified otherwise.
    site-url:80 is equivalent to site-url

    Script keeps existing database unchanged,
    but modifies a backed up version "db.sqlite3.updated"
    located in the same path as the original one.

    Running higlass-container would be stopped by
    update_viewconfs.

    """

    # update viewconfs FROM (ORIGIN):
    if old_hg_name is not None:
        # then the container must be running
        try:
            old_site_url = get_site_url(old_hg_name)
            old_port = get_port(old_hg_name)
            old_data_dir = get_data_dir(old_hg_name)
        except docker.errors.NotFound as ex:
            sys.stderr.write(f"Instance not running: {old_hg_name}\n")
    elif (old_site_url is None) or (old_data_dir is None):
        raise ValueError(
            "old-site-url and old-data-dir must be provided,"
            " when instance is not running and no old-hg-name is provided\n"
            )

    # define origin as site_url:port or site_url (when 80)
    origin = old_site_url if (old_port == "80") \
                        else f"{old_site_url}:{old_port}"

    # update viewconfs TO (DESTINATION):
    # define destination as site_url:port or site_url (when 80)
    destination = new_site_url if (new_port == "80") \
                        else f"{new_site_url}:{new_port}"

    # locate db.sqlite3 and name for the updated version:
    origin_db_path = op.join(old_data_dir, SQLITEDB)
    update_db_path = op.join(old_data_dir, f"{SQLITEDB}.updated")

    # backup the database in a safest way possible ...
    if old_hg_name is not None:
        _stop([old_hg_name,],False, False, False)
    try:
        # this should be a safe way to backup a database:
        res = sp.run(["sqlite3",origin_db_path,f".backup {update_db_path}"])
    except OSError as e:
        sys.stderr.write(
            "sqlite3 is not installed!"
            "script will attempt to copy the database file instead."
            )
        sys.stderr.flush()
        # not so safe way to backup a database:
        shutil.copyfile(origin_db_path, update_db_path)
    else:
        # check if sqlite3 actually ran fine:
        if res.returncode != 0:
            raise RuntimeError(
                    "The database backup using sqlite3 exited"
                    f"with error code {res.returncode}."
                )

    # it would be great to restart the instance after backup ...
    # consider re-using _start with all the parameters inferred from
    # old-hg-name ...


    # once update_db_path is backedup, we can connect to it:
    conn = None
    try:
        conn = sqlite3.connect(update_db_path)
    except sqlite3.Error as e:
        sys.stderr.write(f"Failed to connect to {update_db_path}")
        sys.exit(-1)

    # sql query to update viewconfs, by replacing origin -> destination
    db_query = f'''
            UPDATE tilesets_viewconf
            SET viewconf = replace(viewconf,'{origin}','{destination}')
            '''
    # exec sql query
    with conn:
        cur = conn.cursor()
        cur.execute(db_query)

    conn.close()
    # todo: add some stats on - how many viewconfs
    # were updated

    sys.stderr.write(
        f"{update_db_path } has been updated and ready for migration"
        " copy it to the new host along with the media folder"
        " rename the database file back to db.sqlite3 and restart higlass."
        )
    sys.stderr.flush()
