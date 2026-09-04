"""Runtime objects shared by the SMHI Alerts platforms."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .fire_risk import SmhiFireRiskCoordinator
    from .sensor import SmhiAlertCoordinator
    from .thunder import SmhiThunderCoordinator


@dataclass(slots=True)
class SmhiAlertsRuntimeData:
    """Keep each entry's optional forecast separate from issued warnings."""

    warnings: SmhiAlertCoordinator
    fire_risk: SmhiFireRiskCoordinator | None
    fire_risk_settings: tuple[bool, float | None, float | None]
    thunder: SmhiThunderCoordinator | None = None
    thunder_settings: tuple[bool, float | None, float | None] = (False, None, None)
