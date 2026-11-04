"""Curated question bank: the interview works without any AI provider.

Each entry has a category, difficulty, skill tags and ``key_points`` (what a good answer
touches on). Key points are used only in the final report (study topics) and are never
shown while the interview runs. The bank never claims anything about the candidate: project
questions are generic ("choose a project you built") unless AI-generated from real evidence.
"""

import random
from collections.abc import Iterable
from dataclasses import dataclass

from app.jobs.taxonomy import squash

Difficulty = str  # "beginner" | "intermediate" | "advanced"
_LEVEL = {"b": "beginner", "i": "intermediate", "a": "advanced"}
_ORDER = ["beginner", "intermediate", "advanced"]


@dataclass(frozen=True)
class BankQuestion:
    id: str
    category: str
    difficulty: Difficulty
    text: str
    tags: tuple[str, ...]
    key_points: tuple[str, ...]


def _q(category: str, level: str, tags: str, text: str, points: str) -> BankQuestion:
    tag_tuple = tuple(t for t in tags.split(",") if t)
    return BankQuestion(
        id="",
        category=category,
        difficulty=_LEVEL[level],
        text=text,
        tags=tag_tuple,
        key_points=tuple(p.strip() for p in points.split("|") if p.strip()),
    )


_RAW: list[BankQuestion] = [
    # ------------------------------------------------------------------ HR
    _q(
        "hr",
        "b",
        "general",
        "Tell me about yourself and why you are interested in this kind of role.",
        "relevant background|motivation|link to the role",
    ),
    _q(
        "hr",
        "b",
        "general",
        "What are your main strengths, and one area you are actively working to improve?",
        "specific strengths with examples|honest improvement area|steps being taken",
    ),
    _q(
        "hr",
        "b",
        "general",
        "Why do you want to work in this field, and what would you like to learn in your first year?",
        "genuine motivation|realistic learning goals",
    ),
    _q(
        "hr",
        "i",
        "general",
        "How do you prioritise your work when several deadlines compete at the same time?",
        "criteria for prioritising|communication with stakeholders|example",
    ),
    _q(
        "hr",
        "i",
        "general",
        "Where do you see your career in three years, and how does this role fit that plan?",
        "realistic goals|link to the role|willingness to grow",
    ),
    _q(
        "hr",
        "i",
        "general",
        "What kind of team and working environment helps you do your best work?",
        "self-awareness|flexibility|collaboration",
    ),
    _q(
        "hr",
        "a",
        "general",
        "If you disagreed with your manager about a priority, how would you handle it?",
        "listening first|evidence-based argument|disagree and commit|escalation only if needed",
    ),
    _q(
        "hr",
        "a",
        "general",
        "What would you aim to achieve in your first 90 days in a new role?",
        "learning the domain|building relationships|early small wins|asking for feedback",
    ),
    _q(
        "hr",
        "a",
        "general",
        "How do you decide when to accept a role, and what would make you leave one?",
        "values and criteria|professional reasoning|no blame on past employers",
    ),
    # ---------------------------------------------------------- behavioural
    _q(
        "behavioral",
        "b",
        "teamwork",
        "Tell me about a time you worked in a team to finish something. What was your role and what was the outcome?",
        "clear situation|own role|concrete actions|result",
    ),
    _q(
        "behavioral",
        "b",
        "learning",
        "Describe a time you had to learn something new quickly. How did you go about it?",
        "context|learning approach|outcome|reflection",
    ),
    _q(
        "behavioral",
        "b",
        "responsibility",
        "Tell me about a time you made a mistake. What happened and what did you do next?",
        "ownership|corrective action|lesson learned",
    ),
    _q(
        "behavioral",
        "i",
        "conflict",
        "Describe a disagreement with a teammate. How did you handle it and what was the result?",
        "situation and stakes|actions to understand the other view|resolution|reflection",
    ),
    _q(
        "behavioral",
        "i",
        "pressure",
        "Tell me about a time you had a tight deadline and too much to do. What did you decide to do?",
        "prioritisation|communication|result|what you would change",
    ),
    _q(
        "behavioral",
        "i",
        "initiative",
        "Give an example of when you took initiative without being asked.",
        "why it mattered|actions|measurable or observable result",
    ),
    _q(
        "behavioral",
        "a",
        "leadership",
        "Tell me about a time you had to make a decision with incomplete information.",
        "risk assessment|how information was gathered|decision and outcome|reflection",
    ),
    _q(
        "behavioral",
        "a",
        "influence",
        "Describe a time you pushed back on a requirement or a plan. What was the result?",
        "reasoning with evidence|communication|compromise|outcome",
    ),
    _q(
        "behavioral",
        "a",
        "failure",
        "Tell me about a project that did not go as planned. What would you do differently?",
        "honest account|root causes|actions taken|concrete lessons",
    ),
    # ----------------------------------------------------------- technical
    _q(
        "technical",
        "b",
        "python",
        "What is the difference between a list and a tuple in Python, and when would you choose each?",
        "mutability|hashability|typical uses|performance note",
    ),
    _q(
        "technical",
        "i",
        "python",
        "Explain how Python handles exceptions. When would you define a custom exception, and what does a context manager give you?",
        "try/except/else/finally|specific exceptions|custom exception reasons|resource cleanup",
    ),
    _q(
        "technical",
        "a",
        "python",
        "How do generators and async functions differ from ordinary functions in Python, and what problems does each solve?",
        "lazy evaluation|memory use|event loop and awaiting|I/O-bound vs CPU-bound",
    ),
    _q(
        "technical",
        "b",
        "javascript",
        "What is the difference between let, const and var in JavaScript?",
        "scope|reassignment|hoisting",
    ),
    _q(
        "technical",
        "i",
        "javascript",
        "Explain how promises and async/await work in JavaScript, and how you handle errors with them.",
        "event loop|promise states|try/catch with await|parallel with Promise.all",
    ),
    _q(
        "technical",
        "a",
        "javascript",
        "How does the JavaScript event loop work, and what can block it in a Node.js service?",
        "call stack and queues|microtasks vs macrotasks|CPU-heavy work|offloading to workers",
    ),
    _q(
        "technical",
        "b",
        "java",
        "What is the difference between an interface and an abstract class in Java?",
        "multiple implementation|state and constructors|default methods",
    ),
    _q(
        "technical",
        "i",
        "java",
        "Explain how garbage collection works in Java and what can cause memory leaks.",
        "reachability|generations|lingering references|tools to diagnose",
    ),
    _q(
        "technical",
        "a",
        "java",
        "How would you design thread-safe access to shared state in a Java service?",
        "immutability|synchronisation and locks|concurrent collections|trade-offs",
    ),
    _q(
        "technical",
        "b",
        "sql",
        "What is the difference between INNER JOIN and LEFT JOIN? Give a small example.",
        "matching rows only|keeping unmatched left rows|NULLs",
    ),
    _q(
        "technical",
        "i",
        "sql",
        "What is an index, how does it speed up queries, and what does it cost?",
        "lookup structure|read speed|write and storage cost|choosing columns",
    ),
    _q(
        "technical",
        "a",
        "sql",
        "A query on a large table became slow. How would you investigate and fix it?",
        "execution plan|missing or unused indexes|query rewrite|statistics and data volume",
    ),
    _q(
        "technical",
        "b",
        "nosql",
        "When would you use a document database like MongoDB instead of a relational database?",
        "flexible schema|nested data|trade-offs on joins and consistency",
    ),
    _q(
        "technical",
        "i",
        "nosql",
        "What is a cache such as Redis used for, and how do you keep cached data from becoming stale?",
        "latency reduction|TTL|invalidation strategies|consistency trade-offs",
    ),
    _q(
        "technical",
        "a",
        "nosql",
        "Explain eventual consistency and a situation where it is acceptable and one where it is not.",
        "replication lag|CAP trade-offs|user-visible effects|compensating design",
    ),
    _q(
        "technical",
        "b",
        "rest",
        "What is a REST API, and what do the HTTP methods GET, POST, PUT and DELETE usually mean?",
        "resources|methods and idempotency|status codes",
    ),
    _q(
        "technical",
        "i",
        "rest",
        "How would you design pagination, error responses and authentication for a REST API?",
        "cursor or offset pagination|consistent error shape|token-based auth|status codes",
    ),
    _q(
        "technical",
        "a",
        "rest",
        "How do you evolve a public API without breaking existing clients?",
        "versioning|backwards-compatible changes|deprecation policy|contract tests",
    ),
    _q(
        "technical",
        "b",
        "git",
        "What do git commit, branch and merge do? How would you undo your last commit?",
        "snapshots|parallel work|combining history|reset vs revert",
    ),
    _q(
        "technical",
        "i",
        "git",
        "What is the difference between merge and rebase, and when would you avoid rebasing?",
        "history shape|rewriting commits|shared branches",
    ),
    _q(
        "technical",
        "a",
        "git",
        "How would you resolve a bad commit that is already on a shared main branch and has been deployed?",
        "revert not rewrite|communication|hotfix flow|post-incident follow-up",
    ),
    _q(
        "technical",
        "b",
        "containers",
        "What is Docker and what problem does a container solve compared with installing software directly?",
        "isolation|reproducibility|image vs container",
    ),
    _q(
        "technical",
        "i",
        "containers",
        "How would you keep a Docker image small and secure?",
        "slim base images|multi-stage builds|non-root user|pinned versions and no secrets",
    ),
    _q(
        "technical",
        "a",
        "containers",
        "How does Kubernetes keep an application available during a deployment or a node failure?",
        "replicas and scheduling|rolling updates|readiness and liveness probes|resource limits",
    ),
    _q(
        "technical",
        "b",
        "cloud",
        "What is the cloud, and what is the difference between IaaS, PaaS and SaaS?",
        "on-demand resources|levels of management|examples",
    ),
    _q(
        "technical",
        "i",
        "cloud",
        "How would you deploy a small web application to a cloud provider, and how would you keep secrets out of the code?",
        "compute and database choice|configuration and secret stores|least-privilege access|monitoring",
    ),
    _q(
        "technical",
        "a",
        "cloud",
        "How would you design for high availability and cost control of a service on a cloud platform?",
        "multi-zone redundancy|autoscaling|backups and recovery|cost monitoring",
    ),
    _q(
        "technical",
        "b",
        "testing",
        "Why do we write automated tests? What is the difference between a unit test and an integration test?",
        "regression safety|scope of each|speed",
    ),
    _q(
        "technical",
        "i",
        "testing",
        "How do you test code that depends on a database or an external API?",
        "test doubles|fixtures|isolation|contract or integration tests",
    ),
    _q(
        "technical",
        "a",
        "testing",
        "A test suite has become slow and flaky. How would you improve it?",
        "find nondeterminism|isolate shared state|parallelism|test pyramid balance",
    ),
    _q(
        "technical",
        "b",
        "security",
        "What is SQL injection and how do you prevent it?",
        "untrusted input in queries|parameterised queries|least privilege",
    ),
    _q(
        "technical",
        "i",
        "security",
        "How should passwords and API tokens be stored and transmitted in a web application?",
        "salted slow hashing|HTTPS|secret management|token expiry",
    ),
    _q(
        "technical",
        "a",
        "security",
        "Walk through how you would threat-model a new feature that accepts file uploads.",
        "assets and attackers|validation and size limits|storage isolation|scanning and logging",
    ),
    _q(
        "technical",
        "b",
        "ci_cd",
        "What is continuous integration and why do teams use it?",
        "automatic builds and tests|early feedback|shared main branch",
    ),
    _q(
        "technical",
        "i",
        "ci_cd",
        "What would you put in a CI/CD pipeline for a web service?",
        "lint and test|build artifact|security checks|staged deployment and rollback",
    ),
    _q(
        "technical",
        "a",
        "ci_cd",
        "How would you roll out a risky change with minimal user impact?",
        "feature flags|canary or blue-green|monitoring and rollback|database migration safety",
    ),
    _q(
        "technical",
        "b",
        "linux",
        "What are file permissions on Linux, and what does chmod 755 mean?",
        "owner/group/other|read write execute|numeric form",
    ),
    _q(
        "technical",
        "i",
        "linux",
        "A service on a Linux server stops responding. What commands and checks do you use first?",
        "process and logs|resource usage|network and ports|systematic narrowing",
    ),
    _q(
        "technical",
        "a",
        "linux",
        "How would you find out why a Linux server is slow under load?",
        "CPU, memory, disk and network triage|tools|bottleneck identification|fix and verify",
    ),
    _q(
        "technical",
        "b",
        "oop",
        "What are the four pillars of object-oriented programming? Explain one with an example.",
        "encapsulation|abstraction|inheritance|polymorphism",
    ),
    _q(
        "technical",
        "i",
        "oop",
        "What is the difference between inheritance and composition, and which do you prefer?",
        "is-a vs has-a|coupling|flexibility",
    ),
    _q(
        "technical",
        "a",
        "oop",
        "Explain the SOLID principles and give an example of violating one.",
        "single responsibility|open/closed|substitution|interface segregation|dependency inversion",
    ),
    _q(
        "technical",
        "b",
        "frontend",
        "What is the difference between HTML, CSS and JavaScript in a web page?",
        "structure|presentation|behaviour",
    ),
    _q(
        "technical",
        "i",
        "frontend",
        "How does state management work in a component-based frontend such as React, and when would you lift state up?",
        "local vs shared state|props flow|re-rendering|context or stores",
    ),
    _q(
        "technical",
        "a",
        "frontend",
        "How would you diagnose and fix poor performance in a large single-page application?",
        "profiling|bundle size and splitting|rendering costs|caching and lazy loading",
    ),
    _q(
        "technical",
        "b",
        "microservices",
        "What is a microservice, and how is it different from a monolith?",
        "independent deployment|service boundaries|added complexity",
    ),
    _q(
        "technical",
        "i",
        "microservices",
        "How do microservices communicate, and what happens when one of them is down?",
        "sync vs async|timeouts and retries|circuit breaker|idempotency",
    ),
    _q(
        "technical",
        "a",
        "microservices",
        "How would you handle a transaction that spans several services?",
        "avoid distributed transactions|saga pattern|eventual consistency|compensation",
    ),
    _q(
        "technical",
        "b",
        "general",
        "Explain what happens, at a high level, when you type a web address into a browser and press Enter.",
        "DNS|TCP/TLS|HTTP request and response|rendering",
    ),
    _q(
        "technical",
        "i",
        "general",
        "What is the difference between authentication and authorisation? Give an example of each in a web app.",
        "identity vs permission|login and tokens|roles and access checks",
    ),
    _q(
        "technical",
        "a",
        "general",
        "How do you decide between building something yourself and using an existing library or service?",
        "maintenance cost|fit and risk|licensing and security|exit strategy",
    ),
    # ----------------------------------------------------------- programming
    _q(
        "programming",
        "b",
        "algorithms",
        "Describe how you would check whether a string is a palindrome. What is the time complexity?",
        "two pointers or reversal|normalising input|O(n)",
    ),
    _q(
        "programming",
        "b",
        "algorithms",
        "How would you find the largest number in a list, and how would you also find the second largest?",
        "single pass|tracking two values|edge cases such as duplicates and short lists",
    ),
    _q(
        "programming",
        "b",
        "algorithms",
        "How would you count how many times each word appears in a piece of text?",
        "hash map|normalisation|complexity",
    ),
    _q(
        "programming",
        "i",
        "algorithms",
        "Given a list of numbers and a target, how would you find two numbers that add up to the target? Compare approaches.",
        "brute force O(n^2)|hash set O(n)|duplicates and no-solution cases",
    ),
    _q(
        "programming",
        "i",
        "algorithms",
        "How would you detect whether a linked list contains a cycle?",
        "visited set|fast and slow pointers|space trade-off",
    ),
    _q(
        "programming",
        "i",
        "algorithms",
        "How would you merge overlapping intervals such as [1,3], [2,6], [8,10]?",
        "sorting|single pass merge|O(n log n)",
    ),
    _q(
        "programming",
        "a",
        "algorithms",
        "How would you design an LRU cache with O(1) get and put?",
        "hash map plus doubly linked list|eviction order|edge cases",
    ),
    _q(
        "programming",
        "a",
        "algorithms",
        "How would you find the k most frequent items in a very large stream of data?",
        "counting|heap or bucket approach|memory limits and approximation",
    ),
    _q(
        "programming",
        "a",
        "algorithms",
        "Explain how you would approach a problem that asks for the number of ways to climb n stairs taking 1 or 2 steps. How can you optimise it?",
        "recursion|overlapping subproblems|dynamic programming|constant space",
    ),
    # ---------------------------------------------------------------- project
    _q(
        "project",
        "b",
        "projects",
        "Choose a project you have built or worked on. What does it do and what was your part in it?",
        "clear purpose|own contribution|technologies used",
    ),
    _q(
        "project",
        "i",
        "projects",
        "Choose a project you built. What was the hardest technical problem in it and how did you solve it?",
        "specific problem|options considered|solution and result",
    ),
    _q(
        "project",
        "i",
        "projects",
        "Choose a project you built. How did you test it and how would you know if it broke in production?",
        "testing approach|monitoring or logging|honest limitations",
    ),
    _q(
        "project",
        "a",
        "projects",
        "Choose a project you built. What design decision would you change if you started again, and why?",
        "reasoned trade-off|lessons learned|awareness of alternatives",
    ),
    _q(
        "project",
        "a",
        "projects",
        "Choose a project you built. How would it need to change to serve a hundred times more users?",
        "bottleneck identification|scaling approach|cost and complexity",
    ),
    # ---------------------------------------------------------- system design
    _q(
        "system_design",
        "b",
        "design",
        "How would you design a simple URL shortener? Describe the main parts.",
        "ID generation|storage|redirect flow|basic scale considerations",
    ),
    _q(
        "system_design",
        "b",
        "design",
        "How would you design a simple to-do list application with user accounts?",
        "data model|API|authentication|storage",
    ),
    _q(
        "system_design",
        "i",
        "design",
        "Design a service that sends notifications (email or push) to users. What are the key components and failure cases?",
        "queue|workers and retries|templates and preferences|idempotency and rate limits",
    ),
    _q(
        "system_design",
        "i",
        "design",
        "How would you design the backend for a chat application?",
        "real-time transport|message storage|delivery and ordering|scaling connections",
    ),
    _q(
        "system_design",
        "a",
        "design",
        "Design a rate limiter for a public API used by millions of clients.",
        "algorithms such as token bucket|shared state|failure behaviour|fairness and headers",
    ),
    _q(
        "system_design",
        "a",
        "design",
        "Design a news feed for a social platform. Where would you cache and where would you precompute?",
        "fan-out on write vs read|ranking|caching layers|data consistency trade-offs",
    ),
    _q(
        "system_design",
        "a",
        "design",
        "How would you design a file upload and processing pipeline that must be reliable and secure?",
        "direct uploads|validation and scanning|asynchronous processing|retries and observability",
    ),
]

