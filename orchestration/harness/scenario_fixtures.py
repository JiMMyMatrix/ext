from __future__ import annotations

import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCENARIO_FIXTURE_ROOT = (
	Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "scenarios"
)


def list_scenarios() -> list[str]:
	return sorted(
		entry.name
		for entry in SCENARIO_FIXTURE_ROOT.iterdir()
		if entry.is_dir()
	)


def scenario_dir(name: str) -> Path:
	path = SCENARIO_FIXTURE_ROOT / name
	if path.is_dir():
		return path
	raise ValueError(
		f"unknown scenario fixture: {name}. Available scenarios: {', '.join(list_scenarios())}"
	)


def _copy_entry(source: Path, target: Path) -> None:
	if source.is_dir():
		shutil.copytree(source, target, dirs_exist_ok=True)
		return
	shutil.copy2(source, target)


def materialize_scenario(
	name: str,
	target_root: str | Path,
	*,
	replace_existing: bool = False,
) -> Path:
	source_root = scenario_dir(name)
	target_path = Path(target_root).resolve()
	target_path.mkdir(parents=True, exist_ok=True)

	for source_entry in source_root.iterdir():
		target_entry = target_path / source_entry.name
		if replace_existing and target_entry.exists():
			if target_entry.is_dir():
				shutil.rmtree(target_entry)
			else:
				target_entry.unlink()
		_copy_entry(source_entry, target_entry)

	return target_path


@contextmanager
def temporary_scenario_repo(name: str) -> Iterator[Path]:
	with tempfile.TemporaryDirectory() as tmp_dir:
		repo_root = materialize_scenario(name, tmp_dir)
		yield repo_root
