"""Indian GST engine.

Decides between intra-state (CGST + SGST) and inter-state (IGST) tax based on
the supplier's state and the place of supply, both expressed as 2-digit GST
state codes. The state code is the first two digits of a GSTIN.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

# GST state code -> state name (first two digits of a GSTIN)
STATE_CODES: dict[str, str] = {
    "01": "Jammu & Kashmir",
    "02": "Himachal Pradesh",
    "03": "Punjab",
    "04": "Chandigarh",
    "05": "Uttarakhand",
    "06": "Haryana",
    "07": "Delhi",
    "08": "Rajasthan",
    "09": "Uttar Pradesh",
    "10": "Bihar",
    "11": "Sikkim",
    "12": "Arunachal Pradesh",
    "13": "Nagaland",
    "14": "Manipur",
    "15": "Mizoram",
    "16": "Tripura",
    "17": "Meghalaya",
    "18": "Assam",
    "19": "West Bengal",
    "20": "Jharkhand",
    "21": "Odisha",
    "22": "Chhattisgarh",
    "23": "Madhya Pradesh",
    "24": "Gujarat",
    "26": "Dadra & Nagar Haveli and Daman & Diu",
    "27": "Maharashtra",
    "29": "Karnataka",
    "30": "Goa",
    "31": "Lakshadweep",
    "32": "Kerala",
    "33": "Tamil Nadu",
    "34": "Puducherry",
    "35": "Andaman & Nicobar Islands",
    "36": "Telangana",
    "37": "Andhra Pradesh",
    "38": "Ladakh",
}

TWO_PLACES = Decimal("0.01")


def _round(value: Decimal) -> Decimal:
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def state_code_from_gstin(gstin: str | None) -> str | None:
    """Extract the 2-digit state code from a GSTIN, if valid."""
    if not gstin:
        return None
    code = gstin.strip()[:2]
    return code if code in STATE_CODES else None


def state_name(code: str | None) -> str | None:
    return STATE_CODES.get(code) if code else None


def resolve_place_of_supply(
    explicit: str | None,
    client_gstin: str | None,
    supplier_state: str | None,
) -> str | None:
    """Pick the place of supply: explicit value, else client's state, else
    fall back to the supplier's own state (treated as intra-state)."""
    if explicit and explicit in STATE_CODES:
        return explicit
    from_client = state_code_from_gstin(client_gstin)
    if from_client:
        return from_client
    return supplier_state


@dataclass
class GstBreakdown:
    subtotal: Decimal
    cgst: Decimal
    sgst: Decimal
    igst: Decimal
    tax_total: Decimal
    total: Decimal
    tax_type: str  # "cgst_sgst" | "igst"
    place_of_supply: str | None

    def as_dict(self) -> dict:
        return {
            "subtotal": self.subtotal,
            "cgst": self.cgst,
            "sgst": self.sgst,
            "igst": self.igst,
            "tax_total": self.tax_total,
            "total": self.total,
            "tax_type": self.tax_type,
            "place_of_supply": self.place_of_supply,
        }


def compute_gst(
    subtotal: Decimal,
    tax_rate: Decimal,
    supplier_state: str | None,
    place_of_supply: str | None,
) -> GstBreakdown:
    """Split tax into CGST+SGST (intra-state) or IGST (inter-state).

    - Intra-state (supplier_state == place_of_supply): CGST = SGST = rate / 2.
    - Inter-state or unknown supplier/place: full rate as IGST.
    """
    subtotal = _round(Decimal(subtotal))
    rate = Decimal(tax_rate)

    intra_state = (
        supplier_state is not None
        and place_of_supply is not None
        and supplier_state == place_of_supply
    )

    if intra_state:
        half = _round(subtotal * rate / 2)
        cgst, sgst, igst = half, half, Decimal("0.00")
        tax_type = "cgst_sgst"
    else:
        igst = _round(subtotal * rate)
        cgst = sgst = Decimal("0.00")
        tax_type = "igst"

    tax_total = _round(cgst + sgst + igst)
    total = _round(subtotal + tax_total)
    return GstBreakdown(
        subtotal=subtotal,
        cgst=cgst,
        sgst=sgst,
        igst=igst,
        tax_total=tax_total,
        total=total,
        tax_type=tax_type,
        place_of_supply=place_of_supply,
    )
