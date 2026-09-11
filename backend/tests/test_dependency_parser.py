"""Tests for dependency file parsers."""

import pytest
from evigraph.parsers.dependency_parser import (
    DependencyInfo, PublishIdentity,
    parse_package_json, parse_requirements_txt, parse_pom_xml,
    parse_build_gradle, parse_dependency_file, parse_publish_identity,
    parse_npm_workspaces, parse_package_lock, parse_pnpm_lock, parse_yarn_lock,
    parse_pyproject_toml, parse_poetry_lock, parse_gradle_versions_catalog,
    parse_go_mod, parse_go_sum, parse_csproj, parse_directory_packages_props,
    parse_gemfile, parse_gemfile_lock, parse_composer_json,
    parse_cargo_toml, parse_cargo_lock, parse_bazel_module, parse_sbom,
    detect_dependency_type,
)


def _by_name(deps):
    return {d.name: d for d in deps}


class TestPackageJsonParser:
    def test_basic(self):
        content = """{
            "name": "my-app",
            "dependencies": {
                "react": "^18.0.0",
                "express": "^4.18.0"
            },
            "devDependencies": {
                "jest": "^29.0.0"
            }
        }"""
        deps = parse_package_json("package.json", content)
        
        assert len(deps) == 3
        dep_names = [d.name for d in deps]
        assert "react" in dep_names
        assert "express" in dep_names
        assert "jest" in dep_names
    
    def test_empty(self):
        deps = parse_package_json("package.json", '{"name": "test"}')
        assert len(deps) == 0


class TestRequirementsTxtParser:
    def test_basic(self):
        content = """
requests==2.28.1
fastapi>=0.100.0
numpy
# comment
pytest~=7.0
"""
        deps = parse_requirements_txt("requirements.txt", content)
        
        assert len(deps) == 4
        dep_names = [d.name for d in deps]
        assert "requests" in dep_names
        assert "fastapi" in dep_names
        assert "numpy" in dep_names
        assert "pytest" in dep_names


class TestPomXmlParser:
    def test_basic(self):
        content = """<?xml version="1.0"?>
<project>
    <dependencies>
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-web</artifactId>
            <version>3.0.0</version>
        </dependency>
        <dependency>
            <groupId>org.postgresql</groupId>
            <artifactId>postgresql</artifactId>
            <scope>runtime</scope>
        </dependency>
    </dependencies>
</project>"""
        deps = parse_pom_xml("pom.xml", content)
        
        assert len(deps) == 2
        assert deps[0].name == "org.springframework.boot:spring-boot-starter-web"
        assert deps[0].version == "3.0.0"
        assert deps[1].scope == "runtime"


class TestBuildGradleParser:
    def test_basic(self):
        content = """
dependencies {
    implementation 'org.springframework.boot:spring-boot-starter-web:3.0.0'
    implementation 'org.postgresql:postgresql:42.5.0'
    testImplementation 'junit:junit:4.13.2'
    compileOnly 'org.projectlombok:lombok:1.18.24'
}
"""
        deps = parse_build_gradle("build.gradle", content)
        
        assert len(deps) >= 3
        dep_names = [d.name for d in deps]
        assert any("spring-boot" in n for n in dep_names)
        assert any("postgresql" in n for n in dep_names)
    
    def test_double_quoted_deps(self):
        content = """
dependencies {
    implementation "org.jetbrains.kotlinx:kotlinx-coroutines-core:1.7.0"
}
"""
        deps = parse_build_gradle("build.gradle", content)
        assert len(deps) == 1
        assert "kotlinx-coroutines-core" in deps[0].name


class TestDependencyInfoBackCompat:
    """New fields must default so legacy construction keeps working."""

    def test_new_fields_default(self):
        dep = DependencyInfo(name="x", version="1", scope="s", type="npm")
        assert dep.ecosystem == ""
        assert dep.namespace == ""
        assert dep.resolved is False
        assert dep.git_url == ""
        assert dep.license == ""


class TestPomXmlAdvanced:
    """Parent, properties, dependencyManagement BOM imports."""

    POM = """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <parent>
    <groupId>com.acme.platform</groupId>
    <artifactId>acme-parent</artifactId>
    <version>2.1.0</version>
  </parent>
  <artifactId>orders-service</artifactId>
  <properties>
    <spring.version>6.1.4</spring.version>
  </properties>
  <dependencyManagement>
    <dependencies>
      <dependency>
        <groupId>org.springframework.cloud</groupId>
        <artifactId>spring-cloud-dependencies</artifactId>
        <version>2023.0.1</version>
        <type>pom</type>
        <scope>import</scope>
      </dependency>
      <dependency>
        <groupId>com.acme</groupId>
        <artifactId>acme-pinned</artifactId>
        <version>1.0</version>
      </dependency>
    </dependencies>
  </dependencyManagement>
  <dependencies>
    <dependency>
      <groupId>org.springframework</groupId>
      <artifactId>spring-context</artifactId>
      <version>${spring.version}</version>
    </dependency>
    <dependency>
      <groupId>com.acme.platform</groupId>
      <artifactId>acme-commons</artifactId>
      <version>${project.parent.version}</version>
    </dependency>
  </dependencies>
</project>"""

    def test_parent_coords_emitted(self):
        by_name = _by_name(parse_pom_xml("pom.xml", self.POM))
        parent = by_name["com.acme.platform:acme-parent"]
        assert parent.scope == "parent"
        assert parent.version == "2.1.0"

    def test_bom_import_scope(self):
        by_name = _by_name(parse_pom_xml("pom.xml", self.POM))
        bom = by_name["org.springframework.cloud:spring-cloud-dependencies"]
        assert bom.scope == "bom-import"
        assert bom.version == "2023.0.1"
        assert by_name["com.acme:acme-pinned"].scope == "managed"

    def test_property_resolution(self):
        by_name = _by_name(parse_pom_xml("pom.xml", self.POM))
        assert by_name["org.springframework:spring-context"].version == "6.1.4"
        assert by_name["com.acme.platform:acme-commons"].version == "2.1.0"

    def test_ecosystem_and_namespace(self):
        dep = _by_name(parse_pom_xml("pom.xml", self.POM))["org.springframework:spring-context"]
        assert dep.ecosystem == "maven"
        assert dep.namespace == "org.springframework"
        assert dep.resolved is False
        assert dep.type == "maven"

    def test_malformed_xml_falls_back_to_regex(self):
        content = """<project><dependencies>
        <dependency><groupId>g</groupId><artifactId>a</artifactId><version>1</version></dependency>
        <unclosed>"""
        deps = parse_pom_xml("pom.xml", content)
        assert len(deps) == 1
        assert deps[0].name == "g:a"

    def test_garbage_does_not_raise(self):
        assert parse_pom_xml("pom.xml", "\x00 not xml at all <<<") == []


