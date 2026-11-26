from pydantic_ai import FunctionToolset


def echo(text: str) -> str:
    """Return the given text unchanged."""
    return text


echo_toolset = FunctionToolset([echo])
