import os
from evigraph.engine_config import get_config


def get_repo_workspace_path(repo_id: str) -> str:
    return os.path.join(get_config().workspace_dir, repo_id)


def ensure_workspace():
    os.makedirs(get_config().workspace_dir, exist_ok=True)


EXTENSION_LANGUAGE_MAP = {
    ".java": "Java",
    ".kt": "Kotlin",
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".go": "Go",
    ".rs": "Rust",
    ".c": "C",
    ".cpp": "C++",
    ".h": "C",
    ".hpp": "C++",
    ".cs": "C#",
    ".rb": "Ruby",
    ".php": "PHP",
    ".swift": "Swift",
    ".scala": "Scala",
    ".r": "R",
    ".m": "Objective-C",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".json": "JSON",
    ".xml": "XML",
    ".properties": "Properties",
    ".gradle": "Gradle",
    ".md": "Markdown",
    ".dockerfile": "Dockerfile",
    ".sh": "Shell",
    ".sql": "SQL",
    ".graphql": "GraphQL",
    ".gql": "GraphQL",
    ".proto": "Protobuf",
    ".tf": "Terraform",
    ".tfvars": "Terraform",
    ".hcl": "HCL",
}

IGNORED_FOLDERS = {
    ".git", "node_modules", "target", "build", "dist", ".next",
    ".venv", "venv", "__pycache__", ".idea", ".vscode",
    "coverage", ".pytest_cache", ".gradle", ".mvn",
    "out", "bin", "obj", "vendor", "*.egg-info",
    ".tox", ".eggs", "htmlcov", ".coverage",
}

BINARY_EXTENSIONS = {
    ".exe", ".dll", ".so", ".dylib", ".class", ".jar",
    ".war", ".ear", ".zip", ".tar", ".gz", ".bz2",
    ".7z", ".rar", ".pdf", ".doc", ".docx", ".xls",
    ".xlsx", ".ppt", ".pptx", ".png", ".jpg", ".jpeg",
    ".gif", ".bmp", ".ico", ".svg", ".mp3", ".mp4",
    ".avi", ".mov", ".woff", ".woff2", ".ttf", ".eot",
    ".db", ".sqlite", ".sqlite3", ".o", ".a",
}


def detect_language(file_path: str) -> str:
    ext = os.path.splitext(file_path)[1].lower()
    if file_path.endswith("Dockerfile") or file_path.endswith(".dockerfile"):
        return "Dockerfile"
    if file_path.endswith("docker-compose.yml") or file_path.endswith("docker-compose.yaml"):
        return "Docker Compose"
    return EXTENSION_LANGUAGE_MAP.get(ext, "Unknown")


# Dotfolders that carry deploy/CI topology signals (design §3.2); .git stays excluded.
ALLOWED_DOT_FOLDERS = {".github"}


def should_ignore_folder(folder_name: str) -> bool:
    if folder_name in ALLOWED_DOT_FOLDERS:
        return False
    return folder_name in IGNORED_FOLDERS or folder_name.startswith(".")


def is_binary_file(file_path: str) -> bool:
    ext = os.path.splitext(file_path)[1].lower()
    return ext in BINARY_EXTENSIONS


def is_large_file(file_path: str, max_bytes: int = 1_000_000) -> bool:
    try:
        return os.path.getsize(file_path) > max_bytes
    except OSError:
        return True
