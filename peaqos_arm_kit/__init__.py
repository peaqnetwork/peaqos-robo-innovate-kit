"""peaqOS arm kit: record a robot arm's joint motion as peaqOS events.

Pipeline: joint source -> motion segmenter -> canonical event (hashed) ->
local motion log -> peaqOS EventRegistry (hash only) -> independent verifier.
"""

__version__ = "0.1.0"
