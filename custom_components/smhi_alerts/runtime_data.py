"""Runtime objects shared by the SMHI Alerts platforms."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .fire_risk import SmhiFireRiskCoordinator
    from .mesan import SmhiMesanCoordinator
    from .precipitation import SmhiPrecipitationCoordinator
    from .sensor import SmhiAlertCoordinator
    from .snow_depth import SmhiSnowDepthCoordinator
    from .thunder import SmhiThunderCoordinator
    from .wind import SmhiWindCoordinator
    from .winter import SmhiWinterCoordinator


@dataclass(slots=True)
class SmhiAlertsRuntimeData:
    """Keep each entry's optional forecast separate from issued warnings."""

    warnings: SmhiAlertCoordinator
    fire_risk: SmhiFireRiskCoordinator | None
    fire_risk_settings: tuple[bool, float | None, float | None]
    thunder: SmhiThunderCoordinator | None = None
    thunder_settings: tuple[bool, float | None, float | None] = (False, None, None)
    winter: SmhiWinterCoordinator | None = None
    winter_settings: tuple[bool, float | None, float | None] = (False, None, None)
    snow_depth: SmhiSnowDepthCoordinator | None = None
    snow_depth_settings: tuple[bool, str | None, str | None] = (False, None, None)
    wind: SmhiWindCoordinator | None = None
    wind_settings: tuple[bool, float | None, float | None] = (False, None, None)
    precipitation: SmhiPrecipitationCoordinator | None = None
    precipitation_settings: tuple[bool, float | None, float | None] = (
        False,
        None,
        None,
    )
    analysis: SmhiMesanCoordinator | None = None
    analysis_settings: tuple[bool, float | None, float | None] = (False, None, None)
