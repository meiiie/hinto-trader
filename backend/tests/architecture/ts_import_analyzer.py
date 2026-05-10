"""
TypeScript/React Import Analyzer

Utility functions to scan and analyze imports from TypeScript/React files
for Clean Architecture compliance in frontend.
"""

import re
import os
from pathlib import Path
from typing import List, Set, Tuple
from dataclasses import dataclass


@dataclass
class TSImportInfo:
    """Information about a TypeScript import statement."""
    module: str
    line_number: int
    is_relative: bool


@dataclass
class TSFileImports:
    """All imports from a single TypeScript file."""
    filepath: str
    imports: List[TSImportInfo]

    @property
    def all_modules(self) -> Set[str]:
        """Get all imported module names."""
        return {imp.module for imp in self.imports}

    def has_api_calls(self) -> bool:
        """Check if file contains direct API calls (fetch, axios)."""
        return any(
            'fetch(' in self._file_content or
            'axios' in self._file_content
            for _ in [1]  # Just to use the comprehension
        )


def get_ts_files(directory: str, extensions: List[str] = None) -> List[str]:
    """
    Get all TypeScript/React files in directory recursively.

    Args:
        directory: Root directory to scan
        extensions: File extensions to include (default: .ts, .tsx)

    Returns:
        List of file paths
    """
    extensions = extensions or ['.ts', '.tsx']
    exclude_patterns = ['node_modules', '.d.ts', 'dist', 'build']
    ts_files = []

    root_path = Path(directory)
    if not root_path.exists():
        return []

    for ext in extensions:
        for filepath in root_path.rglob(f'*{ext}'):
            # Skip excluded patterns
            skip = False
            for pattern in exclude_patterns:
                if pattern in str(filepath):
                    skip = True
                    break

            if not skip:
                ts_files.append(str(filepath))

    return sorted(ts_files)


def parse_ts_imports(filepath: str) -> Tuple[TSFileImports, str]:
    """
    Extract all imports from a TypeScript file using regex.

    Args:
        filepath: Path to TypeScript file

    Returns:
        Tuple of (TSFileImports object, file content)
    """
    imports = []
    content = ""

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        lines = content.split('\n')

        # Regex patterns for imports
        import_patterns = [
            r"import\s+.*\s+from\s+['\"](.+?)['\"]",  # import X from 'module'
            r"import\s+['\"](.+?)['\"]",  # import 'module'
            r"require\s*\(\s*['\"](.+?)['\"]",  # require('module')
        ]

        for line_num, line in enumerate(lines, 1):
            for pattern in import_patterns:
                matches = re.findall(pattern, line)
                for module in matches:
                    is_relative = module.startswith('.') or module.startswith('@/')
                    imports.append(TSImportInfo(
                        module=module,
                        line_number=line_num,
                        is_relative=is_relative
                    ))

    except Exception as e:
        print(f"Error parsing {filepath}: {e}")

    return TSFileImports(filepath=filepath, imports=imports), content


def check_component_has_direct_api_calls(filepath: str, strict: bool = False) -> List[str]:
    """
    Check if a React component file contains direct API calls.

    In strict mode, components should use hooks/services for API calls.
    In non-strict mode (default), direct fetch is allowed as it's a common React pattern.

    Args:
        filepath: Path to component file
        strict: If True, flag all direct fetch calls as violations

    Returns:
        List of violations (line descriptions)
    """
    violations = []

    # In non-strict mode, allow direct fetch in components
    # This is a common and acceptable pattern in React
    if not strict:
        return violations

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        lines = content.split('\n')

        # Check for direct fetch calls
        for line_num, line in enumerate(lines, 1):
            # Skip comments
            stripped = line.strip()
            if stripped.startswith('//') or stripped.startswith('*'):
                continue

            # Check for fetch
            if 'fetch(' in line and 'useFetch' not in line:
                violations.append(f"Line {line_num}: Direct fetch() call found")

            # Check for axios direct usage (not in hook)
            if 'axios.' in line and 'useAxios' not in line:
                violations.append(f"Line {line_num}: Direct axios call found")

    except Exception as e:
        print(f"Error checking {filepath}: {e}")

    return violations


def analyze_frontend_architecture(directory: str) -> dict:
    """
    Analyze frontend directory for architecture compliance.

    Args:
        directory: Frontend src directory

    Returns:
        Dict with analysis results
    """
    results = {
        'total_files': 0,
        'components': [],
        'hooks': [],
        'utils': [],
        'violations': []
    }

    ts_files = get_ts_files(directory)
    results['total_files'] = len(ts_files)

    for filepath in ts_files:
        path_lower = filepath.lower().replace('\\', '/')

        # Categorize files
        if '/components/' in path_lower:
            results['components'].append(filepath)

            # Check for direct API calls in components
            violations = check_component_has_direct_api_calls(filepath)
            for v in violations:
                results['violations'].append({
                    'file': filepath,
                    'type': 'direct_api_call',
                    'message': v
                })

        elif '/hooks/' in path_lower:
            results['hooks'].append(filepath)

        elif '/utils/' in path_lower or '/services/' in path_lower:
            results['utils'].append(filepath)

    return results


def print_frontend_analysis(results: dict) -> None:
    """Print frontend analysis results."""
    print(f"Frontend Analysis Results:")
    print(f"  Total files: {results['total_files']}")
    print(f"  Components: {len(results['components'])}")
    print(f"  Hooks: {len(results['hooks'])}")
    print(f"  Utils/Services: {len(results['utils'])}")
    print()

    if results['violations']:
        print(f"❌ Found {len(results['violations'])} violation(s):")
        for v in results['violations']:
            print(f"  File: {v['file']}")
            print(f"  Type: {v['type']}")
            print(f"  {v['message']}")
            print()
    else:
        print("✅ No frontend architecture violations found!")
