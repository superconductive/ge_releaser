import datetime as dt
import enum
import re
from typing import Dict, List, Tuple

from github.Organization import Organization
from github.PullRequest import PullRequest

from ge_releaser.constants import TEAMS


class ChangelogCategory(enum.Enum):
    BREAKING = "BREAKING"
    FEATURE = "FEATURE"
    BUGFIX = "BUGFIX"
    DOCS = "DOCS"
    MAINTENANCE = "MAINTENANCE"


class ChangelogCommit:
    def __init__(self, pr: PullRequest, github_org: Organization) -> None:

        teams: str
        with open(TEAMS) as f:
            teams = f.read().strip()

        if pr.title[0] == "[":
            try:
                type_, self.desc = re.match(r"\[([a-zA-Z]+)\] ?(.*)", pr.title).group(
                    1, 2
                )
                type_ = type_.upper()
                self.pr_type = (
                    ChangelogCategory[type_]
                    if type_ in ChangelogCategory.__members__
                    else ChangelogCategory.MAINTENANCE
                )
            except AttributeError:
                print(f"Couldn't parse PR title: {pr.title}")
                return
        else:
            self.pr_type = ChangelogCategory.MAINTENANCE
            self.desc = pr.title
        self.number = pr.number
        self.merge_timestamp = pr.merged_at
        self.attribution = (
            f" (thanks @{pr.user.login})"
            if pr.user.login not in teams
            else ""
        )

    def sort_key(self) -> Tuple[int, dt.datetime]:
        categories: Dict[ChangelogCategory, int] = {
            c: i + 1 for i, c in enumerate(ChangelogCategory)
        }
        return categories[self.pr_type], self.merge_timestamp

    def __str__(self) -> str:
        return (
            f"* [{self.pr_type.value}] {self.desc} (#{self.number}){self.attribution}"
        )


class ChangelogEntry:
    def __init__(
        self, github_org: Organization, pull_requests: List[PullRequest]
    ) -> None:
        changelog_commits: List[ChangelogCommit] = []
        for pr in pull_requests:
            changelog_commit: ChangelogCommit = ChangelogCommit(pr, github_org)
            changelog_commits.append(changelog_commit)

        changelog_commits.sort(key=ChangelogCommit.sort_key)
        self.commits = changelog_commits

    def write(
        self,
        outfile: str,
        current_version: str,
        release_version: str,
    ) -> None:
        with open(outfile, "r") as f:
            contents: List[str] = f.readlines()

        insertion_point: int = 0
        for i, line in enumerate(contents):
            if current_version in line:
                insertion_point = i - 1

        assert (
            insertion_point > 0
        ), "Could not find appropriate insertion point for new changelog entry"

        if outfile.endswith(".md"):
            contents[insertion_point:insertion_point] = self._render_to_md(
                release_version
            )
        elif outfile.endswith(".rst"):
            contents[insertion_point:insertion_point] = self._render_to_rst(
                release_version
            )
        else:
            raise Exception()

        with open(outfile, "w") as f:
            f.writelines(contents)

    def _render_to_md(self, release_version: str) -> List[str]:
        rendered: List[str] = []
        title: str = f"\n### {release_version}\n"
        rendered.append(title)
        contents: List[str] = self._render_contents()
        rendered.extend(contents)
        return rendered

    def _render_to_rst(self, release_version: str) -> List[str]:
        rendered: List[str] = []
        title: str = f"\n{release_version}\n"
        rendered.append(title)
        divider: str = "-----------------\n"
        rendered.append(divider)
        contents: List[str] = self._render_contents()
        rendered.extend(contents)
        return rendered

    def _render_contents(self) -> List[str]:
        rendered: List[str] = []
        for commit in self.commits:
            rendered.append(f"{commit}\n")

        return rendered
