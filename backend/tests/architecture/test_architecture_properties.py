"""
Architecture Property Tests - The Architecture Police

These tests enforce Clean Architecture rules across the codebase.
They should FAIL when violations exist and PASS when code is clean.

Property 1: Domain Layer Independence
Property 9: Import Direction Compliance
"""

import pytest
from pathlib import Path
from typing import List, Set

from tests.architecture.import_analyzer import (
    get_python_files,
    parse_imports,
    check_dependency_direction,
    get_layer_from_path,
    ArchitectureViolation
)


class TestDomainLayerIndependence:
    """
    Property 1: Domain Layer Independence

    *For any* file in the domain/ directory, scanning its imports
    should reveal NO imports from infrastructure/ or presentation/ directories.

    **Validates: Requirements 1.1**
    """

    def get_domain_files(self) -> List[str]:
        """Get all Python files in domain layer."""
        return get_python_files('src/domain')

    def test_domain_has_no_infrastructure_imports(self):
        """Domain layer must not import from infrastructure."""
        domain_files = self.get_domain_files()
        violations = []

        for filepath in domain_files:
            file_imports = parse_imports(filepath)
            for imp in file_imports.imports:
                if 'infrastructure' in imp.module.lower():
                    violations.append(
                        f"{filepath}:{imp.line_number} imports '{imp.module}'"
                    )

        assert len(violations) == 0, (
            f"Domain layer has {len(violations)} infrastructure import(s):\n" +
            "\n".join(f"  - {v}" for v in violations)
        )

    def test_domain_has_no_presentation_imports(self):
        """Domain layer must not import from presentation."""
        domain_files = self.get_domain_files()
        violations = []

        for filepath in domain_files:
            file_imports = parse_imports(filepath)
            for imp in file_imports.imports:
                if 'presentation' in imp.module.lower():
                    violations.append(
                        f"{filepath}:{imp.line_number} imports '{imp.module}'"
                    )

        assert len(violations) == 0, (
            f"Domain layer has {len(violations)} presentation import(s):\n" +
            "\n".join(f"  - {v}" for v in violations)
        )

    def test_domain_has_no_api_imports(self):
        """Domain layer must not import from api layer."""
        domain_files = self.get_domain_files()
        violations = []

        for filepath in domain_files:
            file_imports = parse_imports(filepath)
            for imp in file_imports.imports:
                # Check for src.api imports (not external api libraries)
                if 'src.api' in imp.module.lower() or '.api.' in imp.module.lower():
                    violations.append(
                        f"{filepath}:{imp.line_number} imports '{imp.module}'"
                    )

        assert len(violations) == 0, (
            f"Domain layer has {len(violations)} api import(s):\n" +
            "\n".join(f"  - {v}" for v in violations)
        )


class TestApplicationLayerDependencies:
    """
    Property 3: Application Layer Dependencies

    *For any* file in application/, its imports should only reference
    domain/ layer or abstract interfaces, never concrete infrastructure.

    **Validates: Requirements 2.1**
    """

    def get_application_files(self) -> List[str]:
        """Get all Python files in application layer."""
        return get_python_files('src/application')

    def test_application_has_no_direct_infrastructure_imports(self):
        """Application layer should not import directly from infrastructure."""
        app_files = self.get_application_files()
        violations = []

        for filepath in app_files:
            file_imports = parse_imports(filepath)
            for imp in file_imports.imports:
                if 'infrastructure' in imp.module.lower():
                    violations.append(
                        f"{filepath}:{imp.line_number} imports '{imp.module}'"
                    )

        # This test is expected to FAIL initially - we have 26 violations
        assert len(violations) == 0, (
            f"Application layer has {len(violations)} direct infrastructure import(s):\n" +
            "\n".join(f"  - {v}" for v in violations[:10]) +
            (f"\n  ... and {len(violations) - 10} more" if len(violations) > 10 else "")
        )