class TestBuildGradleKts:
    """kts function style, platform(), project(), catalog refs."""

    KTS = """
dependencies {
    implementation("org.springframework.boot:spring-boot-starter-web:3.2.0")
    implementation(platform("org.springframework.boot:spring-boot-dependencies:3.2.0"))
    testImplementation(enforcedPlatform("org.junit:junit-bom:5.10.2"))
    implementation(project(":shared-lib"))
    implementation(libs.spring.boot.starter)
    runtimeOnly(libs.postgres.driver)
    annotationProcessor("org.projectlombok:lombok:1.18.30")
}
"""

    def test_kts_string_notation(self):
        by_name = _by_name(parse_build_gradle("build.gradle.kts", self.KTS))
        dep = by_name["org.springframework.boot:spring-boot-starter-web:3.2.0"]
        assert dep.version == "3.2.0"
        assert dep.scope == "implementation"
        assert dep.ecosystem == "maven"
        assert dep.namespace == "org.springframework.boot"

    def test_platform_is_bom_import(self):
        by_name = _by_name(parse_build_gradle("build.gradle.kts", self.KTS))
        assert by_name["org.springframework.boot:spring-boot-dependencies:3.2.0"].scope == "bom-import"
        assert by_name["org.junit:junit-bom:5.10.2"].scope == "bom-import"

    def test_project_reference(self):
        by_name = _by_name(parse_build_gradle("build.gradle.kts", self.KTS))
        assert by_name[":shared-lib"].scope == "project"

    def test_catalog_refs(self):
        by_name = _by_name(parse_build_gradle("build.gradle.kts", self.KTS))
        ref = by_name["libs.spring.boot.starter"]
        assert ref.type == "gradle-catalog-ref"
        assert ref.version == ""
        assert by_name["libs.postgres.driver"].scope == "runtimeOnly"

    def test_groovy_platform_and_project(self):
        content = """
dependencies {
    implementation platform('org.acme:acme-bom:1.0')
    api project(':core')
    kapt 'com.google.dagger:dagger-compiler:2.50'
}
"""
        by_name = _by_name(parse_build_gradle("build.gradle", content))
        assert by_name["org.acme:acme-bom:1.0"].scope == "bom-import"
        assert by_name[":core"].scope == "project"
        assert by_name["com.google.dagger:dagger-compiler:2.50"].scope == "kapt"

    def test_malformed_does_not_raise(self):
        assert parse_build_gradle("build.gradle.kts", "implementation(") == []


class TestGradleVersionCatalog:
    """gradle/libs.versions.toml [libraries]."""

    CATALOG = """
[versions]
spring-boot = "3.2.2"
jackson = { strictly = "2.16.1" }

[libraries]
spring-boot-starter = { module = "org.springframework.boot:spring-boot-starter", version.ref = "spring-boot" }
jackson-databind = { module = "com.fasterxml.jackson.core:jackson-databind", version.ref = "jackson" }
guava = { module = "com.google.guava:guava", version = "33.0.0-jre" }
commons = { group = "org.apache.commons", name = "commons-lang3", version = "3.14.0" }
shorthand = "io.micrometer:micrometer-core:1.12.2"

[bundles]
web = ["spring-boot-starter"]
"""

    def test_version_ref_resolution(self):
        by_name = _by_name(parse_gradle_versions_catalog("gradle/libs.versions.toml", self.CATALOG))
        dep = by_name["org.springframework.boot:spring-boot-starter"]
        assert dep.version == "3.2.2"
        assert dep.type == "maven"
        assert dep.ecosystem == "maven"
        assert dep.namespace == "org.springframework.boot"
        assert dep.resolved is False

    def test_rich_version_and_forms(self):
        by_name = _by_name(parse_gradle_versions_catalog("gradle/libs.versions.toml", self.CATALOG))
        assert by_name["com.fasterxml.jackson.core:jackson-databind"].version == "2.16.1"
        assert by_name["com.google.guava:guava"].version == "33.0.0-jre"
        assert by_name["org.apache.commons:commons-lang3"].version == "3.14.0"
        assert by_name["io.micrometer:micrometer-core"].version == "1.12.2"

    def test_routed_via_parse_dependency_file(self):
        deps = parse_dependency_file("gradle/libs.versions.toml", self.CATALOG)
        assert len(deps) == 5

    def test_malformed_toml(self):
        assert parse_gradle_versions_catalog("libs.versions.toml", "[libraries\nbroken") == []


