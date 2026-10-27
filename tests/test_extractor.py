import pytest

from pipeline.skills import get_extractor


def skills(text: str) -> set[str]:
    return {s.name for s in get_extractor().extract(text)}


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Strong SQL and Python skills", {"SQL", "Python"}),
        ("Experience with postgres and power bi", {"PostgreSQL", "SQL", "Power BI"}),
        ("We use ReactJS with Node.js", {"React", "Node.js", "JavaScript"}),
        ("Proficient in C++ and C#", {"C++", "C#"}),
        ("Docker, k8s, Terraform", {"Docker", "Kubernetes", "Terraform"}),
        ("Build ETL pipelines in Apache Airflow", {"ETL", "Airflow"}),
    ],
)
def test_unambiguous_skills(text, expected):
    assert skills(text) == expected


@pytest.mark.parametrize(
    "text, skill",
    [
        ("Knowledge of R programming", "R"),
        ("Tools: Python, R, SQL", "R"),
        ("Services written in Go and Rust", "Go"),
        ("Experience with TypeScript and Go on AWS", "Go"),
        ("Advanced Excel required", "Excel"),
        ("Comfortable with SQL and Excel", "Excel"),
        ("Big data with Spark and Kafka", "Spark"),
        ("iOS development in Swift", "Swift"),
        ("C programming for embedded systems", "C"),
    ],
)
def test_ambiguous_skills_in_tech_context(text, skill):
    assert skill in skills(text)


@pytest.mark.parametrize(
    "text, skill",
    [
        ("You will excel in a fast-paced environment", "Excel"),
        ("Excel in a fast-paced environment", "Excel"),
        ("Go above and beyond for our customers", "Go"),
        ("A real go-getter", "Go"),
        ("Spark conversations with customers", "Spark"),
        ("Swift response to client requests", "Swift"),
        ("Class C driver's licence required", "C"),
        ("Work closely with R&D", "R"),
        ("Plan A, B or C for the project", "C"),
    ],
)
def test_ambiguous_words_in_plain_english_are_ignored(text, skill):
    assert skill not in skills(text)


def test_cpp_is_not_also_counted_as_c():
    assert skills("Modern C++ with Python bindings") == {"C++", "Python"}


def test_empty_text():
    assert get_extractor().extract("") == []


def test_version_changes_when_taxonomy_changes(tmp_path):
    from pipeline.skills.extractor import TAXONOMY_PATH, SkillExtractor

    copy = tmp_path / "skills.yaml"
    copy.write_text(TAXONOMY_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    v1 = SkillExtractor(copy).version
    copy.write_text(copy.read_text(encoding="utf-8") + "\n- {name: Zig, category: language}\n",
                    encoding="utf-8")
    assert SkillExtractor(copy).version != v1
