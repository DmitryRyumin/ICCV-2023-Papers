# The code is importing necessary modules for the script to work:
import os
import shutil
import re
import json
from pathlib import Path
from bs4 import BeautifulSoup
import markdown2
from prettytable import PrettyTable
from github import Github, InputGitTreeElement, InputGitAuthor
from urllib.parse import urlsplit, urlunsplit, urlparse, urlunparse, parse_qs


class FileUpdate:
    def __init__(self, path, content):
        self.path = path
        self.content = content


repo_full_name = os.getenv("GITHUB_REPOSITORY")
if repo_full_name:
    owner, repo_name = repo_full_name.split("/")
else:
    owner, repo_name = None, None


class Config:
    GITHUB_TOKEN = os.getenv("INPUT_PAPER_TOKEN") or os.getenv("PAPER_TOKEN")
    GITHUB_WORKSPACE = os.getenv("GITHUB_WORKSPACE", "/github/workspace")
    MARKDOWN_DIRECTORY = "sections"
    OUTPUT_DIRECTORY = "json_data"
    MARKDOWN_DIRECTORY_LOCAL = Path("./sections").resolve()
    OUTPUT_DIRECTORY_LOCAL = Path("./local_json_data").resolve()
    REPO_OWNER = owner
    REPO_NAME = repo_name
    COMMIT_MESSAGE = "Update files"


def print_colored_status(status):
    color_codes = {"No table": 91, "Success": 92, "Error": 91}
    color_code = color_codes.get(status, 0)  # Default to red color if not found
    return f"\033[{color_code}m{status}\033[0m" if color_code else status


def print_colored_count(count, label):
    color_code = 91  # Default to red color for No table and Errors

    if label == "Success" and count > 0:
        color_code = 92  # Green color for Success
    elif label in ["No table", "Errors"] and count == 0:
        color_code = 92  # Green color for No table or Errors when count is 0

    return f"\033[{color_code}m{count}\033[0m"


def clear_directory(directory):
    path = Path(directory)
    for item in path.iterdir():
        try:
            if item.is_file():
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item)
        except Exception as e:
            print(f"Error while deleting {item}: {e}")


def get_github_repository():
    github_token = Config.GITHUB_TOKEN
    if not github_token:
        print("GitHub token not available. Exiting.")
        return None, None

    g = Github(github_token)
    return g, g.get_user(Config.REPO_OWNER).get_repo(Config.REPO_NAME)


def update_branch_reference(repo, commit_sha):
    try:
        repo.get_git_ref(f"heads/{repo.default_branch}").edit(commit_sha)
    except Exception as e:
        print(f"Error updating branch reference: {e}")


def commit_and_update_branch(g, repo, latest_commit, tree):
    try:
        committer = InputGitAuthor(
            name=g.get_user().name,
            email=g.get_user().email,
        )

        commit = repo.create_git_commit(
            message=Config.COMMIT_MESSAGE,
            tree=tree,
            parents=[latest_commit],
            committer=committer,
            author=committer,
        )

        # Update the branch reference to the new commit
        print(f"Old Branch SHA: {repo.get_branch(repo.default_branch).commit.sha}")
        print(
            f"Current Branch Protection: {repo.get_branch(repo.default_branch).protected}"
        )

        update_branch_reference(repo, commit.sha)

        print(f"New Branch SHA: {repo.get_branch(repo.default_branch).commit.sha}")
        print("Files updated successfully.")
    except Exception as e:
        print(f"Error updating files: {e}")


def has_file_changed(repo, file_path, new_content, branch_name):
    try:
        contents = repo.get_contents(file_path, ref=branch_name)
        existing_content = contents.decoded_content.decode("utf-8")
        return existing_content != new_content
    except Exception as e:
        print(f"Exception in has_file_changed: {e}")
        print(f"File Path: {file_path}")
        return True


def create_git_tree_elements(file_updates):
    return [
        InputGitTreeElement(
            path=update.path, mode="100644", type="blob", content=update.content
        )
        for update in file_updates
    ]


def update_repository_with_json(file_updates):
    g, github_repo = get_github_repository()

    if not github_repo:
        return

    if not file_updates:
        print("No changes detected. Exiting.")
        return

    # Check if each file has changed
    updated_files = [
        file_update
        for file_update in file_updates
        if has_file_changed(
            github_repo,
            file_update.path,
            file_update.content,
            github_repo.default_branch,
        )
    ]

    print("All files:", [file_update.path for file_update in file_updates])

    if not updated_files:
        print("No changes detected. Exiting.")
        return

    print("Updated files:", [file_update.path for file_update in updated_files])

    # Get the latest commit
    latest_commit_sha = github_repo.get_branch(github_repo.default_branch).commit.sha
    latest_commit = github_repo.get_git_commit(sha=latest_commit_sha)

    # Create a tree with the updates
    tree_elements = create_git_tree_elements(updated_files)
    tree = github_repo.create_git_tree(tree_elements, base_tree=latest_commit.tree)

    print(f"Latest Commit SHA: {latest_commit.sha}")
    print(f"New Tree SHA: {tree.sha}")

    commit_and_update_branch(g, github_repo, latest_commit, tree)


