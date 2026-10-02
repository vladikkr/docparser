"""DocParser: parsing of primary documents into structured data.

The package root carries an `__init__.py` because without it `app` is only a
namespace package, and that made mypy resolve `app/api/v1/router.py` under two
different module names and refuse to check the project at all.
"""
