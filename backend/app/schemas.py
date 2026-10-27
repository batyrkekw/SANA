import ast
import json
import operator
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, StringConstraints, model_validator

Language = Literal["ru", "kk"]
Kind = Literal["lesson", "quiz", "comic", "flashcards", "image"]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=6000)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProfileUpdate(StrictModel):
    display_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)
    ]
    language: Language


class GenerationInput(StrictModel):
    kind: Kind = "lesson"
    subject: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    topic: ShortText
    grade: int = Field(8, ge=1, le=12)
    language: Language = "ru"
    length: int = Field(3, ge=1, le=12)
    instructions: str = Field("", max_length=6000)
    include_images: bool = False
    image_count: int = Field(1, ge=1, le=8)
    style: Literal["educational", "cartoon", "infographic", "historical", "scientific"] = (
        "educational"
    )
    aspect_ratio: Literal["1:1", "4:3", "3:4"] = "1:1"

    @model_validator(mode="after")
    def valid_options(self):
        if self.include_images and self.kind not in ("comic", "lesson"):
            raise ValueError("Images can accompany lessons and comics only")
        if self.kind == "quiz" and self.length < 3:
            raise ValueError("A quiz requires at least three questions")
        return self


def arithmetic(expression: str) -> float:
    """Optional deterministic check of simple arithmetic; no eval or arbitrary execution."""
    if len(expression) > 80:
        raise ValueError("Expression too long")
    operations = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
    }

    def visit(node):
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            value = node.value
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = visit(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        elif isinstance(node, ast.BinOp) and type(node.op) in operations:
            value = operations[type(node.op)](visit(node.left), visit(node.right))
        else:
            raise ValueError("Unsupported arithmetic")
        if abs(value) > 1e12:
            raise ValueError("Arithmetic out of bounds")
        return value

    try:
        return visit(ast.parse(expression, mode="eval").body)
    except (SyntaxError, ZeroDivisionError, RecursionError) as error:
        raise ValueError("Invalid arithmetic") from error


class ArithmeticCheck(StrictModel):
    expression: str = Field(max_length=80)
    result: FiniteFloat

    @model_validator(mode="after")
    def correct(self):
        if abs(arithmetic(self.expression) - self.result) > 1e-6:
            raise ValueError("Arithmetic does not match")
        return self


class Question(StrictModel):
    prompt: Text
    options: list[ShortText] = Field(min_length=2, max_length=6)
    correct_index: int = Field(ge=0)
    explanation: Text
    arithmetic_check: ArithmeticCheck | None = None

    @model_validator(mode="after")
    def valid_answers(self):
        if self.correct_index >= len(self.options):
            raise ValueError("Correct answer out of range")
        if len({option.casefold() for option in self.options}) != len(self.options):
            raise ValueError("Duplicate answers")
        if self.arithmetic_check:
            answer = self.options[self.correct_index].strip().replace(",", ".")
            if re.fullmatch(r"[+-]?\d+(?:\.\d+)?", answer):
                if abs(float(answer) - self.arithmetic_check.result) > 1e-6:
                    raise ValueError("Selected numeric answer does not match verified arithmetic")
        return self


class Panel(StrictModel):
    scene: Text
    dialogue: Text
    narration: Text
    image_prompt: Text


class Flashcard(StrictModel):
    front: Text
    back: Text


class EducationalContent(StrictModel):
    title: ShortText
    language: Language
    kind: Kind
    objectives: list[ShortText] = Field(default_factory=list, max_length=6)
    explanation: str = Field("", max_length=16000)
    examples: list[Text] = Field(default_factory=list, max_length=12)
    questions: list[Question] = Field(default_factory=list, max_length=12)
    summary: str = Field("", max_length=4000)
    panels: list[Panel] = Field(default_factory=list, max_length=8)
    cards: list[Flashcard] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def complete(self):
        if self.kind == "lesson" and not all(
            [
                self.objectives,
                self.explanation.strip(),
                self.examples,
                self.questions,
                self.summary.strip(),
            ]
        ):
            raise ValueError("Incomplete lesson")
        if self.kind == "quiz" and len(self.questions) < 3:
            raise ValueError("Incomplete quiz")
        if self.kind == "comic" and (not self.panels or not self.objectives):
            raise ValueError("Incomplete comic")
        if self.kind == "flashcards" and not self.cards:
            raise ValueError("Incomplete flashcards")
        return self


def validate_result(data: dict, request: GenerationInput, max_bytes: int) -> dict:
    if len(json.dumps(data, ensure_ascii=False).encode()) > max_bytes:
        raise ValueError("Result too large")
    result = EducationalContent.model_validate(data)
    if result.kind != request.kind or result.language != request.language:
        raise ValueError("Result kind or language mismatch")
    counts = {
        "comic": len(result.panels),
        "quiz": len(result.questions),
        "flashcards": len(result.cards),
        "lesson": len(result.questions),
    }
    if request.kind in counts and counts[request.kind] != request.length:
        raise ValueError("Result length mismatch")
    if request.kind != "image":
        # A script check detects obvious wrong-language output, not semantic correctness.
        visible = (
            result.title
            + result.explanation
            + result.summary
            + " ".join(q.prompt for q in result.questions)
            + " ".join(p.narration for p in result.panels)
            + " ".join(c.front for c in result.cards)
        )
        if not re.search(r"[А-Яа-яӘәҒғҚқҢңӨөҰұҮүҺһІі]", visible):
            raise ValueError("Expected Cyrillic educational content")
    return result.model_dump()


class MaterialInput(StrictModel):
    subject: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    topic: ShortText
    content: EducationalContent


class MaterialUpdate(StrictModel):
    title: ShortText
