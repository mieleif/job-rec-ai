import numpy as np

from job_rec_ai import embeddings


def test_cache_ne_recalcule_que_les_textes_nouveaux(tmp_path, monkeypatch):
    """Le modèle (lent) n'est appelé que pour les textes absents du cache."""
    calls = []

    def fake_encode(texts, kind):
        calls.append(list(texts))
        return np.array([[len(t), 1.0] for t in texts]) / 10

    monkeypatch.setattr(embeddings, "encode", fake_encode)
    first = embeddings.passage_matrix(["a", "bb"], cache_dir=tmp_path)
    second = embeddings.passage_matrix(["bb", "ccc", "a"], cache_dir=tmp_path)
    assert calls == [["a", "bb"], ["ccc"]]
    assert np.allclose(second[0], first[1]) and np.allclose(second[2], first[0])
    assert second.shape == (3, 2)
