"""SQLAlchemy models — SQLite seed for weekend build, Postgres-ready for pilot.

Tables: employees (20), payroll_rows (60), vendor_invoices (15), committed_actions (idempotency ledger).
Bank/PAN/Aadhaar are never stored raw — only redacted tails.
"""

from sqlalchemy import Boolean, CheckConstraint, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(primary_key=True)
    emp_id: Mapped[str] = mapped_column(String(16), unique=True, index=True)  # ^[A-Z]+_[0-9]{3,6}$
    name: Mapped[str] = mapped_column(String(80))
    dept: Mapped[str] = mapped_column(String(16))  # Engg|HR|Sales|Ops|Finance
    ctc: Mapped[int] = mapped_column(Integer)  # annual INR
    bank_redacted: Mapped[str] = mapped_column(String(32))  # tail only, e.g. XXXX-XXXX-1142

    rows: Mapped[list["PayrollRow"]] = relationship(back_populates="emp", cascade="all,delete")


class PayrollRow(Base):
    __tablename__ = "payroll_rows"

    id: Mapped[int] = mapped_column(primary_key=True)
    emp_id: Mapped[str] = mapped_column(ForeignKey("employees.emp_id"), index=True)
    month: Mapped[str] = mapped_column(String(7), index=True)  # ^\d{4}-\d{2}$
    gross: Mapped[int] = mapped_column(Integer)
    tds: Mapped[int] = mapped_column(Integer)
    pf: Mapped[int] = mapped_column(Integer)
    esi: Mapped[int] = mapped_column(Integer)
    lop_days: Mapped[int] = mapped_column(Integer, default=0)
    overtime_hrs: Mapped[float] = mapped_column(Float, default=0)
    net: Mapped[int] = mapped_column(Integer)

    emp: Mapped[Employee] = relationship(back_populates="rows")

    __table_args__ = (
        UniqueConstraint("emp_id", "month", name="uq_emp_month"),
        CheckConstraint("gross>0 AND tds>=0 AND pf>=0 AND esi>=0 AND net>0", name="ck_amounts"),
    )


class VendorInvoice(Base):
    __tablename__ = "vendor_invoices"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[str] = mapped_column(String(16), unique=True, index=True)  # ^INV-[0-9]{4,6}$
    vendor: Mapped[str] = mapped_column(String(80))
    po_amount: Mapped[int] = mapped_column(Integer)
    invoiced_amount: Mapped[int] = mapped_column(Integer)
    gstin: Mapped[str] = mapped_column(String(15))
    gst_mismatch: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="PENDING")  # PENDING|HOLD|APPROVED|PAID


class CommittedAction(Base):
    """Idempotency ledger: (run_id, tool, args_hash) is unique — double-approve is a no-op."""

    __tablename__ = "committed_actions"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    tool: Mapped[str] = mapped_column(String(32))
    args_hash: Mapped[str] = mapped_column(String(64))
    result: Mapped[str] = mapped_column(String(2000))  # JSON snapshot
    approver: Mapped[str] = mapped_column(String(120), default="")

    __table_args__ = (UniqueConstraint("run_id", "tool", "args_hash", name="uq_idempotency"),)
