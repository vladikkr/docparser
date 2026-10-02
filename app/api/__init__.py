"""HTTP layer: routers, dependencies and the versioned API surface.

This package carries an `__init__.py` like every other one under `app/`. As a
namespace package it imported fine, but the inconsistency confused mypy into
resolving `app/api/v1/router.py` as both `v1.router` and `app.api.v1.router`
and refused to check anything, and it hides the package from setuptools.
"""
