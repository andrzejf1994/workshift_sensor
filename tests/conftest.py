"""Pytest configuration and shared fixtures."""
import sys
from pathlib import Path

# Add custom_components to sys.path
custom_components_path = Path(__file__).parent.parent
sys.path.insert(0, str(custom_components_path))
