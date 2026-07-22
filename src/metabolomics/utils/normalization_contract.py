"""Shared Step 3 normalization method contract."""

DEFAULT_NORMALIZATION_METHOD = "PQN"

STEP3_METHOD_OPTIONS = (
    ("PQN — urine dilution", "PQN"),
    ("SpecNorm — tissue reference", "SpecNorm"),
)

METHOD_ALIASES = {
    "PQN": "PQN",
    "SPECNORM": "SpecNorm",
    "SPEC_NORM": "SpecNorm",
    "SPECNORM+PQN": "SpecNorm_PQN",
    "SPECNORM_PQN": "SpecNorm_PQN",
    "SPECNORM PQN": "SpecNorm_PQN",
}

NORMALIZATION_SUMMARY_SHEETS = {
    "PQN": "PQN_summary",
    "SpecNorm": "SpecNorm_summary",
    "SpecNorm_PQN": "SpecNorm_PQN_summary",
}


def canonicalize_normalization_method(method_name):
    """Normalize user-facing and legacy method names to internal names."""
    if method_name is None:
        method_name = DEFAULT_NORMALIZATION_METHOD
    raw_method = str(method_name).strip()
    key = raw_method.upper().replace("-", "_")
    key = " ".join(key.split())
    return METHOD_ALIASES.get(key, raw_method)


def get_summary_sheet_name(method_name):
    """Return the Step 3 summary sheet name for the selected method."""
    canonical_method = canonicalize_normalization_method(method_name)
    return NORMALIZATION_SUMMARY_SHEETS.get(canonical_method, f"{canonical_method}_summary")
