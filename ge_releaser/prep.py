import datetime as dt
import json
import logging
import os
from typing import Dict, List, Optional, Tuple, cast

import click
import dateutil.parser
import git
from github.Organization import Organization
from github.PaginatedList import PaginatedList
from github.PullRequest import PullRequest
from github.Repository import Repository
from packaging import version

from ge_releaser.changelog import ChangelogEntry
from ge_releaser.cli import GitEnvironment
from ge_releaser.constants import (
    CHANGELOG_MD,
    CHANGELOG_RST,
    DEPLOYMENT_VERSION,
    PULL_REQUESTS,
    GETTING_STARTED_VERSION,
)
from ge_releaser.util import checkout_and_update_develop, parse_deployment_version_file


def prep(
    env: GitEnvironment, version_number: Optional[str], file: Optional[str]
) -> None:
    click.secho("[prep]", bold=True, fg="blue")

    version_number = _determine_version_number(version_number, file)

    checkout_and_update_develop(env.git_repo)
    current_version, release_version = _parse_versions(version_number)

    release_branch: str = _create_and_checkout_release_branch(
        env.git_repo, release_version
    )
    click.secho(" * Created a release branch (1/6)", fg="yellow")

    _update_deployment_version_file(release_version)
    click.secho(" * Updated deployment version file (2/6)", fg="yellow")

    _update_getting_started_snippet(release_version)
    click.secho(" * Updated version in tutorial snippet (3/6)", fg="yellow")

    _update_changelogs(
        env.github_org, env.github_repo, current_version, release_version
    )
    click.secho(" * Updated changelogs (4/6)", fg="yellow")

    _commit_changes(env.git_repo)
    click.secho(" * Committed changes (5/6)", fg="yellow")

    url: str = _create_pr(
        env.git_repo, env.github_repo, release_branch, release_version
    )
    click.secho(" * Opened prep PR (6/6)", fg="yellow")

    click.secho(
        f"\n[SUCCESS] Please review, approve, and merge PR before continuing to `tag` command",
        fg="green",
    )
    click.echo(f"Link to PR: {url}")


def _determine_version_number(
    version_number: Optional[str], file: Optional[str]
) -> str:
    if version_number is not None:
        return version_number

    version_number = _parse_release_schedule_file(version_number, file)
    return version_number


def _parse_release_schedule_file(
    version_number: Optional[str], file: Optional[str]
) -> str:
    assert file is not None  # Invariant that we have either the version or the file
    with open(file) as f:
        contents: Dict[str, str] = json.loads(f.read().strip())

    today = dt.datetime.today()
    for date, version in contents.items():
        parsed_date: dt.datetime = dateutil.parser.parse(date)
        if today.date() == parsed_date.date():
            version_number = version
            break

    if version_number is None:
        raise ValueError("No suitable scheduled release found!")

    # Ensure we remove the entry from the scheduler file
    with open(file, "w") as f:
        date_to_remove = today.strftime("%Y-%m-%d")
        contents.pop(date_to_remove)
        f.write(json.dumps(contents, indent=4, sort_keys=True))

    return version_number


def _parse_versions(version_number: str) -> Tuple[str, str]:
    current_version: version.Version = parse_deployment_version_file()
    release_version: version.Version = cast(
        version.Version, version.parse(version_number)
    )
    assert release_version > current_version, "Version provided to command is not valid"

    return str(current_version), str(release_version)


def _create_and_checkout_release_branch(
    git_repo: git.Repo, release_version: str
) -> str:
    branch_name: str = f"release-{release_version}"
    git_repo.git.checkout("HEAD", b=branch_name)
    return branch_name


def _update_deployment_version_file(release_version: str) -> None:
    with open(DEPLOYMENT_VERSION, "w") as f:
        f.write(f"{release_version.strip()}\n")


def _update_getting_started_snippet(release_version: str) -> None:
    """Creates a `.mdx` file containing the expected output of the CLI command `great_expectations --version` in a
     markdown codeblock.

    If the .mdx file already exists, it is overwritten when the script runs.
    """
    with open(GETTING_STARTED_VERSION, "w") as snippet_file:
        lines = ("```\n", f"great_expectations, version {release_version}", "\n```")
        snippet_file.writelines(lines)


def _update_changelogs(
    github_org: Organization,
    github_repo: Repository,
    current_version: str,
    release_version: str,
) -> None:
    relevant_prs: List[PullRequest] = _collect_prs_since_last_release(
        github_repo, current_version
    )

    changelog_entry: ChangelogEntry = ChangelogEntry(github_org, relevant_prs)

    changelog_entry.write(CHANGELOG_MD, current_version, release_version)
    changelog_entry.write(CHANGELOG_RST, current_version, release_version)


def _collect_prs_since_last_release(
    github_repo: Repository,
    current_version: str,
) -> List[PullRequest]:
    last_release: dt.datetime = github_repo.get_release(current_version).created_at
    merged_prs: PaginatedList[PullRequest] = github_repo.get_pulls(
        base="develop", state="closed", sort="updated", direction="desc"
    )
    recent_prs: List[PullRequest] = []

    # To ensure we don't accidently exit early, we set a threshold and wait to see a few old PRs before completing iteration
    counter: int = 0
    threshold: int = 5

    for pr in merged_prs:
        if counter >= threshold:
            break
        if not pr.merged:
            continue

        logging.info(pr, pr.merged_at, counter)
        if pr.merged_at < last_release:
            counter += 1
        if pr.merged_at > last_release:
            recent_prs.append(pr)

    return recent_prs


def _commit_changes(git_repo: git.Repo) -> None:
    git_repo.git.add(".")
    # Bypass pre-commit (if running locally on a dev env)
    git_repo.git.commit("-m", "release prep", "--no-verify")


def _create_pr(
    git_repo: git.Repo,
    github_repo: Repository,
    release_branch: str,
    release_version: str,
) -> str:
    git_repo.git.push("--set-upstream", "origin", release_branch)

    pr: PullRequest = github_repo.create_pull(
        title=f"[RELEASE] {release_version}",
        body=f"release prep for {release_version}",
        head=release_branch,
        base="develop",
    )

    return os.path.join(PULL_REQUESTS, str(pr.number))
