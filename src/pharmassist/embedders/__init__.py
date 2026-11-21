from pharmassist.embedders.base import Embedder


def _openai(**kwargs):
    # imported lazily: only callers that embed need the openai package and an API key
    from pharmassist.embedders.openai_large import OpenAIEmbedder
    return OpenAIEmbedder(**kwargs)


EMBEDDERS = {"openai": _openai}

__all__ = ["EMBEDDERS", "Embedder"]
