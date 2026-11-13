"""The CDS rules of check_cds.py, one module per kind of rule. check_cds.py
holds the table that runs them, in its documented order, and the context
they read."""




# Rules that need a project fact return this when it is unset.
NEEDS = {
    "names": "[cds.names] ddls",
    "legacy": "[cds] legacy",
    "sources": "[cds] forbidden_sources",
    "budget": "[cds] budget",
    "basecol": "[cds] filter_fields",
    "mandatory": "[cds.mandatory]",
    "elements": "[cds] consumption",
    "abapfree": "[cds] abapfree = true",
}