class TestNpmWorkspacesAndSpecifiers:
    """Workspaces, workspace:*/catalog:, git deps."""

    def test_workspaces_list(self):
        assert parse_npm_workspaces('{"workspaces": ["packages/*", "apps/web"]}') == [
            "packages/*", "apps/web"]

    def test_workspaces_object(self):
        assert parse_npm_workspaces('{"workspaces": {"packages": ["libs/*"]}}') == ["libs/*"]

    def test_no_workspaces_or_malformed(self):
        assert parse_npm_workspaces('{"name": "x"}') == []
        assert parse_npm_workspaces("not json") == []

    def test_workspace_and_catalog_specifiers_kept(self):
        content = """{
            "dependencies": {
                "@acme/shared": "workspace:*",
                "react": "catalog:",
                "left-pad": "git+https://github.com/left/pad.git#v1.3.0"
            }
        }"""
        by_name = _by_name(parse_package_json("package.json", content))
        assert by_name["@acme/shared"].version == "workspace:*"
        assert by_name["@acme/shared"].namespace == "@acme"
        assert by_name["react"].version == "catalog:"
        assert by_name["react"].ecosystem == "npm"
        assert by_name["left-pad"].git_url == "git+https://github.com/left/pad.git#v1.3.0"


class TestPackageLockParser:
    """Real package-lock parser (was misrouted to parse_package_json)."""

    LOCK_V3 = """{
        "name": "web-app",
        "version": "1.0.0",
        "lockfileVersion": 3,
        "packages": {
            "": {"name": "web-app", "version": "1.0.0",
                 "dependencies": {"react": "^18.2.0"}},
            "node_modules/react": {"version": "18.2.0",
                "resolved": "https://registry.npmjs.org/react/-/react-18.2.0.tgz"},
            "node_modules/@babel/core": {"version": "7.23.9", "dev": true},
            "node_modules/react/node_modules/loose-envify": {"version": "1.4.0"},
            "node_modules/left-pad": {"version": "1.3.0",
                "resolved": "git+ssh://git@github.com/left/pad.git#abc123"},
            "packages/internal-lib": {"version": "0.0.1"}
        }
    }"""

    def test_v3_packages_map(self):
        by_name = _by_name(parse_package_lock("package-lock.json", self.LOCK_V3))
        assert by_name["react"].version == "18.2.0"
        assert by_name["react"].resolved is True
        assert by_name["@babel/core"].scope == "dev"
        assert by_name["@babel/core"].namespace == "@babel"
        assert by_name["loose-envify"].version == "1.4.0"  # nested node_modules key
        assert by_name["left-pad"].git_url.startswith("git+ssh://")

    def test_root_and_workspace_entries_skipped(self):
        names = [d.name for d in parse_package_lock("package-lock.json", self.LOCK_V3)]
        assert "web-app" not in names
        assert "packages/internal-lib" not in names
        assert "internal-lib" not in names

    def test_routing_fixed_to_real_parser(self):
        # The legacy bug routed this file to parse_package_json, which would
        # have returned the root's declared range "^18.2.0" as a dependency.
        deps = parse_dependency_file("package-lock.json", self.LOCK_V3)
        versions = {d.name: d.version for d in deps}
        assert versions["react"] == "18.2.0"
        assert all(d.resolved for d in deps)

    def test_v1_dependencies_map(self):
        content = """{
            "lockfileVersion": 1,
            "dependencies": {
                "express": {"version": "4.18.2",
                    "dependencies": {"accepts": {"version": "1.3.8"}}}
            }
        }"""
        by_name = _by_name(parse_package_lock("package-lock.json", content))
        assert by_name["express"].version == "4.18.2"
        assert by_name["accepts"].version == "1.3.8"

    def test_malformed(self):
        assert parse_package_lock("package-lock.json", "{broken") == []
        assert parse_package_lock("package-lock.json", '{"packages": "nope"}') == []


class TestPnpmLock:
    """pnpm-lock.yaml packages keys."""

    LOCK = """lockfileVersion: '6.0'

dependencies:
  react:
    specifier: ^18.2.0
    version: 18.2.0

packages:

  /@babel/helper-string-parser@7.23.4:
    resolution: {integrity: sha512-xxx}

  /react@18.2.0:
    resolution: {integrity: sha512-yyy}
    dependencies:
      loose-envify: 1.4.0

  /use-sync-external-store@1.2.0(react@18.2.0):
    resolution: {integrity: sha512-zzz}
"""

    def test_v6_keys(self):
        by_name = _by_name(parse_pnpm_lock("pnpm-lock.yaml", self.LOCK))
        assert by_name["react"].version == "18.2.0"
        assert by_name["react"].resolved is True
        assert by_name["@babel/helper-string-parser"].version == "7.23.4"
        assert by_name["@babel/helper-string-parser"].namespace == "@babel"

    def test_peer_suffix_stripped(self):
        by_name = _by_name(parse_pnpm_lock("pnpm-lock.yaml", self.LOCK))
        assert by_name["use-sync-external-store"].version == "1.2.0"

    def test_top_level_dependencies_section_ignored(self):
        deps = parse_pnpm_lock("pnpm-lock.yaml", self.LOCK)
        assert len(deps) == 3

    def test_v9_bare_keys(self):
        content = "packages:\n\n  '@scope/pkg@2.0.1':\n    resolution: {}\n\n  lodash@4.17.21:\n    resolution: {}\n"
        by_name = _by_name(parse_pnpm_lock("pnpm-lock.yaml", content))
        assert by_name["@scope/pkg"].version == "2.0.1"
        assert by_name["lodash"].version == "4.17.21"

    def test_malformed(self):
        assert parse_pnpm_lock("pnpm-lock.yaml", ":::\x00") == []


