"""Maturity calendar export: generates an iCalendar (.ics) file from a portfolio."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import icalendar

from justfixed.domain.investment import Investment
from justfixed.engine.projection import project


def export_maturity_calendar(
    investments: list[Investment],
    *,
    as_of: date,
    assumed_cdi: Decimal,
    assumed_ipca: Decimal | None = None,
) -> bytes:
    """Generate an iCalendar (.ics) file with one event per upcoming maturity.

    Investments whose maturity_date < as_of are excluded. The boundary case
    maturity_date == as_of is included (a maturity today is still relevant).

    Returns bytes; the caller writes to disk.
    """
    cal = icalendar.Calendar()
    cal.add("VERSION", "2.0")
    cal.add("PRODID", "-//JustFixed//maturity-calendar//PT-BR")
    cal.add("X-WR-CALNAME", "JustFixed: Vencimentos")

    now = datetime.now(tz=timezone.utc)

    for inv in investments:
        if inv.maturity_date < as_of:
            continue

        result = project(inv, as_of=as_of, assumed_cdi=assumed_cdi, assumed_ipca=assumed_ipca)
        net = result.net_at_maturity

        event = icalendar.Event()
        event.add("UID", f"justfixed-{inv.id}-maturity@justfixed")
        event.add("DTSTAMP", now)
        event.add("DTSTART", inv.maturity_date)
        event.add("DTEND", inv.maturity_date + timedelta(days=1))
        event.add("SUMMARY", f"{inv.issuer.name}: {net.to_display()}")
        desc_lines = [f"Emissor: {inv.issuer.name}"]
        if inv.custodian is not None:
            desc_lines.append(f"Custodiante: {inv.custodian}")
        desc_lines.append(f"Principal: {inv.principal.to_display()}")
        desc_lines.append(f"Líquido: {net.to_display()}")
        event.add("DESCRIPTION", "\n".join(desc_lines))

        cal.add_component(event)

    return cal.to_ical()
