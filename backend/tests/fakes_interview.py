"""A scripted AI provider that plays all four interview roles. No network, no credentials."""

import json
from collections.abc import Callable
from typing import Any

ROLES = {
    "You are an experienced interviewer": "questions",
    "You are the interviewer": "followup",
    "You are a fair, precise": "evaluation",
    "You are a supportive": "feedback",
}

TOPICS = [
    "database indexing", "API pagination", "caching strategy", "error handling",
    "container networking", "unit testing", "memory management", "message queues",
    "authentication flows", "deployment rollbacks", "logging practice", "schema migration",
    "rate limiting", "code review habits", "dependency upgrades", "load balancing",
    "data validation", "background jobs", "feature toggles", "monitoring alerts",
]  # fmt: skip
FOLLOW_UPS = [
    "What trade-off did you accept when you chose that approach in practice?",
    "Could you walk me through one concrete example where this mattered for you?",
    "Which alternative solution did you consider and why did you reject it?",
    "How would you check that your answer holds under heavier traffic?",
    "What would you change if the requirements suddenly doubled in scope?",
]  # fmt: skip


def data_block(user: str, index: int = 0) -> dict[str, Any]:
    """The JSON inside the ``index``-th DATA block of a user message."""
    lines = user.splitlines()
    fences = [i for i, line in enumerate(lines) if line.startswith("DATA_")]
    start, end = fences[2 * index], fences[2 * index + 1]
    text = "\n".join(lines[start + 1 : end])
    try:
        parsed = json.loads(text)
    except ValueError:
        return {"text": text}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


def evaluation_reply(score: int = 8, **overrides: Any) -> dict[str, Any]:
    reply: dict[str, Any] = {
        "dimensions": {
            "technical_correctness": {"score": score, "rationale": "Mostly right."},
            "relevance": {"score": score, "rationale": "On topic."},
            "completeness": {"score": score, "rationale": "Covers the main points."},
            "problem_solving": {"score": score, "rationale": "Sound approach."},
            "practical_application": {"score": score, "rationale": "Realistic."},
            "clarity": {"score": score, "rationale": "Clear."},
            "evidence_examples": {"score": score, "rationale": "Some examples."},
        },
        "star": None,
        "correct_points": ["The core idea"],
        "missing_or_incorrect_points": ["Edge cases"],
        "strengths": ["Clear structure"],
        "improvements": ["Add an example"],
        "summary": "A solid answer.",
        "not_evaluable": [],
    }
    reply.update(overrides)
    return reply


class InterviewFakeProvider:
    """Replies per role. ``replies[role]`` may be a value or ``callable(system, user)``;
    ``errors[role]`` is raised instead; ``calls`` records ``(role, system, user)``."""

    name = "fake"
    model = "fake-model"

    def __init__(
        self,
        *,
        is_external: bool = False,
        available: bool = True,
        followups: bool = True,
        score: int = 8,
    ) -> None:
        self.is_external = is_external
        self._available = available
        self.replies: dict[str, Any] = {}
        self.errors: dict[str, Exception] = {}
        self.calls: list[tuple[str, str, str]] = []
        self._followups = followups
        self._score = score
        self._follow_index = 0

    @property
    def available(self) -> bool:
        return self._available

    def roles(self, role: str) -> list[tuple[str, str]]:
        return [(s, u) for r, s, u in self.calls if r == role]

    async def complete_json(self, *, system: str, user: str) -> str:
        role = next((r for prefix, r in ROLES.items() if system.startswith(prefix)), "unknown")
        self.calls.append((role, system, user))
        if role in self.errors:
            raise self.errors[role]
        reply = self.replies.get(role)
        if reply is None:
            reply = getattr(self, f"_default_{role}")(user)
        elif callable(reply):
            reply = reply(system, user)
        return reply if isinstance(reply, str) else json.dumps(reply)

    # ----------------------------------------------------------- defaults

    def _default_questions(self, user: str) -> dict[str, Any]:
        data = data_block(user)
        types: list[str] = data["categories"]
        count: int = data["number_of_questions"]
        asked = len(self.roles("questions"))
        questions = []
        for i in range(count):
            category = types[i % len(types)]
            topic = TOPICS[(i + 3 * asked) % len(TOPICS)]
            questions.append(
                {
                    "category": category,
                    "text": f"In a {category} setting, how would you reason about {topic} "
                    f"when requirement number {i + 1} changes late?",
                    "skill_tags": [topic.split()[0]],
                    "expected_points": [f"{topic} basics", "trade-offs"],
                    "project": None,
                }
            )
        return {"questions": questions}

    def _default_followup(self, user: str) -> dict[str, Any]:
        if not self._followups:
            return {"follow_up": None}
        text = FOLLOW_UPS[self._follow_index % len(FOLLOW_UPS)]
        self._follow_index += 1
        return {"follow_up": {"kind": "trade_offs", "text": text}}

    def _default_evaluation(self, user: str) -> dict[str, Any]:
        return evaluation_reply(self._score)

    def _default_feedback(self, user: str) -> dict[str, Any]:
        return {
            "summary": "A reasonable practice session with clear areas to strengthen.",
            "study_topics": [{"topic": "Trade-offs", "reason": "Explain why, not only what."}],
            "practice_questions": ["How would you design a retry policy for a flaky API?"],
        }

    def _default_unknown(self, user: str) -> dict[str, Any]:  # pragma: no cover
        raise AssertionError("unexpected prompt")


ReplyFactory = Callable[[str, str], Any]
