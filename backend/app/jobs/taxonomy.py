"""A small, explicit vocabulary of technologies, soft skills, certifications and domains.

It is used to *recognise* things that a job description (or a candidate's evidence)
literally says, and to map spelling variants to one canonical name. It never infers
that one technology implies another (knowing React does not imply JavaScript here).

Aliases beginning with ``cs:`` are case-sensitive (e.g. ``cs:REST`` must not match the
word "rest"). ``exact`` aliases are only used when a whole list item equals them (a
CV skills list containing just ``Go`` or ``C``); they are never searched for in free
text because they are ordinary words or letters there.
"""

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

SkillKind = Literal[
    "language", "framework", "library", "tool", "database", "cloud", "concept", "soft"
]


@dataclass(frozen=True)
class Entry:
    name: str
    kind: SkillKind
    aliases: tuple[str, ...] = ()
    exact: tuple[str, ...] = ()


def _e(name: str, kind: SkillKind, aliases: str = "", exact: str = "") -> Entry:
    return Entry(
        name,
        kind,
        tuple(a.strip() for a in aliases.split("|") if a.strip()),
        tuple(a.strip() for a in exact.split("|") if a.strip()),
    )


TECHNICAL: tuple[Entry, ...] = (
    # languages
    _e("Python", "language", "python3", "py"),
    _e("Java", "language"),
    _e("JavaScript", "language", "ecmascript", "js"),
    _e("TypeScript", "language", "", "ts"),
    _e("C++", "language", "cpp"),
    _e("C#", "language", "csharp"),
    _e("C", "language", "", "c"),
    _e("Go", "language", "golang", "go"),
    _e("Rust", "language"),
    _e("Ruby", "language"),
    _e("PHP", "language"),
    _e("Kotlin", "language"),
    _e("Swift", "language", "cs:Swift", "swift"),
    _e("Scala", "language"),
    _e("R", "language", "rstudio", "r"),
    _e("SQL", "language", "t-sql|pl/sql"),
    _e("Bash", "language", "shell scripting|bash scripting"),
    _e("HTML", "language", "html5"),
    _e("CSS", "language", "css3"),
    _e("Dart", "language"),
    # frameworks
    _e("FastAPI", "framework", "fast api"),
    _e("Django", "framework"),
    _e("Flask", "framework"),
    _e("Spring Boot", "framework", "springboot|spring framework"),
    _e("React", "framework", "reactjs|react.js|cs:React", "react"),
    _e("React Native", "framework"),
    _e("Next.js", "framework", "nextjs"),
    _e("Vue", "framework", "vue.js|vuejs"),
    _e("Angular", "framework", "angularjs"),
    _e("Svelte", "framework"),
    _e("Node.js", "framework", "nodejs"),
    _e("Express.js", "framework", "expressjs"),
    _e("NestJS", "framework", "nest.js"),
    _e(".NET", "framework", "dotnet|asp.net|.net core"),
    _e("Laravel", "framework"),
    _e("Ruby on Rails", "framework", "cs:Rails"),
    _e("Flutter", "framework"),
    _e("Tailwind CSS", "framework", "tailwind|tailwindcss"),
    # libraries
    _e("pandas", "library"),
    _e("NumPy", "library"),
    _e("scikit-learn", "library", "sklearn|scikit learn"),
    _e("TensorFlow", "library"),
    _e("PyTorch", "library", "pytorch"),
    _e("LangChain", "library"),
    _e("LangGraph", "library"),
    _e("Hugging Face", "library", "huggingface|transformers library"),
    _e("SQLAlchemy", "library"),
    _e("Pydantic", "library"),
    _e("Celery", "library"),
    _e("Redux", "library"),
    _e("Pytest", "library"),
    _e("Jest", "library"),
    # databases
    _e("PostgreSQL", "database", "postgres|postgresql|psql"),
    _e("MySQL", "database"),
    _e("MongoDB", "database", "mongo db"),
    _e("Redis", "database"),
    _e("SQLite", "database"),
    _e("Elasticsearch", "database", "elastic search|opensearch"),
    _e("DynamoDB", "database"),
    _e("Cassandra", "database"),
    _e("SQL Server", "database", "mssql|ms sql"),
    _e("pgvector", "database"),
    _e("Snowflake", "database"),
    # cloud
    _e("AWS", "cloud", "amazon web services"),
    _e("Azure", "cloud", "microsoft azure"),
    _e("GCP", "cloud", "google cloud|google cloud platform"),
    # tools
    _e("Docker", "tool", "dockerfile|docker compose|docker-compose"),
    _e("Kubernetes", "tool", "k8s"),
    _e("Git", "tool"),
    _e("GitHub Actions", "tool"),
    _e("GitLab CI", "tool", "gitlab ci/cd"),
    _e("Jenkins", "tool"),
    _e("Terraform", "tool"),
    _e("Ansible", "tool"),
    _e("Linux", "tool", "unix"),
    _e("Nginx", "tool"),
    _e("RabbitMQ", "tool"),
    _e("Kafka", "tool", "apache kafka"),
    _e("Prometheus", "tool"),
    _e("Grafana", "tool"),
    _e("Airflow", "tool", "apache airflow"),
    _e("Spark", "tool", "apache spark|pyspark|cs:Spark", "spark"),
    _e("Selenium", "tool"),
    _e("Cypress", "tool"),
    _e("Postman", "tool"),
    _e("Figma", "tool"),
    _e("Jira", "tool"),
    _e("OpenAI API", "tool", "openai"),
    # concepts
    _e("REST APIs", "concept", "restful|rest api|rest apis|cs:REST"),
    _e("GraphQL", "concept"),
    _e("Microservices", "concept", "microservice"),
    _e("CI/CD", "concept", "ci/cd|continuous integration|continuous delivery|cicd"),
    _e("Test-Driven Development", "concept", "tdd|test driven development"),
    _e("Unit Testing", "concept", "unit tests|unit testing|automated testing"),
    _e("Agile", "concept", "scrum|kanban"),
    _e("DevOps", "concept"),
    _e("Machine Learning", "concept", "cs:ML"),
    _e("Deep Learning", "concept"),
    _e("NLP", "concept", "natural language processing"),
    _e("Computer Vision", "concept"),
    _e("LLMs", "concept", "llm|large language model|large language models|generative ai"),
    _e("RAG", "concept", "retrieval-augmented generation|retrieval augmented generation|cs:RAG"),
    _e("Data Structures and Algorithms", "concept", "data structures|algorithms"),
    _e("Object-Oriented Programming", "concept", "oop|object-oriented|object oriented"),
    _e("System Design", "concept", "distributed systems|systems design"),
    _e("WebSockets", "concept", "websocket"),
    _e("OAuth", "concept", "oauth2|oauth 2.0"),
    _e("Data Analysis", "concept", "data analytics"),
)