def find_common_prefix(urls):
    if not urls or not all(urls):
        return ""

    first_parts = urlsplit(urls[0])
    common_prefix = f"{first_parts.scheme}://{first_parts.netloc}"

    path_prefix = first_parts.path

    for url in urls[1:]:
        parsed_url = urlsplit(url)

        if (
            parsed_url.scheme != first_parts.scheme
            or parsed_url.netloc != first_parts.netloc
        ):
            common_prefix = f"{parsed_url.scheme}://{parsed_url.netloc}"
            break

        current_path = parsed_url.path

        common_prefix_len = 0
        for i in range(min(len(path_prefix), len(current_path))):
            if path_prefix[i] == current_path[i]:
                common_prefix_len += 1
            else:
                break

        path_prefix = path_prefix[:common_prefix_len]

    common_prefix = common_prefix.rstrip("/")

    parsed_url = urlparse(common_prefix)
    parsed_url = parsed_url._replace(scheme="")
    url_without_https = urlunparse(parsed_url)
    url_without_slashes = url_without_https.lstrip("/")

    return urlunsplit(("https", url_without_slashes, path_prefix, "", ""))


def extract_relative_url(full_url, base_url):
    if full_url.startswith(base_url):
        trimmed_title_page = full_url[len(base_url) :]
        return trimmed_title_page
    else:
        return full_url


def extract_video_id(url):
    VIDEO_NOT_FOUND = {
        "youtube": None,
        "drive": None,
        "dropbox": None,
        "onedrive": None,
        "loom": None,
    }

    try:
        if not url:
            return VIDEO_NOT_FOUND

        parsed_url = urlparse(url)

        if "youtube.com" in parsed_url.netloc or "youtu.be" in parsed_url.netloc:
            video_id = parse_qs(parsed_url.query).get("v", [None])[
                0
            ] or parsed_url.path.lstrip("/")
            if video_id:
                return {
                    "youtube": video_id,
                    "drive": None,
                    "dropbox": None,
                    "onedrive": None,
                    "loom": None,
                }
            else:
                return VIDEO_NOT_FOUND

        elif "drive.google.com" in parsed_url.netloc:
            return {
                "youtube": None,
                "drive": url,
                "dropbox": None,
                "onedrive": None,
                "loom": None,
            }

        elif "dropbox.com" in parsed_url.netloc:
            return {
                "youtube": None,
                "drive": None,
                "dropbox": url,
                "onedrive": None,
                "loom": None,
            }

        elif "onedrive.com" in parsed_url.netloc:
            return {
                "youtube": None,
                "drive": None,
                "dropbox": None,
                "onedrive": url,
                "loom": None,
            }

        elif "loom.com" in parsed_url.netloc:
            return {
                "youtube": None,
                "drive": None,
                "dropbox": None,
                "onedrive": None,
                "loom": url,
            }

        return VIDEO_NOT_FOUND
    except Exception:
        return VIDEO_NOT_FOUND


def extract_hub_info(url):
    if not url:
        return None

    try:
        username, repo_name = urlparse(url).path.strip("/").split("/")[-2:]
        return f"{username}/{repo_name}" if username and repo_name else None
    except Exception:
        return None


def parse_paper_links(html):
    links = html.find_all("a")

    final_link = None
    arxiv_id = None
    pdf_link = None
    hal_link = None
    researchgate_link = None
    amazonscience_link = None

    for link in links:
        href = link.get("href", "")
        img = link.img
        img_alt = img.get("alt", "").lower() if img else ""

        if "thecvf" in img_alt:
            final_link = href
        elif "arxiv" in img_alt and "arxiv.org" in href:
            arxiv_id = urlsplit(href).path.split("/")[-1]
        elif "pdf" in img_alt:
            pdf_link = href
        elif "hal science" in img_alt:
            hal_link = href
        elif "researchgate" in img_alt:
            researchgate_link = href
        elif "amazon science" in img_alt:
            amazonscience_link = href

    return {
        "final": final_link,
        "arxiv_id": arxiv_id,
        "pdf": pdf_link,
        "hal": hal_link,
        "researchgate": researchgate_link,
        "amazonscience": amazonscience_link,
    }


