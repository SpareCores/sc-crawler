import json
from atexit import register
from functools import cache
from os import PathLike, getenv, makedirs, path
from shutil import rmtree
from tempfile import mkdtemp
from typing import TYPE_CHECKING, List

from requests import get
from zipfile import ZipFile

from .logger import logger
from .table_bases import ServerDescriptionFields

if TYPE_CHECKING:
    from .tables import Server

DESCRIPTIONS_ZIP_URL = (
    "https://github.com/SpareCores/sc-navigator-descriptions/archive/refs/heads/main.zip"
)


@cache
def descriptions_data_path() -> str | PathLike:
    """Download current server description data into a temp folder.

    Setting the `SC_CRAWLER_DESCRIPTIONS_DATA_PATH` environment variable will
    override the default path for persistent/cached description data access.
    """
    if getenv("SC_CRAWLER_DESCRIPTIONS_DATA_PATH"):
        temp_dir = getenv("SC_CRAWLER_DESCRIPTIONS_DATA_PATH")
        makedirs(temp_dir, exist_ok=True)
    else:
        temp_dir = mkdtemp()
        register(rmtree, temp_dir)
    zip_path = path.join(temp_dir, "downloaded.zip")
    if not path.exists(zip_path):
        response = get(DESCRIPTIONS_ZIP_URL)
        with open(zip_path, "wb") as f:
            f.write(response.content)
        with ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(temp_dir)
    return path.join(temp_dir, "sc-navigator-descriptions-main", "data")


def _server_ids(server: "Server") -> dict:
    return {"vendor_id": server.vendor_id, "server_id": server.server_id}


def _server_path(server: "Server") -> str | PathLike:
    return path.join(descriptions_data_path(), server.vendor_id, server.api_reference)


def _server_description_output_path(server: "Server") -> str | PathLike:
    return path.join(_server_path(server), "descriptions", "output.json")


def _load_server_description_output(server: "Server") -> dict:
    with open(_server_description_output_path(server), "r") as fp:
        return json.load(fp)


def _log_cannot_load_description(server: "Server", e, exc_info=False):
    logger.debug(
        "Server description not loaded for %s/%s: %s",
        server.vendor_id,
        server.api_reference,
        e,
        stacklevel=2,
        exc_info=exc_info,
    )


def ingest_server_description(server: "Server") -> dict | None:
    """Load and validate generated description data for a Server."""
    try:
        output = _load_server_description_output(server)
        fields = ServerDescriptionFields.model_validate(output)
        return {**_server_ids(server), **fields.model_dump()}
    except Exception as e:
        _log_cannot_load_description(server, e)
        return None


def ingest_server_descriptions(servers: List["Server"]) -> List[dict]:
    """Load generated description data for all Servers with available output."""
    descriptions = []
    for server in servers:
        description = ingest_server_description(server)
        if description is not None:
            descriptions.append(description)
    return descriptions
