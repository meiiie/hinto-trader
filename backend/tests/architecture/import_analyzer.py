"""
Import Analyzer - Architecture Analysis Tool

Utility functions to scan and analyze imports from Python files
using AST (Abstract Syntax Tree) for Clean Architecture compliance.
"""

import ast
import os
from pathlib import Path
from typing import List, Set, Dict, Tuple
from dataclasses import dataclass


@dataclass
class ImportInfo:
    """Information about an import statement."""
    module: str
    names: List[str]
    is_from_import: bool
    line_number: int


@dataclass
class FileImports:
    """All imports from a single file."""
    filepath: str
    imports: List[ImportInfo]

    @property
    def all_modules(self) -> Set[str]:
        """Get all imported module names."""
        return {imp.module for imp in self.imports}

    def has_import_from(self, *patterns: str) -> bool:
        """Check if file imports from any of the given patterns."""
        for module in self.all_modules:
            for pattern in patterns:
                if pattern in module:
                    return True
        return False


def get_python_files(directory: str, exclude_patterns: List[str] = None) -> List[str]:
    """
    Get all Python files in directory recursively.

    Args:
        directory: Root directory to scan
        exclude_patterns: Patterns to exclude (e.g., ['__pycache__', 'test_'])

    Returns:
        List of Python file paths
    """
    exclude_patterns = exclude_patterns or ['__pycache__', '.pyc']
    python_files = []

    root_path = Path(directory)
    if not root_path.exists():
        return []

    for filepath in root_path.rglob('*.py'):
        # Skip excluded patterns
        skip = False
        for pattern in exclude_patterns:
            if pattern in str(filepath):
                skip = True
                break

        if not skip:
            python_files.append(str(filepath))

    return sorted(python_files)


def parse_imports(filepath: str, include_late_imports: bool = False) -> FileImports:
    """
    Extract all imports from a Python file using AST.

    Args:
        filepath: Path to Python file
        include_late_imports: If False, skip imports inside functions (late imports)

    Returns:
        FileImports object with all import information
    """
    imports = []

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            source = f.read()

        tree = ast.parse(source, filename=filepath)

        # Get module-level imports only (not inside functions/classes)
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(ImportInfo(
                        module=alias.name,
                        names=[alias.asname or alias.name],
                        is_from_import=False,
                        line_number=node.lineno
                    ))

            elif isinstance(node, ast.ImportFrom):
                module = node.module or ''
                names = [alias.name for alias in node.names]
                imports.append(ImportInfo(
                    module=module,
                    names=names,
                    is_from_import=True,
                    line_number=node.lineno
                ))

        # Optionally include late imports (inside functions)
        if include_late_imports:
            for node in ast.walk(tree):
                # Skip module-level nodes (already processed)
                if node in ast.iter_child_nodes(tree):
                    continue

                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.append(ImportInfo(
                            module=alias.name,
                            names=[alias.asname or alias.name],
                            is_from_import=False,
                            line_number=node.lineno
                        ))

                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ''
                    names = [alias.name for alias in node.names]
                    imports.append(ImportInfo(
                        module=module,
                        names=names,
                        is_from_import=True,
                        line_number=node.lineno
                    ))

    except SyntaxError as e:
        print(f"Syntax error in {filepath}: {e}")
    except Exception as e:
        print(f"Error parsing {filepath}: {e}")

    return FileImports(filepath=filepath, imports=imports)


def get_layer_from_path(filepath: str) -> str:
    """
    Determine which architectural layer a file belongs to.

    Args:
        filepath: Path to file

    Returns:
        Layer name: 'domain', 'application', 'infrastructure', 'presentation', 'api', or 'unknown'
    """
    path_lower = filepath.lower().replace('\\', '/')

    if '/domain/' in path_lower:
        return 'domain'
    elif '/application/' in path_lower:
        return 'application'
    elif '/infrastructure/' in path_lower:
        return 'infrastructure'
    elif '/presentation/' in path_lower:
        return 'presentation'
    elif '/api/' in path_lower:
        return 'api'
    else:
        return 'unknown'


def get_import_layer(module: str) -> str:
    """
    Determine which layer an import comes from.

    Args:
        module: Import module string

    Returns:
        Layer name or 'external' for third-party imports
    """
    module_lower = module.lower()

    # Check for src-relative imports
    if 'domain' in module_lower:
        return 'domain'
    elif 'application' in module_lower:
        return 'application'
    elif 'infrastructure' in module_lower:
        return 'infrastructure'
    elif 'presentation' in module_lower:
        return 'presentation'
    elif 'api' in module_lower and 'src.api' in module_lower:
        return 'api'
    else:
        return 'external'


