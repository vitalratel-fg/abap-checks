"""SAP's own facts the checks need and abaplint cannot resolve offline.

Shared across projects because they are SAP's, not a project's. A project
adds or overrides entries in abapcheck.toml ([cds.keys], [ddic.standard],
[cds.sap_numbered]); a fact that turns out wrong on a release is fixed HERE,
with where it was confirmed.

Confirm each entry in SE11 / ADT on the target system before relying on it:
on-premise releases differ from the S/4HANA Cloud sources these were read
from where the comment says so.
"""

# Keys of SAP tables and released views a package joins `to one`, client
# left out (check_cds `toone`). Lowercase.
KEYS = {
    "i_companycode": {"companycode"},
    "i_plant": {"plant"},
    "i_valuationarea": {"valuationarea"},
    "i_productplantbasic": {"product", "plant"},
    "i_product": {"product"},
    "i_glaccountinchartofaccounts": {"chartofaccounts", "glaccount"},
    # Field order of its generated table IFIFYEARPERIODCC; key and element
    # names as published for S/4HANA Cloud. Confirm on-premise in ADT.
    "i_fiscalyearperiodforcmpnycode": {"companycode", "fiscalyear", "fiscalperiod"},
    "konp": {"knumh", "kopos"},
    "mbew": {"matnr", "bwkey", "bwtar"},
    "mbv_mbew": {"matnr", "bwkey", "bwtar"},
    "mbewh": {"matnr", "bwkey", "bwtar", "lfgja", "lfmon"},
    "mbv_mbewh": {"matnr", "bwkey", "bwtar", "lfgja", "lfmon"},
    "mara": {"matnr"},
    "marc": {"matnr", "werks"},
    "t001": {"bukrs"},
    "t001w": {"werks"},
}

# Numbered element families that are SAP's own, not a package's slots
# (check_cds `slots`): element stem -> where SAP numbers it.
NUMBERED = {
    "additionalquantity": "ACDOCA QUANT1/QUANT2",
    "additionalunit": "ACDOCA QUNIT1/QUNIT2",
}

# SAP standard data elements a generated table may use, with the type a
# serialised DD03P carries beside the name (make_ddic). abaplint bundles no
# SAP DDIC, so without this it cannot parse a single table; the system, which
# has them, ignores the fallback and uses the data element.
STANDARD = {
    "MANDT": ("CLNT", 3, 0),
    "MATNR": ("CHAR", 40, 0),
    "WERKS_D": ("CHAR", 4, 0),
    "BUKRS": ("CHAR", 4, 0),
    "GJAHR": ("NUMC", 4, 0),
    "POPER": ("NUMC", 3, 0),
    "MONAT": ("NUMC", 2, 0),
    "TIMESTAMPL": ("DEC", 21, 7),
    "TIMESTAMP": ("DEC", 15, 0),
    "PRCTR": ("CHAR", 10, 0),
    "KOSTL": ("CHAR", 10, 0),
    "LIFNR": ("CHAR", 10, 0),
    "KUNNR": ("CHAR", 10, 0),
    "WAERS": ("CUKY", 5, 0),
    "MEINS": ("UNIT", 3, 0),
    "LBKUM": ("QUAN", 13, 3),
    "SALK3": ("CURR", 13, 2),
    "SYUNAME": ("CHAR", 12, 0),
    "XFELD": ("CHAR", 1, 0),
    "BOOLE_D": ("CHAR", 1, 0),
    "ABAP_BOOLEAN": ("CHAR", 1, 0),
    "SYSUUID_X16": ("RAW", 16, 0),
    "DATS": ("DATS", 8, 0),
    "TIMS": ("TIMS", 6, 0),
}