QUESTION_BANK: tuple[BankQuestion, ...] = tuple(
    BankQuestion(
        id=f"{q.category[:3]}-{q.difficulty[0]}-{index:03d}",
        category=q.category,
        difficulty=q.difficulty,
        text=q.text,
        tags=q.tags,
        key_points=q.key_points,
    )
    for index, q in enumerate(_RAW)
)

_TAG_FOR_SKILL = {
    "python": "python", "fastapi": "python", "django": "python", "flask": "python",
    "pandas": "python", "pytest": "testing", "javascript": "javascript", "typescript": "javascript",
    "node.js": "javascript", "express.js": "javascript", "nestjs": "javascript",
    "react": "frontend", "next.js": "frontend", "vue": "frontend", "angular": "frontend",
    "html": "frontend", "css": "frontend", "tailwind css": "frontend", "redux": "frontend",
    "java": "java", "spring boot": "java", "kotlin": "java", "c#": "oop", ".net": "oop",
    "c++": "oop", "sql": "sql", "postgresql": "sql", "mysql": "sql", "sqlite": "sql",
    "sql server": "sql", "sqlalchemy": "sql", "mongodb": "nosql", "redis": "nosql",
    "dynamodb": "nosql", "cassandra": "nosql", "elasticsearch": "nosql",
    "rest apis": "rest", "graphql": "rest", "git": "git", "github actions": "ci_cd",
    "gitlab ci": "ci_cd", "jenkins": "ci_cd", "ci/cd": "ci_cd", "docker": "containers",
    "kubernetes": "containers", "aws": "cloud", "azure": "cloud", "gcp": "cloud",
    "terraform": "cloud", "linux": "linux", "bash": "linux", "unit testing": "testing",
    "jest": "testing", "test-driven development": "testing", "cypress": "testing",
    "selenium": "testing", "oauth": "security", "microservices": "microservices",
    "kafka": "microservices", "rabbitmq": "microservices",
    "object-oriented programming": "oop", "data structures and algorithms": "algorithms",
    "system design": "design", "devops": "ci_cd",
}  # fmt: skip


