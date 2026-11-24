import csv
import io
from pathlib import Path

import pytest

from app.intake.schema import HEADER
from app.experiment.schema import HEADER as EXPERIMENT_HEADER
from app.experiment.store import ExperimentStore
from app.main import create_app
from app.review.store import Store


ROOT = Path(__file__).resolve().parents[1]


def csv_data(records, header=HEADER):
    stream = io.StringIO(newline="")
    csv.writer(stream).writerows([header, *records])
    return stream.getvalue().encode()


def experiment_csv(records):
    return csv_data(records, EXPERIMENT_HEADER)


@pytest.fixture
def dirty():
    return (ROOT / "sample_data" / "incoming.csv").read_bytes()


@pytest.fixture
def clean():
    return (ROOT / "sample_data" / "ready.csv").read_bytes()


@pytest.fixture
def client(tmp_path):
    return create_app(tmp_path / "runs.db").test_client()


@pytest.fixture
def experiment_ready():
    return (ROOT / "sample_data" / "experiment_ready.csv").read_bytes()


@pytest.fixture
def experiment_risk():
    return (ROOT / "sample_data" / "experiment_risk.csv").read_bytes()


@pytest.fixture
def experiment_client(tmp_path):
    return create_app(
        tmp_path / "runs.db", tmp_path / "experiments.db"
    ).test_client()


@pytest.fixture
def experiment_store(tmp_path):
    return ExperimentStore(tmp_path / "experiments.db")


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "runs.db")