@dataclass
class ArchitectureViolation:
    """Represents an architecture rule violation."""
    filepath: str
    file_layer: str
    import_module: str
    import_layer: str
    line_number: int
    rule: str
    message: str


def is_composition_root(filepath: str) -> bool:
    """
    Check if file is a composition root (allowed to import from infrastructure).

    Composition roots are entry points where dependencies are wired together.
    These files are allowed to import from infrastructure to set up DI.
    """
    composition_root_patterns = [
        'dependencies.py',      # FastAPI dependency injection
        'di_container.py',      # DI container itself
        'main.py',              # Application entry points
        'app.py',               # Streamlit/Flask app entry
        '__main__.py',          # Module entry points
    ]

    filename = os.path.basename(filepath).lower()
    return filename in composition_root_patterns


def check_dependency_direction(file_imports: FileImports) -> List[ArchitectureViolation]:
    """
    Check if imports follow Clean Architecture dependency rules.

    Rules:
    - Domain: No imports from application, infrastructure, presentation, api
    - Application: Only imports from domain (and external)
    - Infrastructure: Can import from domain, application
    - Presentation/API: Can import from application (not directly from infrastructure)
      - Exception: Composition roots (dependencies.py, app.py, main.py) are allowed

    Args:
        file_imports: FileImports object to check

    Returns:
        List of violations found
    """
    violations = []
    file_layer = get_layer_from_path(file_imports.filepath)

    # Composition roots are allowed to import from infrastructure
    if is_composition_root(file_imports.filepath):
        # Only check domain and application rules for composition roots
        # Skip presentation_dependencies rule
        pass

    for imp in file_imports.imports:
        import_layer = get_import_layer(imp.module)

        # Skip external imports
        if import_layer == 'external':
            continue

        violation = None

        # Domain layer rules
        if file_layer == 'domain':
            if import_layer in ['application', 'infrastructure', 'presentation', 'api']:
                violation = ArchitectureViolation(
                    filepath=file_imports.filepath,
                    file_layer=file_layer,
                    import_module=imp.module,
                    import_layer=import_layer,
                    line_number=imp.line_number,
                    rule='domain_independence',
                    message=f"Domain layer cannot import from {import_layer} layer"
                )

        # Application layer rules
        elif file_layer == 'application':
            if import_layer in ['infrastructure', 'presentation', 'api']:
                violation = ArchitectureViolation(
                    filepath=file_imports.filepath,
                    file_layer=file_layer,
                    import_module=imp.module,
                    import_layer=import_layer,
                    line_number=imp.line_number,
                    rule='application_dependencies',
                    message=f"Application layer should not import directly from {import_layer} layer"
                )

        # Presentation/API layer rules
        elif file_layer in ['presentation', 'api']:
            if import_layer == 'infrastructure':
                # Skip if this is a composition root (allowed to wire dependencies)
                if is_composition_root(file_imports.filepath):
                    continue

                violation = ArchitectureViolation(
                    filepath=file_imports.filepath,
                    file_layer=file_layer,
                    import_module=imp.module,
                    import_layer=import_layer,
                    line_number=imp.line_number,
                    rule='presentation_dependencies',
                    message=f"Presentation/API layer should not import directly from infrastructure layer"
                )

        if violation:
            violations.append(violation)

    return violations


def analyze_directory(directory: str) -> Tuple[List[FileImports], List[ArchitectureViolation]]:
    """
    Analyze all Python files in a directory for architecture compliance.

    Args:
        directory: Root directory to analyze

    Returns:
        Tuple of (all file imports, all violations)
    """
    all_imports = []
    all_violations = []

    python_files = get_python_files(directory)

    for filepath in python_files:
        file_imports = parse_imports(filepath)
        all_imports.append(file_imports)

        violations = check_dependency_direction(file_imports)
        all_violations.extend(violations)

    return all_imports, all_violations


def print_violations(violations: List[ArchitectureViolation]) -> None:
    """Print violations in a readable format."""
    if not violations:
        print("✅ No architecture violations found!")
        return

    print(f"❌ Found {len(violations)} architecture violation(s):\n")

    for v in violations:
        print(f"  File: {v.filepath}")
        print(f"  Layer: {v.file_layer}")
        print(f"  Line {v.line_number}: imports '{v.import_module}' ({v.import_layer})")
        print(f"  Rule: {v.rule}")
        print(f"  Message: {v.message}")
        print()
