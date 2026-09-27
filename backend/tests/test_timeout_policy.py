from inspect import signature

from app.http_agent import HttpAgentAdapter
from app.scenario_runner import ScenarioRunner


def test_external_and_scenario_turn_deadlines_share_sixty_second_default() -> None:
    http_timeout = signature(HttpAgentAdapter).parameters["timeout_seconds"].default
    runner_timeout = signature(ScenarioRunner.run).parameters["turn_timeout_seconds"].default

    assert http_timeout == 60.0
    assert runner_timeout == 60.0