class TestYarnLock:
    """yarn.lock classic and berry."""

    LOCK = '''# THIS IS AN AUTOGENERATED FILE. DO NOT EDIT THIS FILE DIRECTLY.
# yarn lockfile v1


"@babel/code-frame@^7.0.0", "@babel/code-frame@^7.22.13":
  version "7.23.5"
  resolved "https://registry.yarnpkg.com/@babel/code-frame/-/code-frame-7.23.5.tgz"
  dependencies:
    "@babel/highlight" "^7.23.4"

lodash@^4.17.20, lodash@^4.17.21:
  version "4.17.21"

react@^18.2.0:
  version "18.2.0"
'''

    def test_classic_entries(self):
        by_name = _by_name(parse_yarn_lock("yarn.lock", self.LOCK))
        assert by_name["@babel/code-frame"].version == "7.23.5"
        assert by_name["@babel/code-frame"].namespace == "@babel"
        assert by_name["lodash"].version == "4.17.21"
        assert by_name["react"].version == "18.2.0"
        assert all(d.resolved for d in by_name.values())

    def test_nested_dependency_lines_not_entries(self):
        names = [d.name for d in parse_yarn_lock("yarn.lock", self.LOCK)]
        assert "@babel/highlight" not in names
        assert len(names) == 3

    def test_berry_selector_and_metadata(self):
        content = '__metadata:\n  version: 8\n\n"lodash@npm:^4.17.21":\n  version: 4.17.21\n'
        deps = parse_yarn_lock("yarn.lock", content)
        assert len(deps) == 1
        assert deps[0].name == "lodash"
        assert deps[0].version == "4.17.21"

    def test_malformed(self):
        assert parse_yarn_lock("yarn.lock", "just text with no structure") == []


class TestPyprojectToml:
    """PEP 508 deps, optional groups, poetry tables, git deps."""

    CONTENT = """
[project]
name = "acme-ingest"
version = "0.9.0"
dependencies = [
    "fastapi>=0.110.0",
    "pydantic[email]==2.6.1",
    "tomli; python_version < '3.11'",
    "internal-client @ git+https://github.com/acme/client.git@v2.0.0",
]

[project.optional-dependencies]
test = ["pytest~=8.0"]

[tool.poetry.dependencies]
python = "^3.12"
requests = "^2.31"
custom = { git = "https://github.com/acme/custom.git", tag = "v1.1" }
"""

    def test_pep508_dependencies(self):
        by_name = _by_name(parse_pyproject_toml("pyproject.toml", self.CONTENT))
        assert by_name["fastapi"].version == "0.110.0"
        assert by_name["pydantic"].version == "2.6.1"  # extras stripped from name
        assert by_name["tomli"].version == ""  # marker dropped
        assert by_name["fastapi"].ecosystem == "pypi"

    def test_direct_git_reference(self):
        dep = _by_name(parse_pyproject_toml("pyproject.toml", self.CONTENT))["internal-client"]
        assert dep.git_url == "git+https://github.com/acme/client.git@v2.0.0"
        assert dep.version == "v2.0.0"

    def test_optional_group_scope(self):
        dep = _by_name(parse_pyproject_toml("pyproject.toml", self.CONTENT))["pytest"]
        assert dep.scope == "optional:test"

    def test_poetry_table(self):
        by_name = _by_name(parse_pyproject_toml("pyproject.toml", self.CONTENT))
        assert by_name["requests"].version == "^2.31"
        assert by_name["custom"].git_url == "https://github.com/acme/custom.git"
        assert by_name["custom"].version == "v1.1"
        assert "python" not in by_name

    def test_malformed(self):
        assert parse_pyproject_toml("pyproject.toml", "[project\nbroken") == []


class TestPoetryLock:
    LOCK = '''
[[package]]
name = "requests"
version = "2.31.0"
description = "HTTP for humans"
category = "main"

[[package]]
name = "pytest"
version = "8.0.2"
category = "dev"
'''

    def test_packages(self):
        by_name = _by_name(parse_poetry_lock("poetry.lock", self.LOCK))
        assert by_name["requests"].version == "2.31.0"
        assert by_name["requests"].resolved is True
        assert by_name["requests"].ecosystem == "pypi"
        assert by_name["requests"].scope == ""
        assert by_name["pytest"].scope == "dev"

    def test_routed(self):
        assert len(parse_dependency_file("poetry.lock", self.LOCK)) == 2

    def test_malformed(self):
        assert parse_poetry_lock("poetry.lock", "[[package\nname=") == []


