import pytest
from adduce.utils.hashing import (
    generate_repo_id, generate_node_id, normalize_github_url, sanitize_path,
)


class TestNormalizeGithubUrl:
    def test_standard_url(self):
        url, owner, repo = normalize_github_url("https://github.com/facebook/react")
        assert url == "https://github.com/facebook/react"
        assert owner == "facebook"
        assert repo == "react"
    
    def test_url_with_git_suffix(self):
        url, owner, repo = normalize_github_url("https://github.com/vercel/next.js.git")
        assert url == "https://github.com/vercel/next.js"
        assert owner == "vercel"
        assert repo == "next.js"
    
    def test_url_with_trailing_slash(self):
        url, owner, repo = normalize_github_url("https://github.com/torvalds/linux/")
        assert url == "https://github.com/torvalds/linux"
        assert owner == "torvalds"
        assert repo == "linux"

    def test_scp_ssh_url(self):
        url, owner, repo = normalize_github_url("git@github.com:adduce-labs/adduce")
        assert url == "https://github.com/adduce-labs/adduce"
        assert owner == "adduce-labs"
        assert repo == "adduce"

    def test_scp_ssh_url_with_git_suffix(self):
        url, owner, repo = normalize_github_url("git@github.com:adduce-labs/adduce.git")
        assert url == "https://github.com/adduce-labs/adduce"
        assert owner == "adduce-labs"
        assert repo == "adduce"
    
    def test_invalid_url(self):
        with pytest.raises(ValueError):
            normalize_github_url("not-a-url")
    
    def test_non_github_host_normalizes_but_is_not_authorized_here(self):
        # Normalization is host-agnostic; authorization is ALLOWED_GIT_HOSTS.
        # Conflating the two made the route's allowlist check a no-op, because
        # it validated a github.com URL this function had just rebuilt.
        url, owner, repo = normalize_github_url("https://gitlab.com/user/repo")
        assert (url, owner, repo) == ("https://gitlab.com/user/repo",
                                      "user", "repo")

    def test_host_is_not_smuggled_through_a_query_string(self):
        for hostile in ("https://evil.com/x?u=github.com/owner/repo",
                        "https://evil.com/github.com/owner/repo/extra"):
            with pytest.raises(ValueError):
                normalize_github_url(hostile)

    def test_option_like_segments_rejected(self):
        # A leading '-' would reach `git clone` as an option, not a path.
        with pytest.raises(ValueError):
            normalize_github_url("https://github.com/--upload-pack=x/repo")


class TestGenerateRepoId:
    def test_basic(self):
        assert generate_repo_id("facebook", "react") == "facebook_react"
    
    def test_case_insensitive(self):
        assert generate_repo_id("Facebook", "React") == "facebook_react"
    
    def test_special_chars(self):
        assert generate_repo_id("my-org", "my-repo") == "my-org_my-repo"


class TestGenerateNodeId:
    def test_basic(self):
        node_id = generate_node_id("facebook_react", "File", "src/index.js")
        assert node_id.startswith("facebook_react:File:")
        assert len(node_id) > 20
    
    def test_deterministic(self):
        id1 = generate_node_id("owner_repo", "Class", "src/App.java", "App")
        id2 = generate_node_id("owner_repo", "Class", "src/App.java", "App")
        assert id1 == id2
    
    def test_different_inputs_different_ids(self):
        id1 = generate_node_id("a", "File", "x")
        id2 = generate_node_id("a", "File", "y")
        assert id1 != id2


class TestSanitizePath:
    def test_normal_path(self):
        assert sanitize_path("src/main/java/App.java") == "src/main/java/App.java"
    
    def test_directory_traversal(self):
        assert ".." not in sanitize_path("../../../etc/passwd")
    
    def test_leading_slash(self):
        assert sanitize_path("/etc/passwd") == "etc/passwd"