SOFT: tuple[Entry, ...] = (
    _e(
        "Communication",
        "soft",
        "communication skills|communicate effectively|written communication",
    ),
    _e("Teamwork", "soft", "team player|collaboration|collaborate|collaborative|work in a team"),
    _e("Leadership", "soft", "lead a team|team leadership|leading teams"),
    _e("Problem Solving", "soft", "problem-solving|problem solver|analytical skills"),
    _e("Critical Thinking", "soft"),
    _e("Time Management", "soft", "prioritization|prioritisation|meet deadlines"),
    _e("Adaptability", "soft", "adaptable|flexibility|learn quickly|fast learner"),
    _e("Mentoring", "soft", "mentor|mentorship|coaching"),
    _e("Ownership", "soft", "take ownership|self-motivated|self-starter|proactive"),
    _e("Attention to Detail", "soft", "detail-oriented|detail oriented"),
    _e("Stakeholder Management", "soft", "stakeholder communication|stakeholders"),
    _e("Presentation Skills", "soft", "public speaking|presentation skills"),
    _e("Creativity", "soft", "creative thinking"),
)

DOMAINS: tuple[Entry, ...] = (
    _e("Fintech", "concept", "financial services|banking|payments|fintech"),
    _e("Healthcare", "concept", "healthtech|health care|healthcare"),
    _e("E-commerce", "concept", "ecommerce|e-commerce|online retail"),
    _e("Education Technology", "concept", "edtech|education technology"),
    _e("Cybersecurity", "concept", "information security|infosec|cybersecurity|cyber security"),
    _e("Gaming", "concept", "game development|video games"),
    _e("Telecommunications", "concept", "telecom|telecommunications"),
    _e("Logistics", "concept", "supply chain|logistics"),
    _e("Artificial Intelligence", "concept", "ai/ml|artificial intelligence"),
    _e("Blockchain", "concept", "web3|blockchain|smart contracts"),
    _e("IoT", "concept", "internet of things|iot|embedded systems"),
    _e("Data Privacy", "concept", "gdpr|data protection|data privacy"),
)