class TestRequirementsVcs:
    """Pip VCS lines."""

    def test_git_lines(self):
        content = """
requests==2.28.1
git+https://github.com/acme/tool.git@v3.1.0#egg=acme-tool
-e git+ssh://git@github.com/acme/dev-lib.git#egg=dev-lib
https://files.example.com/pkg.whl
"""
        deps = parse_requirements_txt("requirements.txt", content)
        by_name = _by_name(deps)
        assert by_name["acme-tool"].git_url == "git+https://github.com/acme/tool.git@v3.1.0"
        assert by_name["acme-tool"].version == "v3.1.0"
        assert by_name["dev-lib"].git_url == "git+ssh://git@github.com/acme/dev-lib.git"
        assert by_name["dev-lib"].version == ""
        assert "https" not in by_name  # bare URL lines are not parsed as names

    def test_vcs_name_from_path_when_no_egg(self):
        deps = parse_requirements_txt("requirements.txt",
                                      "git+https://github.com/acme/widget.git@1.2\n")
        assert deps[0].name == "widget"
        assert deps[0].version == "1.2"


class TestGoModAdvanced:
    """Single-line require, replace, exclude, pseudo-versions."""

    GO_MOD = """module github.com/acme/payments

go 1.22

require (
\tgithub.com/gin-gonic/gin v1.9.1
\tgithub.com/google/uuid v1.6.0 // indirect
\tgolang.org/x/exp v0.0.0-20240213143201-ec583247a57a
)

require github.com/stretchr/testify v1.8.4

replace github.com/acme/legacy => ../legacy-local

replace (
\tgithub.com/old/mod => github.com/new/mod v1.2.0
)

exclude github.com/bad/mod v1.0.0
"""

    def test_module_line_is_not_a_dependency(self):
        names = [d.name for d in parse_go_mod("go.mod", self.GO_MOD)]
        assert "module" not in names
        assert "go" not in names

    def test_require_forms(self):
        by_name = _by_name(parse_go_mod("go.mod", self.GO_MOD))
        assert by_name["github.com/gin-gonic/gin"].version == "v1.9.1"
        assert by_name["github.com/google/uuid"].scope == "indirect"
        assert by_name["github.com/stretchr/testify"].version == "v1.8.4"
        assert by_name["github.com/gin-gonic/gin"].ecosystem == "golang"
        assert by_name["github.com/gin-gonic/gin"].namespace == "github.com/gin-gonic"

    def test_pseudo_version_verbatim(self):
        by_name = _by_name(parse_go_mod("go.mod", self.GO_MOD))
        assert by_name["golang.org/x/exp"].version == "v0.0.0-20240213143201-ec583247a57a"

    def test_replace_directives(self):
        by_name = _by_name(parse_go_mod("go.mod", self.GO_MOD))
        local = by_name["github.com/acme/legacy"]
        assert local.scope == "replace"
        assert local.git_url == "../legacy-local"
        swapped = by_name["github.com/old/mod"]
        assert swapped.git_url == "github.com/new/mod"
        assert swapped.version == "v1.2.0"

    def test_exclude_ignored(self):
        assert "github.com/bad/mod" not in _by_name(parse_go_mod("go.mod", self.GO_MOD))

    def test_malformed(self):
        assert parse_go_mod("go.mod", "require (\n\n") == []


class TestGoSum:
    GO_SUM = """github.com/gin-gonic/gin v1.9.1 h1:aaa=
github.com/gin-gonic/gin v1.9.1/go.mod h1:bbb=
github.com/google/uuid v1.6.0 h1:ccc=
github.com/google/uuid v1.6.0/go.mod h1:ddd=
"""

    def test_skips_go_mod_lines_and_dedupes(self):
        deps = parse_go_sum("go.sum", self.GO_SUM)
        assert len(deps) == 2
        by_name = _by_name(deps)
        assert by_name["github.com/gin-gonic/gin"].version == "v1.9.1"
        assert all(d.resolved for d in deps)
        assert all(d.ecosystem == "golang" for d in deps)

    def test_malformed(self):
        assert parse_go_sum("go.sum", "one-token-only\n\n") == []


class TestCsproj:
    """NuGet PackageReference / ProjectReference."""

    CSPROJ = """<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net8.0</TargetFramework>
    <PackageId>Acme.Payments.Client</PackageId>
    <Version>2.4.1</Version>
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="Newtonsoft.Json" Version="13.0.3" />
    <PackageReference Include="Serilog">
      <Version>3.1.1</Version>
    </PackageReference>
    <PackageReference Include="Dapper" />
    <ProjectReference Include="..\\Acme.Core\\Acme.Core.csproj" />
  </ItemGroup>
</Project>"""

    def test_package_references(self):
        by_name = _by_name(parse_csproj("src/Acme.Payments/Acme.Payments.csproj", self.CSPROJ))
        assert by_name["Newtonsoft.Json"].version == "13.0.3"
        assert by_name["Serilog"].version == "3.1.1"  # Version as child element
        assert by_name["Dapper"].version == ""  # central package management
        assert by_name["Newtonsoft.Json"].ecosystem == "nuget"

    def test_project_reference(self):
        by_name = _by_name(parse_csproj("a/b.csproj", self.CSPROJ))
        assert by_name["Acme.Core"].scope == "project"

    def test_routed_by_extension(self):
        assert parse_dependency_file("src/Api/Api.csproj", self.CSPROJ)

    def test_malformed_falls_back_to_regex(self):
        content = '<Project><ItemGroup><PackageReference Include="X" Version="1.0" /><broken'
        deps = parse_csproj("x.csproj", content)
        assert len(deps) == 1
        assert deps[0].name == "X"
        assert deps[0].version == "1.0"


