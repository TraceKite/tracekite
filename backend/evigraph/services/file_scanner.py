import logging
import os
from dataclasses import dataclass, field
from typing import Optional

from evigraph.utils.paths import (
    should_ignore_folder,
    is_binary_file,
    is_large_file,
    detect_language,
)

logger = logging.getLogger(__name__)


@dataclass
class FileInfo:
    path: str              # Relative path from repo root
    absolute_path: str     # Full filesystem path
    name: str
    extension: str
    language: str
    size_bytes: int
    is_test: bool = False
    is_config: bool = False
    is_build_file: bool = False
    is_docker: bool = False
    is_k8s: bool = False


@dataclass
class ScanResult:
    repo_path: str
    files: list[FileInfo] = field(default_factory=list)
    folders: list[str] = field(default_factory=list)
    total_files: int = 0
    total_size_bytes: int = 0
    language_stats: dict[str, int] = field(default_factory=dict)


def is_test_file(rel_path: str, file_name: str) -> bool:
    test_patterns = ["test_", "_test.", "_spec.", ".test.", ".spec."]
    return any(pattern in file_name.lower() or pattern in rel_path.lower() for pattern in test_patterns)


def is_config_file(file_name: str) -> bool:
    config_names = {
        ".env", ".env.example", ".env.local", ".env.production",
        "config.yml", "config.yaml", "config.json", "config.properties",
        "application.yml", "application.yaml", "application.properties",
        "settings.yml", "settings.yaml", "settings.json", "settings.gradle",
        "requirements.txt", "pyproject.toml", "setup.py", "setup.cfg",
        "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
        "pom.xml", "build.gradle", "gradle.properties", "maven.properties",
        "tsconfig.json", "jsconfig.json", ".eslintrc", ".prettierrc",
        "docker-compose.yml", "docker-compose.yaml", "Dockerfile",
        "helmfile.yaml", "Chart.yaml", "values.yaml",
    }
    return file_name.lower() in config_names


def is_build_file(file_name: str) -> bool:
    build_names = {
        "pom.xml", "build.gradle", "settings.gradle", "gradle.properties",
        "package.json", "requirements.txt", "pyproject.toml", "setup.py",
        "Cargo.toml", "go.mod", "go.sum", "CMakeLists.txt", "Makefile",
        "yarn.lock", "package-lock.json", "pnpm-lock.yaml", "poetry.lock",
    }
    return file_name.lower() in build_names


def is_docker_file(file_name: str) -> bool:
    docker_names = {"Dockerfile", ".dockerignore", "docker-compose.yml", "docker-compose.yaml"}
    return file_name in docker_names or file_name.endswith(".dockerfile")


def is_k8s_file(file_name: str, extension: str) -> bool:
    if extension.lower() in (".yaml", ".yml"):
        k8s_names = {"deployment", "service", "configmap", "secret", "ingress",
                      "pod", "replicaset", "statefulset", "daemonset", "job",
                      "cronjob", "pvc", "pv", "namespace", "role", "rolebinding",
                      "helmfile", "chart", "values"}
        base = os.path.splitext(file_name)[0].lower()
        return any(k in base for k in k8s_names)
    return False


def scan_repository(repo_path: str) -> ScanResult:
    """
    Scan a cloned repository and collect file information.
    
    Args:
        repo_path: Absolute path to the cloned repository
    
    Returns:
        ScanResult containing all discovered files and metadata
    """
    result = ScanResult(repo_path=repo_path)
    
    if not os.path.isdir(repo_path):
        logger.error("Repository path does not exist: %s", repo_path)
        return result
    
    logger.info("Scanning repository at %s", repo_path)
    
    for root, dirs, files in os.walk(repo_path):
        # Filter out ignored directories in-place
        dirs[:] = [d for d in dirs if not should_ignore_folder(d)]
        
        rel_folder = os.path.relpath(root, repo_path)
        if rel_folder != ".":
            result.folders.append(rel_folder)
        
        for file_name in files:
            abs_path = os.path.join(root, file_name)
            rel_path = os.path.relpath(abs_path, repo_path)
            
            if is_binary_file(file_name):
                continue
            
            # Skip large files (>1MB)
            if is_large_file(abs_path):
                logger.debug("Skipping large file: %s", rel_path)
                continue
            
            # Skip symlinks that point outside workspace
            if os.path.islink(abs_path):
                real_path = os.path.realpath(abs_path)
                if not real_path.startswith(os.path.realpath(repo_path)):
                    logger.warning("Skipping external symlink: %s", rel_path)
                    continue
            
            extension = os.path.splitext(file_name)[1].lower()
            language = detect_language(file_name)
            size_bytes = os.path.getsize(abs_path)
            
            file_info = FileInfo(
                path=rel_path,
                absolute_path=abs_path,
                name=file_name,
                extension=extension,
                language=language,
                size_bytes=size_bytes,
                is_test=is_test_file(rel_path, file_name),
                is_config=is_config_file(file_name),
                is_build_file=is_build_file(file_name),
                is_docker=is_docker_file(file_name),
                is_k8s=is_k8s_file(file_name, extension),
            )
            
            result.files.append(file_info)
            result.total_files += 1
            result.total_size_bytes += size_bytes
            
            if language != "Unknown":
                result.language_stats[language] = result.language_stats.get(language, 0) + 1
    
    logger.info(
        "Scan complete: %d files, %d folders, languages: %s",
        result.total_files,
        len(result.folders),
        result.language_stats,
    )
    
    return result
