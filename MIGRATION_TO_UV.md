# Migration from Poetry to uv

This project has been migrated from Poetry to uv for faster dependency management and better performance.

## For Contributors

If you were previously contributing to this project using Poetry, here's how to migrate:

### 1. Remove Poetry artifacts
```bash
# Remove the old virtual environment (if using poetry's default location)
rm -rf .venv
# Remove poetry.lock (now replaced by uv.lock)
rm poetry.lock
```

### 2. Install uv
```bash
pip install uv
```

### 3. Set up the development environment
```bash
# Install all dependencies including development extras
uv sync --all-extras

# Install pre-commit hooks
uv run inv install-hooks
```

### 4. Common command translations

| Poetry Command                   | uv Equivalent                                                                 |
| -------------------------------- | ----------------------------------------------------------------------------- |
| `poetry install`                 | `uv sync`                                                                     |
| `poetry add package`             | `uv add package`                                                              |
| `poetry add --group dev package` | `uv add --dev package`                                                        |
| `poetry run command`             | `uv run command`                                                              |
| `poetry shell`                   | `source .venv/bin/activate` (Linux/Mac) or `.venv\Scripts\activate` (Windows) |
| `poetry build`                   | `uv build`                                                                    |
| `poetry publish`                 | `uv publish`                                                                  |

### 5. Running tasks
All invoke tasks now use uv instead of poetry:
```bash
# Run tests
uv run inv tests

# Format code
uv run inv format

# Run linting
uv run inv lint

# Type checking
uv run inv mypy
```

## For End Users

If you were installing the package from source using Poetry, now use:

```bash
git clone https://github.com/BoPeng/ai-marketplace-monitor
cd ai-marketplace-monitor
uv sync
```

The published package on PyPI remains the same:
```bash
pip install ai-marketplace-monitor
```

## Benefits of uv

- **Faster**: uv is significantly faster than Poetry for dependency resolution and installation
- **Better caching**: More efficient caching mechanism
- **Simpler**: Fewer configuration files and simpler setup
- **Standard**: Uses standard Python packaging (pyproject.toml) without Poetry-specific extensions