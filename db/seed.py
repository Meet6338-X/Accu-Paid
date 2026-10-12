"""Deterministic SQLite seed: 20 employees, 60 payroll rows, 15 vendor invoices.

Formulas (configurable per tenant — these are weekend-build defaults):
  gross   = round(ctc / 12)
  pf      = min(1800, round(gross * 0.12))
  esi     = round(gross * 0.0075) if gross <= 21000 else 0
  tds     = round(gross * 0.10) if ctc > 1_000_000 else round(gross * 0.05)
  lop_ded = round(gross / 30 * lop_days)
  ot_pay  = round(gross / 240 * overtime_hrs * 1.5)
  net     = gross - tds - pf - esi - lop_ded + ot_pay

Injected demo anomalies:
  EMP_042 Mar: overtime missing (0 vs 8h) -> ~INR 4,200 dry-run diff (AUTO_OK, cited).
  EMP_025 Mar: overtime missing (0 vs 10h) -> ~INR 7,800 net drop (forces needs_approval).

Usage:
  python db/seed.py [--db accupaid.db]
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from db.models import Base, Employee, PayrollRow, VendorInvoice

MONTHS = ["2026-01", "2026-02", "2026-03"]

EMPLOYEES: list[tuple[str, str, str, int, str]] = [
    ("EMP_007", "Aarav Sharma", "Engg", 1440000, "XXXX-XXXX-1107"),
    ("EMP_012", "Priya Verma", "HR", 720000, "XXXX-XXXX-1112"),
    ("EMP_018", "Rohan Gupta", "Sales", 960000, "XXXX-XXXX-1118"),
    ("EMP_021", "Sneha Iyer", "Ops", 540000, "XXXX-XXXX-1121"),
    ("EMP_025", "Vikram Singh", "Engg", 1800000, "XXXX-XXXX-1125"),
    ("EMP_031", "Anjali Patel", "Finance", 1200000, "XXXX-XXXX-1131"),
    ("EMP_033", "Karan Mehta", "Sales", 840000, "XXXX-XXXX-1133"),
    ("EMP_042", "Divya Nair", "Engg", 1320000, "XXXX-XXXX-1142"),  # demo query employee
    ("EMP_045", "Arjun Reddy", "Ops", 600000, "XXXX-XXXX-1145"),
    ("EMP_051", "Kavya Joshi", "HR", 660000, "XXXX-XXXX-1151"),
    ("EMP_058", "Manoj Kumar", "Ops", 480000, "XXXX-XXXX-1158"),
    ("EMP_063", "Ritu Agarwal", "Finance", 1500000, "XXXX-XXXX-1163"),
    ("EMP_067", "Suresh Yadav", "Sales", 780000, "XXXX-XXXX-1167"),
    ("EMP_072", "Pooja Mishra", "Engg", 2100000, "XXXX-XXXX-1172"),
    ("EMP_078", "Amit Desai", "Finance", 1680000, "XXXX-XXXX-1178"),
    ("EMP_084", "Neha Kulkarni", "HR", 690000, "XXXX-XXXX-1184"),
    ("EMP_089", "Rahul Jain", "Engg", 1560000, "XXXX-XXXX-1189"),
    ("EMP_095", "Fatima Khan", "Ops", 570000, "XXXX-XXXX-1195"),
    ("EMP_101", "Sanjay Bose", "Sales", 900000, "XXXX-XXXX-1201"),
    ("EMP_110", "Deepak Rao", "Engg", 2400000, "XXXX-XXXX-1210"),
]

# emp_id -> [(lop, ot), (lop, ot), (lop, ot)] for 2026-01, 02, 03. Default: [(0,4)]*3.
BASE: dict[str, list[tuple[int, int]]] = {
    "EMP_042": [(0, 8), (0, 8), (0, 0)],
    "EMP_012": [(0, 0), (3, 0), (0, 2)],
    "EMP_025": [(0, 10), (0, 10), (0, 0)],
    "EMP_058": [(2, 0), (0, 4), (1, 0)],
}

INVOICES: list[tuple[str, str, int, int, str, bool, str]] = [
    ("INV-2041", "Sharma Office Supplies", 45000, 45200, "27ABCDE1234F1Z5", False, "PENDING"),
    ("INV-2042", "Kumar Logistics", 120000, 134500, "29FGHIJ5678K2Z3", False, "PENDING"),
    ("INV-2043", "Nair IT Services", 80000, 80000, "32KLMNO9012P3Z7", True, "HOLD"),
    ("INV-2044", "Gupta Traders", 25000, 24800, "27PQRST3456A4Z1", False, "PENDING"),
    ("INV-2045", "Verma Catering", 60000, 73500, "06UVWXY7890B5Z9", True, "HOLD"),
    ("INV-2046", "Reddy Transport", 30000, 30000, "36ZABCD1111C6Z2", False, "APPROVED"),
    ("INV-2047", "Joshi Print House", 15000, 15250, "27EFGHJ2222D1Z8", True, "HOLD"),
    ("INV-2048", "Mishra Electricals", 95000, 94800, "09KLMNP3333E2Z4", False, "PENDING"),
    ("INV-2049", "Khan Fabrics", 200000, 218000, "06QRSTU4444F3Z6", False, "PENDING"),
    ("INV-2050", "Bose Packaging", 40000, 40000, "19UVWVA5555G4Z5", True, "HOLD"),
    ("INV-2051", "Agarwal Stationery", 18000, 17900, "08BCDEA6666H5Z7", False, "PAID"),
    ("INV-2052", "Desai Hardware", 55000, 55000, "24CDEFB7777J6Z3", False, "PENDING"),
    ("INV-2053", "Kulkarni Foods", 33000, 33100, "27DEFGC8888K1Z9", True, "HOLD"),
    ("INV-2054", "Yadav Construction", 70000, 69900, "09EFGHD9999L2Z1", False, "PENDING"),
    ("INV-2055", "Rao Consulting", 110000, 110500, "29FGHEJ0001M3Z5", False, "PENDING"),
]


def payroll_row(ctc: int, lop: int, ot: int) -> tuple[int, int, int, int, int, float, int]:
    gross = round(ctc / 12)
    pf = min(1800, round(gross * 0.12))
    esi = round(gross * 0.0075) if gross <= 21000 else 0
    tds = round(gross * 0.10) if ctc > 1000000 else round(gross * 0.05)
    net = gross - tds - pf - esi - round(gross / 30 * lop) + round(gross / 240 * ot * 1.5)
    return gross, tds, pf, esi, lop, float(ot), net


def seed(db_path: str = "accupaid.db") -> dict[str, int]:
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        for emp_id, name, dept, ctc, bank in EMPLOYEES:
            s.add(Employee(emp_id=emp_id, name=name, dept=dept, ctc=ctc, bank_redacted=bank))
        for emp_id, _name, _dept, ctc, _bank in EMPLOYEES:
            sched = BASE.get(emp_id, [(0, 4), (0, 4), (0, 4)])
            for month, (lop, ot) in zip(MONTHS, sched):
                gross, tds, pf, esi, lop_days, ot_hrs, net = payroll_row(ctc, lop, ot)
                s.add(
                    PayrollRow(
                        emp_id=emp_id, month=month, gross=gross, tds=tds, pf=pf,
                        esi=esi, lop_days=lop_days, overtime_hrs=ot_hrs, net=net,
                    )
                )
        for inv_id, vendor, po, invoiced, gstin, mismatch, status in INVOICES:
            s.add(
                VendorInvoice(
                    invoice_id=inv_id, vendor=vendor, po_amount=po,
                    invoiced_amount=invoiced, gstin=gstin,
                    gst_mismatch=mismatch, status=status,
                )
            )
        s.commit()
    return {
        "employees": len(EMPLOYEES),
        "payroll_rows": len(EMPLOYEES) * len(MONTHS),
        "invoices": len(INVOICES),
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="accupaid.db")
    args = ap.parse_args()
    print(seed(args.db))
