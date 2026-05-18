from pydantic import BaseModel, Field
from typing import List


class GherkinStep(BaseModel):
    keyword: str = Field(..., description="Given/When/Then/And")
    text: str


class GherkinScenario(BaseModel):
    name: str
    steps: List[GherkinStep]
    tags: List[str] = Field(default_factory=list)


class PytestStep(BaseModel):
    description: str
    code: str


class PytestTestCase(BaseModel):
    function_name: str
    docstring: str
    steps: List[PytestStep]


class TestSuite(BaseModel):
    feature: str = Field(..., description="Feature name derived from the user story")
    scenarios: List[GherkinScenario]
    pytest_cases: List[PytestTestCase]
    coverage_notes: str = Field(..., description="Brief note on what scenarios are covered and what's intentionally out of scope")