class TestDirectoryPackagesProps:
    """Central package management pins."""

    PROPS = """<Project>
  <PropertyGroup>
    <ManagePackageVersionsCentrally>true</ManagePackageVersionsCentrally>
  </PropertyGroup>
  <ItemGroup>
    <PackageVersion Include="Newtonsoft.Json" Version="13.0.3" />
    <PackageVersion Include="xunit" Version="2.6.6" />
    <GlobalPackageReference Include="StyleCop.Analyzers" Version="1.1.118" />
  </ItemGroup>
</Project>"""

    def test_package_versions(self):
        by_name = _by_name(parse_directory_packages_props("Directory.Packages.props", self.PROPS))
        assert by_name["Newtonsoft.Json"].version == "13.0.3"
        assert by_name["Newtonsoft.Json"].scope == "managed"
        assert by_name["StyleCop.Analyzers"].scope == "global"
        assert by_name["xunit"].type == "nuget"

    def test_routed_by_name(self):
        assert len(parse_dependency_file("Directory.Packages.props", self.PROPS)) == 3

    def test_malformed(self):
        assert parse_directory_packages_props("Directory.Packages.props", "<Project><broken") == []


class TestGemfile:

    def test_gem_lines(self):
        content = """source "https://rubygems.org"

gem "rails", "~> 7.1"
gem 'pg', '>= 1.5', '< 2.0'
gem "custom-gem", git: "https://github.com/acme/custom-gem.git"
gem "octokit", github: "octokit/octokit.rb"
gem "rake"
"""
        by_name = _by_name(parse_gemfile("Gemfile", content))
        assert by_name["rails"].version == "~> 7.1"
        assert by_name["pg"].version == ">= 1.5"
        assert by_name["custom-gem"].git_url == "https://github.com/acme/custom-gem.git"
        assert by_name["octokit"].git_url == "https://github.com/octokit/octokit.rb"
        assert by_name["rake"].version == ""
        assert by_name["rails"].ecosystem == "gem"

    def test_malformed(self):
        assert parse_gemfile("Gemfile", "gem \"unclosed\n\x00") == []


class TestGemfileLock:
    LOCK = """GIT
  remote: https://github.com/acme/custom-gem.git
  revision: abc123
  specs:
    custom-gem (0.3.1)

GEM
  remote: https://rubygems.org/
  specs:
    concurrent-ruby (1.2.3)
    rails (7.1.3)
      actionpack (= 7.1.3)
      activesupport (= 7.1.3)
    rake (13.1.0)

PLATFORMS
  arm64-darwin-23

DEPENDENCIES
  rails (~> 7.1)

BUNDLED WITH
   2.5.4
"""

    def test_gem_specs(self):
        by_name = _by_name(parse_gemfile_lock("Gemfile.lock", self.LOCK))
        assert by_name["rails"].version == "7.1.3"
        assert by_name["rails"].scope == "lock"
        assert by_name["rails"].resolved is True
        assert by_name["concurrent-ruby"].version == "1.2.3"
        assert by_name["rake"].version == "13.1.0"

    def test_constraint_lines_skipped(self):
        names = [d.name for d in parse_gemfile_lock("Gemfile.lock", self.LOCK)]
        assert "actionpack" not in names
        assert "activesupport" not in names
        assert len(names) == 4

    def test_git_section_remote(self):
        by_name = _by_name(parse_gemfile_lock("Gemfile.lock", self.LOCK))
        assert by_name["custom-gem"].git_url == "https://github.com/acme/custom-gem.git"

    def test_malformed(self):
        assert parse_gemfile_lock("Gemfile.lock", "randomness\n  no structure") == []


class TestComposerJson:

    def test_require_sections(self):
        content = """{
            "name": "acme/app",
            "require": {
                "php": "^8.2",
                "ext-json": "*",
                "monolog/monolog": "^3.5",
                "guzzlehttp/guzzle": "^7.8"
            },
            "require-dev": {"phpunit/phpunit": "^11.0"}
        }"""
        by_name = _by_name(parse_composer_json("composer.json", content))
        assert by_name["monolog/monolog"].version == "^3.5"
        assert by_name["monolog/monolog"].namespace == "monolog"
        assert by_name["monolog/monolog"].ecosystem == "composer"
        assert by_name["phpunit/phpunit"].scope == "require-dev"
        assert "php" not in by_name
        assert "ext-json" not in by_name

    def test_malformed(self):
        assert parse_composer_json("composer.json", "{nope") == []


class TestCargo:
    """Cargo.toml manifests and Cargo.lock."""

    CARGO_TOML = """
[package]
name = "acme-ledger"
version = "0.4.2"
edition = "2021"

[dependencies]
serde = { version = "1.0", features = ["derive"] }
tokio = "1.36"
internal-util = { path = "../util" }
custom-fork = { git = "https://github.com/acme/fork.git", branch = "main" }

[dev-dependencies]
criterion = "0.5"

[build-dependencies]
cc = "1.0"
"""

    def test_cargo_toml(self):
        by_name = _by_name(parse_cargo_toml("Cargo.toml", self.CARGO_TOML))
        assert by_name["serde"].version == "1.0"
        assert by_name["tokio"].version == "1.36"
        assert by_name["serde"].ecosystem == "cargo"
        assert by_name["criterion"].scope == "dev"
        assert by_name["cc"].scope == "build"
        assert by_name["internal-util"].scope == "project"
        assert by_name["custom-fork"].git_url == "https://github.com/acme/fork.git"

    def test_cargo_lock(self):
        lock = """
version = 3

[[package]]
name = "serde"
version = "1.0.196"
source = "registry+https://github.com/rust-lang/crates.io-index"

[[package]]
name = "custom-fork"
version = "0.2.0"
source = "git+https://github.com/acme/fork.git?branch=main#deadbeef"
"""
        by_name = _by_name(parse_cargo_lock("Cargo.lock", lock))
        assert by_name["serde"].version == "1.0.196"
        assert by_name["serde"].resolved is True
        assert by_name["custom-fork"].git_url.startswith("git+https://")

    def test_malformed(self):
        assert parse_cargo_toml("Cargo.toml", "[dependencies\nbroken") == []
        assert parse_cargo_lock("Cargo.lock", "[[package]]\nname `") == []