def tags_for_skills(skills: Iterable[str]) -> list[str]:
    """Bank tags for skill names, in order, without repeats (unknown skills are ignored)."""
    seen: dict[str, None] = {}
    for skill in skills:
        tag = _TAG_FOR_SKILL.get(squash(skill))
        if tag:
            seen.setdefault(tag)
    return list(seen)


def normalise(text: str) -> str:
    return " ".join("".join(c if c.isalnum() else " " for c in text.casefold()).split())


def _distance(question: BankQuestion, difficulty: str) -> int:
    return abs(_ORDER.index(question.difficulty) - _ORDER.index(difficulty))


def pick_for_category(
    category: str,
    difficulty: str,
    count: int,
    *,
    preferred_tags: list[str],
    exclude: set[str],
    rng: random.Random,
) -> list[BankQuestion]:
    """Up to ``count`` distinct questions of one category. Preferred tags (job skills, weak
    topics) are served round-robin so one skill does not take every slot; within a tag the
    closest difficulty wins, and ties are broken by the seeded generator so different
    sessions vary while each stays reproducible."""
    pool = [q for q in QUESTION_BANK if q.category == category and normalise(q.text) not in exclude]
    rng.shuffle(pool)
    pool.sort(key=lambda q: _distance(q, difficulty))
    queues: list[list[BankQuestion]] = [
        [q for q in pool if tag in q.tags] for tag in preferred_tags
    ]
    picked: list[BankQuestion] = []
    seen: set[str] = set()
    while len(picked) < count and any(queues):
        for queue in queues:
            while queue and queue[0].id in seen:
                queue.pop(0)
            if queue and len(picked) < count:
                question = queue.pop(0)
                seen.add(question.id)
                picked.append(question)
    for question in pool:
        if len(picked) >= count:
            break
        if question.id not in seen:
            seen.add(question.id)
            picked.append(question)
    return picked


def job_specific_prompts(duties: list[str], difficulty: str, count: int) -> list[tuple[str, str]]:
    """Generic scenario questions built from the job's own duties: ``(text, duty)``."""
    stems = {
        "beginner": "The posting lists this duty: \"{duty}\". How would you start working on it, and what would you want to learn first?",
        "intermediate": "The posting lists this duty: \"{duty}\". Describe how you would approach it end to end and what could go wrong.",
        "advanced": "The posting lists this duty: \"{duty}\". How would you plan, deliver and measure the success of it, and what trade-offs would you make?",
    }  # fmt: skip
    return [(stems[difficulty].format(duty=d[:160]), d) for d in duties[:count]]
