import duckdb
import pytest

from job_rec_ai import storage


def test_connect_reessaie_tant_que_la_base_est_verrouillee(tmp_path, monkeypatch):
    """La collecte attend que l'API ait fini de relire la base, au lieu d'échouer."""
    attempts = []
    real_connect = duckdb.connect

    def flaky(path, *args, **kwargs):
        attempts.append(path)
        if len(attempts) < 3:
            raise duckdb.IOException("Could not set lock on file")
        return real_connect(path, *args, **kwargs)

    monkeypatch.setattr(storage.duckdb, "connect", flaky)
    monkeypatch.setattr(storage, "LOCK_WAIT", 0)
    storage.connect(tmp_path / "jobs.duckdb").close()
    assert len(attempts) == 3


def test_connect_n_insiste_pas_sur_une_autre_erreur(tmp_path, monkeypatch):
    def broken(path, *args, **kwargs):
        raise duckdb.IOException("disk full")

    monkeypatch.setattr(storage.duckdb, "connect", broken)
    with pytest.raises(duckdb.IOException, match="disk full"):
        storage.connect(tmp_path / "jobs.duckdb")
