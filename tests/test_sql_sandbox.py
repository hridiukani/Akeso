"""SQL in the real sandbox: SQLite is available, and the runner and database are read-only.

Every test runs inside a real container (Docker marker), checking behaviour from the
sandbox user's point of view.
"""

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from fakes import make_sql_task
from akeso import sql_runner
from akeso.datasets import load_dataset
from akeso.environment import SUPPORT_DIR, EnvError
from akeso.grading import ChangeSet, Verdict, changes_from_files, grade
from akeso.sandbox import DockerSandbox
from akeso.tasks import load_task
from akeso.workspace import LocalWorkspace

DB = load_dataset("saas", Path("tasks/datasets")).build(11)
RUNNER = Path(sql_runner.__file__).read_bytes()
RUN = ["python", "-I", f"{SUPPORT_DIR}/run_query.py"]


@pytest.fixture
def sandbox(tmp_path: Path) -> Iterator[DockerSandbox]:
    (tmp_path / "solution.sql").write_text("SELECT name FROM plans ORDER BY plan_id LIMIT 2;\n", newline="\n")
    with DockerSandbox() as box:
        box.start(tmp_path, support_files={"run_query.py": RUNNER, "visible.db": DB})
        yield box


def run_query(box: DockerSandbox, *args: str) -> tuple[int | None, dict]:
    result = box.exec([*RUN, *args], timeout=60)
    return result.exit_code, json.loads(result.output)


def db_digest(box: DockerSandbox) -> str:
    return box.exec(["sha256sum", f"{SUPPORT_DIR}/visible.db"], timeout=30).output.split()[0]


@pytest.mark.docker
def test_sqlite_is_in_the_image(sandbox: DockerSandbox) -> None:
    result = sandbox.exec(["python", "-c", "import sqlite3; print(sqlite3.sqlite_version)"], timeout=30)

    assert result.exit_code == 0 and result.output.strip().startswith("3.")


@pytest.mark.docker
def test_runner_answers_from_the_visible_database(sandbox: DockerSandbox) -> None:
    code, out = run_query(sandbox, "--file", "solution.sql")

    assert code == 0 and out["rows"] == [["Starter"], ["Pro"]]
    code, out = run_query(sandbox, "--sql", "SELECT count(*) FROM payments")  # --db defaults to visible.db
    assert code == 0 and out["rows"][0][0] > 1000


@pytest.mark.docker
def test_support_files_are_root_owned_and_read_only(sandbox: DockerSandbox) -> None:
    listing = sandbox.exec(["stat", "-c", "%U %a %n", SUPPORT_DIR, f"{SUPPORT_DIR}/run_query.py", f"{SUPPORT_DIR}/visible.db"], timeout=30)

    assert listing.output.split("\n")[:3] == [f"root 755 {SUPPORT_DIR}", f"root 444 {SUPPORT_DIR}/run_query.py", f"root 444 {SUPPORT_DIR}/visible.db"]
    assert hashlib.sha256(DB).hexdigest() == db_digest(sandbox)


@pytest.mark.docker
@pytest.mark.parametrize("command", [
    f"echo 'print(1)' > {SUPPORT_DIR}/run_query.py",
    f"rm -f {SUPPORT_DIR}/visible.db",
    f"mv {SUPPORT_DIR}/visible.db /tmp/x.db",
    f"chmod 666 {SUPPORT_DIR}/visible.db",
    f"touch {SUPPORT_DIR}/extra.py",
    f"cp /dev/null {SUPPORT_DIR}/visible.db",
])
def test_sandbox_user_cannot_change_the_judge(sandbox: DockerSandbox, command: str) -> None:
    before = db_digest(sandbox)

    result = sandbox.exec(command, timeout=30)

    assert result.exit_code != 0
    assert db_digest(sandbox) == before
    assert sandbox.exec(["ls", SUPPORT_DIR], timeout=30).output.split() == ["run_query.py", "visible.db"]
    assert sandbox.exec(["sha256sum", f"{SUPPORT_DIR}/run_query.py"], timeout=30).output.split()[0] == hashlib.sha256(RUNNER).hexdigest()


@pytest.mark.docker
@pytest.mark.parametrize("sql", ["DELETE FROM payments", "UPDATE plans SET price = 0", "DROP TABLE plans",
                                 "ATTACH DATABASE '/tmp/x.db' AS x", "VACUUM INTO '/tmp/copy.db'"])
def test_runner_blocks_modifications_inside_the_sandbox(sandbox: DockerSandbox, sql: str) -> None:
    before = db_digest(sandbox)

    code, out = run_query(sandbox, "--sql", sql)

    assert code == 1 and "read-only" in out["error"]
    assert db_digest(sandbox) == before


@pytest.mark.docker
def test_writing_the_database_directly_fails_too(sandbox: DockerSandbox) -> None:
    # Bypassing the runner with Python's own sqlite3 still can't change the file.
    script = f"import sqlite3; c = sqlite3.connect('{SUPPORT_DIR}/visible.db'); c.execute('DELETE FROM payments'); c.commit()"
    before = db_digest(sandbox)

    result = sandbox.exec(["python", "-c", script], timeout=30)

    assert result.exit_code != 0 and "readonly" in result.output.lower().replace("-", "")
    assert db_digest(sandbox) == before


@pytest.mark.docker
def test_support_files_are_not_part_of_the_task_files(sandbox: DockerSandbox) -> None:
    assert sandbox.list_files() == ["solution.sql"]


def test_local_workspace_refuses_support_files(tmp_path: Path) -> None:
    with LocalWorkspace() as workspace, pytest.raises(EnvError, match="require the Docker sandbox"):
        workspace.start(tmp_path, support_files={"visible.db": DB})


@pytest.mark.docker
def test_grading_a_sql_task_in_docker(tmp_path: Path) -> None:
    gold = "SELECT country, count(*) FROM customers GROUP BY country;\n"
    task = load_task(make_sql_task(tmp_path / "tasks", "SELECT country, count(*) FROM customers WHERE country IS NOT NULL GROUP BY country;\n", gold))

    broken = grade(task, ChangeSet(), DockerSandbox)
    fixed = grade(task, changes_from_files(task, {"solution.sql": gold.replace("count(*)", "count(customer_id)")}), DockerSandbox)

    assert broken.verdict is Verdict.FAILED and not broken.visible_passed
    assert fixed.verdict is Verdict.PASSED and fixed.visible_passed and fixed.hidden_passed
