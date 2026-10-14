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


def test_cosine_similarity_normalizes_unnormalized_vectors()->None:
	assert cosine_similarity((3.0,4.0),(6.0,8.0))==pytest.approx(1.0)
	assert cosine_similarity((3.0,4.0),(4.0,-3.0))==pytest.approx(0.0)


def test_cosine_similarity_rejects_zero_and_nonfinite_vectors()->None:
	with pytest.raises(ValueError): cosine_similarity((0.0,0.0),(1.0,2.0))
	with pytest.raises(ValueError): cosine_similarity((float("nan"),1.0),(1.0,2.0))
	with pytest.raises(ValueError): cosine_similarity((float("inf"),1.0),(1.0,2.0))
	with pytest.raises(ValueError): cosine_similarity(("invalid",1.0),(1.0,2.0))


def test_cosine_similarity_handles_large_finite_values()->None:
	assert cosine_similarity((1e308,1e308),(1e308,1e308))==pytest.approx(1.0)