def extract_paper_data(paper_section, columns):
    title_column = columns[0]
    # title = title_column.get_text(strip=True)
    title = (
        title_column.a.encode_contents().decode("utf-8")
        if title_column.a is not None
        else (
            title_column.encode_contents().decode("utf-8")
            if title_column.get_text(strip=True) is not None
            else None
        )
    )

    title = re.sub(r"<(?:br\s*/?>|img[^>]*>)", "", title)
    title = title.strip()

    html_entities = {
        "&amp;": "&",
        "&lt;": "<",
        "&gt;": ">",
        "&quot;": '"',
        "&apos;": "'",
    }
    title = re.sub(
        r"(&\w+;)", lambda x: html_entities.get(x.group(0), x.group(0)), title
    )

    title_link = title_column.find("a")
    title_page = title_link["href"] if title_link else None

    if title and any(column.find("a") for column in columns[1:]):
        links = columns[1].find_all("a")

        web_page_link = next(
            (a for a in links if "page" in a.img.get("alt", "").lower()),
            None,
        )

        web_page = (
            web_page_link["href"]
            if web_page_link and "web" in web_page_link.img.get("alt", "").lower()
            else None
        )
        github_page = (
            web_page_link["href"]
            if web_page_link and "github" in web_page_link.img.get("alt", "").lower()
            else None
        )

        github_link = next(
            (a for a in links if a.img.get("alt", "").lower() == "github"),
            None,
        )
        github = (
            github_link["href"]
            if github_link and "github" in github_link.img.get("alt", "").lower()
            else None
        )
        github_info = extract_hub_info(github)

        gitlab_link = next(
            (a for a in links if a.img.get("alt", "").lower() == "gitlab"),
            None,
        )
        gitlab = (
            gitlab_link["href"]
            if gitlab_link and "gitlab" in gitlab_link.img.get("alt", "").lower()
            else None
        )
        gitlab_info = extract_hub_info(gitlab)

        modelscope_link = next(
            (a for a in links if a.img.get("alt", "").lower() == "modelscope"),
            None,
        )
        modelscope = (
            modelscope_link["href"]
            if modelscope_link
            and "modelscope" in modelscope_link.img.get("alt", "").lower()
            else None
        )

        gitee_link = next(
            (a for a in links if a.img.get("alt", "").lower() == "gitee"),
            None,
        )
        gitee = (
            gitee_link["href"]
            if gitee_link and "gitee" in gitee_link.img.get("alt", "").lower()
            else None
        )

        demo_link = next(
            (
                a
                for a in links
                if any(
                    keyword in a.img.get("alt", "").lower()
                    for keyword in ["hugging face", "hf"]
                )
            ),
            None,
        )
        demo_page = demo_link["href"] if demo_link else None

        colab_link = next(
            (a for a in links if "open in colab" in a.img.get("alt", "").lower()),
            None,
        )
        colab = colab_link["href"] if colab_link else None

        zenodo_link = next(
            (a for a in links if "zenodo" in a.img.get("alt", "").lower()),
            None,
        )
        zenodo = zenodo_link["href"] if zenodo_link else None

        kaggle_link = next(
            (a for a in links if "kaggle" in a.img.get("alt", "").lower()),
            None,
        )
        kaggle = kaggle_link["href"] if kaggle_link else None

        (
            paper_thecvf,
            paper_arxiv_id,
            paper_pdf,
            paper_hal,
            paper_researchgate,
            paper_amazon,
        ) = parse_paper_links(columns[2]).values()

        video_link = columns[3].find("a")
        video = video_link["href"] if video_link else None

        (
            video_id_youtube,
            video_drive,
            video_dropbox,
            video_onedrive,
            video_loom,
        ) = extract_video_id(video).values()

        base_url = None
        if title_page and paper_thecvf:
            urls = [title_page, paper_thecvf]
            common_prefix = find_common_prefix(urls)
            base_url = common_prefix.rstrip("/")

            title_page = extract_relative_url(title_page, base_url)
            paper_thecvf = extract_relative_url(paper_thecvf, base_url)

        paper_data = {
            "title": title,
            "base_url": base_url,
            "title_page": title_page,
            "github": github_info,
            "web_page": web_page,
            "github_page": github_page,
            "colab": colab,
            "modelscope": modelscope,
            "gitee": gitee,
            "gitlab": gitlab_info,
            "zenodo": zenodo,
            "kaggle": kaggle,
            "demo_page": demo_page,
            "paper_thecvf": paper_thecvf,
            "paper_arxiv_id": paper_arxiv_id,
            "paper_pdf": paper_pdf,
            "paper_hal_science": paper_hal,
            "paper_researchgate": paper_researchgate,
            "paper_amazon": paper_amazon,
            "youtube_id": video_id_youtube,
            "drive_google": video_drive,
            "dropbox": video_dropbox,
            "onedrive": video_onedrive,
            "loom": video_loom,
            "section": paper_section,
        }

        return paper_data
    else:
        return None