class TestBazel:
    """MODULE.bazel / WORKSPACE."""

    MODULE = """module(name = "acme_service", version = "1.0")

bazel_dep(name = "rules_go", version = "0.46.0")
bazel_dep(name = "gazelle", version = "0.35.0", dev_dependency = True)
bazel_dep(
    name = "protobuf",
    version = "23.1",
)
"""

    WORKSPACE = """load("@bazel_tools//tools/build_defs/repo:git.bzl", "git_repository")

git_repository(
    name = "com_github_acme_lib",
    remote = "https://github.com/acme/lib.git",
    tag = "v1.4.0",
)
"""

    def test_bazel_dep(self):
        by_name = _by_name(parse_bazel_module("MODULE.bazel", self.MODULE))
        assert by_name["rules_go"].version == "0.46.0"
        assert by_name["rules_go"].type == "bazel"
        assert by_name["gazelle"].scope == "dev"
        assert by_name["protobuf"].version == "23.1"  # multi-line call
        assert "acme_service" not in by_name  # module() is identity, not a dep

    def test_workspace_git_repository(self):
        by_name = _by_name(parse_bazel_module("WORKSPACE", self.WORKSPACE))
        assert by_name["com_github_acme_lib"].git_url == "https://github.com/acme/lib.git"
        assert by_name["com_github_acme_lib"].version == "v1.4.0"

    def test_routed(self):
        assert parse_dependency_file("MODULE.bazel", self.MODULE)
        assert parse_dependency_file("WORKSPACE", self.WORKSPACE)

    def test_malformed(self):
        assert parse_bazel_module("MODULE.bazel", "bazel_dep(name = ") == []


class TestSbom:
    """CycloneDX and SPDX JSON."""

    CDX = """{
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "components": [
            {"type": "library", "group": "org.springframework", "name": "spring-core",
             "version": "6.1.4", "purl": "pkg:maven/org.springframework/spring-core@6.1.4",
             "licenses": [{"license": {"id": "Apache-2.0"}}]},
            {"type": "library", "name": "react", "version": "18.2.0",
             "purl": "pkg:npm/react@18.2.0"},
            {"type": "library", "name": "core", "version": "7.23.9",
             "purl": "pkg:npm/%40babel/core@7.23.9"}
        ]
    }"""

    SPDX = """{
        "spdxVersion": "SPDX-2.3",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": "acme-app",
        "documentDescribes": ["SPDXRef-Package-acme-app"],
        "packages": [
            {"SPDXID": "SPDXRef-Package-acme-app", "name": "acme-app", "versionInfo": "1.0.0"},
            {"SPDXID": "SPDXRef-Package-requests", "name": "requests", "versionInfo": "2.31.0",
             "licenseConcluded": "Apache-2.0",
             "externalRefs": [{"referenceCategory": "PACKAGE-MANAGER",
                               "referenceType": "purl",
                               "referenceLocator": "pkg:pypi/requests@2.31.0"}]},
            {"SPDXID": "SPDXRef-Package-guava", "name": "guava", "versionInfo": "33.0.0-jre",
             "licenseDeclared": "NOASSERTION",
             "externalRefs": [{"referenceType": "purl",
                               "referenceLocator": "pkg:maven/com.google.guava/guava@33.0.0-jre"}]}
        ]
    }"""

    def test_cyclonedx(self):
        by_name = _by_name(parse_sbom("bom.json", self.CDX))
        spring = by_name["org.springframework:spring-core"]  # maven join-key form
        assert spring.ecosystem == "maven"
        assert spring.namespace == "org.springframework"
        assert spring.license == "Apache-2.0"
        assert spring.resolved is True
        assert by_name["react"].ecosystem == "npm"
        assert by_name["@babel/core"].namespace == "@babel"  # purl %40 decoded

    def test_spdx(self):
        by_name = _by_name(parse_sbom("app.spdx.json", self.SPDX))
        assert "acme-app" not in by_name  # documentDescribes root skipped
        assert by_name["requests"].ecosystem == "pypi"
        assert by_name["requests"].license == "Apache-2.0"
        assert by_name["com.google.guava:guava"].namespace == "com.google.guava"
        assert by_name["com.google.guava:guava"].license == ""  # NOASSERTION dropped

    def test_routing(self):
        assert parse_dependency_file("service.cdx.json", self.CDX)
        assert parse_dependency_file("bom.json", self.CDX)
        assert parse_dependency_file("sbom.json", self.CDX)
        assert parse_dependency_file("scan.spdx.json", self.SPDX)

    def test_malformed(self):
        assert parse_sbom("bom.json", "{broken") == []
        assert parse_sbom("bom.json", '{"bomFormat": "CycloneDX", "components": [42]}') == []