CERTIFICATIONS: tuple[Entry, ...] = (
    _e("AWS Certified Solutions Architect", "concept", "aws solutions architect"),
    _e("AWS Certified Developer", "concept", "aws developer associate"),
    _e("AWS Certified Cloud Practitioner", "concept", "aws cloud practitioner"),
    _e("Microsoft Azure Fundamentals", "concept", "az-900|azure fundamentals"),
    _e("Certified Kubernetes Administrator", "concept", "cka"),
    _e("Certified Kubernetes Application Developer", "concept", "ckad"),
    _e("Project Management Professional", "concept", "pmp"),
    _e("Certified ScrumMaster", "concept", "csm|certified scrum master|certified scrummaster"),
    _e("CISSP", "concept"),
    _e("CompTIA Security+", "concept", "security+"),
    _e("Google Professional Cloud Architect", "concept"),
    _e("HashiCorp Certified Terraform Associate", "concept", "terraform associate"),
)

_SQUASH = re.compile(r"\s+")


def squash(text: str) -> str:
    return _SQUASH.sub(" ", text).strip().casefold()


def _is_cs(alias: str) -> bool:
    return alias.startswith("cs:")


def _strip_cs(alias: str) -> str:
    return alias[3:] if _is_cs(alias) else alias


@lru_cache(maxsize=1)
def _lookup() -> dict[str, Entry]:
    """Every searchable alias (squashed) and exact alias -> entry, for list-item lookup."""
    table: dict[str, Entry] = {}
    for entry in TECHNICAL + SOFT:
        for alias in (entry.name, *entry.aliases, *entry.exact):
            table.setdefault(squash(_strip_cs(alias)), entry)
    return table


def lookup(text: str) -> Entry | None:
    """The taxonomy entry a whole skill label refers to (``"Postgres"`` -> PostgreSQL)."""
    return _lookup().get(squash(text))


def canonical_key(text: str) -> str:
    """Stable comparison key: the canonical name if known, else the squashed text."""
    entry = lookup(text)
    return squash(entry.name) if entry else squash(text)


def aliases_for(name: str) -> list[str]:
    """Strings that count as a literal mention of ``name`` in free text."""
    entry = lookup(name)
    if entry is None:
        return [name]
    ambiguous = entry.name.casefold() in {x.casefold() for x in entry.exact}
    return [*([] if ambiguous else [entry.name]), *(_strip_cs(a) for a in entry.aliases)]


def _compile(
    entries: tuple[Entry, ...],
) -> tuple[re.Pattern[str], re.Pattern[str], dict[str, Entry]]:
    insensitive: list[str] = []
    sensitive: list[str] = []
    owners: dict[str, Entry] = {}
    for entry in entries:
        # A name that is also an ordinary word ("Go", "Spark", "React") is only searched
        # for through its explicit aliases, never as free text.
        ambiguous = entry.name.casefold() in {x.casefold() for x in entry.exact}
        for alias in (*(() if ambiguous else (entry.name,)), *entry.aliases):
            text = _strip_cs(alias)
            owners[text if _is_cs(alias) else text.casefold()] = entry
            (sensitive if _is_cs(alias) else insensitive).append(text)

    def build(words: list[str], flags: int) -> re.Pattern[str]:
        ordered = sorted(set(words), key=len, reverse=True) or ["(?!)"]
        body = "|".join(re.escape(w) if w != "(?!)" else w for w in ordered)
        return re.compile(rf"(?<![A-Za-z0-9])(?:{body})(?![A-Za-z0-9])", flags)

    return build(insensitive, re.IGNORECASE), build(sensitive, 0), owners


@lru_cache(maxsize=8)
def _matcher(
    which: Literal["technical", "soft", "domain", "certification"],
) -> tuple[re.Pattern[str], re.Pattern[str], dict[str, Entry]]:
    entries = {
        "technical": TECHNICAL,
        "soft": SOFT,
        "domain": DOMAINS,
        "certification": CERTIFICATIONS,
    }[which]
    return _compile(entries)


def find_matches(
    text: str, which: Literal["technical", "soft", "domain", "certification"]
) -> list[tuple[int, int, Entry]]:
    """Every literal mention as ``(start, end, entry)``, in order of appearance."""
    insensitive, sensitive, owners = _matcher(which)
    hits: list[tuple[int, int, Entry]] = []
    for match in insensitive.finditer(text):
        hits.append((match.start(), match.end(), owners[match.group(0).casefold()]))
    for match in sensitive.finditer(text):
        entry = owners.get(match.group(0))
        if entry is not None:
            hits.append((match.start(), match.end(), entry))
    return sorted(hits, key=lambda hit: hit[0])


def find_entries(
    text: str, which: Literal["technical", "soft", "domain", "certification"]
) -> list[Entry]:
    """Entries literally mentioned in ``text``, in order of first appearance, no repeats."""
    seen: set[str] = set()
    ordered: list[Entry] = []
    for _, _, entry in find_matches(text, which):
        if entry.name not in seen:
            seen.add(entry.name)
            ordered.append(entry)
    return ordered
