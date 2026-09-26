"""Statement data for one policy's reconciliation document.

Following ``build_report`` (Stage 8): this is a read-only roll-up that runs a
few queries over the existing tables and returns a flat dict of money totals and
line items. It returns plain Python data (never ORM objects) so the same builder
can feed the HTML preview and the ReportLab PDF renderer without a live session.
"""
import datetime as dt
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy import select

from app.models.invoice import Invoice
from app.models.payment import Payment
from app.models.party import Party
from app.models.policy import Policy
from app.models.product import Product

# Money rounds to 2 decimals; a nullable/None column contributes 0.0 so an empty
# policy still renders a coherent statement rather than raising.
MONEY_FORMAT = "{:,.2f}"


def _positive_number(value) -> float:
    try:
        return float(value) if value else 0.0
    except (TypeError, ValueError):
        return 0.0


def _round_money(value: float) -> float:
    return round(value, 2)


def build_statement(db, *, policy_id: int) -> dict:
    """Collect the policy + billing data for one policy's statement.

    Returns a flat dict the renderer can consume. Raises ``ValueError`` for an
    unknown ``policy_id``.
    """
    policy = db.get(Policy, policy_id)
    if policy is None:
        raise ValueError(f"Unknown policy_id: {policy_id}")

    product = db.get(Product, policy.product_id) if policy.product_id is not None else None
    organization = (
        db.get(Party, policy.organization_id) if policy.organization_id else None
    )
    policyholder = (
        db.get(Party, policy.party_id) if policy.party_id is not None else None
    )

    invoices = db.scalars(
        select(Invoice).where(Invoice.policy_id == policy_id)
    ).all()

    statement_invoices = []
    total_invoiced = 0.0
    total_paid = 0.0
    for invoice in invoices:
        payments = db.scalars(
            select(Payment).where(Payment.invoice_id == invoice.id)
        ).all()
        paid = _positive_number(invoice.paid_amount)
        total_invoiced += _positive_number(invoice.total_amount)
        total_paid += paid
        statement_invoices.append(
            {
                "invoice_number": invoice.invoice_number,
                "status": invoice.status,
                "total_amount": _round_money(_positive_number(invoice.total_amount)),
                "paid_amount": _round_money(paid),
                "balance": _round_money(
                    _positive_number(invoice.total_amount) - paid
                ),
                "issued_date": invoice.issued_date,
                "due_date": invoice.due_date,
                "payments": [
                    {
                        "amount": _round_money(_positive_number(p.amount)),
                        "method": p.method,
                        "reference": p.reference,
                        "payment_date": p.payment_date,
                    }
                    for p in payments
                ],
            }
        )

    return {
        "policy_number": policy.policy_number,
        "status": policy.status,
        "start_date": policy.start_date,
        "end_date": policy.end_date,
        "premium": _round_money(_positive_number(policy.premium)),
        "product_name": product.name if product else "—",
        "organization_name": organization.name if organization else None,
        "policyholder_name": policyholder.name if policyholder else "—",
        "policyholder_email": policyholder.email if policyholder else None,
        "invoices": statement_invoices,
        "total_invoiced": _round_money(total_invoiced),
        "total_paid": _round_money(total_paid),
        "balance_outstanding": _round_money(total_invoiced - total_paid),
        "as_of": dt.datetime.now(dt.timezone.utc),
    }


def _fmt_money(value) -> str:
    return MONEY_FORMAT.format(_round_money(_positive_number(value)))


def _fmt_date(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, dt.datetime):
        return value.strftime("%b %d, %Y")
    return value.strftime("%b %d, %Y")


def fmt_as_of(value) -> str:
    """Format the ``as_of`` timestamp the statement was built against."""
    if value is None:
        return "—"
    if isinstance(value, dt.datetime):
        return value.strftime("%b %d, %Y at %H:%M UTC")
    return str(value)


