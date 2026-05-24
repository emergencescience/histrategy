#!/usr/bin/env bash
# Install git pre-commit hooks for histrategy
set -e

echo "==> Installing pre-commit hooks..."
pip install pre-commit ruff
pre-commit install

echo "==> Running ruff lint check..."
ruff check histrategy/ --fix

echo ""
echo "✅ Hooks installed. Ruff will run on every commit."
echo "   Pytest runs on 'git push' (not on commit — tests are heavier)."
echo ""
echo "To run tests manually:  pytest tests/ -q"
echo "To check lint manually:  ruff check histrategy/"
