import pytest

from evidenceops.application.knowledge_embedding import HashEmbeddingProvider,cosine_similarity


def test_embedding_shape_is_stable_for_test_provider()->None:
	provider=HashEmbeddingProvider(8)
	vector=provider.embed(("线程池超时",))[0]
	assert len(vector)==8
	assert abs(cosine_similarity(vector,vector)-1)<1e-9
	assert vector==provider.embed(("线程池超时",))[0]


def test_embedding_rejects_invalid_input_and_dimension()->None:
	with pytest.raises(ValueError): HashEmbeddingProvider(0)
	with pytest.raises(ValueError): HashEmbeddingProvider().embed(("",))
	with pytest.raises(ValueError): cosine_similarity((1.0,),(1.0,2.0))