def process_markdown_file(
    markdown_file,
    output_directory,
    counter,
    table,
    success_count,
    no_table_count,
    error_count,
    file_updates,
):
    common_ancestor = Path(
        *Path(markdown_file)
        .resolve()
        .parts[: len(Path(output_directory).resolve().parts)]
    )
    relative_path = Path(
        *Path(markdown_file).resolve().parts[len(common_ancestor.resolve().parts) :]
    )
    json_filename = output_directory.joinpath(relative_path.with_suffix(".json"))

    try:
        with open(markdown_file, "r", encoding="utf-8") as file:
            markdown_content = file.read()

        markdown_content = re.sub(r"<!--.*?-->", "", markdown_content, flags=re.DOTALL)

        html_content = markdown2.markdown(
            text=markdown_content, html4tags=True, extras=["tables"]
        )
        soup = BeautifulSoup(html_content, "html.parser")
        table_in_file = soup.find_all("table")[-1]
        paper_section = soup.find("h2").text

        papers = []

        if table_in_file:
            for row in table_in_file.find_all("tr")[1:]:
                columns = row.find_all("td")[-4:]
                paper_data = extract_paper_data(paper_section, columns)
                if paper_data:
                    papers.append(paper_data)

        if len(papers) == 0:
            table.add_row(
                [counter, markdown_file.name, print_colored_status("No table")]
            )
            no_table_count[0] += 1
        else:
            json_filename.parent.mkdir(parents=True, exist_ok=True)

            with open(json_filename, "w", encoding="utf-8") as file:
                json.dump(papers, file, ensure_ascii=False, indent=2)

            table.add_row(
                [
                    counter,
                    os.path.basename(json_filename),
                    print_colored_status("Success"),
                ],
            )

            json_content = json.dumps(papers, ensure_ascii=False, indent=2)
            file_updates.append(
                FileUpdate(
                    path=f"json_data/{relative_path.with_suffix('.json')}",
                    content=json_content,
                )
            )

            success_count[0] += 1
    except Exception as e:
        table.add_row(
            [
                counter,
                os.path.basename(json_filename),
                print_colored_status(f"Error: {e}"),
            ],
        )
        error_count[0] += 1

    return table, file_updates, success_count, no_table_count, error_count


def main():
    # Check if running in GitHub Actions
    in_actions = os.getenv("GITHUB_ACTIONS") == "true" or os.getenv("CI") == "true"

    # Define the paths based on the environment
    if in_actions:
        # Define the paths using the GitHub workspace
        markdown_directory = Path(Config.GITHUB_WORKSPACE) / Config.MARKDOWN_DIRECTORY
        output_directory = Path(Config.GITHUB_WORKSPACE) / Config.OUTPUT_DIRECTORY
    else:
        # Define local paths
        markdown_directory = Path(Config.MARKDOWN_DIRECTORY_LOCAL)
        output_directory = Path(Config.OUTPUT_DIRECTORY_LOCAL)

    # Add this line at the end to print the paths for verification
    print(f"Markdown Directory: {markdown_directory}")
    print(f"Output Directory: {output_directory}")

    if not output_directory.is_dir():
        output_directory.mkdir(parents=True)
    else:
        clear_directory(output_directory)

    # Create a PrettyTable
    table = PrettyTable(["#", "File", "Status"])
    table.align["File"] = "l"  # Align "File" column to the left

    # Create counters as lists to enable modification within functions
    success_count = [0]
    no_table_count = [0]
    error_count = [0]

    markdown_files = [f for f in markdown_directory.rglob("*.md")]

    file_updates = []

    for counter, markdown_file in enumerate(markdown_files, start=1):
        (
            table,
            file_updates,
            success_count,
            no_table_count,
            error_count,
        ) = process_markdown_file(
            markdown_file,
            output_directory,
            counter,
            table,
            success_count,
            no_table_count,
            error_count,
            file_updates,
        )

    update_repository_with_json(file_updates)

    # Print the PrettyTable
    print(table)

    summary_table = PrettyTable(["Category", "Count"])
    summary_table.align["Category"] = "l"  # Align "Category" column to the left

    # Add rows to the summary table
    summary_table.add_row(["Success", print_colored_count(success_count[0], "Success")])
    summary_table.add_row(
        ["No table", print_colored_count(no_table_count[0], "No table")]
    )
    summary_table.add_row(["Errors", print_colored_count(error_count[0], "Errors")])

    # Print the summary table
    print(summary_table)


if __name__ == "__main__":
    main()
