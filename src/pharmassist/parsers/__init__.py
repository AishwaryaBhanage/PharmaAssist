from pharmassist.parsers.base import Block, Parser
from pharmassist.parsers.docling_parser import DoclingParser

PARSERS = {"docling": DoclingParser}

__all__ = ["PARSERS", "Block", "Parser", "DoclingParser"]