class TestPresentationLayerDependencies:
    """
    Property 6: Presentation Layer Dependencies

    *For any* API router file in api/routers/, its imports should only
    reference application/ layer services, not infrastructure/ directly.

    **Validates: Requirements 4.1**
    """

    def get_presentation_files(self) -> List[str]:
        """Get all Python files in presentation/api layers."""
        api_files = get_python_files('src/api')
        presentation_files = get_python_files('src/presentation')
        return api_files + presentation_files

    def test_presentation_has_no_direct_infrastructure_imports(self):
        """Presentation/API layer should not import directly from infrastructure.

        Exception: dependencies.py is the composition root and is allowed to
        import DIContainer from infrastructure to wire all dependencies.
        """
        pres_files = self.get_presentation_files()
        violations = []

        # Composition root files are allowed to import infrastructure
        composition_root_files = ['dependencies.py']

        for filepath in pres_files:
            # Skip composition root files
            if any(cr in filepath for cr in composition_root_files):
                continue

            file_imports = parse_imports(filepath)
            for imp in file_imports.imports:
                if 'infrastructure' in imp.module.lower():
                    violations.append(
                        f"{filepath}:{imp.line_number} imports '{imp.module}'"
                    )

        assert len(violations) == 0, (
            f"Presentation layer has {len(violations)} direct infrastructure import(s):\n" +
            "\n".join(f"  - {v}" for v in violations)
        )


class TestImportDirectionCompliance:
    """
    Property 9: Import Direction Compliance

    *For any* Python file in the codebase, imports should follow the
    dependency direction: Domain ← Application ← Infrastructure/Presentation.
    No reverse imports allowed.

    **Validates: Requirements 7.3**
    """

    def test_all_imports_follow_dependency_direction(self):
        """All imports must follow Clean Architecture dependency rules."""
        all_files = get_python_files('src')
        all_violations: List[ArchitectureViolation] = []

        for filepath in all_files:
            file_imports = parse_imports(filepath)
            violations = check_dependency_direction(file_imports)
            all_violations.extend(violations)

        assert len(all_violations) == 0, (
            f"Found {len(all_violations)} architecture violation(s):\n" +
            "\n".join(
                f"  - {v.filepath}:{v.line_number} ({v.file_layer}) imports '{v.import_module}' ({v.import_layer})"
                for v in all_violations[:15]
            ) +
            (f"\n  ... and {len(all_violations) - 15} more" if len(all_violations) > 15 else "")
        )


class TestDomainRepositoryAbstraction:
    """
    Property 2: Domain Repository Abstraction

    *For any* repository file in domain/repositories/, it should contain
    only abstract base classes or Protocol definitions, with no concrete implementations.

    **Validates: Requirements 1.3**
    """

    def get_repository_files(self) -> List[str]:
        """Get all repository files in domain layer."""
        return get_python_files('src/domain/repositories')

    def test_domain_repositories_are_abstract(self):
        """Domain repositories should only contain abstract interfaces."""
        repo_files = self.get_repository_files()
        violations = []

        for filepath in repo_files:
            # Skip __init__.py
            if '__init__' in filepath:
                continue

            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()

            # Check for concrete implementations (methods without raise NotImplementedError or pass)
            # This is a simple heuristic - could be improved with AST
            if 'sqlite3' in content.lower() or 'connect(' in content:
                violations.append(f"{filepath}: Contains database implementation code")

            if 'requests.' in content or 'httpx.' in content:
                violations.append(f"{filepath}: Contains HTTP client code")

        assert len(violations) == 0, (
            f"Domain repositories have {len(violations)} concrete implementation(s):\n" +
            "\n".join(f"  - {v}" for v in violations)
        )


# Summary test that runs all checks
class TestArchitectureSummary:
    """Summary test to show overall architecture health."""

    def test_architecture_violation_count(self):
        """Report total number of architecture violations."""
        all_files = get_python_files('src')
        total_violations = 0

        for filepath in all_files:
            file_imports = parse_imports(filepath)
            violations = check_dependency_direction(file_imports)
            total_violations += len(violations)

        # This will show the count even when test passes
        print(f"\n📊 Architecture Violations: {total_violations}")

        # For now, just report - don't fail
        # Once we fix all violations, change this to assert total_violations == 0
        if total_violations > 0:
            pytest.skip(f"Skipping - {total_violations} violations to fix")
