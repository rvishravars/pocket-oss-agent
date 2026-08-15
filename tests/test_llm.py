"""Coverage for the Claude extractor's response handling.

The live call is exercised against a fake client so the suite needs no API key
and never reaches the network. What is tested here is everything the wrapper
adds around the SDK: schema shape, and the failure paths that a naive
implementation would turn into an unrelated AttributeError.
"""

import pytest

from pocket_oss_agent.errors import ProfileExtractionFailed
from pocket_oss_agent.llm import (
    MODEL,
    ClaudeProfileExtractor,
    ExtractedProfile,
)

RESUME = "Marcus Okonkwo. Backend engineer, 6 years. Go, Python. FastAPI, gRPC. AWS, Kafka."


class FakeResponse:
    def __init__(self, *, stop_reason="end_turn", parsed_output=None, category=None):
        self.stop_reason = stop_reason
        self.parsed_output = parsed_output
        self.stop_details = type("Details", (), {"category": category})() if category else None


class FakeMessages:
    def __init__(self, response) -> None:
        self._response = response
        self.calls: list[dict] = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


class FakeClient:
    def __init__(self, response) -> None:
        self.messages = FakeMessages(response)


PROFILE = ExtractedProfile(
    name="Marcus Okonkwo",
    languages=["Go", "Python"],
    frameworks=["FastAPI", "gRPC"],
    tools=["AWS", "Kafka"],
    years_experience=6,
    seniority="senior",
    domain="backend",
)


class TestModelChoice:
    def test_defaults_to_haiku(self) -> None:
        """Single-shot extraction, so the cheapest tier that supports
        structured outputs is the right one.
        """
        assert MODEL == "claude-haiku-4-5"

    def test_the_model_is_overridable(self) -> None:
        client = FakeClient(FakeResponse(parsed_output=PROFILE))
        ClaudeProfileExtractor(client=client, model="claude-opus-5").extract(RESUME)
        assert client.messages.calls[0]["model"] == "claude-opus-5"

    def test_sends_no_effort_parameter(self) -> None:
        """`effort` is rejected on Haiku 4.5."""
        client = FakeClient(FakeResponse(parsed_output=PROFILE))
        ClaudeProfileExtractor(client=client).extract(RESUME)
        assert "output_config" not in client.messages.calls[0]
        assert "effort" not in client.messages.calls[0]


class TestExtraction:
    def test_maps_the_parsed_profile_onto_developer_context(self) -> None:
        client = FakeClient(FakeResponse(parsed_output=PROFILE))
        context = ClaudeProfileExtractor(client=client).extract(RESUME)

        assert context.name == "Marcus Okonkwo"
        assert context.languages == ["Go", "Python"]
        assert context.seniority == "senior"

    def test_sends_the_schema_and_the_resume(self) -> None:
        client = FakeClient(FakeResponse(parsed_output=PROFILE))
        ClaudeProfileExtractor(client=client).extract(RESUME)

        call = client.messages.calls[0]
        assert call["model"] == MODEL
        assert call["output_format"] is ExtractedProfile
        assert RESUME in call["messages"][0]["content"]
        assert "recruiter" in call["system"]

    def test_sends_no_sampling_parameters(self) -> None:
        """temperature, top_p and top_k are rejected on this model."""
        client = FakeClient(FakeResponse(parsed_output=PROFILE))
        ClaudeProfileExtractor(client=client).extract(RESUME)

        call = client.messages.calls[0]
        assert not {"temperature", "top_p", "top_k"} & call.keys()


class TestFailurePaths:
    def test_a_refusal_is_reported_not_dereferenced(self) -> None:
        """A refusal returns HTTP 200 with empty content, so reading
        parsed_output first turns a policy decline into an AttributeError.
        """
        client = FakeClient(FakeResponse(stop_reason="refusal", category="cyber"))

        with pytest.raises(ProfileExtractionFailed) as excinfo:
            ClaudeProfileExtractor(client=client).extract(RESUME)

        assert "declined" in str(excinfo.value)
        assert "cyber" in str(excinfo.value)

    def test_a_refusal_without_a_category_still_reports(self) -> None:
        client = FakeClient(FakeResponse(stop_reason="refusal"))
        with pytest.raises(ProfileExtractionFailed, match="no category reported"):
            ClaudeProfileExtractor(client=client).extract(RESUME)

    def test_hitting_the_token_ceiling_names_the_limit(self) -> None:
        client = FakeClient(FakeResponse(stop_reason="max_tokens"))
        with pytest.raises(ProfileExtractionFailed) as excinfo:
            ClaudeProfileExtractor(client=client, max_tokens=1234).extract(RESUME)

        assert "1234" in str(excinfo.value)

    def test_a_missing_parsed_output_is_reported(self) -> None:
        client = FakeClient(FakeResponse(stop_reason="end_turn", parsed_output=None))
        with pytest.raises(ProfileExtractionFailed, match="no parsed profile"):
            ClaudeProfileExtractor(client=client).extract(RESUME)


class TestSchema:
    def test_the_sdk_sends_a_valid_structured_output_schema(self) -> None:
        """Structured outputs require additionalProperties: false and a fully
        populated `required`. Pydantic omits the former; the SDK's transform
        adds it, so this pins the behaviour we rely on.
        """
        from anthropic.lib._parse._transform import transform_schema

        sent = transform_schema(ExtractedProfile.model_json_schema())

        assert sent["additionalProperties"] is False
        assert sorted(sent["required"]) == sorted(ExtractedProfile.model_fields)

    def test_the_schema_description_is_written_for_the_model(self) -> None:
        """The class docstring rides to the model on every call, so it carries
        no implementation rationale.
        """
        description = ExtractedProfile.model_json_schema()["description"]

        assert len(description) < 120
        assert "DeveloperContext" not in description

    def test_every_field_is_described(self) -> None:
        properties = ExtractedProfile.model_json_schema()["properties"]
        assert all("description" in prop for prop in properties.values())

    def test_seniority_is_constrained_to_the_known_values(self) -> None:
        schema = ExtractedProfile.model_json_schema()
        blob = str(schema)
        for value in ("junior", "mid", "senior", "staff"):
            assert value in blob


class TestClientConstruction:
    def test_builds_its_own_client_when_none_is_given(self, monkeypatch) -> None:
        """The anthropic import is lazy so the package is importable, and the
        rest of the pipeline usable, without a key present.
        """
        import sys
        import types

        built: list[str] = []

        module = types.ModuleType("anthropic")
        module.Anthropic = lambda: built.append("constructed") or object()
        monkeypatch.setitem(sys.modules, "anthropic", module)

        ClaudeProfileExtractor()

        assert built == ["constructed"]
