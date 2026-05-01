"""
Adapters for converting data between pipeline stages.

- preprocessing_to_dnp: ms-preprocessing-toolkit → DNP format
- dnp_to_metaboanalyst: DNP → Metaboanalyst_clone format

The GUI imports adapter modules directly so the package stays lightweight and
does not import openpyxl/pandas at package import time.
"""

__all__ = []
