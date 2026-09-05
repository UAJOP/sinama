import asyncio
from collections.abc import Sequence

from app.http_agent import validate_external_agent_endpoint


async def dual_stack_resolver(_host: str, _port: int) -> Sequence[str]:
    return ["2606:4700:3037::6815:abcd", "104.21.12.34"]


async def ipv6_only_resolver(_host: str, _port: int) -> Sequence[str]:
    return ["2606:4700:3037::6815:abcd"]


def test_dual_stack_endpoint_prefers_ipv4_for_pinned_connection() -> None:
    endpoint = asyncio.run(
        validate_external_agent_endpoint(
            "https://agent.example.com/turn",
            production=True,
            resolver=dual_stack_resolver,
        )
    )

    assert str(endpoint.request_url) == "https://104.21.12.34/turn"
    assert endpoint.host_header == "agent.example.com"
    assert endpoint.sni_hostname == "agent.example.com"


def test_ipv6_only_endpoint_remains_supported() -> None:
    endpoint = asyncio.run(
        validate_external_agent_endpoint(
            "https://agent.example.com/turn",
            production=True,
            resolver=ipv6_only_resolver,
        )
    )

    assert str(endpoint.request_url) == "https://[2606:4700:3037::6815:abcd]/turn"
    assert endpoint.host_header == "agent.example.com"
    assert endpoint.sni_hostname == "agent.example.com"