class TestPublishIdentity:
    """What each repo publishes."""

    def test_pom_with_parent_inheritance(self):
        identity = parse_publish_identity("pom.xml", TestPomXmlAdvanced.POM)
        assert identity == PublishIdentity(
            ecosystem="maven", name="orders-service",
            namespace="com.acme.platform", version="2.1.0")

    def test_package_json(self):
        identity = parse_publish_identity(
            "package.json",
            '{"name": "@acme/shared-utils", "version": "3.2.0", "private": true}')
        assert identity.ecosystem == "npm"
        assert identity.name == "@acme/shared-utils"
        assert identity.namespace == "@acme"
        assert identity.version == "3.2.0"
        assert identity.private is True

    def test_pyproject_project_and_poetry(self):
        assert parse_publish_identity(
            "pyproject.toml", '[project]\nname = "acme-lib"\nversion = "1.0"\n'
        ) == PublishIdentity(ecosystem="pypi", name="acme-lib", version="1.0")
        assert parse_publish_identity(
            "pyproject.toml", '[tool.poetry]\nname = "poetry-lib"\nversion = "2.0"\n'
        ) == PublishIdentity(ecosystem="pypi", name="poetry-lib", version="2.0")

    def test_go_mod_module_path(self):
        identity = parse_publish_identity("go.mod", "module github.com/acme/lib\n\ngo 1.22\n")
        assert identity.ecosystem == "golang"
        assert identity.name == "github.com/acme/lib"
        assert identity.namespace == "github.com/acme"

    def test_csproj_package_id(self):
        identity = parse_publish_identity("src/Client/Client.csproj", TestCsproj.CSPROJ)
        assert identity.ecosystem == "nuget"
        assert identity.name == "Acme.Payments.Client"
        assert identity.version == "2.4.1"
        assert identity.private is False

    def test_csproj_not_packable_is_private(self):
        content = """<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup><IsPackable>false</IsPackable></PropertyGroup>
</Project>"""
        identity = parse_publish_identity("src/Acme.Web/Acme.Web.csproj", content)
        assert identity.name == "Acme.Web"  # file-stem fallback
        assert identity.private is True

    def test_cargo(self):
        identity = parse_publish_identity("Cargo.toml", TestCargo.CARGO_TOML)
        assert identity == PublishIdentity(
            ecosystem="cargo", name="acme-ledger", version="0.4.2")
        private = parse_publish_identity(
            "Cargo.toml", '[package]\nname = "internal"\npublish = false\n')
        assert private.private is True

    def test_gemspec(self):
        content = """Gem::Specification.new do |spec|
  spec.name = "acme-client"
  spec.version = "0.8.1"
end
"""
        identity = parse_publish_identity("acme-client.gemspec", content)
        assert identity == PublishIdentity(ecosystem="gem", name="acme-client",
                                           version="0.8.1")

    def test_gradle_identity_is_a_known_gap(self):
        assert parse_publish_identity("build.gradle", "group = 'com.acme'") is None

    def test_unknown_and_malformed(self):
        assert parse_publish_identity("README.md", "# hi") is None
        assert parse_publish_identity("package.json", "not json") is None
        assert parse_publish_identity("pom.xml", "<broken") is None
        assert parse_publish_identity("go.mod", "no module line") is None
        assert parse_publish_identity("Cargo.toml", "[package\nbroken") is None


class TestDispatchAndDetect:
    """Routing table coverage for new file names."""

    def test_new_files_routed(self):
        assert parse_dependency_file("go.sum", TestGoSum.GO_SUM)
        assert parse_dependency_file("Gemfile", 'gem "rails", "~> 7.1"\n')
        assert parse_dependency_file("Gemfile.lock", TestGemfileLock.LOCK)
        assert parse_dependency_file("composer.json", '{"require": {"a/b": "1"}}')
        assert parse_dependency_file("Cargo.toml", TestCargo.CARGO_TOML)
        assert parse_dependency_file("pnpm-lock.yaml", TestPnpmLock.LOCK)
        assert parse_dependency_file("yarn.lock", TestYarnLock.LOCK)
        assert parse_dependency_file("pyproject.toml", TestPyprojectToml.CONTENT)
        assert parse_dependency_file("build.gradle.kts", TestBuildGradleKts.KTS)

    def test_unknown_still_empty(self):
        assert parse_dependency_file("random.xyz", "content") == []

    def test_detect_dependency_type_legacy_pins(self):
        assert detect_dependency_type("package.json") == "npm"
        assert detect_dependency_type("requirements.txt") == "pip"
        assert detect_dependency_type("pom.xml") == "maven"
        assert detect_dependency_type("build.gradle") == "gradle"
        assert detect_dependency_type("go.mod") == "go"
        assert detect_dependency_type("Cargo.toml") == "cargo"
        assert detect_dependency_type("pyproject.toml") == "poetry"
        assert detect_dependency_type("unknown") is None

    def test_detect_dependency_type_new_entries(self):
        assert detect_dependency_type("package-lock.json") == "npm"
        assert detect_dependency_type("pnpm-lock.yaml") == "pnpm"
        assert detect_dependency_type("yarn.lock") == "yarn"
        assert detect_dependency_type("go.sum") == "go"
        assert detect_dependency_type("libs.versions.toml") == "gradle"
        assert detect_dependency_type("Gemfile.lock") == "bundler"
        assert detect_dependency_type("composer.json") == "composer"
        assert detect_dependency_type("Directory.Packages.props") == "nuget"
        assert detect_dependency_type("Api.csproj") == "nuget"
        assert detect_dependency_type("acme.gemspec") == "gem"
        assert detect_dependency_type("MODULE.bazel") == "bazel"
        assert detect_dependency_type("service.cdx.json") == "sbom"
        assert detect_dependency_type("scan.spdx.json") == "sbom"