def _kv_table(rows) -> Table:
    """A two-column key/value table (label left-aligned, value right)."""
    table = Table(rows, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f8f8f8")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


def render_statement_pdf(stmt: dict) -> bytes:
    """Render one policy's reconciliation statement as an in-memory PDF.

    Single pass over the statement dict produced by :func:`build_statement`,
    so the PDF and the HTML preview always agree on the numbers. Returns the
    encoded bytes (no file written to disk). Raises ``ValueError`` for a
    malformed statement (e.g. unknown policy_id, already raised by the builder).
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=0.85 * inch,
        rightMargin=0.85 * inch,
        topMargin=0.7 * inch,
        bottomMargin=0.7 * inch,
        title=f"Statement {stmt['policy_number']}",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "StatementTitle", parent=styles["Title"], spaceAfter=4
    )
    meta_style = ParagraphStyle(
        "StatementMeta",
        parent=styles["Normal"],
        fontSize=8,
        textColor=colors.HexColor("#555555"),
        spaceAfter=10,
    )
    heading_style = ParagraphStyle(
        "SectionHeading",
        parent=styles["Heading2"],
        fontSize=11,
        spaceBefore=12,
        spaceAfter=6,
    )
    cell_style = ParagraphStyle(
        "Cell", parent=styles["Normal"], fontSize=8.5, leading=10
    )
    right_cell = ParagraphStyle(
        "RightCell", parent=cell_style, alignment=1
    )

    def _status_tag(status: str) -> str:
        return f"<b>{status}</b>"

    as_of = fmt_as_of(stmt["as_of"])

    flowables = [
        Paragraph(f"Policy Statement: {stmt['policy_number']}", title_style),
        Paragraph(
            f"Generated {as_of} · Status {_status_tag(stmt['status'])}",
            meta_style,
        ),
        Spacer(1, 6),
        Paragraph("Policy", heading_style),
        _kv_table(
            [
                ("Product", stmt["product_name"]),
                ("Term", f"{_fmt_date(stmt['start_date'])} → {_fmt_date(stmt['end_date'])}"),
                ("Annual premium", _fmt_money(stmt["premium"])),
                ("Policyholder", stmt["policyholder_name"]),
            ],
        ),
        Spacer(1, 6),
        Paragraph("Policyholder", heading_style),
        _kv_table(
            [
                ("Name", stmt["policyholder_name"]),
                ("Email", stmt["policyholder_email"] or "—"),
            ],
        ),
        Spacer(1, 6),
    ]

    invoices = stmt["invoices"]
    if invoices:
        flowables.append(Paragraph("Invoices", heading_style))
        rows = [
            [
                Paragraph("Invoice", right_cell),
                Paragraph("Issued", right_cell),
                Paragraph("Due", right_cell),
                Paragraph("Billed", right_cell),
                Paragraph("Paid", right_cell),
                Paragraph("Balance", right_cell),
            ]
        ]
        for inv in invoices:
            rows.append(
                [
                    Paragraph(inv["invoice_number"], cell_style),
                    Paragraph(_fmt_date(inv["issued_date"]), cell_style),
                    Paragraph(_fmt_date(inv["due_date"]), cell_style),
                    Paragraph(_fmt_money(inv["total_amount"]), right_cell),
                    Paragraph(_fmt_money(inv["paid_amount"]), right_cell),
                    Paragraph(
                        _fmt_money(inv["balance"])
                        + f'<br/><font color="#c0392b">{inv["status"]}</font>',
                        right_cell,
                    ),
                ]
            )
        rows.append(
            [
                Paragraph("<b>Total</b>", cell_style),
                Paragraph("", cell_style),
                Paragraph("", cell_style),
                Paragraph(f"<b>{_fmt_money(stmt['total_invoiced'])}</b>", right_cell),
                Paragraph(f"<b>{_fmt_money(stmt['total_paid'])}</b>", right_cell),
                Paragraph(
                    f"<b>{_fmt_money(stmt['balance_outstanding'])}</b>", right_cell
                ),
            ]
        )
        table = Table(rows, hAlign="LEFT")
        table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f0f0")),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        flowables.append(table)
    else:
        flowables.append(Paragraph("No invoices have been issued.", cell_style))

    flowables.append(Spacer(1, 6))
    flowables.append(
        Paragraph(
            f"Total billed {_fmt_money(stmt['total_invoiced'])} · "
            f"Total paid {_fmt_money(stmt['total_paid'])} · "
            f"Outstanding {_fmt_money(stmt['balance_outstanding'])}",
            ParagraphStyle(
                "Totals", parent=styles["Normal"], fontSize=10, spaceBefore=4
            ),
        )
    )

    doc.build(flowables)
    return buffer.getvalue()
